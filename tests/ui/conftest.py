"""conftest.py — Qt Test Isolation

Setup specific to the Qt-backed suite: offscreen platform so no real window
opens, and a modal-dialog auto-decline so NodeEditorWindow.__init__'s
session-restore prompt never blocks the run with no user around to click a
button. Scoped to tests/ui/ so tests/core/ never imports PyQt5 (CODEX.md
Ст.3) just by virtue of sharing a test run with these.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtWidgets import QApplication

from ui.editor_window import NodeEditorWindow


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    return NodeEditorWindow()


@pytest.fixture(autouse=True)
def no_session_restore_dialog(monkeypatch):
    """Belt-and-suspenders: even if a test somehow creates a second
    NodeEditorWindow while a first one's session is still on disk, never let
    the real modal dialog block the suite — auto-decline instead."""
    from ui.session_restore_dialog import SessionRestoreDialog

    def _auto_decline(self):
        self.choice = "no"
        return 1

    monkeypatch.setattr(SessionRestoreDialog, "exec_", _auto_decline)
