import re

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QTreeWidget, QTreeWidgetItem, QLabel, QGraphicsView, QGraphicsScene, QSizePolicy, QFrame, QWidget, QApplication
)
from PyQt5.QtCore import Qt, QEvent

from configuration import (
    NODE_BORDER_COLOR, SEARCH_DIALOG_WIDTH,
    SEARCH_DIALOG_HEIGHT, SEARCH_DIALOG_STYLESHEET, SEARCH_RESULTS_LIMIT
)


class SearchMenuDialog(QDialog):
    def __init__(self, command_categories, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setStyleSheet(SEARCH_DIALOG_STYLESHEET)
        self.resize(SEARCH_DIALOG_WIDTH, SEARCH_DIALOG_HEIGHT)
        
        self.payload = None
        self.command_categories = command_categories
        self._all_items = []
        self._anchor_screen_pos = None

        # Remove translucent background so the dialog background color applies
        # self.setAttribute(Qt.WA_TranslucentBackground, True)
        
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(10)
        
        self.info_widget = QWidget()
        info_layout = QVBoxLayout(self.info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(10)

        self.preview_frame = QFrame()
        self.preview_frame.setStyleSheet("background: transparent; border: none;")
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        
        self.preview_scene = QGraphicsScene()
        self.preview_view = QGraphicsView(self.preview_scene)
        self.preview_view.setFrameShape(QFrame.NoFrame)
        self.preview_view.setObjectName("previewView")
        self.preview_view.setMinimumHeight(120)
        self.preview_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.preview_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.preview_view.setInteractive(False)
        self.preview_view.setRenderHint(1)
        preview_layout.addWidget(self.preview_view)
        info_layout.addWidget(self.preview_frame)

        self.desc_frame = QFrame()
        self.desc_frame.setObjectName("descFrame")
        desc_layout = QVBoxLayout(self.desc_frame)
        desc_layout.setContentsMargins(0, 0, 0, 0)
        
        self.desc_label = QLabel("Hover or select a node to see its description.")
        self.desc_label.setObjectName("descriptionLabel")
        self.desc_label.setWordWrap(True)
        self.desc_label.setMinimumHeight(60)
        self.desc_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.desc_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        desc_layout.addWidget(self.desc_label)
        info_layout.addWidget(self.desc_frame)
        info_layout.addStretch()

        self.separator = QFrame()
        self.separator.setFixedWidth(1)
        self.separator.setStyleSheet(f"background-color: {NODE_BORDER_COLOR};")

        self.search_frame = QFrame()
        search_layout = QVBoxLayout(self.search_frame)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(4)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search nodes...")
        self.search_bar.textChanged.connect(self._filter_tree)
        self.search_bar.returnPressed.connect(self._activate_selection)
        self.search_bar.installEventFilter(self)
        search_layout.addWidget(self.search_bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMouseTracking(True)
        self.tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tree.itemSelectionChanged.connect(self._on_item_selected)
        self.tree.itemEntered.connect(self._on_item_hovered)
        self.tree.itemActivated.connect(self._on_item_activated)
        search_layout.addWidget(self.tree)
        
        self.main_layout.addWidget(self.search_frame)
        self.main_layout.addWidget(self.separator)
        self.main_layout.addWidget(self.info_widget)

        self._collect_entries()
        self._render_browse()
        self.search_bar.setFocus()

    def set_anchor_pos(self, pos):
        self._anchor_screen_pos = pos
        screen = QApplication.screenAt(pos)
        if screen:
            screen_geom = screen.availableGeometry()
            self.main_layout.removeWidget(self.info_widget)
            self.main_layout.removeWidget(self.separator)
            self.main_layout.removeWidget(self.search_frame)
            
            # If the menu is near the right edge, we swap: Search on right, Info on left
            if pos.x() + 700 > screen_geom.right():
                self.main_layout.addWidget(self.info_widget)
                self.main_layout.addWidget(self.separator)
                self.main_layout.addWidget(self.search_frame)
            else:
                self.main_layout.addWidget(self.search_frame)
                self.main_layout.addWidget(self.separator)
                self.main_layout.addWidget(self.info_widget)
                
        self._adjust_position()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._anchor_screen_pos:
            self._adjust_position()

    def _adjust_position(self):
        search_frame_pos = self.search_frame.pos()
        new_x = self._anchor_screen_pos.x() - search_frame_pos.x()
        new_y = self._anchor_screen_pos.y() - search_frame_pos.y()
        self.move(new_x, new_y)

    def _collect_entries(self):
        """Build the flat, searchable record set once: each entry carries its node
        payload, its visible label, and the lowercased text matched against."""
        self._param_specs = []   # [(label, payload)] for the browse tree
        self._entries = []       # [{"payload", "label", "haystack"}] for searching

        from nodes_concrete import PARAM_NODE_TYPES
        seen_classes = set()
        for ptype, pclass in PARAM_NODE_TYPES.items():
            if ptype in ("any", "enum_int") or pclass in seen_classes:
                continue
            seen_classes.add(pclass)
            try:
                dummy = pclass()
                title = re.sub('<[^<]+>', '', dummy.node_def.title).strip()
                desc = getattr(dummy.node_def, "description", None) or f"A generic {ptype} parameter."
            except Exception:
                title = f"[P] {ptype.capitalize()}"
                desc = f"A {ptype} parameter."
            payload = {"param_type": ptype, "display": title, "desc": desc}
            self._param_specs.append((title, payload))
            self._entries.append({
                "payload": payload, "label": title,
                "haystack": f"{title} {ptype} {desc}".lower(),
            })

        for subsections in self.command_categories.values():
            for commands in subsections.values():
                for cmd in commands:
                    label = cmd["display"]
                    parts = (label, cmd.get("command", ""), cmd.get("action", ""),
                             cmd.get("action_word", ""),
                             cmd.get("description") or cmd.get("desc") or "")
                    self._entries.append({
                        "payload": cmd, "label": label,
                        "haystack": " ".join(parts).lower(),
                    })

    def _render_browse(self):
        """Empty query: the full, browsable category tree (params, then commands)."""
        self.tree.clear()
        self._all_items = []

        param_cat = QTreeWidgetItem(self.tree, ["[Prm] Parameters"])
        param_cat.setExpanded(True)
        for label, payload in self._param_specs:
            item = QTreeWidgetItem(param_cat, [f"  {label}"])
            item.setData(0, Qt.UserRole, payload)
            self._all_items.append(item)

        cmd_cat = QTreeWidgetItem(self.tree, ["[Cmd] Commands"])
        cmd_cat.setExpanded(True)
        for sec_name, subsections in self.command_categories.items():
            sec_item = QTreeWidgetItem(cmd_cat, [sec_name])
            for subsec_name, commands in subsections.items():
                parent_item = sec_item if subsec_name == "__root__" \
                    else QTreeWidgetItem(sec_item, [subsec_name])
                for cmd in commands:
                    item = QTreeWidgetItem(parent_item, [f"  • {cmd['display']}"])
                    item.setData(0, Qt.UserRole, cmd)
                    self._all_items.append(item)

    def _render_results(self, query):
        """Non-empty query: a flat list ranked best-first, category noise removed."""
        scored = []
        for entry in self._entries:
            score = self._score(query, entry["label"].lower(), entry["haystack"])
            if score is not None:
                scored.append((score, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)

        self.tree.clear()
        self._all_items = []
        for _, entry in scored[:SEARCH_RESULTS_LIMIT]:
            item = QTreeWidgetItem(self.tree, [f"  {entry['label']}"])
            item.setData(0, Qt.UserRole, entry["payload"])
            self._all_items.append(item)

        if self._all_items:
            self._select_first_match()
        else:
            self.tree.clearSelection()
            self.desc_label.setText("No matching nodes.")
            self.preview_scene.clear()

    @staticmethod
    def _subseq_score(needle, text):
        """Score a fuzzy subsequence match (rewarding contiguity and word starts);
        None when `needle` is not a subsequence of `text`."""
        score = 0.0
        cursor = 0
        prev = -1
        for char in needle:
            idx = text.find(char, cursor)
            if idx == -1:
                return None
            if idx == prev + 1:
                score += 4
            if idx == 0 or text[idx - 1] in " _-([":
                score += 6
            prev = idx
            cursor = idx + 1
        return score

    def _score(self, query, label, haystack):
        """Relevance of one entry to the query; None when it does not match.
        Prefers label prefix > label substring > all keywords present > fuzzy."""
        tokens = query.split()
        if all(token in haystack for token in tokens):
            score = 100.0
            if label.startswith(query):
                score += 500
            elif query in label:
                score += 300
            elif all(token in label for token in tokens):
                score += 180
            elif any(token in label for token in tokens):
                score += 90
            return score - len(label) * 0.5

        compact = query.replace(" ", "")
        fuzzy = self._subseq_score(compact, label)
        if fuzzy is not None:
            return 40 + fuzzy - len(label) * 0.3
        fuzzy = self._subseq_score(compact, haystack)
        if fuzzy is not None:
            return fuzzy
        return None

    def _filter_tree(self, text):
        query = " ".join(text.lower().split())
        if query:
            self._render_results(query)
        else:
            self._render_browse()
            self.tree.clearSelection()

    def _visible_leaves(self):
        return [it for it in self._all_items
                if not it.isHidden() and it.data(0, Qt.UserRole)]

    def _select_leaf(self, item):
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)

    def _select_first_match(self):
        leaves = self._visible_leaves()
        if leaves:
            self._select_leaf(leaves[0])

    def _move_selection(self, delta: int):
        leaves = self._visible_leaves()
        if not leaves:
            return
        current = self.tree.currentItem()
        index = leaves.index(current) if current in leaves else -1
        self._select_leaf(leaves[max(0, min(len(leaves) - 1, index + delta))])

    def _activate_selection(self):
        current = self.tree.currentItem()
        if current not in self._visible_leaves():
            leaves = self._visible_leaves()
            current = leaves[0] if leaves else None
        if current is not None:
            self._on_item_activated(current, 0)

    def eventFilter(self, obj, event):
        if obj is self.search_bar and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Down:
                self._move_selection(1)
                return True
            if event.key() == Qt.Key_Up:
                self._move_selection(-1)
                return True
        return super().eventFilter(obj, event)

    def _on_item_hovered(self, item, column):
        self._update_preview_and_desc(item)

    def _on_item_selected(self):
        selected = self.tree.selectedItems()
        if selected:
            self._update_preview_and_desc(selected[0])
        else:
            self.desc_label.setText("")
            self.preview_scene.clear()

    def _update_preview_and_desc(self, item):
        item_payload = item.data(0, Qt.UserRole)
        if not item_payload:
            self.desc_label.setText("")
            self.preview_scene.clear()
            return
            
        desc = item_payload.get("description") or item_payload.get("desc") or "No description available."
        if "command" in item_payload:
            cmd_name = item_payload["command"]
            self.desc_label.setText(f"<b>{cmd_name}</b><br>{desc}")
        else:
            self.desc_label.setText(desc)
            
        self.preview_scene.clear()
        
        node = None
        from nodes_concrete import CommandNode, PARAM_NODE_TYPES

        if "command" in item_payload:
            node = CommandNode(item_payload)
        elif "param_type" in item_payload:
            pclass = PARAM_NODE_TYPES.get(item_payload["param_type"])
            if pclass:
                node = pclass()
            
        if node:
            self.preview_scene.addItem(node)
            # Why: QTimer.singleShot(0) defers execution until the view updates its geometry, ensuring fitInView works correctly.
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._center_preview(node))
            
    def _center_preview(self, node):
        if self.preview_view and node:
            # Why: prevents clipping of node boundaries and sockets.
            rect = self.preview_scene.itemsBoundingRect().adjusted(-15, -15, 15, 15)
            self.preview_view.fitInView(rect, Qt.KeepAspectRatio)

    def _on_item_activated(self, item, column):
        item_payload = item.data(0, Qt.UserRole)
        if item_payload:
            self.payload = item_payload
            self.accept()
