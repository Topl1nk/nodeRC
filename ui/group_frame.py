"""group_frame.py — Group Frame Item

A backdrop rectangle that holds nodes: drag the header to move it (and its
contents), drag any edge or corner to resize, or right-click for group
operations. Color picking, rename and membership are all here.
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtWidgets import (
    QGraphicsItem, QGraphicsRectItem, QGraphicsTextItem,
    QMenu,
)
from PyQt5.QtGui import (
    QPen, QBrush, QColor, QPainter, QPainterPath, QFont, QFontMetrics, QCursor,
)
from PyQt5.QtCore import QRectF, Qt, QPointF

from localization import resolve_default_title, t
from configuration import (
    NODE_SELECTED_COLOR, GRID_SIZE_SMALL,
    GROUP_FRAME_Z, GROUP_FRAME_FILL_ALPHA,
    GROUP_FRAME_BORDER_WIDTH, GROUP_FRAME_TITLE_COLOR,
    GROUP_FRAME_TITLE_FONT, GROUP_FRAME_TITLE_FONT_SIZE, GROUP_FRAME_TITLE_MARGIN,
    GROUP_FRAME_HEADER_HEIGHT, GROUP_FRAME_HEADER_DARKEN,
    GROUP_FRAME_HANDLE, GROUP_FRAME_MIN_SIZE, GROUP_FRAME_BORDER_INSET,
)
from ui.theme import (
    GROUP_FRAME_BORDER_COLOR, brightened_for_canvas, CONTEXT_MENU_STYLESHEET,
)
from ui.title_item import (
    _EditableTitleItem, RenamableTitleMixin,
    editor_window_of, _merge_hsv_component, selected_of_type_including,
)
from ui.color_picker import ColorPickerPopup
from ui.widgets import suppress_default_selection_chrome


class GroupFrameItem(RenamableTitleMixin, QGraphicsRectItem):
    """A backdrop frame that holds nodes: drag the body to move it (and its
    contents), drag any edge or corner to resize it, drag to fit, or refit it to
    the nodes it overlaps."""

    _RESIZE_NONE = (False, False, False, False)

    def __init__(self, rect: QRectF, title: Optional[str] = None):
        super().__init__(QRectF(
            0, 0,
            max(GROUP_FRAME_MIN_SIZE, self._snap(rect.width())),
            max(GROUP_FRAME_MIN_SIZE, self._snap(rect.height())),
        ))
        self.setPos(self._snap(rect.x()), self._snap(rect.y()))
        self.title = title if title is not None else t("default_group_title")
        self.setZValue(GROUP_FRAME_Z)
        self.setFlags(
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self._color = GROUP_FRAME_BORDER_COLOR
        self._apply_color()

        self._resizing = False
        self._resize_edges = self._RESIZE_NONE

        self._dragged_inner_nodes: list = []
        self._group_members: list = []
        # Level-of-detail (see _set_lod_far / GraphicsView._apply_lod, same
        # NODE_LOD_DETAIL_SCALE threshold MetaNode uses): below the
        # threshold nothing about the title changes at all — it scales down
        # with the frame exactly like before there was any LOD handling.
        # Only once the threshold is actually crossed does it switch, as one
        # discrete step, to a constant screen size anchored above the whole
        # frame — never a gradual reaction to the current zoom.
        self._lod_far = False

        self.title_item = _EditableTitleItem(self)
        self.title_item.setFont(self._rename_font())
        self.title_item.setHtml(self._title_html(self.title))
        self._center_title()

    # ── Appearance ────────────────────────────────────────────────────────────

    @staticmethod
    def _title_html(name: str) -> str:
        import html as _html
        return (f"<font color='{GROUP_FRAME_TITLE_COLOR}'>"
                f"<b>{_html.escape(name)}</b></font>")

    def _current_view_scale(self) -> float:
        scene = self.scene()
        if scene is not None:
            views = scene.views()
            if views:
                scale = views[0].transform().m11()
                if scale:
                    return scale
        return 1.0

    # Gap (device px) kept between the selection outline's top edge (see
    # paint()'s dashed rect, offset outward from rect() by
    # GROUP_FRAME_BORDER_INSET) and the title's own bottom edge once
    # LOD-far — just enough that the constant-size label reads as "floating
    # above" the outline rather than touching it.
    _LOD_TITLE_GAP_PX = 10

    def _set_lod_far(self, far: bool):
        """Toggle the far-zoom level of detail for the title (see
        NODE_LOD_DETAIL_SCALE, GraphicsView._apply_lod). The mode itself is
        a single, discrete switch at the threshold, not a gradual reaction
        to the current scale — below it the title behaves exactly as if
        this LOD handling didn't exist (plain text, scales with the frame,
        centered in the header); only once crossed does it switch to a
        constant screen size anchored above the frame.

        _center_title() still gets re-run on every call, though, even while
        ``far`` stays the same as last time: in far mode its anchor is
        deliberately calibrated against the *current* scale (see its
        docstring) so the gap it keeps above the (still shrinking) frame
        stays visually constant as the user keeps zooming out — without
        this, that gap would only be right for the exact scale LOD first
        engaged at, and drift after.
        """
        if self._lod_far != far:
            self._lod_far = far
            self.title_item.setFlag(QGraphicsItem.ItemIgnoresTransformations, far)
        self._center_title()

    def _lod_title_rect(self) -> QRectF:
        """Where the title sits while LOD-far, in this frame's own local
        coordinates — the single source of truth both _center_title (which
        anchors title_item here) and boundingRect/shape (which extend this
        item's own hit-test area to cover it, so clicking/double-clicking
        the title still drags/renames the frame via the exact same
        mousePressEvent/mouseDoubleClickEvent this class already has — no
        second, parallel drag/rename path needed) read from.

        Anchored off the selection outline itself (see paint()'s dashed
        rect, offset outward from rect() by GROUP_FRAME_BORDER_INSET) —
        left-aligned to its left edge and pinned _LOD_TITLE_GAP_PX above
        its top edge — so the title stays in the same visual relationship
        to the outline regardless of the current view scale.
        """
        scale = self._current_view_scale()
        metrics = QFontMetrics(self._rename_font())
        text_w_px = metrics.horizontalAdvance(self.title)
        text_h_px = metrics.height()
        r = self.rect()
        left = r.left() - GROUP_FRAME_BORDER_INSET
        right = left + text_w_px / scale
        dashed_top = r.top() - GROUP_FRAME_BORDER_INSET
        bottom = dashed_top - self._LOD_TITLE_GAP_PX / scale
        top = bottom - text_h_px / scale
        return QRectF(left, top, right - left, bottom - top)

    def _center_title(self):
        """Position the title. Below the LOD threshold this is the original,
        pre-LOD behavior verbatim: centered in the header, scaling normally
        with the frame like everything else about it. Past the threshold
        (``self._lod_far``), the title instead ignores the view's
        transformation (see _set_lod_far) and is anchored per
        _lod_title_rect — above the frame and its selection outline,
        right-aligned to the frame's own edge — regardless of how small the
        frame has shrunk to.
        """
        if not hasattr(self, 'title_item'):
            return
        if not self._lod_far:
            r = self.rect()
            text_h = QGraphicsTextItem.boundingRect(self.title_item).height()
            y = r.top() + (GROUP_FRAME_HEADER_HEIGHT - text_h) / 2.0
            self.title_item.setPos(r.left() + GROUP_FRAME_TITLE_MARGIN, y)
            return
        rect = self._lod_title_rect()
        self.title_item.setPos(rect.left(), rect.top())

    def title_edit_background(self) -> Optional[str]:
        return None

    # ── Frame color ───────────────────────────────────────────────────────────

    def _apply_color(self):
        c = QColor(self._color)
        fill = QColor(c)
        if len(self._color) < 9:
            fill.setAlpha(GROUP_FRAME_FILL_ALPHA)
        self.setBrush(QBrush(fill))
        self.setPen(QPen(Qt.NoPen))

    def color(self) -> str:
        return self._color

    def set_color(self, color_hex: str, *, record_undo: bool = True):
        self._color = color_hex
        self._apply_color()
        self.update()
        win = editor_window_of(self)
        if record_undo and win:
            win.push_undo_state()

    def _pick_color(self):
        win = editor_window_of(self)
        if not win:
            return

        selected_frames = selected_of_type_including(self, GroupFrameItem)

        def on_close():
            win.push_undo_state()

        def apply_color_to_all(c, only_header, changed_component=None):
            for frame in selected_frames:
                merged = _merge_hsv_component(frame._color, c, changed_component)
                frame.set_color(merged, record_undo=False)

        def reset_all():
            for frame in selected_frames:
                frame.set_color(GROUP_FRAME_BORDER_COLOR, record_undo=False)
            return GROUP_FRAME_BORDER_COLOR, False

        current = QColor(self._color)
        if len(self._color) < 9:
            current.setAlpha(GROUP_FRAME_FILL_ALPHA)

        popup = ColorPickerPopup(
            on_color_selected=apply_color_to_all,
            on_reset=reset_all,
            initial_color=current.name(QColor.HexArgb),
            on_close=on_close,
            parent=win
        )
        popup.move(QCursor.pos())
        popup.show()

    def boundingRect(self) -> QRectF:
        margin = GROUP_FRAME_BORDER_INSET + GROUP_FRAME_BORDER_WIDTH
        rect = super().boundingRect().adjusted(-margin, -margin, margin, margin)
        if self._lod_far:
            rect = rect.united(self._lod_title_rect())
        return rect

    def shape(self) -> QPainterPath:
        # Unmodified below the LOD threshold — same hit area this item has
        # always had. Past it, the title's own footprint (see
        # _lod_title_rect) is unioned in so a click/double-click landing on
        # the now-floating title is delivered to this item exactly like one
        # on the header always was, and mousePressEvent/mouseDoubleClickEvent
        # below handle it with no changes of their own.
        path = super().shape()
        if self._lod_far:
            path.addRect(self._lod_title_rect())
        return path

    def paint(self, painter, option, widget):
        suppress_default_selection_chrome(option)
        painter.setRenderHint(QPainter.Antialiasing)
        super().paint(painter, option, widget)

        r = self.rect()
        header_color = QColor(self._color).darker(GROUP_FRAME_HEADER_DARKEN)
        header_color.setAlpha(255)
        header_rect = QRectF(r.left(), r.top(), r.width(),
                             min(GROUP_FRAME_HEADER_HEIGHT, r.height()))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(header_color))
        painter.drawRect(header_rect)

        accent = brightened_for_canvas(QColor(self._color))
        painter.setPen(QPen(accent, 1))
        painter.drawLine(
            QPointF(header_rect.left(), header_rect.bottom()),
            QPointF(header_rect.right(), header_rect.bottom()),
        )

        if self.isSelected():
            outset = GROUP_FRAME_BORDER_INSET
            outline = r.adjusted(-outset, -outset, outset, outset)
            painter.setPen(QPen(QColor(NODE_SELECTED_COLOR),
                                GROUP_FRAME_BORDER_WIDTH, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(outline)

    @staticmethod
    def _snap(value: float) -> float:
        return round(value / GRID_SIZE_SMALL) * GRID_SIZE_SMALL

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            if self._resizing:
                return value
            snapped = QPointF(self._snap(value.x()), self._snap(value.y()))
            delta = snapped - self.pos()
            if delta.manhattanLength() > 0.01:
                for item in getattr(self, '_dragged_inner_nodes', []):
                    if item.scene() and not item.isSelected():
                        item.moveBy(delta.x(), delta.y())
            return snapped
        return super().itemChange(change, value)

    # ── Manual resize ─────────────────────────────────────────────────────────

    def _edge_at(self, pos: QPointF):
        r = self.rect()
        h = GROUP_FRAME_HANDLE
        within_x = r.left() - h <= pos.x() <= r.right() + h
        within_y = r.top() - h <= pos.y() <= r.bottom() + h
        left   = abs(pos.x() - r.left())   <= h and within_y
        right  = abs(pos.x() - r.right())  <= h and within_y
        top    = abs(pos.y() - r.top())    <= h and within_x
        bottom = abs(pos.y() - r.bottom()) <= h and within_x
        edges = (left, top, right, bottom)
        return edges if edges != self._RESIZE_NONE else None

    @staticmethod
    def _cursor_for_edges(edges) -> Qt.CursorShape:
        left, top, right, bottom = edges
        if (left and top) or (right and bottom):
            return Qt.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.SizeBDiagCursor
        if left or right:
            return Qt.SizeHorCursor
        return Qt.SizeVerCursor

    def hoverMoveEvent(self, event):
        edges = self._edge_at(event.pos())
        if edges:
            self.setCursor(self._cursor_for_edges(edges))
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        edges = self._edge_at(event.pos()) if event.button() == Qt.LeftButton else None
        if edges:
            self._resizing = True
            self._resize_edges = edges
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            self._apply_resize(event.scenePos())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self._resize_edges = self._RESIZE_NONE
            win = editor_window_of(self)
            if win:
                win.push_undo_state()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
        self.commit_members(force_all=False)

    # ── Membership ────────────────────────────────────────────────────────────

    def _scene_rect(self) -> QRectF:
        return self.mapToScene(self.rect()).boundingRect()

    def contains_node(self, node) -> bool:
        """Whether ``node``'s center currently sits inside this frame — the
        one containment test every membership decision in this class (and
        MetaNode._adopt_containing_frame, the reverse direction: which frame
        is under a just-moved node) goes through, so "inside the frame" can
        only ever mean one thing."""
        return self._scene_rect().contains(node.sceneBoundingRect().center())

    def _contained_nodes(self, candidates: Optional[list] = None) -> list:
        """Nodes under this frame. ``candidates``, when given, is used instead
        of a fresh ``scene.items()`` scan — a caller committing many frames
        at once (e.g. materialize_graph after a load) collects the scene's
        MetaNodes once and passes the same list to every frame, instead of
        each frame re-fetching and re-sorting the whole scene by Z-order for
        itself (O(frames x scene size) on a graph with many group frames)."""
        from ui.graph_items import MetaNode
        scene = self.scene()
        if not scene:
            return []
        if candidates is None:
            if hasattr(scene, '_meta_nodes'):
                candidates = scene._meta_nodes
            else:
                candidates = [item for item in scene.items() if isinstance(item, MetaNode)]
        return [item for item in candidates
                if item is not self and self.contains_node(item)]

    def commit_members(self, force_all: bool = False, candidates: Optional[list] = None):
        scene = self.scene()
        if not scene:
            self._group_members = []
            return
        if force_all:
            self._group_members = self._contained_nodes(candidates)
            for node in self._group_members:
                node._group_frame = self
        else:
            still_inside = []
            for node in getattr(self, '_group_members', []):
                if node.scene() is scene and self.contains_node(node):
                    still_inside.append(node)
                else:
                    if getattr(node, '_group_frame', None) is self:
                        node._group_frame = None
            self._group_members = still_inside

    def _apply_resize(self, scene_pos: QPointF):
        left, top, right, bottom = self._resize_edges
        rect = self.rect()
        x0, y0 = self.pos().x() + rect.left(), self.pos().y() + rect.top()
        x1, y1 = x0 + rect.width(), y0 + rect.height()
        sx, sy = self._snap(scene_pos.x()), self._snap(scene_pos.y())
        m = GROUP_FRAME_MIN_SIZE
        if left:   x0 = min(sx, x1 - m)
        if right:  x1 = max(sx, x0 + m)
        if top:    y0 = min(sy, y1 - m)
        if bottom: y1 = max(sy, y0 + m)
        self.setPos(x0, y0)
        self.setRect(0, 0, x1 - x0, y1 - y0)
        self._center_title()

    # ── Rename ────────────────────────────────────────────────────────────────

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and not self._edge_at(event.pos()):
            self._begin_rename()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def _rename_font(self) -> QFont:
        return QFont(GROUP_FRAME_TITLE_FONT, GROUP_FRAME_TITLE_FONT_SIZE)

    def _rename_text_color(self) -> str:
        return GROUP_FRAME_TITLE_COLOR

    def _title_source_text(self) -> str:
        return self.title

    def _commit_title(self, name: str):
        self.title = name
        self.title_item.setHtml(self._title_html(name))
        self._center_title()

    def _revert_title(self, backup: str):
        self.title_item.setHtml(self._title_html(backup))
        self._center_title()

    def retranslate(self):
        """Re-resolve the title if it's still the untouched default — same
        detection rule as ParamNode.retranslate (see its docstring): a title
        matching a known translation of "default_group_title" in any
        language is treated as "never renamed"."""
        resolved = resolve_default_title(self.title, "default_group_title")
        if resolved != self.title:
            self._commit_title(resolved)

    # ── Context menu and contained-node operations ────────────────────────────

    def contextMenuEvent(self, event):
        win = editor_window_of(self)
        if not win:
            super().contextMenuEvent(event)
            return

        menu = QMenu()
        menu.setStyleSheet(CONTEXT_MENU_STYLESHEET)

        rename_act = menu.addAction(t("ctx_rename_group"))
        color_act  = menu.addAction(t("ctx_change_color"))
        menu.addSeparator()
        remove_frame_act = menu.addAction(t("ctx_remove_frame"))
        clear_frame_act  = menu.addAction(t("ctx_clear_frame"))
        delete_group_act = menu.addAction(t("ctx_delete_group"))

        chosen = menu.exec_(event.screenPos())
        if chosen == rename_act:
            self._begin_rename()
        elif chosen == color_act:
            self._pick_color()
        elif chosen == remove_frame_act:
            self._remove_frame()
        elif chosen == clear_frame_act:
            self._clear_frame()
        elif chosen == delete_group_act:
            self._delete_group()
        event.accept()

    def _remove_frame(self):
        scene = self.scene()
        win = editor_window_of(self)
        if scene:
            scene.removeItem(self)
            if win:
                win.push_undo_state()

    def _delete_contained(self, also_remove_frame: bool):
        scene = self.scene()
        win = editor_window_of(self)
        if not (scene and win):
            return
        targets = [n for n in self._contained_nodes() if not n.is_protected]
        win._block_undo_push = True
        try:
            scene.clearSelection()
            for node in targets:
                node.setSelected(True)
            if targets:
                win._delete_selected_items()
            if also_remove_frame:
                scene.removeItem(self)
        finally:
            win._block_undo_push = False
        win.push_undo_state()

    def _clear_frame(self):
        self._delete_contained(also_remove_frame=False)

    def _delete_group(self):
        self._delete_contained(also_remove_frame=True)
