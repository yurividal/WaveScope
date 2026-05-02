"""AP-group sidebar widget.

Displays discovered access points grouped by BSSID affinity (physical AP)
and lets the user filter the main table to show or hide specific APs.
"""

from .core import *


class APGroupSidebar(QWidget):
    """
    Collapsible sidebar listing physical access points grouped by BSSID
    affinity.  Two BSSIDs belong to the same physical AP when their first
    5½ octets match (low nibble of last octet masked).

    Signals
    -------
    group_include_requested(key, label)
        Emitted when the user wants to show *only* this AP group.
        key=="" means the user deselected — clear the include filter.
    group_exclude_requested(key)
        Emitted when the user wants to hide an AP group.
    group_unexclude_requested(key)
        Emitted when the user wants to un-hide a previously hidden group.
    """

    group_include_requested = pyqtSignal(str, str)   # (group_key, display_label)
    group_exclude_requested = pyqtSignal(str)         # group_key
    group_unexclude_requested = pyqtSignal(str)       # group_key

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(130)
        self.setMaximumWidth(270)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header bar ────────────────────────────────────────────────────
        self._header = QWidget()
        self._header.setFixedHeight(30)
        hbl = QHBoxLayout(self._header)
        hbl.setContentsMargins(8, 3, 6, 3)
        self._lbl_header = QLabel("Access Points")
        self._lbl_header.setStyleSheet(
            f"color:{BTN_ACCENT}; font-weight:600; font-size:10pt;"
        )
        hbl.addWidget(self._lbl_header)
        hbl.addStretch()
        layout.addWidget(self._header)

        # ── Separator ─────────────────────────────────────────────────────
        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.Shape.HLine)
        self._sep.setFrameShadow(QFrame.Shadow.Plain)
        layout.addWidget(self._sep)

        # ── AP list ───────────────────────────────────────────────────────
        self._list = QListWidget()
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_ctx_menu)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

        # ── Internal state ────────────────────────────────────────────────
        # group_key → (display_label, bssid_count)
        self._group_data: Dict[str, Tuple[str, int]] = {}
        self._selected_key: Optional[str] = None
        self._excluded_keys: set = set()
        self._total_ap_count: int = 0

        # Apply initial theme based on current palette
        _initial_dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        self.apply_theme(_initial_dark)

        # Insert the permanent "All APs" row immediately
        self._insert_all_row(0)

    # ── Theme ─────────────────────────────────────────────────────────────

    def apply_theme(self, is_dark: bool) -> None:
        """Re-style the sidebar for dark or light mode."""
        if is_dark:
            list_bg  = MENU_BG
            list_fg  = MENU_TEXT
            list_sel = MENU_SELECTED
            sel_fg   = "#e8f0ff"
            sep_col  = MENU_BORDER
            hdr_col  = BTN_ACCENT
        else:
            list_bg  = "#f0f4fa"
            list_fg  = "#1a2a3a"
            list_sel = "#cde0f7"
            sel_fg   = "#0a1a2a"
            sep_col  = "#c0cce0"
            hdr_col  = "#2a60a0"

        self._lbl_header.setStyleSheet(
            f"color:{hdr_col}; font-weight:600; font-size:10pt;"
        )
        self._sep.setStyleSheet(f"color:{sep_col};")
        self._list.setStyleSheet(
            f"QListWidget {{"
            f"  background:{list_bg};"
            f"  border:none;"
            f"  color:{list_fg};"
            f"  font-size:10pt;"
            f"}}"
            f"QListWidget::item {{"
            f"  padding:3px 8px;"
            f"}}"
            f"QListWidget::item:hover {{"
            f"  background:{list_sel};"
            f"}}"
            f"QListWidget::item:selected {{"
            f"  background:{list_sel};"
            f"  color:{sel_fg};"
            f"}}"
        )

    # ── Public API ────────────────────────────────────────────────────────

    _ALL_KEY = "__all__"  # sentinel used as UserRole data for the All APs row

    def _insert_all_row(self, total: int) -> None:
        """(Re)insert the All APs row at position 0."""
        item = QListWidgetItem(f"All APs  ({total})")
        item.setData(Qt.ItemDataRole.UserRole, self._ALL_KEY)
        f = item.font()
        f.setBold(True)
        item.setFont(f)
        item.setForeground(QColor(BTN_ACCENT))
        self._list.insertItem(0, item)

    def update_groups(self, aps: List[AccessPoint]) -> None:
        """Rebuild the AP group list from *aps*.  O(n); list is only
        redrawn when the group composition actually changes."""
        # Compute groups: group_key → (manufacturer, set-of-bssids)
        raw: Dict[str, Tuple[str, set]] = {}
        for ap in aps:
            key = ap_group_key(ap.bssid)
            if key not in raw:
                raw[key] = (ap.manufacturer, set())
            raw[key][1].add(ap.bssid)

        # Build (label, count) per group
        new_data: Dict[str, Tuple[str, int]] = {
            key: (ap_group_display_label(key, manuf), len(bssids))
            for key, (manuf, bssids) in raw.items()
        }

        if new_data == self._group_data:
            # Groups unchanged but total count may have shifted — refresh All row
            new_total = sum(v[1] for v in new_data.values())
            if new_total != self._total_ap_count:
                self._total_ap_count = new_total
                self._refresh_all_row()
            return  # nothing else changed — skip list widget rebuild

        self._group_data = new_data
        self._total_ap_count = sum(v[1] for v in new_data.values())
        self._rebuild_list()
        self._lbl_header.setText(f"Access Points ({len(new_data)})")

    def set_active_group(self, key: Optional[str]) -> None:
        """Sync the sidebar highlight to an externally applied include filter."""
        self._selected_key = key
        self._list.blockSignals(True)
        try:
            self._list.clearSelection()
            target = key if key is not None else self._ALL_KEY
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == target:
                    item.setSelected(True)
                    break
        finally:
            self._list.blockSignals(False)

    def mark_group_excluded(self, key: str, excluded: bool) -> None:
        """Update the visual dim/undim state for a hidden/visible group."""
        if excluded:
            self._excluded_keys.add(key)
        else:
            self._excluded_keys.discard(key)
        self._update_item_style(key)

    def clear_all_filters(self) -> None:
        """Reset all selection and excluded-key state."""
        self._selected_key = None
        self._excluded_keys.clear()
        self._list.blockSignals(True)
        try:
            self._list.clearSelection()
            # Re-select the All APs row
            if self._list.count() > 0:
                self._list.item(0).setSelected(True)
        finally:
            self._list.blockSignals(False)
        for i in range(1, self._list.count()):
            item = self._list.item(i)
            if item:
                item.setForeground(QColor(MENU_TEXT))

    # ── Internal helpers ──────────────────────────────────────────────────

    def _rebuild_list(self) -> None:
        prev_key = self._selected_key
        self._list.blockSignals(True)
        try:
            self._list.clear()
            # ── All APs row (always at top) ───────────────────────────────
            self._insert_all_row(self._total_ap_count)
            if prev_key is None:
                self._list.item(0).setSelected(True)
            # ── Per-group rows ────────────────────────────────────────────
            # Sort: excluded groups last, then by count desc, then by label
            sorted_items = sorted(
                self._group_data.items(),
                key=lambda x: (x[0] in self._excluded_keys, -x[1][1], x[1][0]),
            )
            for key, (label, count) in sorted_items:
                item = QListWidgetItem(f"{label}  ({count})")
                item.setData(Qt.ItemDataRole.UserRole, key)
                if key in self._excluded_keys:
                    item.setForeground(QColor(TABLE_LINGER_FG))
                if key == prev_key:
                    item.setSelected(True)
                self._list.addItem(item)
        finally:
            self._list.blockSignals(False)

    def _refresh_all_row(self) -> None:
        """Update just the count on the All APs row without rebuilding everything."""
        if self._list.count() > 0:
            item = self._list.item(0)
            if item and item.data(Qt.ItemDataRole.UserRole) == self._ALL_KEY:
                item.setText(f"All APs  ({self._total_ap_count})")

    def _update_item_style(self, key: str) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == key:
                if key in self._excluded_keys:
                    item.setForeground(QColor(TABLE_LINGER_FG))
                else:
                    item.setForeground(QColor(MENU_TEXT))
                break

    # ── Qt event handlers ─────────────────────────────────────────────────

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        if key == self._ALL_KEY:
            # All APs row — clear any include filter
            self._selected_key = None
            self._list.blockSignals(True)
            try:
                self._list.clearSelection()
                item.setSelected(True)
            finally:
                self._list.blockSignals(False)
            self.group_include_requested.emit("", "")
            return
        label, _ = self._group_data.get(key, (key, 0))
        if key == self._selected_key:
            # Second click on same AP row → back to All APs
            self._selected_key = None
            self._list.blockSignals(True)
            try:
                self._list.clearSelection()
                if self._list.count() > 0:
                    self._list.item(0).setSelected(True)
            finally:
                self._list.blockSignals(False)
            self.group_include_requested.emit("", "")
        else:
            self._selected_key = key
            self.group_include_requested.emit(key, label)

    def _on_ctx_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if key == self._ALL_KEY:
            return  # no context menu for the All APs row
        label, _ = self._group_data.get(key, (key, 0))

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{MENU_BG};border:1px solid {MENU_BORDER};"
            f"color:{MENU_TEXT};}}"
            f"QMenu::item:selected{{background:{MENU_SELECTED};}}"
        )

        act_show = menu.addAction("👁  Show only this AP")
        act_show.triggered.connect(
            lambda checked, k=key, l=label: self._do_show_only(k, l)
        )

        menu.addSeparator()

        if key in self._excluded_keys:
            act_unhide = menu.addAction("✓  Unhide this AP")
            act_unhide.triggered.connect(
                lambda checked, k=key: self._do_unhide(k)
            )
        else:
            act_hide = menu.addAction("🚫  Hide this AP")
            act_hide.triggered.connect(
                lambda checked, k=key: self._do_hide(k)
            )

        menu.exec(self._list.viewport().mapToGlobal(pos))

    def _do_show_only(self, key: str, label: str) -> None:
        self._selected_key = key
        self._list.blockSignals(True)
        try:
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item:
                    item.setSelected(item.data(Qt.ItemDataRole.UserRole) == key)
        finally:
            self._list.blockSignals(False)
        self.group_include_requested.emit(key, label)

    def _do_hide(self, key: str) -> None:
        self._excluded_keys.add(key)
        self._update_item_style(key)
        self.group_exclude_requested.emit(key)

    def _do_unhide(self, key: str) -> None:
        self._excluded_keys.discard(key)
        self._update_item_style(key)
        self.group_unexclude_requested.emit(key)
