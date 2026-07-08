"""title_bar.py — Custom Frameless Window Chrome

Replaces the native OS title bar so open projects can live as tabs directly
in the chrome, the way Windows 11 Notepad does. TitleBarWidget hosts the tab
strip plus the window's own minimize/maximize/close controls. Drag-to-move
and edge resize on Windows are handled by the window's own nativeEvent
(WM_NCHITTEST override in editor_window.py) when the window isn't maximized,
which also restores native edge-snap; this widget's own mouse handlers cover
everything nativeEvent doesn't: dragging on non-Windows platforms, and
dragging a *maximized* window on Windows (which never gets the real Win32
WS_MAXIMIZE style as a frameless window, so the native "drag the caption to
restore" behavior never fires for it — see _native_drag_handles_this()).
"""
from __future__ import annotations

import os
import sys
from typing import Callable, List, Optional

from PyQt5.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMenu, QSizePolicy, QToolButton, QWidget,
    QStyle, QStyleOption, QStyleOptionToolButton,
)
from PyQt5.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt
from PyQt5.QtGui import (
    QBrush, QColor, QCursor, QLinearGradient, QPainterPath, QPalette, QPainter, QPen, QRegion,
)

from localization import t
from configuration import (
    TITLE_BAR_HEIGHT, TITLE_BAR_BTN_WIDTH,
    TAB_HEIGHT, TAB_MIN_WIDTH, TAB_MAX_WIDTH,
    WINDOW_CORNER_RADIUS, HOTKEY_HINTS,
)
from ui.theme import (
    TITLE_BAR_QSS, TAB_STRIP_QSS, TAB_BUTTON_QSS, TITLE_BAR_MENU_STYLESHEET,
    NODE_BORDER_COLOR, TAB_GRADIENT_DARK, TAB_GRADIENT_LIGHT, TEXT_COLOR,
    TITLE_BAR_CLOSE_HOVER_COLOR,
)
from ui.window_chrome import show_system_menu, restore_without_animation, handoff_to_native_caption_drag

TAB_SLIDE_ANIM_MS = 140  # how long other tabs take to slide open a gap for a dragged one


def _add_action_with_hint(menu, label: str, hint: Optional[str], callback):
    """Add a QMenu action whose keyboard shortcut is shown as plain,
    right-aligned text (Qt's classic "Label\\tCtrl+X" convention) — display
    only, not a live QAction.setShortcut() binding. The real hotkey dispatch
    lives entirely in NodeEditorWindow.keyPressEvent, which is layout-
    independent via a nativeVirtualKey() remap; a live Qt shortcut here
    wouldn't share that guarantee and would fire in parallel with it."""
    text = f"{label}\t{hint}" if hint else label
    return menu.addAction(text, callback)


def _paint_tab_face(painter: QPainter, w: int, h: int, active: bool) -> None:
    """The tab-face background gradient — the QPainter twin of the QSS
    background in TAB_BUTTON_QSS (same TAB_GRADIENT_* stops, same
    orientation per state), for the pieces of tab chrome that aren't
    QSS-painted widgets (the hover close button)."""
    gradient = QLinearGradient(0, 0, 0, h)
    top, bottom = (TAB_GRADIENT_LIGHT, TAB_GRADIENT_DARK) if active else (TAB_GRADIENT_DARK, TAB_GRADIENT_LIGHT)
    gradient.setColorAt(0.0, QColor(top))
    gradient.setColorAt(1.0, QColor(bottom))
    painter.fillRect(0, 0, w, h, QBrush(gradient))


def _paint_tab_outline(painter: QPainter, w: int, h: int, active: bool) -> None:
    """The tab outline: solid at the anchored edge (top when active, bottom
    when inactive — the seam shared with the canvas below / strip above),
    fading smoothly to fully transparent toward the opposite edge, which
    carries no border at all. One painter for both the tab itself and the
    hover close button, so the two can't drift apart.
    """
    border_color = QColor(NODE_BORDER_COLOR)
    solid = QColor(border_color)
    solid.setAlpha(255)
    transparent = QColor(border_color)
    transparent.setAlpha(0)

    gradient = QLinearGradient(0, 0, 0, h)
    if active:
        gradient.setColorAt(0.0, solid)
        gradient.setColorAt(1.0, transparent)
    else:
        gradient.setColorAt(0.0, transparent)
        gradient.setColorAt(1.0, solid)

    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.setPen(QPen(QBrush(gradient), 1))
    painter.drawLine(0, 0, 0, h - 1)          # left edge
    painter.drawLine(w - 1, 0, w - 1, h - 1)  # right edge

    painter.setPen(QPen(solid, 1))
    if active:
        painter.drawLine(0, 0, w - 1, 0)          # top edge, full opacity
    else:
        painter.drawLine(0, h - 1, w - 1, h - 1)  # bottom edge, full opacity


class TabCloseButton(QToolButton):
    """The square, full-tab-height close button that appears at a hovered
    tab's right edge. Painted as a miniature copy of its own tab — the same
    face gradient and outline in whichever active/inactive state the tab is
    currently in (read live off the parent's "active" property), via the
    shared painters above — with the '×' centered on top. Hovering the
    button itself turns it the same red the window's own close button uses
    (TITLE_BAR_CLOSE_HOVER_COLOR)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.ArrowCursor)
        self._hovered = False

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        active = self.parentWidget() is not None and self.parentWidget().property("active") == "true"
        if self._hovered:
            painter.fillRect(0, 0, w, h, QColor(TITLE_BAR_CLOSE_HOVER_COLOR))
        else:
            _paint_tab_face(painter, w, h, active)
        _paint_tab_outline(painter, w, h, active)
        painter.setPen(QColor(TEXT_COLOR))
        font = painter.font()
        font.setPointSize(12)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, "×")


class TabButton(QWidget):
    """One open project: title label + close 'x'. Click switches to it, the
    'x' or a middle-click closes it, right-click opens the tab context menu.
    Dragging it sideways visually follows the cursor (Chrome-style) — see
    TabStripWidget._start_drag/_update_drag/_end_drag, which own the actual
    floating/reorder mechanics; this widget just forwards raw mouse events."""

    def __init__(self, tab, on_select: Callable, on_close: Callable,
                 on_drag: Callable, on_context_menu: Callable, parent=None):
        super().__init__(parent)
        self.tab = tab
        self._on_select = on_select
        self._on_close = on_close
        self._on_drag = on_drag
        self._on_context_menu = on_context_menu
        self._press_pos: Optional[object] = None
        self._dragging = False
        self._hovered = False
        self.setObjectName("TabButton")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(TAB_BUTTON_QSS)
        self.setFixedHeight(TAB_HEIGHT)
        self.setMinimumWidth(TAB_MIN_WIDTH)
        self.setMaximumWidth(TAB_MAX_WIDTH)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(10, 0, 4, 0)
        self._layout.setSpacing(4)

        self.label = QLabel()
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._layout.addWidget(self.label)

        # Not in the layout: a square, full-height overlay anchored to the
        # right edge (see _position_close_btn/_set_hovered) instead of a
        # small fixed-size button sharing the label's row — normally hidden,
        # only shown (and only then taking up room, via the wider margin
        # _set_hovered reserves for it) while the tab is hovered.
        self.close_btn = TabCloseButton(self)
        self.close_btn.setToolTip(t("tab_close_tooltip"))
        self.close_btn.clicked.connect(lambda: self._on_close(self.tab))
        self.close_btn.setVisible(False)

        self.refresh()
        self._position_close_btn()

    def refresh(self):
        path = self.tab.project_path
        if path:
            name = os.path.basename(path)
        else:
            name = t("untitled")
            
        if self.tab.dirty:
            # Escape HTML characters in name so the bold tag works correctly without breaking formatting
            safe_name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            self.label.setText(f"{safe_name}&nbsp;<span style='font-size: 11pt; font-weight: 800;'>*</span>")
        else:
            # When not dirty, keep it plain to avoid parsing issues
            self.label.setText(name)
            
        self.setToolTip(path or t("untitled"))

    def set_active(self, active: bool):
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def enterEvent(self, event):
        self._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_hovered(False)
        super().leaveEvent(event)

    def _set_hovered(self, hovered: bool):
        if hovered and self._dragging:
            # A tab being dragged never shows its close button — the cursor
            # is glued to the tab so hover would otherwise be permanently on,
            # and a close target under a moving tab invites misclicks.
            return
        if self._hovered == hovered:
            return
        self._hovered = hovered
        # The extra width is exactly the close button's own footprint, and
        # the layout's right margin grows by the same amount — so the label
        # keeps the width/position it already had, and the widget simply
        # grows into a new strip on the right where the button now sits.
        extra = TAB_HEIGHT if hovered else 0
        self.setMinimumWidth(TAB_MIN_WIDTH + extra)
        self.setMaximumWidth(TAB_MAX_WIDTH + extra)
        self._layout.setContentsMargins(10, 0, 4 + extra, 0)
        self.close_btn.setVisible(hovered)
        self._position_close_btn()
        self.update()

    def _position_close_btn(self):
        # Square, full tab height, flush with the right edge — not part of
        # the internal QHBoxLayout (see __init__), so its geometry is set
        # here directly instead of via layout margins/spacing.
        self.close_btn.setGeometry(self.width() - TAB_HEIGHT, 0, TAB_HEIGHT, TAB_HEIGHT)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_close_btn()

    def paintEvent(self, event):
        # Overriding paintEvent bypasses Qt's automatic stylesheet painting,
        # so the QSS background gradient (TAB_BUTTON_QSS, untouched by the
        # outline below) has to be re-applied explicitly first, exactly the
        # way Qt would have painted it on its own.
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, painter, self)

        # The outline covers the tab *body* only: while hovered, the last
        # TAB_HEIGHT px belong to the close button, which paints its own
        # complete mini-tab chrome (face + outline) over that strip — so
        # the body's right edge line lands at the seam between the two.
        active = self.property("active") == "true"
        body_w = self.width() - (TAB_HEIGHT if self._hovered else 0)
        _paint_tab_outline(painter, body_w, self.height(), active)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
            self._dragging = False
            # Chrome-style: a tab activates on press, not on release — so
            # pressing-and-holding to start a drag still shows this as the
            # active tab immediately, instead of leaving whatever was active
            # before showing until the drag ends (or never, if it turns into
            # a genuine drag rather than a plain click).
            self._on_select(self.tab)
        elif event.button() == Qt.MiddleButton:
            self._on_close(self.tab)
        elif event.button() == Qt.RightButton:
            self._on_select(self.tab)
            self._on_context_menu(self, event.globalPos())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is not None and event.buttons() & Qt.LeftButton:
            if not self._dragging:
                moved = (event.pos() - self._press_pos).manhattanLength()
                if moved > QApplication.startDragDistance():
                    # Order matters: retract the close button while
                    # _dragging is still False (_set_hovered refuses hover
                    # changes mid-drag), THEN flip the flag that keeps it
                    # retracted for the rest of the drag.
                    self._set_hovered(False)
                    self._dragging = True
                    self._on_drag("start", self, event.globalPos())
            if self._dragging:
                self._on_drag("move", self, event.globalPos())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            was_dragging = self._dragging
            if self._dragging:
                self._on_drag("end", self, event.globalPos())
            self._press_pos = None
            self._dragging = False
            if was_dragging:
                # The cursor usually ends the drag still over this tab, but
                # no enterEvent will fire (it never left) — re-derive hover
                # from where the cursor actually is.
                self._set_hovered(self.underMouse())
        super().mouseReleaseEvent(event)


class TabStripWidget(QWidget):
    def __init__(self, on_select: Callable, on_close: Callable, on_new: Callable,
                 on_reorder: Callable, on_close_others: Callable,
                 on_close_to_right: Callable, on_close_to_left: Callable,
                 on_reopen_closed: Callable, on_duplicate: Callable,
                 on_open: Callable, on_save: Callable, on_save_as: Callable,
                 on_export: Callable, on_import: Callable, parent=None):
        super().__init__(parent)
        self.setObjectName("TabStripWidget")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(TAB_STRIP_QSS)
        self._on_select = on_select
        self._on_close = on_close
        self._on_new = on_new
        self._on_reorder = on_reorder
        self._on_close_others = on_close_others
        self._on_close_to_right = on_close_to_right
        self._on_close_to_left = on_close_to_left
        self._on_reopen_closed = on_reopen_closed
        self._on_duplicate = on_duplicate
        self._on_open = on_open
        self._on_save = on_save
        self._on_save_as = on_save_as
        self._on_export = on_export
        self._on_import = on_import
        self._buttons: List[TabButton] = []
        self._dragging_btn: Optional[TabButton] = None
        self._drag_press_local_x = 0
        self._drag_target_index = 0
        self._drag_others_order: List[TabButton] = []
        self._drag_base_slot_x: List[int] = []
        self._slot_animations: dict = {}

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 0, 4, 0)
        self._layout.setSpacing(2)

        # Hamburger menu (project-wide Open/Save/Save As — everything the
        # Start node's buttons used to carry except Launch, which stays on
        # the node itself) sits leftmost, then new-tab, then the tabs.
        self.menu_btn = TitleBarButton("menu", self._show_project_menu, t("titlebar_menu_tooltip"), parent=self)
        self._layout.addWidget(self.menu_btn)

        self.new_btn = TitleBarButton("new_tab", lambda: on_new(), t("tab_new_tooltip"), parent=self)
        # Sits left of every tab (index 1, right after the hamburger) —
        # rebuild() inserts tab buttons starting at index 2, right after it.
        self._layout.addWidget(self.new_btn)
        self._layout.addStretch(1)

    def _show_project_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(TITLE_BAR_MENU_STYLESHEET)
        _add_action_with_hint(menu, t("tab_menu_new"), HOTKEY_HINTS["new_tab_alt"], self._on_new)
        _add_action_with_hint(menu, t("btn_open"), HOTKEY_HINTS["open"], self._on_open)
        _add_action_with_hint(menu, t("btn_save"), HOTKEY_HINTS["save"], self._on_save)
        _add_action_with_hint(menu, t("btn_save_as"), HOTKEY_HINTS["save_as"], self._on_save_as)
        menu.addSeparator()
        _add_action_with_hint(menu, t("menu_export"), None, self._on_export)
        _add_action_with_hint(menu, t("menu_import"), None, self._on_import)
        menu.exec_(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft()))
        self._resettle_hover(self.menu_btn)

    @staticmethod
    def _resettle_hover(btn: "TitleBarButton") -> None:
        """QMenu.exec_() blocks in its own nested event loop; the cursor
        leaves the launching button for the popup (and then wherever the
        user clicks to dismiss it) without Qt ever delivering it a real
        leaveEvent, so the QSS :hover pseudo-state is left stuck painted
        "on" once exec_() returns. Recomputing WA_UnderMouse from the actual
        cursor position and re-polishing — the same idiom TabButton.set_active
        already uses after changing a QSS-relevant property — is more robust
        than hoping a synthetic event unsticks Qt's own bookkeeping.
        """
        under_mouse = btn.rect().contains(btn.mapFromGlobal(QCursor.pos()))
        btn.setAttribute(Qt.WA_UnderMouse, under_mouse)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()

    # ── Drag-to-reorder — the dragged tab visually follows the cursor
    # (Chrome-style) while every other tab slides to open a gap at the spot
    # it would land in, instead of just teleporting on a live index swap ────

    def _handle_drag(self, action: str, btn: TabButton, global_pos) -> None:
        if action == "start":
            self._start_drag(btn, global_pos)
        elif action == "move":
            self._update_drag(btn, global_pos)
        else:
            self._end_drag(btn, global_pos)

    def _start_drag(self, btn: TabButton, global_pos) -> None:
        self._dragging_btn = btn
        self._drag_press_local_x = self.mapFromGlobal(global_pos).x() - btn.x()
        self._drag_target_index = self._buttons.index(btn)
        # The other tabs' relative order never changes for the rest of this
        # drag — only where the floating tab would land among them does — so
        # capture that fixed order and each one's own "no gap" compacted x
        # once, up front, as the stable reference the whole drag measures
        # against (see _update_drag). Reading it back off the layout
        # mid-drag instead would be reading positions we're mid-animation
        # into (see _slide_others_to_open_gap_at), not the stable slots.
        self._drag_others_order = [b for b in self._buttons if b is not btn]
        self._layout.removeWidget(btn)
        self._layout.activate()  # force the compaction above to apply now, synchronously
        self._drag_base_slot_x = [b.x() for b in self._drag_others_order]
        btn.raise_()

    def _update_drag(self, btn: TabButton, global_pos) -> None:
        if self._dragging_btn is not btn:
            return
        local_x = self.mapFromGlobal(global_pos).x() - self._drag_press_local_x
        # new_btn sits fixed at the left of every tab, so it's the left
        # bound here; there's nothing fixed on the right (just stretch), so
        # the right bound is simply the strip's own edge — this is also why
        # tabs no longer visually collide when dragged all the way right:
        # previously new_btn sat there instead, a fixed-width obstacle the
        # clamp math didn't leave enough room in front of.
        min_x = self.new_btn.geometry().right() + self._layout.spacing() + 1
        max_x = max(min_x, self.width() - btn.width())
        local_x = max(min_x, min(local_x, max_x))
        btn.move(local_x, btn.y())

        # Pinned at the left edge should always mean "slot 0", but the
        # center-crossing test below can't actually reach that: the first
        # other tab sits almost exactly where the dragged one is clamped to
        # (both right after new_btn), so with similar-width tabs neither
        # center ever crosses the other. Rather than chase that geometry,
        # just special-case the pinned position directly.
        if local_x <= min_x:
            target_index = 0
        else:
            target_index = self._target_index_for(btn, local_x)
        if target_index != self._drag_target_index:
            old_index = self._drag_target_index
            self._drag_target_index = target_index
            self._slide_others_to_open_gap_at(btn, target_index, old_index)

    def _end_drag(self, btn: TabButton, global_pos) -> None:
        if self._dragging_btn is not btn:
            return
        self._dragging_btn = None
        for anim in self._slot_animations.values():
            anim.stop()
        self._slot_animations.clear()
        # rebuild() (triggered by the reorder callback re-touching the
        # window's tab model) puts every TabButton back under layout
        # management with correct geometry, so no manual cleanup needed here
        # even though every other tab is currently sitting at an animated,
        # off-layout position.
        self._on_reorder(btn.tab, self._drag_target_index)

    def _target_index_for(self, dragged_btn: TabButton, local_x: int) -> int:
        """Which slot among the (fixed-order) other tabs the dragged one's
        current position now overlaps, measured against their stable base
        positions from _start_drag — not their current (possibly mid-slide)
        on-screen ones, which would make this chase its own tail."""
        center_x = local_x + dragged_btn.width() / 2
        for i, (other, base_x) in enumerate(zip(self._drag_others_order, self._drag_base_slot_x)):
            if center_x < base_x + other.width() / 2:
                return i
        return len(self._drag_others_order)

    def _slide_others_to_open_gap_at(self, dragged_btn: TabButton, target_index: int,
                                      old_index: Optional[int] = None) -> None:
        """Animate every other tab into the slot it should sit in for the
        dragged tab to have a gap open at ``target_index`` — the tabs before
        the gap stay put, the ones from the gap onward slide over by the
        dragged tab's own footprint to make room.

        Only the tabs between ``old_index`` and ``target_index`` actually
        change which side of the gap they're on — everyone else's offset is
        provably the same as before, so restarting their QPropertyAnimation
        too (on every single index crossing during the drag) was pure churn
        on a tab strip with many open tabs."""
        gap = dragged_btn.width() + self._layout.spacing()
        if old_index is None:
            indices = range(len(self._drag_others_order))
        else:
            lo, hi = sorted((old_index, target_index))
            indices = range(lo, hi)
        for i in indices:
            other = self._drag_others_order[i]
            base_x = self._drag_base_slot_x[i]
            target_x = base_x + (gap if i >= target_index else 0)
            self._animate_to(other, target_x)

    def _animate_to(self, widget: QWidget, target_x: int) -> None:
        anim = self._slot_animations.get(widget)
        if anim is None:
            anim = QPropertyAnimation(widget, b"pos", self)
            self._slot_animations[widget] = anim
        anim.stop()
        anim.setDuration(TAB_SLIDE_ANIM_MS)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(widget.pos())
        anim.setEndValue(QPoint(target_x, widget.y()))
        anim.start()

    # ── Tab context menu ─────────────────────────────────────────────────────

    def _show_context_menu(self, btn: TabButton, global_pos) -> None:
        tab = btn.tab
        menu = QMenu(self)
        menu.setStyleSheet(TITLE_BAR_MENU_STYLESHEET)
        _add_action_with_hint(menu, t("tab_menu_duplicate"), HOTKEY_HINTS.get("duplicate_tab"), lambda: self._on_duplicate(tab))
        menu.addSeparator()
        _add_action_with_hint(menu, t("tab_menu_close"), HOTKEY_HINTS["close_tab"], lambda: self._on_close(tab))
        close_others = _add_action_with_hint(menu, t("tab_menu_close_others"), HOTKEY_HINTS.get("close_others"), lambda: self._on_close_others(tab))
        close_others.setEnabled(len(self._buttons) > 1)
        close_right = _add_action_with_hint(menu, t("tab_menu_close_to_right"), HOTKEY_HINTS.get("close_right"), lambda: self._on_close_to_right(tab))
        close_right.setEnabled(btn is not self._buttons[-1])
        close_left = _add_action_with_hint(menu, t("tab_menu_close_to_left"), HOTKEY_HINTS.get("close_left"), lambda: self._on_close_to_left(tab))
        close_left.setEnabled(btn is not self._buttons[0])
        menu.addSeparator()
        _add_action_with_hint(menu, t("tab_menu_reopen_closed"), HOTKEY_HINTS["reopen_closed_tab"], self._on_reopen_closed)
        # Anchored like the hamburger's own menu — at a fixed landmark's
        # bottom-left corner, not the cursor — but the one fixed landmark a
        # tab strip has is the active tab, not whichever one was
        # right-clicked (btn), so the menu always opens in the same place
        # regardless of which tab it's acting on.
        active_btn = next((b for b in self._buttons if b.property("active") == "true"), btn)
        menu.exec_(active_btn.mapToGlobal(active_btn.rect().bottomLeft()))

    def rebuild(self, tabs: list, active_tab):
        for btn in self._buttons:
            self._layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons = []
        for i, tab in enumerate(tabs):
            btn = TabButton(tab, self._on_select, self._on_close,
                             self._handle_drag, self._show_context_menu, parent=self)
            btn.set_active(tab is active_tab)
            self._layout.insertWidget(i + 2, btn)  # menu_btn=0, new_btn=1
            self._buttons.append(btn)

    def refresh_active(self, active_tab):
        for btn in self._buttons:
            btn.set_active(btn.tab is active_tab)

    def refresh_tab(self, tab):
        for btn in self._buttons:
            if btn.tab is tab:
                btn.refresh()
                return


class TitleBarButton(QToolButton):
    """Custom painted window control button (minimize, maximize, close, plus
    the new-tab "+" and hamburger "≡") to ensure visual consistency.

    Why: Unicode text glyphs render with inconsistent sizes, positions, and stroke weights
    on different platforms/fonts. Custom painting gives us pixel-perfect, identical results.
    Reusing this same class (and its fixed TITLE_BAR_BTN_WIDTH × TITLE_BAR_HEIGHT footprint)
    for "new_tab"/"menu" — rather than a separate smaller QToolButton with a plain text glyph
    — is what makes them land the same size and weight as min/max/close instead of looking
    like an afterthought next to them.
    """
    def __init__(self, role: str, callback: Callable, tooltip: str, parent=None):
        super().__init__(parent)
        self.role = role  # "min", "max", "close", "new_tab", "menu"
        self.setObjectName("titleBarCloseBtn" if role == "close" else "titleBarWinBtn")
        self.setFixedSize(TITLE_BAR_BTN_WIDTH, TITLE_BAR_HEIGHT)
        self.setToolTip(tooltip)
        self.clicked.connect(callback)

    def paintEvent(self, event):
        # Why: QToolButton's paintEvent draws the QSS hover and pressed background state
        # on the button, which we want to keep. We suppress text drawing by leaving the
        # button's text blank, and then draw our own crisp foreground icons.
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        color = self.palette().color(QPalette.ButtonText)
        pen = QPen(color, 1.0)
        painter.setPen(pen)

        w, h = self.width(), self.height()
        cx, cy = w // 2, h // 2

        if self.role == "min":
            # A centered dash ("—"), not a low underscore-like line — Windows'
            # own minimize glyph sits near the bottom edge, but that reads as
            # a stray underscore at this size; vertically centered reads as
            # a clear, deliberate dash instead.
            painter.drawLine(cx - 5, cy, cx + 5, cy)
        elif self.role == "new_tab":
            # Plus sign, same 1px line weight as min/max/close.
            painter.drawLine(cx - 6, cy, cx + 6, cy)
            painter.drawLine(cx, cy - 6, cx, cy + 6)
        elif self.role == "menu":
            # Hamburger — three 1px horizontal lines.
            for dy in (-5, 0, 5):
                painter.drawLine(cx - 7, cy + dy, cx + 7, cy + dy)
        elif self.role == "max":
            is_maximized = False
            if self.parent() and hasattr(self.parent(), "_window"):
                is_maximized = self.parent()._window.isMaximized()

            if is_maximized:
                # Restore: two overlapping 8x8 squares
                fg_x = cx - 5
                fg_y = cy - 2
                painter.drawRect(fg_x, fg_y, 7, 7)

                bg_x = fg_x + 2
                bg_y = fg_y - 2
                painter.drawLine(bg_x, bg_y, bg_x + 7, bg_y)
                painter.drawLine(bg_x + 7, bg_y, bg_x + 7, bg_y + 7)
                painter.drawLine(bg_x + 7, bg_y + 7, fg_x + 8, bg_y + 7)
                painter.drawLine(bg_x, bg_y, bg_x, fg_y - 1)
            else:
                # Maximize: single 10x10 square
                x = cx - 5
                y = cy - 5
                painter.drawRect(x, y, 9, 9)
        elif self.role == "close":
            # Diagonal cross (9x9 pixels)
            painter.drawLine(cx - 4, cy - 4, cx + 4, cy + 4)
            painter.drawLine(cx - 4, cy + 4, cx + 4, cy - 4)


class TitleBarWidget(QWidget):
    _EDGE_SNAP_MARGIN = 3  # px from a screen edge that counts as "dropped there"

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self._drag_start: Optional[object] = None
        self._press_ratio: float = 0.0  # click x, as a fraction of bar width, for un-maximize drag
        self._manual_drag_active: bool = False  # latched at press time, see mouseMoveEvent
        self._edge_snapped: bool = False  # True after a manual half-screen snap, see _snap_to_edge_if_dropped_there
        # Narrows _edge_snapped to specifically "snapped to the bottom half"
        # — the one snap this app halves the window's width for when it's
        # picked back up and dragged away (see _begin_drag_unsnapping_bottom).
        self._snapped_to_bottom: bool = False
        self._corner_radius: int = WINDOW_CORNER_RADIUS
        self.setObjectName("TitleBarWidget")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(TITLE_BAR_QSS)
        self.setFixedHeight(TITLE_BAR_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tab_strip = TabStripWidget(
            on_select=window.switch_to_tab,
            on_close=window.close_tab,
            on_new=lambda: window.new_tab(),
            on_reorder=window.reorder_tab,
            on_close_others=window.close_other_tabs,
            on_close_to_right=window.close_tabs_to_the_right,
            on_close_to_left=window.close_tabs_to_the_left,
            on_reopen_closed=window.reopen_closed_tab,
            on_duplicate=window.duplicate_tab,
            on_open=window.load_project,
            on_save=window.save_project,
            on_save_as=lambda: window.save_project(save_as=True),
            on_export=window.export_chain_script,
            on_import=window.import_chain_script,
            parent=self,
        )
        layout.addWidget(self.tab_strip, 1)

        self.min_btn = TitleBarButton("min", window.showMinimized, t("titlebar_minimize_tooltip"), parent=self)
        self.max_btn = TitleBarButton("max", self._toggle_maximize, t("titlebar_maximize_tooltip"), parent=self)
        self.close_btn = TitleBarButton("close", window.close, t("titlebar_close_tooltip"), parent=self)
        layout.addWidget(self.min_btn)
        layout.addWidget(self.max_btn)
        layout.addWidget(self.close_btn)

    def set_corner_radius(self, radius: int) -> None:
        """Round (or square, radius=0) the title bar's top corners — see
        NodeEditorWindow._update_window_rounding. Masks the whole widget
        rather than styling it via QSS border-radius: that only rounds this
        widget's OWN background paint, not the tab strip / min / max / close
        buttons sitting flush in its corners, which kept painting their own
        square corners over the rounded background (visible as a mismatched
        notch wherever a child widget's own paint didn't happen to cover that
        exact spot). A mask clips every child the same way for free."""
        self._corner_radius = radius
        self._apply_corner_mask()

    def _apply_corner_mask(self) -> None:
        radius = self._corner_radius
        if radius <= 0:
            self.clearMask()
            return
        # Only the top corners should round — the title bar's bottom edge is
        # an interior seam (it meets the rest of the window), not an outer
        # corner. Building the rounded rect taller than the widget and
        # intersecting with the widget's real bounds pushes the bottom two
        # corners' rounding below y=height(), leaving that edge straight. The
        # extra height must clear the bottom radius by more than the radius
        # itself — extending by exactly `radius` leaves the bottom corners'
        # curve starting exactly at y=height(), still visibly rounding in
        # that "straight" edge; doubling it keeps the curve well clear.
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height() + radius * 2), radius, radius)
        region = QRegion(path.toFillPolygon().toPolygon())
        region &= QRegion(0, 0, self.width(), self.height())
        self.setMask(region)

    def resizeEvent(self, event):
        self._apply_corner_mask()
        super().resizeEvent(event)

    def _maximize(self) -> None:
        """Enter maximized state — shared by the maximize button/double-click
        and drag-to-top-edge snap. remember_normal_geometry() must run before
        showMaximized() (see NodeEditorWindow.remember_normal_geometry); a
        manual edge-snap flag, if any, no longer applies once really maximized."""
        self._window.remember_normal_geometry()
        self._window.showMaximized()
        self._edge_snapped = False
        self._snapped_to_bottom = False

    def _toggle_maximize(self):
        if self._window.isMaximized():
            self._window.showNormal()
            self.max_btn.setToolTip(t("titlebar_maximize_tooltip"))
            self._edge_snapped = False
            self._snapped_to_bottom = False
        else:
            self._maximize()
            self.max_btn.setToolTip(t("titlebar_restore_tooltip"))
        self.max_btn.update()

    def set_max_button_native_hover(self, hovered: bool) -> None:
        """Keep the maximize button's :hover paint in sync while Windows is
        treating its rect as non-client (HTMAXBUTTON — see
        NodeEditorWindow._hit_test_native_message) and therefore not
        delivering it ordinary mouse-move/enter/leave events at all.
        [nativeHover] mirrors the existing [nodeHover] convention (theme.py):
        a second, explicit trigger for the same QSS :hover look, for a
        widget whose real mouse events aren't reliable for it.
        """
        new_value = "true" if hovered else "false"
        if self.max_btn.property("nativeHover") == new_value:
            return
        self.max_btn.setProperty("nativeHover", new_value)
        self.max_btn.style().unpolish(self.max_btn)
        self.max_btn.style().polish(self.max_btn)
        self.max_btn.update()

    def is_drag_region(self, pos) -> bool:
        """True if ``pos`` (in this widget's local coordinates) is empty
        chrome — not a tab, the '+' button, or a window-control button.
        Used both for our own drag/double-click fallback and, on Windows,
        by NodeEditorWindow.nativeEvent's WM_NCHITTEST handler."""
        child = self.childAt(pos)
        return child is None or child is self.tab_strip

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_drag_region(event.pos()):
            self._toggle_maximize()
        super().mouseDoubleClickEvent(event)

    # Windows relies on WM_NCHITTEST (see NodeEditorWindow.nativeEvent) for
    # drag-to-move when NOT maximized, which also restores native edge-snap —
    # these handlers stay out of the way for that case. But a frameless
    # window never gets the real Win32 WS_MAXIMIZE style, so Windows' own
    # "drag the caption to restore-and-follow-the-cursor" behavior never
    # fires while maximized; nativeEvent deliberately returns None then so
    # these handlers can restore the window and drag it manually instead —
    # the same manual path used unconditionally on non-Windows platforms.
    def _native_drag_handles_this(self) -> bool:
        return sys.platform == "win32" and not self._window.isMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton and self.is_drag_region(event.pos()):
            show_system_menu(self._window, event.globalPos())
            event.accept()
            return
        # A manual half-screen snap (see _snap_to_edge_if_dropped_there) is a
        # plain setGeometry(), not a real maximize — isMaximized() stays
        # False, so a fresh press here goes through the *native* drag path
        # below, not the maximized-restore branch in mouseMoveEvent. Round
        # the corners back here, unconditionally, so picking the window back
        # up to move it looks right regardless of which path ends up driving
        # the actual drag.
        if event.button() == Qt.LeftButton and self._edge_snapped and self.is_drag_region(event.pos()):
            if self._snapped_to_bottom:
                self._begin_drag_unsnapping_bottom(event.globalPos())
            else:
                self._clear_edge_snap()
        if self._native_drag_handles_this():
            super().mousePressEvent(event)
            return
        if event.button() == Qt.LeftButton and self.is_drag_region(event.pos()):
            self._drag_start = event.globalPos() - self._window.frameGeometry().topLeft()
            self._press_ratio = event.pos().x() / max(1, self.width())
            # Latched for the whole gesture: mouseMoveEvent must keep driving
            # this drag manually even after restoring from maximized flips
            # _native_drag_handles_this() back to True mid-drag. Windows never
            # actually took over (no real WM_NCLBUTTONDOWN caption-drag ever
            # started — this is a synthetic, Qt-tracked left-button-held
            # sequence), so re-checking the live value on every move event
            # was silently dropping all position updates the instant the
            # window became un-maximized, freezing it until the next click.
            self._manual_drag_active = True
            event.accept()
        else:
            self._drag_start = None
            self._manual_drag_active = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._manual_drag_active and self._drag_start is not None
                and event.buttons() & Qt.LeftButton):
            if self._window.isMaximized():
                # Diagnostic logging (see handoff_to_native_caption_drag)
                # showed Qt's own normalGeometry() getting corrupted after
                # repeated maximize/restore cycles on this frameless window —
                # it starts returning a near-fullscreen rect instead of the
                # real pre-maximize size, and showNormal() below isn't
                # guaranteed to have finished resizing the native HWND to
                # match by the time we'd read it back either. Use our own
                # snapshot (taken proactively before showMaximized() was ever
                # called — see remember_normal_geometry()) instead of trusting
                # either of those, and force it with setGeometry() right
                # after restoring rather than hoping showNormal() got there.
                target_geo = self._window.normal_geometry_for_restore()
                # Restore first so the window can actually move, then keep
                # the cursor at roughly the same relative spot in the bar
                # it grabbed, instead of snapping the window's corner to it.
                # restore_without_animation (not showNormal() directly) skips
                # Windows' animated restore transition, which otherwise owns
                # the window position for its duration and makes our move()
                # calls below get dropped for that transition's few frames.
                restore_without_animation(self._window)
                self._window.setGeometry(target_geo)
                self.max_btn.setToolTip(t("titlebar_maximize_tooltip"))
                self.max_btn.update()
                offset_x = int(self._press_ratio * target_geo.width())
                self._drag_start = QPoint(offset_x, event.pos().y())
                self._window.move(event.globalPos() - self._drag_start)
                # Hands the rest of this drag off to Windows' own caption-move
                # loop (see handoff_to_native_caption_drag) so Aero edge-snap
                # and its preview guides work for it. Blocks until mouse-up,
                # so by the time it returns the drag (and any native snap) is
                # already done.
                if handoff_to_native_caption_drag(self._window):
                    # Native Aero Snap can flush the window against screen
                    # edges (half-screen snap, Windows 11 quarter-snap, etc.)
                    # without ever raising WindowStateChange or going through
                    # _snap_to_edge_if_dropped_there — neither of which
                    # _update_window_rounding reacts to, so the corners stay
                    # rounded (visibly, at the title bar's top edge) even
                    # though the window is now flush. Check the actual
                    # resulting geometry once the native drag loop returns.
                    self._refresh_corner_rounding_after_native_drag()
                    self._manual_drag_active = False
                    self._drag_start = None
                    event.accept()
                    return
            else:
                self._window.move(event.globalPos() - self._drag_start)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # Only reached if the native handoff above wasn't taken (non-Windows,
        # or the handoff call failed) — in that case Windows never got a
        # chance to snap this drag itself, so do it ourselves from the
        # cursor's final drop position.
        if self._manual_drag_active and self._drag_start is not None:
            self._snap_to_edge_if_dropped_there(event.globalPos())
        self._drag_start = None
        self._manual_drag_active = False
        super().mouseReleaseEvent(event)

    def _refresh_corner_rounding_after_native_drag(self) -> None:
        if self._window.isMaximized():
            return  # changeEvent already squared these via _update_window_rounding
        window_handle = self._window.windowHandle()
        screen = window_handle.screen() if window_handle else None
        if screen is None:
            screen = QApplication.screenAt(self._window.frameGeometry().center())
        if screen is None:
            return
        geo = screen.availableGeometry()
        win = self._window.frameGeometry()
        m = self._EDGE_SNAP_MARGIN
        touching_edges = sum((
            abs(win.left() - geo.left()) <= m,
            abs(win.right() - geo.right()) <= m,
            abs(win.top() - geo.top()) <= m,
            abs(win.bottom() - geo.bottom()) <= m,
        ))

        def _matches_snap_size(actual: int, full: int) -> bool:
            # Windows' own half/quarter/full snap layouts always size a window
            # to exactly full, half, or the complementary half of the
            # available dimension. A window that just happens to be parked in
            # a corner (any arbitrary size) won't match any of these.
            half = full // 2
            return abs(actual - full) <= m or abs(actual - half) <= m or abs(actual - (full - half)) <= m

        size_matches = (_matches_snap_size(win.width(), geo.width())
                         or _matches_snap_size(win.height(), geo.height()))
        # A half/quarter-snapped window is always flush against at least two
        # screen edges at once (e.g. left half touches left+top+bottom); a
        # small window that merely landed near a corner by coincidence isn't
        # snapped even if it also happens to touch two edges.
        snapped = touching_edges >= 2 and size_matches
        self._window.set_corners_square(snapped)
        self._edge_snapped = snapped
        self._snapped_to_bottom = False  # a native Aero snap is never this app's own bottom-half zone

    def _snap_to_edge_if_dropped_there(self, global_pos: QPoint) -> None:
        """Used after a *manual* drag (mouseReleaseEvent — non-Windows, or
        the native handoff wasn't taken): nothing here was ever snapped
        natively, so every zone (top/left/right/bottom) is this method's
        to check. A completed *native* caption drag is different — Aero
        Snap already handled top/left/right itself before WM_EXITSIZEMOVE
        even fired — so NodeEditorWindow.nativeEvent calls
        _snap_to_bottom_if_dropped_there directly for that case instead of
        this whole method, or a top/left/right drop would double-apply on
        top of what Windows already did.
        """
        screen = QApplication.screenAt(global_pos)
        if screen is None:
            return
        geo = screen.availableGeometry()
        m = self._EDGE_SNAP_MARGIN

        # Split as floor/remainder (not floor/floor) so the two halves always
        # tile the available width exactly — on an odd-width screen, using
        # geo.width() // 2 for both sides left a 1px gap between them.
        left_width = geo.width() // 2
        right_width = geo.width() - left_width

        if global_pos.y() <= geo.top() + m:
            self._maximize()
        elif global_pos.x() <= geo.left() + m:
            self._window.setGeometry(geo.left(), geo.top(), left_width, geo.height())
            self._window.set_corners_square(True)
            self._edge_snapped = True
            self._snapped_to_bottom = False
        elif global_pos.x() >= geo.right() - m:
            self._window.setGeometry(geo.left() + left_width, geo.top(), right_width, geo.height())
            self._window.set_corners_square(True)
            self._edge_snapped = True
            self._snapped_to_bottom = False
        else:
            self._snap_to_bottom_if_dropped_there(global_pos)

    def _snap_to_bottom_if_dropped_there(self, global_pos: QPoint) -> bool:
        """The one manual snap zone Windows' own Aero Snap has no native
        equivalent for — split out of _snap_to_edge_if_dropped_there so a
        *native* caption drag's completion (NodeEditorWindow.nativeEvent's
        WM_EXITSIZEMOVE) can offer just this zone, without re-running the
        top/left/right branches Aero Snap already applied natively for that
        drag. Returns whether it actually snapped.
        """
        screen = QApplication.screenAt(global_pos)
        if screen is None:
            return False
        geo = screen.availableGeometry()
        m = self._EDGE_SNAP_MARGIN
        if global_pos.y() < geo.bottom() - m:
            return False
        if global_pos.x() <= geo.left() + m or global_pos.x() >= geo.right() - m:
            return False  # a corner — left/right's own snap territory, not this zone's

        # Same floor/remainder split as left/right, applied vertically —
        # Windows itself has no native bottom-drop gesture, but dropping
        # here should be at least as useful as doing nothing; snapping to
        # the bottom half mirrors the left/right half-screen behavior.
        top_height = geo.height() // 2
        bottom_height = geo.height() - top_height
        self._window.setGeometry(geo.left(), geo.top() + top_height, geo.width(), bottom_height)
        self._window.set_corners_square(True)
        self._edge_snapped = True
        self._snapped_to_bottom = True
        return True

    def _clear_edge_snap(self) -> None:
        self._window.set_corners_square(False)
        self._edge_snapped = False
        self._snapped_to_bottom = False

    def _begin_drag_unsnapping_bottom(self, cursor_global_pos: QPoint) -> None:
        """Picking a bottom-snapped window back up to drag it away halves its
        width — the same spirit as Windows' own "restore a maximized window
        the instant you start dragging it" gesture, just for the one snap
        state that's entirely this app's own (Aero Snap has no bottom zone
        of its own to restore *from*, so Windows never does this for us).
        No-op if the window isn't currently bottom-snapped.
        """
        if not self._snapped_to_bottom:
            return
        old_geo = self._window.geometry()
        new_width = max(self._window.minimumWidth(), old_geo.width() // 2)
        # Keeps the cursor at the same relative X fraction of the window it
        # grabbed, instead of snapping the window's left edge under it.
        ratio = (cursor_global_pos.x() - old_geo.left()) / max(1, old_geo.width())
        new_left = cursor_global_pos.x() - int(ratio * new_width)
        self._clear_edge_snap()
        self._window.setGeometry(new_left, old_geo.top(), new_width, old_geo.height())
