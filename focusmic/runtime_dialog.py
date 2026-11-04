"""Guidance dialog shown when the external PyTorch/CUDA runtime is missing."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from . import runtime
from .controls import LinkLabel, ThemedLabel


class RuntimeDialog(QDialog):
    """Explain the separate runtime package and let the user re-check."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("安装 AI 运行时")
        self.setModal(True)
        self.setMinimumWidth(540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(ThemedLabel(
            "需要安装 AI 运行时", theme, role="text", size=16, weight=600))
        layout.addWidget(ThemedLabel(
            "FocusMic 主程序不包含 PyTorch 和 CUDA（约 4.3 GB），"
            "需要单独安装一次运行时包。安装完成后回到这里点击“重新检测”。",
            theme, role="muted", size=11, wrap=True))
        self.status_label = ThemedLabel("", theme, role="red", size=10, wrap=True)
        layout.addWidget(self.status_label)
        layout.addWidget(LinkLabel(
            "打开 GitHub Releases 下载 FocusMic-Runtime", runtime.RELEASES_URL, theme, size=11))

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        download = QPushButton("下载运行时包")
        download.setObjectName("primary")
        download.clicked.connect(self._download)
        recheck = QPushButton("重新检测")
        recheck.clicked.connect(self._recheck)
        close = QPushButton("关闭")
        close.setObjectName("ghost")
        close.clicked.connect(self.reject)
        buttons.addWidget(download)
        buttons.addWidget(recheck)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._recheck()

    def _download(self):
        QDesktopServices.openUrl(QUrl(runtime.RELEASES_URL))

    def _recheck(self):
        status = runtime.check_installed()
        self.status_label.set_theme(self._theme)
        if status.ok:
            self.status_label.setText(
                f"已检测到 PyTorch {status.torch_version} / "
                f"CUDA {status.cuda_version}，可以开始分离了。")
            self.accept()
            return
        self.status_label.setText(status.message())
