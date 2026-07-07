"""Windows 11 Snap Layouts on hover for the custom maximize button.

DWM shows the flyout automatically once WM_NCHITTEST answers HTMAXBUTTON
for the button's rect — nothing else to draw. But that also makes Windows
route input there as non-client messages instead of ordinary ones, so
NodeEditorWindow additionally has to: keep the button's own :hover paint in
sync (TitleBarWidget.set_max_button_native_hover), and perform the actual
maximize/restore toggle from WM_NCLBUTTONUP instead of the button's own
click signal, which never fires for a non-client-flagged rect.
"""
import ctypes
import os
from ctypes import wintypes

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QPoint

from ui.editor_window import _HTCAPTION, _HTMAXBUTTON, _WM_NCHITTEST


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD), ("pt", wintypes.POINT),
    ]


def _lparam_for(x: int, y: int) -> int:
    return (y & 0xFFFF) << 16 | (x & 0xFFFF)


def _hit_test_at(window, global_point: QPoint):
    msg = _MSG(hwnd=int(window.winId()), message=_WM_NCHITTEST, wParam=0,
              lParam=_lparam_for(global_point.x(), global_point.y()))
    return window._hit_test_native_message(ctypes.addressof(msg))


def _global_center_of(window, widget):
    return window.mapToGlobal(widget.mapTo(window, widget.rect().center()))


def test_hovering_the_maximize_button_reports_htmaxbutton(window):
    window.show()
    max_btn = window.title_bar.max_btn
    result = _hit_test_at(window, _global_center_of(window, max_btn))

    assert result == _HTMAXBUTTON
    assert max_btn.property("nativeHover") == "true"


def test_hovering_elsewhere_in_the_title_bar_does_not_report_htmaxbutton(window):
    window.show()
    min_btn = window.title_bar.min_btn
    result = _hit_test_at(window, _global_center_of(window, min_btn))

    assert result != _HTMAXBUTTON
    assert window.title_bar.max_btn.property("nativeHover") == "false"


def test_native_hover_clears_once_cursor_moves_off_the_button(window):
    window.show()
    max_btn = window.title_bar.max_btn
    _hit_test_at(window, _global_center_of(window, max_btn))
    assert max_btn.property("nativeHover") == "true"

    _hit_test_at(window, _global_center_of(window, window.title_bar.min_btn))
    assert max_btn.property("nativeHover") == "false"


def test_window_leave_event_clears_native_hover_as_a_safety_net(window):
    from PyQt5.QtCore import QEvent
    window.show()
    max_btn = window.title_bar.max_btn
    _hit_test_at(window, _global_center_of(window, max_btn))
    assert max_btn.property("nativeHover") == "true"

    window.leaveEvent(QEvent(QEvent.Leave))
    assert max_btn.property("nativeHover") == "false"


def test_nclbuttonup_on_maxbutton_toggles_maximize(window, monkeypatch):
    window.show()
    calls = []
    monkeypatch.setattr(window.title_bar, "_toggle_maximize", lambda: calls.append(1))

    msg = _MSG(hwnd=int(window.winId()), message=0x00A2, wParam=_HTMAXBUTTON, lParam=0)
    handled, result = window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))

    assert handled is True
    assert calls == [1]


def test_nclbuttondown_on_maxbutton_is_consumed_without_toggling(window, monkeypatch):
    window.show()
    calls = []
    monkeypatch.setattr(window.title_bar, "_toggle_maximize", lambda: calls.append(1))

    msg = _MSG(hwnd=int(window.winId()), message=0x00A1, wParam=_HTMAXBUTTON, lParam=0)
    handled, result = window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))

    assert handled is True
    assert calls == []


def test_drag_region_still_reports_htcaption_when_not_over_max_button(window):
    window.show()
    # An empty stretch of the title bar, away from any button/tab.
    point = window.title_bar.mapTo(window, QPoint(window.title_bar.width() - 2, 5))
    # Skip if that lands on a real child (narrow test window) — the point of
    # this test is a genuine drag-region hit, not a specific pixel.
    if window.title_bar.childAt(window.title_bar.mapFromGlobal(window.mapToGlobal(point))) is not None:
        return
    result = _hit_test_at(window, window.mapToGlobal(point))
    assert result in (_HTCAPTION, None)
