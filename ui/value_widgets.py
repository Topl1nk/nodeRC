"""value_widgets.py — Shared Value-Editor Primitives

The literal widgets a node body embeds for its fields (ui/param_nodes.py's
ParamNode._make_field/_make_checkbox/_make_spinbox/_make_combobox) and the
ones the Project Inputs panel's rows use (ui/project_inputs_panel.py) are the
same construction — same QSS, same height, same widget class — so there is
exactly one place that knows what a "string field" or a "bool checkbox" looks
like (ст.1.1). ParamNode's methods are thin per-node wrappers that just supply
the node's own preferred width; the panel calls these functions directly with
its own fixed width, so both stay pixel-identical without a second
implementation to drift out of sync.
"""
from __future__ import annotations

from typing import List, Optional

from PyQt5.QtWidgets import QAbstractSpinBox, QComboBox, QLineEdit, QSpinBox
from PyQt5.QtGui import QColor, QPalette

from configuration import NODE_WIDGET_HEIGHT, TEXT_COLOR
from ui.theme import COMBOBOX_QSS, FIELD_QSS, SPINBOX_QSS, apply_field_placeholder_palette
from ui.widgets import InsetFillCheckBox


def build_text_field(text: str = "", placeholder: str = "", *,
                     width: Optional[int] = None) -> QLineEdit:
    w = QLineEdit(text)
    if placeholder:
        w.setPlaceholderText(placeholder)
    if width is not None:
        w.setFixedWidth(width)
    w.setFixedHeight(NODE_WIDGET_HEIGHT)
    w.setStyleSheet(FIELD_QSS)
    apply_field_placeholder_palette(w)
    return w


def build_checkbox(text: str = "true", checked: bool = False, *,
                   width: Optional[int] = None) -> InsetFillCheckBox:
    w = InsetFillCheckBox(text)
    w.setChecked(checked)
    if width is not None:
        w.setFixedWidth(width)
    w.setFixedHeight(NODE_WIDGET_HEIGHT)
    return w


def build_spinbox(lo: int = -999999, hi: int = 999999, value: int = 0, *,
                  width: Optional[int] = None) -> QSpinBox:
    w = QSpinBox()
    # Native up/down arrows paint inside the widget's own border; every
    # embedded field in this app uses its own external stepper instead (see
    # ParamNode._make_stepper) — this box just omits them for the compact
    # panel row, where there's no room for a second control anyway.
    w.setButtonSymbols(QAbstractSpinBox.NoButtons)
    w.setRange(lo, hi)
    w.setValue(value)
    if width is not None:
        w.setFixedWidth(width)
    w.setFixedHeight(NODE_WIDGET_HEIGHT)
    w.setStyleSheet(SPINBOX_QSS)
    apply_field_placeholder_palette(w)
    pal = w.palette()
    pal.setColor(QPalette.ButtonText, QColor(TEXT_COLOR))
    w.setPalette(pal)
    return w


def build_combobox(owner, items: Optional[List[str]] = None, *, placeholder: str = "",
                   width: Optional[int] = None, editable: bool = True) -> QComboBox:
    from ui.graph_items import NodeComboBox
    w = NodeComboBox(owner)
    w.setEditable(editable)
    for item in (items or []):
        w.addItem(item)
    if placeholder and w.lineEdit():
        # See ParamNode._make_combobox for why the palette patch below must
        # come before this setPlaceholderText call, not after.
        w.lineEdit().setPlaceholderText(placeholder)
    if width is not None:
        w.setFixedWidth(width)
    w.setFixedHeight(NODE_WIDGET_HEIGHT)
    w.setStyleSheet(COMBOBOX_QSS)
    apply_field_placeholder_palette(w)
    pal = w.palette()
    pal.setColor(QPalette.ButtonText, QColor(TEXT_COLOR))
    w.setPalette(pal)
    return w
