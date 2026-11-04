"""Task-manager-like line charts drawn with QPainter (no QtCharts dependency)."""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


class LineChart(QWidget):
    def __init__(self, color: str, theme, parent=None, points: int = 50,
                 decimals: int = 0):
        super().__init__(parent)
        self._history = deque([0.0] * points, maxlen=points)
        self._color = QColor(color)
        self._theme = theme
        self._fixed_max = None
        self._decimals = int(decimals)
        self.setMinimumHeight(112)

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def push(self, value: float):
        self._history.append(float(value))
        self.update()

    def clear(self):
        self._history = deque([0.0] * self._history.maxlen, maxlen=self._history.maxlen)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 8, -26, -18)
        if rect.width() <= 4 or rect.height() <= 4:
            return
        data = list(self._history)
        peak = max(max(data), 1.0)
        ceiling = self._fixed_max if self._fixed_max else peak * 1.18
        grid_pen = QPen(QColor(self._theme.chart_grid), 1)
        painter.setPen(grid_pen)
        for i in range(4):
            y = rect.top() + rect.height() * i / 3
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        font = QFont("Cascadia Mono", 7)
        painter.setFont(font)
        painter.setPen(QColor(self._theme.faint))
        painter.drawText(QRectF(rect.right() + 5, rect.top() - 7, 30, 14),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         f"{ceiling:.{self._decimals}f}")
        painter.drawText(QRectF(rect.right() + 5, rect.bottom() - 7, 22, 14),
                         Qt.AlignLeft | Qt.AlignVCenter, "0")
        # Area + line.
        n = len(data)
        path = QPainterPath()
        for i, value in enumerate(data):
            x = rect.left() + rect.width() * i / max(1, n - 1)
            y = rect.bottom() - rect.height() * min(value, ceiling) / ceiling
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        fill = QPainterPath(path)
        fill.lineTo(rect.right(), rect.bottom())
        fill.lineTo(rect.left(), rect.bottom())
        fill.closeSubpath()
        grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
        c = QColor(self._color)
        c.setAlpha(58)
        grad.setColorAt(0, c)
        c2 = QColor(self._color)
        c2.setAlpha(0)
        grad.setColorAt(1, c2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(grad)
        painter.drawPath(fill)
        line = QPen(self._color, 1.8)
        line.setCapStyle(Qt.RoundCap)
        line.setJoinStyle(Qt.RoundJoin)
        painter.setPen(line)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        # Latest value dot.
        if n:
            x = rect.right()
            y = rect.bottom() - rect.height() * min(data[-1], ceiling) / ceiling
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._color)
            painter.drawEllipse(QPointF(x, y), 2.6, 2.6)
        painter.setPen(QColor(self._theme.faint))
        painter.setFont(QFont("Microsoft YaHei UI", 7))
        painter.drawText(QRectF(rect.left(), rect.bottom() + 3, 50, 14),
                         Qt.AlignLeft | Qt.AlignVCenter, "−30s")
        painter.drawText(QRectF(rect.right() - 28, rect.bottom() + 3, 28, 14),
                         Qt.AlignRight | Qt.AlignVCenter, "现在")


class MetricCard(QFrame):
    def __init__(self, title: str, unit: str, color: str, theme,
                 fixed_max: float | None = None, parent=None,
                 color_role: str | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._title = title
        self._unit = unit
        self._color = color
        self._color_role = color_role
        self._theme = theme
        self._fixed_max = fixed_max
        self._values: deque[float] = deque(maxlen=50)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.title = QLabel(title)
        self.title.setObjectName("CardTitle")
        self.value = QLabel("—")
        self.value.setObjectName("KpiValue")
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.title)
        top.addStretch(1)
        top.addWidget(self.value)
        root.addLayout(top)
        self.chart = LineChart(color, theme, decimals=2 if unit == "s" else 0)
        self.chart.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if fixed_max is not None:
            self.chart._fixed_max = fixed_max
        root.addWidget(self.chart, 1)
        self.footer = QLabel("等待数据")
        self.footer.setObjectName("Faint")
        root.addWidget(self.footer)
        self.set_theme(theme)

    def set_theme(self, theme):
        self._theme = theme
        if self._color_role:
            self._color = getattr(theme, self._color_role, self._color)
            self.chart.set_color(self._color)
        self.chart.set_theme(theme)
        self.title.setStyleSheet(f"color:{theme.text};")
        self.value.setStyleSheet(f"color:{theme.text};")
        self.footer.setStyleSheet(f"color:{theme.faint};font-size:11px;")
        self.setStyleSheet(
            f"QFrame#Card{{background:{theme.surface};border:1px solid {theme.border};border-radius:12px;}}")
        self.chart.update()

    def _format(self, value: float) -> str:
        return f"{value:.2f}" if self._unit == "s" else f"{value:.0f}"

    def push(self, value: float):
        v = float(value)
        self._values.append(v)
        self.chart.push(v)
        text = self._format(v)
        if self._unit:
            self.value.setText(
                f"{text}<span style='font-size:11px;color:{self._theme.muted}'> "
                f"{self._unit}</span>")
        else:
            self.value.setText(text)
        vals = list(self._values)
        if vals:
            self.footer.setText(
                f"平均 {self._format(sum(vals)/len(vals))} · "
                f"最高 {self._format(max(vals))} {self._unit}")


class KpiCard(QFrame):
    def __init__(self, label: str, value: str, unit: str, theme,
                 accent: str | None = None, parent=None,
                 accent_role: str | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._theme = theme
        self._accent = accent
        self._accent_role = accent_role
        root = QVBoxLayout(self)
        root.setContentsMargins(13, 10, 13, 10)
        root.setSpacing(2)
        self.label = QLabel(label)
        self.label.setObjectName("KpiLabel")
        self.value = QLabel(f"{value}<span style='font-size:11px;color:{theme.muted}'> {unit}</span>")
        self.value.setObjectName("KpiValue")
        self.value.setStyleSheet(f"color:{accent or theme.text};")
        root.addWidget(self.label)
        root.addWidget(self.value)
        self.set_theme(theme)

    def set_theme(self, theme):
        self._theme = theme
        if self._accent_role:
            self._accent = getattr(theme, self._accent_role, self._accent)
        self.label.setStyleSheet(f"color:{theme.muted};font-size:11px;")
        self.value.setStyleSheet(f"color:{self._accent or theme.text};")
        self.setStyleSheet(
            f"QFrame#Card{{background:{theme.surface};border:1px solid {theme.border};border-radius:11px;}}")

    def set_value(self, value: str, unit: str = ""):
        self.value.setText(f"{value}<span style='font-size:11px;color:{self._theme.muted}'> {unit}</span>")
