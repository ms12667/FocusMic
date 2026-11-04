"""Small theme-aware controls: labels, setting rows and animated switches."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class ThemedLabel(QLabel):
    """A QLabel whose color follows the current Theme."""

    def __init__(self, text: str, theme, role: str = "muted", size: int = 11,
                 weight: int | None = None, wrap: bool = False, mono: bool = False,
                 parent=None):
        super().__init__(text, parent)
        self._role = role
        self._size = size
        self._weight = weight
        self._mono = mono
        self.setTextFormat(Qt.PlainText)
        self.setWordWrap(wrap)
        self.set_theme(theme)

    def set_theme(self, theme):
        color = getattr(theme, self._role, theme.muted)
        family = "Cascadia Mono" if self._mono else "Microsoft YaHei UI"
        weight = f"font-weight:{self._weight};" if self._weight else ""
        self.setStyleSheet(
            f"color:{color};font-family:'{family}';font-size:{self._size}px;"
            f"{weight}background:transparent;")


class LinkLabel(QLabel):
    """External link whose color follows the theme."""

    def __init__(self, text: str, url: str, theme, size: int = 12, parent=None):
        super().__init__(parent)
        self._text = text
        self._url = url
        self._size = size
        self.setOpenExternalLinks(True)
        self.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.setWordWrap(True)
        self.set_theme(theme)

    def set_theme(self, theme):
        self.setStyleSheet(
            f"font-family:'Microsoft YaHei UI';font-size:{self._size}px;background:transparent;")
        self.setText(
            f'<a href="{self._url}" style="color:{theme.blue};text-decoration:none;">'
            f'{self._text}</a>')


class ToggleSwitch(QAbstractButton):
    """An iOS-style switch with a real knob and a short animation."""

    def __init__(self, theme, parent=None, width: int = 42, height: int = 24):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(width, height)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self._theme = theme
        self._hover = False
        self._progress = 1.0 if self.isChecked() else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._tick)
        self.toggled.connect(self._animate)

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def _tick(self, value):
        self._progress = float(value)
        self.update()

    def _animate(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.42)
        track = QRectF(1, 2, self.width() - 2, self.height() - 4)
        radius = track.height() / 2
        off = QColor(self._theme.border if self._theme.dark else self._theme.faint)
        if not self._theme.dark:
            off.setAlpha(170)
        on = QColor(self._theme.accent)
        if self._hover:
            on = QColor(self._theme.accent_hover)
        mix = self._progress
        color = QColor(
            int(off.red() + (on.red() - off.red()) * mix),
            int(off.green() + (on.green() - off.green()) * mix),
            int(off.blue() + (on.blue() - off.blue()) * mix),
        )
        painter.setPen(QPen(QColor(self._theme.border), 1))
        painter.setBrush(color)
        painter.drawRoundedRect(track, radius, radius)

        knob_size = track.height() - 4
        left = track.left() + 2
        right = track.right() - knob_size - 2
        x = left + (right - left) * mix
        knob = QRectF(x, track.top() + 2, knob_size, knob_size)
        painter.setPen(QPen(QColor(0, 0, 0, 28), 1))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(knob)
        # Focus ring for keyboard users.
        if self.hasFocus():
            painter.setPen(QPen(QColor(self._theme.accent), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(track.adjusted(-1, -1, 1, 1), radius + 1, radius + 1)
        painter.end()


class SettingRow(QWidget):
    """Title + description on the left, a control on the right."""

    def __init__(self, title: str, description: str, control: QWidget, theme,
                 parent=None):
        super().__init__(parent)
        self._theme = theme
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title = ThemedLabel(title, theme, role="text", size=12, weight=600)
        self.description = ThemedLabel(description, theme, role="muted", size=10, wrap=True)
        texts.addWidget(self.title)
        texts.addWidget(self.description)
        layout.addLayout(texts, 1)
        layout.addWidget(control, 0, Qt.AlignVCenter)

    def set_theme(self, theme):
        self._theme = theme
        self.title.set_theme(theme)
        self.description.set_theme(theme)
