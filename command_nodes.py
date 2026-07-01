"""command_nodes.py — Execution-Flow Nodes

StartNode roots the chain and carries the Launch/Open/Save controls; CommandNode
represents one RealityCapture CLI command with typed parameter sockets and
collapsible X/Y/Z vector groups.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QPushButton, QWidget, QGraphicsProxyWidget
from PyQt5.QtCore import QPointF, Qt

from localization import t
from configuration import (
    NODE_HEADER_HEIGHT, NODE_ROW_HEIGHT, NODE_HORIZONTAL_PAD, NODE_WIDGET_V_OFFSET,
    AUTOSPAWN_X_GAP, AUTOSPAWN_Y_OFFSET, AUTOSPAWN_V_GAP,
)
from theme import PUSHBTN_QSS, NODE_BORDER_COLOR
from node_blueprint import (
    PARAM_TYPE_PREFIX, command_node_def, group_xyz_params, param_spec_name,
    resolve_param_type, start_node_def,
)
from graph_items import Connection, MetaNode, SocketItem, editor_window_of
from diagnostics import log_and_explain


class StartNode(MetaNode):
    is_protected = True  # the chain's root: bulk delete and group-clear must spare it

    def __init__(self):
        super().__init__(start_node_def())
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

        # Why: Separates Launch button from file-management options to prevent accidental execution clicks.
        _add_btn(t("btn_launch"), "", self._request_chain_execution, 0.0)

        # Why: Visual line separating Launch execution from project file utilities.
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

        _add_btn(t("btn_open"),    "Ctrl+O",       self._request_open,    2.0)
        _add_btn(t("btn_save"),    "Ctrl+S",       self._request_save,    3.0)
        _add_btn(t("btn_save_as"), "Ctrl+Shift+S", self._request_save_as, 4.0)

    def _request_chain_execution(self):
        win = editor_window_of(self)
        if win:
            win.execute_chain()

    def _request_open(self):
        win = editor_window_of(self)
        if win:
            win.load_project()

    def _request_save(self):
        win = editor_window_of(self)
        if win:
            win.save_project()

    def _request_save_as(self):
        win = editor_window_of(self)
        if win:
            win.save_project(save_as=True)


class CommandNode(MetaNode):
    def __init__(self, cmd_def: dict, expanded_vectors: set = None):
        self.cmd_def = cmd_def
        self.expanded_vectors = expanded_vectors or set()
        super().__init__(command_node_def(cmd_def, self.expanded_vectors))

    def serialize_payload(self) -> dict:
        return {"cmd_def": self.cmd_def}

    def toggle_vector_expansion(self, base_name: str):
        self.expanded_vectors.symmetric_difference_update({base_name})

        scene = self.scene()
        win = editor_window_of(self)
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
        win = editor_window_of(self)
        if not win:
            super().contextMenuEvent(event)
            return
        has_params = bool(self.cmd_def.get("required", []) or self.cmd_def.get("optional", []))
        self._run_context_menu(event, [
            (t("ctx_rename"),         self._begin_rename,                         True),
            (t("ctx_change_color"),   self._pick_color,                           True),
            (t("ctx_auto_create_params"),
             self.auto_create_required_parameters,
             has_params),
            None,
            (t("ctx_duplicate"),      getattr(win, "duplicate_nodes",      None), True),
            (t("ctx_copy"),           getattr(win, "copy_nodes",           None), True),
            (t("ctx_paste"),          getattr(win, "paste_nodes",          None), True),
            (t("ctx_group_frame"),    getattr(win, "group_selected_nodes", None), True),
            None,
            (t("ctx_delete_node"),    self._delete_self,                          True),
        ])

    def _all_required_params(self):
        """All required and optional parameter sockets on this command, connected or not."""
        result = []
        all_params = self.cmd_def.get("required", []) + self.cmd_def.get("optional", [])
        for param in group_xyz_params(all_params, self.expanded_vectors):
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
        win = editor_window_of(self)
        if not win or not scene:
            return

        all_required = self._all_required_params()
        win._block_undo_push = True
        try:
            command_pos = self.scenePos()
            spawn_y = command_pos.y() + AUTOSPAWN_Y_OFFSET

            for param, socket in all_required:
                try:
                    # If this input is already connected, do not overwrite it or create a new node
                    if any(c.dest is socket for c in win.connections):
                        continue

                    param_name   = param_spec_name(param)
                    param_type   = resolve_param_type(param_name, param)
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
                    log_and_explain(f"Skipped auto-creating parameter {param}", exc)

            self._refresh_connections()
            for p_node in [c.source.meta_node for c in win.connections if c.dest.meta_node is self]:
                p_node._refresh_connections()

        finally:
            win._block_undo_push = False
            win.push_undo_state()
