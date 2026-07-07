"""pack_registry.py — Discovering Node Packs

Scans drop-in pack directories for pack.json manifests and validates them
against core.pack_protocol, without importing or executing a single line of
a pack's own code — discovery is manifest-only (Доктрина III.2: declared
access is presented before anything runs). Launching a pack's entry_point
is core/pack_executor.py's job (Phase 4), not this module's.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from configuration import BUNDLED_PACKS_DIR_NAME, PACKS_DIR_NAME
from core.autosave import app_data_dir
from core.pack_protocol import PackManifest, PackManifestError
from diagnostics import log_and_explain

MANIFEST_FILENAME = "pack.json"


@dataclass(frozen=True)
class InstalledPack:
    """A discovered pack: its validated manifest plus the folder it was
    found in, so pack_executor can resolve entry_point/commands_source
    relative to it later."""
    manifest: PackManifest
    pack_dir: Path


def default_pack_search_dirs() -> List[Path]:
    """Bundled packs shipped alongside the editor, then user-installed
    drop-in packs under %APPDATA%/nodeRC/packs — in that order. A
    user-installed pack sharing a pack_id with a bundled one shadows it
    (discover_packs keeps the last manifest seen per pack_id)."""
    return [Path(BUNDLED_PACKS_DIR_NAME), app_data_dir() / PACKS_DIR_NAME]


def discover_packs(search_dirs: List[Path]) -> List[InstalledPack]:
    """Every valid, protocol-compatible manifest found one level under each
    directory in search_dirs (one subfolder per pack, each holding a
    pack.json at its root).

    A malformed or protocol-incompatible manifest is skipped with a logged,
    human-readable reason (Ст.8.2/8.3) — one broken pack never keeps the
    rest of the catalog from loading. Later search_dirs take precedence: a
    pack_id found in more than one directory keeps only the last manifest
    seen for it.
    """
    found: Dict[str, InstalledPack] = {}
    for search_dir in search_dirs:
        if not search_dir.is_dir():
            continue
        for pack_dir in sorted(p for p in search_dir.iterdir() if p.is_dir()):
            manifest_path = pack_dir / MANIFEST_FILENAME
            if not manifest_path.is_file():
                continue
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = PackManifest.from_dict(payload)
                manifest.check_protocol_compatible()
            except (OSError, json.JSONDecodeError, PackManifestError) as exc:
                log_and_explain(f"Skipping pack at {pack_dir}", exc)
                continue
            found[manifest.pack_id] = InstalledPack(manifest=manifest, pack_dir=pack_dir)
    return list(found.values())
