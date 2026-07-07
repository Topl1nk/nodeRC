"""Canvas scrollbar tests.

The custom scrollbars are installed via CanvasScrollBarManager which calls
view.setVerticalScrollBar / setHorizontalScrollBar and then deliberately lets
Qt own their geometry.  The old "inset-from-edge" positioning has been removed
because manually calling setGeometry() on a scrollbar that QAbstractScrollArea
is managing causes layoutChildren() / updateScrollBars() to desync, producing
a visible scroll range of zero (no draggable thumb) even when the scene
content overflows the viewport.

Critical invariant (ст. 14.3): WM_NCHITTEST in editor_window must yield
HTCLIENT when the cursor falls over the scrollbar widgets so Windows never
mistakes a scrollbar click for a resize gesture (see
NodeEditorWindow._hit_test_native_message).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import Qt, QEvent


def test_custom_scrollbars_installed(window):
    """After initialisation the view must expose our UnifiedScrollBar instances,
    not Qt's default QScrollBar, so the custom stylesheet and sizeHint are
    active from the first paint."""
    from ui.scrollbar import UnifiedScrollBar

    window.resize(900, 600)
    window.show()
    view = window.view
    assert isinstance(view.verticalScrollBar(), UnifiedScrollBar)
    assert isinstance(view.horizontalScrollBar(), UnifiedScrollBar)


def test_canvas_scrollbars_have_no_dynamic_thickness(window):
    """Scrollbar thickness is fixed (_TRACK_SIZE) — hover changes only the
    handle color, never the widget's own geometry (sizeHint), since an
    external geometry change on a QAbstractScrollArea-managed scrollbar
    desyncs the scroll range and shifts the thumb along the track."""
    window.resize(900, 600)
    window.show()
    view = window.view
    mgr = view._scrollbar_manager

    vbar = mgr.vbar
    before = vbar.sizeHint()
    vbar.enterEvent(QEvent(QEvent.Enter))
    assert vbar.sizeHint() == before

    vbar.leaveEvent(QEvent(QEvent.Leave))
    assert vbar.sizeHint() == before


def test_scrollbars_hidden_by_default(window):
    """At startup the canvas scrollbars must be closed (ст. 0.2) — same as
    the Project Inputs panel — until the toggle button reveals them."""
    window.resize(900, 600)
    window.show()
    view = window.view
    mgr = view._scrollbar_manager

    assert mgr.scrollbars_visible is False
    assert view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert view.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_scrollbars_visible_flag_syncs_with_policy(window):
    """toggle_scrollbar_visibility must update both the policy and the internal
    flag so subsequent reads are consistent."""
    window.resize(900, 600)
    window.show()
    view = window.view
    mgr = view._scrollbar_manager

    assert mgr.scrollbars_visible is False

    mgr.toggle_scrollbar_visibility()
    assert mgr.scrollbars_visible is True
    assert view.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert view.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded

    mgr.toggle_scrollbar_visibility()
    assert mgr.scrollbars_visible is False
    assert view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert view.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_scrollbar_colors_match_configuration(window):
    """Every UnifiedScrollBar (canvas included) draws its handle/track from
    the three shared configuration.py colors — inactive handle, active
    (hover) handle, and track background — so all scrollbars in the app
    stay visually consistent from one source (ст. 1.1)."""
    from configuration import (
        SCROLLBAR_HANDLE_COLOR, SCROLLBAR_HANDLE_ACTIVE_COLOR, SCROLLBAR_TRACK_COLOR,
    )

    window.resize(900, 600)
    window.show()
    view = window.view
    mgr = view._scrollbar_manager
    vbar = mgr.vbar

    style = vbar.styleSheet()
    assert f"background: {SCROLLBAR_TRACK_COLOR}" in style
    assert f"background: {SCROLLBAR_HANDLE_COLOR}" in style

    vbar.enterEvent(QEvent(QEvent.Enter))
    assert f"background: {SCROLLBAR_HANDLE_ACTIVE_COLOR}" in vbar.styleSheet()
    vbar.leaveEvent(QEvent(QEvent.Leave))


def test_scrollbar_edge_margin_is_6px(window):
    """Canvas scrollbars must be inset 6px from the view edge (top/bottom for
    the vertical bar, left/right for the horizontal one) — a QSS margin on
    the groove, not setGeometry (see ui/scrollbar.py docstring for why)."""
    from configuration import CANVAS_SCROLLBAR_EDGE_MARGIN

    assert CANVAS_SCROLLBAR_EDGE_MARGIN == 6

    window.resize(900, 600)
    window.show()
    view = window.view
    mgr = view._scrollbar_manager

    assert mgr.vbar.edge_margin == CANVAS_SCROLLBAR_EDGE_MARGIN
    assert mgr.hbar.edge_margin == CANVAS_SCROLLBAR_EDGE_MARGIN
    vstyle = mgr.vbar.styleSheet()
    assert f"margin-top: {CANVAS_SCROLLBAR_EDGE_MARGIN}px" in vstyle
    assert f"margin-bottom: {CANVAS_SCROLLBAR_EDGE_MARGIN}px" in vstyle
    hstyle = mgr.hbar.styleSheet()
    assert f"margin-left: {CANVAS_SCROLLBAR_EDGE_MARGIN}px" in hstyle
    assert f"margin-right: {CANVAS_SCROLLBAR_EDGE_MARGIN}px" in hstyle


def test_toggle_button_repositioned_on_resize(window):
    """After a resize event the toggle button must land near the bottom-right
    corner of the view (within SCROLLBAR_BTN_MARGIN + SCROLLBAR_BTN_OFFSET of
    both edges)."""
    from configuration import SCROLLBAR_BTN_MARGIN, SCROLLBAR_BTN_OFFSET, SCROLLBAR_BTN_SIZE

    window.resize(900, 600)
    window.show()
    view = window.view
    mgr = view._scrollbar_manager

    view.resize(1000, 700)
    mgr.on_view_resize()

    btn = mgr.toggle_btn
    pad = SCROLLBAR_BTN_MARGIN + SCROLLBAR_BTN_OFFSET
    assert btn.x() == view.width() - btn.width() - pad
    assert btn.y() == view.height() - btn.height() - pad


def test_nchittest_yields_to_vbar(window):
    """WM_NCHITTEST must return None (HTCLIENT) when the cursor is over the
    vertical scrollbar so Windows never routes the click as a resize gesture.
    This is the critical guard added in editor_window._hit_test_native_message.
    """
    import ctypes
    from ctypes import wintypes
    from PyQt5.QtCore import QPoint
    from ui.editor_window import _WM_NCHITTEST

    class _MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD), ("pt", wintypes.POINT),
        ]

    window.resize(900, 600)
    window.show()
    view = window.view

    mgr = view._scrollbar_manager
    vbar = mgr.vbar

    # vbar's geometry is set by Qt's layout; it's near the right edge.
    # Pick the centre of the vbar in window-local coordinates.
    vbar_geo = vbar.geometry()  # view-local
    view_origin = view.mapTo(window, QPoint(0, 0))
    bar_center_win = view_origin + vbar_geo.center()
    global_pt = window.mapToGlobal(bar_center_win)

    msg = _MSG(
        hwnd=int(window.winId()),
        message=_WM_NCHITTEST,
        wParam=0,
        lParam=(global_pt.y() & 0xFFFF) << 16 | (global_pt.x() & 0xFFFF),
    )
    result = window._hit_test_native_message(ctypes.addressof(msg))
    # The guard must yield HTCLIENT (None) — not a resize code.
    assert result is None, f"Expected None (HTCLIENT) over vbar, got {result}"
