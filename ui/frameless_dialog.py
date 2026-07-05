"""frameless_dialog.py — Shared Chrome for Secondary Modals

Every secondary window in the app (message boxes, the session-restore
prompt) shares this same frameless, DWM-rounded, dark-themed chrome instead
of falling back to the native OS dialog style — so the whole app reads as
one consistent family of windows, not a mix of custom and native ones.

These are simple, non-resizable modals with no separate title-bar strip;
the dialog's own title label doubles as its draggable "header" (clicking
any other empty area of the dialog body also drags it, exactly like
clicking empty chrome on the main window's title bar does).
"""
from __future__ import annotations

from PyQt5.QtWidgets import QDialog, QLabel
from PyQt5.QtCore import Qt

from ui.theme import RESTORE_DIALOG_QSS
from ui.window_chrome import apply_rounded_corners


class FramelessDialogBase(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setObjectName("RestoreChoiceDialog")
        self.setStyleSheet(RESTORE_DIALOG_QSS)
        self.setModal(True)
        self._drag_start = None

    def showEvent(self, event):
        super().showEvent(event)
        apply_rounded_corners(self)

    @staticmethod
    def make_title_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("restoreTitle")
        return label

    # Frameless means no OS-provided drag handle — the dialog body itself
    # (any spot a child widget doesn't already handle, e.g. a button) drags
    # the window, the same convention the main window's title bar uses.
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_start)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        super().mouseReleaseEvent(event)
