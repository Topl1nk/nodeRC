"""frameless_dialog.py — Shared Chrome for Secondary Modals

Every secondary window in the app (message boxes, the session-restore
prompt) shares this same frameless, dark-themed chrome instead of falling
back to the native OS dialog style — so the whole app reads as one
consistent family of windows, not a mix of custom and native ones.

Styled as the same primitive a graph node uses — a colored header band over
a body, square (non-rounded) corners, NODE_BORDER_COLOR outline — rather than
a generic flat rounded panel, so these dialogs read as part of the node
editor's own visual language instead of a separate "app chrome" style.

These are simple, non-resizable modals with no separate title-bar strip;
the header band doubles as the dialog's draggable handle (clicking any
other empty area of the dialog body also drags it, exactly like clicking
empty chrome on the main window's title bar does).
"""
from __future__ import annotations

import sys

from PyQt5.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget
from PyQt5.QtCore import Qt, QPoint, QTimer

from configuration import NODE_HEADER_HEIGHT, DWMWCP_DONOTROUND, NODE_SELECTED_COLOR
from diagnostics import log_and_explain
from ui.theme import RESTORE_DIALOG_QSS
from ui.window_chrome import apply_rounded_corners, apply_immersive_dark_mode

# Same selection-highlight color a node's border uses when selected —
# overrides RESTORE_DIALOG_QSS's own border rule (later same-selector
# property wins) for the brief "still waiting on you" flash below.
_FLASH_BORDER_QSS = RESTORE_DIALOG_QSS + f"\n#RestoreChoiceDialog {{ border: 1px solid {NODE_SELECTED_COLOR}; }}"

_WH_MOUSE_LL = 14
_WM_LBUTTONDOWN = 0x0201
_WM_RBUTTONDOWN = 0x0204


class FramelessDialogBase(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setObjectName("RestoreChoiceDialog")
        self.setStyleSheet(RESTORE_DIALOG_QSS)
        self.setModal(True)
        self._drag_start = None

        outer = QVBoxLayout(self)
        # 1px margin, matching the border width below: with 0 margin the
        # header/body children paint edge-to-edge and cover the exact pixels
        # #RestoreChoiceDialog's own QSS border would draw on, hiding it
        # completely rather than just not showing a flash.
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        # The node primitive: a colored header band spanning the full width,
        # a body below it — see graph_items.py's MetaNode.paint(), which
        # this mirrors (header rect + body rect + one outer border), just
        # built from real widgets instead of painted directly.
        self._header = QLabel()
        self._header.setObjectName("dialogHeader")
        self._header.setFixedHeight(NODE_HEADER_HEIGHT)
        outer.addWidget(self._header)

        body = QWidget()
        body.setObjectName("dialogBody")
        outer.addWidget(body)
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(16, 16, 16, 16)
        self.body_layout.setSpacing(10)

    def setWindowTitle(self, title: str) -> None:
        super().setWindowTitle(title)
        self._header.setText(title)

    def showEvent(self, event):
        super().showEvent(event)
        # Square corners, matching every node's sharp-cornered look — not
        # the rounded DWM corner the main window uses elsewhere.
        apply_rounded_corners(self, DWMWCP_DONOTROUND)
        apply_immersive_dark_mode(self)
        if sys.platform == "win32":
            self._install_click_outside_hook()

    def hideEvent(self, event):
        if sys.platform == "win32":
            self._remove_click_outside_hook()
        super().hideEvent(event)

    # Why a low-level mouse hook, not a Qt event filter: a click on the main
    # window while this dialog is application-modal never becomes a Qt event
    # at all — Windows marks the main window WS_DISABLED for the duration,
    # and a disabled window's clicks are dropped before they're ever posted
    # to any window's message queue (confirmed by instrumenting a
    # QApplication-wide eventFilter here first: it saw every click on this
    # dialog itself, but literally zero events for a main-window click).
    # WH_MOUSE_LL taps input before that per-window routing happens, so it's
    # the only thing that can see it. The hook API is inherently process-
    # wide by Windows' own design (no thread/window-scoped low-level hook
    # exists) but the callback below does nothing for any click outside the
    # main window's rect and is removed the moment this dialog closes.
    def _install_click_outside_hook(self):
        try:
            import ctypes
            from ctypes import wintypes

            class _POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            class _MSLLHOOKSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("pt", _POINT), ("mouseData", wintypes.DWORD),
                    ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_void_p),
                ]

            hook_proc_type = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

            user32 = ctypes.windll.user32
            # Without explicit argtypes/restype, ctypes guesses a plain
            # 32-bit c_int for lParam — but it's really a pointer-sized
            # value (64-bit on x64 Windows), so any lParam past 2^31
            # overflowed that guess and raised on every single mouse move
            # (not just clicks — WH_MOUSE_LL fires for those too), which is
            # both why nothing flashed and why the mouse felt laggy: this
            # was throwing on practically every mouse-move event system-wide.
            user32.CallNextHookEx.restype = ctypes.c_long
            user32.CallNextHookEx.argtypes = [
                ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
            user32.SetWindowsHookExW.restype = ctypes.c_void_p
            user32.SetWindowsHookExW.argtypes = [
                ctypes.c_int, hook_proc_type, wintypes.HINSTANCE, wintypes.DWORD]
            user32.UnhookWindowsHookEx.restype = wintypes.BOOL
            user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]

            def hook_proc(code, wparam, lparam):
                if code >= 0 and wparam in (_WM_LBUTTONDOWN, _WM_RBUTTONDOWN):
                    info = ctypes.cast(lparam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                    click_pos = QPoint(info.pt.x, info.pt.y)
                    parent = self.parent()
                    # This dialog is centered *over* the main window, so its
                    # own rect overlaps the main window's — without excluding
                    # it, every click on the dialog itself (its own header,
                    # buttons, drag-move) also counted as "clicked the main
                    # window" and flashed too.
                    if (parent is not None and parent.frameGeometry().contains(click_pos)
                            and not self.frameGeometry().contains(click_pos)):
                        self.flash_attention()
                return user32.CallNextHookEx(None, code, wparam, lparam)

            # Kept alive on self — ctypes doesn't hold a reference to the
            # Python callback, and a GC'd one crashes the hook the instant
            # it's called.
            self._mouse_hook_proc = hook_proc_type(hook_proc)
            self._mouse_hook = user32.SetWindowsHookExW(
                _WH_MOUSE_LL, self._mouse_hook_proc, None, 0)
        except Exception as exc:
            log_and_explain("Failed to install modal-attention mouse hook", exc)
            self._mouse_hook = None

    def _remove_click_outside_hook(self):
        if getattr(self, "_mouse_hook", None):
            try:
                import ctypes
                ctypes.windll.user32.UnhookWindowsHookEx(self._mouse_hook)
            except Exception as exc:
                log_and_explain("Failed to remove modal-attention mouse hook", exc)
            self._mouse_hook = None

    def flash_attention(self):
        """Blink the border white — the same cue a real native modal dialog
        gives you for clicking its disabled parent."""
        # on / off / on / off, ~120ms apart — one steady flash reads as a
        # rendering glitch; a couple of blinks reads as a deliberate cue.
        for i, qss in enumerate((_FLASH_BORDER_QSS, RESTORE_DIALOG_QSS) * 2):
            QTimer.singleShot(i * 120, lambda qss=qss: self.setStyleSheet(qss))

    # Frameless means no OS-provided drag handle — the header band or any
    # other spot a child widget doesn't already handle (e.g. a button) drags
    # the window, the same convention the main window's title bar uses.
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.globalPos() - self.frameGeometry().topLeft()
            # Same white border a node gets while selected/dragged — clicking
            # or moving this dialog is the equivalent gesture here.
            self.setStyleSheet(_FLASH_BORDER_QSS)
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_start)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        self.setStyleSheet(RESTORE_DIALOG_QSS)
        super().mouseReleaseEvent(event)
