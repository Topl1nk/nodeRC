"""search_menu.py — Node Spawning Palette

Fuzzy-searchable catalog of commands and parameter nodes with a live node
preview; the primary way nodes get onto the canvas.
"""
import re

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QTreeWidget, QTreeWidgetItem, QLabel, QGraphicsView, QGraphicsScene, QSizePolicy, QFrame, QWidget, QApplication
)
from PyQt5.QtCore import Qt, QEvent, QTimer, QSize
from PyQt5.QtGui import QPainter, QColor, QPixmap, QIcon

from configuration import (
    SEARCH_DIALOG_WIDTH,
    SEARCH_DIALOG_HEIGHT, SEARCH_RESULTS_LIMIT,
)
from ui.theme import NODE_BORDER_COLOR, TEXT_MUTED_COLOR, SEARCH_DIALOG_STYLESHEET, apply_field_placeholder_palette
from localization import t
from ui.param_nodes import PARAM_NODE_TYPES
from ui.command_nodes import CommandNode
from core.node_blueprint import resolve_param_type, resolve_color_schema
from core.app_prefs import get_search_usage, get_search_usage_after, record_search_usage
from diagnostics import log_and_explain

SUGGESTION_LIMIT = 6
_SWATCH_DIAMETER = 10

# One dot per socket color, built once and reused — the same color
# vocabulary already painted on every socket/wire on the canvas
# (SOCKET_COLOR_SCHEMA), so a row reads by its color at a glance instead of
# needing a "[Prm]"/"[Cmd]" text tag to say what it is.
_swatch_icon_cache: dict = {}


def _swatch_icon(hex_color: str) -> QIcon:
    icon = _swatch_icon_cache.get(hex_color)
    if icon is None:
        pixmap = QPixmap(_SWATCH_DIAMETER, _SWATCH_DIAMETER)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(hex_color))
        painter.drawEllipse(0, 0, _SWATCH_DIAMETER, _SWATCH_DIAMETER)
        painter.end()
        icon = QIcon(pixmap)
        _swatch_icon_cache[hex_color] = icon
    return icon


def _entry_color(payload: dict) -> str:
    """The same socket color this payload's node would show on canvas —
    per-type for a param, the flat exec grey for a command."""
    if "param_type" in payload:
        return resolve_color_schema(payload["param_type"])["socket"]
    return resolve_color_schema("exec")["socket"]



class SearchMenuDialog(QDialog):
    def __init__(self, command_categories, parent=None, source_socket=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setStyleSheet(SEARCH_DIALOG_STYLESHEET)
        self.resize(SEARCH_DIALOG_WIDTH, SEARCH_DIALOG_HEIGHT)

        self.payload = None
        self.command_categories = command_categories
        self._all_items = []
        self._suggestion_items = []
        self._anchor_screen_pos = None

        # The socket this menu was opened from (drag-release / click-to-spawn)
        # drives all context ranking below — None for a plain right-click on
        # empty canvas, which gets no ranking bias at all.
        self.source_socket = source_socket
        self._context_key = self._compute_context_key(source_socket)
        self._usage = get_search_usage()
        self._usage_after = get_search_usage_after()

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
        self.preview_view.setRenderHint(QPainter.Antialiasing)
        preview_layout.addWidget(self.preview_view)
        info_layout.addWidget(self.preview_frame)

        self.desc_frame = QFrame()
        self.desc_frame.setObjectName("descFrame")
        desc_layout = QVBoxLayout(self.desc_frame)
        desc_layout.setContentsMargins(0, 0, 0, 0)
        
        self.desc_label = QLabel(t("manual_html"))
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
        self.search_bar.setPlaceholderText(t("search_placeholder"))
        apply_field_placeholder_palette(self.search_bar)
        self.search_bar.textChanged.connect(self._filter_tree)
        self.search_bar.returnPressed.connect(self._activate_selection)
        self.search_bar.installEventFilter(self)
        search_layout.addWidget(self.search_bar)

        from ui.scrollbar import UnifiedScrollBar
        self.tree = QTreeWidget()
        self.tree.setVerticalScrollBar(UnifiedScrollBar())
        self.tree.setHeaderHidden(True)
        self.tree.setMouseTracking(True)
        self.tree.setIconSize(QSize(_SWATCH_DIAMETER, _SWATCH_DIAMETER))
        self.tree.setIndentation(14)
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
        self._adjust_position()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._anchor_screen_pos:
            self._adjust_position()

    def _adjust_position(self):
        # Search bar + tree always sit on the left, preview + description
        # always on the right (the fixed order main_layout was built with in
        # __init__) — this used to swap sides near the right screen edge,
        # which made the menu land in a different spot every time and broke
        # the muscle memory of "type immediately, look right for the
        # preview". Clamping the window position instead keeps that layout
        # fixed and just slides the whole popup back on-screen.
        search_frame_pos = self.search_frame.pos()
        new_x = self._anchor_screen_pos.x() - search_frame_pos.x()
        new_y = self._anchor_screen_pos.y() - search_frame_pos.y()
        screen = QApplication.screenAt(self._anchor_screen_pos)
        if screen:
            geom = screen.availableGeometry()
            new_x = max(geom.left(), min(new_x, geom.right() - self.width()))
            new_y = max(geom.top(), min(new_y, geom.bottom() - self.height()))
        self.move(new_x, new_y)

    @staticmethod
    def _compute_context_key(source_socket):
        """Identifies "what this menu was opened from", for the usage-after
        bigram: the owning command's name for an exec socket, "start" for
        the chain root, or None for a param socket / plain right-click —
        param context is ranked by type compatibility instead (see
        _is_compatible), which needs no history."""
        if source_socket is None or not source_socket.sock_def.is_exec:
            return None
        node = source_socket.meta_node
        cmd_def = getattr(node, "cmd_def", None)
        if cmd_def:
            return f"cmd:{cmd_def.get('command', '')}"
        return "start"

    @staticmethod
    def _usage_key(payload):
        if "command" in payload:
            return f"cmd:{payload.get('command', '')}"
        if "param_type" in payload:
            return f"param:{payload['param_type']}"
        return None

    @staticmethod
    def _payload_param_types(payload):
        """Every data type this command's required/optional params accept —
        derived straight from cmd_def, no node instantiation needed."""
        types = set()
        for key in ("required", "optional"):
            for param in payload.get(key, []):
                name = param if isinstance(param, str) else param.get("name", "")
                types.add(resolve_param_type(name, param) if isinstance(param, dict) else "string")
        return types

    def _is_compatible(self, payload):
        """Whether ``payload`` matches the drag source's data type — only
        meaningful for a param (non-exec) source, where sockets carry a real
        type; an exec source (chain flow) reports every command compatible,
        since virtually all of them are, and lets usage ranking sort instead."""
        if self.source_socket is None or self.source_socket.sock_def.is_exec:
            return True
        src_type = self.source_socket.sock_def.param_type
        if self.source_socket.sock_def.kind == "output":
            return "command" not in payload or src_type in self._payload_param_types(payload)
        return payload.get("param_type") == src_type

    def _score_components(self, payload):
        """(usage_score, compat_bonus) for one entry. usage_score reflects
        prior picks — raw popularity plus the "usually follows this node"
        bigram for the current exec context; compat_bonus rewards a real
        data-type match on a param source. Kept apart because the two
        callers weight them differently: the Suggested shortlist only fires
        on real usage_score (so a fresh install shows nothing rather than an
        arbitrary top-N), while search ranking blends both into one score."""
        usage_score = 0.0
        key = self._usage_key(payload)
        if key:
            usage_score += min(self._usage.get(key, 0), 20) * 3
            if self._context_key:
                usage_score += min(self._usage_after.get(self._context_key, {}).get(key, 0), 20) * 15
        compat_bonus = 40.0 if self._is_compatible(payload) else 0.0
        return usage_score, compat_bonus

    def _rank_bonus(self, payload):
        usage_score, compat_bonus = self._score_components(payload)
        return usage_score + compat_bonus

    def _ranked_suggestions(self, limit=SUGGESTION_LIMIT):
        scored = []
        for entry in self._entries:
            usage_score, compat_bonus = self._score_components(entry["payload"])
            if usage_score > 0:
                scored.append((usage_score + compat_bonus, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    def _apply_compat_style(self, item, payload):
        """Dims an entry whose data type can't actually feed the drag
        source — a passive hint, never a filter; every node stays clickable."""
        if (self.source_socket is not None and not self.source_socket.sock_def.is_exec
                and not self._is_compatible(payload)):
            item.setForeground(0, QColor(TEXT_MUTED_COLOR))

    def _collect_entries(self):
        """Build the flat, searchable record set once: each entry carries its node
        payload, its visible label, and the lowercased text matched against."""
        self._param_specs = []   # [(label, payload)] for the browse tree
        self._entries = []       # [{"payload", "label", "haystack"}] for searching

        seen_classes = set()
        for ptype, pclass in PARAM_NODE_TYPES.items():
            if ptype in ("any", "enum_int") or pclass in seen_classes:
                continue
            seen_classes.add(pclass)
            try:
                dummy = pclass()
                title = re.sub('<[^<]+>', '', dummy.node_def.title).strip()
                desc = getattr(dummy.node_def, "description", None) or f"A generic {ptype} parameter."
            except Exception as exc:
                # A broken param node class degrades to placeholder text here
                # rather than crashing the search menu — but that must never
                # happen silently, or a real construction bug in a node class
                # stays invisible in the search results with no clue why.
                log_and_explain(f"Search menu: {pclass.__name__}() failed while building its entry", exc)
                title = f"[P] {ptype.capitalize()}"
                desc = f"A {ptype} parameter."
            payload = {"param_type": ptype, "display": title, "desc": desc}
            self._param_specs.append((title, payload))
            self._entries.append({
                "payload": payload, "label": title,
                "haystack": f"{title} {ptype} {desc}".lower(),
            })

        for pack_sections in self.command_categories.values():
            for subsections in pack_sections.values():
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
        """Empty query: a Suggested shortlist (only once there's usage
        history for this context) on top, expanded; every other category
        collapsed to its header. The old layout expanded every param and
        every command pack immediately — dozens of rows all competing for
        attention before the user typed a single character. Typing is the
        primary path (the search bar has focus and a placeholder inviting
        it); browsing a specific collapsed category is the fallback, one
        click away, not the default view."""
        self.tree.clear()
        self._all_items = []
        self._suggestion_items = []

        suggestions = self._ranked_suggestions()
        if suggestions:
            sug_cat = QTreeWidgetItem(self.tree, [f"★ {t('tree_header_suggested')}"])
            sug_cat.setExpanded(True)
            self._style_category_header(sug_cat)
            for idx, entry in enumerate(suggestions):
                item = QTreeWidgetItem(sug_cat, [f"{idx + 1}   {entry['label']}"])
                item.setIcon(0, _swatch_icon(_entry_color(entry["payload"])))
                item.setData(0, Qt.UserRole, entry["payload"])
                self._apply_compat_style(item, entry["payload"])
                self._all_items.append(item)
                self._suggestion_items.append(item)

        param_cat = QTreeWidgetItem(self.tree, [t("tree_header_params")])
        self._style_category_header(param_cat)
        for label, payload in self._param_specs:
            item = QTreeWidgetItem(param_cat, [label])
            item.setIcon(0, _swatch_icon(_entry_color(payload)))
            item.setData(0, Qt.UserRole, payload)
            self._apply_compat_style(item, payload)
            self._all_items.append(item)

        exec_color = resolve_color_schema("exec")["socket"]
        for pack_name, pack_sections in self.command_categories.items():
            pack_item = QTreeWidgetItem(self.tree, [pack_name])
            self._style_category_header(pack_item)
            for sec_name, subsections in pack_sections.items():
                sec_item = QTreeWidgetItem(pack_item, [sec_name])
                self._style_category_header(sec_item)
                for subsec_name, commands in subsections.items():
                    parent_item = sec_item
                    if subsec_name != "__root__":
                        parent_item = QTreeWidgetItem(sec_item, [subsec_name])
                        self._style_category_header(parent_item)
                    for cmd in commands:
                        item = QTreeWidgetItem(parent_item, [cmd["display"]])
                        item.setIcon(0, _swatch_icon(exec_color))
                        item.setData(0, Qt.UserRole, cmd)
                        self._apply_compat_style(item, cmd)
                        self._all_items.append(item)

        if suggestions:
            self._select_first_match()

    @staticmethod
    def _style_category_header(item):
        """Bold, muted — a header reads as chrome to skim past, not content
        to parse, now that it no longer carries a "[Prm]"/"[Cmd]" text tag."""
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setForeground(0, QColor(TEXT_MUTED_COLOR))

    def _render_results(self, query):
        """Non-empty query: a flat list ranked best-first, category noise
        removed. Usage/compatibility nudge the ranking but never hide a
        match — the compat dimming still marks the unlikely ones."""
        self._suggestion_items = []
        scored = []
        for entry in self._entries:
            score = self._score(query, entry["label"].lower(), entry["haystack"])
            if score is not None:
                scored.append((score + self._rank_bonus(entry["payload"]), entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)

        self.tree.clear()
        self._all_items = []
        for _, entry in scored[:SEARCH_RESULTS_LIMIT]:
            item = QTreeWidgetItem(self.tree, [entry["label"]])
            item.setIcon(0, _swatch_icon(_entry_color(entry["payload"])))
            item.setData(0, Qt.UserRole, entry["payload"])
            self._apply_compat_style(item, entry["payload"])
            self._all_items.append(item)

        if self._all_items:
            self._select_first_match()
        else:
            self.tree.clearSelection()
            self.desc_label.setText(t("msg_no_matching_nodes"))
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
            # A bare digit (1-6) instantly places the matching Suggested
            # entry — only while the search bar is still empty, so it never
            # steals a digit the user is actually typing into a query.
            if not self.search_bar.text() and self._suggestion_items:
                digit = event.key() - Qt.Key_1
                if 0 <= digit < len(self._suggestion_items):
                    self._on_item_activated(self._suggestion_items[digit], 0)
                    return True
        return super().eventFilter(obj, event)

    def _on_item_hovered(self, item, column):
        self._update_preview_and_desc(item)

    def _on_item_selected(self):
        selected = self.tree.selectedItems()
        if selected:
            self._update_preview_and_desc(selected[0])
        else:
            self.desc_label.setText(t("manual_html"))
            self.preview_scene.clear()

    def _update_preview_and_desc(self, item):
        item_payload = item.data(0, Qt.UserRole)
        if not item_payload:
            self.desc_label.setText(t("manual_html"))
            self.preview_scene.clear()
            return
            
        desc = item_payload.get("description") or item_payload.get("desc") or t("msg_no_description")
        if "command" in item_payload:
            cmd_name = item_payload["command"]
            self.desc_label.setText(f"<b>{cmd_name}</b><br>{desc}")
        else:
            self.desc_label.setText(desc)
            
        self.preview_scene.clear()

        node = None
        if "command" in item_payload:
            node = CommandNode(item_payload)
        elif "param_type" in item_payload:
            pclass = PARAM_NODE_TYPES.get(item_payload["param_type"])
            if pclass:
                node = pclass()

        if node:
            self.preview_scene.addItem(node)
            # Why: QTimer.singleShot(0) defers execution until the view updates its geometry, ensuring fitInView works correctly.
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
            key = self._usage_key(item_payload)
            if key:
                record_search_usage(key, self._context_key)
            self.accept()
