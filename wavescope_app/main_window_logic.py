"""Main window behavior and handlers mixin.

Contains data-flow, event handlers, selection logic, theming,
and detail/connection rendering methods for the main window.
"""

from .core import *
from .core_vendor import _resolve_vendor_icon_path
from .graphs import ChannelAllocationsDialog
from .capture import CaptureTypeDialog, ManagedCaptureWindow, MonitorModeWindow
from .theme import IW_GEN_COLORS, _dark_palette, _light_palette


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

    def _capture_selection_bssids(self) -> Tuple[set[str], Optional[str]]:
        """Return ({selected_bssids}, focused_bssid) from the current table selection."""
        sm = self._table.selectionModel()
        if sm is None:
            return set(), None

        selected_bssids: set[str] = set()
        for proxy_idx in sm.selectedRows():
            src_idx = self._proxy.mapToSource(proxy_idx)
            ap = self._model.ap_at(src_idx.row())
            if ap is not None:
                selected_bssids.add(ap.bssid)

        focused_bssid: Optional[str] = None
        cur_proxy = sm.currentIndex()
        if cur_proxy.isValid():
            src_idx = self._proxy.mapToSource(cur_proxy)
            ap = self._model.ap_at(src_idx.row())
            if ap is not None:
                focused_bssid = ap.bssid

        return selected_bssids, focused_bssid

    def _restore_selection_bssids(
        self, selected_bssids: set[str], focused_bssid: Optional[str]
    ) -> None:
        """Restore table selection by BSSID after a model reset."""
        sm = self._table.selectionModel()
        if sm is None:
            return

        sm.blockSignals(True)
        try:
            sm.clearSelection()
            first_idx = QModelIndex()
            preferred_idx = QModelIndex()

            for row in range(self._model.rowCount()):
                ap = self._model.ap_at(row)
                if ap is None or ap.bssid not in selected_bssids:
                    continue

                proxy_idx = self._proxy.mapFromSource(self._model.index(row, 0))
                if not proxy_idx.isValid():
                    continue

                sm.select(
                    proxy_idx,
                    QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows,
                )

                if not first_idx.isValid():
                    first_idx = proxy_idx
                if focused_bssid and ap.bssid == focused_bssid:
                    preferred_idx = proxy_idx

            current = preferred_idx if preferred_idx.isValid() else first_idx
            if current.isValid():
                sm.setCurrentIndex(
                    current,
                    QItemSelectionModel.SelectionFlag.Current
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
                self._table.scrollTo(
                    current,
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                )
        finally:
            sm.blockSignals(False)

        self._on_selection_change(None, None)

    # Fields populated exclusively by enrich_with_iw — persist across missed cycles
    _IW_PERSIST_FIELDS = (
        "dbm_exact",
        "manufacturer",
        "manufacturer_source",
        "wps_manufacturer",
        "wifi_gen",
        "chan_util",
        "station_count",
        "pmf",
        "akm",
        "akm_raw",
        "rrm",
        "btm",
        "ft",
        "country",
        "iw_center_freq",
        "beacon_interval_tu",
        "dtim_period",
        "rsn_capabilities",
        "vendor_ie_ouis",
        "phy_cap_summary",
        "he_eht_features",
        "conn_iface",
        "conn_link_ssid",
        "conn_link_freq_mhz",
        "conn_link_signal_dbm",
        "conn_rx_bitrate",
        "conn_tx_bitrate",
        "conn_expected_tp",
        "conn_signal_avg_dbm",
        "conn_tx_retries",
        "conn_tx_failed",
        "conn_inactive_ms",
        "conn_connected_time_s",
        "conn_tx_packets",
        "conn_tx_bytes",
        "conn_rx_packets",
        "conn_rx_bytes",
        "conn_rx_drop_misc",
        "conn_rx_phy",
        "conn_tx_phy",
        "conn_tx_retry_rate_pct",
        "conn_tx_fail_rate_pct",
        "conn_survey_busy_pct",
        "conn_survey_noise_dbm",
    )

    # Fields where 0 / "" / None means "parse failed" — once we get a real
    # value the last-good value is kept even if subsequent cycles return 0.
    _STICKY_NONZERO_FIELDS = (
        "bandwidth_mhz",   # nmcli returns 0 for 6 GHz
        "rate_mbps",       # nmcli returns 0 for 6 GHz
        "wifi_gen",        # may be "" when iw scan cache is stale
        "country",         # Country IE sometimes absent on one cycle
        "iw_center_freq",  # may be None when iw misses the center-freq line
    )

    def _auto_size_table_columns(self):
        """
        Fit all table columns to visible content/header, then distribute any
        remaining horizontal space across all columns so the table fills width.
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

        widths = required[:]
        total = sum(widths)

        if total > viewport_w and total > 0:
            scale = viewport_w / total
            widths = [max(min_w, int(w * scale)) for w in widths]

        # If there's remaining room, distribute it across all columns
        total = sum(widths)
        if total < viewport_w:
            extra = viewport_w - total
            weight_sum = sum(required) or col_count
            adds = [int(extra * (w / weight_sum)) for w in required]
            widths = [w + a for w, a in zip(widths, adds)]

            # Rounding fix-up: spread leftover pixels across columns
            rem = viewport_w - sum(widths)
            if rem > 0:
                order = sorted(
                    range(col_count), key=lambda i: required[i], reverse=True
                )
                for i in range(rem):
                    widths[order[i % col_count]] += 1

        # If rounding/scaling left us too wide, trim proportionally (not one column)
        total = sum(widths)
        if total > viewport_w:
            over = total - viewport_w
            while over > 0:
                changed = False
                for i in sorted(
                    range(col_count), key=lambda k: widths[k], reverse=True
                ):
                    if widths[i] > min_w:
                        widths[i] -= 1
                        over -= 1
                        changed = True
                        if over == 0:
                            break
                if not changed:
                    break

        self._suspend_col_resize_tracking = True
        try:
            for col, w in enumerate(widths):
                self._table.setColumnWidth(col, max(min_w, w))
        finally:
            self._suspend_col_resize_tracking = False

    def _on_data(self, aps: List[AccessPoint]):
        selected_bssids, focused_bssid = self._capture_selection_bssids()

        # ── sticky-nonzero field restoration ────────────────────────────────
        # For nmcli/iw fields that can transiently return 0/""/None even though
        # a real value was seen before (e.g. bandwidth_mhz=0 for 6 GHz when
        # nmcli loses the parse):  keep the last known-good value.
        for ap in aps:
            key = ap.bssid.lower()
            cache = self._sticky_cache.setdefault(key, {})
            for field in self._STICKY_NONZERO_FIELDS:
                val = getattr(ap, field)
                if val:                    # nonzero / non-empty / non-None → update
                    cache[field] = val
                elif field in cache:       # zero/empty but we have a good value
                    setattr(ap, field, cache[field])

        # ── iw-field persistence ─────────────────────────────────────────────
        # pmf is set to "No" / "Optional" / "Required" by iw for every AP it
        # sees; a blank pmf means iw missed this AP on this cycle.
        for ap in aps:
            key = ap.bssid.lower()
            if ap.pmf != "":
                # iw enriched this AP — refresh cache, reset miss counter
                self._iw_cache[key] = {
                    f: getattr(ap, f) for f in self._IW_PERSIST_FIELDS
                }
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

            if key in self._iw_cache:
                self._iw_cache[key] = {
                    f: getattr(ap, f) for f in self._IW_PERSIST_FIELDS
                }
        # ────────────────────────────────────────────────────────────────────
        self._aps = aps
        self._model.update(aps)
        if selected_bssids:
            self._restore_selection_bssids(selected_bssids, focused_bssid)
        # model.update() emits modelReset (not layoutChanged), so the proxy's
        # layoutChanged won't fire — update the graph explicitly here.
        self._channel_graph.update_aps(self._visible_aps(), self._model.ssid_colors())
        self._history_graph.set_ssid_colors(self._model.ssid_colors())
        self._history_graph.push(aps)
        self._auto_size_table_columns()

        total = len(aps)
        shown = self._proxy.rowCount()
        self._lbl_count.setText(f"  {shown}/{total} APs")
        ts = time.strftime("%H:%M:%S")
        self._lbl_updated.setText(f"  Last scan: {ts}  ")
        self.statusBar().showMessage(f"Found {total} access points  |  Showing {shown}")
        self._show_connection()

    def _on_theme_change(self, idx: int):
        modes = ["dark", "light", "auto"]
        self._apply_theme(modes[idx])

    def _apply_theme(self, mode: str):
        app = QApplication.instance()
        if mode == "dark":
            app.setPalette(_dark_palette())
            plot_bg, plot_fg = "#0d1117", "#a9b4cc"
            is_dark = True
        elif mode == "light":
            app.setPalette(_light_palette())
            plot_bg, plot_fg = "#f0f4f8", "#444455"
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
                ("#0d1117", "#a9b4cc") if is_dark else ("#f0f4f8", "#444455")
            )
        pg.setConfigOptions(foreground=plot_fg, background=plot_bg)
        self._channel_graph.set_theme(plot_bg, plot_fg)
        self._history_graph.set_theme(plot_bg, plot_fg)
        self._apply_details_theme(is_dark)
        if hasattr(self, "_alloc_dialog") and self._alloc_dialog is not None:
            self._alloc_dialog.sync_theme(is_dark)
        self._table.viewport().update()

    def _apply_details_theme(self, is_dark: bool):
        if is_dark:
            card_bg = "#121a27"
            card_border = "#273248"
            name_color = "#8ea0bf"
            value_bg = "#0f1622"
            value_border = "#2a3850"
            value_color = "#dfe7f5"
        else:
            card_bg = "#ffffff"
            card_border = "#c7d2e3"
            name_color = "#4a5a73"
            value_bg = "#eef3fb"
            value_border = "#c8d6ee"
            value_color = "#22314a"

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

        self._details_widget.setStyleSheet(details_style)
        if hasattr(self, "_connection_widget"):
            self._connection_widget.setStyleSheet(details_style)

    def _on_error(self, msg: str):
        self.statusBar().showMessage(f"⚠ Scanner error: {msg}")

    def _on_col_resized(self, col: int, old_size: int, new_size: int):
        """Record that the user explicitly resized this column."""
        if getattr(self, "_suspend_col_resize_tracking", False):
            return
        self._user_sized_cols.add(col)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._auto_size_table_columns()

    def _on_band_change(self, band: str):
        self._proxy.set_band(
            band
        )  # → invalidateFilter → layoutChanged → _on_filter_changed
        self._channel_graph.set_band(band)

    def _on_interval_change(self, idx: int):
        secs = REFRESH_INTERVALS[idx]
        self._scanner.set_interval(secs)

    def _on_linger_change(self, secs: int):
        self._scanner.set_linger_secs(float(secs))

    def _on_pause(self, paused: bool):
        if paused:
            self._scanner.stop()
            self._btn_pause.setText("▶ Resume")
            self.statusBar().showMessage("Paused — click Resume to continue scanning")
        else:
            self._scanner = WiFiScanner(
                interval_sec=REFRESH_INTERVALS[self._interval_combo.currentIndex()],
                linger_secs=float(self._linger_spin.value()),
            )
            self._scanner.data_ready.connect(self._on_data)
            self._scanner.scan_error.connect(self._on_error)
            self._scanner.start()
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
        """Called when user clicks a label in the channel graph."""
        if bssid is None:
            self._table.clearSelection()
            self._history_graph.filter_bssids(None)
            return
        # Find the row for this bssid and select it
        for row in range(self._model.rowCount()):
            ap = self._model.ap_at(row)
            if ap and ap.bssid == bssid:
                proxy_row = self._proxy.mapFromSource(self._model.index(row, 0)).row()
                if proxy_row >= 0:
                    self._table.selectRow(proxy_row)
                break
        self._history_graph.filter_bssids({bssid})

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
            single_bssid = ap.bssid if len(selected_bssids) == 1 else None
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
            "QMenu{background:#131926;border:1px solid #2a3350;color:#d0d8f0;}"
            "QMenu::item:selected{background:#1e4a80;}"
            "QMenu::separator{height:1px;background:#2a3350;margin:3px 8px;}"
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

        menu.addSeparator()

        # Remove specific include/exclude
        if self._proxy.has_col_filters():
            clear_a = menu.addAction("✕  Clear all column filters")
            clear_a.triggered.connect(self._on_clear_col_filters)

        menu.addSeparator()

        # Details shortcut
        det = menu.addAction("ℹ  View details")
        det.triggered.connect(lambda: self._open_details_for_proxy_row(idx.row()))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _open_details_for_proxy_row(self, proxy_row: int) -> None:
        if proxy_row < 0:
            return
        proxy_idx = self._proxy.index(proxy_row, 0)
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
        if self._proxy.has_col_filters():
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
        self._refresh_filter_badge()

    def _show_details(self, ap: AccessPoint):
        color = self._model.ssid_colors().get(ap.ssid, QColor("#888888")).name()
        sig_col = signal_color(ap.signal).name()

        def badge(text, bg=None, fg=None):
            color = fg or bg
            if color:
                return (
                    f'<span style="color:{color};font-size:14px;font-weight:600">'
                    f"{text}</span>"
                )
            return f'<span style="font-size:14px;font-weight:600">{text}</span>'

        def dim(text):
            return f"<span style='color:#777'>{text}</span>"

        # ── SSID header ───────────────────────────────────────────────────
        in_use = (
            (
                ' &nbsp;<span style="font-size:13px;font-weight:600;color:#2e7d32;">'
                '▲ CONNECTED</span>'
            )
            if ap.in_use
            else ""
        )
        self._det_ssid.setText(
            f'<span style="font-size:20px;font-weight:700;color:{color}">{ap.display_ssid}</span>{in_use}'
        )

        # ── WiFi generation ───────────────────────────────────────────────
        gen_color = IW_GEN_COLORS.get(ap.wifi_gen, "#37474F")
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

        if sec_display == "Open":
            sec_html = badge(sec_display, "#b71c1c")
        elif "WPA3" in sec_display or "SAE" in sec_display:
            sec_html = badge(sec_display, "#1b5e20")
        elif "WPA2" in sec_display:
            sec_html = badge(sec_display, "#0d47a1")
        else:
            sec_html = badge(sec_display, "#37474F")

        # ── PMF ───────────────────────────────────────────────────────────
        pmf_map = {"Required": "#1b5e20", "Optional": "#e65100", "No": "#b71c1c"}
        pmf_c = pmf_map.get(ap.pmf)
        pmf_html = badge(ap.pmf, pmf_c) if pmf_c else dim(ap.pmf or "Unknown")

        # ── Channel utilisation ───────────────────────────────────────────
        util_pct = ap.chan_util_pct
        if util_pct is not None:
            if util_pct >= 75:
                uc = "#f44336"
            elif util_pct >= 50:
                uc = "#ff9800"
            elif util_pct >= 25:
                uc = "#ffc107"
            else:
                uc = "#4caf50"
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
                    f"style='vertical-align:middle;'> &nbsp;{manuf_text}"
                )
            else:
                v["manufacturer"].setText(manuf_text)
        else:
            v["manufacturer"].setText(dim("Unknown"))
        manuf_tip = f"Source: {manuf_source}"
        v["manufacturer"].setToolTip(manuf_tip)
        if "manufacturer" in self._det_name_labels:
            self._det_name_labels["manufacturer"].setToolTip(manuf_tip)
        v["wifi_gen"].setText(gen_html)
        v["mode_80211"].setText(ap.phy_mode)
        v["band"].setText(ap.band)
        v["channel"].setText(str(ap.channel))
        v["frequency"].setText(f"{ap.freq_mhz} MHz")
        v["chan_width"].setText(f"{ap.bandwidth_mhz} MHz")
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
            sec_line_bottom = dim(sec_secondary)
            v["security"].setText(f"{sec_line_top}<br>{sec_line_bottom}")
        else:
            v["security"].setText(sec_line_top)
        v["security"].setToolTip("")
        v["wpa_flags"].setText(format_ie_flags(ap.wpa_flags, "WPA IE not present"))
        v["rsn_flags"].setText(format_ie_flags(ap.rsn_flags, "RSN IE not present"))
        v["rsn_caps"].setText(ap.rsn_capabilities or dim("Not advertised"))
        v["vendor_ies"].setText(ap.vendor_ie_ouis or dim("Not advertised"))
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
        v["wps_manufacturer"].setText(ap.wps_manufacturer or dim("Not advertised"))
        v["pmf"].setText(pmf_html)
        v["chan_util"].setText(util_html)
        v["clients"].setText(
            str(ap.station_count) if ap.station_count is not None else dim("Unknown")
        )
        v["roaming"].setText(kvr_html)

    def _show_connection(self):
        def dim(text):
            return f"<span style='color:#777'>{text}</span>"

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
                (x for x in self._aps if x.conn_iface or x.conn_link_freq_mhz is not None),
                None,
            )
        v = self._conn_vals
        if connected_ap is None:
            self._conn_ssid.setText(
                "<span style='font-size:20px;font-weight:700;color:#777'>Wifi not connected</span>"
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
            ):
                v[key].setText(dim("—"))
            return

        ap = connected_ap

        color = self._model.ssid_colors().get(ap.ssid, QColor("#888888")).name()
        connected_badge = (
            " &nbsp;<span style='font-size:13px;font-weight:600;color:#2e7d32;'>"
            "CONNECTED AP</span>"
        )
        self._conn_ssid.setText(
            f'<span style="font-size:20px;font-weight:700;color:{color}">{ap.display_ssid}</span>{connected_badge}'
        )

        v["status"].setText("Connected")
        v["ssid"].setText(ap.display_ssid)
        v["bssid"].setText(ap.bssid)
        manuf_text = format_manufacturer_display(ap.manufacturer)
        v["manufacturer"].setText(manuf_text or dim("Unknown"))
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
            str(ap.conn_rx_packets) if ap.conn_rx_packets is not None else dim("Not reported")
        )
        v["tx_packets"].setText(
            str(ap.conn_tx_packets) if ap.conn_tx_packets is not None else dim("Not reported")
        )
        v["rx_bytes"].setText(
            str(ap.conn_rx_bytes) if ap.conn_rx_bytes is not None else dim("Not reported")
        )
        v["tx_bytes"].setText(
            str(ap.conn_tx_bytes) if ap.conn_tx_bytes is not None else dim("Not reported")
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
        # After a successful download the OUI DB is already reloaded globally;
        # trigger a fresh scan so new AP objects pick up the better names.
        if OUI_JSON_PATH.exists():
            self._scanner.stop()
            self._scanner = WiFiScanner(
                interval_sec=REFRESH_INTERVALS[self._interval_combo.currentIndex()],
                linger_secs=float(self._linger_spin.value()),
            )
            self._scanner.data_ready.connect(self._on_data)
            self._scanner.scan_error.connect(self._on_error)
            self._scanner.start()

    def _on_update_oui(self):
        dlg = OuiDownloadDialog(self, first_run=False)
        dlg.exec()
        if OUI_JSON_PATH.exists():
            # Restart scanner so APs get fresh manufacturer names
            self._scanner.stop()
            self._scanner = WiFiScanner(
                interval_sec=REFRESH_INTERVALS[self._interval_combo.currentIndex()],
                linger_secs=float(self._linger_spin.value()),
            )
            self._scanner.data_ready.connect(self._on_data)
            self._scanner.scan_error.connect(self._on_error)
            self._scanner.start()
            self.statusBar().showMessage("OUI database updated — re-scanning…")

    def _status(self, msg: str):
        self.statusBar().showMessage(msg)

    def closeEvent(self, event):
        self._scanner.stop()
        super().closeEvent(event)
