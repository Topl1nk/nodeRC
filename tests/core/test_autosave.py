import os
from pathlib import Path
import pytest

from core.app_prefs import load_prefs, save_prefs, get_session_restore_always, set_session_restore_always
from core.session import start_new_session, session_tab_files
from core.autosave import write_snapshot, load_snapshot, discard_snapshot, flush

@pytest.fixture(autouse=True)
def isolated_appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))

def test_app_prefs_round_trip():
    # Default is False
    assert get_session_restore_always() is False
    
    set_session_restore_always(True)
    assert get_session_restore_always() is True

def test_session_management():
    # Create first session
    s1, prev1 = start_new_session()
    assert s1.is_dir()
    assert prev1 is None
    
    # We must write at least one tab to make the session non-empty,
    # otherwise start_new_session drops it.
    write_snapshot(s1, "tab1", None, False, 0, {"fake": "graph"})
    flush()

    # Create second session
    s2, prev2 = start_new_session()
    assert s2.is_dir()
    assert prev2 == s1

def test_autosave_snapshots(tmp_path):
    session_dir = tmp_path / "session1"
    session_dir.mkdir()
    
    write_snapshot(session_dir, "tab1", None, True, 0, {"node": 1})
    write_snapshot(session_dir, "tab2", None, False, 1, {"node": 2})
    flush()

    tab1_data = load_snapshot(session_dir, "tab1")
    assert tab1_data is not None
    assert tab1_data["dirty"] is True
    assert tab1_data["graph"] == {"node": 1}
    
    tab2_data = load_snapshot(session_dir, "tab2")
    assert tab2_data["dirty"] is False
    assert tab2_data["graph"] == {"node": 2}

    discard_snapshot(session_dir, "tab1")
    assert load_snapshot(session_dir, "tab1") is None
    
    tabs = session_tab_files(session_dir)
    assert len(tabs) == 1
    assert tabs[0].name == "tab2.json"
