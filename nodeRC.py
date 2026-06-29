"""
nodeRC.py — Entry Point and Command Database Manager
Parses rc_commands.json on startup.
"""

from __future__ import annotations
import sys
import logging
from typing import List

from configuration import COMMAND_DB_JSON, RC_HELP_HTML
from diagnostics import install_global_exception_hook
from rc_documentation_extractor import command_display_name, command_action_word

_logger = logging.getLogger("nodeRC")


def builtin_command_defaults() -> List[dict]:
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
            "display":  command_display_name(cmd),
            "action":   command_action_word(cmd),
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
        rebuild_command_database_from_html(RC_HELP_HTML, COMMAND_DB_JSON)
    except Exception as exc:
        _logger.warning("Documentation refresh skipped: %s", exc)

    from canvas import NodeEditorWindow
    win = NodeEditorWindow()
    win.show()
    sys.exit(app.exec_())