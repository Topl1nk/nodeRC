"""conftest.py — Test Isolation

Autouse, session-wide setup so tests never touch the real user's
%APPDATA%/nodeRC (autosave/session files) and never hang on a real modal
dialog: NodeEditorWindow.__init__ now writes/reads session-restore state on
every construction, and a real "restore previous session?" QDialog.exec_()
would block forever with no user around to click a button.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def isolate_app_data(tmp_path, monkeypatch):
    """Give every test its own %APPDATA%, so autosave/session state never
    leaks into (or between) test runs — each test starts with zero session
    history, guaranteeing the restore-prompt never has anything to offer."""
    monkeypatch.setenv("APPDATA", str(tmp_path))


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
