"""project_tab.py — Per-Tab Document State

Each open project lives in one ProjectTab: its own graph scene, connection
list, undo history and dirty/path bookkeeping. NodeEditorWindow holds a list
of these and proxies scene/connections/_block_undo_push through to whichever
tab is active, so every other module that reaches through
win.scene/win.connections/win._block_undo_push keeps working unchanged.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from ui.scene import NodeScene
from ui.graph_items import Connection


class ProjectTab:
    def __init__(self, scene: NodeScene, untitled_number: Optional[int] = None):
        self.tab_id: str = uuid.uuid4().hex
        self.scene: NodeScene = scene
        self.connections: List[Connection] = []
        self.history: List[dict] = []
        self.history_index: int = -1
        self.project_path: Optional[str] = None
        self.dirty: bool = False
        self._block_undo_push: bool = False
        # Assigned by the window at creation time for "Untitled N" display
        # while project_path is None; irrelevant once the tab is saved.
        self.untitled_number: Optional[int] = untitled_number
