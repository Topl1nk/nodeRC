"""The hover-revealed tab close button: hidden at rest, a square full-height
mini active-tab at the hovered tab's right edge, never shown mid-drag
(see TabButton._set_hovered / TabCloseButton in ui/title_bar.py).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QEvent
from PyQt5.QtGui import QColor

from configuration import TAB_HEIGHT, TAB_MAX_WIDTH
from ui.title_bar import TabButton, TabCloseButton
from ui.theme import TAB_GRADIENT_DARK, TAB_GRADIENT_LIGHT


def _first_tab(window) -> TabButton:
    return next(c for c in window.title_bar.tab_strip.children() if isinstance(c, TabButton))


def test_close_button_hidden_at_rest(window):
    tab = _first_tab(window)
    assert isinstance(tab.close_btn, TabCloseButton)
    assert tab.close_btn.isVisible() is False


def test_hover_widens_tab_and_reveals_square_full_height_button(window):
    window.resize(900, 600)
    window.show()
    tab = _first_tab(window)
    width_before = tab.width()

    tab.enterEvent(QEvent(QEvent.Enter))
    window.title_bar.tab_strip._layout.activate()

    assert tab.close_btn.isVisibleTo(tab) is True
    assert tab.width() == width_before + TAB_HEIGHT
    geo = tab.close_btn.geometry()
    assert geo.width() == geo.height() == tab.height()   # square, full tab height
    assert geo.right() == tab.width() - 1                # flush with the right edge

    tab.leaveEvent(QEvent(QEvent.Leave))
    window.title_bar.tab_strip._layout.activate()
    assert tab.close_btn.isVisibleTo(tab) is False
    assert tab.width() == width_before


def test_close_button_inherits_its_own_tabs_chrome(window):
    window.new_tab()
    window.resize(900, 600)
    window.show()
    tabs = [c for c in window.title_bar.tab_strip.children() if isinstance(c, TabButton)]
    active_tab = next(t for t in tabs if t.property("active") == "true")
    inactive_tab = next(t for t in tabs if t.property("active") != "true")

    for tab in (active_tab, inactive_tab):
        tab.enterEvent(QEvent(QEvent.Enter))
        img = tab.close_btn.grab().toImage()
        w, h = img.width(), img.height()
        top_face = img.pixelColor(w // 2, 2)
        # Active tab: light gradient stop at the top; inactive: dark stop at
        # the top — the button's face matches its own tab's orientation.
        expected = TAB_GRADIENT_LIGHT if tab is active_tab else TAB_GRADIENT_DARK
        assert abs(top_face.lightness() - QColor(expected).lightness()) < 30
        tab.leaveEvent(QEvent(QEvent.Leave))


def test_close_button_turns_red_on_its_own_hover(window):
    from ui.theme import TITLE_BAR_CLOSE_HOVER_COLOR
    window.resize(900, 600)
    window.show()
    tab = _first_tab(window)
    tab.enterEvent(QEvent(QEvent.Enter))
    btn = tab.close_btn

    btn.enterEvent(QEvent(QEvent.Enter))
    img = btn.grab().toImage()
    center = img.pixelColor(img.width() // 2, img.height() // 2)
    assert center.name() == QColor(TITLE_BAR_CLOSE_HOVER_COLOR).name()

    btn.leaveEvent(QEvent(QEvent.Leave))
    img = btn.grab().toImage()
    center = img.pixelColor(img.width() // 2, img.height() // 2)
    assert center.name() != QColor(TITLE_BAR_CLOSE_HOVER_COLOR).name()


def test_drag_retracts_button_and_blocks_hover_until_release(window):
    window.resize(900, 600)
    window.show()
    tab = _first_tab(window)
    tab.enterEvent(QEvent(QEvent.Enter))
    assert tab.close_btn.isVisibleTo(tab) is True

    tab._set_hovered(False)
    tab._dragging = True

    tab._set_hovered(True)  # what enter/hover would do mid-drag — must be refused
    assert tab.close_btn.isVisibleTo(tab) is False
    assert tab.width() <= TAB_MAX_WIDTH  # no extra strip reserved while dragging

    tab._dragging = False
    tab._set_hovered(True)
    assert tab.close_btn.isVisibleTo(tab) is True
