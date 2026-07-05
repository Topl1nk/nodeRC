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
import time
from pathlib import Path
from typing import List, Optional

from configuration import APP_DATA_DIR_NAME
from core.graph_serialization import serialize_graph
from diagnostics import log_and_explain

AUTOSAVE_VERSION = 1


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_DATA_DIR_NAME


def tab_snapshot_path(session_dir: Path, tab_id: str) -> Path:
    return session_dir / f"{tab_id}.json"


def write_snapshot(session_dir: Path, tab_id: str, project_path: Optional[str],
                    dirty: bool, tab_index: int, scene, connections: List) -> None:
    """Write this tab's current graph into its slot in ``session_dir``.
    Never touches ``project_path`` itself — that file is only ever written
    by an explicit manual save. ``tab_index`` (the tab's position in the
    window's tab strip) is what lets restore rebuild tabs in their original
    left-to-right order — the files themselves sort by tab_id, which carries
    no ordering information at all."""
    path = tab_snapshot_path(session_dir, tab_id)
    abs_path = os.path.abspath(project_path) if project_path else None
    rel_path = None
    if abs_path:
        try:
            rel_path = os.path.relpath(abs_path, os.getcwd())
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
        "graph": serialize_graph(scene, connections),
    }
    try:
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(envelope, f)
        os.replace(tmp, path)
    except Exception as exc:
        log_and_explain("Autosave write failed", exc)


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
    back to the path relative to the current working directory (e.g. the
    project folder moved but its layout relative to where nodeRC runs from
    didn't)."""
    if not envelope.get("has_manual_save"):
        return None
    abs_path = envelope.get("manual_path_absolute")
    if abs_path and os.path.exists(abs_path):
        return abs_path
    rel_path = envelope.get("manual_path_relative")
    if rel_path:
        candidate = os.path.abspath(os.path.join(os.getcwd(), rel_path))
        if os.path.exists(candidate):
            return candidate
    return abs_path
