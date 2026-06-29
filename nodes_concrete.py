from __future__ import annotations
import os
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Any

from PyQt5.QtWidgets import (
    QPushButton, QWidget, QHBoxLayout, QGraphicsProxyWidget, QFileDialog,
)
from PyQt5.QtGui import QDoubleValidator
from PyQt5.QtCore import QPointF, Qt

from configuration import (
    NODE_HEADER_HEIGHT, NODE_ROW_HEIGHT,
    NODE_HORIZONTAL_PAD, NODE_WIDGET_V_OFFSET,
    INTEGER_PARAM_NAMES, PUSHBTN_QSS,
    AUTOSPAWN_X_GAP, AUTOSPAWN_Y_OFFSET, AUTOSPAWN_V_GAP,
    NODE_BORDER_COLOR,
)
from nodes_base import (
    SocketDef, NodeDef, MetaNode, _BaseParamNode, _VectorParamNode,
    resolve_color_schema, param_spec_name, _html_title, _param_node_def,
    Connection, SocketItem,
)

# Visual prefix per parameter type — keeps auto-created nodes consistent with the
# titles the typed ParamNode classes assign themselves.
PARAM_TYPE_PREFIX: Dict[str, str] = {
    "string": "[S]", "bool": "[B]", "integer": "[I]", "float": "[#]",
    "float2": "[#2]", "float3": "[#3]", "enum": "[E]", "enum_int": "[E]",
    "filepath": "[F/D]", "dirpath": "[F/D]", "keyvalue": "[K]",
}


def _vector_axis_run(params: list, start: int, base: str) -> list:
    run = []
    for offset, suffix in enumerate("xyz"):
        position = start + offset
        if position >= len(params):
            break
        if param_spec_name(params[position]).lower() != (base + suffix).lower():
            break
        run.append(params[position])
    return run


def _mark_expanded_start(param, base: str) -> dict:
    marked = {"name": param_spec_name(param)} if isinstance(param, str) else param.copy()
    marked["is_expanded_vector_start"] = True
    marked["vector_base"] = base
    return marked


def _collapse_vector(axis_params: list, base: str) -> dict:
    is_triple = len(axis_params) == 3
    axes_label = "X,Y,Z" if is_triple else "X,Y"
    return {
        "name": base or ("XYZ" if is_triple else "XY"),
        "label": f"{base} ({axes_label})" if base else axes_label,
        "type": "float3" if is_triple else "float2",
        "original": list(axis_params),
        "is_collapsed_vector": True,
        "vector_base": base,
    }


def group_xyz_params(params: list, expanded_bases: set = None) -> list:
    expanded_bases = expanded_bases or set()
    grouped = []
    index = 0
    while index < len(params):
        head_name = param_spec_name(params[index])
        base = head_name[:-1] if head_name.lower().endswith("x") else None
        axis_run = _vector_axis_run(params, index, base) if base is not None else []

        if len(axis_run) >= 2:
            if base in expanded_bases:
                grouped.append(_mark_expanded_start(axis_run[0], base))
                grouped.extend(axis_run[1:])
            else:
                grouped.append(_collapse_vector(axis_run, base))
            index += len(axis_run)
            continue

        grouped.append(params[index])
        index += 1
    return grouped


def _start_node_def() -> NodeDef:
    exec_schema = resolve_color_schema("exec")
    return NodeDef(
        title=_html_title("> START"),
        header_color=exec_schema["hdr"],
        body_color=exec_schema["body"],
        sockets=[SocketDef(
            "exec_out", "output", row=-1, label="",
            color=exec_schema["socket"], is_exec=True,
        )],
        width=185,
        has_footer=False,
        extra_rows=5.5,
    )


def _resolve_param_type(name: str, param) -> str:
    declared = param.get("type", "string") if isinstance(param, dict) else "string"
    if declared == "string" and name.lower() in INTEGER_PARAM_NAMES:
        return "integer"
    return declared


def _append_param_sockets(sockets: List[SocketDef], param, row: int, optional: bool):
    name   = param_spec_name(param)
    ptype  = _resolve_param_type(name, param)
    values = param.get("values", []) if isinstance(param, dict) else []
    label  = param.get("label", name) if isinstance(param, dict) else name
    socket_color = resolve_color_schema(ptype)["socket"]

    sockets.append(SocketDef(
        name, "input", row=row, label=f"{label}  (opt)" if optional else label,
        optional=optional, color=socket_color, param_type=ptype, values=values,
        is_collapsed_vector=param.get("is_collapsed_vector", False) if isinstance(param, dict) else False,
        is_expanded_vector_start=param.get("is_expanded_vector_start", False) if isinstance(param, dict) else False,
        vector_base=param.get("vector_base", "") if isinstance(param, dict) else "",
    ))
    if name.startswith("new"):
        sockets.append(SocketDef(
            f"{name}_out", "output", row=row, label="", optional=optional,
            color=socket_color, param_type=ptype, values=values,
        ))


def _command_node_def(cmd_def: dict, expanded_vectors: set = None) -> NodeDef:
    display = cmd_def.get("display", cmd_def.get("command", ""))
    exec_schema = resolve_color_schema("exec")
    sockets: List[SocketDef] = [
        SocketDef("__exec_in__",  "input",  row=-1, label="", color=exec_schema["socket"], is_exec=True),
        SocketDef("__exec_out__", "output", row=-1, label="", color=exec_schema["socket"], is_exec=True),
    ]
    row_idx = 0
    for optional, key in ((False, "required"), (True, "optional")):
        for param in group_xyz_params(cmd_def.get(key, []), expanded_vectors):
            _append_param_sockets(sockets, param, row_idx, optional)
            row_idx += 1
    return NodeDef(
        title=_html_title(display, bold_first=True),
        header_color=exec_schema["hdr"],
        body_color=exec_schema["body"],
        sockets=sockets,
        width=235,
    )


class StartNode(MetaNode):
    is_protected = True  # the chain's root: bulk delete and group-clear must spare it

    def __init__(self):
        super().__init__(_start_node_def())
        param_rows = [s.row for s in self.node_def.sockets if not s.is_exec]
        rows = max(param_rows, default=-1) + 1
        btn_w = self.node_def.width - NODE_HORIZONTAL_PAD * 2

        def _add_btn(label: str, tooltip: str, callback, row_offset: float):
            btn = QPushButton(label)
            btn.setStyleSheet(PUSHBTN_QSS)
            btn.setFixedWidth(btn_w)
            btn.setToolTip(tooltip)
            btn.clicked.connect(callback)
            proxy = QGraphicsProxyWidget(self)
            proxy.setWidget(btn)
            y = NODE_HEADER_HEIGHT + (rows + row_offset) * NODE_ROW_HEIGHT + NODE_WIDGET_V_OFFSET
            proxy.setPos(NODE_HORIZONTAL_PAD, y)

        # Launch sits alone at the top; file-management buttons are grouped below
        # the separator so accidental clicks on Launch are physically impossible.
        _add_btn("> Launch", "",              self._request_chain_execution, 0.0)

        # Horizontal separator — visually isolates Launch from file operations
        sep = QWidget()
        sep.setFixedWidth(btn_w)
        sep.setFixedHeight(2)
        sep.setStyleSheet(f"background-color: {NODE_BORDER_COLOR};")
        sep_proxy = QGraphicsProxyWidget(self)
        sep_proxy.setWidget(sep)
        sep_proxy.setPos(
            NODE_HORIZONTAL_PAD,
            NODE_HEADER_HEIGHT + (rows + 1.35) * NODE_ROW_HEIGHT + NODE_WIDGET_V_OFFSET,
        )

        _add_btn("Open",    "Ctrl+O",       self._request_open,    2.0)
        _add_btn("Save",    "Ctrl+S",       self._request_save,    3.0)
        _add_btn("Save As", "Ctrl+Shift+S", self._request_save_as, 4.0)

    def _request_chain_execution(self):
        scene = self.scene()
        win = getattr(scene, 'nodeEditorWindow', None) if scene else None
        if win:
            win.execute_chain()

    def _request_open(self):
        scene = self.scene()
        win = getattr(scene, 'nodeEditorWindow', None) if scene else None
        if win:
            win.load_project()

    def _request_save(self):
        scene = self.scene()
        win = getattr(scene, 'nodeEditorWindow', None) if scene else None
        if win:
            win.save_project()

    def _request_save_as(self):
        scene = self.scene()
        win = getattr(scene, 'nodeEditorWindow', None) if scene else None
        if win:
            win.save_project(save_as=True)


class CommandNode(MetaNode):
    def __init__(self, cmd_def: dict, expanded_vectors: set = None):
        self.cmd_def = cmd_def
        self.expanded_vectors = expanded_vectors or set()
        super().__init__(_command_node_def(cmd_def, self.expanded_vectors))

    def serialize_payload(self) -> dict:
        return {"cmd_def": self.cmd_def}

    def toggle_vector_expansion(self, base_name: str):
        self.expanded_vectors.symmetric_difference_update({base_name})

        scene = self.scene()
        win = getattr(scene, 'nodeEditorWindow', None) if scene else None
        if not win or not scene:
            return

        was_selected = self.isSelected()
        new_node = CommandNode(self.cmd_def, self.expanded_vectors.copy())
        new_node.setPos(self.pos())
        scene.addItem(new_node)
        new_node.setSelected(was_selected)

        for old in list(win.connections):
            if old.source.meta_node is self:
                migrated = new_node.sockets.get(old.source.sock_def.name)
                if migrated:
                    self._rewire(scene, win, migrated, old.dest)
            elif old.dest.meta_node is self:
                migrated = new_node.sockets.get(old.dest.sock_def.name)
                if migrated:
                    self._rewire(scene, win, old.source, migrated)
            else:
                continue
            scene.removeItem(old)
            if old in win.connections:
                win.connections.remove(old)

        scene.removeItem(self)
        win.push_undo_state()

    @staticmethod
    def _rewire(scene, win, out_sock: SocketItem, in_sock: SocketItem):
        scene._enforce_connection_rules(out_sock, in_sock)
        conn = Connection(out_sock, in_sock)
        scene.addItem(conn)
        win.connections.append(conn)
        conn.source.meta_node._refresh_connections()
        conn.dest.meta_node._refresh_connections()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._begin_rename()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        if not self._editor_window():
            super().contextMenuEvent(event)
            return
        has_required = bool(self.cmd_def.get("required", []))
        win = self._editor_window()
        self._run_context_menu(event, [
            ("Rename",         self._begin_rename,                         True),
            ("Auto-Create Required Parameters",
             self.auto_create_required_parameters,
             has_required),
            None,
            ("Duplicate",      getattr(win, "duplicate_nodes",      None), True),
            ("Copy",           getattr(win, "copy_nodes",           None), True),
            ("Paste",          getattr(win, "paste_nodes",          None), True),
            ("Group in Frame", getattr(win, "group_selected_nodes", None), True),
            None,
            ("Delete Node",    self._delete_self,                          True),
        ])

    def _all_required_params(self):
        """All required-parameter sockets on this command, connected or not."""
        result = []
        for param in group_xyz_params(self.cmd_def.get("required", []), self.expanded_vectors):
            socket = self.get_socket(param_spec_name(param))
            if socket:
                result.append((param, socket))
        return result

    def auto_create_required_parameters(self):
        """Create param nodes for every required parameter, replacing any existing wires.

        Always operates on the full required-param list so the result is identical
        regardless of what was manually connected beforehand.
        """
        scene = self.scene()
        win = self._editor_window()
        if not win or not scene:
            return

        all_required = self._all_required_params()
        win._block_undo_push = True
        try:
            command_pos = self.scenePos()
            spawn_y = command_pos.y() + AUTOSPAWN_Y_OFFSET

            for param, socket in all_required:
                try:
                    # Remove any existing incoming wire on this socket so the
                    # auto-created node becomes the one true source.
                    for c in [c for c in win.connections if c.dest is socket]:
                        scene.removeItem(c)
                        win.connections.remove(c)

                    param_name   = param_spec_name(param)
                    param_type   = _resolve_param_type(param_name, param)
                    param_values = [] if isinstance(param, str) else param.get("values", [])

                    prefix = PARAM_TYPE_PREFIX.get(param_type, "")
                    creation_data = {
                        "param_type": param_type,
                        "display": f"{prefix} {param_name}" if prefix else param_name,
                        "values": param_values,
                    }

                    param_node = win.add_param_node(
                        QPointF(command_pos.x() - AUTOSPAWN_X_GAP, spawn_y), creation_data)
                    if not param_node:
                        continue
                    spawn_y += param_node.node_def.body_height + AUTOSPAWN_V_GAP

                    out_socket = (
                        param_node.get_socket("dirpath_out") if param_type == "dirpath"
                        else param_node.get_socket("path_out") if param_type == "filepath"
                        else param_node.get_socket("value_out")
                    )
                    if out_socket:
                        self._rewire(scene, win, out_socket, socket)
                except Exception as exc:
                    from diagnostics import log_and_explain
                    log_and_explain(f"Skipped auto-creating parameter {param}", exc)

            self._refresh_connections()
            for p_node in [c.source.meta_node for c in win.connections if c.dest.meta_node is self]:
                p_node._refresh_connections()

        finally:
            win._block_undo_push = False
            win.push_undo_state()


class StringParamNode(_BaseParamNode):
    TYPE_ID = "string"

    def __init__(self, param_name="[S] String", default=""):
        super().__init__(_param_node_def(param_name, self.TYPE_ID))
        self._editor = self._make_field(default, "text value...")
        self._editor.textChanged.connect(self._notify_connections_changed)
        self._editor.editingFinished.connect(self._on_widget_user_edit)
        self._attach_input_widget(self._editor)

    def get_value_state(self) -> Any:
        return self._editor.text()

    def set_value_state(self, val: Any):
        self._editor.setText(str(val))

    def get_value(self, socket_name: str = None) -> str:
        return self._editor.text().strip()


class BoolParamNode(_BaseParamNode):
    TYPE_ID = "bool"

    def __init__(self, param_name="[B] Boolean", default=False):
        super().__init__(_param_node_def(param_name, self.TYPE_ID))
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


class IntParamNode(_BaseParamNode):
    TYPE_ID = "integer"

    def __init__(self, param_name="[I] Integer", default=0):
        super().__init__(_param_node_def(param_name, self.TYPE_ID))
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


class FloatParamNode(_BaseParamNode):
    TYPE_ID = "float"

    def __init__(self, param_name="[#] Float", default=0.0):
        super().__init__(_param_node_def(param_name, self.TYPE_ID))
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


class EnumParamNode(_BaseParamNode):
    TYPE_ID = "enum"

    def __init__(self, param_name="[E] Enum", values=None):
        schema        = resolve_color_schema("enum")
        string_schema = resolve_color_schema("string")
        node_def = NodeDef(
            title=_html_title(param_name),
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

        self._new_item = self._make_field(placeholder="new item…", fixed_width=False)
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
                from diagnostics import log_and_explain
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

    def _apply_linked_sync(self, source_node: _BaseParamNode, active_key: Optional[str]):
        self._combobox.setCurrentText(source_node._combobox.currentText())

    def get_value(self, socket_name: str = None) -> str:
        src_socket = self.get_socket("src")
        if src_socket and self.scene():
            win = getattr(self.scene(), 'nodeEditorWindow', None)
            if win:
                for conn in win.connections:
                    if conn.dest.meta_node is self and conn.dest.sock_def.name == src_socket.sock_def.name:
                        self._populate_from_source(
                            conn.source.meta_node.get_value(conn.source.sock_def.name)
                        )
                        break
        return self._combobox.currentText()


class PathParamNode(_BaseParamNode):
    TYPE_ID = "path"

    def __init__(self, param_name="[F/F] Load"):
        dir_schema    = resolve_color_schema("dirpath")
        file_schema   = resolve_color_schema("filepath")
        string_schema = resolve_color_schema("string")

        node_def = NodeDef(
            title=_html_title(param_name),
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

        self._ext_filter = self._make_field("", "*.ext")
        self._ext_filter.textChanged.connect(
            lambda: self._on_dir_changed(self._dir_editor.text())
        )
        self._ext_filter.textChanged.connect(self._notify_connections_changed)
        self._ext_filter.editingFinished.connect(self._on_widget_user_edit)

        self._dir_editor = self._make_field(placeholder="dirpath…", fixed_width=False)
        self._dir_editor.textChanged.connect(self._on_dir_changed)
        self._dir_editor.textChanged.connect(self._notify_connections_changed)
        self._dir_editor.editingFinished.connect(self._on_widget_user_edit)

        dir_widget = QWidget()
        dir_widget.setStyleSheet("background:transparent;")
        dir_layout = QHBoxLayout(dir_widget)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(3)
        dir_layout.addWidget(self._dir_editor)
        dir_layout.addWidget(self._make_toolbtn("…", self._browse_for_folder))
        dir_widget.setFixedWidth(self._widget_width())

        self._file_combo = self._make_combobox()
        self._file_combo.lineEdit().setPlaceholderText("filename…")
        self._file_combo.currentTextChanged.connect(self._notify_connections_changed)
        self._file_combo.activated.connect(self._on_widget_user_edit)
        if self._file_combo.lineEdit():
            self._file_combo.lineEdit().editingFinished.connect(self._on_widget_user_edit)

        self._attach_widget_at_row(dir_widget, 0)
        self._attach_widget_at_row(self._file_combo, 1)
        self._attach_widget_at_row(self._ext_filter, 2)

    def _browse_for_folder(self):
        path = QFileDialog.getExistingDirectory(None, "Select folder", self._dir_editor.text())
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
                from diagnostics import log_and_explain
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

    def _apply_linked_sync(self, source_node: _BaseParamNode, active_key: Optional[str]):
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


class KeyValueParamNode(_BaseParamNode):
    TYPE_ID = "keyvalue"

    def __init__(self, param_name="[K] Key=Value"):
        super().__init__(_param_node_def(param_name, self.TYPE_ID))
        self._editor = self._make_field("key=value", "key=value")
        self._editor.textChanged.connect(self._notify_connections_changed)
        self._editor.editingFinished.connect(self._on_widget_user_edit)
        self._attach_input_widget(self._editor)

    def get_value_state(self) -> Any:
        return self._editor.text()

    def set_value_state(self, val: Any):
        self._editor.setText(str(val))

    def get_value(self, socket_name: str = None) -> str:
        return self._editor.text().strip()


class Float2ParamNode(_VectorParamNode):
    TYPE_ID = "float2"
    AXES = ("X", "Y")

    def __init__(self, param_name="[#2] Float2 (X,Y)"):
        super().__init__(param_name)


class Float3ParamNode(_VectorParamNode):
    TYPE_ID = "float3"
    AXES = ("X", "Y", "Z")

    def __init__(self, param_name="[#3] Float3 (X,Y,Z)"):
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
