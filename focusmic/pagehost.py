"""Slide-and-fade page host for the three FocusMic workspace pages."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QRect, QVariantAnimation, Qt
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


class PageHost(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pages: list[QWidget] = []
        self.current = -1
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(230)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._tick)
        self._anim.finished.connect(self._finish)
        self._old = None
        self._new = None
        self._direction = 1

    def add_page(self, page: QWidget):
        page.setParent(self)
        page.setGraphicsEffect(QGraphicsOpacityEffect(page))
        page.hide()
        self.pages.append(page)
        if self.current < 0:
            self.current = 0
            page.setGeometry(self.rect())
            page.graphicsEffect().setOpacity(1)
            page.show()

    def set_current(self, index: int, animate: bool = True):
        if index == self.current or not (0 <= index < len(self.pages)):
            return
        if self._anim.state() == QVariantAnimation.Running:
            self._anim.stop()
            self._finish()
        old = self.pages[self.current]
        new = self.pages[index]
        self._direction = 1 if index > self.current else -1
        self._old, self._new = old, new
        base = self.rect()
        new.setGeometry(base)
        new.move(base.x() + self._direction * 18, base.y())
        new.show()
        new.raise_()
        new.graphicsEffect().setOpacity(0.0)
        if not animate:
            self._anim.setStartValue(1.0)
            self._anim.setEndValue(1.0)
            self._finish(index)
            return
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _tick(self, value):
        p = float(value)
        base = self.rect()
        if self._old is None or self._new is None:
            return
        self._old.graphicsEffect().setOpacity(1.0 - p)
        self._old.move(base.x() - self._direction * 8 * p, base.y())
        self._new.graphicsEffect().setOpacity(p)
        self._new.move(base.x() + self._direction * 18 * (1 - p), base.y())

    def _finish(self, index: int | None = None):
        base = self.rect()
        if self._old is not None:
            self._old.hide()
            self._old.setGeometry(base)
            self._old.graphicsEffect().setOpacity(1.0)
        if self._new is not None:
            self._new.setGeometry(base)
            self._new.graphicsEffect().setOpacity(1.0)
            self.current = self.pages.index(self._new)
        self._old = self._new = None
        for i, page in enumerate(self.pages):
            if i != self.current:
                page.hide()
                page.setGeometry(base)
                page.graphicsEffect().setOpacity(1.0)

    def resizeEvent(self, event):
        base = self.rect()
        for page in self.pages:
            page.setGeometry(base)
        if self._anim.state() == QVariantAnimation.Running:
            self._anim.stop()
            self._finish()
        super().resizeEvent(event)
