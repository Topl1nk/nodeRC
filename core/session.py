"""session.py — Whole-Session Recovery

A session IS a folder: %APPDATA%/nodeRC/sessions/<timestamp>/, holding one
autosave.py snapshot file per tab that was open. No separate index —
whichever tab files exist in a session folder ARE that session's tabs.

Each app run gets its own fresh, empty folder to write into
(start_new_session()); whichever folder was newest from the *previous* run
is handed back as "the previous session" to offer for restore. Folders are
pruned to the SESSION_HISTORY_LIMIT most recent.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import List, Optional, Tuple

from configuration import SESSION_DIR_NAME, SESSION_HISTORY_LIMIT
from core.autosave import app_data_dir
from diagnostics import log_and_explain


_LAST_SESSION_MARKER = "_last_session.txt"


def sessions_root() -> Path:
    d = app_data_dir() / SESSION_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _existing_session_dirs() -> List[Path]:
    root = sessions_root()
    return sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name)


def _read_last_session_marker(root: Path) -> Optional[str]:
    try:
        name = (root / _LAST_SESSION_MARKER).read_text(encoding="utf-8").strip()
        return name or None
    except OSError:
        return None


def _write_last_session_marker(root: Path, name: str) -> None:
    try:
        (root / _LAST_SESSION_MARKER).write_text(name, encoding="utf-8")
    except OSError as exc:
        log_and_explain("Session marker write failed", exc)


def start_new_session() -> Tuple[Path, Optional[Path]]:
    """Call once at startup. Returns (this run's fresh session folder, the
    previous run's folder or None). Also prunes history beyond
    SESSION_HISTORY_LIMIT, oldest first."""
    existing = _existing_session_dirs()

    # A session folder that never got a single tab snapshot written to it
    # (every tab that run stayed a blank, never-touched "Untitled") holds
    # nothing worth restoring — drop it outright rather than letting it
    # occupy one of the SESSION_HISTORY_LIMIT slots and mask an older, real
    # session as "the previous one" to offer for restore.
    non_empty = []
    for d in existing:
        if session_tab_files(d):
            non_empty.append(d)
        else:
            try:
                shutil.rmtree(d)
            except OSError as exc:
                log_and_explain("Empty session cleanup failed", exc)
    existing = non_empty

    # "Previous session" is tracked by an explicit marker written at the end
    # of this function, not inferred by sorting folder names — those names
    # are wall-clock timestamps, so a clock rolled backward between runs
    # could make the newest folder sort before an older one and silently
    # offer a stale session for restore. The marker records which folder
    # this process itself created last, which a clock change can't disturb.
    root = sessions_root()
    previous_dir = None
    last_name = _read_last_session_marker(root)
    if last_name:
        candidate = root / last_name
        if candidate in existing:
            previous_dir = candidate
    if previous_dir is None:
        # First run after this marker was introduced (or the marker was
        # lost) — fall back to the old name-sort heuristic just this once.
        previous_dir = existing[-1] if existing else None

    stamp = f"{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}"
    current_dir = root / stamp
    current_dir.mkdir(parents=True, exist_ok=True)
    _write_last_session_marker(root, stamp)

    all_dirs = existing + [current_dir]
    excess = len(all_dirs) - SESSION_HISTORY_LIMIT
    for old_dir in all_dirs[:max(0, excess)]:
        try:
            shutil.rmtree(old_dir)
        except OSError as exc:
            log_and_explain("Old session cleanup failed", exc)

    return current_dir, previous_dir


def session_tab_files(session_dir: Optional[Path]) -> List[Path]:
    if session_dir is None or not session_dir.is_dir():
        return []
    return sorted(session_dir.glob("*.json"))
