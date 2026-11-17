"""Guidance dialog shown when the external PyTorch/CUDA runtime is missing."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from . import runtime
from .controls import LinkLabel, ThemedLabel
from .i18n import t


class RuntimeDialog(QDialog):
    """Explain the separate runtime package and let the user re-check."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle(t("runtime.window_title"))
        self.setModal(True)
        self.setMinimumWidth(540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(ThemedLabel(
            t("runtime.heading"), theme, role="text", size=16, weight=600))
        layout.addWidget(ThemedLabel(
            t("runtime.body"), theme, role="muted", size=11, wrap=True))
        self.status_label = ThemedLabel("", theme, role="red", size=10, wrap=True)
        layout.addWidget(self.status_label)
        layout.addWidget(LinkLabel(
            t("runtime.link"), runtime.RELEASES_URL, theme, size=11))

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        download = QPushButton(t("runtime.download"))
        download.setObjectName("primary")
        download.clicked.connect(self._download)
        recheck = QPushButton(t("runtime.recheck"))
        recheck.clicked.connect(self._recheck)
        close = QPushButton(t("runtime.close"))
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
            self.status_label.setText(t(
                "runtime.ready", torch=status.torch_version,
                cuda=status.cuda_version))
            self.accept()
            return
        self.status_label.setText(status.message())
