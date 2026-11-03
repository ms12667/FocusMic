"""FocusMic desktop shell: Home, Performance, About, settings and theme."""
from __future__ import annotations

import logging
import platform
import threading

import cv2
import sounddevice as sd
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (
    QColor, QDesktopServices, QFont, QIcon, QImage, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton, QSlider, QSizePolicy,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from . import __version__
from .audio import LiveAudio, list_input_devices, resolve_input
from .charts import KpiCard, MetricCard
from .config import Settings, load_settings, save_settings
from .icons import IconButton, MorphIconButton, NavButton, render_icon
from .metrics import MetricsSampler
from .pagehost import PageHost
from .paths import ASSETS_DIR, icon_path, mediapipe_model
from .pipeline import NativePipeline
from .settings_dialog import SettingsDialog
from .startup import set_startup
from .theme import Theme, stylesheet, theme_for
from .video import MouthTracker

MEDIAPIPE_MODEL = mediapipe_model("face_landmarker.task")
ICON = icon_path()
BRAND_ICON = ASSETS_DIR / "icons" / "focusmic_icon_256.png"


class StatusChip(QLabel):
    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(28)
        self.setMinimumWidth(86)
        self.set_state("idle")

    def set_theme(self, theme):
        self._theme = theme
        self.set_state(self.property("state") or "idle")

    def set_state(self, state: str):
        self.setProperty("state", state)
        if state == "bypass":
            color, text = self._theme.accent, "● 直通"
        elif state == "running":
            color, text = self._theme.teal, "● 运行中"
        else:
            color, text = self._theme.muted, "● 待机"
        self.setText(text)
        self.setStyleSheet(
            f"QLabel{{color:{color};background:{self._theme.surface2};"
            f"border:1px solid {self._theme.border};border-radius:14px;"
            f"padding:0 12px;font-size:11px;font-weight:600;}}")


class InfoTile(QFrame):
    def __init__(self, label: str, unit: str, theme, parent=None):
        super().__init__(parent)
        self.setObjectName("SoftCard")
        self._theme = theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(1)
        self.label = QLabel(label)
        self.label.setObjectName("KpiLabel")
        self.value = QLabel(f"— {unit}")
        layout.addWidget(self.label)
        layout.addWidget(self.value)
        self.set_theme(theme)

    def set_theme(self, theme):
        self._theme = theme
        self.setStyleSheet(
            f"QFrame#SoftCard{{background:{theme.surface2};border:1px solid {theme.border};"
            f"border-radius:10px;}}")
        self.label.setStyleSheet(f"color:{theme.muted};font-size:10px;")
        self.value.setStyleSheet(
            f"font-family:'Cascadia Mono';font-size:18px;font-weight:600;color:{theme.text};")

    def set_value(self, value: str, unit: str = ""):
        self.value.setText(f"{value} {unit}")


def _muted(text: str, theme: Theme, size: int = 11) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color:{theme.muted};font-size:{size}px;")
    return label


def _card_title(text: str, theme: Theme) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color:{theme.text};font-size:14px;font-weight:600;")
    return label


class PreviewCanvas(QWidget):
    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._image = None
        self._box = None
        self.setMinimumSize(430, 248)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def set_frame(self, image: QImage, box=None):
        self._image = image
        self._box = box
        self.update()

    def clear(self):
        self._image = None
        self._box = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.setClipPath(path)
        if self._image is not None:
            painter.fillRect(rect, QColor("#080C11"))
            scaled = self._image.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = rect.x() + (rect.width() - scaled.width()) / 2
            y = rect.y() + (rect.height() - scaled.height()) / 2
            painter.drawImage(int(x), int(y), scaled)
            if self._box is not None:
                cx, cy, size = self._box
                side = size * min(scaled.width(), scaled.height())
                bx = x + cx * scaled.width() - side / 2
                by = y + cy * scaled.height() - side / 2
                pen = QPen(QColor(self._theme.teal), 2)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(QRectF(bx, by, side, side), 4, 4)
        else:
            grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
            grad.setColorAt(0, QColor("#0A1017"))
            grad.setColorAt(1, QColor("#070B10"))
            painter.fillRect(rect, grad)
            painter.setPen(QPen(QColor(255, 255, 255, 14), 1))
            step = 24
            for gx in range(0, self.width(), step):
                for gy in range(0, self.height(), step):
                    painter.drawPoint(gx, gy)
            # Focus brackets.
            cx, cy = self.width() / 2, self.height() / 2 - 28
            arm, gap = 18, 34
            pen = QPen(QColor(self._theme.accent), 1.4)
            painter.setPen(pen)
            for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                x0, y0 = cx + sx * gap, cy + sy * gap
                painter.drawLine(QPointF(x0, y0), QPointF(x0 - sx * arm, y0))
                painter.drawLine(QPointF(x0, y0), QPointF(x0, y0 - sy * arm))
            pix = render_icon("video", self._theme.muted, 30)
            painter.drawPixmap(QPointF(cx - pix.width() / pix.devicePixelRatio() / 2,
                                       cy - pix.height() / pix.devicePixelRatio() / 2 + 44), pix)
            painter.setPen(QColor(self._theme.muted))
            font = QFont("Microsoft YaHei UI", 11)
            painter.setFont(font)
            painter.drawText(QRectF(0, cy + 86, self.width(), 22),
                             Qt.AlignHCenter | Qt.AlignTop, "摄像头未开启")
            painter.setPen(QColor(self._theme.faint))
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(QRectF(0, cy + 108, self.width(), 20),
                             Qt.AlignHCenter | Qt.AlignTop, "点击「开始分离」后预览")
        painter.end()




class MainWindow(QMainWindow):
    log_signal = Signal(str)
    hotkey_signal = Signal()

    def __init__(self):
        super().__init__()
        self.settings: Settings = load_settings()
        self.theme: Theme = theme_for(self.settings.theme_mode, self._system_dark())
        self.pipeline = None
        self.tracker = None
        self.worker = None
        self.mic_devices = []
        self.metrics = MetricsSampler()
        self._last_bypass = False
        self._hotkey_handle = None
        self._keyboard = None
        self._tray = None
        self._page = 0

        self.setWindowTitle("FocusMic")
        self.setWindowIcon(QIcon(str(ICON)))
        width, height = self.settings.window_width, self.settings.window_height
        if height < 760 or not (1.20 <= width / max(height, 1) <= 1.50):
            width, height = 1080, 810
        self.settings.window_width, self.settings.window_height = width, height
        self.resize(width, height)
        self.setMinimumSize(960, 720)
        self._build()
        self._apply_theme()
        self.log_signal.connect(self._append_activity)
        self.hotkey_signal.connect(self._hotkey_bypass)
        self._register_hotkey()
        self._setup_tray()
        QApplication.instance().styleHints().colorSchemeChanged.connect(self._system_dark_changed)

        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(50)
        self.preview_timer.timeout.connect(self._refresh_preview)
        self.preview_timer.start()
        self.metrics_timer = QTimer(self)
        self.metrics_timer.setInterval(600)
        self.metrics_timer.timeout.connect(self._refresh_metrics)
        self.metrics_timer.start()
        self._refresh_metrics()

    @staticmethod
    def _system_dark() -> bool:
        return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark

    def _build(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(208)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 18, 14, 16)
        side.setSpacing(5)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        icon = QLabel()
        pix = QPixmap(str(BRAND_ICON))
        if not pix.isNull():
            icon.setPixmap(pix.scaled(38, 38, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand.addWidget(icon)
        names = QVBoxLayout()
        names.setSpacing(0)
        name = QLabel("FocusMic")
        name.setStyleSheet("font-size:17px;font-weight:600;")
        local = QLabel("本地 · 私有")
        local.setStyleSheet(f"color:{self.theme.muted};font-size:10px;")
        names.addWidget(name)
        names.addWidget(local)
        brand.addLayout(names)
        brand.addStretch(1)
        side.addLayout(brand)
        side.addSpacing(22)

        self.nav_buttons = []
        for index, (icon_name, text) in enumerate((
                ("house", "主页"), ("chart-line", "性能信息"), ("info", "关于 FocusMic"))):
            button = NavButton(icon_name, text, self.theme)
            button.clicked.connect(lambda _=False, i=index: self.show_page(i))
            self.nav_buttons.append(button)
            side.addWidget(button)
        side.addStretch(1)

        tools = QHBoxLayout()
        tools.setSpacing(4)
        self.theme_button = MorphIconButton("moon", "sun", self.theme, size=18)
        self.theme_button.setToolTip("切换深色 / 浅色")
        self.theme_button.setChecked(self.theme.dark)
        self.theme_button._progress = 1.0 if self.theme.dark else 0.0
        self.theme_button.toggled.connect(self._toggle_theme)
        self.settings_button = IconButton("settings", self.theme, size=18, tip="设置")
        self.settings_button.clicked.connect(self._open_settings)
        tools.addWidget(self.theme_button)
        tools.addWidget(self.settings_button)
        tools.addStretch(1)
        side.addLayout(tools)
        version = QLabel(f"v{__version__} · Windows")
        version.setStyleSheet(f"color:{self.theme.faint};font-size:9px;padding:4px 6px;")
        side.addWidget(version)
        outer.addWidget(sidebar)
        self.nav_buttons[0].set_active(True)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(26, 20, 26, 20)
        content_layout.setSpacing(12)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.page_title = QLabel("主页")
        self.page_title.setObjectName("PageTitle")
        self.page_subtitle = QLabel("实时分离与快速设置")
        self.page_subtitle.setObjectName("PageSubtitle")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.status_chip = StatusChip(self.theme)
        header.addWidget(self.status_chip)
        content_layout.addLayout(header)

        self.page_host = PageHost()
        self.home_page = self._build_home()
        self.performance_page = self._build_performance()
        self.about_page = self._build_about()
        for page in (self.home_page, self.performance_page, self.about_page):
            self.page_host.add_page(page)
        content_layout.addWidget(self.page_host, 1)
        outer.addWidget(content, 1)

    def _build_home(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(12)

        preview_card = QFrame()
        preview_card.setObjectName("Card")
        pv = QVBoxLayout(preview_card)
        pv.setContentsMargins(12, 11, 12, 12)
        pv.setSpacing(8)
        pv_head = QHBoxLayout()
        pv_head.addWidget(_card_title("实时预览", self.theme))
        pv_head.addStretch(1)
        self.preview_state = QLabel("摄像头未开启")
        self.preview_state.setStyleSheet(f"color:{self.theme.muted};font-size:10px;")
        pv_head.addWidget(self.preview_state)
        pv.addLayout(pv_head)
        self.preview_label = PreviewCanvas(self.theme)
        pv.addWidget(self.preview_label, 1)
        left.addWidget(preview_card, 1)

        stats = QHBoxLayout()
        stats.setSpacing(8)
        self.tile_infer = InfoTile("推理延迟", "ms", self.theme)
        self.tile_lag = InfoTile("音频滞后", "s", self.theme)
        self.tile_track = InfoTile("目标跟踪", "%", self.theme)
        for tile in (self.tile_infer, self.tile_lag, self.tile_track):
            stats.addWidget(tile, 1)
        left.addLayout(stats)
        top.addLayout(left, 3)

        controls = QFrame()
        controls.setObjectName("Card")
        form = QVBoxLayout(controls)
        form.setContentsMargins(15, 13, 15, 13)
        form.setSpacing(7)
        form.addWidget(_card_title("快速设置", self.theme))
        form.addWidget(_muted("设备与音画参数", self.theme, 10))

        self.mic = QComboBox()
        self.mic_devices = list_input_devices(sd)
        for d in self.mic_devices:
            self.mic.addItem(f"{d['name']}  ·  {d['hostapi']}", d["index"])
        try:
            default_idx, _ = resolve_input(sd, None)
            pos = self.mic.findData(default_idx)
            if pos >= 0:
                self.mic.setCurrentIndex(pos)
        except Exception:
            pass
        self.camera = QComboBox()
        for i in range(6):
            self.camera.addItem(f"摄像头 {i}", i)
        self.model = QComboBox()
        self.model.addItem("Falcon Small · 推荐", "small")
        self.model.addItem("Falcon Big · 质量", "big")
        form.addWidget(_muted("麦克风", self.theme, 10))
        form.addWidget(self.mic)
        form.addWidget(_muted("摄像头", self.theme, 10))
        form.addWidget(self.camera)
        form.addWidget(_muted("模型", self.theme, 10))
        form.addWidget(self.model)

        self.monitor = QCheckBox("耳机实时监听")
        form.addWidget(self.monitor)

        av_row = QHBoxLayout()
        av_row.setSpacing(7)
        av_row.addWidget(_muted("音画同步", self.theme, 10))
        self.av = QSlider(Qt.Horizontal)
        self.av.setRange(-250, 250)
        self.av.setSingleStep(10)
        self.av_value = QLabel(f"{self.settings.av_offset_ms} ms")
        self.av_value.setStyleSheet(
            f"font-family:'Cascadia Mono';font-size:10px;color:{self.theme.muted};")
        self.av.valueChanged.connect(lambda v: self.av_value.setText(f"{v} ms"))
        av_row.addWidget(self.av, 1)
        av_row.addWidget(self.av_value)
        form.addLayout(av_row)

        form.addSpacing(4)
        run_row = QHBoxLayout()
        run_row.setSpacing(7)
        self.start_btn = QPushButton("开始分离")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("ghost")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        run_row.addWidget(self.start_btn, 2)
        run_row.addWidget(self.stop_btn, 1)
        form.addLayout(run_row)

        tools_row = QHBoxLayout()
        tools_row.setSpacing(7)
        self.reacquire_btn = QPushButton("重新锁定")
        self.reacquire_btn.setEnabled(False)
        self.reacquire_btn.clicked.connect(self.reacquire)
        self.bypass_btn = QPushButton("旁路：关")
        self.bypass_btn.setCheckable(True)
        self.bypass_btn.setEnabled(False)
        self.bypass_btn.toggled.connect(self.toggle_bypass)
        tools_row.addWidget(self.reacquire_btn)
        tools_row.addWidget(self.bypass_btn)
        form.addLayout(tools_row)

        form.addSpacing(5)
        self.cable_label = QLabel("CABLE Input · 未连接")
        self.cable_label.setWordWrap(True)
        self.cable_label.setStyleSheet(f"color:{self.theme.muted};font-size:10px;")
        form.addWidget(self.cable_label)
        form.addStretch(1)
        self.activity = _muted("就绪。点击开始分离。", self.theme, 10)
        form.addWidget(self.activity)
        top.addWidget(controls, 2)
        layout.addLayout(top, 1)
        self._apply_home_settings()
        return page

    def _build_performance(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        kpis = QHBoxLayout()
        kpis.setSpacing(8)
        self.kpi_infer = KpiCard("推理延迟", "—", "ms", self.theme)
        self.kpi_cpu = KpiCard("CPU", "—", "%", self.theme)
        self.kpi_gpu = KpiCard("GPU", "—", "%", self.theme, accent=self.theme.accent)
        self.kpi_vram = KpiCard("显存", "—", "MB", self.theme)
        for card in (self.kpi_infer, self.kpi_cpu, self.kpi_gpu, self.kpi_vram):
            kpis.addWidget(card, 1)
        layout.addLayout(kpis)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.chart_infer = MetricCard("推理延迟", "ms", self.theme.blue, self.theme)
        self.chart_cpu = MetricCard("系统 CPU", "%", self.theme.teal, self.theme, fixed_max=100)
        self.chart_gpu = MetricCard("GPU 使用率", "%", self.theme.accent, self.theme, fixed_max=100)
        self.chart_vram = MetricCard("显存占用", "MB", self.theme.red, self.theme)
        for i, card in enumerate((self.chart_infer, self.chart_cpu, self.chart_gpu, self.chart_vram)):
            grid.addWidget(card, i // 2, i % 2)
        layout.addLayout(grid, 1)
        self.perf_note = _muted("采样间隔 0.6 s · 最近约 30 s · GPU 数据来自 NVML", self.theme, 10)
        layout.addWidget(self.perf_note)
        return page

    def _build_about(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        brand = QFrame()
        brand.setObjectName("Card")
        brand.setFixedWidth(300)
        box = QVBoxLayout(brand)
        box.setContentsMargins(20, 22, 20, 20)
        box.setSpacing(8)
        icon = QLabel()
        pix = QPixmap(str(BRAND_ICON))
        if not pix.isNull():
            icon.setPixmap(pix.scaled(92, 92, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        box.addWidget(icon)
        name = QLabel("FocusMic")
        name.setStyleSheet("font-size:25px;font-weight:600;")
        box.addWidget(name)
        box.addWidget(_muted(f"版本 {__version__}", self.theme, 11))
        box.addSpacing(8)
        box.addWidget(_muted("把镜头里的你，从房间的声音里留下来。", self.theme, 12))
        box.addSpacing(8)
        privacy = QLabel("● 本地推理\n● 摄像头与麦克风不上传\n● 无遥测")
        privacy.setStyleSheet(f"color:{self.theme.teal};font-size:11px;")
        box.addWidget(privacy)
        box.addStretch(1)
        box.addWidget(_muted("Windows 10/11 · NVIDIA GPU", self.theme, 10))
        layout.addWidget(brand)

        right = QVBoxLayout()
        right.setSpacing(12)
        dev = QFrame()
        dev.setObjectName("Card")
        dev_box = QVBoxLayout(dev)
        dev_box.setContentsMargins(16, 13, 16, 13)
        dev_box.setSpacing(5)
        dev_box.addWidget(_card_title("开发者", self.theme))
        dev_box.addWidget(_muted("ms12667", self.theme, 12))
        link = QLabel('<a style="color:%s" href="https://github.com/ms12667/FocusMic">'
                     'github.com/ms12667/FocusMic</a>' % self.theme.blue)
        link.setOpenExternalLinks(True)
        link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        dev_box.addWidget(link)
        right.addWidget(dev)

        lic = QFrame()
        lic.setObjectName("Card")
        lic_box = QVBoxLayout(lic)
        lic_box.setContentsMargins(16, 13, 16, 13)
        lic_box.setSpacing(5)
        lic_box.addWidget(_card_title("许可证与致谢", self.theme))
        lic_box.addWidget(_muted(
            "FocusMic  Apache-2.0\n"
            "Falcon  Apache-2.0（JusperLee）\n"
            "MediaPipe  Apache-2.0\n"
            "Lucide icons  ISC\n"
            "Simple Icons  CC0\n"
            "PySide6  LGPL-3.0\n"
            "VB-CABLE  独立捐赠软件，不随本应用分发", self.theme, 11))
        right.addWidget(lic)

        build = QFrame()
        build.setObjectName("Card")
        build_box = QVBoxLayout(build)
        build_box.setContentsMargins(16, 13, 16, 13)
        build_box.setSpacing(5)
        build_box.addWidget(_card_title("构建信息", self.theme))
        try:
            import torch
            torch_version = torch.__version__
            cuda = "CUDA 可用" if torch.cuda.is_available() else "CPU"
        except Exception:
            torch_version, cuda = "—", "—"
        build_box.addWidget(_muted(
            f"Python {platform.python_version()} · PySide6 {self._pyside_version()}\n"
            f"PyTorch {torch_version} · {cuda}", self.theme, 10))
        right.addWidget(build)
        right.addStretch(1)
        layout.addLayout(right, 1)
        return page

    @staticmethod
    def _pyside_version() -> str:
        try:
            import PySide6
            return PySide6.__version__
        except Exception:
            return "—"

    def _apply_home_settings(self):
        if self.settings.mic_name:
            for i, d in enumerate(self.mic_devices):
                if d["name"] == self.settings.mic_name:
                    self.mic.setCurrentIndex(i)
                    break
        pos = self.camera.findData(self.settings.camera)
        if pos >= 0:
            self.camera.setCurrentIndex(pos)
        pos = self.model.findData(self.settings.variant)
        if pos >= 0:
            self.model.setCurrentIndex(pos)
        self.av.setValue(self.settings.av_offset_ms)
        self.monitor.setChecked(self.settings.monitor)
        self.av_value.setText(f"{self.av.value()} ms")

    def show_page(self, index: int):
        if index == self._page:
            return
        self._page = index
        for i, button in enumerate(self.nav_buttons):
            button.set_active(i == index)
        titles = (
            ("主页", "实时分离与快速设置"),
            ("性能信息", "推理、系统与显存占用"),
            ("关于 FocusMic", "版本、开发者与许可证"),
        )
        self.page_title.setText(titles[index][0])
        self.page_subtitle.setText(titles[index][1])
        self.page_host.set_current(index, animate=True)

    def _append_activity(self, text: str):
        self.activity.setText(text)
        logging.getLogger("focusmic").info(text)

    def _set_controls_running(self, running: bool):
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.reacquire_btn.setEnabled(running)
        self.bypass_btn.setEnabled(running)
        for widget in (self.mic, self.camera, self.model, self.av, self.monitor):
            widget.setEnabled(not running)
        if not running:
            if self.bypass_btn.isChecked():
                self.bypass_btn.setChecked(False)
            self.bypass_btn.setText("旁路：关")

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        mic_idx = self.mic.currentData()
        camera = self.camera.currentData()
        variant = self.model.currentData()
        av = self.av.value()
        monitor = self.monitor.isChecked()
        self._store_settings()
        try:
            audio = LiveAudio(mic_idx)
            self.tracker = MouthTracker(int(camera), model_path=MEDIAPIPE_MODEL)
        except Exception as exc:
            self.log_signal.emit(f"设备初始化失败：{exc}")
            return
        self.pipeline = NativePipeline(
            audio, self.tracker, variant=variant, av_offset_ms=av,
            gain_db=self.settings.gain_db, output=True, monitor=monitor,
        )
        self._set_controls_running(True)
        self.activity.setText("正在加载 Falcon 模型…")
        self.preview_state.setText("正在启动")
        self.log_signal.emit(f"启动：{self.mic.currentText()} / 摄像头 {camera} / {variant} / AV {av} ms")
        self.worker = threading.Thread(target=self._run, daemon=True, name="pipeline")
        self.worker.start()

    def _run(self):
        try:
            self.pipeline.load("cuda")
            self.log_signal.emit("模型就绪，正在分离。")
            self.pipeline.run()
        except Exception as exc:
            self.log_signal.emit(f"运行失败：{exc}")
        finally:
            self.log_signal.emit("已停止。")

    def stop(self):
        if self.pipeline is not None:
            self.pipeline.stop()
        if self.worker is not None and self.worker.is_alive():
            self.worker.join(timeout=3.0)
        if self.tracker is not None:
            self.tracker.stop()
        self.pipeline = None
        self.tracker = None
        self.worker = None
        self.preview_label.clear()
        self.preview_state.setText("摄像头未开启")
        self.cable_label.setText("CABLE Input · 未连接")
        self.status_chip.set_state("idle")
        self._set_controls_running(False)
        self._last_bypass = False

    def reacquire(self):
        if self.tracker is not None:
            self.tracker.reset_target()
            self.log_signal.emit("已清除目标，下一帧重新选择人脸。")

    def toggle_bypass(self, checked: bool):
        if self.pipeline is not None:
            self.pipeline.manual_bypass = bool(checked)
        self.bypass_btn.setText("旁路：开" if checked else "旁路：关")
        self.log_signal.emit("手动旁路：" + ("开（原始麦克风）" if checked else "关（Falcon）"))

    def _hotkey_bypass(self):
        if self.pipeline is not None and self.worker is not None and self.worker.is_alive():
            self.bypass_btn.setChecked(not self.bypass_btn.isChecked())

    def _store_settings(self):
        idx = self.mic.currentData()
        for d in self.mic_devices:
            if d["index"] == idx:
                self.settings.mic_name = d["name"]
                break
        self.settings.camera = int(self.camera.currentData())
        self.settings.variant = self.model.currentData()
        self.settings.av_offset_ms = self.av.value()
        self.settings.monitor = self.monitor.isChecked()
        self.settings.window_width = self.width()
        self.settings.window_height = self.height()
        try:
            save_settings(self.settings)
        except OSError as exc:
            logging.getLogger("focusmic").warning("save settings failed: %s", exc)

    def _refresh_preview(self):
        if self.tracker is None:
            return
        frame, box = self.tracker.preview_frame()
        if frame is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        image = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self.preview_label.set_frame(image, box)
        self.preview_state.setText("● 跟踪中" if (self.pipeline and not self.pipeline.bypass) else "● 预览")

    def _refresh_metrics(self):
        sample = self.metrics.sample()
        running = bool(self.pipeline and self.worker and self.worker.is_alive())
        status = self.pipeline.status() if self.pipeline is not None else None
        infer = float(status["infer_ms"]) if status else 0.0
        lag = float(status["audio_lag"]) if status else 0.0
        tracked = float(status["tracked"]) if status else 0.0
        bypass = bool(status and status.get("bypass"))
        cable = status["cable"] if status else {"active": False}
        self.chart_infer.push(infer if running else 0)
        self.chart_cpu.push(sample["cpu"])
        self.chart_gpu.push(sample["gpu"])
        self.chart_vram.push(sample["vram"])
        self.kpi_infer.set_value(f"{infer:.0f}" if running else "—", "ms")
        self.kpi_cpu.set_value(f"{sample['cpu']:.0f}", "%")
        self.kpi_gpu.set_value(f"{sample['gpu']:.0f}", "%")
        self.kpi_vram.set_value(f"{sample['vram']:.0f}", "MB")
        self.tile_infer.set_value(f"{infer:.0f}" if running else "—", "ms")
        self.tile_lag.set_value(f"{lag:.2f}" if running else "—", "s")
        self.tile_track.set_value(f"{tracked*100:.0f}" if running else "—", "%")
        if running:
            self.status_chip.set_state("bypass" if bypass else "running")
            if cable.get("active"):
                self.cable_label.setText(f"● CABLE Input · 已连接\n{cable.get('device', '')}")
                self.cable_label.setStyleSheet(f"color:{self.theme.teal};font-size:10px;")
            else:
                self.cable_label.setText("● CABLE Input · 未连接")
                self.cable_label.setStyleSheet(f"color:{self.theme.red};font-size:10px;")
        else:
            self.status_chip.set_state("idle")
        if bypass != self._last_bypass and running:
            if bypass:
                reason = "手动旁路" if status.get("manual_bypass") else "视觉丢失"
                self.log_signal.emit(f"{reason}：已切换为原始麦克风直通")
            else:
                self.log_signal.emit("已恢复 Falcon 分离输出")
            self._last_bypass = bypass
        if not running and self.worker is not None and not self.worker.is_alive():
            self._set_controls_running(False)
            self.worker = None
            self.pipeline = None
            if self.tracker is not None:
                self.tracker.stop()
                self.tracker = None
            self.preview_label.clear()
            self.preview_state.setText("摄像头未开启")
            self.status_chip.set_state("idle")

    def _open_settings(self):
        dialog = SettingsDialog(self.settings, self.theme, self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            set_startup(self.settings.start_with_windows)
        except Exception as exc:
            self.log_signal.emit(f"开机启动设置失败：{exc}")
        try:
            save_settings(self.settings)
        except OSError as exc:
            self.log_signal.emit(f"设置保存失败：{exc}")
        self._apply_theme()
        self._register_hotkey()
        self.activity.setText("设置已保存。输出增益将在下次开始时生效。")

    def _toggle_theme(self, checked: bool):
        self.settings.theme_mode = "dark" if checked else "light"
        self.theme = theme_for(self.settings.theme_mode, self._system_dark())
        self._apply_theme()
        try:
            save_settings(self.settings)
        except OSError:
            pass

    def _system_dark_changed(self, *args):
        if self.settings.theme_mode == "system":
            self.theme = theme_for("system", self._system_dark())
            self._apply_theme()

    def _apply_theme(self):
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet(self.theme))
        self.theme_button.blockSignals(True)
        self.theme_button.setChecked(self.theme.dark)
        if self.theme_button._anim.state() != QVariantAnimation.Running:
            self.theme_button._progress = 1.0 if self.theme.dark else 0.0
        self.theme_button.update()
        self.theme_button.blockSignals(False)
        for button in self.nav_buttons:
            button.set_theme(self.theme)
        for widget in self.findChildren(QWidget):
            if hasattr(widget, "set_theme"):
                try:
                    widget.set_theme(self.theme)
                except Exception:
                    pass
        self.status_chip.set_theme(self.theme)
        self.activity.setStyleSheet(f"color:{self.theme.muted};font-size:10px;")


    def _setup_tray(self):
        try:
            self._tray = QSystemTrayIcon(QIcon(str(ICON)), self)
            menu = QMenu()
            self._tray_menu = menu
            show = menu.addAction("显示 / 隐藏")
            show.triggered.connect(lambda: self.hide() if self.isVisible() else self.showNormal())
            start = menu.addAction("开始分离")
            start.triggered.connect(self.start)
            stop = menu.addAction("停止")
            stop.triggered.connect(self.stop)
            bypass = menu.addAction("切换旁路")
            bypass.triggered.connect(self.bypass_btn.toggle)
            settings = menu.addAction("设置")
            settings.triggered.connect(self._open_settings)
            menu.addSeparator()
            quit_action = menu.addAction("退出")
            quit_action.triggered.connect(self.close)
            self._tray.setContextMenu(menu)
            self._tray.setToolTip("FocusMic")
            self._tray.activated.connect(
                lambda reason: self.showNormal() if reason == QSystemTrayIcon.DoubleClick else None)
            self._tray.show()
        except Exception as exc:
            logging.getLogger("focusmic").warning("tray unavailable: %s", exc)
            self._tray = None

    def _register_hotkey(self):
        if self._hotkey_handle is not None and self._keyboard is not None:
            try:
                self._keyboard.remove_hotkey(self._hotkey_handle)
            except Exception:
                pass
            self._hotkey_handle = None
        if not self.settings.hotkey_enabled:
            return
        try:
            import keyboard
            self._keyboard = keyboard
            self._hotkey_handle = keyboard.add_hotkey(self.settings.hotkey, self.hotkey_signal.emit)
            logging.getLogger("focusmic").info("hotkey registered: %s", self.settings.hotkey)
        except Exception as exc:
            self._hotkey_handle = None
            logging.getLogger("focusmic").warning("hotkey unavailable: %s", exc)

    def closeEvent(self, event):
        self.stop()
        self._store_settings()
        if self._hotkey_handle is not None and self._keyboard is not None:
            try:
                self._keyboard.remove_hotkey(self._hotkey_handle)
            except Exception:
                pass
        if self._tray is not None:
            self._tray.hide()
        self.metrics.close()
        event.accept()
