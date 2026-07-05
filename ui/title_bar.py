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

from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QWidget
from PyQt5.QtCore import QPoint, Qt

from localization import t
from configuration import (
    TITLE_BAR_HEIGHT, TITLE_BAR_BTN_WIDTH,
    TAB_HEIGHT, TAB_MIN_WIDTH, TAB_MAX_WIDTH, TAB_CLOSE_BTN_SIZE, TAB_NEW_BTN_WIDTH,
)
from ui.theme import TITLE_BAR_QSS, TAB_STRIP_QSS, TAB_BUTTON_QSS


class TabButton(QWidget):
    """One open project: title label + close 'x'. Click switches to it,
    the 'x' or a middle-click closes it. Dragging it sideways past a
    neighboring tab reorders them live."""

    def __init__(self, tab, on_select: Callable, on_close: Callable,
                 on_reorder: Callable, parent=None):
        super().__init__(parent)
        self.tab = tab
        self._on_select = on_select
        self._on_close = on_close
        self._on_reorder = on_reorder
        self._press_pos: Optional[object] = None
        self._dragging = False
        self.setObjectName("TabButton")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(TAB_BUTTON_QSS)
        self.setFixedHeight(TAB_HEIGHT)
        self.setMinimumWidth(TAB_MIN_WIDTH)
        self.setMaximumWidth(TAB_MAX_WIDTH)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 4, 0)
        layout.setSpacing(4)

        self.label = QLabel()
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.label)

        self.close_btn = QToolButton()
        self.close_btn.setText("×")
        self.close_btn.setFixedSize(TAB_CLOSE_BTN_SIZE, TAB_CLOSE_BTN_SIZE)
        self.close_btn.setToolTip(t("tab_close_tooltip"))
        self.close_btn.clicked.connect(lambda: self._on_close(self.tab))
        layout.addWidget(self.close_btn)

        self.refresh()

    def refresh(self):
        path = self.tab.project_path
        if path:
            name = os.path.basename(path)
        elif self.tab.untitled_number:
            name = f"{t('untitled')} {self.tab.untitled_number}"
        else:
            name = t("untitled")
        self.label.setText(f"{name}{'*' if self.tab.dirty else ''}")
        self.setToolTip(path or t("untitled"))

    def set_active(self, active: bool):
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
            self._dragging = False
        elif event.button() == Qt.MiddleButton:
            self._on_close(self.tab)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is not None and event.buttons() & Qt.LeftButton:
            moved = (event.pos() - self._press_pos).manhattanLength()
            if moved > QApplication.startDragDistance():
                self._dragging = True
                self._on_reorder(self, event.globalPos())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if not self._dragging:
                self._on_select(self.tab)
            self._press_pos = None
            self._dragging = False
        super().mouseReleaseEvent(event)


class TabStripWidget(QWidget):
    def __init__(self, on_select: Callable, on_close: Callable, on_new: Callable,
                 on_reorder: Callable, parent=None):
        super().__init__(parent)
        self.setObjectName("TabStripWidget")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(TAB_STRIP_QSS)
        self._on_select = on_select
        self._on_close = on_close
        self._on_reorder = on_reorder
        self._buttons: List[TabButton] = []

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 0, 4, 0)
        self._layout.setSpacing(2)

        self.new_btn = QToolButton()
        self.new_btn.setObjectName("tabNewBtn")
        self.new_btn.setText("+")
        self.new_btn.setFixedSize(TAB_NEW_BTN_WIDTH, TAB_HEIGHT)
        self.new_btn.setToolTip(t("tab_new_tooltip"))
        self.new_btn.clicked.connect(lambda: on_new())
        self._layout.addWidget(self.new_btn)
        self._layout.addStretch(1)

    def _handle_drag(self, dragged_btn: TabButton, global_pos):
        """Live-swap the dragged tab with whichever neighbor it's now
        dragged past — a simple, floating-preview-free reorder."""
        local_x = self.mapFromGlobal(global_pos).x()
        current_index = self._buttons.index(dragged_btn)
        target_index = len(self._buttons) - 1
        for i, btn in enumerate(self._buttons):
            if local_x < btn.geometry().center().x():
                target_index = i
                break
        if target_index == current_index:
            return
        self._on_reorder(dragged_btn.tab, target_index)

    def rebuild(self, tabs: list, active_tab):
        for btn in self._buttons:
            self._layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons = []
        for i, tab in enumerate(tabs):
            btn = TabButton(tab, self._on_select, self._on_close, self._handle_drag, parent=self)
            btn.set_active(tab is active_tab)
            self._layout.insertWidget(i, btn)
            self._buttons.append(btn)

    def refresh_active(self, active_tab):
        for btn in self._buttons:
            btn.set_active(btn.tab is active_tab)

    def refresh_tab(self, tab):
        for btn in self._buttons:
            if btn.tab is tab:
                btn.refresh()
                return


class TitleBarWidget(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self._drag_start: Optional[object] = None
        self._press_ratio: float = 0.0  # click x, as a fraction of bar width, for un-maximize drag
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
            parent=self,
        )
        layout.addWidget(self.tab_strip, 1)

        self.min_btn = self._make_win_btn("–", window.showMinimized, t("titlebar_minimize_tooltip"))
        self.max_btn = self._make_win_btn("□", self._toggle_maximize, t("titlebar_maximize_tooltip"))
        self.close_btn = self._make_win_btn("✕", window.close, t("titlebar_close_tooltip"), close=True)
        layout.addWidget(self.min_btn)
        layout.addWidget(self.max_btn)
        layout.addWidget(self.close_btn)

    def _make_win_btn(self, glyph: str, callback: Callable, tooltip: str, *, close: bool = False) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName("titleBarCloseBtn" if close else "titleBarWinBtn")
        btn.setText(glyph)
        btn.setFixedSize(TITLE_BAR_BTN_WIDTH, TITLE_BAR_HEIGHT)
        btn.setToolTip(tooltip)
        btn.clicked.connect(callback)
        return btn

    def _toggle_maximize(self):
        if self._window.isMaximized():
            self._window.showNormal()
            self.max_btn.setText("□")
            self.max_btn.setToolTip(t("titlebar_maximize_tooltip"))
        else:
            self._window.showMaximized()
            self.max_btn.setText("❐")
            self.max_btn.setToolTip(t("titlebar_restore_tooltip"))

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
        if self._native_drag_handles_this():
            super().mousePressEvent(event)
            return
        if event.button() == Qt.LeftButton and self.is_drag_region(event.pos()):
            self._drag_start = event.globalPos() - self._window.frameGeometry().topLeft()
            self._press_ratio = event.pos().x() / max(1, self.width())
            event.accept()
        else:
            self._drag_start = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (not self._native_drag_handles_this() and self._drag_start is not None
                and event.buttons() & Qt.LeftButton):
            if self._window.isMaximized():
                # Restore first so the window can actually move, then keep
                # the cursor at roughly the same relative spot in the bar
                # it grabbed, instead of snapping the window's corner to it.
                self._window.showNormal()
                self.max_btn.setText("□")
                self.max_btn.setToolTip(t("titlebar_maximize_tooltip"))
                offset_x = int(self._press_ratio * self._window.width())
                self._drag_start = QPoint(offset_x, event.pos().y())
            self._window.move(event.globalPos() - self._drag_start)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        super().mouseReleaseEvent(event)
