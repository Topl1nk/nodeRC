from __future__ import annotations

import sys

from PyQt5.QtCore import QPoint

from configuration import DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND
from diagnostics import log_and_explain


def extend_frame_into_client_area(widget) -> None:
    """Tell DWM the glass frame is extended across the *entire* client area.
    No-op off Windows.

    Why: we keep WS_CAPTION (via window flags) so Aero snap/native resize still
    work, and hide its visuals with WM_NCCALCSIZE. But WM_NCCALCSIZE only
    affects normal paint/hit-testing — DWM's own compositor-level effects (the
    minimize/restore genie animation, Aero Peek) still treat the window as
    having a real native caption unless explicitly told otherwise, and briefly
    paint a blank rectangle in our caption color where the tab strip should be.
    Extending the frame margins to (-1,-1,-1,-1) makes DWM treat the whole
    window as already-extended frame, so it stops drawing its own caption
    during those effects.
    """
    if sys.platform != "win32":
        return
    try:
        from ctypes import windll, byref, Structure, c_int

        class MARGINS(Structure):
            _fields_ = [("cxLeftWidth", c_int), ("cxRightWidth", c_int),
                        ("cyTopHeight", c_int), ("cyBottomHeight", c_int)]

        hwnd = int(widget.winId())
        margins = MARGINS(-1, -1, -1, -1)
        windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, byref(margins))
    except Exception as exc:
        log_and_explain("Failed to extend DWM frame into client area", exc)


def apply_rounded_corners(widget, preference: int = DWMWCP_ROUND) -> None:
    """Set the native Windows 11 window corner style explicitly. No-op off
    Windows.

    Why: we keep WS_CAPTION (via window flags) for Aero snap/native resize,
    which normally makes DWM round the corners and auto-square them while
    maximized on its own. But Qt's showMaximized() never gives the window a
    real Win32 WS_MAXIMIZE style (see title_bar.py), so DWM can't reliably
    detect "this window is maximized" itself — it can keep rounding corners
    that are now sitting exactly on the monitor edge, clipping the content
    under them. Callers explicitly pass DWMWCP_DONOTROUND while maximized to
    compensate.
    """
    if sys.platform != "win32":
        return
    try:
        from ctypes import windll, byref, sizeof, c_int
        hwnd = int(widget.winId())
        pref = c_int(preference)
        windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, byref(pref), sizeof(pref))
    except Exception as exc:
        log_and_explain("Window corner rounding unavailable", exc)


def restore_without_animation(widget) -> None:
    """Call showNormal() with Windows' minimize/restore "genie" animation
    suppressed for just this one transition. No-op (plain showNormal()) off
    Windows.

    Why: TitleBarWidget manually restores-and-drags a maximized frameless
    window (see _native_drag_handles_this() in title_bar.py) because Windows'
    own restore-to-cursor gesture never fires for it. But ShowWindow(SW_
    SHOWNORMAL) still plays the system's animated maximize/restore transition
    (SPI_GETANIMATION) when going from maximized to normal, and DWM owns the
    window's position for that transition's duration — our immediately-
    following move() calls get silently dropped until the animation finishes,
    so the window appears to snap to the animation's resting spot (roughly
    centered under where the drag started) instead of tracking the cursor.
    Temporarily flipping ANIMATIONINFO.iMinAnimate off around the call skips
    that animation so our own move() takes effect on every frame.
    """
    if sys.platform != "win32":
        widget.showNormal()
        return
    try:
        from ctypes import windll, byref, sizeof, Structure, c_uint, c_int, c_bool

        class ANIMATIONINFO(Structure):
            _fields_ = [("cbSize", c_uint), ("iMinAnimate", c_int)]

        SPI_GETANIMATION, SPI_SETANIMATION = 0x0048, 0x0049
        SPIF_SENDCHANGE = 0x2

        info = ANIMATIONINFO(sizeof(ANIMATIONINFO), 0)
        windll.user32.SystemParametersInfoW(SPI_GETANIMATION, sizeof(info), byref(info), 0)
        original_animate = info.iMinAnimate

        if original_animate:
            info.iMinAnimate = 0
            windll.user32.SystemParametersInfoW(SPI_SETANIMATION, sizeof(info), byref(info), 0)

        try:
            widget.showNormal()
        finally:
            if original_animate:
                info.iMinAnimate = original_animate
                windll.user32.SystemParametersInfoW(SPI_SETANIMATION, sizeof(info), byref(info), 0)
    except Exception as exc:
        log_and_explain("Failed to suppress restore animation", exc)
        widget.showNormal()


def handoff_to_native_caption_drag(widget) -> bool:
    """Release Qt's mouse grab and tell Windows to take over the rest of the
    current drag as if the user had pressed down on a real native caption.
    Returns True if the handoff was issued. No-op (returns False) off Windows.

    Why: TitleBarWidget drives a maximized-window drag manually (see
    _native_drag_handles_this() in title_bar.py) because the native "restore
    to cursor" gesture desyncs for a frameless window while it's still
    maximized. But driving the *entire* rest of the gesture manually never
    engages Aero edge-snap (or its preview guides) for the rest of that drag,
    since those live entirely inside Windows' own WM_NCLBUTTONDOWN/HTCAPTION
    move loop. Once the window has been restored to normal size/position (by
    the caller, right before this is invoked), handing the remainder of the
    drag to that loop gets snap + guides back, same as a normal native
    caption drag.

    Reads the cursor position with GetCursorPos (real physical screen
    pixels) rather than a Qt QPoint: Qt's own coordinates are DPI-scaled
    logical pixels whenever high-DPI scaling is active, and WM_NCLBUTTONDOWN's
    lParam needs physical ones — passing logical coordinates desynced the
    drag anchor by the scale factor, visibly trailing the cursor for the
    rest of the drag.
    """
    if sys.platform != "win32":
        return False
    try:
        from ctypes import windll, wintypes, byref

        hwnd = int(widget.winId())
        windll.user32.ReleaseCapture()

        pt = wintypes.POINT()
        windll.user32.GetCursorPos(byref(pt))

        WM_NCLBUTTONDOWN = 0x00A1
        HTCAPTION = 2
        lparam = (pt.y << 16) | (pt.x & 0xFFFF)
        windll.user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, lparam)
        return True
    except Exception as exc:
        log_and_explain("Failed to hand drag off to native caption move", exc)
        return False


def show_system_menu(widget, global_pos: QPoint) -> None:
    """Trigger the OS native window system menu (Restore, Move, Size, Minimize,
    Maximize, Close) at the given screen coordinates. No-op off Windows.
    
    Why: A custom frameless window loses the native title bar right-click and
    Alt+Space system menus. Calling TrackPopupMenu on the native system menu
    and routing commands to the window message queue brings this back seamlessly.
    """
    if sys.platform != "win32":
        return
    try:
        from ctypes import windll
        hwnd = int(widget.winId())
        hmenu = windll.user32.GetSystemMenu(hwnd, False)
        if not hmenu:
            return

        is_max = widget.isMaximized()
        is_min = widget.isMinimized()

        # Update enabled/disabled states of default items to match the current window state:
        # SC_RESTORE = 0xF120, SC_MOVE = 0xF010, SC_SIZE = 0xF000, SC_MINIMIZE = 0xF020, SC_MAXIMIZE = 0xF030
        # MF_ENABLED = 0x00000000, MF_GRAYED = 0x00000001
        user32 = windll.user32
        user32.EnableMenuItem(hmenu, 0xF120, 0x00000000 if (is_max or is_min) else 0x00000001)
        user32.EnableMenuItem(hmenu, 0xF010, 0x00000001 if is_max else 0x00000000)
        user32.EnableMenuItem(hmenu, 0xF000, 0x00000001 if is_max else 0x00000000)
        user32.EnableMenuItem(hmenu, 0xF020, 0x00000001 if is_min else 0x00000000)
        user32.EnableMenuItem(hmenu, 0xF030, 0x00000001 if is_max else 0x00000000)

        # TPM_LEFTALIGN = 0x0000, TPM_RIGHTBUTTON = 0x0002
        user32.TrackPopupMenu(hmenu, 0x0002, global_pos.x(), global_pos.y(), 0, hwnd, None)
    except Exception as exc:
        log_and_explain("Failed to show native system menu", exc)


def hex_to_colorref(hex_str: str) -> int:
    """Convert CSS hex color string to Win32 COLORREF format (0x00BBGGRR)."""
    hex_str = hex_str.lstrip('#')
    r = int(hex_str[0:2], 16)
    g = int(hex_str[2:4], 16)
    b = int(hex_str[4:6], 16)
    return (b << 16) | (g << 8) | r


def apply_immersive_dark_mode(widget) -> None:
    """Force Windows DWM to treat the window frame as dark mode and color the
    native caption/border to match our theme.
    
    Why: During window transitions (minimize, restore, snapping), Windows temporarily
    redraws the native frame (non-client area). If not styled dark, a bright white
    flash or title bar strip is visible during these animations.
    """
    if sys.platform != "win32":
        return
    try:
        from ctypes import windll, byref, sizeof, c_int, c_bool
        hwnd = int(widget.winId())
        dwmapi = windll.dwmapi

        # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 (Windows 10 20H1+ and Windows 11), 19 (Windows 10 before 20H1)
        enabled = c_bool(True)
        dwmapi.DwmSetWindowAttribute(hwnd, 20, byref(enabled), sizeof(enabled))
        dwmapi.DwmSetWindowAttribute(hwnd, 19, byref(enabled), sizeof(enabled))

        # The real native caption is supposed to be fully hidden by the
        # WM_NCCALCSIZE hack (see extend_frame_into_client_area), but at a
        # rounded corner DWM's own clip still leaks a few caption-colored
        # pixels through the curve. Matching it to WINDOW_BORDER_COLOR (what
        # visually surrounds that corner everywhere else) makes the leak
        # blend in instead of showing up as a mismatched fleck of
        # WINDOW_BACKGROUND_COLOR.
        from configuration import WINDOW_BORDER_COLOR
        caption_val = c_int(hex_to_colorref(WINDOW_BORDER_COLOR))
        border_val = c_int(hex_to_colorref(WINDOW_BORDER_COLOR))

        # DWMWA_BORDER_COLOR = 34
        dwmapi.DwmSetWindowAttribute(hwnd, 34, byref(border_val), sizeof(border_val))
        # DWMWA_CAPTION_COLOR = 35
        dwmapi.DwmSetWindowAttribute(hwnd, 35, byref(caption_val), sizeof(caption_val))
    except Exception as exc:
        log_and_explain("Failed to apply immersive dark mode", exc)
