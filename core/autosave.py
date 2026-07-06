"""autosave.py — Per-Tab Recovery Snapshots

One file per open tab, written into that run's session folder (see
core/session.py — a session IS a folder of these files, nothing more). Each
envelope carries everything needed to restore that single tab on its own:
the graph, whether it's dirty, and — if it has a manual save — both the
absolute and relative path to it, so a moved project folder can still be
found via the relative fallback.
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import Executor, ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

from configuration import APP_DATA_DIR_NAME
from diagnostics import log_and_explain

AUTOSAVE_VERSION = 1

# A single background worker per process: snapshots for one session all
# funnel through it, so two writes for the same tab can never race and land
# out of order, while the disk I/O itself never blocks the UI thread that
# queued it (see write_snapshot_async).
#
# _executor_lock serializes submit() against flush()'s shutdown+replace: both
# happen while holding it, so a submit can never land on an executor that has
# already had shutdown() called on it (which raises RuntimeError).
_executor_lock = threading.Lock()
_executor: Executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="autosave")


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_DATA_DIR_NAME


def _relpath_anchor() -> str:
    """Fixed anchor for ``manual_path_relative`` — the user's home directory,
    not ``os.getcwd()``. cwd depends on how nodeRC was launched (desktop
    shortcut vs. taskbar pin vs. a terminal) and can differ between runs of
    the same install, which made the relative-path fallback resolve to the
    wrong file (or nowhere) even though the project never moved. Home is
    stable across launch methods on a given machine."""
    return str(Path.home())


def tab_snapshot_path(session_dir: Path, tab_id: str) -> Path:
    return session_dir / f"{tab_id}.json"


def write_snapshot(session_dir: Path, tab_id: str, project_path: Optional[str],
                    dirty: bool, tab_index: int, graph: dict, *,
                    history: Optional[List[dict]] = None, history_index: int = -1) -> None:
    """Write this tab's current graph into its slot in ``session_dir``.
    Never touches ``project_path`` itself — that file is only ever written
    by an explicit manual save. ``tab_index`` (the tab's position in the
    window's tab strip) is what lets restore rebuild tabs in their original
    left-to-right order — the files themselves sort by tab_id, which carries
    no ordering information at all.

    ``graph`` is a plain-data payload already produced by
    ``core.graph_serialization.serialize_graph`` — this function never
    touches the live scene, so it's safe to call from the background thread
    ``write_snapshot_async`` submits it to. ``history``/``history_index``
    (already a bounded window — see editor_window._trimmed_history) let
    Ctrl+Z keep working across a crash/session restore, not just within the
    run that made the edits — a plain manual Save/Open intentionally does
    NOT carry this (see save_project/_load_into_tab): reopening a project
    file is meant to start a fresh undo baseline.
    """
    path = tab_snapshot_path(session_dir, tab_id)
    abs_path = os.path.abspath(project_path) if project_path else None
    rel_path = None
    if abs_path:
        try:
            rel_path = os.path.relpath(abs_path, _relpath_anchor())
        except ValueError:
            pass  # different drive on Windows — no relative path is possible
    envelope = {
        "autosave_version": AUTOSAVE_VERSION,
        "saved_at": time.time(),
        "dirty": bool(dirty),
        "tab_index": tab_index,
        "has_manual_save": project_path is not None,
        "manual_path_absolute": abs_path,
        "manual_path_relative": rel_path,
        "graph": graph,
        "history": history or [],
        "history_index": history_index,
    }
    try:
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(envelope, f)
        os.replace(tmp, path)
    except Exception as exc:
        log_and_explain("Autosave write failed", exc)


def write_snapshot_async(session_dir: Path, tab_id: str, project_path: Optional[str],
                          dirty: bool, tab_index: int, graph: dict, *,
                          history: Optional[List[dict]] = None, history_index: int = -1) -> None:
    """Same as ``write_snapshot``, but the JSON encode + disk write run on a
    background thread instead of the caller's (the UI thread on every edit
    that dirties a tab) — ``graph`` is already a plain dict by this point, so
    handing it to another thread is safe. Use ``flush()`` before the process
    exits to guarantee a just-queued write actually lands on disk.
    """
    with _executor_lock:
        _executor.submit(write_snapshot, session_dir, tab_id, project_path,
                          dirty, tab_index, graph, history=history, history_index=history_index)


def flush() -> None:
    """Block until every write queued via ``write_snapshot_async`` has
    completed. Call this before the app exits — otherwise the last few
    edits before close could still be sitting in the queue when the process
    ends, defeating the whole point of an immediate per-edit snapshot."""
    global _executor
    with _executor_lock:
        _executor.shutdown(wait=True)
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="autosave")


def discard_snapshot(session_dir: Path, tab_id: str) -> None:
    """Remove a tab's slot from the current session — used when the tab
    closes cleanly, so a crash right after doesn't resurrect it."""
    path = tab_snapshot_path(session_dir, tab_id)
    try:
        if path.exists():
            path.unlink()
    except Exception as exc:
        log_and_explain("Autosave cleanup failed", exc)


def load_snapshot(session_dir: Path, tab_id: str) -> Optional[dict]:
    path = tab_snapshot_path(session_dir, tab_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log_and_explain("Autosave read failed", exc)
        return None


def resolve_manual_path(envelope: dict) -> Optional[str]:
    """The manual save path an envelope points to — absolute first, falling
    back to the path relative to the user's home directory (e.g. the project
    folder moved but its layout relative to home didn't). Must use the same
    anchor as ``write_snapshot`` (``_relpath_anchor``) — anything else makes
    the relative fallback resolve to the wrong file."""
    if not envelope.get("has_manual_save"):
        return None
    abs_path = envelope.get("manual_path_absolute")
    if abs_path and os.path.exists(abs_path):
        return abs_path
    rel_path = envelope.get("manual_path_relative")
    if rel_path:
        candidate = os.path.abspath(os.path.join(_relpath_anchor(), rel_path))
        if os.path.exists(candidate):
            return candidate
    return abs_path
