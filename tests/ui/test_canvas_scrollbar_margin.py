"""The canvas's horizontal/vertical scrollbars sit flush against the view's
edges by default (Qt's own QAbstractScrollArea layout) — inset by
TITLE_BAR_RESIZE_MARGIN (6px) instead while the window is in its normal,
non-maximized state, where those edges double as the native resize-grab
band (see GraphicsView._position_scrollbars).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QEvent

from configuration import TITLE_BAR_RESIZE_MARGIN


def test_scrollbars_are_inset_when_not_maximized(window):
    window.resize(900, 600)
    window.show()
    view = window.view
    view._position_scrollbars()

    vbar = view.verticalScrollBar()
    hbar = view.horizontalScrollBar()
    assert vbar.geometry().right() == view.width() - 1 - TITLE_BAR_RESIZE_MARGIN
    assert vbar.geometry().top() == TITLE_BAR_RESIZE_MARGIN
    assert hbar.geometry().bottom() == view.height() - 1 - TITLE_BAR_RESIZE_MARGIN
    assert hbar.geometry().left() == TITLE_BAR_RESIZE_MARGIN


def test_scrollbars_sit_flush_when_maximized(window, monkeypatch):
    window.resize(900, 600)
    window.show()
    monkeypatch.setattr(window, "isMaximized", lambda: True)
    view = window.view
    view._position_scrollbars()

    vbar = view.verticalScrollBar()
    hbar = view.horizontalScrollBar()
    assert vbar.geometry().right() == view.width() - 1
    assert vbar.geometry().top() == 0
    assert hbar.geometry().bottom() == view.height() - 1
    assert hbar.geometry().left() == 0


def test_inset_survives_qts_own_relayout(window):
    # Simulates what Qt does internally when toggling scrollbar policy or
    # reacting to a scene-rect change: it repositions the scrollbar flush
    # against the edge again, dispatching Resize/Move to it in the process.
    window.resize(900, 600)
    window.show()
    view = window.view
    view._position_scrollbars()
    vbar = view.verticalScrollBar()

    vbar.setGeometry(view.width() - vbar.width(), 0, vbar.width(), view.height())  # Qt's flush default
    view.eventFilter(vbar, QEvent(QEvent.Resize))

    assert vbar.geometry().right() == view.width() - 1 - TITLE_BAR_RESIZE_MARGIN
    assert vbar.geometry().top() == TITLE_BAR_RESIZE_MARGIN
