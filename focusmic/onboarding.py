"""First-run setup wizard for FocusMic."""
from __future__ import annotations

import sounddevice as sd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .audio import input_device_label
from .cameras import list_cameras
from .controls import ThemedLabel
from .i18n import LANGUAGES, current_language, set_language, t
from .icons import render_icon
from .output import resolve_cable_input


class OnboardingDialog(QDialog):
    """Four short pages: welcome, devices, output, ready.

    The language selector is always available in the header, so a first-run
    user can switch the whole wizard before choosing devices. It never opens
    the microphone or camera; it only reads device lists.
    """

    STEPS = 4

    def __init__(self, settings, theme, mic_devices, parent=None,
                 camera_infos=None):
        super().__init__(parent)
        self._settings = settings
        self._theme = theme
        self._mic_devices = list(mic_devices)
        self._camera_infos = list(camera_infos) if camera_infos else list_cameras()
        self.start_language = current_language()
        self.language = current_language()
        self.language_changed = False
        self.applied = False
        self.mic_name = settings.mic_name
        self.mic_hostapi = settings.mic_hostapi
        self.camera = int(settings.camera)
        self._content = None
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self.setWindowTitle(t("onboarding.window_title"))
        self.setModal(True)
        self.setMinimumSize(640, 480)
        self.resize(640, 480)
        self._build()

    def _title(self, text: str) -> ThemedLabel:
        return ThemedLabel(text, self._theme, role="text", size=21, weight=600)

    def _body(self, text: str) -> ThemedLabel:
        return ThemedLabel(text, self._theme, role="muted", size=11, wrap=True)

    def _bullet(self, text: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        dot = ThemedLabel("•", self._theme, role="teal", size=14)
        dot.setFixedWidth(9)
        dot.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        layout.addWidget(dot)
        layout.addWidget(self._body(text), 1)
        return row

    def _card(self) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("Card")
        box = QVBoxLayout(card)
        box.setContentsMargins(22, 20, 22, 20)
        box.setSpacing(10)
        return card, box

    def _build(self):
        if self._content is not None:
            self._root.removeWidget(self._content)
            self._content.deleteLater()
        self._content = QWidget(self)
        self._root.addWidget(self._content)
        root = QVBoxLayout(self._content)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(12)

        top = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(render_icon("mic", self._theme.accent, 30))
        top.addWidget(icon)
        top.addSpacing(8)
        top.addWidget(ThemedLabel("FocusMic", self._theme, role="text", size=16, weight=600))
        top.addStretch(1)
        top.addWidget(ThemedLabel(
            t("onboarding.language.label"), self._theme, role="muted", size=10))
        self.language_combo = QComboBox()
        for language in LANGUAGES:
            self.language_combo.addItem(language.native, language.code)
        index = self.language_combo.findData(self.language)
        if index >= 0:
            self.language_combo.setCurrentIndex(index)
        self.language_combo.setToolTip(t("onboarding.language.hint"))
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        top.addWidget(self.language_combo)
        top.addSpacing(8)
        self.step_label = ThemedLabel("", self._theme, role="faint", size=10)
        top.addWidget(self.step_label)
        root.addLayout(top)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_welcome())
        self.stack.addWidget(self._page_devices())
        self.stack.addWidget(self._page_output())
        self.stack.addWidget(self._page_ready())
        root.addWidget(self.stack, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        skip = QPushButton(t("onboarding.skip"))
        skip.setObjectName("ghost")
        skip.clicked.connect(self._skip)
        footer.addWidget(skip)
        footer.addStretch(1)
        self.back_btn = QPushButton(t("onboarding.back"))
        self.back_btn.setObjectName("ghost")
        self.back_btn.clicked.connect(self._back)
        self.next_btn = QPushButton(t("onboarding.next"))
        self.next_btn.setObjectName("primary")
        self.next_btn.clicked.connect(self._next)
        footer.addWidget(self.back_btn)
        footer.addWidget(self.next_btn)
        root.addLayout(footer)
        self._sync()

    def _language_changed(self, _index=None):
        code = self.language_combo.currentData()
        if not code or code == self.language:
            return
        step = self.stack.currentIndex()
        self.language = str(code)
        self.language_changed = self.language != self.start_language
        set_language(self.language)
        # Rebuilding deletes the combo that is emitting this signal, so defer.
        QTimer.singleShot(0, lambda: self._reload(step))

    def _reload(self, step: int):
        mic_identity = None
        selected = self.mic.currentData()
        if selected is not None:
            mic_identity = (str(selected["name"]), str(selected["hostapi"]))
        camera = int(self.camera.currentData()) if self.camera.currentData() is not None else 0
        self.setWindowTitle(t("onboarding.window_title"))
        self._build()
        if mic_identity is not None:
            for i, device in enumerate(self._mic_devices):
                if (str(device["name"]), str(device["hostapi"])) == mic_identity:
                    self.mic.setCurrentIndex(i)
                    break
        pos = self.camera.findData(camera)
        if pos >= 0:
            self.camera.setCurrentIndex(pos)
        self.stack.setCurrentIndex(max(0, min(self.STEPS - 1, int(step))))
        self._sync()

    def _page_welcome(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._title(t("onboarding.welcome.title")))
        layout.addWidget(self._body(t("onboarding.welcome.body")))
        card, box = self._card()
        box.addWidget(ThemedLabel(
            t("onboarding.welcome.how"), self._theme,
            role="text", size=13, weight=600))
        for text in (
            t("onboarding.welcome.b1"),
            t("onboarding.welcome.b2"),
            t("onboarding.welcome.b3"),
        ):
            box.addWidget(self._bullet(text))
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _page_devices(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._title(t("onboarding.devices.title")))
        layout.addWidget(self._body(t("onboarding.devices.body")))
        card, box = self._card()
        box.addWidget(ThemedLabel(
            t("onboarding.devices.mic"), self._theme, role="muted", size=10))
        self.mic = QComboBox()
        self.mic.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mic.setMinimumContentsLength(16)
        for d in self._mic_devices:
            self.mic.addItem(input_device_label(d), d)
        if not self._mic_devices:
            self.mic.addItem(t("onboarding.devices.no_mic"), None)
        else:
            target = -1
            for i, d in enumerate(self._mic_devices):
                if (str(d["name"]) == self._settings.mic_name
                        and str(d["hostapi"]) == self._settings.mic_hostapi):
                    target = i
                    break
            if target < 0 and self._settings.mic_name:
                matches = [
                    (i, d) for i, d in enumerate(self._mic_devices)
                    if str(d["name"]) == self._settings.mic_name
                ]
                if matches:
                    matches.sort(key=lambda item: (
                        "WASAPI" not in item[1]["hostapi"],
                        abs(float(item[1]["samplerate"]) - 48000.0),
                        item[1]["index"],
                    ))
                    target = matches[0][0]
            if target >= 0:
                self.mic.setCurrentIndex(target)
        box.addWidget(self.mic)
        box.addWidget(ThemedLabel(
            t("onboarding.devices.camera"), self._theme, role="muted", size=10))
        self.camera = QComboBox()
        for info in self._camera_infos:
            self.camera.addItem(
                info.label(t("onboarding.devices.camera_item", index=info.index)),
                info.index)
        pos = self.camera.findData(int(self._settings.camera))
        if pos >= 0:
            self.camera.setCurrentIndex(pos)
        box.addWidget(self.camera)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _page_output(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._title(t("onboarding.output.title")))
        layout.addWidget(self._body(t("onboarding.output.body")))
        card, box = self._card()
        box.addWidget(ThemedLabel(
            t("onboarding.output.check_title"), self._theme,
            role="text", size=13, weight=600))
        self.cable_status = ThemedLabel(
            t("onboarding.output.detecting"), self._theme,
            role="muted", size=11, wrap=True)
        box.addWidget(self.cable_status)
        recheck = QPushButton(t("onboarding.output.recheck"))
        recheck.clicked.connect(self._check_cable)
        box.addWidget(recheck, 0, Qt.AlignLeft)
        layout.addWidget(card)
        layout.addWidget(self._body(t("onboarding.output.hint")))
        layout.addStretch(1)
        self._check_cable()
        return page

    def _page_ready(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._title(t("onboarding.ready.title")))
        layout.addWidget(self._body(t("onboarding.ready.body")))
        card, box = self._card()
        self.summary = ThemedLabel("", self._theme, role="muted", size=11, wrap=True)
        box.addWidget(self.summary)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _check_cable(self):
        try:
            _idx, name = resolve_cable_input(sd)
            self.cable_status.setText(t("onboarding.output.detected", name=name))
            self.cable_status.setStyleSheet(
                f"color:{self._theme.teal};font-size:11px;background:transparent;")
        except Exception:
            self.cable_status.setText(t("onboarding.output.missing"))
            self.cable_status.setStyleSheet(
                f"color:{self._theme.red};font-size:11px;background:transparent;")

    def _sync(self):
        index = self.stack.currentIndex()
        self.step_label.setText(t(
            "onboarding.step", current=index + 1, total=self.STEPS))
        self.back_btn.setEnabled(index > 0)
        self.next_btn.setText(
            t("onboarding.finish") if index == self.STEPS - 1
            else t("onboarding.next"))
        if index == self.STEPS - 1:
            mic = (self.mic.currentText() if self.mic.currentData() is not None
                   else t("onboarding.ready.not_selected"))
            camera = self.camera.currentText()
            self.summary.setText(t(
                "onboarding.ready.summary", mic=mic, camera=camera))

    def _back(self):
        if self.stack.currentIndex() > 0:
            self.stack.setCurrentIndex(self.stack.currentIndex() - 1)
            self._sync()

    def _next(self):
        index = self.stack.currentIndex()
        if index == self.STEPS - 1:
            self._finish()
            return
        self.stack.setCurrentIndex(index + 1)
        self._sync()

    def _finish(self):
        selected = self.mic.currentData()
        if selected is not None:
            self.mic_name = str(selected["name"])
            self.mic_hostapi = str(selected["hostapi"])
        camera_data = self.camera.currentData()
        self.camera = int(camera_data) if camera_data is not None else 0
        self._settings.mic_name = self.mic_name
        self._settings.mic_hostapi = self.mic_hostapi
        self._settings.camera = self.camera
        if self.language_changed:
            self._settings.language = self.language
        self._settings.onboarding_done = True
        self.applied = True
        self.accept()

    def _skip(self):
        if self.language_changed:
            self._settings.language = self.language
        self._settings.onboarding_done = True
        self.applied = False
        self.accept()

    def reject(self):
        # Cancelling the wizard must not leave the app in a half-applied
        # language that is not saved.
        set_language(self.start_language)
        super().reject()
