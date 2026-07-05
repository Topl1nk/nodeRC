"""window_chrome.py — Shared Frameless-Window Helpers

DWM rounded-corner styling used by every frameless top-level window in the
app — the main editor window and every secondary dialog (message boxes,
session-restore prompt) — so they all read as one family of chrome instead
of a mix of custom and native window styles.
"""
from __future__ import annotations

import sys

from configuration import DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND
from diagnostics import log_and_explain


def apply_rounded_corners(widget) -> None:
    """Restore the native Windows 11 rounded window corners a frameless
    window otherwise loses — DWM still manages this window, it just needs
    to be told the corner style explicitly. No-op off Windows."""
    if sys.platform != "win32":
        return
    try:
        from ctypes import windll, byref, sizeof, c_int
        hwnd = int(widget.winId())
        pref = c_int(DWMWCP_ROUND)
        windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, byref(pref), sizeof(pref))
    except Exception as exc:
        log_and_explain("Window corner rounding unavailable", exc)
