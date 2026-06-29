from __future__ import annotations
from typing import Optional

from PyQt5.QtWidgets import QGraphicsView, QPushButton
from PyQt5.QtGui import QPainter, QColor
from PyQt5.QtCore import Qt, QPoint, QRectF

from configuration import (
    CANVAS_BACKGROUND_COLOR, SCROLLBAR_TOGGLE_BG, SCROLLBAR_TOGGLE_HOVER,
    VIGNETTE_COLOR, VIGNETTE_RADIUS, SCROLLBAR_BTN_MARGIN, SCROLLBAR_BTN_OFFSET
)


class GraphicsView(QGraphicsView):
    _ZOOM_STEP_IN  = 1.20
    _ZOOM_STEP_OUT = 1 / 1.20

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(
            QPainter.Antialiasing |
            QPainter.SmoothPixmapTransform |
            QPainter.TextAntialiasing,
        )
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setStyleSheet(f"background:{CANVAS_BACKGROUND_COLOR}; border:none;")

        self._panning     = False
        self._pan_origin: Optional[QPoint] = None
        self._suppress_redelivered_click = False

        self._scrollbar_toggle_btn = QPushButton("⊞", self)
        self._scrollbar_toggle_btn.setFixedSize(22, 22)
        self._scrollbar_toggle_btn.setToolTip("Toggle scrollbars")
        self._scrollbar_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background:{SCROLLBAR_TOGGLE_BG};color:white;
                border:none;border-radius:4px;font-size:13px;
            }}
            QPushButton:hover{{background:{SCROLLBAR_TOGGLE_HOVER};}}
        """)
        self._scrollbar_toggle_btn.clicked.connect(self._toggle_scrollbar_visibility)
        self._scrollbars_visible = False

    def wheelEvent(self, event):
        factor = self._ZOOM_STEP_IN if event.angleDelta().y() > 0 else self._ZOOM_STEP_OUT
        self.scale(factor, factor)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        if self.scene():
            self.scene().drawBackground(painter, rect)

        painter.save()
        painter.resetTransform()

        from PyQt5.QtGui import QRadialGradient, QBrush
        w = self.viewport().width()
        h = self.viewport().height()

        gradient = QRadialGradient(w / 2.0, h / 2.0, max(w, h) * VIGNETTE_RADIUS)
        gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
        gradient.setColorAt(1.0, QColor(*VIGNETTE_COLOR))

        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.NoPen)
        painter.drawRect(0, 0, w, h)

        painter.restore()

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning    = True
            self._pan_origin = event.pos()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
        elif self._suppress_redelivered_click:
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning    = False
            self._pan_origin = None
            self.viewport().setCursor(Qt.ArrowCursor)
            event.accept()
        elif self._suppress_redelivered_click:
            self._suppress_redelivered_click = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_origin is not None:
            delta            = event.pos() - self._pan_origin
            self._pan_origin = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scrollbar_toggle_btn.move(
            self.width()  - self._scrollbar_toggle_btn.width() - SCROLLBAR_BTN_MARGIN - SCROLLBAR_BTN_OFFSET,
            self.height() - self._scrollbar_toggle_btn.height() - SCROLLBAR_BTN_MARGIN - SCROLLBAR_BTN_OFFSET,
        )

    def _toggle_scrollbar_visibility(self):
        self._scrollbars_visible = not self._scrollbars_visible
        policy = Qt.ScrollBarAsNeeded if self._scrollbars_visible else Qt.ScrollBarAlwaysOff
        self.setHorizontalScrollBarPolicy(policy)
        self.setVerticalScrollBarPolicy(policy)
        self._scrollbar_toggle_btn.setText("⊟" if self._scrollbars_visible else "⊞")
