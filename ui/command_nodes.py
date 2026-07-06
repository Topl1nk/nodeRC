"""command_nodes.py — Execution-Flow Nodes

StartNode roots the chain and carries the Launch control; CommandNode
represents one RealityCapture CLI command with typed parameter sockets and
collapsible X/Y/Z vector groups.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QPushButton
from PyQt5.QtCore import QPointF, Qt

from localization import t
from configuration import (
    NODE_HEADER_HEIGHT, NODE_ROW_HEIGHT, NODE_HORIZONTAL_PAD, NODE_WIDGET_V_OFFSET,
    AUTOSPAWN_X_GAP, AUTOSPAWN_Y_OFFSET, AUTOSPAWN_V_GAP, NODE_START_Z, HOTKEY_HINTS,
)
from ui.theme import PUSHBTN_QSS
from core.node_blueprint import (
    PARAM_TYPE_PREFIX, command_node_def, group_xyz_params, param_spec_name,
    resolve_param_type, start_node_def,
)
from ui.graph_items import MetaNode, editor_window_of
from diagnostics import log_and_explain


class StartNode(MetaNode):
    is_protected = True  # the chain's root: bulk delete and group-clear must spare it
    always_on_top = True  # stays above every other node, even ones brought to front by a drag

    def __init__(self):
        super().__init__(start_node_def())
        self._set_resting_z(NODE_START_Z)
        rows = self.node_def.param_row_count
        btn_w = self.node_def.width - NODE_HORIZONTAL_PAD * 2

        # Project-wide Open/Save/Save As live in the title bar's hamburger
        # menu (see TabStripWidget._show_project_menu) now — only the
        # chain-execution control belongs on the node itself.
        self._launch_btn = QPushButton(t("btn_launch"))
        self._launch_btn.setStyleSheet(PUSHBTN_QSS)
        self._launch_btn.setFixedWidth(btn_w)
        self._launch_btn.setToolTip(HOTKEY_HINTS["execute_chain"])
        self._launch_btn.clicked.connect(self._request_chain_execution)
        proxy = self._make_proxy(self._launch_btn)
        y = NODE_HEADER_HEIGHT + rows * NODE_ROW_HEIGHT + NODE_WIDGET_V_OFFSET
        proxy.setPos(NODE_HORIZONTAL_PAD, y)

    def retranslate(self):
        self._launch_btn.setText(t("btn_launch"))

    def _request_chain_execution(self):
        win = editor_window_of(self)
        if win:
            win.execute_chain()


class CommandNode(MetaNode):
    def __init__(self, cmd_def: dict, expanded_vectors: set = None):
        self.cmd_def = cmd_def
        self.expanded_vectors = expanded_vectors or set()
        super().__init__(command_node_def(cmd_def, self.expanded_vectors))

    def serialize_payload(self) -> dict:
        payload = {"cmd_def": self.cmd_def}
        if self.expanded_vectors:
            payload["expanded_vectors"] = sorted(self.expanded_vectors)
        return payload

    def toggle_vector_expansion(self, base_name: str):
        self.expanded_vectors.symmetric_difference_update({base_name})
        new_node = CommandNode(self.cmd_def, self.expanded_vectors.copy())
        self._swap_node(new_node)

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
            (t("ctx_rename"),         self._begin_rename,                         True, HOTKEY_HINTS["rename"]),
            (t("ctx_change_color"),   self._pick_color,                           True),
            (t("ctx_auto_create_params"),
             self.auto_create_required_parameters,
             has_params),
            None,
            (t("ctx_duplicate"),      getattr(win, "duplicate_nodes",      None), True, HOTKEY_HINTS["duplicate"]),
            (t("ctx_copy"),           getattr(win, "copy_nodes",           None), True, HOTKEY_HINTS["copy"]),
            (t("ctx_paste"),          getattr(win, "paste_nodes",          None), True, HOTKEY_HINTS["paste"]),
            (t("ctx_group_frame"),    getattr(win, "group_selected_nodes", None), True, HOTKEY_HINTS["group"]),
            None,
            (t("ctx_delete_node"),    self._delete_self,                          True, HOTKEY_HINTS["delete"]),
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
        """Create param nodes for every required parameter that isn't already wired.

        Always scans the full required-param list, but skips any input that
        already has an incoming connection so manual wiring is never overwritten.
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
