"""keymap.py — Keyboard shortcut key codes and modifiers.

Split out of configuration.py because these need Qt.Key_*/Qt.*Modifier —
importing PyQt5 there would drag Qt into every headless core/ import (core
imports configuration.py for its Qt-free constants). See CODEX.md Ст.7.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt

# ── Keyboard Shortcuts ─────────────────────────────────────────────────────────
KEY_SPAWN_MENU   = Qt.Key_Space
KEY_DELETE       = Qt.Key_Delete
KEY_SAVE         = Qt.Key_S
KEY_OPEN         = Qt.Key_O
KEY_COPY         = Qt.Key_C
KEY_PASTE        = Qt.Key_V
KEY_UNDO         = Qt.Key_Z
KEY_REDO         = Qt.Key_Y
KEY_TOGGLE_GRID  = Qt.Key_G
KEY_FIT_VIEW     = Qt.Key_F
KEY_FULLSCREEN   = Qt.Key_F11
KEY_COMMIT_EDIT  = [Qt.Key_Return, Qt.Key_Enter]
KEY_CANCEL_EDIT  = Qt.Key_Escape
KEY_RENAME_NODE  = Qt.Key_F2
KEY_SELECT_ALL   = Qt.Key_A
KEY_GROUP        = Qt.Key_G  # with Ctrl — frames the selection (bare G toggles the grid)
KEY_DUPLICATE    = Qt.Key_D  # with Ctrl — clones the selection in place
KEY_PREV_LANG    = Qt.Key_BracketLeft
KEY_NEXT_LANG    = Qt.Key_BracketRight
KEY_NEW_TAB      = Qt.Key_N  # with Ctrl+Shift — new tab
KEY_NEW_TAB_ALT  = Qt.Key_N  # with Ctrl — new tab
KEY_DUPLICATE_TAB= Qt.Key_D  # with Ctrl+Shift — duplicate tab
KEY_CLOSE_TAB    = Qt.Key_X  # with Ctrl+Shift — close the active project
KEY_CLOSE_OTHERS = Qt.Key_W  # with Ctrl+Shift — close other tabs
KEY_CLOSE_RIGHT  = Qt.Key_E  # with Ctrl+Shift — close tabs to right
KEY_CLOSE_LEFT   = Qt.Key_Q  # with Ctrl+Shift — close tabs to left
KEY_REOPEN_TAB   = Qt.Key_T  # with Ctrl+Shift — reopen closed tab
KEY_NEXT_TAB     = Qt.Key_Tab  # with Ctrl / Ctrl+Shift — cycle projects
KEY_EXECUTE      = Qt.Key_F5  # trigger execute_chain(), same as StartNode's Launch button
KEY_TOGGLE_PROJECT_INPUTS_PANEL = Qt.Key_I  # with Ctrl — show/hide the left Project Inputs dock
KEY_TOGGLE_PROJECT_INPUTS_PANEL_ALT = Qt.Key_Q  # without modifiers - same as above

# ── Keyboard Modifiers ────────────────────────────────────────────────────────
MOD_NONE       = Qt.NoModifier
MOD_CTRL       = Qt.ControlModifier
MOD_CTRL_SHIFT = Qt.ControlModifier | Qt.ShiftModifier
