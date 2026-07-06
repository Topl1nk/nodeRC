from __future__ import annotations
from typing import Optional

from PyQt5.QtWidgets import (
    QGraphicsView, QGraphicsProxyWidget, QPushButton, QApplication, QWidget,
    QAbstractSpinBox, QComboBox,
)
from PyQt5.QtGui import QPainter, QColor, QRadialGradient, QBrush, QCursor
from PyQt5.QtCore import Qt, QPoint, QRectF, QTimer

from localization import t
from ui.graph_items import MetaNode
from configuration import (
    CANVAS_BACKGROUND_COLOR, SCROLLBAR_TOGGLE_BG, SCROLLBAR_TOGGLE_HOVER,
    VIGNETTE_COLOR, VIGNETTE_RADIUS, SCROLLBAR_BTN_MARGIN, SCROLLBAR_BTN_OFFSET,
    SCROLLBAR_BTN_SIZE, VIEW_ZOOM_STEP, VIEW_ZOOM_MIN, VIEW_ZOOM_MAX,
    VIEW_FRAME_MARGIN, NODE_HOVER_POLL_INTERVAL_MS,
    SCROLLBAR_TOGGLE_SHOW_GLYPH, SCROLLBAR_TOGGLE_HIDE_GLYPH,
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
        # Why: Partial repaints limit redraws to changed item rects during node drag.
        # scrollContentsBy forces full repaint on pan to avoid smearing the screen-fixed vignette.
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
        self._hovered_node: Optional[MetaNode] = None
        self._hovered_widget: Optional[QWidget] = None

        # Polling instead of relying on mouseMoveEvent: QGraphicsProxyWidget
        # does not reliably forward mouse-move to the view once a focusable/
        # editable embedded widget (QLineEdit, QComboBox) is under the cursor,
        # so the outline would silently stop updating for those fields. A
        # cheap timer reading the real OS cursor position sidesteps that
        # entirely — see _poll_hover / _update_hovered_node below, which stay
        # the single resolver either way.
        self._hover_poll_timer = QTimer(self)
        self._hover_poll_timer.setInterval(NODE_HOVER_POLL_INTERVAL_MS)
        self._hover_poll_timer.timeout.connect(self._poll_hover)
        self._hover_poll_timer.start()

        self._scrollbar_toggle_btn = QPushButton(SCROLLBAR_TOGGLE_SHOW_GLYPH, self)
        self._scrollbar_toggle_btn.setFixedSize(SCROLLBAR_BTN_SIZE, SCROLLBAR_BTN_SIZE)
        self._scrollbar_toggle_btn.setToolTip(t("tooltip_toggle_scrollbars"))
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
        # Wheel over an embedded widget (combo dropdown, spinbox, scrollable text)
        # must scroll/change the widget, not zoom the canvas — but only while its
        # node is actually selected or the field itself has focus. Otherwise a
        # scroll gesture passing over an untouched node (e.g. panning past it
        # with the wheel) would silently change a parameter's value.
        item = self.itemAt(event.pos())
        cursor = item
        while cursor is not None:
            if isinstance(cursor, QGraphicsProxyWidget):
                node = cursor.parentItem()
                widget = cursor.widget()
                node_selected = isinstance(node, MetaNode) and node.isSelected()
                focused = QApplication.focusWidget()
                field_focused = widget is not None and focused is not None and (
                    focused is widget or widget.isAncestorOf(focused))
                if node_selected or field_focused:
                    super().wheelEvent(event)
                    if event.isAccepted():
                        return
                break
            cursor = cursor.parentItem()

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
        # Why: fitInView ignores zoom bounds, which can over-zoom single nodes.
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
        # Why: Painting grid and vignette under nodes keeps visual elements un-dimmed.
        if self.scene():
            self.scene().drawBackground(painter, rect)

        if self._vignette_brush is None:
            self._build_vignette_brush()
        painter.save()
        painter.resetTransform()  # Why: fixed to screen coordinates
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

    def _poll_hover(self):
        # Geometric containment against the real OS cursor, not underMouse():
        # a focusable embedded widget (QLineEdit) can make Qt consider the
        # cursor "not over" this view's own widget once it starts handling
        # IME/text-cursor input for the embedded field, which made underMouse()
        # false-negative exactly for the fields that were never getting hover.
        pos = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(pos) or self.window() is None or not self.window().isActiveWindow():
            self._update_hovered_node(None)
            self._update_hovered_widget(None)
            return
        self._update_hovered_node(pos)
        self._update_hovered_widget(self._resolve_leaf_widget(pos))

    def _resolve_leaf_widget(self, pos: QPoint) -> Optional[QWidget]:
        """The specific embedded leaf widget (QLineEdit, QToolButton, ...)
        under the cursor, resolved via ``itemAt()`` and proxy-local
        coordinates — the same reliable mechanism ``_update_hovered_node``
        uses for the node itself — rather than
        ``QApplication.widgetAt(QCursor.pos())``. Global-screen widget
        lookup turned out not to reliably resolve QGraphicsProxyWidget-
        embedded content either (sometimes the wrong widget, sometimes
        none), which is what produced hover outlines that were missing on
        some fields and, since a stale one could be left lit next to a
        freshly-lit one, looked like they overlapped.
        """
        item = self.itemAt(pos)
        proxy = item
        while proxy is not None and not isinstance(proxy, QGraphicsProxyWidget):
            proxy = proxy.parentItem()
        if proxy is None:
            return None
        top_widget = proxy.widget()
        if top_widget is None:
            return None
        local_pos = proxy.mapFromScene(self.mapToScene(pos)).toPoint()
        leaf = top_widget.childAt(local_pos)
        if leaf is None:
            return top_widget
        # A compound editor (QSpinBox, QComboBox) carries its own [nodeHover]
        # rule on itself, not on the native internal child childAt() actually
        # lands on (e.g. the spin box's built-in QLineEdit) — climb back up to
        # that compound widget so the property lands where the stylesheet
        # looks for it, instead of on an untargeted descendant.
        w = leaf
        while w is not top_widget:
            if isinstance(w, (QAbstractSpinBox, QComboBox)):
                return w
            w = w.parentWidget()
        return leaf

    def _update_hovered_node(self, pos: Optional[QPoint]):
        """The single, authoritative source of the node hover outline: which
        MetaNode is under the cursor right now, resolved via the same item-
        picking Qt itself uses (``itemAt``) — not per-item hover events, which
        QGraphicsProxyWidget children (text fields, combo boxes...) don't
        reliably deliver mouse-move to in the first place. One resolver
        covers bare node canvas and every embedded widget identically, so
        there is nothing left that could wire hover differently per widget
        type. ``pos is None`` means the cursor is outside the viewport.
        """
        item = self.itemAt(pos) if pos is not None else None
        node = item
        while node is not None and not isinstance(node, MetaNode):
            node = node.parentItem()
        if node is self._hovered_node:
            return
        old_node = self._hovered_node
        if old_node is not None:
            try:
                old_node._set_hovered(False)
            except RuntimeError:
                old_node = None  # deleted from under us — nothing left to repaint
        self._hovered_node = node
        if node is not None:
            node._set_hovered(True)
        # Force a repaint of exactly the old/new node's own area rather than
        # trusting SmartViewportUpdate's automatic dirty-region tracking (an
        # embedded proxy widget's area isn't always covered by it) or, at the
        # other extreme, repainting the *entire* viewport on every hover
        # change — on a large, zoomed-out scene that turns a hover flicker
        # between two small nodes into a full-canvas redraw every ~40ms poll
        # tick. Explicitly updating just the two nodes' mapped rects keeps
        # the "don't rely on automatic tracking" guarantee this replaced
        # without paying for the untouched rest of the canvas.
        for changed_node in (old_node, node):
            if changed_node is None:
                continue
            try:
                rect = self.mapFromScene(changed_node.sceneBoundingRect()).boundingRect()
            except RuntimeError:
                continue  # deleted from under us
            self.viewport().update(rect)

    def _update_hovered_widget(self, widget: Optional[QWidget]):
        """Drives the ``[nodeHover="true"]`` QSS state on embedded field/
        button widgets (theme.py) from the same cursor poll that drives the
        node border — QGraphicsProxyWidget does not reliably clear a widget's
        native :hover pseudo-state when the cursor moves between sibling
        widgets sharing one wrapper container (EnumParamNode's new-item row,
        PathParamNode's row containers), which left the border stuck lit
        after the cursor moved on. Resolving the hovered widget from our own
        ground-truth poll instead — the same fix already applied to the node
        border itself — removes the dependency on that unreliable delivery
        entirely rather than special-casing the wrapped widgets.
        """
        if widget is self._hovered_widget:
            return
        if self._hovered_widget is not None:
            try:
                self._hovered_widget.setProperty("nodeHover", "false")
                self._hovered_widget.style().unpolish(self._hovered_widget)
                self._hovered_widget.style().polish(self._hovered_widget)
            except RuntimeError:
                pass  # the previously-hovered widget was deleted from under us
        self._hovered_widget = widget
        if widget is not None:
            widget.setProperty("nodeHover", "true")
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def leaveEvent(self, event):
        # Instant clear on leaving the viewport, instead of waiting up to one
        # poll tick — same single resolvers as _poll_hover, just told directly
        # that the cursor is nowhere in the view.
        self._update_hovered_node(None)
        self._update_hovered_widget(None)
        super().leaveEvent(event)

    def scrollContentsBy(self, dx: int, dy: int):
        super().scrollContentsBy(dx, dy)
        # Why: A pan scroll-blits the viewport, smearing the screen-fixed vignette.
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
        self._scrollbar_toggle_btn.setText(
            SCROLLBAR_TOGGLE_HIDE_GLYPH if self._scrollbars_visible
            else SCROLLBAR_TOGGLE_SHOW_GLYPH)
