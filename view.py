from __future__ import annotations
from typing import Optional

from PyQt5.QtWidgets import QGraphicsView, QPushButton
from PyQt5.QtGui import QPainter, QColor, QRadialGradient, QBrush
from PyQt5.QtCore import Qt, QPoint, QRectF

from configuration import (
    CANVAS_BACKGROUND_COLOR, SCROLLBAR_TOGGLE_BG, SCROLLBAR_TOGGLE_HOVER,
    VIGNETTE_COLOR, VIGNETTE_RADIUS, SCROLLBAR_BTN_MARGIN, SCROLLBAR_BTN_OFFSET,
    SCROLLBAR_BTN_SIZE, VIEW_ZOOM_STEP, VIEW_ZOOM_MIN, VIEW_ZOOM_MAX,
    VIEW_FRAME_MARGIN,
)


class GraphicsView(QGraphicsView):
    _ZOOM_STEP_IN  = VIEW_ZOOM_STEP
    _ZOOM_STEP_OUT = 1 / VIEW_ZOOM_STEP

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(
            QPainter.Antialiasing |
            QPainter.SmoothPixmapTransform |
            QPainter.TextAntialiasing,
        )
        # Partial repaints: only changed item rects redraw on a node drag, not the
        # whole viewport. The vignette is painted in drawBackground (under the nodes);
        # scrollContentsBy forces a full repaint on pan so it never smears.
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self._vignette_brush: Optional[QBrush] = None
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
        self._scrollbar_toggle_btn.setFixedSize(SCROLLBAR_BTN_SIZE, SCROLLBAR_BTN_SIZE)
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
        # Clamp so the graph can neither vanish nor magnify past readability.
        next_scale = self.transform().m11() * factor
        if next_scale < VIEW_ZOOM_MIN or next_scale > VIEW_ZOOM_MAX:
            return
        self.scale(factor, factor)

    def frame_content(self, items):
        """Fit the view to the given list of items (MetaNodes or any scene items)."""
        scene = self.scene()
        if scene is None or not items:
            return
        rect = items[0].sceneBoundingRect()
        for item in items[1:]:
            rect = rect.united(item.sceneBoundingRect())
        if not rect.isValid() or rect.isNull():
            return
        self.fitInView(rect.adjusted(-VIEW_FRAME_MARGIN, -VIEW_FRAME_MARGIN,
                                     VIEW_FRAME_MARGIN, VIEW_FRAME_MARGIN), Qt.KeepAspectRatio)
        # fitInView ignores zoom bounds; pull an over-zoomed single node back in.
        scale = self.transform().m11()
        if scale > VIEW_ZOOM_MAX:
            self.scale(VIEW_ZOOM_MAX / scale, VIEW_ZOOM_MAX / scale)

    def _build_vignette_brush(self):
        w = self.viewport().width()
        h = self.viewport().height()
        gradient = QRadialGradient(w / 2.0, h / 2.0, max(w, h) * VIGNETTE_RADIUS)
        gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
        gradient.setColorAt(1.0, QColor(*VIGNETTE_COLOR))
        self._vignette_brush = QBrush(gradient)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        # Grid first, then the vignette — both under the items, so nodes and wires
        # paint on top and stay un-dimmed; only the canvas/grid is darkened.
        if self.scene():
            self.scene().drawBackground(painter, rect)

        if self._vignette_brush is None:
            self._build_vignette_brush()
        painter.save()
        painter.resetTransform()  # viewport space — vignette is fixed to the screen
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._vignette_brush)
        painter.drawRect(0, 0, self.viewport().width(), self.viewport().height())
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

    def scrollContentsBy(self, dx: int, dy: int):
        super().scrollContentsBy(dx, dy)
        # A pan scroll-blits the viewport, which would smear the screen-fixed
        # vignette; force a full repaint so the background is redrawn cleanly.
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._build_vignette_brush()
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
