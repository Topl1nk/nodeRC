"""nodeRC.py — Entry Point

Installs the structured exception hook, refreshes the command catalog from the
local RealityScan documentation when available, and opens the editor window.
"""
from __future__ import annotations

import logging
import sys

from configuration import WINDOW_STYLE
from diagnostics import install_global_exception_hook

_logger = logging.getLogger("nodeRC")


if __name__ == "__main__":
    install_global_exception_hook()

    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setStyle(WINDOW_STYLE)

    # Unifies every QToolTip in the app to the same primitive used
    # everywhere else (dialog header/body colors) instead of the native OS
    # tooltip style — set at the QApplication level so it applies no matter
    # which widget triggers the tooltip.
    from ui.theme import TOOLTIP_QSS
    app.setStyleSheet(TOOLTIP_QSS)

    # Kept alive on the QApplication instance itself — the language-cycle
    # hotkey then works no matter which window (main or any secondary
    # dialog) currently has focus.
    from ui.global_hotkeys import LanguageHotkeyFilter
    app.hotkey_filter = LanguageHotkeyFilter(app)
    app.installEventFilter(app.hotkey_filter)

    # Same reasoning as the language filter above: the Project Inputs panel's
    # hover-reveal must track the cursor across every open window, not just
    # whichever one last had focus.
    from ui.project_inputs_panel import ProjectInputsHoverFilter
    app.project_inputs_hover_filter = ProjectInputsHoverFilter(app)
    app.installEventFilter(app.project_inputs_hover_filter)

    try:
        # Both imports live in the try, not at module level (Доктрина III.1):
        # the realityscan pack is optional like any other, and a system
        # without it installed must still launch, not crash on this import.
        from packs.realityscan.config import COMMAND_DB_JSON, RS_HELP_HTML
        from packs.realityscan.rs_documentation_extractor import rebuild_command_database_from_html
        rebuild_command_database_from_html(RS_HELP_HTML)
    except (Exception, SystemExit) as exc:
        _logger.warning("Documentation refresh skipped: %s", exc)

    from ui.editor_window import NodeEditorWindow
    win = NodeEditorWindow()
    win.show()
    sys.exit(app.exec_())
