"""Title bar menu chrome: the hamburger button's QSS :hover state must not
stay stuck "on" after QMenu.exec_() returns (TitleBarWidget._resettle_hover),
the tab context menu anchors to the active tab rather than the cursor or the
right-clicked tab, and only the two menus anchored to the title bar (project
menu, tab context menu) omit their top border — every other context menu in
the app (node/group/canvas) keeps CONTEXT_MENU_STYLESHEET's full 4-sided one.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QColor, QCursor
from PyQt5.QtWidgets import QMenu

from ui.theme import (
    BUTTON_BG_COLOR, BUTTON_HOVER_COLOR, CONTEXT_MENU_STYLESHEET, TITLE_BAR_MENU_STYLESHEET,
)


def test_project_menu_clears_stuck_hover_when_cursor_has_left(window, monkeypatch):
    btn = window.title_bar.tab_strip.menu_btn
    monkeypatch.setattr(QMenu, "exec_", lambda self, *a, **k: None)
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: window.mapToGlobal(QPoint(-500, -500))))
    btn.setAttribute(Qt.WA_UnderMouse, True)

    window.title_bar.tab_strip._show_project_menu()

    assert btn.testAttribute(Qt.WA_UnderMouse) is False


def test_project_menu_keeps_hover_when_cursor_is_still_over_the_button(window, monkeypatch):
    btn = window.title_bar.tab_strip.menu_btn
    monkeypatch.setattr(QMenu, "exec_", lambda self, *a, **k: None)
    center = btn.mapToGlobal(btn.rect().center())
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: center))
    btn.setAttribute(Qt.WA_UnderMouse, False)

    window.title_bar.tab_strip._show_project_menu()

    assert btn.testAttribute(Qt.WA_UnderMouse) is True


def test_tab_context_menu_anchors_to_the_active_tab_not_the_cursor(window, monkeypatch):
    from ui.title_bar import TabButton
    window.new_tab()
    strip = window.title_bar.tab_strip
    buttons = [c for c in strip.children() if isinstance(c, TabButton)]
    active_btn = next(b for b in buttons if b.property("active") == "true")
    right_clicked_btn = next(b for b in buttons if b is not active_btn)

    captured = {}
    monkeypatch.setattr(QMenu, "exec_", lambda self, pos: captured.setdefault("pos", pos))

    # Right-click a *different* tab than the active one, from a cursor
    # position that matches neither tab's corner — the anchor must still
    # land on the active tab's bottom-left corner.
    strip._show_context_menu(right_clicked_btn, QPoint(9999, 9999))

    expected = active_btn.mapToGlobal(active_btn.rect().bottomLeft())
    assert captured["pos"] == expected


def test_only_title_bar_menus_omit_the_top_border():
    # Node/group/canvas context menus (built straight from
    # CONTEXT_MENU_STYLESHEET) must keep their full border — no top-border
    # override anywhere in the shared base stylesheet.
    assert "border-top" not in CONTEXT_MENU_STYLESHEET
    assert "border:1px solid" in CONTEXT_MENU_STYLESHEET

    # The title-bar-only variant layers just the top-border removal on top,
    # without dropping or duplicating any of the base declarations.
    assert TITLE_BAR_MENU_STYLESHEET.startswith(CONTEXT_MENU_STYLESHEET)
    assert "border-top: none;" in TITLE_BAR_MENU_STYLESHEET


def test_title_bar_menus_use_the_title_bar_stylesheet(window):
    assert window.title_bar.tab_strip.menu_btn is not None
    # Both menu-opening call sites hand QMenu the title-bar variant, not the
    # shared base one.
    import ui.title_bar as title_bar_module
    import inspect
    source = inspect.getsource(title_bar_module)
    assert source.count("menu.setStyleSheet(TITLE_BAR_MENU_STYLESHEET)") == 2


def test_context_menu_background_is_the_button_hover_color():
    assert f"background:{BUTTON_HOVER_COLOR};" in CONTEXT_MENU_STYLESHEET
    # Selected-item highlight swapped to the other tone of the same pair so
    # it still contrasts against the new (lighter) menu background.
    assert f"background:{BUTTON_BG_COLOR};" in CONTEXT_MENU_STYLESHEET


def test_title_bar_buttons_get_a_1px_hover_outline_matching_the_menu_border():
    from ui.theme import NODE_BORDER_COLOR, TITLE_BAR_QSS
    for selector in ("QToolButton#titleBarWinBtn:hover", "QToolButton#titleBarCloseBtn:hover"):
        block_start = TITLE_BAR_QSS.index(selector)
        block = TITLE_BAR_QSS[block_start:TITLE_BAR_QSS.index("}", block_start)]
        assert f"border: 1px solid {NODE_BORDER_COLOR};" in block


def test_title_bar_buttons_reserve_border_width_at_rest_to_avoid_hover_jitter():
    # The rest-state border must be 1px too (just transparent) — swapping
    # 0px "none" for a 1px solid line only on :hover would grow the button's
    # box by 2px and visibly nudge every tab to its right sideways.
    from ui.theme import TITLE_BAR_QSS
    for selector in ("QToolButton#titleBarWinBtn {", "QToolButton#titleBarCloseBtn {"):
        block_start = TITLE_BAR_QSS.index(selector)
        block = TITLE_BAR_QSS[block_start:TITLE_BAR_QSS.index("}", block_start)]
        assert "border: 1px solid transparent;" in block
