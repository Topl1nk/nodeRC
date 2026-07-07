"""config.py — RealityCapture Pack Paths

The pack's own external paths, moved here from the app-wide configuration.py
when RC became a drop-in pack: nothing outside packs/realitycapture/ should
need to know where RealityCapture lives on disk.

RealityCapture/RealityScan's own install location varies by version, drive
and Epic Games library path (Capturing Reality's original install path and
the newer Epic/RealityScan one both still turn up in the wild) — an
environment variable override means a non-default install doesn't require
editing source, only the two hardcoded paths below stay as the common case.
"""
from __future__ import annotations

import os
from pathlib import Path

_PACK_DIR = Path(__file__).resolve().parent

RC_HELP_HTML = os.environ.get(
    "NODERC_RC_HELP_HTML",
    r"C:\ProgramData\Epic\RealityScan\LanguagePack\help\en-US\appbasics\allcommands.htm")
RC_EXECUTABLE = os.environ.get(
    "NODERC_RC_EXECUTABLE",
    r"C:\Program Files\Capturing Reality\RealityCapture\RealityCapture.exe")

# The generated command catalog lives inside the pack folder itself — the
# same file pack.json declares as commands_source, so the generic catalog
# loader (core/pack_catalog.py) and this pack's own richer loader
# (command_database.py) read one file, not two copies (Ст.1.1; the
# equivalence is pinned by tests/core/test_bundled_packs.py).
COMMAND_DB_JSON = str(_PACK_DIR / "rc_commands.json")
