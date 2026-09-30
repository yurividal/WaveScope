"""Main window behavior and handlers mixin.

Contains data-flow, event handlers, selection logic, theming,
and detail/connection rendering methods for the main window.
"""

from .core import *
from .core_vendor import _resolve_vendor_icon_path
from .core_scanner import _IW_COPY_FIELDS, _CONN_COPY_FIELDS
from .graphs import ChannelAllocationsDialog
from .capture import CaptureTypeDialog, ManagedCaptureWindow, MonitorModeWindow
from .known_ssids import KnownSSIDStore, KnownSSIDDialog
from .theme import (
    IW_GEN_COLORS,
    _dark_palette,
    _light_palette,
    GRAPH_BG_DARK,
    GRAPH_BG_LIGHT,
    GRAPH_FG_DARK,
    GRAPH_FG_LIGHT,
    CARD_BG_DARK,
    CARD_VALUE_BG_DARK,
    CARD_VALUE_BORDER_DARK,
    CARD_VALUE_BG_LIGHT,
    CARD_VALUE_BORDER_LIGHT,
    DIALOG_BORDER_DARK,
    DIALOG_BORDER_LIGHT,
    DIALOG_TEXT_DARK,
    DIALOG_TEXT_LIGHT,
    DIALOG_NOTE_DARK,
    DIALOG_NOTE_LIGHT,
    SIG_POOR,
    SIG_WEAK,
    SIG_FAIR,
    SIG_EXCELLENT,
    SEC_BAD,
    SEC_WPA2,
    SEC_WPA3,
    SEC_OTHER,
    PMF_OPTIONAL,
    MENU_BG,
    MENU_BORDER,
    MENU_TEXT,
    MENU_SELECTED,
    CONNECTED_GREEN,
    HTML_MUTED,
    FALLBACK_GRAY,
)


class MainWindowLogicMixin:
    def _visible_aps(self) -> List[AccessPoint]:
        """Return the AccessPoint objects currently visible in the filtered table."""
        result: List[AccessPoint] = []
        for row in range(self._proxy.rowCount()):
            src_idx = self._proxy.mapToSource(self._proxy.index(row, 0))
            ap = self._model.ap_at(src_idx.row())
            if ap is not None:
                result.append(ap)
        return result

    def _on_filter_changed(self):
        """Called whenever the proxy filter changes — sync the channel graph."""
        visible = self._visible_aps()
        self._channel_graph.update_aps(visible, self._model.ssid_colors())
        shown = self._proxy.rowCount()
        self._lbl_count.setText(f"  {shown}/{len(self._aps)} APs")

    def _refresh_selected_details(self) -> None:
        """Re-render the Details tab for the current selection after a scan.

        The table model applies scans as an in-place diff, so the selection
        survives on its own; only the details text needs refreshing.
        """
        sm = self._table.selectionModel()
        if sm is not None and sm.selectedRows():
            self._on_selection_change(None, None)

    # Fields populated exclusively by enrich_with_iw — persist across up to
    # 5 cycles in which iw misses the BSS.  The live RSSI (dbm_exact) and the
    # iw "last seen" age are deliberately excluded: restoring them would freeze
    # the dBm column while nmcli's signal keeps moving.
    _IW_PERSIST_FIELDS = tuple(
        f for f in _IW_COPY_FIELDS if f not in ("dbm_exact", "last_seen_ms", "iw_seen")
    ) + ("manufacturer", "manufacturer_source")
    # Connected-session telemetry is only restored for the in-use AP.
    _CONN_PERSIST_FIELDS = tuple(_CONN_COPY_FIELDS) + (
        "conn_tx_retry_rate_pct",
        "conn_tx_fail_rate_pct",
    )

    # Fields where 0 / "" / None means "parse failed" — once we get a real
    # value the last-good value is kept even if subsequent cycles return 0.
    _STICKY_NONZERO_FIELDS = (
        "channel",  # nmcli returns 0 for some channels (e.g. ch144/5720 MHz)
        "freq_mhz",  # keep last-good freq so band/channel never regress to 0
        "bandwidth_mhz",  # nmcli returns 0 for 6 GHz
        "rate_mbps",  # nmcli returns 0 for 6 GHz
        "wifi_gen",  # may be "" when iw scan cache is stale
        "country",  # Country IE sometimes absent on one cycle
        "iw_center_freq",  # may be None when iw misses the center-freq line
    )

    def _auto_size_table_columns(self):
        """
        Fit all table columns to visible content/header.

        If the table is narrower than the viewport, distribute the extra space
        across columns so it still fills cleanly. If the content is wider than
        the viewport, keep the natural widths and let the horizontal scrollbar
        handle the overflow instead of compressing columns.
        """
        model = self._table.model()
        if model is None:
            return

        col_count = model.columnCount()
        if col_count <= 0:
            return

        viewport_w = self._table.viewport().width()
        if viewport_w <= 0:
            return

        hdr = self._table.horizontalHeader()
        min_w = max(24, hdr.minimumSectionSize())
        row_count = min(model.rowCount(), 250)

        fm = self._table.fontMetrics()
        hfm = hdr.fontMetrics()

        required: List[int] = []
        for col in range(col_count):
            header_text = str(
                model.headerData(
                    col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole
                )
                or ""
            )
            w = hfm.horizontalAdvance(header_text) + 28

            for row in range(row_count):
                idx = model.index(row, col)
                text = str(model.data(idx, Qt.ItemDataRole.DisplayRole) or "")
                if text:
                    w = max(w, fm.horizontalAdvance(text) + 24)

            required.append(max(min_w, w))

        # Columns the user dragged keep their width; hidden columns take none.
        user_cols = getattr(self, "_user_sized_cols", set())
        hidden = {c for c in range(col_count) if self._table.isColumnHidden(c)}
        fixed = user_cols | hidden
        widths = [
            self._table.columnWidth(c) if c in user_cols else (0 if c in hidden else required[c])
            for c in range(col_count)
        ]
        auto_cols = [c for c in range(col_count) if c not in fixed]

        # If there's remaining room, distribute it across the auto-sized columns
        total = sum(widths)
        if total < viewport_w and auto_cols:
            extra = viewport_w - total
            weight_sum = sum(required[c] for c in auto_cols) or len(auto_cols)
            for c in auto_cols:
                widths[c] += int(extra * (required[c] / weight_sum))
            # Rounding fix-up: spread leftover pixels across columns
            rem = viewport_w - sum(widths)
            order = sorted(auto_cols, key=lambda i: required[i], reverse=True)
            for i in range(max(0, rem)):
                widths[order[i % len(order)]] += 1

        self._suspend_col_resize_tracking = True
        try:
            for col in auto_cols:
                self._table.setColumnWidth(col, max(min_w, widths[col]))
        finally:
            self._suspend_col_resize_tracking = False

    def _on_data(self, aps: List[AccessPoint]):
        if self.sender() is not None and self.sender() is not self._scanner:
            return  # late emission from a scanner that is shutting down

        # ── sticky-nonzero field restoration ────────────────────────────────
        # For nmcli/iw fields that can transiently return 0/""/None even though
        # a real value was seen before (e.g. bandwidth_mhz=0 for 6 GHz when
        # nmcli loses the parse):  keep the last known-good value.
        for ap in aps:
            key = ap.bssid.lower()
            cache = self._sticky_cache.setdefault(key, {})
            for field in self._STICKY_NONZERO_FIELDS:
                val = getattr(ap, field)
                if val:  # nonzero / non-empty / non-None → update
                    cache[field] = val
                elif field in cache:  # zero/empty but we have a good value
                    setattr(ap, field, cache[field])

        # ── iw-field persistence ─────────────────────────────────────────────
        # iw_seen marks BSSs decoded from iw's scan cache on this cycle.
        for ap in aps:
            key = ap.bssid.lower()
            if ap.iw_seen:
                self._iw_cache[key] = {f: getattr(ap, f) for f in self._IW_PERSIST_FIELDS}
                self._iw_miss[key] = 0
            elif key in self._iw_cache and self._iw_miss.get(key, 0) < 5:
                # iw missed this AP but we have recent data — restore it
                for f, v in self._iw_cache[key].items():
                    setattr(ap, f, v)
                self._iw_miss[key] = self._iw_miss.get(key, 0) + 1

        # ── connected counter deltas (retry/fail rates) ───────────────────
        for ap in aps:
            if not ap.in_use:
                continue
            key = ap.bssid.lower()
            prev = self._conn_counter_prev.get(key)
            if (
                prev
                and ap.conn_tx_packets is not None
                and ap.conn_tx_retries is not None
                and ap.conn_tx_failed is not None
            ):
                d_pkts = ap.conn_tx_packets - prev.get("tx_packets", ap.conn_tx_packets)
                d_retry = ap.conn_tx_retries - prev.get("tx_retries", ap.conn_tx_retries)
                d_fail = ap.conn_tx_failed - prev.get("tx_failed", ap.conn_tx_failed)
                if d_pkts > 0 and d_retry >= 0 and d_fail >= 0:
                    ap.conn_tx_retry_rate_pct = (d_retry / d_pkts) * 100.0
                    ap.conn_tx_fail_rate_pct = (d_fail / d_pkts) * 100.0

            if (
                ap.conn_tx_packets is not None
                and ap.conn_tx_retries is not None
                and ap.conn_tx_failed is not None
            ):
                self._conn_counter_prev[key] = {
                    "tx_packets": ap.conn_tx_packets,
                    "tx_retries": ap.conn_tx_retries,
                    "tx_failed": ap.conn_tx_failed,
                }

        # ── evict per-BSSID caches for BSSs no longer listed ─────────────
        # `aps` already includes lingering BSSs, so this only drops entries
        # past the linger window — the caches stay bounded on long surveys.
        live = {ap.bssid.lower() for ap in aps}
        for cache in (self._sticky_cache, self._iw_cache, self._iw_miss, self._conn_counter_prev):
            for key in [k for k in cache if k not in live]:
                del cache[key]
        # ────────────────────────────────────────────────────────────────────

        # ── cross-AP analysis ────────────────────────────────────────────
        self._channel_stats = compute_channel_stats(aps)
        self._color_collisions = find_bss_color_collisions(aps)
        self._channel_graph.set_analysis(self._channel_stats, set(self._color_collisions))

        self._aps = aps
        self._model.update(aps)
        self._refresh_selected_details()
        # Explicit graph refresh: a pure value update (no rows added/removed)
        # does not trigger the proxy's filter signals.
        self._channel_graph.update_aps(self._visible_aps(), self._model.ssid_colors())
        self._history_graph.set_ssid_colors(self._model.ssid_colors())
        self._history_graph.push(aps)

        # Show AP Name / Power columns only when at least one AP has a value
        any_ap_name = any(ap.ap_name for ap in aps)
        any_pwr = any(ap.power_level[0] is not None for ap in aps)
        if self._table.isColumnHidden(COL_APNAME) == any_ap_name or self._table.isColumnHidden(COL_CISCO_PWR) == any_pwr:
            self._table.setColumnHidden(COL_APNAME, not any_ap_name)
            self._table.setColumnHidden(COL_CISCO_PWR, not any_pwr)
            self._auto_size_table_columns()

        # Update the AP sidebar (skips rebuild if groups haven't changed)
        self._ap_sidebar.update_groups(aps)

        total = len(aps)
        shown = self._proxy.rowCount()
        self._lbl_count.setText(f"  {shown}/{total} APs")
        ts = time.strftime("%H:%M:%S")
        self._lbl_updated.setText(f"  Last scan: {ts}  ")
        msg = f"Found {total} access points  |  Showing {shown}"
        if self._color_collisions:
            n = len(self._color_collisions)
            msg += f"  |  ⚠ BSS color collision on {n} BSS{'s' if n != 1 else ''} (see Details)"
        self.statusBar().showMessage(msg)
        self._show_connection()
        # Hide the first-scan overlay once data arrives for the first time
        if hasattr(self, "_scan_overlay") and self._scan_overlay.isVisible():
            self._scan_overlay.hide()

    def _on_theme_change(self, idx: int):
        modes = ["dark", "light", "auto"]
        self._apply_theme(modes[idx])

    def _apply_tb_theme(self, is_dark: bool) -> None:
        """Re-style the toolbar pill groups for dark/light mode."""
        if is_dark:
            bg, bdr, lbl_c = "#0a1520", "#1c2e44", "#3a5880"
        else:
            bg, bdr, lbl_c = "#e8eff8", "#b8cce0", "#7090b0"

        frame_ss = (
            f"QFrame#tbGroup {{ background:{bg};"
            f" border:1px solid {bdr}; border-radius:6px; }}"
        )
        lbl_ss = (
            f"color:{lbl_c}; font-size:7pt; font-weight:700;"
            " letter-spacing:0.5px; border:none; background:transparent;"
        )
        for frame in self._tb_groups:
            frame.setStyleSheet(frame_ss)
            hdr = frame.findChild(QLabel, "tbGroupHeader")
            if hdr:
                hdr.setStyleSheet(lbl_ss)
            for div in frame.findChildren(QFrame):
                if div.frameShape() == QFrame.Shape.VLine:
                    div.setStyleSheet(f"background:{bdr}; border:none;")

    def _apply_theme(self, mode: str):
        app = QApplication.instance()
        if mode == "dark":
            app.setPalette(_dark_palette())
            plot_bg, plot_fg = GRAPH_BG_DARK, GRAPH_FG_DARK
            is_dark = True
        elif mode == "light":
            app.setPalette(_light_palette())
            plot_bg, plot_fg = GRAPH_BG_LIGHT, GRAPH_FG_LIGHT
            is_dark = False
        else:  # auto — match system dark/light, use our own palette
            from PyQt6.QtCore import Qt as _Qt

            cs = app.styleHints().colorScheme()
            if cs == _Qt.ColorScheme.Dark:
                is_dark = True
            elif cs == _Qt.ColorScheme.Light:
                is_dark = False
            else:  # Unknown — probe style's default palette
                sp = app.style().standardPalette()
                is_dark = sp.color(QPalette.ColorRole.Window).lightness() < 128
            app.setPalette(_dark_palette() if is_dark else _light_palette())
            plot_bg, plot_fg = (
                (GRAPH_BG_DARK, GRAPH_FG_DARK)
                if is_dark
                else (GRAPH_BG_LIGHT, GRAPH_FG_LIGHT)
            )
        pg.setConfigOptions(foreground=plot_fg, background=plot_bg)
        self._channel_graph.set_theme(plot_bg, plot_fg)
        self._history_graph.set_theme(plot_bg, plot_fg)
        self._apply_details_theme(is_dark)
        self._apply_tb_theme(is_dark)
        self._ap_sidebar.apply_theme(is_dark)
        if hasattr(self, "_alloc_dialog") and self._alloc_dialog is not None:
            self._alloc_dialog.sync_theme(is_dark)
        self._table.viewport().update()

    def _apply_details_theme(self, is_dark: bool):
        if is_dark:
            card_bg = CARD_BG_DARK
            card_border = DIALOG_BORDER_DARK
            name_color = DIALOG_NOTE_DARK
            value_bg = CARD_VALUE_BG_DARK
            value_border = CARD_VALUE_BORDER_DARK
            value_color = DIALOG_TEXT_DARK
        else:
            card_bg = DIALOG_BG_LIGHT
            card_border = DIALOG_BORDER_LIGHT
            name_color = DIALOG_NOTE_LIGHT
            value_bg = CARD_VALUE_BG_LIGHT
            value_border = CARD_VALUE_BORDER_LIGHT
            value_color = DIALOG_TEXT_LIGHT

        details_style = (
            f"QFrame#detailsCard {{"
            f"background:{card_bg};"
            f"border:1px solid {card_border};"
            "border-radius:8px;"
            "}"
            f"QLabel[detailRole='name'] {{"
            f"color:{name_color};"
            "font-size:10pt;"
            "font-weight:600;"
            "}"
            f"QLabel[detailRole='value'] {{"
            f"background:{value_bg};"
            f"border:1px solid {value_border};"
            "border-radius:6px;"
            "padding:3px 8px;"
            f"color:{value_color};"
            "font-size:10.5pt;"
            "}"
        )

        # Clear before re-applying — forces Qt6 to flush cached child-widget
        # styles so property selectors (e.g. [detailRole='value']) re-evaluate.
        self._details_widget.setStyleSheet("")
        self._details_widget.setStyleSheet(details_style)
        if hasattr(self, "_connection_widget"):
            self._connection_widget.setStyleSheet("")
            self._connection_widget.setStyleSheet(details_style)

    def _on_error(self, msg: str):
        self.statusBar().showMessage(f"⚠ Scanner error: {msg}")

    def _on_col_resized(self, col: int, old_size: int, new_size: int):
        """Record that the user explicitly resized this column."""
        if getattr(self, "_suspend_col_resize_tracking", False):
            return
        # Hiding/unhiding a column also emits sectionResized (to/from 0);
        # that is not a user drag.
        if new_size == 0 or old_size == 0 or self._table.isColumnHidden(col):
            return
        self._user_sized_cols.add(col)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._auto_size_table_columns()

    def _on_band_change(self, band: str):
        self._proxy.set_band(band)  # → rows removed/inserted → _on_filter_changed
        self._channel_graph.set_band(band)

    def _on_interval_change(self, idx: int):
        if self._scanner is not None:
            self._scanner.set_interval(REFRESH_INTERVALS[idx])

    def _on_linger_change(self, secs: int):
        if self._scanner is not None:
            self._scanner.set_linger_secs(float(secs))

    # ── Scanner lifecycle ────────────────────────────────────────────────

    def _start_scanner(self) -> None:
        """Create and start a scanner using the current toolbar settings."""
        self._scanner = WiFiScanner(
            interval_sec=REFRESH_INTERVALS[self._interval_combo.currentIndex()],
            linger_secs=float(self._linger_spin.value()),
        )
        self._scanner.data_ready.connect(self._on_data)
        self._scanner.scan_error.connect(self._on_error)
        self._scanner.start()

    def _stop_scanner(self, wait_ms: Optional[int] = 3000) -> None:
        """Stop the current scanner without ever dropping a running QThread.

        If it has not finished within *wait_ms* it is parked in
        _retired_scanners until its `finished` signal fires, so Python never
        garbage-collects a live QThread ("Destroyed while thread is still
        running" abort).
        """
        sc, self._scanner = self._scanner, None
        if sc is None:
            return
        if not sc.stop(wait_ms):
            self._retired_scanners.append(sc)
            sc.finished.connect(lambda s=sc: self._retired_scanners.remove(s) if s in self._retired_scanners else None)

    def _on_pause(self, paused: bool):
        if paused:
            self._stop_scanner()
            self._btn_pause.setText("▶ Resume")
            self.statusBar().showMessage("Paused — click Resume to continue scanning")
        else:
            self._start_scanner()
            self._btn_pause.setText("⏸ Pause")
            self.statusBar().showMessage("Resumed scanning…")

    def _on_monitor_mode(self):
        picker = CaptureTypeDialog(parent=self)
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        choice = picker.chosen()
        if choice == "monitor":
            if not hasattr(self, "_monitor_win") or self._monitor_win is None:
                self._monitor_win = MonitorModeWindow(parent=self)
            self._monitor_win.show()
            self._monitor_win.raise_()
            self._monitor_win.activateWindow()
        elif choice == "managed":
            if not hasattr(self, "_managed_win") or self._managed_win is None:
                self._managed_win = ManagedCaptureWindow(parent=self)
            self._managed_win.show()
            self._managed_win.raise_()
            self._managed_win.activateWindow()

    def _on_open_allocations(self):
        is_dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        if not hasattr(self, "_alloc_dialog") or self._alloc_dialog is None:
            self._alloc_dialog = ChannelAllocationsDialog(is_dark=is_dark, parent=self)
        else:
            self._alloc_dialog.sync_theme(is_dark)
        self._alloc_dialog.show()
        self._alloc_dialog.raise_()
        self._alloc_dialog.activateWindow()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._table.clearSelection()
            self._channel_graph.highlight_bssid(None)
            self._history_graph.filter_bssids(None)
        super().keyPressEvent(event)

    def _on_graph_highlight(self, bssid: Optional[str]):
        """Called when user clicks a label in the channel graph.

        A grouped label stands for every SSID on that radio, so all of its
        BSSIDs are selected in the table and shown in the signal history.
        """
        if bssid is None:
            self._table.clearSelection()
            self._history_graph.filter_bssids(None)
            return
        members = self._channel_graph.members_of(bssid) or [bssid]
        sm = self._table.selectionModel()
        sm.blockSignals(True)
        try:
            sm.clearSelection()
            for i, b in enumerate(members):
                row = self._model.row_of_bssid(b)
                if row < 0:
                    continue
                pidx = self._proxy.mapFromSource(self._model.index(row, 0))
                if not pidx.isValid():
                    continue
                flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
                if b == bssid:
                    flags |= QItemSelectionModel.SelectionFlag.Current
                    self._table.scrollTo(pidx)
                sm.select(pidx, flags)
                if b == bssid:
                    sm.setCurrentIndex(pidx, QItemSelectionModel.SelectionFlag.NoUpdate)
        finally:
            sm.blockSignals(False)
        # Details for the clicked (strongest) member; graph keeps its highlight.
        row = self._model.row_of_bssid(bssid)
        ap = self._model.ap_at(row) if row >= 0 else None
        if ap is not None:
            self._show_details(ap)
        self._history_graph.filter_bssids(set(members))

    def _on_selection_change(self, selected, deselected):
        indexes = self._table.selectionModel().selectedRows()
        if not indexes:
            self._det_ssid.setText(
                "<span style='font-size:15px;color:#777'>Select an access point to view details.</span>"
            )
            for v in self._det_vals.values():
                v.setText("—")
            self._history_graph.filter_bssids(None)
            self._channel_graph.highlight_bssid(None)
            return

        proxy_idx = indexes[0]
        src_idx = self._proxy.mapToSource(proxy_idx)
        ap = self._model.ap_at(src_idx.row())
        if ap:
            self._show_details(ap)
            selected_bssids = set()
            for pi in indexes:
                si = self._proxy.mapToSource(pi)
                a = self._model.ap_at(si.row())
                if a:
                    selected_bssids.add(a.bssid)
            self._history_graph.filter_bssids(selected_bssids)
            # Highlight single selection in channel graph
            # One BSSID, or several that the graph draws as one grouped shape.
            single_bssid = (
                ap.bssid
                if len(selected_bssids) == 1 or self._channel_graph.same_shape(selected_bssids)
                else None
            )
            self._channel_graph.highlight_bssid(single_bssid)

    # ── Context menu ─────────────────────────────────────────────────────

    def _on_context_menu(self, pos):
        idx = self._table.indexAt(pos)
        if not idx.isValid():
            return
        src_idx = self._proxy.mapToSource(idx)
        ap = self._model.ap_at(src_idx.row())
        if ap is None:
            return

        col = idx.column()
        cell_val = self._model.data(src_idx, Qt.ItemDataRole.DisplayRole) or ""

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{MENU_BG};border:1px solid {MENU_BORDER};color:{MENU_TEXT};}}"
            f"QMenu::item:selected{{background:{MENU_SELECTED};}}"
            f"QMenu::separator{{height:1px;background:{MENU_BORDER};margin:3px 8px;}}"
        )

        # ── Filterable columns ────────────────────────────────────────────
        filterable = [
            (COL_SSID, ap.display_ssid, "SSID"),
            (COL_MANUF, format_manufacturer_display(ap.manufacturer), "Manufacturer"),
            (COL_BSSID, ap.bssid, "MAC address"),
            (COL_COUNTRY, ap.country or "", "Country"),
            (COL_CHAN, str(ap.channel), "Channel"),
            (COL_BW, str(ap.bandwidth_mhz), "Channel Width"),
            (COL_BAND, ap.band, "Band"),
            (COL_SEC, ap.security_short, "Security"),
        ]

        # AP group key + label for this BSSID
        _ap_gkey = ap_group_key_for(ap)
        _ap_glabel = ap_group_display_label(_ap_gkey, ap.manufacturer)

        # Show only
        show_menu = menu.addMenu("👁  Show only")
        for fcol, fval, fname in filterable:
            if fval and fval not in ("-", "?", "Unknown"):
                short = fval[:32] + ("…" if len(fval) > 32 else "")
                a = show_menu.addAction(f"{fname}: {short}")
                a.triggered.connect(
                    lambda checked, c=fcol, v=fval: self._proxy.add_include(c, v)
                    or self._refresh_filter_badge()
                )
        show_menu.addSeparator()
        a_ap_show = show_menu.addAction(f"This AP  ({_ap_glabel})")
        a_ap_show.triggered.connect(
            lambda checked, k=_ap_gkey, l=_ap_glabel: (
                self._proxy.set_ap_group_include(k, label=l),
                self._ap_sidebar.set_active_group(k),
                self._refresh_filter_badge(),
            )
        )

        # Hide / exclude
        hide_menu = menu.addMenu("🚫  Hide")
        for fcol, fval, fname in filterable:
            if fval and fval not in ("-", "?"):
                short = fval[:32] + ("…" if len(fval) > 32 else "")
                a = hide_menu.addAction(f"{fname}: {short}")
                a.triggered.connect(
                    lambda checked, c=fcol, v=fval: self._proxy.add_exclude(c, v)
                    or self._refresh_filter_badge()
                )
        hide_menu.addSeparator()
        a_ap_hide = hide_menu.addAction(f"This AP  ({_ap_glabel})")
        a_ap_hide.triggered.connect(
            lambda checked, k=_ap_gkey: (
                self._proxy.add_ap_group_exclude(k),
                self._ap_sidebar.mark_group_excluded(k, True),
                self._refresh_filter_badge(),
            )
        )

        menu.addSeparator()

        # Remove specific include/exclude
        if self._proxy.has_col_filters() or self._proxy.has_ap_group_filters():
            clear_a = menu.addAction("✕  Clear all filters")
            clear_a.triggered.connect(self._on_clear_col_filters)

        menu.addSeparator()

        # ── Known SSIDs ───────────────────────────────────────────────────
        _ssid = ap.display_ssid
        if _ssid and _ssid not in ("", "--"):
            if _ssid in self._known_store:
                act_known = menu.addAction(f"☆  Remove '{_ssid}' from Known SSIDs")
                act_known.triggered.connect(
                    lambda checked, s=_ssid: (
                        self._known_store.remove(s),
                        self._known_store_changed(),
                    )
                )
            else:
                act_known = menu.addAction(f"★  Add '{_ssid}' to Known SSIDs")
                act_known.triggered.connect(
                    lambda checked, s=_ssid: (
                        self._known_store.add(s),
                        self._known_store_changed(),
                    )
                )

        menu.addSeparator()

        # Details shortcut
        det = menu.addAction("ℹ  View details")
        # Capture the BSSID, not the row: a scan can re-sort the table while
        # the menu is open, and the row would then point at another AP.
        det.triggered.connect(lambda checked=False, b=ap.bssid: self._open_details_for_bssid(b))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _open_details_for_bssid(self, bssid: str) -> None:
        src_row = self._model.row_of_bssid(bssid)
        if src_row < 0:
            return
        proxy_idx = self._proxy.mapFromSource(self._model.index(src_row, 0))
        if not proxy_idx.isValid():
            return

        sm = self._table.selectionModel()
        if sm is not None:
            sm.select(
                proxy_idx,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            sm.setCurrentIndex(
                proxy_idx,
                QItemSelectionModel.SelectionFlag.Current
                | QItemSelectionModel.SelectionFlag.Rows,
            )

        src_idx = self._proxy.mapToSource(proxy_idx)
        ap = self._model.ap_at(src_idx.row())
        if ap is not None:
            self._show_details(ap)

        if hasattr(self, "_tabs") and hasattr(self, "_details_tab_index"):
            self._tabs.setCurrentIndex(self._details_tab_index)

    def _refresh_filter_badge(self):
        has_any = (
            self._proxy.has_col_filters()
            or self._proxy.has_ap_group_filters()
            or self._proxy.has_known_filter()
        )
        if has_any:
            self._lbl_filters.setText(self._proxy.active_filter_text())
            self._lbl_filters.show()
            self._btn_clear_filters.show()
        else:
            self._lbl_filters.hide()
            self._btn_clear_filters.hide()
        cnt = self._proxy.rowCount()
        self._lbl_count.setText(f"  {cnt}/{len(self._aps)} APs")

    def _on_clear_col_filters(self):
        self._proxy.clear_col_filters()
        self._proxy.clear_ap_group_filters()
        self._ap_sidebar.clear_all_filters()
        # Reset known combo to "All" without re-triggering the change handler
        self._known_combo.blockSignals(True)
        self._known_combo.setCurrentIndex(0)
        self._known_combo.blockSignals(False)
        self._proxy.set_known_filter("off")
        self._refresh_filter_badge()

    # ── AP Sidebar handlers ───────────────────────────────────────────────

    def _on_sidebar_include(self, key: str, label: str) -> None:
        """Show only the selected AP group (empty key = clear filter)."""
        if key:
            self._proxy.set_ap_group_include(key, label=label)
        else:
            self._proxy.set_ap_group_include(None)
        self._refresh_filter_badge()

    def _on_sidebar_exclude(self, key: str) -> None:
        """Hide all BSSIDs belonging to the given AP group."""
        self._proxy.add_ap_group_exclude(key)
        self._refresh_filter_badge()

    def _on_sidebar_unexclude(self, key: str) -> None:
        """Un-hide a previously hidden AP group."""
        self._proxy.remove_ap_group_exclude(key)
        self._refresh_filter_badge()

    # ── Known SSIDs handlers ──────────────────────────────────────────────

    def _known_store_changed(self) -> None:
        """Called whenever the known-SSID store is mutated."""
        self._proxy.set_known_ssids(self._known_store.as_frozenset())
        self._refresh_filter_badge()

    def _on_known_filter_change(self, idx: int) -> None:
        mode = self._known_combo.itemData(idx)
        self._proxy.set_known_filter(mode)
        self._refresh_filter_badge()

    def _on_known_edit(self) -> None:
        dlg = KnownSSIDDialog(self._known_store, parent=self)
        dlg.changed.connect(self._known_store_changed)
        dlg.exec()

    def _on_sidebar_toggle(self, checked: bool) -> None:
        """Collapse or expand the AP sidebar panel."""
        sizes = self._h_splitter.sizes()
        if checked:
            # Expand: restore last known width
            w = getattr(self, "_sidebar_last_width", 180)
            total = sum(sizes)
            self._h_splitter.setSizes([w, max(1, total - w)])
        else:
            # Collapse: remember current width first
            if sizes[0] > 0:
                self._sidebar_last_width = sizes[0]
            self._h_splitter.setSizes([0, sum(sizes)])

    def _on_hsplitter_moved(self, pos: int, index: int) -> None:
        """Track sidebar width so the toggle can restore it."""
        w = self._h_splitter.sizes()[0]
        if w > 0:
            self._sidebar_last_width = w
            # Keep toggle button state in sync when user drags the splitter
            self._btn_sidebar.blockSignals(True)
            self._btn_sidebar.setChecked(True)
            self._btn_sidebar.blockSignals(False)
        else:
            self._btn_sidebar.blockSignals(True)
            self._btn_sidebar.setChecked(False)
            self._btn_sidebar.blockSignals(False)

    def _show_details(self, ap: AccessPoint):
        color = self._model.ssid_colors().get(ap.ssid, QColor(FALLBACK_GRAY)).name()
        sig_col = dbm_color(ap.dbm).name()
        esc = html.escape  # SSIDs, AP names, WPS strings come from beacons

        def badge(text, bg=None, fg=None):
            color = fg or bg
            if color:
                return (
                    f'<span style="color:{color};font-size:14px;font-weight:600">'
                    f"{text}</span>"
                )
            return f'<span style="font-size:14px;font-weight:600">{text}</span>'

        def dim(text):
            return f"<span style='color:{HTML_MUTED}'>{text}</span>"

        # ── SSID header ───────────────────────────────────────────────────
        in_use = (
            (
                f' &nbsp;<span style="font-size:13px;font-weight:600;color:{CONNECTED_GREEN};">'
                "▲ CONNECTED</span>"
            )
            if ap.in_use
            else ""
        )
        self._det_ssid.setText(
            f'<span style="font-size:20px;font-weight:700;color:{color}">{esc(ap.display_ssid)}</span>{in_use}'
        )

        # ── WiFi generation ───────────────────────────────────────────────
        gen_color = IW_GEN_COLORS.get(ap.wifi_gen, SEC_OTHER)
        if ap.wifi_gen:
            gen_html = badge(f"{ap.wifi_gen}  ·  {ap.protocol}", gen_color)
        else:
            gen_html = ap.protocol or dim("Unknown")

        # ── Security ──────────────────────────────────────────────────────
        sec_derived = (ap.security_short or "").strip()
        sec_raw = (ap.security or "").strip()

        def sec_richness(text: str) -> int:
            s = (text or "").strip().upper()
            if not s or s in {"(NONE)", "NONE", "--", "(NULL)"}:
                return 0
            score = len(re.findall(r"[A-Z0-9]+", s))
            if "WPA3" in s or "SAE" in s or "OWE" in s:
                score += 4
            if "WPA2" in s:
                score += 3
            if "WPA" in s:
                score += 2
            if "EAP" in s or "802.1X" in s or "8021X" in s:
                score += 3
            if "PSK" in s:
                score += 2
            return score

        def detail_tokens(text: str) -> set[str]:
            t = (text or "").upper()
            t = t.replace("802.1X", "8021X")
            return set(re.findall(r"[A-Z0-9]+", t))

        def should_show_secondary_line(primary: str, secondary: str) -> bool:
            p = (primary or "").strip()
            s = (secondary or "").strip()
            if not p or not s:
                return False
            if p == s:
                return False
            p_tokens = detail_tokens(p)
            s_tokens = detail_tokens(s)
            if not s_tokens:
                return False
            return not s_tokens.issubset(p_tokens)

        def choose_primary_detail(first: str, second: str) -> str:
            a = (first or "").strip()
            b = (second or "").strip()
            if not a:
                return b
            if not b:
                return a

            a_tokens = detail_tokens(a)
            b_tokens = detail_tokens(b)
            a_has_wpa3 = "WPA3" in a_tokens or "SAE" in a_tokens
            b_has_wpa3 = "WPA3" in b_tokens or "SAE" in b_tokens
            if a_has_wpa3 != b_has_wpa3:
                return a if a_has_wpa3 else b

            if len(a_tokens) != len(b_tokens):
                return a if len(a_tokens) > len(b_tokens) else b
            return a if len(a) >= len(b) else b

        sec_display = choose_primary_detail(sec_derived, sec_raw)
        if not sec_display:
            sec_display = "Open"

        sec_display = esc(sec_display)
        if sec_display.startswith("Open") or sec_display in ("WEP", "Unknown"):
            sec_html = badge(sec_display, SEC_BAD)
        elif "WPA3" in sec_display or "SAE" in sec_display or sec_display == "OWE":
            sec_html = badge(sec_display, SEC_WPA3)
        elif "WPA2" in sec_display:
            sec_html = badge(sec_display, SEC_WPA2)
        else:
            sec_html = badge(sec_display, SEC_OTHER)

        # ── PMF ───────────────────────────────────────────────────────────
        pmf_map = {"Required": SEC_WPA3, "Optional": PMF_OPTIONAL, "No": SEC_BAD}
        pmf_c = pmf_map.get(ap.pmf)
        pmf_html = badge(ap.pmf, pmf_c) if pmf_c else dim(ap.pmf or "Unknown")

        # ── Channel utilisation ───────────────────────────────────────────
        util_pct = ap.chan_util_pct
        if util_pct is not None:
            if util_pct >= 75:
                uc = SIG_POOR
            elif util_pct >= 50:
                uc = SIG_WEAK
            elif util_pct >= 25:
                uc = SIG_FAIR
            else:
                uc = SIG_EXCELLENT
            util_html = f'<span style="color:{uc};font-size:15px;font-weight:700">{util_pct}%</span>'
        else:
            util_html = dim("No BSS Load IE")

        # ── Roaming ───────────────────────────────────────────────────────
        kvr_items: List[str] = []
        if ap.rrm:
            kvr_items.append("802.11k - Radio Resource Management <b>(RRM)</b>")
        if ap.btm:
            kvr_items.append("802.11v - BSS Transition Management <b>(BTM)</b>")
        if ap.ft:
            kvr_items.append("802.11r - Fast BSS Transition <b>(FT)</b>")
        kvr_html = "<br>".join(kvr_items) if kvr_items else dim("None detected")

        # ── Populate rows ─────────────────────────────────────────────────
        v = self._det_vals

        def raw_ie_or_dim(value: str, missing_text: str) -> str:
            text = (value or "").strip()
            if not text or text.lower() in {"(none)", "none", "--", "(null)"}:
                return dim(missing_text)
            return text

        def format_ie_flags(value: str, missing_text: str) -> str:
            text = (value or "").strip()
            if not text or text.lower() in {"(none)", "none", "--", "(null)"}:
                return dim(missing_text)

            cipher_map = {
                "ccmp": "CCMP (AES)",
                "ccmp256": "CCMP-256",
                "ccmp_256": "CCMP-256",
                "tkip": "TKIP",
                "gcmp": "GCMP",
                "gcmp256": "GCMP-256",
                "gcmp_256": "GCMP-256",
                "wep40": "WEP-40",
                "wep104": "WEP-104",
            }
            akm_map = {
                "psk": "PSK",
                "sae": "SAE",
                "eap": "802.1X (EAP)",
                "8021x": "802.1X (EAP)",
                "owe": "OWE",
                "ft_psk": "FT-PSK",
                "ft_sae": "FT-SAE",
                "ft_eap": "FT-EAP",
                "eap_suite_b_192": "EAP Suite-B-192",
            }

            def _add_unique(items: list[str], item: str):
                if item and item not in items:
                    items.append(item)

            pairwise: list[str] = []
            group: list[str] = []
            akm: list[str] = []
            other: list[str] = []

            for raw_token in text.split():
                token = raw_token.strip().lower()
                if not token:
                    continue

                if token.startswith("pair_"):
                    c = token[len("pair_") :]
                    _add_unique(pairwise, cipher_map.get(c, c.upper()))
                    continue

                if token.startswith("group_"):
                    c = token[len("group_") :]
                    _add_unique(group, cipher_map.get(c, c.upper()))
                    continue

                if token.startswith("akm_"):
                    a = token[len("akm_") :]
                    _add_unique(akm, akm_map.get(a, a.upper()))
                    continue

                if token in cipher_map:
                    _add_unique(other, cipher_map[token])
                    continue

                if token in akm_map:
                    _add_unique(akm, akm_map[token])
                    continue

                _add_unique(other, raw_token)

            lines: list[str] = []
            if pairwise:
                lines.append(f"Pairwise Cipher: {', '.join(pairwise)}")
            if group:
                lines.append(f"Group Cipher: {', '.join(group)}")
            if akm:
                lines.append(f"AKM: {', '.join(akm)}")
            if other:
                lines.append(f"Other: {', '.join(other)}")

            return "<br>".join(lines) if lines else text

        v["bssid"].setText(ap.bssid)
        manuf_raw = ap.manufacturer or ""
        manuf_text = format_manufacturer_display(manuf_raw)
        manuf_source = (ap.manufacturer_source or "Unknown").strip() or "Unknown"
        if manuf_text:
            icon_path = _resolve_vendor_icon_path(manuf_raw)
            if icon_path is not None:
                v["manufacturer"].setText(
                    f"<img src='{icon_path.as_uri()}' height='16' "
                    f"style='vertical-align:middle;'> &nbsp;{esc(manuf_text)}"
                )
            else:
                v["manufacturer"].setText(esc(manuf_text))
        else:
            v["manufacturer"].setText(dim("Unknown"))
        manuf_tip = f"Source: {manuf_source}"
        v["manufacturer"].setToolTip(manuf_tip)
        if "manufacturer" in self._det_name_labels:
            self._det_name_labels["manufacturer"].setToolTip(manuf_tip)
        v["wifi_gen"].setText(gen_html)
        v["mode_80211"].setText(ap.phy_mode)
        v["band"].setText(ap.band)
        ch_notes = []
        if ap.is_psc:
            ch_notes.append("PSC")
        if ap.is_dfs:
            ch_notes.append("DFS")
        span = get_ap_channel_span(ap)
        ch_text = str(ap.channel)
        if span != str(ap.channel):
            ch_text += f"  ·  block {span}"
        if ch_notes:
            ch_text += f"  {dim('(' + ', '.join(ch_notes) + ')')}"
        v["channel"].setText(ch_text)
        center = get_ap_draw_center(ap)
        freq_text = f"{ap.freq_mhz} MHz (primary)"
        if ap.bandwidth_mhz > 20 and int(center) != ap.freq_mhz:
            freq_text += f"  ·  {int(center)} MHz block center"
        v["frequency"].setText(freq_text)
        v["chan_width"].setText(
            f"{ap.bandwidth_mhz} MHz" + (" (80+80, non-contiguous)" if ap.iw_80p80 else "")
        )
        v["country"].setText(ap.country or dim("Unknown"))
        v["beacon_interval"].setText(
            f"{ap.beacon_interval_tu} TU"
            if ap.beacon_interval_tu is not None
            else dim("Not advertised")
        )
        v["dtim_period"].setText(
            str(ap.dtim_period) if ap.dtim_period is not None else dim("Not advertised")
        )
        v["phy_caps"].setText(ap.phy_cap_summary or dim("Not advertised"))
        v["he_features"].setText(ap.he_eht_features or dim("Not advertised"))
        v["signal"].setText(
            f'<span style="color:{sig_col};font-size:15px;font-weight:700">'
            f"{ap.signal}%&nbsp;</span>"
            f'<span style="color:{sig_col}">({ap.dbm} dBm)</span>'
        )
        v["max_rate"].setText(f"{int(ap.rate_mbps)} Mbps")
        sec_line_top = sec_html
        sec_secondary = sec_raw if sec_display == sec_derived else sec_derived
        if should_show_secondary_line(sec_display, sec_secondary):
            sec_line_bottom = dim(esc(sec_secondary))
            v["security"].setText(f"{sec_line_top}<br>{sec_line_bottom}")
        else:
            v["security"].setText(sec_line_top)
        v["security"].setToolTip("")
        v["wpa_flags"].setText(format_ie_flags(ap.wpa_flags, "WPA IE not present"))
        v["rsn_flags"].setText(format_ie_flags(ap.rsn_flags, "RSN IE not present"))
        v["rsn_caps"].setText(esc(ap.rsn_capabilities) or dim("Not advertised"))
        v["vendor_ies"].setText(esc(ap.vendor_ie_ouis) or dim("Not advertised"))
        v["wpa_flags"].setToolTip(raw_ie_or_dim(ap.wpa_flags, "WPA IE not present"))
        v["rsn_flags"].setToolTip(raw_ie_or_dim(ap.rsn_flags, "RSN IE not present"))
        akm_compact = (ap.akm or "").strip()
        akm_verbose = (ap.akm_raw or "").strip()
        akm_primary = choose_primary_detail(akm_compact, akm_verbose)
        if akm_primary:
            akm_secondary = akm_verbose if akm_primary == akm_compact else akm_compact
            if should_show_secondary_line(akm_primary, akm_secondary):
                v["akm_raw"].setText(f"{akm_primary}<br>{dim(akm_secondary)}")
            else:
                v["akm_raw"].setText(raw_ie_or_dim(akm_primary, "AKM unknown"))
        else:
            v["akm_raw"].setText(dim("AKM unknown"))
        v["akm_raw"].setToolTip("")
        v["wps_manufacturer"].setText(esc(ap.wps_manufacturer) or dim("Not advertised"))
        v["pmf"].setText(pmf_html)
        v["chan_util"].setText(util_html)
        v["clients"].setText(
            str(ap.station_count) if ap.station_count is not None else dim("Unknown")
        )
        v["roaming"].setText(kvr_html)
        if "ap_name" in v:
            v["ap_name"].setText(esc(ap.ap_name) or dim("Not advertised"))
        if "cisco_tx_power" in v:
            pwr, src = ap.power_level
            v["cisco_tx_power"].setText(
                f"{pwr:g} dBm  {dim('(' + src + ')')}" if pwr is not None else dim("Not advertised")
            )

        # ── RF analysis & extended IEs ────────────────────────────────────
        st = ap_congestion(ap, self._channel_stats)
        if st is not None:
            sc = SIG_POOR if st.score >= 70 else SIG_WEAK if st.score >= 45 else SIG_FAIR if st.score >= 25 else SIG_EXCELLENT
            v["congestion"].setText(
                f'<span style="color:{sc};font-weight:700">{st.score}/100</span> '
                + dim(
                    f"ch {st.channel}: {st.bss_count} overlapping BSS, "
                    f"{st.strong_count} ≥ {CCA_PD_THRESHOLD_DBM} dBm"
                    + (f", max util {st.max_util_pct}%" if st.max_util_pct is not None else "")
                    + " · heuristic"
                )
            )
        else:
            v["congestion"].setText(dim("—"))

        if ap.bss_color is None:
            v["bss_color"].setText(dim("Not advertised (pre-802.11ax)"))
        else:
            txt = f"{ap.bss_color}" + (" (coloring disabled)" if ap.bss_color_disabled else "")
            others = self._color_collisions.get(ap.bssid.lower(), [])
            if others:
                names = ", ".join(esc(o.display_ssid) + f" ({o.bssid[-5:]}, ch {o.channel})" for o in others[:4])
                txt = (
                    f'<span style="color:{SIG_POOR};font-weight:700">{txt} — collision</span><br>'
                    + dim(f"Same color on overlapping channel: {names}")
                )
            v["bss_color"].setText(txt)

        subs = punctured_subchannels(get_ap_draw_center(ap), ap.bandwidth_mhz, ap.punct_bitmap)
        v["punct"].setText(
            ", ".join(f"{int(lo)}–{int(hi)} MHz" for lo, hi in subs) + dim(f"  (bitmap 0x{ap.punct_bitmap:04X})")
            if subs
            else dim("None" if ap.wifi_gen == "WiFi 7" else "N/A (pre-802.11be)")
        )
        v["ap_power_6g"].setText(esc(ap.he_6ghz_ap_type) or dim("N/A" if ap.band != "6 GHz" else "Not advertised"))

        if ap.mld_mac:
            links = [a for a in self._aps if a.mld_mac == ap.mld_mac and a.bssid != ap.bssid]
            link_txt = ", ".join(f"{a.band} ch {a.channel}" for a in links)
            v["mld"].setText(ap.mld_mac + (f"<br>{dim('Other links seen: ' + link_txt)}" if link_txt else ""))
        else:
            v["mld"].setText(dim("Not advertised"))

        if ap.rnr_neighbors:
            seen = {a.bssid.lower() for a in self._aps}
            rows = []
            for n in ap.rnr_neighbors[:8]:
                op = int(n.get("op_class", 0))
                band_lbl = "6 GHz" if op in (131, 132, 133, 134, 135, 136, 137) else f"op class {op}"
                b = str(n.get("bssid", "")) or "?"
                flags = []
                if n.get("same_ssid"):
                    flags.append("same SSID")
                if n.get("colocated"):
                    flags.append("co-located")
                if b != "?" and b not in seen:
                    flags.append("not seen by this adapter")
                rows.append(f"{band_lbl} ch {n.get('channel')} · {b}" + (f" {dim('(' + ', '.join(flags) + ')')}" if flags else ""))
            v["rnr"].setText("<br>".join(rows))
        else:
            v["rnr"].setText(dim("No Reduced Neighbor Report"))

        limits = []
        if ap.power_constraint_db is not None:
            limits.append(f"Power Constraint: {ap.power_constraint_db} dB")
        if ap.tpe_summary:
            limits.append(f"TPE: {esc(ap.tpe_summary)}")
        if ap.country_power:
            limits.append(f"Country ({esc(ap.country)}{', ' + esc(ap.country_env) if ap.country_env else ''}): {esc(ap.country_power)}")
        v["tx_limits"].setText("<br>".join(limits) or dim("Not advertised"))

        if ap.basic_rates or ap.has_11b_rates is not None:
            txt = (f"{ap.basic_rates} Mbps" if ap.basic_rates else dim("none marked"))
            if ap.has_11b_rates:
                txt += "<br>" + dim("802.11b (DSSS/CCK) rates enabled — legacy clients slow the whole cell")
            v["basic_rates"].setText(txt)
        else:
            v["basic_rates"].setText(dim("Unknown"))

        if ap.is_lingering:
            v["last_seen"].setText(dim("Not in the latest scan (lingering)"))
        elif ap.last_seen_ms is not None:
            v["last_seen"].setText(f"{ap.last_seen_ms / 1000:.1f} s ago (iw scan cache)")
        else:
            v["last_seen"].setText(dim("Unknown"))

        v["rsnx"].setText(esc(ap.rsnx_caps) or dim("Not advertised"))
        v["group_mgmt"].setText(esc(ap.group_mgmt_cipher) or dim("Not advertised"))
        if ap.owe_transition_bssid:
            v["owe_pair"].setText(
                f"{ap.owe_transition_bssid}"
                + (f"  {dim('SSID ' + esc(ap.owe_transition_ssid))}" if ap.owe_transition_ssid else "")
            )
        else:
            v["owe_pair"].setText(dim("None"))
        if ap.mobility_domain:
            n = mobility_domain_members(ap, self._aps)
            v["mobility_domain"].setText(
                f"MDID {ap.mobility_domain}"
                + (" · FT over DS" if ap.ft_over_ds else " · FT over the air")
                + f"  {dim(f'({n} BSSID(s) of this SSID share it)')}"
            )
        else:
            v["mobility_domain"].setText(dim("Not advertised (no 802.11r)"))

    def _show_connection(self):
        def dim(text):
            return f"<span style='color:{HTML_MUTED}'>{text}</span>"

        connected_ap = next(
            (
                x
                for x in self._aps
                if x.in_use and (x.conn_iface or x.conn_link_freq_mhz is not None)
            ),
            None,
        )
        if connected_ap is None:
            connected_ap = next((x for x in self._aps if x.in_use), None)
        if connected_ap is None:
            connected_ap = next(
                (
                    x
                    for x in self._aps
                    if x.conn_iface or x.conn_link_freq_mhz is not None
                ),
                None,
            )
        v = self._conn_vals
        if connected_ap is None:
            self._conn_ssid.setText(
                f"<span style='font-size:20px;font-weight:700;color:{HTML_MUTED}'>Wifi not connected</span>"
            )
            v["status"].setText(dim("Wifi not connected"))
            for key in (
                "ssid",
                "bssid",
                "manufacturer",
                "band",
                "channel",
                "security",
                "akm",
                "pmf",
                "beacon_interval",
                "dtim_period",
                "rsn_caps",
                "vendor_ies",
                "signal",
                "iface",
                "rx_phy",
                "tx_phy",
                "link_freq",
                "rx_bitrate",
                "tx_bitrate",
                "expected_tp",
                "rx_packets",
                "tx_packets",
                "rx_bytes",
                "tx_bytes",
                "rx_drop_misc",
                "signal_avg",
                "tx_retries",
                "tx_retry_rate",
                "tx_failed",
                "tx_fail_rate",
                "channel_busy",
                "noise_floor",
                "inactive",
                "connected_time",
                "snr",
                "signal_chains",
                "roam",
            ):
                v[key].setText(dim("—"))
            return

        ap = connected_ap

        color = self._model.ssid_colors().get(ap.ssid, QColor(FALLBACK_GRAY)).name()
        connected_badge = (
            f" &nbsp;<span style='font-size:13px;font-weight:600;color:{CONNECTED_GREEN};'>"
            "CONNECTED AP</span>"
        )
        self._conn_ssid.setText(
            f'<span style="font-size:20px;font-weight:700;color:{color}">{html.escape(ap.display_ssid)}</span>{connected_badge}'
        )

        v["status"].setText("Connected")
        v["ssid"].setText(html.escape(ap.display_ssid))
        v["bssid"].setText(ap.bssid)
        manuf_text = format_manufacturer_display(ap.manufacturer)
        v["manufacturer"].setText(html.escape(manuf_text) or dim("Unknown"))
        v["band"].setText(ap.band)
        v["channel"].setText(str(ap.channel) if ap.channel else dim("Unknown"))
        v["security"].setText(ap.security_short or dim("Unknown"))
        v["akm"].setText(ap.akm or ap.akm_raw or dim("Unknown"))
        v["pmf"].setText(ap.pmf or dim("Unknown"))
        v["beacon_interval"].setText(
            f"{ap.beacon_interval_tu} TU"
            if ap.beacon_interval_tu is not None
            else dim("Not advertised")
        )
        v["dtim_period"].setText(
            str(ap.dtim_period) if ap.dtim_period is not None else dim("Not advertised")
        )
        v["rsn_caps"].setText(ap.rsn_capabilities or dim("Not advertised"))
        v["vendor_ies"].setText(ap.vendor_ie_ouis or dim("Not advertised"))
        v["signal"].setText(f"{ap.dbm} dBm  ({ap.signal}%)")
        if ap.conn_snr_db is not None:
            v["snr"].setText(f"{ap.conn_snr_db:.0f} dB")
        else:
            v["snr"].setText(dim("Needs noise floor (driver does not report survey data)"))
        v["signal_chains"].setText(
            f"{ap.conn_signal_chains} dBm" if ap.conn_signal_chains else dim("Not reported")
        )
        cands = roam_candidates(ap, self._aps)
        if cands:
            v["roam"].setText(
                "<br>".join(
                    f"{c.bssid} · {c.band} ch {c.channel} · {c.dbm} dBm "
                    + dim(f"({c.dbm - ap.dbm:+d} dB)")
                    for c in cands[:6]
                )
            )
        else:
            v["roam"].setText(dim("No other BSSID of this SSID visible"))

        v["iface"].setText(ap.conn_iface or dim("Unknown"))
        v["rx_phy"].setText(ap.conn_rx_phy or dim("Not reported"))
        v["tx_phy"].setText(ap.conn_tx_phy or dim("Not reported"))
        if ap.conn_link_freq_mhz is not None:
            v["link_freq"].setText(f"{ap.conn_link_freq_mhz} MHz")
        else:
            v["link_freq"].setText(dim("Not reported"))
        v["rx_bitrate"].setText(ap.conn_rx_bitrate or dim("Not reported"))
        v["tx_bitrate"].setText(ap.conn_tx_bitrate or dim("Not reported"))
        v["expected_tp"].setText(ap.conn_expected_tp or dim("Not reported"))
        v["rx_packets"].setText(
            str(ap.conn_rx_packets)
            if ap.conn_rx_packets is not None
            else dim("Not reported")
        )
        v["tx_packets"].setText(
            str(ap.conn_tx_packets)
            if ap.conn_tx_packets is not None
            else dim("Not reported")
        )
        v["rx_bytes"].setText(
            str(ap.conn_rx_bytes)
            if ap.conn_rx_bytes is not None
            else dim("Not reported")
        )
        v["tx_bytes"].setText(
            str(ap.conn_tx_bytes)
            if ap.conn_tx_bytes is not None
            else dim("Not reported")
        )
        v["rx_drop_misc"].setText(
            str(ap.conn_rx_drop_misc)
            if ap.conn_rx_drop_misc is not None
            else dim("Not reported")
        )
        if ap.conn_signal_avg_dbm is not None:
            v["signal_avg"].setText(f"{ap.conn_signal_avg_dbm} dBm")
        else:
            v["signal_avg"].setText(dim("Not reported"))
        if ap.conn_tx_retries is not None:
            v["tx_retries"].setText(str(ap.conn_tx_retries))
        else:
            v["tx_retries"].setText(dim("Not reported"))
        if ap.conn_tx_retry_rate_pct is not None:
            v["tx_retry_rate"].setText(f"{ap.conn_tx_retry_rate_pct:.1f}%")
        else:
            v["tx_retry_rate"].setText(dim("Not reported"))
        if ap.conn_tx_failed is not None:
            v["tx_failed"].setText(str(ap.conn_tx_failed))
        else:
            v["tx_failed"].setText(dim("Not reported"))
        if ap.conn_tx_fail_rate_pct is not None:
            v["tx_fail_rate"].setText(f"{ap.conn_tx_fail_rate_pct:.1f}%")
        else:
            v["tx_fail_rate"].setText(dim("Not reported"))
        if ap.conn_survey_busy_pct is not None:
            v["channel_busy"].setText(f"{ap.conn_survey_busy_pct:.1f}%")
        else:
            v["channel_busy"].setText(dim("Not reported"))
        if ap.conn_survey_noise_dbm is not None:
            v["noise_floor"].setText(f"{ap.conn_survey_noise_dbm} dBm")
        else:
            v["noise_floor"].setText(dim("Not reported"))
        if ap.conn_inactive_ms is not None:
            v["inactive"].setText(f"{ap.conn_inactive_ms} ms")
        else:
            v["inactive"].setText(dim("Not reported"))
        if ap.conn_connected_time_s is not None:
            v["connected_time"].setText(f"{ap.conn_connected_time_s} s")
        else:
            v["connected_time"].setText(dim("Not reported"))

    def eventFilter(self, obj, event):
        # Keep the first-scan overlay filling the table when it is resized
        if (
            hasattr(self, "_scan_overlay")
            and obj is self._table
            and event.type() == QEvent.Type.Resize
            and self._scan_overlay.isVisible()
        ):
            self._scan_overlay.setGeometry(self._table.rect())
        if (
            hasattr(self, "_manufacturer_tip_widgets")
            and obj in self._manufacturer_tip_widgets
            and event.type()
            in {
                QEvent.Type.ToolTip,
                QEvent.Type.Enter,
                QEvent.Type.MouseButtonPress,
            }
        ):
            tip = obj.toolTip() if hasattr(obj, "toolTip") else ""
            if tip:
                QToolTip.showText(QCursor.pos(), tip, obj)
                if event.type() == QEvent.Type.ToolTip:
                    return True
        return super().eventFilter(obj, event)

    def _prompt_oui_download(self):
        dlg = OuiDownloadDialog(self, first_run=True)
        dlg.exec()
        if dlg.downloaded:
            self._after_oui_update()

    def _on_update_oui(self):
        dlg = OuiDownloadDialog(self, first_run=False)
        dlg.exec()
        if dlg.downloaded:
            self._after_oui_update()
            self.statusBar().showMessage("OUI database updated — re-scanning…")

    def _after_oui_update(self) -> None:
        """New AccessPoints resolve vendors from the reloaded DB on the next
        scan; lingering copies (and cached manufacturer fields) still carry
        the old names, so drop them."""
        for cache in self._iw_cache.values():
            cache.pop("manufacturer", None)
            cache.pop("manufacturer_source", None)
        if self._scanner is not None:
            self._scanner.request_cache_clear()

    def _status(self, msg: str):
        self.statusBar().showMessage(msg)

    def closeEvent(self, event):
        # A running capture has taken the interface out of NetworkManager's
        # control (or stopped NM); restore it before the app goes away.
        busy = [
            w
            for w in (getattr(self, "_monitor_win", None), getattr(self, "_managed_win", None))
            if w is not None and w.is_busy()
        ]
        if busy:
            ans = QMessageBox.question(
                self,
                "Capture in progress",
                "A packet capture is still running.\n\n"
                "Stop it and restore the Wi-Fi interface before quitting?\n"
                "(You may be asked for your password.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if ans != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.statusBar().showMessage("Stopping capture and restoring the interface…")
            QApplication.processEvents()
            for w in busy:
                w.shutdown_blocking()

        self._save_settings()
        self._stop_scanner(wait_ms=None)
        for sc in list(self._retired_scanners):
            sc.stop(wait_ms=None)
        super().closeEvent(event)

    # ── Settings persistence (QSettings: ~/.config/wavescope/WaveScope.conf) ──

    def _restore_settings(self) -> None:
        st = self._settings

        def _int(key: str, default: int) -> int:
            try:
                return int(st.value(key, default))
            except (TypeError, ValueError):
                return default

        geo = st.value("window/geometry")
        if isinstance(geo, QByteArray) and not geo.isEmpty():
            self.restoreGeometry(geo)
        for key, splitter in (("window/h_splitter", self._h_splitter), ("window/v_splitter", self._v_splitter)):
            state = st.value(key)
            if isinstance(state, QByteArray) and not state.isEmpty():
                splitter.restoreState(state)
        self._sidebar_last_width = _int("window/sidebar_width", self._sidebar_last_width)
        if st.value("window/sidebar_visible", "true") in (False, "false"):
            self._btn_sidebar.setChecked(False)

        idx = _int("scan/interval_index", self._interval_combo.currentIndex())
        if 0 <= idx < self._interval_combo.count():
            self._interval_combo.setCurrentIndex(idx)
        self._linger_spin.setValue(_int("scan/linger_s", self._linger_spin.value()))
        band = st.value("filter/band", "All")
        if isinstance(band, str) and self._band_combo.findText(band) >= 0:
            self._band_combo.setCurrentText(band)

        theme = _int("ui/theme_index", 0)
        if 0 <= theme < self._theme_combo.count():
            self._theme_combo.setCurrentIndex(theme)  # emits → _on_theme_change
        mode = st.value("graph/multi_ssid_label", "apname")
        if isinstance(mode, str):
            self._channel_graph.set_label_mode(mode)
        tab = _int("ui/tab_index", 0)
        if 0 <= tab < self._tabs.count():
            self._tabs.setCurrentIndex(tab)

        widths = st.value("table/user_column_widths", {})
        if isinstance(widths, dict):
            for col_s, w in widths.items():
                try:
                    col, w = int(col_s), int(w)
                except (TypeError, ValueError):
                    continue
                if 0 <= col < len(TABLE_HEADERS) and w > 0:
                    self._table.setColumnWidth(col, w)
                    self._user_sized_cols.add(col)

    def _save_settings(self) -> None:
        st = self._settings
        st.setValue("window/geometry", self.saveGeometry())
        st.setValue("window/h_splitter", self._h_splitter.saveState())
        st.setValue("window/v_splitter", self._v_splitter.saveState())
        st.setValue("window/sidebar_width", int(getattr(self, "_sidebar_last_width", 180)))
        st.setValue("window/sidebar_visible", self._btn_sidebar.isChecked())
        st.setValue("scan/interval_index", self._interval_combo.currentIndex())
        st.setValue("scan/linger_s", self._linger_spin.value())
        st.setValue("filter/band", self._band_combo.currentText())
        st.setValue("ui/theme_index", self._theme_combo.currentIndex())
        st.setValue("ui/tab_index", self._tabs.currentIndex())
        st.setValue("graph/multi_ssid_label", self._channel_graph.label_mode())
        st.setValue(
            "table/user_column_widths",
            {str(c): self._table.columnWidth(c) for c in sorted(self._user_sized_cols)},
        )
        st.sync()
