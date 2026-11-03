"""SVG icon rendering and small morphing/animated controls.

Morphicons itself is a JavaScript engine; this is a Qt-native take on the same
idea (stroke icons from Lucide, with spring-like crossfade/rotation for state
changes). See ASSETS/license notes for attribution.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QWidget

from .paths import ASSETS_DIR

ICON_DIR = ASSETS_DIR / "icons" / "lucide"
_CACHE: dict[tuple[str, str, int, float], QPixmap] = {}


def _svg_text(name: str, color: str) -> str | None:
    path = ICON_DIR / f"{name}.svg"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if "currentColor" in text:
        return text.replace("currentColor", color)
    # Simple Icons / filled assets have no currentColor; give the root a fill.
    if "<svg" in text and "fill=" not in text:
        return text.replace("<svg", f'<svg fill="{color}"', 1)
    return text


def render_icon(name: str, color: str, size: int = 20, dpr: float = 2.0) -> QPixmap:
    key = (name, color, size, dpr)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    text = _svg_text(name, color)
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.fill(Qt.transparent)
    if text:
        renderer = QSvgRenderer(QByteArray(text.encode("utf-8")))
        painter = QPainter(px)
        painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(painter, QRectF(0, 0, px.width(), px.height()))
        painter.end()
    px.setDevicePixelRatio(dpr)
    _CACHE[key] = px
    return px


class IconButton(QAbstractButton):
    """A quiet square icon button with hover fill."""

    def __init__(self, name: str, theme, parent=None, size: int = 18, tip: str = ""):
        super().__init__(parent)
        self._name = name
        self._theme = theme
        self._size = size
        self._hover = False
        self.setFixedSize(36, 36)
        self.setCursor(Qt.PointingHandCursor)
        if tip:
            self.setToolTip(tip)
        self.setAttribute(Qt.WA_Hover, True)

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def set_icon_name(self, name: str):
        self._name = name
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        if self._hover or self.isDown():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self._theme.hover))
            painter.drawRoundedRect(rect, 8, 8)
        color = self._theme.text if self._hover else self._theme.muted
        pix = render_icon(self._name, color, self._size)
        x = (self.width() - pix.width() / pix.devicePixelRatio()) / 2
        y = (self.height() - pix.height() / pix.devicePixelRatio()) / 2
        painter.drawPixmap(QPointF(x, y), pix)


class MorphIconButton(IconButton):
    """Sun/moon style crossfade+rotation, a small tribute to Morphicons."""

    def __init__(self, from_name: str, to_name: str, theme, parent=None, size: int = 18):
        super().__init__(from_name, theme, parent, size)
        self._from = from_name
        self._to = to_name
        self._progress = 0.0
        self.setCheckable(True)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_progress)
        self.toggled.connect(self._animate)

    def _set_progress(self, value):
        self._progress = float(value)
        self.update()

    def _animate(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        if self._hover or self.isDown():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self._theme.hover))
            painter.drawRoundedRect(rect, 8, 8)
        p = self._progress
        color = self._theme.text if self._hover else self._theme.muted
        a = render_icon(self._from, color, self._size)
        b = render_icon(self._to, color, self._size)
        center = QPointF(self.width() / 2, self.height() / 2)
        for pix, alpha, rot in ((a, 1 - p, -90 * p), (b, p, 90 * (1 - p))):
            if alpha <= 0.01:
                continue
            painter.save()
            painter.setOpacity(alpha)
            painter.translate(center)
            painter.rotate(rot)
            painter.drawPixmap(QPointF(-pix.width() / pix.devicePixelRatio() / 2,
                                       -pix.height() / pix.devicePixelRatio() / 2), pix)
            painter.restore()


class NavButton(QAbstractButton):
    """Sidebar tab with icon + label and an animated accent rail."""

    def __init__(self, icon_name: str, text: str, theme, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._text = text
        self._theme = theme
        self._active = False
        self._hover = False
        self._progress = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._tick)
        self.setFixedHeight(46)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def set_active(self, active: bool):
        if self._active == active:
            return
        self._active = active
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(1.0 if active else 0.0)
        self._anim.start()

    def _tick(self, value):
        self._progress = float(value)
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 2, -2, -2)
        if self._progress > 0.01:
            painter.setPen(Qt.NoPen)
            soft = QColor(self._theme.accent_soft)
            soft.setAlpha(int(255 * min(1.0, self._progress)))
            painter.setBrush(soft)
            painter.drawRoundedRect(rect, 9, 9)
            accent = QColor(self._theme.accent)
            accent.setAlpha(int(255 * min(1.0, self._progress)))
            painter.setBrush(accent)
            h = (self.height() - 24) * (0.35 + 0.65 * self._progress)
            painter.drawRoundedRect(QRectF(2, (self.height() - h) / 2, 3, h), 1.5, 1.5)
        elif self._hover:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self._theme.hover))
            painter.drawRoundedRect(rect, 9, 9)
        active_look = self._progress > 0.5
        color = self._theme.accent if active_look else (
            self._theme.text if self._hover else self._theme.muted)
        pix = render_icon(self._icon_name, color, 18)
        painter.drawPixmap(QPointF(15, (self.height() - pix.height() / pix.devicePixelRatio()) / 2), pix)
        painter.setPen(QColor(color))
        font = self.font()
        font.setPointSizeF(10.2)
        font.setWeight(QFont.Weight.DemiBold if active_look else QFont.Weight.Medium)
        painter.setFont(font)
        painter.drawText(QRectF(44, 0, self.width() - 50, self.height()),
                         Qt.AlignVCenter | Qt.AlignLeft, self._text)
