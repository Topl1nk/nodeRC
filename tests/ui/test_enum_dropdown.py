"""Three [E] Enum node dropdown bugs, all rooted in how its popup/buttons
interact with mechanisms built for the ordinary embedded-widget case:

1. QComboBox.setView() silently resets the view's own scrollbar policy to
   ScrollBarAlwaysOff, clobbering the ScrollBarAsNeeded set just before it
   (NodeComboBox.__init__, ui/graph_items.py) — a long list opened with no
   scrollbar at all.
2. An open combo popup is a floating widget on top of the canvas, not a
   scene item under the cursor — GraphicsView.wheelEvent's item lookup can
   never see it, so wheel-over-the-list fell through to canvas zoom instead
   of scrolling. Two Qt-native detection attempts (activePopupWidget(),
   widgetAt()) both proved unreliable in the live app; GraphicsView now
   tracks which combo's popup is open itself (register_open_popup/
   unregister_open_popup, called from NodeComboBox.showPopup/hidePopup) and
   computes the popup's real screen rect directly, with no dependency on
   which native window the OS decided to route the wheel message to.
3. The "+"/"-" buttons are NoFocus QToolButtons swept into ParamNode's
   linked-editing focus tracker (_watch_field_focus) — that mechanism enters
   on MouseButtonPress but only ever exits on a later FocusOut, which a
   NoFocus widget can never emit, leaving the selection wash lit forever
   after a click (ui/param_nodes.py).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtWidgets import QApplication


def _enum_node(window, n=30):
    values = [f"option{i}" for i in range(n)]
    return window.add_param_node(QPointF(0, 0), {"param_type": "enum", "display": "E", "values": values})


def test_enum_popup_scrollbar_policy_survives_setview(window):
    node = _enum_node(window)
    combo = node._combobox
    assert combo.view().verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded


def test_enum_popup_scrollbar_is_visible_when_list_overflows(window):
    node = _enum_node(window)
    combo = node._combobox
    combo.showPopup()
    sb = combo.view().verticalScrollBar()
    assert sb.isVisible() is True
    assert sb.maximum() > 0


def test_short_enum_list_has_no_scrollbar(window):
    node = _enum_node(window, n=3)
    combo = node._combobox
    combo.showPopup()
    sb = combo.view().verticalScrollBar()
    assert sb.maximum() == 0


def _spy_events(widget):
    """A QObject eventFilter goes through Qt's real C++ dispatch (unlike
    monkeypatching .event(), which a sip-wrapped widget's C++ vtable calls
    never see), so it reliably observes what sendEvent actually delivered."""
    from PyQt5.QtCore import QObject

    class _Spy(QObject):
        def __init__(self):
            super().__init__()
            self.received = []

        def eventFilter(self, obj, event):
            self.received.append(event.type())
            return False

    spy = _Spy()
    widget.installEventFilter(spy)
    return spy


def test_showing_the_popup_registers_it_with_the_view(window):
    node = _enum_node(window)
    combo = node._combobox
    assert window.view._open_popup_combo is None

    combo.showPopup()
    assert window.view._open_popup_combo is combo

    combo.hidePopup()
    assert window.view._open_popup_combo is None


def test_wheel_over_open_popup_scrolls_it_not_the_canvas(window):
    node = _enum_node(window)
    combo = node._combobox
    combo.showPopup()
    popup_view = combo.view()
    viewport = popup_view.viewport()
    zoom_before = window.view.transform().m11()
    spy = _spy_events(viewport)

    global_pos = popup_view.mapToGlobal(QPoint(5, 5))
    wheel = QWheelEvent(
        QPoint(5, 5), global_pos,
        QPoint(0, 0), QPoint(0, -240),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )
    window.view.wheelEvent(wheel)

    assert window.view.transform().m11() == zoom_before  # canvas did not zoom
    assert QEvent.Wheel in spy.received                  # the list's viewport actually got it


def test_wheel_at_the_lists_scroll_limit_still_does_not_zoom(window):
    node = _enum_node(window)
    combo = node._combobox
    combo.showPopup()
    popup_view = combo.view()
    sb = popup_view.verticalScrollBar()
    sb.setValue(sb.minimum())  # already scrolled all the way to the top
    zoom_before = window.view.transform().m11()

    # QAbstractScrollArea.wheelEvent ignores (doesn't accept) a wheel event
    # that tries to scroll past the limit — this must not be read as "the
    # popup didn't want it" and fall through to canvas zoom.
    global_pos = popup_view.mapToGlobal(QPoint(5, 5))
    wheel = QWheelEvent(
        QPoint(5, 5), global_pos,
        QPoint(0, 0), QPoint(0, 240),  # scroll further up, past the top
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )
    window.view.wheelEvent(wheel)

    assert window.view.transform().m11() == zoom_before
    assert sb.value() == sb.minimum()


def test_wheel_outside_the_open_popups_rect_still_zooms_canvas(window):
    node = _enum_node(window)
    combo = node._combobox
    combo.showPopup()
    zoom_before = window.view.transform().m11()

    # Registered as open, but the cursor is nowhere near its actual rect —
    # must not blanket-forward every wheel event just because *some* combo
    # somewhere has its popup open.
    far_away = window.view.mapToGlobal(QPoint(-9999, -9999))
    wheel = QWheelEvent(
        QPoint(-9999, -9999), far_away,
        QPoint(0, 0), QPoint(0, 240),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )
    window.view.wheelEvent(wheel)

    assert window.view.transform().m11() != zoom_before


def test_wheel_without_open_popup_still_zooms_canvas(window):
    node = window.add_param_node(QPointF(-5000, -5000), {"param_type": "string", "display": "s"})
    zoom_before = window.view.transform().m11()

    wheel = QWheelEvent(
        QPoint(1, 1), window.view.mapToGlobal(QPoint(1, 1)),
        QPoint(0, 0), QPoint(0, 240),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )
    window.view.wheelEvent(wheel)

    assert window.view.transform().m11() != zoom_before


def test_stale_popup_registration_is_cleared_once_noticed(window):
    node = _enum_node(window)
    combo = node._combobox
    combo.showPopup()
    combo.hidePopup()
    # hidePopup already unregisters cleanly, but wheelEvent must also
    # tolerate a registration nobody explicitly cleared (e.g. the node was
    # torn down mid-interaction) rather than forwarding into a dead popup.
    window.view._open_popup_combo = combo
    zoom_before = window.view.transform().m11()

    wheel = QWheelEvent(
        QPoint(1, 1), window.view.mapToGlobal(QPoint(1, 1)),
        QPoint(0, 0), QPoint(0, 240),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )
    window.view.wheelEvent(wheel)

    assert window.view.transform().m11() != zoom_before
    assert window.view._open_popup_combo is None


def test_add_remove_buttons_are_not_watched_for_linked_editing(window):
    node = window.add_param_node(QPointF(0, 0), {"param_type": "enum", "display": "E", "values": ["a", "b"]})
    assert node._add_btn.focusPolicy() == Qt.NoFocus
    assert node._remove_btn.focusPolicy() == Qt.NoFocus

    calls = []
    original = node.eventFilter
    node.eventFilter = lambda obj, event: calls.append(obj) or original(obj, event)

    press = QEvent(QEvent.MouseButtonPress)
    QApplication.sendEvent(node._add_btn, press)

    # Qt only invokes eventFilter on objects that actually had it installed —
    # if _add_btn were still tracked, sending it a press would show up here.
    assert node._add_btn not in calls


def test_enum_add_button_click_never_leaves_the_selection_wash_stuck(window):
    node = window.add_param_node(QPointF(0, 0), {"param_type": "enum", "display": "E", "values": ["a", "b"]})
    node.setSelected(True)

    press = QEvent(QEvent.MouseButtonPress)
    QApplication.sendEvent(node._add_btn, press)
    node._add_enum_item()

    # A real click never enters linked-editing for this button in the first
    # place (previous test), so there's nothing left to dissolve — the group
    # stays empty rather than permanently holding this node.
    win = window
    assert node not in win._linked_group
