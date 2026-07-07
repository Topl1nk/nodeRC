"""pack_catalog.py — Merging Node Catalogs Across Installed Packs

The search menu (ui/search_menu.py) already renders any category tree it's
handed — {section: {subsection: [command, ...]}} — generically; it never
needed to know RealityCapture existed. This module is what makes that true
end to end: it reads each installed pack's own commands_source JSON file
directly off disk and merges them, so the editor's node palette reflects
every installed pack, not just the one bundled today.

Reads only the static catalog file a manifest declares — never a pack's own
Python code. core/pack_executor.py is the only thing that ever runs a
pack's code, and only in its own subprocess (Доктрина III.1); loading the
palette must not be an exception to that just because it happens at
startup instead of on a Launch click.
"""
from __future__ import annotations

import json
from typing import Dict, List

from core.pack_registry import InstalledPack
from diagnostics import log_and_explain

CommandCategoryTree = Dict[str, Dict[str, List[dict]]]


def load_pack_catalog(installed: InstalledPack) -> CommandCategoryTree:
    """The category tree at pack_dir/commands_source. A pack with no
    commands_source, or whose catalog file is missing or malformed,
    contributes nothing — logged (Ст.8.2), not fatal to the rest of the
    merge."""
    if not installed.manifest.commands_source:
        return {}
    catalog_path = installed.pack_dir / installed.manifest.commands_source
    if not catalog_path.is_file():
        return {}
    try:
        return json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log_and_explain(f"Skipping catalog for pack '{installed.manifest.pack_id}'", exc)
        return {}


def merge_catalogs(*trees: CommandCategoryTree) -> CommandCategoryTree:
    """Combine multiple packs' category trees into one. A section name
    shared by two packs merges their subsections instead of one silently
    overwriting the other."""
    merged: CommandCategoryTree = {}
    for tree in trees:
        for section, subsections in tree.items():
            merged_section = merged.setdefault(section, {})
            for subsection, commands in subsections.items():
                merged_section.setdefault(subsection, []).extend(commands)
    return merged


def flatten_commands(tree: CommandCategoryTree) -> List[dict]:
    return [
        command
        for subsections in tree.values()
        for commands in subsections.values()
        for command in commands
    ]
