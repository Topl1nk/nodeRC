from __future__ import annotations

from PyQt5.QtWidgets import QScrollBar, QPushButton, QGraphicsView
from PyQt5.QtCore import Qt, QSize

from configuration import (
    SCROLLBAR_TOGGLE_BG, SCROLLBAR_TOGGLE_HOVER,
    SCROLLBAR_BTN_MARGIN, SCROLLBAR_BTN_OFFSET, SCROLLBAR_BTN_SIZE,
    SCROLLBAR_TOGGLE_SHOW_GLYPH, SCROLLBAR_TOGGLE_HIDE_GLYPH,
    CANVAS_SCROLLBAR_EDGE_MARGIN,
    SCROLLBAR_HANDLE_COLOR, SCROLLBAR_HANDLE_ACTIVE_COLOR, SCROLLBAR_TRACK_COLOR,
)
from localization import t


class UnifiedScrollBar(QScrollBar):
    """Single scrollbar class used everywhere in the application.

    Standalone use (side panels, search tree):
        sb = UnifiedScrollBar()          # vertical
        scroll_area.setVerticalScrollBar(sb)

    Canvas use — installs a matched vbar/hbar pair + visibility toggle button:
        mgr = UnifiedScrollBar.install_on_view(view)
        # mgr  IS the vertical scrollbar (QScrollBar)
        # mgr.vbar        → itself
        # mgr.hbar        → the horizontal partner
        # mgr.toggle_btn  → QPushButton for show/hide
        # mgr.on_view_resize()          — call from GraphicsView.resizeEvent
        # mgr.toggle_scrollbar_visibility()

    Why one class:
        vbar and hbar are identical in behaviour — same styling, same sizeHint
        logic, same hover handling.  Separating them into a manager wrapper
        class adds indirection with no benefit.  The vbar instance itself
        carries the manager state as plain attributes set by install_on_view.

    Critical: do NOT call setGeometry() on an instance that lives inside a
    QAbstractScrollArea.  Qt's layoutChildren() / updateScrollBars() must be
    the sole authority over scrollbar geometry; external setGeometry() calls
    desync the viewport size and cause the scroll range to compute as zero —
    the draggable thumb vanishes even when the scene content overflows.
    """

    # ── Construction ───────────────────────────────────────────────────────────

    def __init__(self, orientation=Qt.Vertical, edge_margin: int = 0, parent=None):
        super().__init__(orientation, parent)
        self.edge_margin = edge_margin
        self.setCursor(Qt.ArrowCursor)
        self._hovered = False
        self._apply_style()

        # Manager-mode attributes — populated by install_on_view on the vbar.
        # Left as None on standalone instances so attribute errors fail loudly
        # if someone accidentally calls manager methods on a plain scrollbar.
        self.vbar: UnifiedScrollBar | None = None
        self.hbar: UnifiedScrollBar | None = None
        self.toggle_btn: QPushButton | None = None
        self.scrollbars_visible: bool = True
        self._managed_view: QGraphicsView | None = None

    # ── Canvas factory ─────────────────────────────────────────────────────────

    @classmethod
    def install_on_view(cls, view: QGraphicsView) -> UnifiedScrollBar:
        """Install a matched pair of scrollbars on *view* and wire the toggle
        button.  Returns the vertical scrollbar instance which also carries all
        manager state — store it as ``view._scrollbar_manager``.

        Qt remains the sole authority over scrollbar geometry (no setGeometry
        is called on the bars); only the floating toggle button is repositioned
        in on_view_resize().
        """
        vbar = cls(Qt.Vertical, edge_margin=CANVAS_SCROLLBAR_EDGE_MARGIN, parent=view)
        hbar = cls(Qt.Horizontal, edge_margin=CANVAS_SCROLLBAR_EDGE_MARGIN, parent=view)

        view.setVerticalScrollBar(vbar)
        view.setHorizontalScrollBar(hbar)

        # Wire manager state onto the vbar instance.
        vbar.vbar = vbar  # self-ref so callers can always write mgr.vbar
        vbar.hbar = hbar
        vbar._managed_view = view

        # Closed by default (ст. 0.2), same as the Project Inputs panel —
        # the canvas starts uncluttered; the toggle button reveals scrollbars
        # on demand rather than showing them before anyone asked.
        vbar.scrollbars_visible = False
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        btn = QPushButton(SCROLLBAR_TOGGLE_SHOW_GLYPH, view)
        btn.setFixedSize(SCROLLBAR_BTN_SIZE, SCROLLBAR_BTN_SIZE)
        btn.setToolTip(t("tooltip_toggle_scrollbars"))
        btn.setStyleSheet(f"""
            QPushButton {{
                background:{SCROLLBAR_TOGGLE_BG};color:white;
                border:none;border-radius:4px;font-size:13px;
            }}
            QPushButton:hover{{background:{SCROLLBAR_TOGGLE_HOVER};}}
        """)
        btn.clicked.connect(vbar.toggle_scrollbar_visibility)
        vbar.toggle_btn = btn

        return vbar

    # ── Manager methods (only meaningful on the vbar returned by install_on_view)

    def on_view_resize(self) -> None:
        """Reposition the toggle button; scrollbar geometry is Qt's job."""
        btn = self.toggle_btn
        if btn is None:
            return
        pad = SCROLLBAR_BTN_MARGIN + SCROLLBAR_BTN_OFFSET
        view = self._managed_view
        btn.move(view.width() - btn.width() - pad,
                 view.height() - btn.height() - pad)
        btn.raise_()

    def toggle_scrollbar_visibility(self) -> None:
        self.scrollbars_visible = not self.scrollbars_visible
        view = self._managed_view
        policy = Qt.ScrollBarAsNeeded if self.scrollbars_visible else Qt.ScrollBarAlwaysOff
        view.setHorizontalScrollBarPolicy(policy)
        view.setVerticalScrollBarPolicy(policy)
        self.toggle_btn.setText(
            SCROLLBAR_TOGGLE_HIDE_GLYPH if self.scrollbars_visible
            else SCROLLBAR_TOGGLE_SHOW_GLYPH
        )

    # Track width/height — constant, never varies with hover (see class
    # docstring: an external geometry change on a QAbstractScrollArea-managed
    # scrollbar desyncs the scroll range and shifts the thumb along the track).
    _TRACK_SIZE = 8

    # ── Size hint ──────────────────────────────────────────────────────────────

    def sizeHint(self) -> QSize:
        orig = super().sizeHint()
        if self.orientation() == Qt.Vertical:
            return QSize(self._TRACK_SIZE, orig.height())
        return QSize(orig.width(), self._TRACK_SIZE)

    # ── Hover (color only — thickness never changes, see _TRACK_SIZE) ──────────

    def enterEvent(self, event):
        self._hovered = True
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._apply_style()
        super().leaveEvent(event)

    # ── Stylesheet ─────────────────────────────────────────────────────────────

    def _apply_style(self):
        handle = SCROLLBAR_HANDLE_ACTIVE_COLOR if self._hovered else SCROLLBAR_HANDLE_COLOR
        # Inset the groove from the view's top/bottom (vertical) or
        # left/right (horizontal) edge — a QSS margin on the scrollbar's own
        # box model, not setGeometry (see class docstring: setGeometry on a
        # QAbstractScrollArea-managed scrollbar desyncs the scroll range).
        if self.orientation() == Qt.Vertical:
            track_margin = f"margin-top: {self.edge_margin}px; margin-bottom: {self.edge_margin}px;"
        else:
            track_margin = f"margin-left: {self.edge_margin}px; margin-right: {self.edge_margin}px;"
        self.setStyleSheet(f"""
            QScrollBar {{
                border: none;
                background: {SCROLLBAR_TRACK_COLOR};
                width: {self._TRACK_SIZE}px;
                height: {self._TRACK_SIZE}px;
                {track_margin}
            }}
            QScrollBar::handle {{
                background: {handle};
                min-width: 20px;
                min-height: 20px;
                border-radius: 0px;
            }}
            QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
        """)


# Back-compat alias — old imports of CanvasScrollBarManager still resolve.
CanvasScrollBarManager = UnifiedScrollBar
