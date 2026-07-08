"""title_item.py — Inline-Editing Title and Rename Mixin

Shared by MetaNode and GroupFrameItem — extracted here to break the circular
dependency between the two when they live in separate modules.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QGraphicsTextItem, QMenu
from PyQt5.QtGui import QColor, QPainterPath, QFont, QTextCursor
from PyQt5.QtCore import Qt

from configuration import (
    UI_FONT_FAMILY, NODE_RENAME_FONT_SIZE, TEXT_COLOR, NODE_SOCKET_Z,
)
from ui.keymap import KEY_COMMIT_EDIT, KEY_CANCEL_EDIT
from ui.theme import CONTEXT_MENU_STYLESHEET


def editor_window_of(item):
    """The editor window owning a scene item, or None when it is unparented."""
    if item is None:
        return None
    try:
        scene = item.scene()
    except RuntimeError:
        return None
    return getattr(scene, "nodeEditorWindow", None) if scene else None


def selected_of_type_including(item, cls):
    """Scene's currently-selected items of ``cls``, guaranteed to include ``item``.

    Shared by MetaNode and GroupFrameItem's color pickers so a multi-select
    color change always covers the item the user right-clicked, even if it
    wasn't part of the selection.
    """
    selected = [other for other in item.scene().selectedItems() if isinstance(other, cls)]
    if item not in selected:
        selected.append(item)
    return selected


def run_context_menu(event, actions) -> None:
    """The one right-click-menu builder for both MetaNode and GroupFrameItem
    (Ст.14.3/Ст.1.1) — before this, GroupFrameItem's own contextMenuEvent
    reimplemented a menu ad hoc: no hotkey-hint column, and a hardcoded
    if/elif dispatch instead of this shared tuple-list convention, so its
    menu structurally drifted from every node's. One QSS, one hint
    convention, one dispatch mechanism now backs both.

    Each entry in ``actions`` is either:
      - ``(label, callback, enabled)`` or ``(label, callback, enabled, hint)``
        — a normal action; ``hint`` (e.g. "Ctrl+D") is shown right-aligned,
        display-only — see HOTKEY_HINTS in configuration.py
      - ``None``                       — a visual separator
    """
    menu = QMenu()
    menu.setStyleSheet(CONTEXT_MENU_STYLESHEET)
    handlers = {}
    for item in actions:
        if item is None:
            menu.addSeparator()
            continue
        label, callback, enabled, *rest = item
        hint = rest[0] if rest else None
        text = f"{label}\t{hint}" if hint else label
        entry = menu.addAction(text)
        entry.setEnabled(enabled and callback is not None)
        handlers[entry] = callback
    chosen = menu.exec_(event.screenPos())
    if chosen is not None and handlers.get(chosen):
        handlers[chosen]()
    event.accept()


def _merge_hsv_component(current_hex: str, picked_hex: str,
                         changed_component: str) -> str:
    """Merge a single HSV/alpha component from ``picked_hex`` into ``current_hex``."""
    cur = QColor(current_hex)
    pick = QColor(picked_hex)
    h, s, v, a = cur.getHsvF()
    if changed_component == 'a':
        cur.setAlpha(pick.alpha())
    elif changed_component == 'h':
        cur.setHsvF(max(0.0, pick.hsvHueF()), s, v, a)
    elif changed_component == 's':
        cur.setHsvF(max(0.0, h), pick.hsvSaturationF(), v, a)
    elif changed_component == 'v':
        cur.setHsvF(max(0.0, h), s, pick.valueF(), a)
    elif changed_component == 'sv':
        cur.setHsvF(max(0.0, h), pick.hsvSaturationF(), pick.valueF(), a)
    else:
        return picked_hex
    return cur.name(QColor.HexArgb)


class _EditableTitleItem(QGraphicsTextItem):
    """Header title that edits in place; commits on Enter/focus-out, reverts on Esc."""

    def __init__(self, host):
        super().__init__(host)
        self._host = host
        self._editing = False
        self.setAcceptedMouseButtons(Qt.NoButton)

    def begin_editing(self):
        self._editing = True
        self.setAcceptedMouseButtons(Qt.AllButtons)
        self.prepareGeometryChange()

    def end_editing(self):
        self._editing = False
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.prepareGeometryChange()

    def shape(self):
        # Empty while not editing so clicks/double-clicks pass through to the
        # node body instead of hit-testing the title.
        if not self._editing:
            return QPainterPath()
        return super().shape()

    def contains(self, point):
        # Point hit-testing (itemAt, scene picking) goes through contains(),
        # not through boundingRect() — so this, not boundingRect(), is what
        # makes clicks/double-clicks pass through to the node body while not
        # editing. boundingRect() is deliberately left reporting the item's
        # real paint area (see below): it's what the scene uses to know which
        # screen region needs repainting, and a connection wire passing close
        # to the header would trigger a partial repaint of just its own area —
        # if the title claimed an empty bounding rect, the scene wouldn't know
        # the title also lives there and would skip repainting it, leaving
        # stale/erased text until something else forced a full node repaint.
        if not self._editing:
            return False
        return super().contains(point)

    def paint(self, painter, option, widget=None):
        if self.textInteractionFlags() != Qt.NoTextInteraction:
            backdrop = self._host.title_edit_background()
            if backdrop:
                painter.fillRect(
                    self.boundingRect().adjusted(-2, -1, 2, 1), QColor(backdrop))
        super().paint(painter, option, widget)

    def keyPressEvent(self, event):
        if event.key() in KEY_COMMIT_EDIT:
            self._host._commit_rename()
            event.accept()
        elif event.key() == KEY_CANCEL_EDIT:
            self._host._cancel_rename()
            event.accept()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._host._commit_rename()

    def _is_editing(self) -> bool:
        return self.textInteractionFlags() != Qt.NoTextInteraction

    def mousePressEvent(self, event):
        if not self._is_editing():
            event.ignore()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._is_editing():
            event.ignore()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if not self._is_editing():
            event.ignore()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if not self._is_editing():
            event.ignore()
            return
        super().mouseDoubleClickEvent(event)


class RenamableTitleMixin:
    """One in-place rename lifecycle shared by nodes and group frames."""

    def _rename_font(self) -> QFont:
        return QFont(UI_FONT_FAMILY, NODE_RENAME_FONT_SIZE)

    def _rename_text_color(self) -> str:
        return TEXT_COLOR

    def _title_source_text(self) -> str:
        return self.title_item.toPlainText()

    def _commit_title(self, name: str):
        raise NotImplementedError

    def _revert_title(self, backup: str):
        raise NotImplementedError

    def _begin_rename(self):
        item = self.title_item
        self._rename_backup = self._title_source_text()
        item.setDefaultTextColor(QColor(self._rename_text_color()))
        item.setFont(self._rename_font())
        item.setPlainText(self._rename_backup)
        item.setZValue(NODE_SOCKET_Z)
        item.setTextInteractionFlags(Qt.TextEditorInteraction)
        item.begin_editing()
        item.setFocus(Qt.OtherFocusReason)
        cursor = item.textCursor()
        cursor.select(QTextCursor.Document)
        item.setTextCursor(cursor)

    def _end_rename(self) -> bool:
        item = self.title_item
        if item.textInteractionFlags() == Qt.NoTextInteraction:
            return False
        item.setTextInteractionFlags(Qt.NoTextInteraction)
        item.end_editing()
        item.setZValue(0)
        return True

    def _commit_rename(self):
        if not self._end_rename():
            return
        name = self.title_item.toPlainText().strip() or self._rename_backup
        self._commit_title(name)
        win = editor_window_of(self)
        if win:
            win.push_undo_state()

    def _cancel_rename(self):
        if not self._end_rename():
            return
        self._revert_title(self._rename_backup)
