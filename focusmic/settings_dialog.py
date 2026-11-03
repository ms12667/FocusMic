"""Settings dialog: startup, appearance, hotkey, output gain."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QKeySequenceEdit, QLabel,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from .config import Settings
from .icons import render_icon
from .startup import startup_enabled


def _hotkey_display(value: str) -> str:
    parts = [p.strip() for p in value.replace(" ", "").split("+") if p.strip()]
    return "+".join(p[:1].upper() + p[1:] for p in parts) or "Ctrl+Alt+M"


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, theme, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FocusMic 设置")
        self.setModal(True)
        self.setMinimumWidth(560)
        self._settings = settings
        self._theme = theme
        self._result = None
        self._build()

    def _section(self, title: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 14, 0, 4)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("CardTitle")
        layout.addWidget(label)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color:{self._theme.border};")
        layout.addWidget(line)
        return widget

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(6)

        header = QHBoxLayout()
        icon = QLabel()
        pix = render_icon("settings", self._theme.accent, 24)
        icon.setPixmap(pix)
        title = QLabel("设置")
        title.setObjectName("PageTitle")
        header.addWidget(icon)
        header.addSpacing(8)
        header.addWidget(title)
        header.addStretch(1)
        root.addLayout(header)
        subtitle = QLabel("FocusMic 的启动、外观和快捷键。")
        subtitle.setObjectName("Muted")
        root.addWidget(subtitle)

        startup_box = self._section("启动")
        root.addWidget(startup_box)
        self.startup = QCheckBox("开机启动 FocusMic")
        self.startup.setChecked(startup_enabled())
        root.addWidget(self.startup)
        startup_note = QLabel("写入当前用户的启动项，不需要管理员权限。")
        startup_note.setObjectName("Faint")
        root.addWidget(startup_note)

        appearance = self._section("外观")
        root.addWidget(appearance)
        row = QHBoxLayout()
        self.follow = QCheckBox("跟随系统外观")
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.addItem("浅色", "light")
        mode = self._settings.theme_mode
        self.follow.setChecked(mode == "system")
        self.theme_combo.setCurrentIndex(1 if mode == "light" else 0)
        self.theme_combo.setEnabled(mode != "system")
        self.follow.toggled.connect(lambda checked: self.theme_combo.setEnabled(not checked))
        row.addWidget(self.follow, 1)
        row.addWidget(self.theme_combo)
        root.addLayout(row)

        hotkey = self._section("快捷键")
        root.addWidget(hotkey)
        self.hotkey_enabled = QCheckBox("启用全局旁路热键")
        self.hotkey_enabled.setChecked(self._settings.hotkey_enabled)
        root.addWidget(self.hotkey_enabled)
        hotkey_row = QHBoxLayout()
        hotkey_label = QLabel("原始麦克风 / Falcon 切换")
        hotkey_label.setObjectName("Muted")
        self.hotkey_edit = QKeySequenceEdit(QKeySequence(_hotkey_display(self._settings.hotkey)))
        self.hotkey_edit.setEnabled(self._settings.hotkey_enabled)
        self.hotkey_enabled.toggled.connect(self.hotkey_edit.setEnabled)
        hotkey_row.addWidget(hotkey_label, 1)
        hotkey_row.addWidget(self.hotkey_edit)
        root.addLayout(hotkey_row)
        hotkey_note = QLabel("点击输入框后按下组合键，例如 Ctrl+Alt+M。")
        hotkey_note.setObjectName("Faint")
        root.addWidget(hotkey_note)

        output = self._section("输出")
        root.addWidget(output)
        gain_row = QHBoxLayout()
        gain_label = QLabel("输出增益")
        gain_label.setObjectName("Muted")
        self.gain = QSlider(Qt.Horizontal)
        self.gain.setRange(-12, 12)
        self.gain.setValue(int(self._settings.gain_db))
        self.gain_value = QLabel(f"{self.gain.value()} dB")
        self.gain_value.setMinimumWidth(52)
        self.gain.valueChanged.connect(lambda v: self.gain_value.setText(f"{v} dB"))
        gain_row.addWidget(gain_label)
        gain_row.addWidget(self.gain, 1)
        gain_row.addWidget(self.gain_value)
        root.addLayout(gain_row)

        root.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def _save(self):
        seq = self.hotkey_edit.keySequence().toString(QKeySequence.PortableText)
        hotkey = seq.lower().replace(" ", "")
        if self.hotkey_enabled.isChecked() and not hotkey:
            self.hotkey_edit.setFocus()
            return
        self._settings.start_with_windows = self.startup.isChecked()
        if self.follow.isChecked():
            self._settings.theme_mode = "system"
        else:
            self._settings.theme_mode = self.theme_combo.currentData()
        self._settings.hotkey_enabled = self.hotkey_enabled.isChecked()
        if hotkey:
            self._settings.hotkey = hotkey
        self._settings.gain_db = float(self.gain.value())
        self._result = self._settings
        self.accept()

    @property
    def result_settings(self) -> Settings | None:
        return self._result
