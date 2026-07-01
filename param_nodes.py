"""param_nodes.py — Parameter Value Nodes

ParamNode owns everything common to a value-producing node: embedded editor
construction, connected-input mirroring, linked mass-editing of same-type
selections, and the value (de)serialization contract. The concrete classes map
each RealityCapture parameter type onto its editor widgets.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from PyQt5.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QApplication, QCheckBox, QComboBox,
    QFileDialog, QGraphicsItem, QGraphicsProxyWidget, QHBoxLayout, QLabel,
    QLineEdit, QSpinBox, QToolButton, QWidget,
)
from PyQt5.QtGui import QColor, QDoubleValidator, QPalette
from PyQt5.QtCore import QEvent, Qt, QTimer

from localization import t
from configuration import (
    NODE_HEADER_HEIGHT, NODE_ROW_HEIGHT, NODE_HORIZONTAL_PAD,
    NODE_WIDGET_V_OFFSET, NODE_WIDGET_HEIGHT, NODE_LINKED_FIELD_Z,
    NODE_WIDGET_Z_BASE, BROWSE_BTN_WIDTH, TEXT_COLOR,
)
from theme import (
    FIELD_QSS, COMBOBOX_QSS, SPINBOX_QSS, TOOLBTN_QSS, VECTOR_AXIS_LABEL_QSS,
)
from node_blueprint import (
    NodeDef, SocketDef, html_title, param_node_def, resolve_color_schema,
)
from graph_items import MetaNode, NodeComboBox, editor_window_of
from inset_fill_checkbox import InsetFillCheckBox
from diagnostics import log_and_explain


class ParamNode(MetaNode):
    supports_plain_rename = True

    def __init__(self, node_def: NodeDef):
        super().__init__(node_def)
        self._update_scheduled = False

    def serialize_payload(self) -> dict:
        return {
            "creation_data": getattr(self, "creation_data",
                                     {"param_type": self.TYPE_ID, "display": self.TYPE_ID}),
            "current_value": self.get_value_state(),
        }

    def _on_renamed(self, name: str):
        creation_data = dict(getattr(self, "creation_data", {}) or {})
        creation_data.setdefault("param_type", self.TYPE_ID)
        creation_data["display"] = name
        self.creation_data = creation_data

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._begin_rename()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.ItemSceneHasChanged and not self._update_scheduled:
            self._update_scheduled = True
            QTimer.singleShot(100, self._on_scene_loaded)
        return result

    def _on_scene_loaded(self):
        self._update_scheduled = False
        self._update_connected_values()

    # ── Embedded editor construction ──────────────────────────────────────────

    def _widget_width(self) -> int:
        return self.node_def.width - NODE_HORIZONTAL_PAD * 2 - 4

    def _make_field(self, text: str = "", placeholder: str = "", *,
                    fixed_width: bool = True) -> QLineEdit:
        w = QLineEdit(text)
        if placeholder:
            w.setPlaceholderText(placeholder)
        if fixed_width:
            w.setFixedWidth(self._widget_width())
        w.setFixedHeight(NODE_WIDGET_HEIGHT)
        w.setStyleSheet(FIELD_QSS)
        return w

    def _make_combobox(self, items: List[str] = None, *,
                       fixed_width: bool = True, editable: bool = True) -> QComboBox:
        w = NodeComboBox(self)
        w.setEditable(editable)
        for item in (items or []):
            w.addItem(item)
        if fixed_width:
            w.setFixedWidth(self._widget_width())
        w.setFixedHeight(NODE_WIDGET_HEIGHT)
        w.setStyleSheet(COMBOBOX_QSS)
        pal = w.palette()
        pal.setColor(QPalette.ButtonText, QColor(TEXT_COLOR))
        w.setPalette(pal)
        return w

    def _make_spinbox(self, lo: int = -999999, hi: int = 999999,
                      value: int = 0) -> QSpinBox:
        w = QSpinBox()
        w.setRange(lo, hi)
        w.setValue(value)
        w.setFixedWidth(self._widget_width())
        w.setFixedHeight(NODE_WIDGET_HEIGHT)
        w.setStyleSheet(SPINBOX_QSS)
        pal = w.palette()
        pal.setColor(QPalette.ButtonText, QColor(TEXT_COLOR))
        w.setPalette(pal)
        return w

    def _make_checkbox(self, text: str = "true", checked: bool = False) -> QCheckBox:
        w = InsetFillCheckBox(text)
        w.setChecked(checked)
        w.setFixedWidth(self._widget_width())
        w.setFixedHeight(NODE_WIDGET_HEIGHT)
        return w

    def _make_toolbtn(self, text: str, callback=None) -> QToolButton:
        w = QToolButton()
        w.setText(text)
        w.setStyleSheet(TOOLBTN_QSS)
        w.setFixedWidth(BROWSE_BTN_WIDTH)
        w.setFixedHeight(NODE_WIDGET_HEIGHT)
        if callback:
            w.clicked.connect(callback)
        return w

    def _attach_widget_at_row(self, widget: QWidget, row: int):
        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(widget)
        proxy.setPos(
            NODE_HORIZONTAL_PAD,
            NODE_HEADER_HEIGHT + row * NODE_ROW_HEIGHT + NODE_WIDGET_V_OFFSET,
        )
        proxy.setZValue(NODE_WIDGET_Z_BASE - row)
        proxy._field_key = f"row_{row}"
        self._watch_field_focus(widget)

    def _attach_input_widget(self, widget: QWidget):
        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(widget)
        param_rows = [s.row for s in self.node_def.sockets if not s.is_exec]
        rows = max(param_rows, default=-1) + 1
        proxy.setPos(
            NODE_HORIZONTAL_PAD,
            NODE_HEADER_HEIGHT + rows * NODE_ROW_HEIGHT + NODE_WIDGET_V_OFFSET,
        )
        proxy.setZValue(NODE_WIDGET_Z_BASE - rows)
        proxy._field_key = f"row_{rows}"
        self._watch_field_focus(widget)

    # ── Connected-input mirroring ─────────────────────────────────────────────

    def _get_connected_input_value(self, socket_name: str) -> Optional[str]:
        sock = self.get_socket(socket_name)
        win = editor_window_of(self)
        if not sock or not win:
            return None
        for conn in win.connections:
            if conn.dest is sock:
                return conn.source.meta_node.get_value(conn.source.sock_def.name)
        return None

    def _show_connected_value(self, line_edit: QLineEdit, value: Optional[str]):
        if value:
            line_edit.blockSignals(True)
            line_edit.setText(value)
            line_edit.setReadOnly(True)
            line_edit.blockSignals(False)
        else:
            line_edit.setReadOnly(False)

    def _show_connected_combobox(self, combo: QComboBox, value: Optional[str]):
        if value:
            combo.blockSignals(True)
            combo.setCurrentText(value)
            if combo.lineEdit():
                combo.lineEdit().setReadOnly(True)
            combo.setFocusPolicy(Qt.NoFocus)
            combo.setProperty("connected", "true")
            combo.style().unpolish(combo)
            combo.style().polish(combo)
            combo.blockSignals(False)
        else:
            if combo.lineEdit():
                combo.lineEdit().setReadOnly(False)
            combo.setFocusPolicy(Qt.StrongFocus)
            combo.setProperty("connected", "false")
            combo.style().unpolish(combo)
            combo.style().polish(combo)

    def _notify_connections_changed(self, *args):
        self._propagate_connections_changed(set())
        self._broadcast_to_linked_peers()

    # ── Linked mass-editing ───────────────────────────────────────────────────
    #
    # 1. Linked Grouping: Clicking any parameter widget (QLineEdit, QComboBox,
    #    etc.) gathers all selected parameter nodes of the same type into
    #    ``win._linked_group``.
    # 2. Pre-Click Selection Tracking: By default, clicking a widget triggers a
    #    deselection pass in QGraphicsScene before focus is established. To
    #    counter this, NodeScene stores the pre-click selection state in
    #    ``scene._pre_click_selection``, letting ``_enter_linked_editing``
    #    reconstruct the full group correctly.
    # 3. Visual Wash Overlay: All selected/linked nodes show the translucent
    #    _SelectionOverlay above their body.
    # 4. Field Key Isolation: only the actively edited field matches
    #    ``win._active_field_key``; its proxy is raised to NODE_LINKED_FIELD_Z so
    #    it paints above the wash — the haze lifts only from the active input.
    # 5. Inactive fields and peer nodes keep their original Z-values, staying
    #    under the wash as expected.

    _broadcasting: bool = False

    def _watch_field_focus(self, widget: QWidget):
        for w in (widget, *widget.findChildren(QWidget)):
            if isinstance(w, (QLineEdit, QComboBox, QAbstractSpinBox, QAbstractButton)):
                w.installEventFilter(self)

    def _owns_widget(self, widget: Optional[QWidget]) -> bool:
        if widget is None:
            return False
        for child in self.childItems():
            if isinstance(child, QGraphicsProxyWidget):
                w = child.widget()
                if w is not None and (w is widget or w.isAncestorOf(widget)):
                    return True
        return False

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.FocusIn, QEvent.MouseButtonPress):
            win = editor_window_of(self)
            if win:
                counter = getattr(win, '_focus_event_counter', 0) + 1
                win._focus_event_counter = counter
                for child in self.childItems():
                    if isinstance(child, QGraphicsProxyWidget):
                        w = child.widget()
                        if w is not None and (w is obj or w.isAncestorOf(obj)):
                            active_key = getattr(child, '_field_key', None)
                            if active_key is not None:
                                win._active_field_key = active_key
                            break
            self._enter_linked_editing()
        elif event.type() == QEvent.FocusOut:
            win = editor_window_of(self)
            ct = getattr(win, '_focus_event_counter', 0) if win else 0
            QTimer.singleShot(0, lambda: self._exit_linked_editing_if_focus_left(ct))
        return super().eventFilter(obj, event)

    def _enter_linked_editing(self):
        win   = editor_window_of(self)
        scene = self.scene()
        if not win or not scene:
            return

        pre_click = getattr(scene, '_pre_click_selection', None)
        selected_items = pre_click if pre_click is not None else scene.selectedItems()

        same_type = [
            n for n in selected_items
            if isinstance(n, ParamNode) and n.TYPE_ID == self.TYPE_ID
        ]
        group = same_type if self in same_type else [self, *same_type]
        if set(win._linked_group) == set(group):
            for node in win._linked_group:
                if node.scene():
                    node._adjust_proxy_z_values()
            return

        saved_key = getattr(win, '_active_field_key', None)
        self._dissolve_linked_group()
        win._active_field_key = saved_key

        win._linked_group = group
        for node in group:
            node._refresh_selection_visuals()

    def _exit_linked_editing_if_focus_left(self, queued_ct: int):
        win = editor_window_of(self)
        if not win or not win._linked_group:
            return
        if self not in win._linked_group:
            return
        current_ct = getattr(win, '_focus_event_counter', 0)
        if current_ct > queued_ct:
            return
        focused = QApplication.focusWidget()
        if any(n.scene() and n._owns_widget(focused) for n in win._linked_group):
            return
        self._dissolve_linked_group()

    def _dissolve_linked_group(self):
        win = editor_window_of(self)
        if not win or not win._linked_group:
            return
        win._active_field_key = None
        group, win._linked_group = win._linked_group, []
        for node in group:
            if node.scene():
                node._refresh_selection_visuals()
        win.push_undo_state()

    def _refresh_selection_visuals(self):
        win = editor_window_of(self)
        is_linked = win is not None and self in getattr(win, '_linked_group', [])
        self._selection_overlay.setVisible(self.isSelected() or is_linked)
        self.update()
        self._adjust_proxy_z_values()

    def _adjust_proxy_z_values(self):
        win = editor_window_of(self)
        is_edited = win is not None and self in win._linked_group
        active_key = getattr(win, '_active_field_key', None) if is_edited else None

        for child in self.childItems():
            if isinstance(child, QGraphicsProxyWidget):
                child_key = getattr(child, '_field_key', None)
                if is_edited and active_key is not None and child_key == active_key:
                    if not hasattr(child, '_original_z_value'):
                        child._original_z_value = child.zValue()
                    child.setZValue(NODE_LINKED_FIELD_Z)
                    child.update()
                else:
                    if hasattr(child, '_original_z_value'):
                        child.setZValue(child._original_z_value)
                        delattr(child, '_original_z_value')
                        child.update()

        self.update()
        self._selection_overlay.update()

    def _broadcast_to_linked_peers(self):
        if ParamNode._broadcasting:
            return
        win = editor_window_of(self)
        if not win or self not in win._linked_group:
            return
        active_key = getattr(win, '_active_field_key', None)
        ParamNode._broadcasting = True
        try:
            for peer in win._linked_group:
                if peer is not self and peer.scene():
                    peer._apply_linked_sync(self, active_key)
        finally:
            ParamNode._broadcasting = False

    def _apply_linked_sync(self, source_node: "ParamNode", active_key: Optional[str]):
        self.set_value_state(source_node.get_value_state())

    # ── Value propagation ─────────────────────────────────────────────────────

    def _propagate_connections_changed(self, visited):
        if self in visited:
            return
        visited.add(self)
        win = editor_window_of(self)
        if not win:
            return
        for conn in win.connections:
            if conn.source.meta_node is self:
                dest_node = conn.dest.meta_node
                if hasattr(dest_node, "_update_connected_values"):
                    dest_node._update_connected_values()
                    dest_node._propagate_connections_changed(visited)

    def _update_connected_values(self):
        """
        Hook method called when connections are established or updated.
        Why: Parameter classes override this to pull input data or lock widgets.
        """
        return

    def _on_widget_user_edit(self):
        win = editor_window_of(self)
        if win:
            win.push_undo_state()

    def _format_float_input(self, line_edit: QLineEdit):
        text = line_edit.text().strip()
        if not text:
            return
        try:
            val = float(text.replace(",", "."))
            if "." not in text and "e" not in text.lower():
                line_edit.setText(f"{int(val)}.0")
            elif text.endswith("."):
                line_edit.setText(text + "0")
        except ValueError:
            # Non-numeric text is a valid in-progress edit, not an error — leave it
            # untouched and let the field keep what the user is still typing.
            pass

    def _on_float_editing_finished(self):
        sender = self.sender()
        if isinstance(sender, QLineEdit):
            self._format_float_input(sender)
        self._on_widget_user_edit()

    def _refresh_connections(self):
        super()._refresh_connections()
        self._update_connected_values()

    # ── Value contract ────────────────────────────────────────────────────────

    def get_value_state(self) -> Any:
        """
        Get the internal state of the parameter value for serialization.
        Why: Backing files need a standard format to serialize all parameter nodes.
        """
        return None

    def set_value_state(self, val: Any):
        """
        Set the internal state of the parameter value from serialized data.
        Why: Backing files need a standard format to restore parameter widgets.
        """
        return

    def get_value(self, socket_name: str = None) -> str:
        raise NotImplementedError


class VectorParamNode(ParamNode):
    AXES: tuple = ()

    def __init__(self, param_name: str):
        super().__init__(param_node_def(param_name, self.TYPE_ID))

        param_rows = [s.row for s in self.node_def.sockets if not s.is_exec]
        rows = max(param_rows, default=-1) + 1

        total_w = self._widget_width()
        n_axes = len(self.AXES)
        spacing = 4
        col_w = int((total_w - spacing * (n_axes - 1)) / n_axes)

        self._editors: List[QLineEdit] = []
        for i, axis in enumerate(self.AXES):
            cell_widget = QWidget()
            cell_widget.setStyleSheet("background:transparent;")
            layout = QHBoxLayout(cell_widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(2)

            editor = self._make_field("0.0", axis.lower(), fixed_width=False)
            editor.setValidator(QDoubleValidator())
            editor.textChanged.connect(self._notify_connections_changed)
            editor.editingFinished.connect(self._on_float_editing_finished)

            label = QLabel(f"{axis}:")
            label.setStyleSheet(VECTOR_AXIS_LABEL_QSS)

            layout.addWidget(label)
            layout.addWidget(editor)
            self._editors.append(editor)

            cell_widget.setFixedWidth(col_w)

            proxy = QGraphicsProxyWidget(self)
            proxy.setWidget(cell_widget)
            proxy.setPos(
                NODE_HORIZONTAL_PAD + i * (col_w + spacing),
                NODE_HEADER_HEIGHT + rows * NODE_ROW_HEIGHT + NODE_WIDGET_V_OFFSET,
            )
            proxy.setZValue(NODE_WIDGET_Z_BASE - rows)
            proxy._field_key = f"vector_{axis}"

            self._watch_field_focus(cell_widget)

    def get_value_state(self) -> Any:
        return [editor.text() for editor in self._editors]

    def set_value_state(self, val: Any):
        if isinstance(val, list):
            for editor, component in zip(self._editors, val):
                editor.setText(str(component))

    def _apply_linked_sync(self, source_node: ParamNode, active_key: Optional[str]):
        if active_key and active_key.startswith("vector_"):
            axis = active_key.split("_")[1]
            try:
                idx = self.AXES.index(axis)
                if hasattr(source_node, '_editors') and idx < len(source_node._editors):
                    self._editors[idx].setText(source_node._editors[idx].text())
                return
            except ValueError:
                # The active key named an axis this vector lacks; fall through to a
                # whole-value sync below instead of mirroring a single component.
                pass
        self.set_value_state(source_node.get_value_state())

    def get_value(self, socket_name: str = None) -> str:
        return " ".join(editor.text().strip() or "0.0" for editor in self._editors)


class StringParamNode(ParamNode):
    TYPE_ID = "string"

    def __init__(self, param_name=None, default=""):
        if param_name is None:
            param_name = t("param_string_title")
        super().__init__(param_node_def(param_name, self.TYPE_ID))
        self._editor = self._make_field(default, t("param_string_placeholder"))
        self._editor.textChanged.connect(self._notify_connections_changed)
        self._editor.editingFinished.connect(self._on_widget_user_edit)
        self._attach_input_widget(self._editor)

    def get_value_state(self) -> Any:
        return self._editor.text()

    def set_value_state(self, val: Any):
        self._editor.setText(str(val))

    def get_value(self, socket_name: str = None) -> str:
        return self._editor.text().strip()


class BoolParamNode(ParamNode):
    TYPE_ID = "bool"

    def __init__(self, param_name=None, default=False):
        if param_name is None:
            param_name = t("param_bool_title")
        super().__init__(param_node_def(param_name, self.TYPE_ID))
        self._checkbox = self._make_checkbox("true" if default else "false", default)
        self._checkbox.toggled.connect(
            lambda checked: self._checkbox.setText("true" if checked else "false")
        )
        self._checkbox.toggled.connect(self._notify_connections_changed)
        self._checkbox.toggled.connect(self._on_widget_user_edit)
        self._attach_input_widget(self._checkbox)

    def get_value_state(self) -> Any:
        return self._checkbox.isChecked()

    def set_value_state(self, val: Any):
        checked = bool(val)
        self._checkbox.setChecked(checked)
        self._checkbox.setText("true" if checked else "false")

    def get_value(self, socket_name: str = None) -> str:
        return "true" if self._checkbox.isChecked() else "false"


class IntParamNode(ParamNode):
    TYPE_ID = "integer"

    def __init__(self, param_name=None, default=0):
        if param_name is None:
            param_name = t("param_int_title")
        super().__init__(param_node_def(param_name, self.TYPE_ID))
        self._spinbox = self._make_spinbox(-999999, 999999, default)
        self._spinbox.valueChanged.connect(self._notify_connections_changed)
        self._spinbox.editingFinished.connect(self._on_widget_user_edit)
        self._attach_input_widget(self._spinbox)

    def get_value_state(self) -> Any:
        return self._spinbox.value()

    def set_value_state(self, val: Any):
        self._spinbox.setValue(int(val))

    def get_value(self, socket_name: str = None) -> str:
        return str(self._spinbox.value())


class FloatParamNode(ParamNode):
    TYPE_ID = "float"

    def __init__(self, param_name=None, default=0.0):
        if param_name is None:
            param_name = t("param_float_title")
        super().__init__(param_node_def(param_name, self.TYPE_ID))
        self._editor = self._make_field(str(default))
        self._editor.setValidator(QDoubleValidator())
        self._editor.textChanged.connect(self._notify_connections_changed)
        self._editor.editingFinished.connect(self._on_float_editing_finished)
        self._attach_input_widget(self._editor)

    def get_value_state(self) -> Any:
        return self._editor.text()

    def set_value_state(self, val: Any):
        self._editor.setText(str(val))

    def get_value(self, socket_name: str = None) -> str:
        return self._editor.text().strip()


class EnumParamNode(ParamNode):
    TYPE_ID = "enum"

    def __init__(self, param_name=None, values=None):
        if param_name is None:
            param_name = t("param_enum_title")
        schema        = resolve_color_schema("enum")
        string_schema = resolve_color_schema("string")
        node_def = NodeDef(
            title=html_title(param_name),
            header_color=schema["hdr"],
            body_color=schema["body"],
            sockets=[
                SocketDef("src", "input", row=1, label="",
                          color=string_schema["socket"], param_type="string",
                          optional=True),
                SocketDef("value_out", "output", row=1, label="",
                          color=string_schema["socket"], param_type="string"),
            ],
            has_footer=False,
        )
        super().__init__(node_def)

        self._new_item = self._make_field(placeholder=t("param_enum_new_placeholder"), fixed_width=False)

        self._add_btn = self._make_toolbtn("+", self._add_enum_item)
        self._remove_btn = self._make_toolbtn("−", self._remove_enum_item)
        editor_row = QWidget()
        editor_row.setStyleSheet("background:transparent;")
        editor_layout = QHBoxLayout(editor_row)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(3)
        editor_layout.addWidget(self._new_item)
        editor_layout.addWidget(self._add_btn)
        editor_layout.addWidget(self._remove_btn)
        editor_row.setFixedWidth(self._widget_width())
        self._attach_widget_at_row(editor_row, 0)

        self._combobox = self._make_combobox(values or ["option1", "option2"], editable=False)
        self._combobox.currentTextChanged.connect(self._notify_connections_changed)
        self._combobox.activated.connect(self._on_widget_user_edit)
        self._attach_widget_at_row(self._combobox, 1)

    def _add_enum_item(self):
        text = self._new_item.text().strip()
        if text and self._combobox.findText(text) == -1:
            self._combobox.addItem(text)
            self._combobox.setCurrentText(text)
            self._new_item.clear()
            self._on_widget_user_edit()

    def _remove_enum_item(self):
        idx = self._combobox.currentIndex()
        if idx >= 0:
            self._combobox.removeItem(idx)
            self._on_widget_user_edit()

    def _populate_from_source(self, source: str):
        if not source:
            return
        if source.lower().endswith(".xml") and os.path.isfile(source):
            try:
                root = ET.parse(source).getroot()
                items = [el.text.strip() for el in root.iter()
                         if el.text and el.text.strip()]
            except Exception as exc:
                log_and_explain("Failed to parse combobox XML parameters", exc)
                items = []
        else:
            items = [s.strip() for s in source.split(",") if s.strip()]
        if items:
            current = self._combobox.currentText()
            self._combobox.blockSignals(True)
            self._combobox.clear()
            self._combobox.addItems(items)
            new_text = current if current in items else items[0]
            self._combobox.setCurrentText(new_text)
            self._combobox.blockSignals(False)
            if new_text != current:
                self._notify_connections_changed()

    def _update_connected_values(self):
        src_val = self._get_connected_input_value("src")
        if src_val:
            self._new_item.clear()
            self._new_item.setReadOnly(True)
            self._add_btn.setVisible(False)
            self._remove_btn.setVisible(False)
            self._populate_from_source(src_val)
        else:
            self._new_item.setReadOnly(False)
            self._add_btn.setVisible(True)
            self._remove_btn.setVisible(True)

    def get_value_state(self) -> Any:
        return {
            "items": [self._combobox.itemText(i) for i in range(self._combobox.count())],
            "current": self._combobox.currentText(),
        }

    def set_value_state(self, val: Any):
        if isinstance(val, dict):
            self._combobox.blockSignals(True)
            self._combobox.clear()
            self._combobox.addItems(val.get("items", []))
            self._combobox.setCurrentText(val.get("current", ""))
            self._combobox.blockSignals(False)
        else:
            self._combobox.setCurrentText(str(val))  # legacy saves stored only the selection

    def _apply_linked_sync(self, source_node: ParamNode, active_key: Optional[str]):
        self._combobox.setCurrentText(source_node._combobox.currentText())

    def get_value(self, socket_name: str = None) -> str:
        src_socket = self.get_socket("src")
        win = editor_window_of(self)
        if src_socket and win:
            for conn in win.connections:
                if conn.dest.meta_node is self and conn.dest.sock_def.name == src_socket.sock_def.name:
                    self._populate_from_source(
                        conn.source.meta_node.get_value(conn.source.sock_def.name)
                    )
                    break
        return self._combobox.currentText()


class PathParamNode(ParamNode):
    TYPE_ID = "path"

    def __init__(self, param_name=None):
        if param_name is None:
            param_name = t("param_path_title")
        dir_schema    = resolve_color_schema("dirpath")
        file_schema   = resolve_color_schema("filepath")
        string_schema = resolve_color_schema("string")

        node_def = NodeDef(
            title=html_title(param_name),
            header_color=dir_schema["hdr"],
            body_color=dir_schema["body"],
            sockets=[
                SocketDef("dirpath_out", "output", row=0, label="",
                          color=dir_schema["socket"], param_type="dirpath"),
                SocketDef("path_out", "output", row=0, label="",
                          color=file_schema["socket"], param_type="filepath"),
                SocketDef("filename", "input", row=1, label="",
                          color=string_schema["socket"], param_type="string",
                          optional=True),
                SocketDef("filetype", "input", row=2, label="",
                          color=string_schema["socket"], param_type="string",
                          optional=True),
            ],
            width=260,
            has_footer=False,
        )
        super().__init__(node_def)

        self._ext_filter = self._make_field("", t("param_path_ext_placeholder"))
        self._ext_filter.textChanged.connect(
            lambda: self._on_dir_changed(self._dir_editor.text())
        )
        self._ext_filter.textChanged.connect(self._notify_connections_changed)
        self._ext_filter.editingFinished.connect(self._on_widget_user_edit)

        self._dir_editor = self._make_field(placeholder=t("param_path_dir_placeholder"), fixed_width=False)
        self._dir_editor.textChanged.connect(self._on_dir_changed)
        self._dir_editor.textChanged.connect(self._notify_connections_changed)
        self._dir_editor.editingFinished.connect(self._on_widget_user_edit)

        self._file_combo = self._make_combobox()
        self._file_combo.lineEdit().setPlaceholderText(t("param_path_file_placeholder"))
        self._file_combo.currentTextChanged.connect(self._notify_connections_changed)
        self._file_combo.activated.connect(self._on_widget_user_edit)
        if self._file_combo.lineEdit():
            self._file_combo.lineEdit().editingFinished.connect(self._on_widget_user_edit)

        # Every row is a single wrapper QWidget primitive holding its leaves. Uniform
        # structure means colour recoloring walks identical containers for each row;
        # otherwise a bare leaf like the combobox can lose its proxy widget reference
        # and silently skip the recolour pass.
        self._attach_widget_at_row(self._row_container(
            [self._dir_editor, self._make_toolbtn("…", self._browse_for_folder)]), 0)
        self._attach_widget_at_row(self._row_container([self._file_combo]), 1)
        self._attach_widget_at_row(self._row_container([self._ext_filter]), 2)

    def _row_container(self, leaves):
        wrapper = QWidget()
        wrapper.setStyleSheet("background:transparent;")
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        for leaf in leaves:
            layout.addWidget(leaf)
        wrapper.setFixedWidth(self._widget_width())
        return wrapper

    def _browse_for_folder(self):
        path = QFileDialog.getExistingDirectory(None, t("dialog_select_folder"), self._dir_editor.text())
        if path:
            self._dir_editor.setText(path)
            self._on_widget_user_edit()

    def _update_connected_values(self):
        self._show_connected_combobox(self._file_combo,
                                      self._get_connected_input_value("filename"))
        self._show_connected_value(self._ext_filter,
                                   self._get_connected_input_value("filetype"))

    def _on_dir_changed(self, text):
        self._file_combo.blockSignals(True)
        self._file_combo.clear()
        if os.path.isdir(text):
            try:
                raw = (self._get_connected_input_value("filetype")
                       or self._ext_filter.text()).strip()
                ext = raw.lstrip("*").lstrip(".").lower()
                files = sorted(
                    f for f in os.listdir(text)
                    if os.path.isfile(os.path.join(text, f))
                    and (not ext or f.lower().endswith("." + ext))
                )
                self._file_combo.addItem("")
                self._file_combo.addItems(files)
                self._file_combo.setCurrentText("")
            except Exception as exc:
                log_and_explain("Failed to list files in directory", exc)
        self._file_combo.blockSignals(False)
        self._notify_connections_changed()

    def get_value_state(self) -> Any:
        return {
            "dir": self._dir_editor.text(),
            "file": self._file_combo.currentText(),
            "ext": self._ext_filter.text(),
        }

    def set_value_state(self, val: Any):
        if isinstance(val, dict):
            # Ext first so the directory listing filters correctly when dir is applied.
            self._ext_filter.setText(val.get("ext", ""))
            self._dir_editor.setText(val.get("dir", ""))
            self._file_combo.setCurrentText(val.get("file", ""))
        else:
            self._dir_editor.setText(str(val))

    def _apply_linked_sync(self, source_node: ParamNode, active_key: Optional[str]):
        if active_key == "row_0":
            self._dir_editor.setText(source_node._dir_editor.text())
        elif active_key == "row_1":
            self._file_combo.setCurrentText(source_node._file_combo.currentText())
        elif active_key == "row_2":
            self._ext_filter.setText(source_node._ext_filter.text())
        else:
            self.set_value_state(source_node.get_value_state())

    def get_value(self, socket_name: str = None) -> str:
        d = self._dir_editor.text().strip().replace("\\", "/")
        if socket_name == "dirpath_out":
            return d
        filename = self._get_connected_input_value("filename") or self._file_combo.currentText().strip()
        raw_type = (self._get_connected_input_value("filetype") or self._ext_filter.text()).strip()
        ext = raw_type.lstrip("*").lstrip(".")
        if ext and filename:
            suffix = "." + ext
            if not filename.lower().endswith(suffix.lower()):
                filename += suffix
        if d and filename:
            return (d + "/" + filename).replace("\\", "/")
        return d


class KeyValueParamNode(ParamNode):
    TYPE_ID = "keyvalue"

    def __init__(self, param_name=None):
        if param_name is None:
            param_name = t("param_keyvalue_title")
        super().__init__(param_node_def(param_name, self.TYPE_ID))
        self._editor = self._make_field("key=value", t("param_keyvalue_placeholder"))
        self._editor.textChanged.connect(self._notify_connections_changed)
        self._editor.editingFinished.connect(self._on_widget_user_edit)
        self._attach_input_widget(self._editor)

    def get_value_state(self) -> Any:
        return self._editor.text()

    def set_value_state(self, val: Any):
        self._editor.setText(str(val))

    def get_value(self, socket_name: str = None) -> str:
        return self._editor.text().strip()


class Float2ParamNode(VectorParamNode):
    TYPE_ID = "float2"
    AXES = ("X", "Y")

    def __init__(self, param_name=None):
        if param_name is None:
            param_name = t("param_float2_title")
        super().__init__(param_name)


class Float3ParamNode(VectorParamNode):
    TYPE_ID = "float3"
    AXES = ("X", "Y", "Z")

    def __init__(self, param_name=None):
        if param_name is None:
            param_name = t("param_float3_title")
        super().__init__(param_name)


PARAM_NODE_TYPES: Dict[str, type] = {
    "string":   StringParamNode,
    "bool":     BoolParamNode,
    "integer":  IntParamNode,
    "float":    FloatParamNode,
    "float2":   Float2ParamNode,
    "float3":   Float3ParamNode,
    "enum":     EnumParamNode,
    "enum_int": EnumParamNode,
    "filepath": PathParamNode,
    "dirpath":  PathParamNode,
    "keyvalue": KeyValueParamNode,
}
