from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QTreeWidget, QTreeWidgetItem, QLabel, QGraphicsView, QGraphicsScene, QSizePolicy, QFrame, QWidget, QApplication
)
from PyQt5.QtCore import Qt

from configuration import (
    CANVAS_BACKGROUND_COLOR, BUTTON_BG_COLOR, NODE_BORDER_COLOR, 
    NODE_SELECTED_COLOR, TEXT_COLOR, TEXT_MUTED_COLOR
)

SEARCH_DIALOG_STYLESHEET = f"""
QDialog {{
    background-color: {CANVAS_BACKGROUND_COLOR};
    border: 1px solid {NODE_BORDER_COLOR};
}}
QLineEdit {{
    background-color: {BUTTON_BG_COLOR};
    color: {TEXT_COLOR};
    border: 1px solid {NODE_BORDER_COLOR};
    padding: 4px;
    font-family: Consolas, monospace;
}}
QLineEdit:focus {{
    border: 1px solid {NODE_SELECTED_COLOR};
}}
QTreeWidget {{
    background-color: transparent;
    color: {TEXT_COLOR};
    border: none;
    font-family: Consolas, monospace;
    outline: none;
}}
QTreeWidget::item:hover {{
    background-color: {BUTTON_BG_COLOR};
}}
QTreeWidget::item:selected {{
    background-color: {NODE_BORDER_COLOR};
    color: {TEXT_COLOR};
}}
QGraphicsView#previewView {{
    background: transparent;
    border: none;
}}
QLabel#descriptionLabel {{
    color: {TEXT_MUTED_COLOR};
    font-family: Consolas, monospace;
    padding: 6px;
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 14px;
    margin: 0px 0px 0px 0px;
}}
QScrollBar::handle:vertical {{
    background: {NODE_BORDER_COLOR};
    min-height: 20px;
    border-radius: 7px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
"""

class SearchMenuDialog(QDialog):
    def __init__(self, command_categories, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setStyleSheet(SEARCH_DIALOG_STYLESHEET)
        self.resize(700, 450)
        
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

        # Block 1: Node Preview
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
        self.preview_view.setRenderHint(1) # Antialiasing
        preview_layout.addWidget(self.preview_view)
        info_layout.addWidget(self.preview_frame)

        # Block 2: Description
        self.desc_frame = QFrame()
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
        info_layout.addStretch() # Push everything up

        # Vertical Separator
        self.separator = QFrame()
        self.separator.setFixedWidth(1)
        self.separator.setStyleSheet(f"background-color: {NODE_BORDER_COLOR};")

        # Block 3: Search + Tree
        self.search_frame = QFrame()
        search_layout = QVBoxLayout(self.search_frame)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(4)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search nodes...")
        self.search_bar.textChanged.connect(self._filter_tree)
        search_layout.addWidget(self.search_bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMouseTracking(True)
        self.tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tree.itemSelectionChanged.connect(self._on_item_selected)
        self.tree.itemEntered.connect(self._on_item_hovered)
        self.tree.itemActivated.connect(self._on_item_activated)
        search_layout.addWidget(self.tree)
        
        # Default order (will be overridden in set_anchor_pos)
        self.main_layout.addWidget(self.search_frame)
        self.main_layout.addWidget(self.separator)
        self.main_layout.addWidget(self.info_widget)

        self._populate_tree()
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
        # Anchor the search bar's top-left to the screen pos
        search_frame_pos = self.search_frame.pos()
        new_x = self._anchor_screen_pos.x() - search_frame_pos.x()
        new_y = self._anchor_screen_pos.y() - search_frame_pos.y()
        self.move(new_x, new_y)

    def _populate_tree(self):
        # Add parameter nodes first
        param_cat = QTreeWidgetItem(self.tree, ["[Prm] Parameters"])
        param_cat.setExpanded(True)
        
        from nodes import PARAM_NODE_TYPES
        seen_classes = set()
        for ptype, pclass in PARAM_NODE_TYPES.items():
            if ptype in ("any", "enum_int"): continue
            if pclass in seen_classes: continue
            seen_classes.add(pclass)
            
            try:
                # Instantiate briefly just to read title and description
                dummy = pclass()
                title = dummy.node_def.title
                import re
                title = re.sub('<[^<]+>', '', title).strip() # Strip HTML tags
                desc = getattr(dummy.node_def, "description", None) or f"A generic {ptype} parameter."
            except Exception as e:
                title = f"[P] {ptype.capitalize()}"
                desc = f"A {ptype} parameter."
                
            item = QTreeWidgetItem(param_cat, [f"  {title}"])
            item.setData(0, Qt.UserRole, {"param_type": ptype, "display": title, "desc": desc})
            self._all_items.append(item)

        # Add command nodes
        cmd_cat = QTreeWidgetItem(self.tree, ["[Cmd] Commands"])
        cmd_cat.setExpanded(True)

        for sec_name, subsections in self.command_categories.items():
            sec_item = QTreeWidgetItem(cmd_cat, [sec_name])
            for subsec_name, commands in subsections.items():
                parent_item = sec_item
                if subsec_name != "__root__":
                    parent_item = QTreeWidgetItem(sec_item, [subsec_name])
                    
                for cmd in commands:
                    item = QTreeWidgetItem(parent_item, [f"  > {cmd['display']}"])
                    item.setData(0, Qt.UserRole, cmd)
                    self._all_items.append(item)

    def _filter_tree(self, text):
        query = text.lower()
        for item in self._all_items:
            data = item.data(0, Qt.UserRole)
            if not data: continue
            
            display_text = ""
            if "command" in data:
                display_text = data["display"].lower() + " " + data.get("action_word", "").lower()
            elif "param_type" in data:
                display_text = data["display"].lower()

            match = query in display_text
            item.setHidden(not match)
            
            # Show/hide parent categories based on children visibility
            parent = item.parent()
            while parent:
                parent.setHidden(False)
                parent.setExpanded(True if query else False)
                parent = parent.parent()

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
        data = item.data(0, Qt.UserRole)
        if not data:
            self.desc_label.setText("")
            self.preview_scene.clear()
            return
            
        # Update Description
        desc = data.get("description") or data.get("desc") or "No description available."
        if "command" in data:
            cmd_name = data["command"]
            self.desc_label.setText(f"<b>{cmd_name}</b><br>{desc}")
        else:
            self.desc_label.setText(desc)
            
        # Update Preview
        self.preview_scene.clear()
        
        node = None
        from nodes import (
            CommandNode, StringParamNode, BoolParamNode, IntParamNode,
            EnumParamNode, PathParamNode, KeyValueParamNode
        )
        
        if "command" in data:
            node = CommandNode(data)
        elif "param_type" in data:
            ptype = data["param_type"]
            from nodes import PARAM_NODE_TYPES
            pclass = PARAM_NODE_TYPES.get(ptype)
            if pclass:
                try:
                    node = pclass()
                except TypeError:
                    node = pclass()
            
        if node:
            self.preview_scene.addItem(node)
            # Center the node in the view
            # Using QTimer.singleShot to allow the view to update its geometry first
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._center_preview(node))
            
    def _center_preview(self, node):
        if self.preview_view and node:
            # Add a margin to ensure no border clipping of the node and its sockets
            rect = self.preview_scene.itemsBoundingRect().adjusted(-15, -15, 15, 15)
            self.preview_view.fitInView(rect, Qt.KeepAspectRatio)

    def _on_item_activated(self, item, column):
        data = item.data(0, Qt.UserRole)
        if data:
            self.payload = data
            self.accept()
