"""app_prefs.py — Tiny App-Level Preferences

A single JSON file at %APPDATA%/nodeRC/prefs.json — plain and inspectable,
matching every other persisted format in this codebase (project saves,
autosave envelopes) rather than reaching for QSettings' registry-backed
default for a couple of booleans. Currently holds exactly one preference:
whether the user picked "Always Yes" on the session-restore prompt, so it
stops asking and just restores automatically on every future launch.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from configuration import PREFS_FILE_NAME
from core.autosave import app_data_dir
from diagnostics import log_and_explain

PREFS_VERSION = 1
_DEFAULTS = {"prefs_version": PREFS_VERSION, "session_restore_always": False}


def prefs_path() -> Path:
    return app_data_dir() / PREFS_FILE_NAME


def load_prefs() -> dict:
    path = prefs_path()
    if not path.exists():
        return dict(_DEFAULTS)
    try:
        with open(path, "r", encoding="utf-8") as f:
            prefs = json.load(f)
        return {**_DEFAULTS, **prefs}
    except Exception as exc:
        log_and_explain("Prefs read failed, using defaults", exc)
        return dict(_DEFAULTS)


def save_prefs(prefs: dict) -> None:
    path = prefs_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)
        os.replace(tmp, path)
    except Exception as exc:
        log_and_explain("Prefs write failed", exc)


def get_session_restore_always() -> bool:
    """True once the user has picked "Always Yes" on the session-restore
    prompt — future launches skip the prompt and restore automatically."""
    return bool(load_prefs().get("session_restore_always"))


def set_session_restore_always(value: bool) -> None:
    prefs = load_prefs()
    prefs["session_restore_always"] = value
    save_prefs(prefs)


def get_search_usage() -> dict:
    """{entry_key: pick_count} — how often each search-menu entry has ever
    been chosen, across every context. Backs the search menu's "Suggested"
    shortlist and its overall ranking (see ui/search_menu.py)."""
    return load_prefs().get("search_usage", {})


def get_search_usage_after() -> dict:
    """{context_key: {entry_key: pick_count}} — which entries tend to get
    picked right after a given exec context (a command, or "start"), so the
    search menu can rank "what usually follows this node" above raw
    popularity."""
    return load_prefs().get("search_usage_after", {})


def record_search_usage(key: str, after_key: str = None) -> None:
    """Bumps ``key``'s overall pick count, and — when the search opened off
    an exec socket (``after_key`` identifies its owning node) — its
    follow-up count for that context too."""
    prefs = load_prefs()
    usage = prefs.setdefault("search_usage", {})
    usage[key] = usage.get(key, 0) + 1
    if after_key:
        after = prefs.setdefault("search_usage_after", {})
        bucket = after.setdefault(after_key, {})
        bucket[key] = bucket.get(key, 0) + 1
    save_prefs(prefs)
