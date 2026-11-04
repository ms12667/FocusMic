"""Waveform and spectrum comparison widgets for the Run Report page."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


def _envelope(samples: np.ndarray, width: int) -> np.ndarray:
    """RMS amplitude per horizontal pixel, so both lanes share one scale."""
    if samples.size == 0 or width <= 0:
        return np.zeros(max(0, width), np.float32)
    n = len(samples)
    edges = np.linspace(0, n, width + 1).astype(int)
    out = np.zeros(width, np.float32)
    for i in range(width):
        lo, hi = edges[i], max(edges[i] + 1, edges[i + 1])
        chunk = samples[lo:hi]
        if chunk.size:
            out[i] = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64))))
    return out


def _paused_badge(painter: QPainter, theme, rect: QRectF, bottom: bool = False):
    box = QRectF(rect.right() - 58, rect.bottom() - 24 if bottom else rect.top() + 4,
                 54, 18)
    painter.setPen(QPen(QColor(theme.border), 1))
    painter.setBrush(QColor(theme.surface2))
    painter.drawRoundedRect(box, 5, 5)
    painter.setPen(QColor(theme.muted))
    painter.setFont(QFont("Microsoft YaHei UI", 8))
    painter.drawText(box, Qt.AlignCenter, "已停止")


def _spectrum(samples: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray] | None:
    if samples.size < 4096:
        return None
    x = np.asarray(samples[-min(len(samples), sample_rate * 4):], np.float32)
    frame = 2048
    hop = 1024
    window = np.hanning(frame).astype(np.float32)
    power = None
    for start in range(0, len(x) - frame + 1, hop):
        spec = np.fft.rfft(x[start:start + frame] * window)
        p = (np.abs(spec) ** 2).astype(np.float64)
        power = p if power is None else power + p
    if power is None:
        return None
    power /= max(1, 1 + (len(x) - frame) // hop)
    freqs = np.fft.rfftfreq(frame, 1.0 / sample_rate)
    db = 10.0 * np.log10(power + 1e-12)
    keep = freqs <= 4000.0
    freqs, db = freqs[keep], db[keep]
    if db.size > 5:
        kernel = np.ones(5, np.float32) / 5.0
        db = np.convolve(db, kernel, mode="same")
    return freqs, db


class WaveformCompare(QWidget):
    """Two stacked envelopes: raw microphone vs. separated output."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._raw = None
        self._out = None
        self._sr = 16000
        self._paused = False
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def set_data(self, raw, out, sample_rate: int = 16000):
        self._raw = None if raw is None else np.asarray(raw, np.float32)
        self._out = None if out is None else np.asarray(out, np.float32)
        self._sr = int(sample_rate)
        self.update()

    def set_paused(self, paused: bool):
        self._paused = bool(paused)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        raw, out = self._raw, self._out
        if raw is None or out is None or raw.size == 0 or out.size == 0:
            painter.setPen(QColor(self._theme.faint))
            painter.setFont(QFont("Microsoft YaHei UI", 9))
            painter.drawText(rect, Qt.AlignCenter, "开始分离后显示最近 8 秒的输入 / 输出波形")
            painter.end()
            return
        n = min(len(raw), len(out))
        raw, out = raw[-n:], out[-n:]
        gap = 10.0
        lane_h = (rect.height() - gap) / 2
        pix = max(1, int(rect.width()) - 8)
        env_raw = _envelope(raw, pix)
        env_out = _envelope(out, pix)
        peak = max(float(env_raw.max()), float(env_out.max()), 1e-5)
        lanes = (
            (QRectF(rect.left(), rect.top(), rect.width(), lane_h),
             env_raw, self._theme.blue, "原始麦克风"),
            (QRectF(rect.left(), rect.top() + lane_h + gap, rect.width(), lane_h),
             env_out, self._theme.teal, "处理后输出"),
        )
        font = QFont("Microsoft YaHei UI", 8)
        painter.setFont(font)
        for lane, env, color, label in lanes:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self._theme.surface2))
            painter.drawRoundedRect(lane, 6, 6)
            center = lane.center().y()
            half = max(2.0, lane.height() / 2 - 12)
            # Midline.
            pen = QPen(QColor(self._theme.chart_grid), 1)
            painter.setPen(pen)
            painter.drawLine(QPointF(lane.left() + 4, center),
                             QPointF(lane.right() - 4, center))
            scale = half / peak
            c = QColor(color)
            c.setAlpha(170)
            painter.setPen(QPen(c, 1.2))
            x0 = lane.left() + 4
            for i, amp in enumerate(env):
                x = x0 + i
                h = float(amp) * scale
                painter.drawLine(QPointF(x, center - h), QPointF(x, center + h))
            painter.setPen(QColor(color))
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(lane.left() + 9, lane.top() + 10), 2.5, 2.5)
            painter.setPen(QColor(self._theme.muted))
            painter.drawText(QRectF(lane.left() + 16, lane.top() + 2,
                                   lane.width() - 20, 16),
                             Qt.AlignLeft | Qt.AlignVCenter, label)
        painter.setPen(QColor(self._theme.faint))
        painter.drawText(QRectF(rect.left() + 4, rect.bottom() - 17, 60, 15),
                         Qt.AlignLeft | Qt.AlignVCenter, "−8 s")
        painter.drawText(QRectF(rect.right() - 64, rect.bottom() - 17, 60, 15),
                         Qt.AlignRight | Qt.AlignVCenter, "现在")
        if self._paused:
            _paused_badge(painter, self._theme, rect)
        painter.end()


class SpectrumCompare(QWidget):
    """Averaged speech spectrum of the same two signals."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._raw = None
        self._out = None
        self._sr = 16000
        self._paused = False
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def set_data(self, raw, out, sample_rate: int = 16000):
        self._raw = None if raw is None else np.asarray(raw, np.float32)
        self._out = None if out is None else np.asarray(out, np.float32)
        self._sr = int(sample_rate)
        self.update()

    def set_paused(self, paused: bool):
        self._paused = bool(paused)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(6, 8, -8, -20)
        raw = _spectrum(self._raw, self._sr) if self._raw is not None else None
        out = _spectrum(self._out, self._sr) if self._out is not None else None
        if raw is None or out is None:
            painter.setPen(QColor(self._theme.faint))
            painter.setFont(QFont("Microsoft YaHei UI", 9))
            painter.drawText(QRectF(self.rect()), Qt.AlignCenter,
                             "等待更多音频（约 1 秒）")
            painter.end()
            return
        f_raw, db_raw = raw
        f_out, db_out = out
        lo = min(float(db_raw.min()), float(db_out.min()))
        hi = max(float(db_raw.max()), float(db_out.max()))
        lo = max(lo, hi - 55.0)
        span = max(1.0, hi - lo)
        # Grid.
        painter.setPen(QPen(QColor(self._theme.chart_grid), 1))
        for i in range(4):
            y = rect.top() + rect.height() * i / 3
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        font = QFont("Cascadia Mono", 7)
        painter.setFont(font)
        painter.setPen(QColor(self._theme.faint))
        painter.drawText(QRectF(rect.left(), rect.bottom() + 3, 30, 14),
                         Qt.AlignLeft, "0")
        for khz in (1, 2, 3, 4):
            x = rect.left() + rect.width() * khz / 4.0
            painter.drawText(QRectF(x - 12, rect.bottom() + 3, 28, 14),
                             Qt.AlignHCenter, f"{khz}k")
        painter.drawText(QRectF(rect.right() - 34, rect.top() - 7, 34, 14),
                         Qt.AlignRight, f"{hi:.0f} dB")
        # Curves.
        for freqs, db, color in ((f_raw, db_raw, self._theme.blue),
                                 (f_out, db_out, self._theme.teal)):
            path = QPainterPath()
            for i, (f, value) in enumerate(zip(freqs, db)):
                x = rect.left() + rect.width() * min(1.0, float(f) / 4000.0)
                y = rect.bottom() - rect.height() * (max(lo, min(hi, float(value))) - lo) / span
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            pen = QPen(QColor(color), 1.6)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
        # Legend.
        painter.setFont(QFont("Microsoft YaHei UI", 8))
        for i, (label, color) in enumerate((("原始", self._theme.blue),
                                            ("输出", self._theme.teal))):
            x = rect.left() + 6 + i * 52
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(x, rect.top() + 5), 2.5, 2.5)
            painter.setPen(QColor(self._theme.muted))
            painter.drawText(QRectF(x + 6, rect.top() - 3, 40, 16),
                             Qt.AlignLeft | Qt.AlignVCenter, label)
        if self._paused:
            _paused_badge(painter, self._theme, rect, bottom=True)
        painter.end()
