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
