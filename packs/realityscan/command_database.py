"""command_database.py — RealityScan Command Catalog Access

Loads the categorized command catalog produced by rs_documentation_extractor,
falling back to a minimal built-in set when no local documentation was parsed —
the command palette must never be empty.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Tuple

from packs.realityscan.config import COMMAND_DB_JSON
from packs.realityscan.rs_documentation_extractor import command_display_name, command_action_word
from diagnostics import log_and_explain

CommandCategoryTree = Dict[str, Dict[str, List[dict]]]


def builtin_command_defaults() -> List[dict]:
    """Minimal offline command set that keeps the editor functional without RS.

    Why: guarantees a non-empty command palette so the UI never silently
    degrades to unusable.
    """
    builtin_commands = [
        ("-addFolder",            ["dirpath"], []),
        ("-align",                [], []),
        ("-calculateHighModel",   [], []),
        ("-calculateNormalModel", [], []),
        ("-exportModel",          ["filepath"], ["params.xml"]),
        ("-save",                 ["filepath"], []),
        ("-load",                 ["filepath"], []),
        ("-quit",                 [], []),
    ]
    return [
        {
            "command":  cmd,
            "required": req,
            "optional": opt,
            "display":  command_display_name(cmd),
            "action":   command_action_word(cmd),
        }
        for cmd, req, opt in builtin_commands
    ]


def load_command_database() -> Tuple[CommandCategoryTree, List[dict]]:
    """The categorized catalog plus its flattened command list."""
    if os.path.exists(COMMAND_DB_JSON):
        try:
            with open(COMMAND_DB_JSON, "r", encoding="utf-8") as f:
                categories: CommandCategoryTree = json.load(f)
            commands = [
                command
                for subsections in categories.values()
                for section_commands in subsections.values()
                for command in section_commands
            ]
            return categories, commands
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            # AttributeError covers a well-formed-but-wrong-shaped JSON (e.g.
            # a list instead of the expected category dict) tripping .values()
            # below. Either way the palette must never come up empty — see
            # module docstring — so fall through to the built-in set instead
            # of taking the whole app down on a corrupted or stale-shaped
            # only if this file itself isn't the thing that's corrupt).
            log_and_explain(f"Ignoring unreadable {COMMAND_DB_JSON}", exc)

    defaults = builtin_command_defaults()
    return {"Commands": {"__root__": defaults}}, defaults
