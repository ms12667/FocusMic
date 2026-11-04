"""First-run setup wizard for FocusMic."""
from __future__ import annotations

import sounddevice as sd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .controls import ThemedLabel
from .icons import render_icon
from .output import resolve_cable_input


class OnboardingDialog(QDialog):
    """Four short pages: welcome, devices, output, ready.

    It never opens the microphone or camera; it only reads device lists.
    """

    STEPS = 4

    def __init__(self, settings, theme, mic_devices, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FocusMic 首次设置")
        self.setModal(True)
        self.setMinimumSize(640, 480)
        self.resize(640, 480)
        self._settings = settings
        self._theme = theme
        self._mic_devices = list(mic_devices)
        self.applied = False
        self.mic_name = settings.mic_name
        self.mic_hostapi = settings.mic_hostapi
        self.camera = int(settings.camera)
        self._build()

    def _title(self, text: str) -> ThemedLabel:
        label = ThemedLabel(text, self._theme, role="text", size=21, weight=600)
        return label

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
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(12)

        top = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(render_icon("mic", self._theme.accent, 30))
        top.addWidget(icon)
        top.addSpacing(8)
        top.addWidget(ThemedLabel("FocusMic", self._theme, role="text", size=16, weight=600))
        top.addStretch(1)
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
        skip = QPushButton("跳过")
        skip.setObjectName("ghost")
        skip.clicked.connect(self._skip)
        footer.addWidget(skip)
        footer.addStretch(1)
        self.back_btn = QPushButton("上一步")
        self.back_btn.setObjectName("ghost")
        self.back_btn.clicked.connect(self._back)
        self.next_btn = QPushButton("下一步")
        self.next_btn.setObjectName("primary")
        self.next_btn.clicked.connect(self._next)
        footer.addWidget(self.back_btn)
        footer.addWidget(self.next_btn)
        root.addLayout(footer)
        self._sync()

    def _page_welcome(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._title("欢迎使用 FocusMic"))
        layout.addWidget(self._body(
            "FocusMic 会同时看摄像头和听麦克风：用嘴型认住你，"
            "把麦克风里属于你的声音留下，把旁边人的声音尽量压掉。"))
        card, box = self._card()
        box.addWidget(ThemedLabel("它是怎么工作的", self._theme, role="text", size=13, weight=600))
        for text in (
            "摄像头只用来识别嘴部，画面不会保存。",
            "声音和画面都只在本机处理，不会上传。",
            "分离结果通过本机虚拟声卡送到语音或会议软件。",
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
        layout.addWidget(self._title("选择设备"))
        layout.addWidget(self._body(
            "先选好你平时用的麦克风和摄像头。以后也可以在主页随时更改，"
            "不需要重新运行这个向导。"))
        card, box = self._card()
        box.addWidget(ThemedLabel("麦克风", self._theme, role="muted", size=10))
        self.mic = QComboBox()
        self.mic.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mic.setMinimumContentsLength(16)
        for d in self._mic_devices:
            self.mic.addItem(f"{d['name']}  ·  {d['hostapi']}", d)
        if not self._mic_devices:
            self.mic.addItem("没有检测到录音设备", None)
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
        box.addWidget(ThemedLabel("摄像头", self._theme, role="muted", size=10))
        self.camera = QComboBox()
        for i in range(6):
            self.camera.addItem(f"摄像头 {i}", i)
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
        layout.addWidget(self._title("接到语音软件"))
        layout.addWidget(self._body(
            "FocusMic 会把分离后的声音送到本机虚拟声卡。"
            "在语音或会议软件里，把麦克风选成 CABLE Output 即可。"))
        card, box = self._card()
        box.addWidget(ThemedLabel("虚拟声卡检测", self._theme, role="text", size=13, weight=600))
        self.cable_status = ThemedLabel("正在检测…", self._theme, role="muted", size=11, wrap=True)
        box.addWidget(self.cable_status)
        recheck = QPushButton("重新检测")
        recheck.clicked.connect(self._check_cable)
        box.addWidget(recheck, 0, Qt.AlignLeft)
        layout.addWidget(card)
        layout.addWidget(self._body(
            "如果还没有安装虚拟声卡，请先安装后点“重新检测”。"
            "检测不到也可以先完成向导，之后在主页继续配置。"))
        layout.addStretch(1)
        self._check_cable()
        return page

    def _page_ready(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._title("准备完成"))
        layout.addWidget(self._body(
            "设置会保存在本机。点“完成”回到主页，再点“开始分离”即可。\n"
            "之后可以随时在主页调整设备，或在“使用教程”里查看详细步骤。"))
        card, box = self._card()
        self.summary = ThemedLabel("", self._theme, role="muted", size=11, wrap=True)
        box.addWidget(self.summary)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _check_cable(self):
        try:
            _idx, name = resolve_cable_input(sd)
            self.cable_status.setText("● 已检测到：" + name)
            self.cable_status.setStyleSheet(
                f"color:{self._theme.teal};font-size:11px;background:transparent;")
        except Exception:
            self.cable_status.setText(
                "● 未检测到虚拟声卡。请安装虚拟音频驱动后再点“重新检测”。")
            self.cable_status.setStyleSheet(
                f"color:{self._theme.red};font-size:11px;background:transparent;")

    def _sync(self):
        index = self.stack.currentIndex()
        self.step_label.setText(f"步骤 {index + 1} / {self.STEPS}")
        self.back_btn.setEnabled(index > 0)
        self.next_btn.setText("完成" if index == self.STEPS - 1 else "下一步")
        if index == self.STEPS - 1:
            mic = self.mic.currentText() if self.mic.currentData() is not None else "未选择"
            camera = self.camera.currentText()
            self.summary.setText(f"麦克风：{mic}\n摄像头：{camera}\n\n点“完成”后进入主页。")

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
        self.camera = int(self.camera.currentData())
        self._settings.mic_name = self.mic_name
        self._settings.mic_hostapi = self.mic_hostapi
        self._settings.camera = self.camera
        self._settings.onboarding_done = True
        self.applied = True
        self.accept()

    def _skip(self):
        self._settings.onboarding_done = True
        self.applied = False
        self.accept()
