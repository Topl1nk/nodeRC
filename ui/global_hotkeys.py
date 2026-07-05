"""global_hotkeys.py — App-Wide Keyboard Shortcuts

The language-cycle hotkey needs to work no matter which window currently has
focus — the main editor, an error dialog, the session-restore prompt, or any
future secondary window — so it's caught once here at the QApplication
level instead of being wired into every individual window's keyPressEvent.
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QObject

from configuration import (
    KEY_PREV_LANG, KEY_NEXT_LANG,
    VK_OEM_LEFT_BRACKET, VK_OEM_RIGHT_BRACKET,
    PREV_LANG_LAYOUT_CHARS, NEXT_LANG_LAYOUT_CHARS,
    MOD_NONE,
)


class LanguageHotkeyFilter(QObject):
    """Install once on the QApplication instance (see nodeRC.py). Cycles the
    UI language on every open NodeEditorWindow, regardless of which widget
    or top-level window currently holds keyboard focus."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and event.modifiers() == MOD_NONE:
            direction = self._direction_for(event)
            if direction is not None:
                self._cycle_all_windows(direction)
                event.accept()
                return True
        return super().eventFilter(obj, event)

    @staticmethod
    def _direction_for(event):
        nvk = event.nativeVirtualKey()
        key = event.key()
        if key == KEY_PREV_LANG or nvk == VK_OEM_LEFT_BRACKET or event.text() in PREV_LANG_LAYOUT_CHARS:
            return -1
        if key == KEY_NEXT_LANG or nvk == VK_OEM_RIGHT_BRACKET or event.text() in NEXT_LANG_LAYOUT_CHARS:
            return 1
        return None

    @staticmethod
    def _cycle_all_windows(direction: int):
        from PyQt5.QtWidgets import QApplication
        from ui.editor_window import NodeEditorWindow  # deferred: avoids an import cycle

        app = QApplication.instance()
        if not app:
            return
        for widget in app.topLevelWidgets():
            if isinstance(widget, NodeEditorWindow):
                widget.cycle_language(direction)
