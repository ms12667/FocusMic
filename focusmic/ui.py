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
    QColor, QFont, QFontMetrics, QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QKeySequenceEdit,
    QLabel, QMainWindow, QPlainTextEdit, QPushButton, QScrollArea, QSlider,
    QSizePolicy, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from . import __version__
from . import runtime as runtime_env
from .audio import (
    LiveAudio, input_device_label, resolve_input, visible_input_devices,
)
from .cameras import list_cameras
from .charts import KpiCard, MetricCard
from .config import Settings, load_settings, save_settings
from .controls import LinkLabel, SettingRow, ThemedLabel, ToggleSwitch
from .i18n import (
    AUTO_LANGUAGE, LANGUAGES, current_language, language_info, set_language, t,
    ui_font_family,
)
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
            color, text = self._theme.accent, t("status.bypass")
        elif state == "running":
            color, text = self._theme.teal, t("status.running")
        elif state == "stopping":
            color, text = self._theme.accent, t("status.stopping")
        else:
            color, text = self._theme.muted, t("status.idle")
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
            font = QFont(ui_font_family(), 11)
            font.setWeight(QFont.Weight.Medium)
            painter.setFont(font)
            painter.drawText(
                QRectF(12, cy + 50, self.width() - 24, 26),
                Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                t("preview.camera_off"))
            painter.setPen(QColor(self._theme.faint))
            font.setPointSize(9)
            font.setWeight(QFont.Weight.Normal)
            painter.setFont(font)
            painter.drawText(
                QRectF(12, cy + 76, self.width() - 24, 42),
                Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                t("preview.start_hint"))
        if self._selecting:
            painter.setPen(QColor(self._theme.accent))
            painter.setFont(QFont(ui_font_family(), 9))
            painter.drawText(
                QRectF(10, 6, self.width() - 20, 40),
                Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                t("preview.select_hint"))
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
        # Apply the saved language before any label is constructed.
        set_language(self.settings.language)
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
        self._pending_language = None

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

    def _poll_devices(self, announce: bool = True):
        """Refresh microphone list on USB hot-plug and stop on device loss."""
        try:
            devices = visible_input_devices(sd, self.settings.show_all_mics)
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
            self.mic.addItem(input_device_label(d), d["index"])
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
        if announce and added:
            self.log_signal.emit(t(
                "log.mic_connected", names=t("list.separator").join(added)))
        if announce and removed:
            self.log_signal.emit(t(
                "log.mic_disconnected", names=t("list.separator").join(removed)))
        running = bool(self.pipeline and self.worker and self.worker.is_alive())
        lost = old_identity is not None and not matching
        if running and lost:
            self.log_signal.emit(t("log.mic_lost"))
            self.stop()

    def _build(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        nav_items = (
            ("house", t("nav.home")),
            ("book-open", t("nav.tutorial")),
            ("chart-line", t("nav.performance")),
            ("activity", t("nav.report")),
            ("settings", t("nav.settings")),
            ("info", t("nav.about")),
        )
        nav_font = QFont(ui_font_family())
        nav_font.setPointSizeF(10.2)
        nav_font.setWeight(QFont.Weight.Medium)
        nav_width = max(
            208, min(270, max(
                QFontMetrics(nav_font).horizontalAdvance(label)
                for _, label in nav_items) + 84))

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(nav_width)
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
        local = ThemedLabel(t("app.tagline"), self.theme, role="muted", size=10)
        names.addWidget(name)
        names.addWidget(local)
        brand.addLayout(names)
        brand.addStretch(1)
        side.addLayout(brand)
        side.addSpacing(22)

        self.nav_buttons = []
        for index, (icon_name, text) in enumerate(nav_items):
            button = NavButton(icon_name, text, self.theme)
            button.clicked.connect(lambda _=False, i=index: self.show_page(i))
            self.nav_buttons.append(button)
            side.addWidget(button)
        side.addStretch(1)

        tools = QHBoxLayout()
        tools.setSpacing(4)
        self.theme_button = MorphIconButton("moon", "sun", self.theme, size=18)
        self.theme_button.setToolTip(t("settings.appearance.title"))
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
        self.page_title = QLabel(t("page.home.title"))
        self.page_title.setObjectName("PageTitle")
        self.page_subtitle = QLabel(t("page.home.subtitle"))
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
        self._append_activity(t("log.ready"))

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
            t("home.runtime.missing"),
            self.theme, role="text", size=10, wrap=True)
        banner_row.addWidget(self.runtime_banner_label, 1)
        runtime_help = QPushButton(t("home.runtime.help"))
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
        pv_head.addWidget(_card_title(t("home.camera_preview"), self.theme))
        pv_head.addStretch(1)
        self.preview_state = ThemedLabel(
            t("home.preview.off"), self.theme, role="muted", size=10)
        pv_head.addWidget(self.preview_state)
        pv.addLayout(pv_head)
        self.preview_label = PreviewCanvas(self.theme)
        self.preview_label.setFixedHeight(380)
        self.preview_label.roi_selected.connect(self._apply_manual_roi)
        pv.addWidget(self.preview_label)
        left.addWidget(preview_card)

        stats = QHBoxLayout()
        stats.setSpacing(8)
        self.tile_infer = InfoTile(t("home.tile.infer"), "ms", self.theme)
        self.tile_full = InfoTile(t("home.tile.full"), "s", self.theme)
        self.tile_track = InfoTile(t("home.tile.track"), "%", self.theme)
        for tile in (self.tile_infer, self.tile_full, self.tile_track):
            stats.addWidget(tile, 1)
        left.addLayout(stats)
        top.addWidget(left_column, 0)

        controls = QFrame()
        controls.setObjectName("Card")
        form = QVBoxLayout(controls)
        form.setContentsMargins(15, 13, 15, 13)
        form.setSpacing(7)
        form.addWidget(_card_title(t("home.quick.title"), self.theme))
        form.addWidget(_muted(t("home.quick.subtitle"), self.theme, 10))

        self.mic = QComboBox()
        self.mic.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mic.setMinimumContentsLength(14)
        self.mic_devices = visible_input_devices(sd, self.settings.show_all_mics)
        for d in self.mic_devices:
            self.mic.addItem(input_device_label(d), d["index"])
        target = -1
        try:
            default_idx, _ = resolve_input(sd, None)
            target = self.mic.findData(default_idx)
        except Exception:
            target = -1
        if target < 0:
            # The PortAudio default may be a hidden MME twin. Prefer a
            # physical WASAPI endpoint over a virtual cable/Steam device.
            for i, device in enumerate(self.mic_devices):
                name = str(device["name"]).upper()
                if "CABLE" not in name and "STEAM" not in name:
                    target = i
                    break
        if target < 0 and self.mic.count():
            target = 0
        if target >= 0:
            self.mic.setCurrentIndex(target)
        self._mic_signature = self._device_signature(self.mic_devices)
        self.camera = QComboBox()
        self.camera_infos = list_cameras()
        for info in self.camera_infos:
            self.camera.addItem(
                info.label(t("home.camera_item", index=info.index)), info.index)
        self.model = QComboBox()
        self.model.addItem(t("home.model.small"), "small")
        self.model.addItem(t("home.model.big"), "big")
        form.addWidget(_muted(t("home.label.mic"), self.theme, 10))
        form.addWidget(self.mic)
        form.addWidget(_muted(t("home.label.camera"), self.theme, 10))
        form.addWidget(self.camera)
        form.addWidget(_muted(t("home.label.model"), self.theme, 10))
        form.addWidget(self.model)

        self.monitor = ToggleSwitch(self.theme)
        self.monitor_row = SettingRow(
            t("home.monitor.title"), t("home.monitor.desc"),
            self.monitor, self.theme)
        form.addWidget(self.monitor_row)

        av_row = QHBoxLayout()
        av_row.setSpacing(7)
        av_row.addWidget(_muted(t("home.av"), self.theme, 10))
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
        gain_row.addWidget(_muted(t("home.gain"), self.theme, 10))
        self.gain = QSlider(Qt.Horizontal)
        self.gain.setRange(-12, 12)
        self.gain.setSingleStep(1)
        self.gain_value = ThemedLabel(
            f"{int(self.settings.gain_db)} dB", self.theme, role="muted", size=10, mono=True)
        self.gain.valueChanged.connect(self._gain_changed)
        gain_row.addWidget(self.gain, 1)
        gain_row.addWidget(self.gain_value)
        form.addLayout(gain_row)
        form.addWidget(_muted(t("home.gain.hint"), self.theme, 9))

        run_row = QHBoxLayout()
        run_row.setSpacing(7)
        self.start_btn = QPushButton(t("home.start"))
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton(t("home.stop"))
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        run_row.addWidget(self.start_btn, 2)
        run_row.addWidget(self.stop_btn, 1)
        form.addLayout(run_row)

        tools_row = QHBoxLayout()
        tools_row.setSpacing(7)
        self.reacquire_btn = QPushButton(t("home.reacquire"))
        self.reacquire_btn.setEnabled(False)
        self.reacquire_btn.setToolTip(t("home.reacquire.tip"))
        self.reacquire_btn.clicked.connect(self.reacquire)
        self.roi_btn = QPushButton(t("home.roi"))
        self.roi_btn.setToolTip(t("home.roi.tip"))
        self.roi_btn.setEnabled(False)
        self.roi_btn.clicked.connect(self.begin_roi_select)
        self.bypass_btn = QPushButton(t("home.bypass.off"))
        self.bypass_btn.setCheckable(True)
        self.bypass_btn.setEnabled(False)
        self.bypass_btn.toggled.connect(self.toggle_bypass)
        tools_row.addWidget(self.reacquire_btn)
        tools_row.addWidget(self.roi_btn)
        tools_row.addWidget(self.bypass_btn)
        form.addLayout(tools_row)
        form.addStretch(1)
        self.cable_label = ThemedLabel(
            t("home.cable.disconnected"), self.theme, role="muted", size=10, wrap=True)
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
        console_head.addWidget(_card_title(t("home.run_output"), self.theme))
        console_head.addStretch(1)
        console_head.addWidget(ThemedLabel(
            t("home.local_only"), self.theme, role="faint", size=9))
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
            t("tutorial.intro.title"), t("tutorial.intro.subtitle"))
        intro_box.addWidget(ThemedLabel(
            t("tutorial.intro.body"),
            self.theme, role="muted", size=11, wrap=True))
        box.addWidget(intro)

        prep, prep_box = self._settings_card(
            t("tutorial.prep.title"), t("tutorial.prep.subtitle"))
        for text in (
            t("tutorial.prep.b1"),
            t("tutorial.prep.b2"),
            t("tutorial.prep.b3"),
            t("tutorial.prep.b4"),
        ):
            prep_box.addWidget(self._tutorial_bullet(text))
        box.addWidget(prep)

        first, first_box = self._settings_card(
            t("tutorial.first.title"), t("tutorial.first.subtitle"))
        first_steps = (
            (t("tutorial.first.s1"), t("tutorial.first.s1d")),
            (t("tutorial.first.s2"), t("tutorial.first.s2d")),
            (t("tutorial.first.s3"), t("tutorial.first.s3d")),
            (t("tutorial.first.s4"), t("tutorial.first.s4d")),
            (t("tutorial.first.s5"), t("tutorial.first.s5d")),
            (t("tutorial.first.s6"), t("tutorial.first.s6d")),
        )
        for i, (title, desc) in enumerate(first_steps, 1):
            first_box.addWidget(self._tutorial_step(i, title, desc))
        box.addWidget(first)

        states, states_box = self._settings_card(
            t("tutorial.states.title"), t("tutorial.states.subtitle"))
        for text in (
            t("tutorial.states.b1"),
            t("tutorial.states.b2"),
            t("tutorial.states.b3"),
            t("tutorial.states.b4"),
            t("tutorial.states.b5"),
            t("tutorial.states.b6"),
        ):
            states_box.addWidget(self._tutorial_bullet(text))
        box.addWidget(states)

        tips, tips_box = self._settings_card(
            t("tutorial.tips.title"), t("tutorial.tips.subtitle"))
        for text in (
            t("tutorial.tips.b1"),
            t("tutorial.tips.b2"),
            t("tutorial.tips.b3"),
            t("tutorial.tips.b4"),
            t("tutorial.tips.b5"),
        ):
            tips_box.addWidget(self._tutorial_bullet(text))
        box.addWidget(tips)

        faq, faq_box = self._settings_card(
            t("tutorial.faq.title"), t("tutorial.faq.subtitle"))
        for question, answer in (
            (t("tutorial.faq.q1"), t("tutorial.faq.a1")),
            (t("tutorial.faq.q2"), t("tutorial.faq.a2")),
            (t("tutorial.faq.q3"), t("tutorial.faq.a3")),
            (t("tutorial.faq.q4"), t("tutorial.faq.a4")),
            (t("tutorial.faq.q5"), t("tutorial.faq.a5")),
        ):
            faq_box.addWidget(self._tutorial_qa(question, answer))
        box.addWidget(faq)

        privacy, privacy_box = self._settings_card(
            t("tutorial.privacy.title"), t("tutorial.privacy.subtitle"))
        for text in (
            t("tutorial.privacy.b1"),
            t("tutorial.privacy.b2"),
            t("tutorial.privacy.b3"),
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
        self.kpi_infer = KpiCard(t("perf.infer"), "—", "ms", self.theme)
        self.kpi_full = KpiCard(t("perf.full"), "—", "s", self.theme,
                                accent_role="accent")
        self.kpi_cpu = KpiCard(t("perf.cpu"), "—", "%", self.theme)
        self.kpi_memory = KpiCard(t("perf.memory"), "—", "MB", self.theme)
        self.kpi_gpu = KpiCard(t("perf.gpu"), "—", "%", self.theme)
        for card in (self.kpi_infer, self.kpi_full, self.kpi_cpu,
                     self.kpi_memory, self.kpi_gpu):
            kpis.addWidget(card, 1)
        layout.addLayout(kpis)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.chart_infer = MetricCard(
            t("perf.infer"), "ms", self.theme.blue, self.theme, color_role="blue")
        self.chart_full = MetricCard(
            t("perf.full"), "s", self.theme.accent, self.theme, color_role="accent")
        self.chart_cpu = MetricCard(
            t("perf.cpu"), "%", self.theme.teal, self.theme,
            fixed_max=100, color_role="teal")
        self.chart_memory = MetricCard(
            t("perf.memory"), "MB", self.theme.blue, self.theme, color_role="blue")
        self.chart_gpu = MetricCard(
            t("perf.gpu"), "%", self.theme.red, self.theme,
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
        note_box.addWidget(_card_title(t("perf.note.title"), self.theme))
        note_box.addWidget(ThemedLabel(
            t("perf.note.body"),
            self.theme, role="muted", size=10, wrap=True))
        note_box.addStretch(1)
        grid.addWidget(note_card, 2, 1)
        layout.addLayout(grid, 1)
        self.perf_note = _muted(t("perf.footer"), self.theme, 10)
        layout.addWidget(self.perf_note)
        return page

    def _build_report(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        kpis = QHBoxLayout()
        kpis.setSpacing(8)
        self.report_kpi_bypass = KpiCard(
            t("report.bypass"), "—", t("unit.times"), self.theme)
        self.report_kpi_max = KpiCard(
            t("report.max_infer"), "—", "ms", self.theme)
        self.report_kpi_suppress = KpiCard(
            t("report.suppress"), "—", "dB", self.theme, accent_role="teal")
        self.report_kpi_full = KpiCard(
            t("report.full"), "—", "s", self.theme, accent_role="accent")
        self.report_kpi_time = KpiCard(
            t("report.elapsed"), "—", "", self.theme)
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
        wave_box.addWidget(_card_title(t("report.wave.title"), self.theme))
        wave_box.addWidget(ThemedLabel(
            t("report.wave.desc"),
            self.theme, role="muted", size=10, wrap=True))
        self.report_wave = WaveformCompare(self.theme)
        wave_box.addWidget(self.report_wave, 1)
        middle.addWidget(wave_card, 2)

        spectrum_card = QFrame()
        spectrum_card.setObjectName("Card")
        spectrum_box = QVBoxLayout(spectrum_card)
        spectrum_box.setContentsMargins(15, 13, 15, 13)
        spectrum_box.setSpacing(6)
        spectrum_box.addWidget(_card_title(t("report.spectrum.title"), self.theme))
        spectrum_box.addWidget(ThemedLabel(
            t("report.spectrum.desc"),
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
        console_head.addWidget(_card_title(t("report.run_output"), self.theme))
        console_head.addStretch(1)
        self.report_stats = ThemedLabel(
            t("report.waiting"), self.theme, role="faint", size=9)
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
            t("settings.startup.title"), t("settings.startup.subtitle"))
        self.settings_startup = ToggleSwitch(self.theme)
        self.settings_startup.setAccessibleName(t("settings.autostart.title"))
        self.settings_startup.setChecked(self.settings.start_with_windows)
        self.settings_startup.toggled.connect(self._on_startup_toggle)
        startup_box.addWidget(SettingRow(
            t("settings.autostart.title"),
            t("settings.autostart.desc"),
            self.settings_startup, self.theme))
        self.settings_tray = ToggleSwitch(self.theme)
        self.settings_tray.setAccessibleName(t("settings.tray.title"))
        self.settings_tray.setChecked(self.settings.close_to_tray)
        self.settings_tray.toggled.connect(self._on_close_to_tray_toggle)
        startup_box.addWidget(SettingRow(
            t("settings.tray.title"),
            t("settings.tray.desc"),
            self.settings_tray, self.theme))
        left.addWidget(startup_card)

        appearance_card, appearance_box = self._settings_card(
            t("settings.appearance.title"), t("settings.appearance.subtitle"))
        self.settings_follow = ToggleSwitch(self.theme)
        self.settings_follow.setAccessibleName(t("settings.follow.title"))
        self.settings_follow.setChecked(self.settings.theme_mode == "system")
        self.settings_follow.toggled.connect(self._on_follow_toggle)
        appearance_box.addWidget(SettingRow(
            t("settings.follow.title"),
            t("settings.follow.desc"),
            self.settings_follow, self.theme))
        self.settings_theme = QComboBox()
        self.settings_theme.addItem(t("settings.theme.dark"), "dark")
        self.settings_theme.addItem(t("settings.theme.light"), "light")
        self.settings_theme.currentIndexChanged.connect(self._on_settings_theme)
        appearance_box.addWidget(SettingRow(
            t("settings.theme.title"), t("settings.theme.desc"),
            self.settings_theme, self.theme))
        left.addWidget(appearance_card)

        language_card, language_box = self._settings_card(
            t("settings.language.title"), t("settings.language.subtitle"))
        self.settings_language = QComboBox()
        self.settings_language.addItem(
            t("settings.language.auto",
              language=language_info(AUTO_LANGUAGE).native),
            AUTO_LANGUAGE)
        for language in LANGUAGES:
            self.settings_language.addItem(language.native, language.code)
        self.settings_language.currentIndexChanged.connect(self._on_language_changed)
        language_box.addWidget(SettingRow(
            t("settings.language.label"),
            t("settings.language.desc"),
            self.settings_language, self.theme))
        left.addWidget(language_card)
        left.addStretch(1)

        devices_card, devices_box = self._settings_card(
            t("settings.devices.title"), t("settings.devices.subtitle"))
        self.settings_all_mics = ToggleSwitch(self.theme)
        self.settings_all_mics.setAccessibleName(t("settings.all_mics.title"))
        self.settings_all_mics.setChecked(self.settings.show_all_mics)
        self.settings_all_mics.toggled.connect(self._on_show_all_mics)
        devices_box.addWidget(SettingRow(
            t("settings.all_mics.title"),
            t("settings.all_mics.desc"),
            self.settings_all_mics, self.theme))
        right.addWidget(devices_card)

        hotkey_card, hotkey_box = self._settings_card(
            t("settings.hotkey.title"), t("settings.hotkey.subtitle"))
        self.settings_hotkey_enabled = ToggleSwitch(self.theme)
        self.settings_hotkey_enabled.setAccessibleName(
            t("settings.hotkey.enable.title"))
        self.settings_hotkey_enabled.setChecked(self.settings.hotkey_enabled)
        self.settings_hotkey_enabled.toggled.connect(self._on_hotkey_enabled)
        hotkey_box.addWidget(SettingRow(
            t("settings.hotkey.enable.title"),
            t("settings.hotkey.enable.desc"),
            self.settings_hotkey_enabled, self.theme))
        edit_row = QHBoxLayout()
        edit_row.setSpacing(10)
        edit_row.addWidget(_muted(t("settings.hotkey.combo"), self.theme, 10))
        edit_row.addStretch(1)
        self.settings_hotkey = QKeySequenceEdit(
            QKeySequence(_hotkey_display(self.settings.hotkey)))
        self.settings_hotkey.setMaximumWidth(190)
        self.settings_hotkey.setEnabled(self.settings.hotkey_enabled)
        edit_row.addWidget(self.settings_hotkey)
        hotkey_box.addLayout(edit_row)
        hotkey_box.addWidget(ThemedLabel(
            t("settings.hotkey.hint"),
            self.theme, role="faint", size=10, wrap=True))
        right.addWidget(hotkey_card)

        paths_card, paths_box = self._settings_card(
            t("settings.paths.title"), t("settings.paths.subtitle"))
        for label, path in (
                (t("settings.paths.config"), r"%APPDATA%\FocusMic\config.json"),
                (t("settings.paths.log"),
                 r"%LOCALAPPDATA%\FocusMic\logs\focusmic.log")):
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
            t("settings.footer"), self.theme, role="muted", size=10, wrap=True)
        self.settings_status.setMinimumWidth(0)
        self.settings_status.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred)
        footer.addWidget(self.settings_status, 1)
        wizard = QPushButton(t("settings.wizard"))
        wizard.setObjectName("ghost")
        wizard.clicked.connect(self._show_onboarding)
        footer.addWidget(wizard)
        save = QPushButton(t("settings.save"))
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
                   self.settings_theme, self.settings_language,
                   self.settings_all_mics, self.settings_hotkey)
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
            language_index = self.settings_language.findData(self.settings.language)
            if language_index >= 0:
                self.settings_language.setCurrentIndex(language_index)
            self.settings_all_mics.setChecked(self.settings.show_all_mics)
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
            self.log_signal.emit(t("log.settings_save_failed", error=exc))

    def _on_close_to_tray_toggle(self, checked: bool):
        self.settings.close_to_tray = bool(checked)
        self._persist_settings()

    def _on_startup_toggle(self, checked: bool):
        try:
            set_startup(bool(checked))
            self.settings.start_with_windows = bool(checked)
            self._persist_settings()
            self._set_settings_status(t(
                "settings.status.autostart_on" if checked
                else "settings.status.autostart_off"))
            self.log_signal.emit(t(
                "log.autostart",
                state=t("common.on") if checked else t("common.off")))
        except Exception as exc:
            self.settings_startup.blockSignals(True)
            self.settings_startup.setChecked(not checked)
            self.settings_startup.blockSignals(False)
            self._set_settings_status(
                t("settings.status.autostart_failed", error=exc), error=True)

    def _on_follow_toggle(self, checked: bool):
        self.settings.theme_mode = "system" if checked else self.settings_theme.currentData()
        if not self.settings.theme_mode:
            self.settings.theme_mode = "dark" if self.theme.dark else "light"
        self.settings_theme.setEnabled(not checked)
        self.theme = theme_for(self.settings.theme_mode, self._system_dark())
        self._apply_theme()
        self._persist_settings()
        self._set_settings_status(t(
            "settings.status.theme_system" if checked
            else "settings.status.theme_fixed"))

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
        self._set_settings_status(t("settings.status.theme_switched"))

    def _on_show_all_mics(self, checked: bool):
        if self.pipeline is not None or self._stopping:
            self.settings_all_mics.blockSignals(True)
            self.settings_all_mics.setChecked(not checked)
            self.settings_all_mics.blockSignals(False)
            return
        self.settings.show_all_mics = bool(checked)
        self._persist_settings()
        self._mic_signature = None
        self._poll_devices(announce=False)
        if self.mic.currentData() is not None:
            self._store_settings()
        self._set_settings_status(t("settings.status.devices_updated"))

    def _on_language_changed(self, _index=None):
        code = self.settings_language.currentData()
        if not code:
            return
        self.settings.language = str(code)
        self._persist_settings()
        if self.pipeline is not None or self._stopping:
            self._pending_language = str(code)
            self._set_settings_status(t("settings.status.language_after_stop"))
            return
        self._pending_language = str(code)
        # Do not delete the combo box inside its own signal handler.
        QTimer.singleShot(0, self._apply_pending_language)

    def _apply_pending_language(self):
        code = self._pending_language
        if not code:
            return
        self._pending_language = None
        set_language(code)
        app = QApplication.instance()
        if app is not None:
            app.setFont(QFont(ui_font_family(), 10))
        self._rebuild_ui()
        self._set_settings_status(t("settings.status.language_changed"))

    def _rebuild_ui(self):
        """Rebuild all widgets in the new language, preserving the session."""
        page = self._page
        log_text = self.log_view.toPlainText() if hasattr(self, "log_view") else ""
        report_text = (
            self.report_log.toPlainText() if hasattr(self, "report_log") else "")
        self._page = -1
        self._build()
        self._apply_theme()
        self._refresh_runtime_banner()
        last = len(self.nav_buttons) - 1
        self.show_page(page if 0 <= page <= last else 0)
        if log_text:
            self.log_view.setPlainText(log_text)
            bar = self.log_view.verticalScrollBar()
            bar.setValue(bar.maximum())
        if report_text:
            self.report_log.setPlainText(report_text)
            bar = self.report_log.verticalScrollBar()
            bar.setValue(bar.maximum())
        self._refresh_metrics()

    @staticmethod
    def _hotkey_problem(hotkey: str) -> str | None:
        parts = [p for p in str(hotkey).lower().replace(" ", "").split("+") if p]
        modifiers = {"ctrl", "alt", "shift"}
        if not parts:
            return t("hotkey.error.empty")
        if any(p in {"meta", "win", "windows", "cmd"} for p in parts):
            return t("hotkey.error.meta")
        if len(parts) < 2 or not any(p in modifiers for p in parts):
            return t("hotkey.error.modifier")
        if all(p in modifiers for p in parts):
            return t("hotkey.error.normal")
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
            self._set_settings_status(t("settings.status.hotkey_failed"), error=True)
            self._persist_settings()
            return
        self._persist_settings()
        self._set_settings_status(t(
            "settings.status.hotkey_on" if checked
            else "settings.status.hotkey_off"))

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
            self._set_settings_status(
                t("settings.status.saved_hotkey_failed"), error=True)
        else:
            self._set_settings_status(t(
                "settings.status.saved", time=time.strftime("%H:%M:%S")))
        self.log_signal.emit(t("log.settings_saved"))

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
            t("about.version", version=__version__),
            self.theme, role="muted", size=11))
        box.addSpacing(8)
        box.addWidget(ThemedLabel(
            t("about.tagline"),
            self.theme, role="text", size=12, wrap=True))
        box.addSpacing(12)
        for text in (t("about.badge.local"),
                     t("about.badge.private"),
                     t("about.badge.telemetry")):
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
            t("about.requirements.line"),
            self.theme, role="faint", size=10, wrap=True))
        layout.addWidget(brand)

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        right = QVBoxLayout(body)
        right.setContentsMargins(0, 0, 8, 0)
        right.setSpacing(10)

        right.addWidget(self._about_card(
            t("about.what.title"), t("about.what.body")))

        right.addWidget(self._about_card(
            t("about.effect.title"), t("about.effect.body")))

        right.addWidget(self._about_card(
            t("about.noise.title"), t("about.noise.body")))

        right.addWidget(self._about_card(
            t("about.req.title"), t("about.req.body")))

        right.addWidget(self._about_card(
            t("about.perf.title"), t("about.perf.body")))

        right.addWidget(self._about_card(
            t("about.quick.title"), t("about.quick.body")))

        right.addWidget(self._about_card(
            t("about.privacy.title"), t("about.privacy.body")))

        lic = QFrame()
        lic.setObjectName("Card")
        lic_box = QVBoxLayout(lic)
        lic_box.setContentsMargins(18, 15, 18, 15)
        lic_box.setSpacing(8)
        lic_box.addWidget(_card_title(t("about.license.title"), self.theme))
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
            ("VB-CABLE", t("about.vbcable")),
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
        links_box.addWidget(_card_title(t("about.links.title"), self.theme))
        links_box.addWidget(LinkLabel(
            "github.com/ms12667/FocusMic",
            "https://github.com/ms12667/FocusMic", self.theme, size=11))
        links_box.addWidget(LinkLabel(
            t("about.links.releases"),
            "https://github.com/ms12667/FocusMic/releases", self.theme, size=11))
        right.addWidget(links)

        status = runtime_env.check_installed()
        build = QFrame()
        build.setObjectName("Card")
        build_box = QVBoxLayout(build)
        build_box.setContentsMargins(18, 15, 18, 15)
        build_box.setSpacing(8)
        build_box.addWidget(_card_title(t("about.build.title"), self.theme))
        build_grid = QGridLayout()
        build_grid.setHorizontalSpacing(18)
        build_grid.setVerticalSpacing(7)
        torch_version = status.torch_version or t("about.build.not_installed")
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
            (t("page.home.title"), t("page.home.subtitle")),
            (t("page.tutorial.title"), t("page.tutorial.subtitle")),
            (t("page.performance.title"), t("page.performance.subtitle")),
            (t("page.report.title"), t("page.report.subtitle")),
            (t("page.settings.title"), t("page.settings.subtitle")),
            (t("page.about.title"), t("page.about.subtitle")),
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
        if hasattr(self, "settings_all_mics"):
            self.settings_all_mics.setEnabled(not running)
        if not running:
            if self.bypass_btn.isChecked():
                self.bypass_btn.setChecked(False)
            self.bypass_btn.setText(t("home.bypass.off"))

    def _refresh_runtime_banner(self):
        status = runtime_env.check_installed()
        self.runtime_banner.setVisible(not status.ok)
        if status.ok:
            self.start_btn.setToolTip("")
        else:
            self.runtime_banner_label.setText(t("home.runtime.missing"))
            self.start_btn.setToolTip(status.message())

    def _show_runtime_dialog(self):
        RuntimeDialog(self.theme, self).exec()
        self._refresh_runtime_banner()

    def start(self):
        if self._stopping:
            self.log_signal.emit(t("log.stopping_previous"))
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
            self.log_signal.emit(t("log.device_init_failed", error=exc))
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
        self.preview_state.setText(t("home.preview.starting"))
        self.log_signal.emit(t("log.loading_model"))
        self.log_signal.emit(t(
            "log.start_summary", mic=self.mic.currentText(), camera=camera,
            model=self.model.currentText(), av=av,
            gain=int(self.settings.gain_db)))
        self.worker = threading.Thread(
            target=self._run, args=(pipeline,), daemon=True, name="pipeline")
        self.worker.start()

    def _run(self, pipeline):
        try:
            pipeline.load("cuda")
            self.log_signal.emit(t("log.model_ready"))
            pipeline.run()
        except Exception as exc:
            self.log_signal.emit(t("log.run_failed", error=exc))
        finally:
            self.log_signal.emit(t("log.stopped"))

    def stop(self):
        if self._stopping:
            return
        pipeline = self.pipeline
        tracker = self.tracker
        worker = self.worker
        if pipeline is None and worker is None:
            self.preview_label.clear()
            self.preview_state.setText(t("home.preview.off"))
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
        self.preview_state.setText(t("home.preview.off"))
        self._set_cable(False)
        self.status_chip.set_state("stopping")
        self._set_controls_running(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self._last_bypass = False
        if self._page == 3:
            self._refresh_report()
        self.log_signal.emit(t("status.stopping"))
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
            self.log_signal.emit(t("log.stop_timeout"))
        if self._page == 3:
            self._refresh_report()
        if self._pending_language:
            if ok:
                QTimer.singleShot(0, self._apply_pending_language)
            else:
                # Device teardown timed out; keep the saved language for the
                # next launch instead of rebuilding a half-stopped UI.
                self._pending_language = None

    def reacquire(self):
        self.preview_label.set_selecting(False)
        if self.tracker is not None:
            self.tracker.reset_target()
            self.log_signal.emit(t("log.target_cleared"))

    def begin_roi_select(self):
        if self.tracker is None:
            return
        self.preview_label.set_selecting(True)
        self.preview_state.setText(t("home.roi"))
        self.log_signal.emit(t("log.roi_prompt"))

    def _apply_manual_roi(self, x0: float, y0: float, x1: float, y1: float):
        self.preview_label.set_selecting(False)
        if self.tracker is None:
            return
        self.tracker.set_manual_roi(x0, y0, x1, y1)
        self.preview_state.setText(t("report.waiting"))
        self.log_signal.emit(t("log.roi_submitted"))

    def toggle_bypass(self, checked: bool):
        if self.pipeline is not None:
            self.pipeline.manual_bypass = bool(checked)
        self.bypass_btn.setText(
            t("home.bypass.on") if checked else t("home.bypass.off"))
        self.log_signal.emit(t(
            "log.manual_bypass_on" if checked else "log.manual_bypass_off"))

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
        self.preview_state.setText(
            t("home.preview.tracking") if (self.pipeline and not self.pipeline.bypass)
            else t("home.preview.preview"))

    def _set_cable(self, active: bool, device: str = ""):
        self._cable_connected = bool(active)
        self._cable_device = device if active else ""
        if active:
            text = t("home.cable.connected")
            if device:
                text += f"\n{device}"
            color = self.theme.teal
        else:
            text = t("home.cable.disconnected")
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
            self.log_signal.emit(t("log.manual_expired"))
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
                reason = t("log.camera_thread_exited" if thread_dead else (
                    "log.camera_no_frame" if no_first_frame
                    else "log.camera_interrupted"))
                self.log_signal.emit(t("log.camera_stopping", reason=reason))
                self.stop()
                return
        if running and status is not None:
            cable_error = (status.get("cable") or {}).get("error")
            if cable_error:
                self.log_signal.emit(t("log.cable_error"))
                self.stop()
                return
            monitor_error = (status.get("monitor") or {}).get("error")
            if monitor_error and monitor_error != self._last_monitor_error:
                self.log_signal.emit(t("log.monitor_error", error=monitor_error))
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
                reason = t("log.bypass_manual" if status.get("manual_bypass")
                           else "log.bypass_visual")
                self.log_signal.emit(t("log.bypass_switch", reason=reason))
            else:
                self.log_signal.emit(t("log.bypass_restored"))
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
            self.report_stats.setText(t("report.start_hint"))
            return
        raw = data.get("raw")
        out = data.get("out")
        sample_rate = int(data.get("sample_rate", 16000))
        self.report_wave.set_data(raw, out, sample_rate)
        self.report_spectrum.set_data(raw, out, sample_rate)
        self.report_wave.set_paused(not live)
        self.report_spectrum.set_paused(not live)
        self.report_kpi_bypass.set_value(
            str(int(data.get("bypass_count", 0))), t("unit.times"))
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
        cable_state = t(
            "report.cable.connected" if cable.get("active")
            else "report.cable.disconnected")
        stats = t(
            "report.stats",
            windows=int(data.get("windows", 0)),
            skipped=int(data.get("skipped", 0)),
            tracked=f"{float(data.get('tracked', 0.0))*100:.0f}",
            cable=cable_state,
            manual=int(data.get("manual_bypass_count", 0)))
        if not live:
            stats += t("report.stats.stopped")
        self.report_stats.setText(stats)

    def _maybe_show_onboarding(self):
        if not self.settings.onboarding_done and not self._onboarding_open:
            self._show_onboarding()

    def _show_onboarding(self, checked: bool = False):
        if self._onboarding_open:
            return
        if self.pipeline is not None:
            self.log_signal.emit(t("log.stop_first_wizard"))
            return
        previous_language = current_language()
        self._onboarding_open = True
        accepted = False
        try:
            dialog = OnboardingDialog(
                self.settings, self.theme, self.mic_devices, self,
                camera_infos=self.camera_infos)
            accepted = dialog.exec()
        finally:
            self._onboarding_open = False
        if not accepted:
            return
        self.settings.onboarding_done = True
        if dialog.language != previous_language:
            self.settings.language = dialog.language
        self._persist_settings()
        if dialog.language != previous_language:
            set_language(dialog.language)
            app = QApplication.instance()
            if app is not None:
                app.setFont(QFont(ui_font_family(), 10))
            self._rebuild_ui()
        if dialog.applied:
            self._apply_home_settings()
            self._log_onboarding_devices()
        self._sync_settings_page()
        if dialog.applied:
            self.log_signal.emit(t("log.onboarding_done"))
        else:
            self.log_signal.emit(t("log.onboarding_skipped"))

    def _log_onboarding_devices(self):
        mic = self.mic.currentText() or t("common.not_selected")
        camera = self.camera.currentText() or t("common.not_selected")
        self.log_signal.emit(t("log.devices", mic=mic, camera=camera))

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
            (t("tray.hide") if visible else t("tray.show"), True, 1),
            (t("tray.start"), not running, 2),
            (t("tray.stop"), running, 3),
            (t("tray.bypass"), running, 4),
            None,
            (t("tray.settings"), True, 5),
            None,
            (t("tray.quit"), True, 6),
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
                        "FocusMic", t("tray.notice"),
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
