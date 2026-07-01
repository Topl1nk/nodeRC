"""nodeRC.py — Entry Point

Installs the structured exception hook, refreshes the command catalog from the
local RealityScan documentation when available, and opens the editor window.
"""
from __future__ import annotations

import logging
import sys

from configuration import COMMAND_DB_JSON, RC_HELP_HTML, WINDOW_STYLE
from diagnostics import install_global_exception_hook

_logger = logging.getLogger("nodeRC")


if __name__ == "__main__":
    install_global_exception_hook()

    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setStyle(WINDOW_STYLE)

    try:
        from rc_documentation_extractor import rebuild_command_database_from_html
        rebuild_command_database_from_html(RC_HELP_HTML, COMMAND_DB_JSON)
    except Exception as exc:
        _logger.warning("Documentation refresh skipped: %s", exc)

    from editor_window import NodeEditorWindow
    win = NodeEditorWindow()
    win.show()
    sys.exit(app.exec_())
