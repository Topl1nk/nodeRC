"""conftest.py — Test Isolation

Autouse, session-wide setup so tests never touch the real user's
%APPDATA%/nodeRC (autosave/session files). Qt-specific fixtures live in
tests/ui/conftest.py, not here — CODEX.md Ст.3 requires core/ tests to run
without ever importing PyQt5/ui.*, and a root-level conftest.py applies to
every subdirectory including tests/core/, so any Qt import here would leak
into the headless suite regardless of what the individual test files do.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_app_data(tmp_path, monkeypatch):
    """Give every test its own %APPDATA%, so autosave/session state never
    leaks into (or between) test runs — each test starts with zero session
    history, guaranteeing the restore-prompt never has anything to offer."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
