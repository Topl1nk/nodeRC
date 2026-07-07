"""Bottom-of-screen window snap — the one zone Windows' own Aero Snap has no
native equivalent for (see TitleBarWidget._snap_to_bottom_if_dropped_there).

Previously only reachable from the fully-manual drag path
(TitleBarWidget.mouseReleaseEvent), which a real Windows drag never takes:
starting a drag from an already-restored window hands the whole thing to
DefWindowProc's own native caption-move loop, so mouseReleaseEvent here never
ran and the bottom snap was dead for the common case. NodeEditorWindow now
also triggers it from WM_EXITSIZEMOVE, once a native caption drag it saw
start (WM_NCLBUTTONDOWN/HTCAPTION) has ended.
"""
import ctypes
import os
from ctypes import wintypes

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QApplication

from ui.editor_window import _HTCAPTION, _WM_NCLBUTTONDOWN


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD), ("pt", wintypes.POINT),
    ]


_WM_EXITSIZEMOVE = 0x0232


def _send(window, message, wparam=0, lparam=0):
    msg = _MSG(hwnd=int(window.winId()), message=message, wParam=wparam, lParam=lparam)
    return window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))


def _screen_geo(window):
    screen = QApplication.screenAt(window.frameGeometry().center()) or QApplication.primaryScreen()
    return screen.availableGeometry()


def test_snap_to_bottom_center_resizes_to_bottom_half(window):
    window.show()
    geo = _screen_geo(window)
    center_bottom = QPoint(geo.center().x(), geo.bottom())

    height_before = window.geometry().height()

    snapped = window.title_bar._snap_to_bottom_if_dropped_there(center_bottom)

    assert snapped is True
    win_geo = window.geometry()
    # The offscreen test platform's tiny virtual screen means the requested
    # bottom-half height can land under the window's own WINDOW_MIN_HEIGHT
    # and get clamped there — real screens are nowhere near that small, so
    # this only checks the snap actually moved/shrank the window, not exact
    # pixel alignment to the (possibly clamped) target rect.
    assert win_geo.top() > 0
    assert win_geo.height() < height_before
    assert window.title_bar._edge_snapped is True


def test_snap_to_bottom_does_nothing_away_from_the_bottom_edge(window):
    window.show()
    geo = _screen_geo(window)
    middle = geo.center()

    snapped = window.title_bar._snap_to_bottom_if_dropped_there(middle)

    assert snapped is False


def test_snap_to_bottom_yields_to_corners(window):
    window.show()
    geo = _screen_geo(window)
    bottom_left_corner = QPoint(geo.left(), geo.bottom())

    snapped = window.title_bar._snap_to_bottom_if_dropped_there(bottom_left_corner)

    assert snapped is False  # left/right's own snap territory


def test_native_caption_drag_end_triggers_bottom_snap(window, monkeypatch):
    window.show()
    geo = _screen_geo(window)
    monkeypatch.setattr("ui.editor_window.QCursor.pos", staticmethod(lambda: QPoint(geo.center().x(), geo.bottom())))

    _send(window, _WM_NCLBUTTONDOWN, wparam=_HTCAPTION)
    assert window._native_caption_drag_active is True

    _send(window, _WM_EXITSIZEMOVE)

    assert window._native_caption_drag_active is False
    assert window.title_bar._edge_snapped is True


def test_exitsizemove_without_a_seen_caption_drag_does_nothing(window, monkeypatch):
    window.show()
    calls = []
    monkeypatch.setattr(window.title_bar, "_snap_to_bottom_if_dropped_there", lambda pos: calls.append(pos))

    # A plain edge resize also ends with WM_EXITSIZEMOVE — must not be
    # mistaken for a caption drag that never happened.
    _send(window, _WM_EXITSIZEMOVE)

    assert calls == []


def test_nclbuttondown_on_caption_does_not_consume_the_message(window):
    window.show()
    handled, result = _send(window, _WM_NCLBUTTONDOWN, wparam=_HTCAPTION)
    # Must fall through to Qt's own default handling (False) — consuming it
    # would prevent Windows from ever starting its native caption-drag loop.
    assert handled is False


# ── Picking a bottom-snapped window back up halves its width ────────────────

def test_unsnapping_bottom_halves_width_and_keeps_cursor_ratio(window):
    window.show()
    window.title_bar._edge_snapped = True
    window.title_bar._snapped_to_bottom = True
    old_geo = window.geometry()
    # Grab it a quarter of the way across.
    grab_x = old_geo.left() + old_geo.width() // 4
    cursor = QPoint(grab_x, old_geo.top())

    window.title_bar._begin_drag_unsnapping_bottom(cursor)

    new_geo = window.geometry()
    assert new_geo.width() == max(window.minimumWidth(), old_geo.width() // 2)
    assert window.title_bar._edge_snapped is False
    assert window.title_bar._snapped_to_bottom is False
    # The cursor should still land at roughly the same fraction across the
    # (now narrower) window, not have the window's edge snap under it.
    new_ratio = (cursor.x() - new_geo.left()) / new_geo.width()
    assert abs(new_ratio - 0.25) < 0.05


def test_unsnapping_bottom_is_a_noop_when_not_bottom_snapped(window):
    window.show()
    window.title_bar._edge_snapped = True
    window.title_bar._snapped_to_bottom = False  # e.g. a left/right half-snap
    geo_before = window.geometry()

    window.title_bar._begin_drag_unsnapping_bottom(QPoint(geo_before.left(), geo_before.top()))

    assert window.geometry() == geo_before
    assert window.title_bar._edge_snapped is True  # untouched — not this method's snap to clear


def test_mouse_press_on_bottom_snapped_window_halves_width(window, monkeypatch):
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtCore import QEvent, Qt as _Qt

    window.show()
    window.title_bar._edge_snapped = True
    window.title_bar._snapped_to_bottom = True
    monkeypatch.setattr(window.title_bar, "is_drag_region", lambda pos: True)
    old_width = window.geometry().width()
    press_pos = QPoint(10, 10)

    event = QMouseEvent(QEvent.MouseButtonPress, press_pos, window.title_bar.mapToGlobal(press_pos),
                        _Qt.LeftButton, _Qt.LeftButton, _Qt.NoModifier)
    window.title_bar.mousePressEvent(event)

    assert window.geometry().width() < old_width
    assert window.title_bar._snapped_to_bottom is False


def test_native_caption_drag_start_halves_a_bottom_snapped_window(window):
    window.show()
    window.title_bar._edge_snapped = True
    window.title_bar._snapped_to_bottom = True
    old_geo = window.geometry()
    grab_x, grab_y = old_geo.left() + 20, old_geo.top() + 5
    lparam = ((grab_y & 0xFFFF) << 16) | (grab_x & 0xFFFF)

    _send(window, _WM_NCLBUTTONDOWN, wparam=_HTCAPTION, lparam=lparam)

    assert window.geometry().width() < old_geo.width()
    assert window.title_bar._snapped_to_bottom is False
