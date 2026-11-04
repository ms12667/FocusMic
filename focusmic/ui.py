"""FocusMic desktop shell: Home, Performance, About, settings and theme."""
from __future__ import annotations

import logging
import platform
import threading
import time
from importlib import metadata

import cv2
import sounddevice as sd
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (
    QColor, QFont, QIcon, QImage, QKeySequence, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QKeySequenceEdit,
    QLabel, QMainWindow, QPlainTextEdit, QPushButton, QScrollArea, QSlider,
    QSizePolicy, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from . import __version__
from . import runtime as runtime_env
from .audio import LiveAudio, list_input_devices, resolve_input
from .charts import KpiCard, MetricCard
from .config import Settings, load_settings, save_settings
from .controls import LinkLabel, SettingRow, ThemedLabel, ToggleSwitch
from .icons import MorphIconButton, NavButton, render_icon
from .metrics import MetricsSampler
from .onboarding import OnboardingDialog
from .pagehost import PageHost
from .paths import ASSETS_DIR, icon_path, mediapipe_model
from .pipeline import NativePipeline
from .report import SpectrumCompare, WaveformCompare
from .runtime_dialog import RuntimeDialog
from .startup import set_startup
from .theme import Theme, stylesheet, theme_for
from .tray import show_native_menu
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
        elif state == "stopping":
            color, text = self._theme.accent, "● 正在停止"
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


def _muted(text: str, theme: Theme, size: int = 11) -> ThemedLabel:
    return ThemedLabel(text, theme, role="muted", size=size, wrap=True)


def _card_title(text: str, theme: Theme) -> ThemedLabel:
    return ThemedLabel(text, theme, role="text", size=14, weight=600)


def _hotkey_display(value: str) -> str:
    parts = [p.strip() for p in value.replace(" ", "").split("+") if p.strip()]
    return "+".join(p[:1].upper() + p[1:] for p in parts) or "Ctrl+Alt+M"


def _package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except Exception:
        return "—"


class PreviewCanvas(QWidget):
    """Portrait camera preview with an optional manual target selection box."""

    roi_selected = Signal(float, float, float, float)

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._image = None
        self._box = None
        self._image_rect = QRectF()
        self._selecting = False
        self._select_start = None
        self._select_rect = None
        self.setMinimumSize(280, 360)
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
        self._image_rect = QRectF()
        self._select_start = None
        self._select_rect = None
        self._selecting = False
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def set_selecting(self, active: bool):
        self._selecting = bool(active)
        self._select_start = None
        self._select_rect = None
        self.setCursor(Qt.CrossCursor if self._selecting else Qt.ArrowCursor)
        self.update()

    def _clamp_point(self, point: QPointF):
        rect = self._image_rect
        if rect.isEmpty():
            return None
        return QPointF(
            min(max(point.x(), rect.left()), rect.right()),
            min(max(point.y(), rect.top()), rect.bottom()))

    def mousePressEvent(self, event):
        if not self._selecting or event.button() != Qt.LeftButton:
            return
        point = self._clamp_point(event.position())
        if point is None:
            return
        self._select_start = point
        self._select_rect = QRectF(point, point)
        self.update()

    def mouseMoveEvent(self, event):
        if self._select_start is None:
            return
        point = self._clamp_point(event.position())
        if point is None:
            return
        self._select_rect = QRectF(self._select_start, point).normalized()
        self.update()

    def mouseReleaseEvent(self, event):
        if self._select_start is None:
            return
        point = self._clamp_point(event.position()) or self._select_start
        rect = QRectF(self._select_start, point).normalized()
        self._select_start = None
        self._selecting = False
        self.setCursor(Qt.ArrowCursor)
        image_rect = self._image_rect
        self._select_rect = None
        self.update()
        if rect.width() < 12 or rect.height() < 12 or image_rect.isEmpty():
            return
        x0 = (rect.left() - image_rect.left()) / image_rect.width()
        y0 = (rect.top() - image_rect.top()) / image_rect.height()
        x1 = (rect.right() - image_rect.left()) / image_rect.width()
        y1 = (rect.bottom() - image_rect.top()) / image_rect.height()
        self.roi_selected.emit(
            max(0.0, min(1.0, x0)), max(0.0, min(1.0, y0)),
            max(0.0, min(1.0, x1)), max(0.0, min(1.0, y1)))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 9, 9)
        painter.setClipPath(path)
        if self._image is not None:
            painter.fillRect(rect, QColor(self._theme.bg))
            scaled = self._image.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = rect.x() + (rect.width() - scaled.width()) / 2
            y = rect.y() + (rect.height() - scaled.height()) / 2
            painter.drawImage(int(x), int(y), scaled)
            self._image_rect = QRectF(x, y, scaled.width(), scaled.height())
            if self._box is not None:
                cx, cy, size = self._box
                side = size * min(scaled.width(), scaled.height())
                bx = x + cx * scaled.width() - side / 2
                by = y + cy * scaled.height() - side / 2
                color = QColor(self._theme.teal)
                color.setAlpha(210)
                painter.setPen(QPen(color, 1.6))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(QRectF(bx, by, side, side), 6, 6)
        else:
            self._image_rect = QRectF()
            grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
            grad.setColorAt(0, QColor(self._theme.surface2))
            grad.setColorAt(1, QColor(self._theme.bg))
            painter.fillRect(rect, grad)
            dot = QColor(self._theme.border)
            dot.setAlpha(150)
            painter.setPen(QPen(dot, 1))
            step = 24
            for gx in range(0, self.width(), step):
                for gy in range(0, self.height(), step):
                    painter.drawPoint(gx, gy)
            cx = self.width() / 2
            cy = self.height() / 2 - 34
            painter.setPen(QPen(QColor(self._theme.border), 1))
            painter.setBrush(QColor(self._theme.surface))
            painter.drawEllipse(QPointF(cx, cy), 34, 34)
            pix = render_icon("video", self._theme.muted, 28)
            painter.drawPixmap(
                QPointF(cx - pix.width() / pix.devicePixelRatio() / 2,
                        cy - pix.height() / pix.devicePixelRatio() / 2), pix)
            painter.setPen(QColor(self._theme.text))
            font = QFont("Microsoft YaHei UI", 11)
            font.setWeight(QFont.Weight.Medium)
            painter.setFont(font)
            painter.drawText(QRectF(0, cy + 50, self.width(), 24),
                             Qt.AlignHCenter | Qt.AlignTop, "摄像头未开启")
            painter.setPen(QColor(self._theme.faint))
            font.setPointSize(9)
            font.setWeight(QFont.Weight.Normal)
            painter.setFont(font)
            painter.drawText(QRectF(0, cy + 74, self.width(), 22),
                             Qt.AlignHCenter | Qt.AlignTop, "点击「开始分离」后显示预览")
        if self._selecting:
            painter.setPen(QColor(self._theme.accent))
            painter.setFont(QFont("Microsoft YaHei UI", 9))
            painter.drawText(QRectF(0, 8, self.width(), 20),
                             Qt.AlignHCenter | Qt.AlignTop,
                             "拖动框住你的脸，松开后锁定")
        if self._select_rect is not None:
            fill = QColor(self._theme.accent)
            fill.setAlpha(38)
            painter.setPen(QPen(QColor(self._theme.accent), 1.6, Qt.DashLine))
            painter.setBrush(fill)
            painter.drawRoundedRect(self._select_rect, 5, 5)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(self._theme.border), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 9, 9)
        painter.end()




class MainWindow(QMainWindow):
    log_signal = Signal(str)
    hotkey_signal = Signal()
    stop_done = Signal(bool)

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
        self._stopping = False
        self.report_snapshot = None
        self._onboarding_open = False
        self._last_monitor_error = None
        self._really_quit = False
        self._tray_notice_shown = False

        self.setWindowTitle("FocusMic")
        self.setWindowIcon(QIcon(str(ICON)))
        width, height = self.settings.window_width, self.settings.window_height
        if height < 760 or not (1.20 <= width / max(height, 1) <= 1.50):
            width, height = 1080, 810
        self.settings.window_width, self.settings.window_height = width, height
        self.resize(width, height)
        self.setMinimumSize(1024, 768)
        self._build()
        self._apply_theme()
        self._refresh_runtime_banner()
        self.log_signal.connect(self._append_activity)
        self.hotkey_signal.connect(self._hotkey_bypass)
        self.stop_done.connect(self._on_stop_finished)
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
        self.report_timer = QTimer(self)
        self.report_timer.setInterval(200)
        self.report_timer.timeout.connect(self._refresh_report_live)
        self.report_timer.start()
        self.device_timer = QTimer(self)
        self.device_timer.setInterval(2000)
        self.device_timer.timeout.connect(self._poll_devices)
        self.device_timer.start()
        self._refresh_metrics()
        QTimer.singleShot(600, self._maybe_show_onboarding)

    @staticmethod
    def _system_dark() -> bool:
        return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark

    @staticmethod
    def _device_signature(devices) -> list[tuple[int, str, str]]:
        return [(int(d["index"]), str(d["name"]), str(d["hostapi"]))
                for d in devices]

    def _poll_devices(self):
        """Refresh microphone list on USB hot-plug and stop on device loss."""
        try:
            devices = list_input_devices(sd)
        except Exception:
            return
        signature = self._device_signature(devices)
        if signature == self._mic_signature:
            return
        old_devices = list(self.mic_devices)
        old_idx = self.mic.currentData()
        old_names = {str(d["name"]) for d in old_devices}
        new_names = {str(d["name"]) for d in devices}
        added = sorted(new_names - old_names)
        removed = sorted(old_names - new_names)
        self.mic_devices = devices
        self.mic.blockSignals(True)
        self.mic.clear()
        for d in devices:
            self.mic.addItem(f"{d['name']}  ·  {d['hostapi']}", d["index"])
        old_selected = next(
            (d for d in old_devices if d["index"] == old_idx), None)
        old_identity = (
            (str(old_selected["name"]), str(old_selected["hostapi"]))
            if old_selected is not None else None)
        matching = [
            i for i, d in enumerate(devices)
            if old_identity is not None
            and (str(d["name"]), str(d["hostapi"])) == old_identity
        ]
        target = matching[0] if matching else -1
        if target < 0 and old_identity is None and old_idx is not None:
            target = self.mic.findData(old_idx)
        if target < 0:
            target = self._settings_mic_index(devices)
        if target < 0 and devices:
            target = 0
        if target >= 0:
            self.mic.setCurrentIndex(target)
        self.mic.blockSignals(False)
        self._mic_signature = signature
        if added:
            self.log_signal.emit("已连接麦克风：" + "、".join(added))
        if removed:
            self.log_signal.emit("已断开麦克风：" + "、".join(removed))
        running = bool(self.pipeline and self.worker and self.worker.is_alive())
        lost = old_identity is not None and not matching
        if running and lost:
            self.log_signal.emit("当前麦克风已断开，正在停止分离。")
            self.stop()

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
        local = ThemedLabel("本地 · 私有", self.theme, role="muted", size=10)
        names.addWidget(name)
        names.addWidget(local)
        brand.addLayout(names)
        brand.addStretch(1)
        side.addLayout(brand)
        side.addSpacing(22)

        self.nav_buttons = []
        for index, (icon_name, text) in enumerate((
                ("house", "主页"),
                ("book-open", "使用教程"),
                ("chart-line", "性能信息"),
                ("activity", "运行报告"),
                ("settings", "设置"),
                ("info", "关于 FocusMic"))):
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
        tools.addWidget(self.theme_button)
        tools.addStretch(1)
        side.addLayout(tools)
        version = ThemedLabel(f"v{__version__} · Windows", self.theme, role="faint", size=9)
        version.setStyleSheet(version.styleSheet() + "padding:4px 6px;")
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
        self.tutorial_page = self._build_tutorial()
        self.performance_page = self._build_performance()
        self.report_page = self._build_report()
        self.settings_page = self._build_settings()
        self.about_page = self._build_about()
        for page in (self.home_page, self.tutorial_page, self.performance_page,
                     self.report_page, self.settings_page, self.about_page):
            self.page_host.add_page(page)
        content_layout.addWidget(self.page_host, 1)
        outer.addWidget(content, 1)
        self._append_activity("就绪。点击开始分离。")

    def _build_home(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.runtime_banner = QFrame()
        self.runtime_banner.setObjectName("RuntimeBanner")
        banner_row = QHBoxLayout(self.runtime_banner)
        banner_row.setContentsMargins(12, 8, 12, 8)
        banner_row.setSpacing(10)
        self.runtime_banner_label = ThemedLabel(
            "未检测到 AI 运行时（PyTorch + CUDA）。安装 FocusMic-Runtime 后才能开始分离。",
            self.theme, role="text", size=10, wrap=True)
        banner_row.addWidget(self.runtime_banner_label, 1)
        runtime_help = QPushButton("查看安装方法")
        runtime_help.setObjectName("ghost")
        runtime_help.clicked.connect(self._show_runtime_dialog)
        banner_row.addWidget(runtime_help)
        layout.addWidget(self.runtime_banner)

        top = QHBoxLayout()
        top.setSpacing(14)

        left_column = QWidget()
        left_column.setFixedWidth(344)
        left = QVBoxLayout(left_column)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(12)

        preview_card = QFrame()
        preview_card.setObjectName("Card")
        pv = QVBoxLayout(preview_card)
        pv.setContentsMargins(12, 11, 12, 12)
        pv.setSpacing(8)
        pv_head = QHBoxLayout()
        pv_head.addWidget(_card_title("摄像头预览", self.theme))
        pv_head.addStretch(1)
        self.preview_state = ThemedLabel("未开启", self.theme, role="muted", size=10)
        pv_head.addWidget(self.preview_state)
        pv.addLayout(pv_head)
        self.preview_label = PreviewCanvas(self.theme)
        self.preview_label.setFixedHeight(380)
        self.preview_label.roi_selected.connect(self._apply_manual_roi)
        pv.addWidget(self.preview_label)
        left.addWidget(preview_card)

        stats = QHBoxLayout()
        stats.setSpacing(8)
        self.tile_infer = InfoTile("推理延迟", "ms", self.theme)
        self.tile_full = InfoTile("全链路延迟", "s", self.theme)
        self.tile_track = InfoTile("目标跟踪", "%", self.theme)
        for tile in (self.tile_infer, self.tile_full, self.tile_track):
            stats.addWidget(tile, 1)
        left.addLayout(stats)
        top.addWidget(left_column, 0)

        controls = QFrame()
        controls.setObjectName("Card")
        form = QVBoxLayout(controls)
        form.setContentsMargins(15, 13, 15, 13)
        form.setSpacing(7)
        form.addWidget(_card_title("快速设置", self.theme))
        form.addWidget(_muted("设备、监听与输出", self.theme, 10))

        self.mic = QComboBox()
        self.mic.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mic.setMinimumContentsLength(14)
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
        self._mic_signature = self._device_signature(self.mic_devices)
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

        self.monitor = ToggleSwitch(self.theme)
        self.monitor_row = SettingRow(
            "耳机实时监听", "把分离后的声音送回耳机", self.monitor, self.theme)
        form.addWidget(self.monitor_row)

        av_row = QHBoxLayout()
        av_row.setSpacing(7)
        av_row.addWidget(_muted("音画同步", self.theme, 10))
        self.av = QSlider(Qt.Horizontal)
        self.av.setRange(-250, 250)
        self.av.setSingleStep(10)
        self.av_value = ThemedLabel(
            f"{self.settings.av_offset_ms} ms", self.theme, role="muted", size=10, mono=True)
        self.av.valueChanged.connect(lambda v: self.av_value.setText(f"{v} ms"))
        av_row.addWidget(self.av, 1)
        av_row.addWidget(self.av_value)
        form.addLayout(av_row)

        gain_row = QHBoxLayout()
        gain_row.setSpacing(7)
        gain_row.addWidget(_muted("输出增益", self.theme, 10))
        self.gain = QSlider(Qt.Horizontal)
        self.gain.setRange(-12, 12)
        self.gain.setSingleStep(1)
        self.gain_value = ThemedLabel(
            f"{int(self.settings.gain_db)} dB", self.theme, role="muted", size=10, mono=True)
        self.gain.valueChanged.connect(self._gain_changed)
        gain_row.addWidget(self.gain, 1)
        gain_row.addWidget(self.gain_value)
        form.addLayout(gain_row)
        form.addWidget(_muted("增益在下次开始分离时生效", self.theme, 9))

        run_row = QHBoxLayout()
        run_row.setSpacing(7)
        self.start_btn = QPushButton("开始分离")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        run_row.addWidget(self.start_btn, 2)
        run_row.addWidget(self.stop_btn, 1)
        form.addLayout(run_row)

        tools_row = QHBoxLayout()
        tools_row.setSpacing(7)
        self.reacquire_btn = QPushButton("重新锁定")
        self.reacquire_btn.setEnabled(False)
        self.reacquire_btn.setToolTip("清除目标与框选，重新自动选择最大人脸")
        self.reacquire_btn.clicked.connect(self.reacquire)
        self.roi_btn = QPushButton("框选目标")
        self.roi_btn.setToolTip("在预览中框住自己的脸，只在该区域选择目标")
        self.roi_btn.setEnabled(False)
        self.roi_btn.clicked.connect(self.begin_roi_select)
        self.bypass_btn = QPushButton("旁路：关")
        self.bypass_btn.setCheckable(True)
        self.bypass_btn.setEnabled(False)
        self.bypass_btn.toggled.connect(self.toggle_bypass)
        tools_row.addWidget(self.reacquire_btn)
        tools_row.addWidget(self.roi_btn)
        tools_row.addWidget(self.bypass_btn)
        form.addLayout(tools_row)
        form.addStretch(1)
        self.cable_label = ThemedLabel(
            "CABLE Input · 未连接", self.theme, role="muted", size=10, wrap=True)
        form.addWidget(self.cable_label)
        self._cable_connected = False
        self._cable_device = ""
        controls.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        top.addWidget(controls, 1)
        layout.addLayout(top, 0)

        console_card = QFrame()
        console_card.setObjectName("Card")
        console_box = QVBoxLayout(console_card)
        console_box.setContentsMargins(13, 10, 13, 11)
        console_box.setSpacing(6)
        console_head = QHBoxLayout()
        console_head.addWidget(_card_title("运行输出", self.theme))
        console_head.addStretch(1)
        console_head.addWidget(ThemedLabel("仅本机", self.theme, role="faint", size=9))
        console_box.addLayout(console_head)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(600)
        self.log_view.setMinimumHeight(120)
        self.log_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        console_box.addWidget(self.log_view, 1)
        layout.addWidget(console_card, 1)
        self._apply_home_settings()
        self.mic.currentIndexChanged.connect(self._mic_changed)
        return page

    def _tutorial_step(self, number: int, title: str, desc: str = "") -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        badge = ThemedLabel(str(number), self.theme, role="accent", size=12, weight=700)
        badge.setFixedWidth(22)
        badge.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        layout.addWidget(badge)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(ThemedLabel(title, self.theme, role="text", size=12, weight=600, wrap=True))
        if desc:
            texts.addWidget(ThemedLabel(desc, self.theme, role="muted", size=11, wrap=True))
        layout.addLayout(texts, 1)
        return row

    def _tutorial_bullet(self, text: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        dot = ThemedLabel("•", self.theme, role="accent", size=14)
        dot.setFixedWidth(10)
        dot.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        layout.addWidget(dot)
        layout.addWidget(ThemedLabel(text, self.theme, role="muted", size=11, wrap=True), 1)
        return row

    def _tutorial_qa(self, question: str, answer: str) -> QWidget:
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(ThemedLabel(question, self.theme, role="text", size=11, weight=600, wrap=True))
        layout.addWidget(ThemedLabel(answer, self.theme, role="muted", size=11, wrap=True))
        return row

    def _build_tutorial(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea > QWidget > QWidget{background:transparent;}")
        content = QWidget()
        content.setObjectName("TutorialContent")
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 0, 8, 0)
        box.setSpacing(12)

        intro, intro_box = self._settings_card(
            "FocusMic 在做什么", "摄像头负责认住你的嘴型，麦克风负责收声音。")
        intro_box.addWidget(ThemedLabel(
            "它会把麦克风里的声音过一遍：属于你的声音留下，旁边人的声音尽量压掉。"
            "所有处理都在本机完成，摄像头和麦克风内容不会上传。",
            self.theme, role="muted", size=11, wrap=True))
        box.addWidget(intro)

        prep, prep_box = self._settings_card(
            "开始前准备", "准备得越顺手，分离越稳。")
        for text in (
            "摄像头能拍到完整脸部，光线均匀，嘴不要被手、头发或口罩挡住。",
            "麦克风尽量靠近嘴；耳机麦通常比桌面麦更稳。",
            "建议戴耳机。外放出来的声音会被麦克风再次收进去。",
            "关掉其他占用摄像头或显卡的程序，避免抢资源。",
        ):
            prep_box.addWidget(self._tutorial_bullet(text))
        box.addWidget(prep)

        first, first_box = self._settings_card(
            "第一次使用", "按顺序做完，基本就能用了。")
        first_steps = (
            ("打开 FocusMic，在主页选择麦克风和摄像头。", "模型先用“Falcon Small”。"),
            ("点“开始分离”，等右上角状态变成“运行中”。",
             "预览里出现嘴部框，说明已经锁定你的脸。"),
            ("如果一直没有嘴部框，调整位置和光线，再点“重新锁定”。", ""),
            ("打开常用的语音或会议软件，把它的麦克风设为 CABLE Output。",
             "它就是 FocusMic 使用的虚拟声卡输出。"),
            ("关闭该软件自带的降噪、自动增益和回声消除。",
             "否则它会二次处理分离后的声音。"),
            ("需要自己试听时，再打开“耳机实时监听”。", "请使用耳机，避免啸叫。"),
        )
        for i, (title, desc) in enumerate(first_steps, 1):
            first_box.addWidget(self._tutorial_step(i, title, desc))
        box.addWidget(first)

        states, states_box = self._settings_card(
            "状态和旁路", "先看懂状态胶囊，再判断要不要干预。")
        for text in (
            "待机：没有开始分离。",
            "运行中：正在实时分离。",
            "直通：手遮嘴、目标丢失或手动切换时，直接使用原始麦克风；恢复后会自动回到分离。",
            "按 Ctrl+Alt+M，或点主页“旁路”按钮，可以手动切换；热键可在设置里修改。",
            "麦克风、摄像头或虚拟声卡断开时，程序会自动停止；接回后重新选择设备并开始即可。",
            "输出增益在开始分离前调整，下次开始生效。",
        ):
            states_box.addWidget(self._tutorial_bullet(text))
        box.addWidget(states)

        tips, tips_box = self._settings_card(
            "让它更准", "大多是姿势、距离和光线的问题。")
        for text in (
            "嘴部全程可见最重要。转头后等 1–2 秒，让画面重新跟上。",
            "画面里有别人时，运行中点“框选目标”，在预览里框住自己的脸。",
            "房间越吵，自己的嘴越要靠近麦克风，这比后处理更有效。",
            "Falcon Small 延迟低，适合日常；Falcon Big 更干净，但更吃显卡、延迟更高。",
            "如果自己的声音被压得厉害，或音画不同步，先调“音画同步”，从 20–40 ms 试起。",
        ):
            tips_box.addWidget(self._tutorial_bullet(text))
        box.addWidget(tips)

        faq, faq_box = self._settings_card(
            "常见问题", "先按这里排查，通常能自己解决。")
        for question, answer in (
            ("预览里没有嘴部框，跟踪一直是 0%？",
             "检查摄像头是否被其他程序占用、光线是否太暗、脸和嘴是否被挡住；调整后点“重新锁定”。"),
            ("语音软件里听不到我的声音？",
             "确认它的麦克风选的是 CABLE Output；再回到主页看 CABLE Input 是否显示“已连接”。"),
            ("别人听到我的声音被压得很小？",
             "确保分离时嘴部全程可见，不要遮嘴；把麦克风靠近一些，并在性能页确认跟踪率。"),
            ("延迟比较高？",
             "先用 Falcon Small，关闭其他占显卡的程序；性能页的全链路延迟可以看实时数值。"),
            ("停止后开始按钮是灰的？",
             "等“正在停止”结束，通常会在一两秒内回到待机，按钮会自动恢复。"),
        ):
            faq_box.addWidget(self._tutorial_qa(question, answer))
        box.addWidget(faq)

        privacy, privacy_box = self._settings_card(
            "隐私", "不需要联网，也不会把声音传出去。")
        for text in (
            "摄像头画面和麦克风声音只在本机处理，不上传。",
            "没有遥测；配置和日志保存在本机的用户目录。",
            "分离结果通过本机虚拟声卡（CABLE）输出，只有你选择的语音软件能收到。",
        ):
            privacy_box.addWidget(self._tutorial_bullet(text))
        box.addWidget(privacy)
        box.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        return page

    def _build_performance(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        kpis = QHBoxLayout()
        kpis.setSpacing(8)
        self.kpi_infer = KpiCard("推理延迟", "—", "ms", self.theme)
        self.kpi_full = KpiCard("全链路延迟", "—", "s", self.theme,
                                accent_role="accent")
        self.kpi_cpu = KpiCard("FocusMic CPU", "—", "%", self.theme)
        self.kpi_memory = KpiCard("FocusMic 内存", "—", "MB", self.theme)
        self.kpi_gpu = KpiCard("FocusMic GPU", "—", "%", self.theme)
        for card in (self.kpi_infer, self.kpi_full, self.kpi_cpu,
                     self.kpi_memory, self.kpi_gpu):
            kpis.addWidget(card, 1)
        layout.addLayout(kpis)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.chart_infer = MetricCard(
            "推理延迟", "ms", self.theme.blue, self.theme, color_role="blue")
        self.chart_full = MetricCard(
            "全链路延迟", "s", self.theme.accent, self.theme, color_role="accent")
        self.chart_cpu = MetricCard(
            "FocusMic CPU", "%", self.theme.teal, self.theme,
            fixed_max=100, color_role="teal")
        self.chart_memory = MetricCard(
            "FocusMic 内存", "MB", self.theme.blue, self.theme, color_role="blue")
        self.chart_gpu = MetricCard(
            "FocusMic GPU", "%", self.theme.red, self.theme,
            fixed_max=100, color_role="red")
        for i, card in enumerate((self.chart_infer, self.chart_full,
                                  self.chart_cpu, self.chart_memory,
                                  self.chart_gpu)):
            grid.addWidget(card, i // 2, i % 2)
        note_card = QFrame()
        note_card.setObjectName("Card")
        note_box = QVBoxLayout(note_card)
        note_box.setContentsMargins(16, 14, 16, 14)
        note_box.setSpacing(8)
        note_box.addWidget(_card_title("采样口径", self.theme))
        note_box.addWidget(ThemedLabel(
            "内存为进程独占工作集（USS），与任务管理器一致；"
            "GPU 为 Windows GPU Engine 中该进程最忙引擎的占用，"
            "口径与任务管理器相同；全链路延迟由输入缓冲、输出队列和"
            "设备延迟估算，不含接收端软件缓冲。",
            self.theme, role="muted", size=10, wrap=True))
        note_box.addStretch(1)
        grid.addWidget(note_card, 2, 1)
        layout.addLayout(grid, 1)
        self.perf_note = _muted(
            "仅统计 FocusMic 进程 · 每 0.6 s 采样 · 最近 30 s", self.theme, 10)
        layout.addWidget(self.perf_note)
        return page

    def _build_report(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        kpis = QHBoxLayout()
        kpis.setSpacing(8)
        self.report_kpi_bypass = KpiCard("自动直通", "—", "次", self.theme)
        self.report_kpi_max = KpiCard("最大推理延迟", "—", "ms", self.theme)
        self.report_kpi_suppress = KpiCard(
            "平均抑制", "—", "dB", self.theme, accent_role="teal")
        self.report_kpi_full = KpiCard(
            "全链路延迟", "—", "s", self.theme, accent_role="accent")
        self.report_kpi_time = KpiCard("本次运行", "—", "", self.theme)
        for card in (self.report_kpi_bypass, self.report_kpi_max,
                     self.report_kpi_suppress, self.report_kpi_full,
                     self.report_kpi_time):
            kpis.addWidget(card, 1)
        layout.addLayout(kpis)

        middle = QHBoxLayout()
        middle.setSpacing(12)
        wave_card = QFrame()
        wave_card.setObjectName("Card")
        wave_box = QVBoxLayout(wave_card)
        wave_box.setContentsMargins(15, 13, 15, 13)
        wave_box.setSpacing(6)
        wave_box.addWidget(_card_title("声纹对比", self.theme))
        wave_box.addWidget(ThemedLabel(
            "原始麦克风与处理后输出，最近 8 秒（未计输出增益）",
            self.theme, role="muted", size=10, wrap=True))
        self.report_wave = WaveformCompare(self.theme)
        wave_box.addWidget(self.report_wave, 1)
        middle.addWidget(wave_card, 2)

        spectrum_card = QFrame()
        spectrum_card.setObjectName("Card")
        spectrum_box = QVBoxLayout(spectrum_card)
        spectrum_box.setContentsMargins(15, 13, 15, 13)
        spectrum_box.setSpacing(6)
        spectrum_box.addWidget(_card_title("频谱对比", self.theme))
        spectrum_box.addWidget(ThemedLabel(
            "0–4 kHz；平均抑制 = 输入/输出能量比",
            self.theme, role="muted", size=10, wrap=True))
        self.report_spectrum = SpectrumCompare(self.theme)
        spectrum_box.addWidget(self.report_spectrum, 1)
        middle.addWidget(spectrum_card, 1)
        layout.addLayout(middle, 2)

        console_card = QFrame()
        console_card.setObjectName("Card")
        console_box = QVBoxLayout(console_card)
        console_box.setContentsMargins(13, 10, 13, 11)
        console_box.setSpacing(6)
        console_head = QHBoxLayout()
        console_head.addWidget(_card_title("运行输出", self.theme))
        console_head.addStretch(1)
        self.report_stats = ThemedLabel("等待数据", self.theme, role="faint", size=9)
        console_head.addWidget(self.report_stats)
        console_box.addLayout(console_head)
        self.report_log = QPlainTextEdit()
        self.report_log.setReadOnly(True)
        self.report_log.setMaximumBlockCount(2000)
        self.report_log.setMinimumHeight(150)
        self.report_log.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        console_box.addWidget(self.report_log, 1)
        layout.addWidget(console_card, 3)
        return page

    def _settings_card(self, title: str, subtitle: str = ""):
        card = QFrame()
        card.setObjectName("Card")
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)
        box.addWidget(_card_title(title, self.theme))
        if subtitle:
            box.addWidget(ThemedLabel(
                subtitle, self.theme, role="muted", size=10, wrap=True))
        return card, box

    def _build_settings(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        columns = QHBoxLayout()
        columns.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(12)
        right = QVBoxLayout()
        right.setSpacing(12)

        startup_card, startup_box = self._settings_card(
            "启动", "登录 Windows 后自动在后台准备。")
        self.settings_startup = ToggleSwitch(self.theme)
        self.settings_startup.setAccessibleName("开机启动 FocusMic")
        self.settings_startup.setChecked(self.settings.start_with_windows)
        self.settings_startup.toggled.connect(self._on_startup_toggle)
        startup_box.addWidget(SettingRow(
            "开机启动 FocusMic",
            "写入当前用户的启动项，不需要管理员权限",
            self.settings_startup, self.theme))
        self.settings_tray = ToggleSwitch(self.theme)
        self.settings_tray.setAccessibleName("关闭窗口时最小化到托盘")
        self.settings_tray.setChecked(self.settings.close_to_tray)
        self.settings_tray.toggled.connect(self._on_close_to_tray_toggle)
        startup_box.addWidget(SettingRow(
            "关闭窗口时最小化到托盘",
            "默认开启；关闭后点窗口的 × 会直接退出程序",
            self.settings_tray, self.theme))
        left.addWidget(startup_card)

        appearance_card, appearance_box = self._settings_card(
            "外观", "深色、浅色，或交给 Windows 决定。")
        self.settings_follow = ToggleSwitch(self.theme)
        self.settings_follow.setAccessibleName("跟随系统外观")
        self.settings_follow.setChecked(self.settings.theme_mode == "system")
        self.settings_follow.toggled.connect(self._on_follow_toggle)
        appearance_box.addWidget(SettingRow(
            "跟随系统外观",
            "Windows 切换深色模式时同步切换",
            self.settings_follow, self.theme))
        self.settings_theme = QComboBox()
        self.settings_theme.addItem("深色", "dark")
        self.settings_theme.addItem("浅色", "light")
        self.settings_theme.currentIndexChanged.connect(self._on_settings_theme)
        appearance_box.addWidget(SettingRow(
            "手动外观", "关闭跟随后使用这个模式",
            self.settings_theme, self.theme))
        left.addWidget(appearance_card)
        left.addStretch(1)

        hotkey_card, hotkey_box = self._settings_card(
            "快捷键", "在原始麦克风与分离输出之间切换。")
        self.settings_hotkey_enabled = ToggleSwitch(self.theme)
        self.settings_hotkey_enabled.setAccessibleName("启用全局旁路热键")
        self.settings_hotkey_enabled.setChecked(self.settings.hotkey_enabled)
        self.settings_hotkey_enabled.toggled.connect(self._on_hotkey_enabled)
        hotkey_box.addWidget(SettingRow(
            "启用全局旁路热键",
            "其他程序在前台时也能触发",
            self.settings_hotkey_enabled, self.theme))
        edit_row = QHBoxLayout()
        edit_row.setSpacing(10)
        edit_row.addWidget(_muted("组合键", self.theme, 10))
        edit_row.addStretch(1)
        self.settings_hotkey = QKeySequenceEdit(
            QKeySequence(_hotkey_display(self.settings.hotkey)))
        self.settings_hotkey.setMaximumWidth(190)
        self.settings_hotkey.setEnabled(self.settings.hotkey_enabled)
        edit_row.addWidget(self.settings_hotkey)
        hotkey_box.addLayout(edit_row)
        hotkey_box.addWidget(ThemedLabel(
            "点击输入框后按下组合键，例如 Ctrl+Alt+M。保存后立即生效。",
            self.theme, role="faint", size=10, wrap=True))
        right.addWidget(hotkey_card)

        paths_card, paths_box = self._settings_card(
            "配置与日志", "设置和日志都保存在当前用户目录。")
        for label, path in (
                ("配置文件", r"%APPDATA%\FocusMic\config.json"),
                ("日志文件", r"%LOCALAPPDATA%\FocusMic\logs\focusmic.log")):
            paths_box.addWidget(_muted(label, self.theme, 10))
            value = ThemedLabel(path, self.theme, role="muted",
                                size=9, wrap=True, mono=True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setMinimumWidth(0)
            value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            paths_box.addWidget(value)
        paths_box.addStretch(1)
        right.addWidget(paths_card)
        right.addStretch(1)

        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        outer.addLayout(columns, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.settings_status = ThemedLabel(
            "外观和开关会立即应用；组合键保存后生效。",
            self.theme, role="muted", size=10)
        footer.addWidget(self.settings_status, 1)
        wizard = QPushButton("首次向导")
        wizard.setObjectName("ghost")
        wizard.clicked.connect(self._show_onboarding)
        footer.addWidget(wizard)
        save = QPushButton("保存设置")
        save.setObjectName("primary")
        save.clicked.connect(self._save_settings_page)
        footer.addWidget(save)
        outer.addLayout(footer)
        self._sync_settings_page()
        return page

    def _sync_settings_page(self):
        if not hasattr(self, "settings_startup"):
            return
        widgets = (self.settings_startup, self.settings_tray,
                   self.settings_follow, self.settings_hotkey_enabled,
                   self.settings_theme, self.settings_hotkey)
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self.settings_startup.setChecked(self.settings.start_with_windows)
            self.settings_tray.setChecked(self.settings.close_to_tray)
            follow = self.settings.theme_mode == "system"
            self.settings_follow.setChecked(follow)
            self.settings_theme.setEnabled(not follow)
            mode = self.settings.theme_mode
            if mode == "system":
                mode = "dark" if self.theme.dark else "light"
            index = self.settings_theme.findData(mode)
            if index >= 0:
                self.settings_theme.setCurrentIndex(index)
            self.settings_hotkey_enabled.setChecked(self.settings.hotkey_enabled)
            self.settings_hotkey.setEnabled(self.settings.hotkey_enabled)
            self.settings_hotkey.setKeySequence(
                QKeySequence(_hotkey_display(self.settings.hotkey)))
        finally:
            for widget in widgets:
                widget.blockSignals(False)

    def _set_settings_status(self, text: str, error: bool = False):
        if not hasattr(self, "settings_status"):
            return
        color = self.theme.red if error else self.theme.teal
        self.settings_status.setText(text)
        self.settings_status.setStyleSheet(
            f"color:{color};font-size:10px;background:transparent;")

    def _persist_settings(self):
        self.settings.window_width = self.width()
        self.settings.window_height = self.height()
        try:
            save_settings(self.settings)
        except OSError as exc:
            self.log_signal.emit(f"设置保存失败：{exc}")

    def _on_close_to_tray_toggle(self, checked: bool):
        self.settings.close_to_tray = bool(checked)
        self._persist_settings()

    def _on_startup_toggle(self, checked: bool):
        try:
            set_startup(bool(checked))
            self.settings.start_with_windows = bool(checked)
            self._persist_settings()
            self._set_settings_status(
                "开机启动已" + ("开启。" if checked else "关闭。"))
            self.log_signal.emit(
                "开机启动：" + ("开" if checked else "关"))
        except Exception as exc:
            self.settings_startup.blockSignals(True)
            self.settings_startup.setChecked(not checked)
            self.settings_startup.blockSignals(False)
            self._set_settings_status(f"开机启动设置失败：{exc}", error=True)

    def _on_follow_toggle(self, checked: bool):
        self.settings.theme_mode = "system" if checked else self.settings_theme.currentData()
        if not self.settings.theme_mode:
            self.settings.theme_mode = "dark" if self.theme.dark else "light"
        self.settings_theme.setEnabled(not checked)
        self.theme = theme_for(self.settings.theme_mode, self._system_dark())
        self._apply_theme()
        self._persist_settings()
        self._set_settings_status(
            "外观：跟随系统。" if checked else "外观：已固定。")

    def _on_settings_theme(self, index: int):
        if self.settings_follow.isChecked():
            return
        mode = self.settings_theme.currentData()
        if not mode:
            return
        self.settings.theme_mode = mode
        self.theme = theme_for(mode, self._system_dark())
        self._apply_theme()
        self._persist_settings()
        self._set_settings_status("外观已切换。")

    @staticmethod
    def _hotkey_problem(hotkey: str) -> str | None:
        parts = [p for p in str(hotkey).lower().replace(" ", "").split("+") if p]
        modifiers = {"ctrl", "alt", "shift"}
        if not parts:
            return "请先输入一个组合键，例如 Ctrl+Alt+M。"
        if any(p in {"meta", "win", "windows", "cmd"} for p in parts):
            return "请使用 Ctrl/Alt/Shift 组合键，不要使用 Win/Meta。"
        if len(parts) < 2 or not any(p in modifiers for p in parts):
            return "至少需要一个 Ctrl/Alt/Shift 修饰键加一个普通键。"
        if all(p in modifiers for p in parts):
            return "还需要一个普通键，例如 M。"
        return None

    def _on_hotkey_enabled(self, checked: bool):
        if checked:
            problem = self._hotkey_problem(self.settings.hotkey)
            if problem:
                self.settings_hotkey_enabled.blockSignals(True)
                self.settings_hotkey_enabled.setChecked(False)
                self.settings_hotkey_enabled.blockSignals(False)
                self.settings.hotkey_enabled = False
                self.settings_hotkey.setEnabled(False)
                self._set_settings_status(problem, error=True)
                self._persist_settings()
                return
        self.settings.hotkey_enabled = bool(checked)
        self.settings_hotkey.setEnabled(bool(checked))
        if checked and not self._register_hotkey():
            self.settings_hotkey_enabled.blockSignals(True)
            self.settings_hotkey_enabled.setChecked(False)
            self.settings_hotkey_enabled.blockSignals(False)
            self.settings.hotkey_enabled = False
            self.settings_hotkey.setEnabled(False)
            self._set_settings_status("热键注册失败，请换一个组合键。", error=True)
            self._persist_settings()
            return
        self._persist_settings()
        self._set_settings_status(
            "旁路热键已启用。" if checked else "旁路热键已停用。")

    def _save_settings_page(self):
        sequence = self.settings_hotkey.keySequence().toString(QKeySequence.PortableText)
        hotkey = sequence.lower().replace(" ", "")
        if self.settings_hotkey_enabled.isChecked():
            problem = self._hotkey_problem(hotkey)
            if problem:
                self._set_settings_status(problem, error=True)
                self.settings_hotkey.setFocus()
                return
        if hotkey:
            self.settings.hotkey = hotkey
        self.settings.hotkey_enabled = self.settings_hotkey_enabled.isChecked()
        self.settings.theme_mode = (
            "system" if self.settings_follow.isChecked()
            else self.settings_theme.currentData() or self.settings.theme_mode)
        self.settings.start_with_windows = self.settings_startup.isChecked()
        self.settings.close_to_tray = self.settings_tray.isChecked()
        self._persist_settings()
        registered = self._register_hotkey()
        if self.settings.hotkey_enabled and not registered:
            self._set_settings_status("设置已保存，但热键注册失败。", error=True)
        else:
            self._set_settings_status(
                time.strftime("已保存 · %H:%M:%S"))
        self.log_signal.emit("设置已保存。")

    def _about_card(self, title: str, body: str) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 15, 18, 15)
        box.setSpacing(7)
        box.addWidget(_card_title(title, self.theme))
        label = ThemedLabel(body, self.theme, role="muted", size=10, wrap=True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(label)
        return card

    def _build_about(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        brand = QFrame()
        brand.setObjectName("Card")
        brand.setFixedWidth(292)
        box = QVBoxLayout(brand)
        box.setContentsMargins(22, 24, 22, 22)
        box.setSpacing(6)
        icon = QLabel()
        pix = QPixmap(str(BRAND_ICON))
        if not pix.isNull():
            icon.setPixmap(pix.scaled(92, 92, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        box.addWidget(icon)
        box.addWidget(ThemedLabel("FocusMic", self.theme, role="text", size=25, weight=600))
        box.addWidget(ThemedLabel(
            f"版本 {__version__} · Version {__version__}",
            self.theme, role="muted", size=11))
        box.addSpacing(8)
        box.addWidget(ThemedLabel(
            "把镜头里的你，从房间的声音里留下来。\n"
            "Keep the person on camera, not the whole room.",
            self.theme, role="text", size=12, wrap=True))
        box.addSpacing(12)
        for text in ("本地推理 / Local inference",
                     "画面与声音不上传 / No uploads",
                     "无遥测 / No telemetry"):
            row = QHBoxLayout()
            row.setSpacing(7)
            dot = ThemedLabel("●", self.theme, role="teal", size=9)
            dot.setFixedWidth(10)
            row.addWidget(dot)
            row.addWidget(ThemedLabel(
                text, self.theme, role="muted", size=10, wrap=True), 1)
            box.addLayout(row)
        box.addStretch(1)
        box.addWidget(ThemedLabel(
            "Windows 10/11 · NVIDIA GPU · CUDA 12.8",
            self.theme, role="faint", size=10, wrap=True))
        layout.addWidget(brand)

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        right = QVBoxLayout(body)
        right.setContentsMargins(0, 0, 8, 0)
        right.setSpacing(10)

        right.addWidget(self._about_card(
            "FocusMic 是什么 / What it is",
            "FocusMic 是一个 Windows 本地的音视频目标说话人提取工具：摄像头看嘴型，"
            "麦克风听声音，实时把你自己的声音从同一房间的多人说话中分离出来。\n\n"
            "FocusMic is a local Windows audio-visual target speaker extraction app. "
            "It uses lip motion from the camera and audio from the microphone to "
            "isolate your voice from other people speaking in the same room, in real time."))

        right.addWidget(self._about_card(
            "效果 / What it does",
            "保留你的声音，压低旁边人的说话声；手遮住嘴、离开画面或丢失目标时"
            "自动直通原始麦克风，避免“没声音”。\n"
            "Falcon Small 单窗推理约 65–85 ms；内部同音色干扰测试中，纯音频基线 "
            "SIR 0.6 dB，口型路线 15.1 dB。实际效果取决于光照、正脸角度、"
            "麦克风距离和房间混响。\n\n"
            "Keeps your voice and suppresses nearby speakers. If your mouth is covered "
            "or the target is lost, FocusMic falls back to the raw microphone so you are "
            "never muted. Falcon Small inference is ~65–85 ms per 2 s window. In an "
            "internal same-voice test, the audio-only baseline measured 0.6 dB SIR; the "
            "lip-based route measured 15.1 dB. Real results depend on lighting, face "
            "angle, mic distance and room acoustics."))

        right.addWidget(self._about_card(
            "和传统降噪的区别 / vs. noise suppression",
            "传统降噪（RNNoise、Krisp、NVIDIA Broadcast 等）主要去除风扇、键盘、"
            "稳态噪声，无法区分两个同时说话的人；很多实现会把旁边人的说话声"
            "一起保留或一起压掉。\n"
            "FocusMic 不靠“声音像不像噪声”，而是用画面里的嘴部运动锁定目标"
            "说话人，所以舍友同时说话时仍能偏向你。它不是降噪器的替代品，"
            "而是解决“多人同时说话”的问题。\n\n"
            "Traditional noise suppression (RNNoise, Krisp, NVIDIA Broadcast, etc.) "
            "removes fans, keyboards and stationary noise, but cannot tell two "
            "concurrent talkers apart. FocusMic uses visual lip motion to identify the "
            "target speaker, so it can favor you even when a roommate talks at the same "
            "time. It solves concurrent-speech separation, not just noise."))

        right.addWidget(self._about_card(
            "运行环境 / Requirements",
            "Windows 10/11 x64；NVIDIA 显卡与支持 CUDA 12.8 的驱动；摄像头；"
            "麦克风；VB-CABLE 虚拟声卡。\n"
            "磁盘：主程序约 590 MB，AI 运行时约 4.3 GB；显存：Small 约 384 MB，"
            "Big 约 567 MB；建议 8 GB 以上内存。\n\n"
            "Windows 10/11 x64; NVIDIA GPU with a CUDA 12.8-capable driver; camera; "
            "microphone; VB-CABLE. Disk: app ~590 MB, runtime ~4.3 GB. VRAM: ~384 MB "
            "(Small) / ~567 MB (Big). 8 GB+ RAM recommended."))

        right.addWidget(self._about_card(
            "性能开销 / Performance",
            "测试机：RTX 5070 Ti Laptop 12 GB + Ryzen 9 7945HX。\n"
            "Falcon Small：约 67.6 ms/窗，0.2 s 步长时 GPU 约 31%；"
            "Falcon Big：约 74.8 ms/窗。\n"
            "MediaPipe 口型跟踪约 10.8 ms/帧，25 fps 下约单核 27%。\n"
            "端到端约 0.3–0.5 s（不含语音/会议软件自身缓冲）；"
            "全链路延迟在应用内实时显示。\n\n"
            "Tested on RTX 5070 Ti Laptop 12 GB + Ryzen 9 7945HX. Falcon Small: "
            "~67.6 ms per window, ~31% GPU at a 0.2 s hop; Falcon Big: ~74.8 ms. "
            "MediaPipe mouth tracking: ~10.8 ms/frame, ~27% of one CPU core at 25 fps. "
            "End-to-end latency is roughly 0.3–0.5 s, excluding the receiving app's "
            "buffer; the in-app full-chain estimate is shown live."))

        right.addWidget(self._about_card(
            "快速上手 / Quick start",
            "1. 安装 VB-CABLE。\n"
            "2. 先安装 FocusMic-Runtime，再安装 FocusMic。\n"
            "3. 首次向导选择麦克风和摄像头；正对镜头，保证嘴部可见。\n"
            "4. 在语音/会议软件里把麦克风选为 CABLE Output，并关闭它自带的"
            "降噪、AGC 和回声消除。\n"
            "5. 回到 FocusMic 点“开始分离”；手遮嘴或按 Ctrl+Alt+M 可切到原始麦克风。\n\n"
            "1. Install VB-CABLE.\n"
            "2. Install FocusMic-Runtime, then FocusMic.\n"
            "3. In the first-run wizard pick your microphone and camera; face the "
            "camera with your mouth visible.\n"
            "4. In your voice/meeting app select CABLE Output as the microphone and "
            "disable its noise suppression, AGC and echo cancellation.\n"
            "5. Click Start in FocusMic. Cover your mouth or press Ctrl+Alt+M to bypass "
            "to the raw microphone."))

        right.addWidget(self._about_card(
            "隐私 / Privacy",
            "所有推理在本机完成；摄像头画面不保存、不上传；没有遥测。"
            "日志只写到本机 %LOCALAPPDATA%\\FocusMic\\logs。\n\n"
            "All inference runs locally. Camera frames are not saved or uploaded. "
            "No telemetry. Logs stay in %LOCALAPPDATA%\\FocusMic\\logs."))

        lic = QFrame()
        lic.setObjectName("Card")
        lic_box = QVBoxLayout(lic)
        lic_box.setContentsMargins(18, 15, 18, 15)
        lic_box.setSpacing(8)
        lic_box.addWidget(_card_title("许可证与致谢 / License & credits", self.theme))
        lic_grid = QGridLayout()
        lic_grid.setHorizontalSpacing(18)
        lic_grid.setVerticalSpacing(7)
        license_rows = (
            ("FocusMic", "Apache-2.0"),
            ("Falcon", "Apache-2.0 · JusperLee"),
            ("MediaPipe", "Apache-2.0"),
            ("Lucide icons", "ISC"),
            ("Simple Icons", "CC0"),
            ("PySide6", "LGPL-3.0"),
            ("VB-CABLE", "separate driver · 独立驱动，不随应用分发"),
        )
        for row_index, (product, license_name) in enumerate(license_rows):
            lic_grid.addWidget(
                ThemedLabel(product, self.theme, role="text", size=10), row_index, 0)
            lic_grid.addWidget(
                ThemedLabel(license_name, self.theme, role="muted", size=10, wrap=True),
                row_index, 1)
        lic_grid.setColumnStretch(1, 1)
        lic_box.addLayout(lic_grid)
        right.addWidget(lic)

        links = QFrame()
        links.setObjectName("Card")
        links_box = QVBoxLayout(links)
        links_box.setContentsMargins(18, 15, 18, 15)
        links_box.setSpacing(7)
        links_box.addWidget(_card_title("链接 / Links", self.theme))
        links_box.addWidget(LinkLabel(
            "github.com/ms12667/FocusMic",
            "https://github.com/ms12667/FocusMic", self.theme, size=11))
        links_box.addWidget(LinkLabel(
            "Releases · 下载运行时与安装包 / downloads",
            "https://github.com/ms12667/FocusMic/releases", self.theme, size=11))
        right.addWidget(links)

        status = runtime_env.check_installed()
        build = QFrame()
        build.setObjectName("Card")
        build_box = QVBoxLayout(build)
        build_box.setContentsMargins(18, 15, 18, 15)
        build_box.setSpacing(8)
        build_box.addWidget(_card_title("构建信息 / Build", self.theme))
        build_grid = QGridLayout()
        build_grid.setHorizontalSpacing(18)
        build_grid.setVerticalSpacing(7)
        torch_version = status.torch_version or "未安装 / Not installed"
        cuda = f"CUDA {status.cuda_version}" if status.cuda_version else "—"
        build_rows = (
            ("Python", platform.python_version()),
            ("PySide6", _package_version("PySide6")),
            ("PyTorch", torch_version),
            ("CUDA", cuda),
        )
        for row_index, (key, value) in enumerate(build_rows):
            build_grid.addWidget(
                ThemedLabel(key, self.theme, role="muted", size=10), row_index, 0)
            build_grid.addWidget(
                ThemedLabel(value, self.theme, role="text", size=10), row_index, 1)
        build_grid.setColumnStretch(1, 1)
        build_box.addLayout(build_grid)
        right.addWidget(build)
        right.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea > QWidget > QWidget{background:transparent;}")
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        return page

    def _gain_changed(self, value: int):
        self.gain_value.setText(f"{value} dB")
        self.settings.gain_db = float(value)

    def _settings_mic_index(self, devices=None) -> int:
        """Find the saved microphone by (name, host API), not name alone.

        PortAudio exposes the same endpoint once per host API (MME,
        DirectSound, WASAPI, WDM-KS), so matching only by name silently reset
        users to the first duplicate.
        """
        devices = self.mic_devices if devices is None else devices
        name = self.settings.mic_name
        host = self.settings.mic_hostapi
        if not name:
            return -1
        if host:
            for i, d in enumerate(devices):
                if str(d["name"]) == name and str(d["hostapi"]) == host:
                    return i
        matches = [
            (i, d) for i, d in enumerate(devices) if str(d["name"]) == name
        ]
        if not matches:
            return -1
        if host:
            return matches[0][0]
        # Legacy config without a host API: prefer WASAPI/48 kHz.
        matches.sort(key=lambda item: (
            "WASAPI" not in item[1]["hostapi"],
            abs(float(item[1]["samplerate"]) - 48000.0),
            item[1]["index"],
        ))
        return matches[0][0]

    def _apply_home_settings(self):
        index = self._settings_mic_index()
        if index >= 0:
            self.mic.setCurrentIndex(index)
        pos = self.camera.findData(self.settings.camera)
        if pos >= 0:
            self.camera.setCurrentIndex(pos)
        pos = self.model.findData(self.settings.variant)
        if pos >= 0:
            self.model.setCurrentIndex(pos)
        self.av.setValue(self.settings.av_offset_ms)
        self.monitor.setChecked(self.settings.monitor)
        self.av_value.setText(f"{self.av.value()} ms")
        self.gain.setValue(int(self.settings.gain_db))
        self.gain_value.setText(f"{self.gain.value()} dB")

    def show_page(self, index: int):
        if index == self._page:
            if index == 4:
                self._sync_settings_page()
            elif index == 3:
                self._refresh_report()
            return
        self._page = index
        for i, button in enumerate(self.nav_buttons):
            button.set_active(i == index)
        titles = (
            ("主页", "实时分离与快速设置"),
            ("使用教程", "从安装到开始分离"),
            ("性能信息", "FocusMic 进程的 CPU、内存、GPU 与延迟"),
            ("运行报告", "声纹对比、抑制效果与本次统计"),
            ("设置", "启动、外观与快捷键"),
            ("关于 FocusMic", "版本、开发者与许可证"),
        )
        self.page_title.setText(titles[index][0])
        self.page_subtitle.setText(titles[index][1])
        if index != 0:
            self.preview_label.set_selecting(False)
        if index == 4:
            self._sync_settings_page()
        elif index == 3:
            self._refresh_report()
        self.page_host.set_current(index, animate=True)

    def _append_activity(self, text: str):
        stamp = time.strftime("%H:%M:%S")
        for name in ("log_view", "report_log"):
            view = getattr(self, name, None)
            if view is None:
                continue
            view.appendPlainText(f"{stamp}  {text}")
            bar = view.verticalScrollBar()
            bar.setValue(bar.maximum())
        logging.getLogger("focusmic").info(text)

    def _set_controls_running(self, running: bool):
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.reacquire_btn.setEnabled(running)
        self.roi_btn.setEnabled(running)
        self.bypass_btn.setEnabled(running)
        for widget in (self.mic, self.camera, self.model, self.av,
                       self.gain, self.monitor):
            widget.setEnabled(not running)
        self.monitor_row.setEnabled(not running)
        if not running:
            if self.bypass_btn.isChecked():
                self.bypass_btn.setChecked(False)
            self.bypass_btn.setText("旁路：关")

    def _refresh_runtime_banner(self):
        status = runtime_env.check_installed()
        self.runtime_banner.setVisible(not status.ok)
        if status.ok:
            self.start_btn.setToolTip("")
        else:
            self.runtime_banner_label.setText(
                "未检测到 AI 运行时（PyTorch + CUDA）。"
                "安装 FocusMic-Runtime 后才能开始分离。")
            self.start_btn.setToolTip(status.message())

    def _show_runtime_dialog(self):
        RuntimeDialog(self.theme, self).exec()
        self._refresh_runtime_banner()

    def start(self):
        if self._stopping:
            self.log_signal.emit("正在停止上一轮，请稍候…")
            return
        if self.worker and self.worker.is_alive():
            return
        # Importing torch from the external runtime takes a moment; do it before
        # opening devices so a missing/broken runtime cannot leave the app
        # half-started.
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            runtime_status = runtime_env.ensure_runtime(check_cuda=True)
        finally:
            QApplication.restoreOverrideCursor()
        if not runtime_status.ok:
            self._refresh_runtime_banner()
            self._show_runtime_dialog()
            return
        mic_idx = self.mic.currentData()
        camera = self.camera.currentData()
        variant = self.model.currentData()
        av = self.av.value()
        monitor = self.monitor.isChecked()
        self._store_settings()
        try:
            audio = LiveAudio(mic_idx)
            tracker = MouthTracker(int(camera), model_path=MEDIAPIPE_MODEL)
        except Exception as exc:
            self.log_signal.emit(f"设备初始化失败：{exc}")
            return
        pipeline = NativePipeline(
            audio, tracker, variant=variant, av_offset_ms=av,
            gain_db=self.settings.gain_db, output=True, monitor=monitor,
            log=self.log_signal.emit,
        )
        self.tracker = tracker
        self.pipeline = pipeline
        self.report_snapshot = None
        self._last_monitor_error = None
        self._set_controls_running(True)
        self.preview_state.setText("正在启动")
        self.log_signal.emit("正在加载分离模型…")
        self.log_signal.emit(
            f"启动：{self.mic.currentText()} / 摄像头 {camera} / "
            f"{self.model.currentText()} / AV {av} ms / "
            f"增益 {int(self.settings.gain_db)} dB")
        self.worker = threading.Thread(
            target=self._run, args=(pipeline,), daemon=True, name="pipeline")
        self.worker.start()

    def _run(self, pipeline):
        try:
            pipeline.load("cuda")
            self.log_signal.emit("模型就绪，正在分离。")
            pipeline.run()
        except Exception as exc:
            self.log_signal.emit(f"运行失败：{exc}")
        finally:
            self.log_signal.emit("已停止。")

    def stop(self):
        if self._stopping:
            return
        pipeline = self.pipeline
        tracker = self.tracker
        worker = self.worker
        if pipeline is None and worker is None:
            self.preview_label.clear()
            self.preview_state.setText("未开启")
            self._set_cable(False)
            self.status_chip.set_state("idle")
            self._set_controls_running(False)
            self._last_bypass = False
            return
        self._stopping = True
        if pipeline is not None:
            try:
                self.report_snapshot = pipeline.report(seconds=8)
            except Exception:
                self.report_snapshot = None
            pipeline.stop()
        self.pipeline = None
        self.tracker = None
        self.worker = None
        self.preview_label.clear()
        self.preview_state.setText("未开启")
        self._set_cable(False)
        self.status_chip.set_state("stopping")
        self._set_controls_running(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self._last_bypass = False
        if self._page == 3:
            self._refresh_report()
        self.log_signal.emit("正在停止…")
        threading.Thread(
            target=self._finish_stop, args=(tracker, worker),
            daemon=True, name="stop-cleanup").start()

    def _finish_stop(self, tracker, worker):
        ok = True
        if worker is not None and worker.is_alive():
            # Never block the GUI thread on PortAudio/MediaPipe teardown.
            worker.join(timeout=8.0)
            ok = not worker.is_alive()
        if tracker is not None and (worker is None or not worker.is_alive()):
            # Stops are idempotent. A lingering MediaPipe close thread must not
            # disable the Start button: cap.release() happens before close().
            tracker.stop()
        self.stop_done.emit(ok)

    def _on_stop_finished(self, ok: bool):
        self._stopping = False
        self.status_chip.set_state("idle")
        self._set_controls_running(False)
        if not ok:
            self.start_btn.setEnabled(False)
            self.log_signal.emit(
                "停止超时：设备仍在后台释放，请稍后重启 FocusMic。")
        if self._page == 3:
            self._refresh_report()

    def reacquire(self):
        self.preview_label.set_selecting(False)
        if self.tracker is not None:
            self.tracker.reset_target()
            self.log_signal.emit("已清除目标与框选，下一帧重新选择人脸。")

    def begin_roi_select(self):
        if self.tracker is None:
            return
        self.preview_label.set_selecting(True)
        self.preview_state.setText("框选目标")
        self.log_signal.emit("框选目标：在预览中拖出包含自己脸部的框。")

    def _apply_manual_roi(self, x0: float, y0: float, x1: float, y1: float):
        self.preview_label.set_selecting(False)
        if self.tracker is None:
            return
        self.tracker.set_manual_roi(x0, y0, x1, y1)
        self.preview_state.setText("等待识别")
        self.log_signal.emit("已提交框选区域，等待识别目标。")

    def toggle_bypass(self, checked: bool):
        if self.pipeline is not None:
            self.pipeline.manual_bypass = bool(checked)
        self.bypass_btn.setText("旁路：开" if checked else "旁路：关")
        self.log_signal.emit("手动旁路：" + ("开（原始麦克风）" if checked else "关（分离输出）"))

    def _hotkey_bypass(self):
        if self.pipeline is not None and self.worker is not None and self.worker.is_alive():
            self.bypass_btn.setChecked(not self.bypass_btn.isChecked())

    def _mic_changed(self, _index=None):
        # Save immediately so a choice survives "close to tray" and restarts.
        self._store_settings()

    def _store_settings(self):
        idx = self.mic.currentData()
        for d in self.mic_devices:
            if d["index"] == idx:
                self.settings.mic_name = str(d["name"])
                self.settings.mic_hostapi = str(d["hostapi"])
                break
        self.settings.camera = int(self.camera.currentData())
        self.settings.variant = self.model.currentData()
        self.settings.av_offset_ms = self.av.value()
        self.settings.gain_db = float(self.gain.value())
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

    def _set_cable(self, active: bool, device: str = ""):
        self._cable_connected = bool(active)
        self._cable_device = device if active else ""
        if active:
            text = "● CABLE Input · 已连接"
            if device:
                text += f"\n{device}"
            color = self.theme.teal
        else:
            text = "CABLE Input · 未连接"
            color = self.theme.red if self.pipeline is not None else self.theme.muted
        self.cable_label.setText(text)
        self.cable_label.setStyleSheet(
            f"color:{color};font-size:10px;background:transparent;")

    def _refresh_metrics(self):
        sample = self.metrics.sample()
        running = bool(self.pipeline and self.worker and self.worker.is_alive())
        status = self.pipeline.status() if self.pipeline is not None else None
        tracker_status = self.tracker.status() if self.tracker is not None else None
        if tracker_status is not None and tracker_status.get("manual_expired"):
            self.tracker.manual_expired = False
            self.log_signal.emit("框选超时，已恢复自动选择目标。")
        if (running and tracker_status is not None
                and tracker_status.get("started_at") is not None):
            failed = int(tracker_status.get("read_failures", 0))
            last_frame = tracker_status.get("last_time")
            now = time.perf_counter()
            stale = last_frame is not None and now - last_frame > 3.0
            started = tracker_status.get("started_at")
            no_first_frame = (
                started is not None and not last_frame and now - started > 4.0)
            thread_dead = tracker_status.get("thread_alive") is False
            camera_error = str(tracker_status.get("error") or "").startswith("camera thread:")
            if failed >= 50 or stale or no_first_frame or thread_dead or camera_error:
                reason = "摄像头线程已退出" if thread_dead else (
                    "摄像头没有画面" if no_first_frame else "摄像头画面中断")
                self.log_signal.emit(reason + "，正在停止分离。")
                self.stop()
                return
        if running and status is not None:
            cable_error = (status.get("cable") or {}).get("error")
            if cable_error:
                self.log_signal.emit("CABLE 输出异常，正在停止分离。")
                self.stop()
                return
            monitor_error = (status.get("monitor") or {}).get("error")
            if monitor_error and monitor_error != self._last_monitor_error:
                self.log_signal.emit(f"耳机监听异常，已继续分离：{monitor_error}")
            self._last_monitor_error = monitor_error
        infer = float(status["infer_ms"]) if status else 0.0
        full = float(status["full_latency"]) if status else 0.0
        tracked = float(status["tracked"]) if status else 0.0
        bypass = bool(status and status.get("bypass"))
        cable = status["cable"] if status else {"active": False}
        self.chart_infer.push(infer if running else 0)
        self.chart_full.push(full if running else 0)
        self.chart_cpu.push(sample["app_cpu"])
        self.chart_memory.push(sample["app_ram"])
        self.chart_gpu.push(sample["app_gpu"])
        self.kpi_infer.set_value(f"{infer:.0f}" if running else "—", "ms")
        self.kpi_full.set_value(
            f"{full:.2f}" if running and full > 0 else "—", "s")
        self.kpi_cpu.set_value(f"{sample['app_cpu']:.0f}", "%")
        self.kpi_memory.set_value(f"{sample['app_ram']:.0f}", "MB")
        self.kpi_gpu.set_value(
            f"{sample['app_gpu']:.0f}" if sample["gpu_supported"] else "—", "%")
        self.tile_infer.set_value(f"{infer:.0f}" if running else "—", "ms")
        self.tile_full.set_value(
            f"{full:.2f}" if running and full > 0 else "—", "s")
        self.tile_track.set_value(f"{tracked*100:.0f}" if running else "—", "%")
        if running:
            self.status_chip.set_state("bypass" if bypass else "running")
            self._set_cable(bool(cable.get("active")), cable.get("device", ""))
        elif not self._stopping:
            self.status_chip.set_state("idle")
            self._set_cable(False)
        if bypass != self._last_bypass and running:
            if bypass:
                reason = "手动旁路" if status.get("manual_bypass") else "视觉丢失"
                self.log_signal.emit(f"{reason}：已切换为原始麦克风直通")
            else:
                self.log_signal.emit("已恢复分离输出")
            self._last_bypass = bypass
        if not running and self.worker is not None and not self.worker.is_alive():
            # The pipeline thread ended on its own; run the same non-blocking
            # teardown path instead of touching camera/MediaPipe on the GUI.
            self.stop()
            return

    @staticmethod
    def _duration_text(seconds: float) -> str:
        total = max(0, int(seconds))
        return f"{total // 60:02d}:{total % 60:02d}"

    def _refresh_report_live(self):
        if self._page != 3 or self._stopping or self.pipeline is None:
            return
        self._refresh_report()

    def _refresh_report(self):
        live = self.pipeline is not None and not self._stopping
        data = None
        if self.pipeline is not None:
            try:
                data = self.pipeline.report(seconds=8)
            except Exception:
                data = None
        if data is None:
            data = self.report_snapshot
        if data is None:
            self.report_wave.set_data(None, None)
            self.report_spectrum.set_data(None, None)
            self.report_wave.set_paused(False)
            self.report_spectrum.set_paused(False)
            for card in (self.report_kpi_bypass, self.report_kpi_max,
                         self.report_kpi_suppress, self.report_kpi_full,
                         self.report_kpi_time):
                card.set_value("—", "")
            self.report_stats.setText("开始分离后显示本次报告")
            return
        raw = data.get("raw")
        out = data.get("out")
        sample_rate = int(data.get("sample_rate", 16000))
        self.report_wave.set_data(raw, out, sample_rate)
        self.report_spectrum.set_data(raw, out, sample_rate)
        self.report_wave.set_paused(not live)
        self.report_spectrum.set_paused(not live)
        self.report_kpi_bypass.set_value(
            str(int(data.get("bypass_count", 0))), "次")
        max_infer = float(data.get("max_infer_ms", 0.0))
        self.report_kpi_max.set_value(
            f"{max_infer:.0f}" if max_infer > 0 else "—", "ms")
        suppression_samples = int(data.get("suppression_samples", 0))
        suppression = float(data.get("suppression_db", 0.0))
        self.report_kpi_suppress.set_value(
            f"{suppression:.1f}" if suppression_samples else "—", "dB")
        full = float(data.get("full_latency", 0.0))
        self.report_kpi_full.set_value(
            f"{full:.2f}" if full > 0 else "—", "s")
        self.report_kpi_time.set_value(
            self._duration_text(float(data.get("elapsed", 0.0))), "")
        cable = data.get("cable") or {}
        self.report_stats.setText(
            f"窗口 {int(data.get('windows', 0))} · "
            f"跳过 {int(data.get('skipped', 0))} · "
            f"跟踪 {float(data.get('tracked', 0.0))*100:.0f}% · "
            f"CABLE {'已连接' if cable.get('active') else '未连接'} · "
            f"手动旁路 {int(data.get('manual_bypass_count', 0))} 次"
            f"{'' if live else ' · 已停止'}")

    def _maybe_show_onboarding(self):
        if not self.settings.onboarding_done and not self._onboarding_open:
            self._show_onboarding()

    def _show_onboarding(self, checked: bool = False):
        if self._onboarding_open:
            return
        if self.pipeline is not None:
            self.log_signal.emit("请先停止分离，再运行首次向导。")
            return
        self._onboarding_open = True
        accepted = False
        try:
            dialog = OnboardingDialog(
                self.settings, self.theme, self.mic_devices, self)
            accepted = dialog.exec()
        finally:
            self._onboarding_open = False
        if not accepted:
            return
        if dialog.applied:
            self._apply_home_settings()
            self._log_onboarding_devices()
        self.settings.onboarding_done = True
        self._persist_settings()
        self._sync_settings_page()
        if dialog.applied:
            self.log_signal.emit("首次设置完成。")
        else:
            self.log_signal.emit("已跳过首次设置，可在设置里重新运行。")

    def _log_onboarding_devices(self):
        mic = self.mic.currentText() or "未选择"
        camera = self.camera.currentText() or "未选择"
        self.log_signal.emit(f"设备：{mic} / {camera}")

    def _show_settings_page(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.show_page(4)

    def _toggle_theme(self, checked: bool):
        self.settings.theme_mode = "dark" if checked else "light"
        self.theme = theme_for(self.settings.theme_mode, self._system_dark())
        self._apply_theme()
        self._sync_settings_page()
        try:
            save_settings(self.settings)
        except OSError:
            pass

    def _system_dark_changed(self, *args):
        if self.settings.theme_mode == "system":
            self.theme = theme_for("system", self._system_dark())
            self._apply_theme()
            self._sync_settings_page()

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
        if hasattr(self, "cable_label"):
            self._set_cable(self._cable_connected, self._cable_device)
        if hasattr(self, "preview_label"):
            self.preview_label.update()

    def _setup_tray(self):
        try:
            self._tray = QSystemTrayIcon(QIcon(str(ICON)), self)
            self._tray.setToolTip("FocusMic")
            # No QMenu here: the context menu is a real Win32 popup.
            self._tray.activated.connect(self._tray_activated)
            self._tray.show()
        except Exception as exc:
            logging.getLogger("focusmic").warning("tray unavailable: %s", exc)
            self._tray = None

    def _show_main_window(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.Context:
            self._show_native_tray_menu()
        elif reason == QSystemTrayIcon.DoubleClick:
            self._show_main_window()

    def _show_native_tray_menu(self):
        running = bool(self.pipeline and self.worker and self.worker.is_alive())
        visible = self.isVisible() and not self.isMinimized()
        items = [
            ("隐藏 FocusMic" if visible else "显示 FocusMic", True, 1),
            ("开始分离", not running, 2),
            ("停止", running, 3),
            ("切换旁路", running, 4),
            None,
            ("设置…", True, 5),
            None,
            ("退出", True, 6),
        ]
        try:
            choice = show_native_menu(int(self.winId()), items)
        except Exception as exc:
            logging.getLogger("focusmic").warning("tray menu failed: %s", exc)
            return
        if choice == 1:
            if visible:
                self.hide()
            else:
                self._show_main_window()
        elif choice == 2:
            self.start()
        elif choice == 3:
            self.stop()
        elif choice == 4:
            self.bypass_btn.toggle()
        elif choice == 5:
            self._show_settings_page()
        elif choice == 6:
            self._really_quit = True
            self.close()

    def _register_hotkey(self) -> bool:
        if self._hotkey_handle is not None and self._keyboard is not None:
            try:
                self._keyboard.remove_hotkey(self._hotkey_handle)
            except Exception:
                pass
            self._hotkey_handle = None
        if not self.settings.hotkey_enabled:
            return True
        problem = self._hotkey_problem(self.settings.hotkey)
        if problem:
            logging.getLogger("focusmic").warning("hotkey rejected: %s", problem)
            return False
        try:
            import keyboard
            keyboard.parse_hotkey(self.settings.hotkey)
            self._keyboard = keyboard
            self._hotkey_handle = keyboard.add_hotkey(
                self.settings.hotkey, self.hotkey_signal.emit,
                trigger_on_release=True)
            logging.getLogger("focusmic").info("hotkey registered: %s", self.settings.hotkey)
            return True
        except Exception as exc:
            self._hotkey_handle = None
            logging.getLogger("focusmic").warning("hotkey unavailable: %s", exc)
            return False

    def closeEvent(self, event):
        app = QApplication.instance()
        closing_system = bool(
            app is not None and getattr(app, "closingDown", lambda: False)())
        if (self.settings.close_to_tray and self._tray is not None
                and not self._really_quit and not closing_system):
            self._store_settings()
            self.hide()
            event.ignore()
            if not self._tray_notice_shown:
                self._tray_notice_shown = True
                try:
                    self._tray.showMessage(
                        "FocusMic", "程序仍在后台运行，右键托盘图标可退出。",
                        QSystemTrayIcon.Information, 3000)
                except Exception:
                    pass
            return
        self._really_quit = True
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
