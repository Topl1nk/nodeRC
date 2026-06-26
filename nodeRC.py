"""
nodeRC.py — Entry Point and Legacy Command Loader
Parses rc_commands.txt (legacy) or delegates to rc_commands.json (rich).
On startup, attempts to refresh both files from local RC documentation HTML.
"""

from __future__ import annotations
import sys
import os
import re
import json
from typing import List

from configuration import COMMAND_DB_TXT, COMMAND_DB_JSON, RC_HELP_HTML
from diagnostics import install_global_exception_hook


def load_legacy_command_definitions(filename: str = COMMAND_DB_TXT) -> List[dict]:
    """
    Parse rc_commands.txt into flat list of command dicts.
    Format per line:  -cmd; required:p1,p2; optional:p3
    """
    if not os.path.exists(filename):
        return _builtin_command_defaults()

    command_defs: List[dict] = []
    with open(filename, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            parts    = [p.strip() for p in line.split(";")]
            command  = parts[0]
            required: List[str] = []
            optional: List[str] = []
            for part in parts[1:]:
                if part.startswith("required:"):
                    required = [p for p in part[len("required:"):].strip().split(",") if p]
                elif part.startswith("optional:"):
                    optional = [p for p in part[len("optional:"):].strip().split(",") if p]
            command_defs.append({
                "command":  command,
                "required": required,
                "optional": optional,
                "display":  _command_display_name(command),
                "action":   _command_action_word(command),
            })
    return command_defs if command_defs else _builtin_command_defaults()


def _command_display_name(command_flag: str) -> str:
    s = command_flag.lstrip("-")
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', s)
    s = re.sub(r'([a-z\d])([A-Z])', r'\1 \2', s)
    return s


def _command_action_word(command_flag: str) -> str:
    s = command_flag.lstrip("-")
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', s)
    s = re.sub(r'([a-z\d])([A-Z])', r'\1 \2', s)
    parts = s.strip().split()
    return parts[0].lower() if parts else ""


def _builtin_command_defaults() -> List[dict]:
    """
    Minimal offline command set that makes the editor functional without RC installed.
    Why: guarantees non-empty command palette so the UI never silently degrades to unusable.
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
            "display":  _command_display_name(cmd),
            "action":   _command_action_word(cmd),
        }
        for cmd, req, opt in builtin_commands
    ]


if __name__ == "__main__":
    install_global_exception_hook()

    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    try:
        from rc_documentation_extractor import rebuild_command_database_from_html
        rebuild_command_database_from_html(RC_HELP_HTML, COMMAND_DB_JSON, COMMAND_DB_TXT)
    except Exception as exc:
        print(f"[nodeRC] Documentation refresh skipped: {exc}")

    from canvas import NodeEditorWindow
    win = NodeEditorWindow()
    win.show()
    sys.exit(app.exec_())