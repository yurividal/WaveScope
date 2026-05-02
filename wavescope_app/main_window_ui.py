"""Main window UI construction mixin.

Contains the UI assembly code for the main application window.
"""

from .core import *
from .graphs import ChannelGraphWidget, SignalHistoryWidget
from .ap_sidebar import APGroupSidebar
from .known_ssids import KnownSSIDStore, KnownSSIDDialog


class MainWindowUIMixin:
    def _setup_ui(self):
        # ── Toolbar ────────────────────────────────────────────────────────
        tb = QToolBar("Main Toolbar")
        tb.setMovable(False)
        tb.setIconSize(pg.QtCore.QSize(16, 16))
        self.addToolBar(tb)

        # ── Shared style helpers ────────────────────────────────────────
        _GROUP_BG  = "#0a1520"
        _GROUP_BDR = "#1c2e44"
        _GROUP_LBL = "#3a5880"

        def _btn_ss(checkable=False) -> str:
            s = (
                f"QPushButton {{ color:{BTN_ACCENT}; border:1px solid {BTN_BORDER};"
                f" border-radius:3px; padding:2px 8px; background:transparent; }}"
                f"QPushButton:hover {{ background:{BTN_HOVER_BG}; }}"
            )
            if checkable:
                s += (
                    f"QPushButton:checked {{ color:{BTN_CHECKED_TEXT};"
                    f" border-color:{BTN_CHECKED_BORDER}; background:{BTN_CHECKED_BG}; }}"
                )
            return s

        def _make_group(label: str, widgets: list) -> QFrame:
            """Wrap *widgets* in a labelled rounded-rect pill."""
            frame = QFrame()
            frame.setObjectName("tbGroup")
            frame.setStyleSheet(
                f"QFrame#tbGroup {{ background:{_GROUP_BG};"
                f" border:1px solid {_GROUP_BDR}; border-radius:6px; }}"
            )
            lay = QHBoxLayout(frame)
            lay.setContentsMargins(7, 2, 7, 2)
            lay.setSpacing(5)
            hdr = QLabel(label)
            hdr.setObjectName("tbGroupHeader")
            hdr.setStyleSheet(
                f"color:{_GROUP_LBL}; font-size:7pt; font-weight:700;"
                " letter-spacing:0.5px; border:none; background:transparent;"
            )
            lay.addWidget(hdr)
            div = QFrame()
            div.setFrameShape(QFrame.Shape.VLine)
            div.setFixedWidth(1)
            div.setStyleSheet(f"background:{_GROUP_BDR}; border:none;")
            lay.addWidget(div)
            for w in widgets:
                lay.addWidget(w)
            return frame

        # ── SCAN group widgets ──────────────────────────────────────────
        self._btn_pause = QPushButton("⏸ Pause")
        self._btn_pause.setCheckable(True)
        self._btn_pause.setStyleSheet(_btn_ss(checkable=True))
        self._btn_pause.toggled.connect(self._on_pause)

        self._interval_combo = QComboBox()
        for s in REFRESH_INTERVALS:
            self._interval_combo.addItem(f"{s}s", s)
        self._interval_combo.setFixedWidth(58)
        self._interval_combo.setToolTip("Scan refresh interval")
        self._interval_combo.currentIndexChanged.connect(self._on_interval_change)

        self._linger_spin = QSpinBox()
        self._linger_spin.setRange(0, 600)
        self._linger_spin.setValue(60)
        self._linger_spin.setSuffix(" s")
        self._linger_spin.setFixedWidth(68)
        self._linger_spin.setToolTip(
            "Keep vanished APs visible for this many seconds after they disappear\n"
            "(0 = remove immediately)"
        )
        self._linger_spin.valueChanged.connect(self._on_linger_change)

        # ⚙ Tools drop-down (OUI + Capture — less-frequent actions)
        self._btn_tools = QPushButton("⚙ Tools ▾")
        self._btn_tools.setStyleSheet(_btn_ss())
        self._btn_tools.setToolTip("OUI database and packet capture")
        _tools_menu = QMenu(self)
        _tools_menu.addAction("📖  Update OUI Database", self._on_update_oui)
        _tools_menu.addSeparator()
        _tools_menu.addAction("📡  Packet Capture…", self._on_monitor_mode)
        self._btn_tools.clicked.connect(
            lambda: _tools_menu.exec(
                self._btn_tools.mapToGlobal(self._btn_tools.rect().bottomLeft())
            )
        )

        # ── VIEW group widgets ──────────────────────────────────────────
        self._btn_sidebar = QPushButton("⊞ APs")
        self._btn_sidebar.setCheckable(True)
        self._btn_sidebar.setChecked(True)
        self._btn_sidebar.setToolTip("Show / hide the Access Point sidebar")
        self._btn_sidebar.setStyleSheet(_btn_ss(checkable=True))
        self._btn_sidebar.toggled.connect(self._on_sidebar_toggle)

        # ── FILTER group widgets ────────────────────────────────────────
        self._band_combo = QComboBox()
        self._band_combo.addItems(["All", "2.4 GHz", "5 GHz", "6 GHz"])
        self._band_combo.setFixedWidth(88)
        self._band_combo.setToolTip("Filter by frequency band")
        self._band_combo.currentTextChanged.connect(self._on_band_change)

        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  SSID / MAC / vendor…")
        self._search.setFixedWidth(240)
        self._search.textChanged.connect(self._proxy.set_text)

        self._known_combo = QComboBox()
        self._known_combo.addItem("All",          "off")
        self._known_combo.addItem("Only known",   "only")
        self._known_combo.addItem("Hide known",   "hide")
        self._known_combo.setFixedWidth(112)
        self._known_combo.setToolTip(
            "Filter by Known SSIDs list.\n"
            "'Only known' shows only marked SSIDs.\n"
            "'Hide known' hides them."
        )
        self._known_combo.currentIndexChanged.connect(self._on_known_filter_change)

        self._btn_known_edit = QPushButton("Edit…")
        self._btn_known_edit.setToolTip("Open the Known SSIDs manager")
        self._btn_known_edit.setStyleSheet(_btn_ss())
        self._btn_known_edit.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        self._btn_known_edit.clicked.connect(self._on_known_edit)

        # ── Assemble pill groups ────────────────────────────────────────
        _scan_group = _make_group("SCAN", [
            self._btn_pause,
            QLabel(" Refresh:"), self._interval_combo,
            QLabel(" Linger:"), self._linger_spin,
            self._btn_tools,
        ])
        _view_group = _make_group("VIEW", [
            self._btn_sidebar,
        ])
        _filter_group = _make_group("Filters", [
            self._search,
            QLabel(" Band:"), self._band_combo,
            QLabel(" SSIDs:"), self._known_combo,
            self._btn_known_edit,
        ])
        _filter_group.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )

        # ── Assemble toolbar layout ─────────────────────────────────────
        self._tb_groups = [_scan_group, _view_group, _filter_group]

        # ── Status widgets (right, no pill) ────────────────────────────
        self._lbl_count = QLabel("  0 APs")

        self._lbl_filters = QLabel()
        self._lbl_filters.setStyleSheet(f"color:{BTN_CHECKED_TEXT}; font-size:9pt;")
        self._lbl_filters.hide()

        self._btn_clear_filters = QPushButton("✕ Clear filters")
        self._btn_clear_filters.setStyleSheet(
            f"QPushButton{{color:{BTN_CHECKED_TEXT};border:1px solid {BTN_CHECKED_TEXT};"
            f"border-radius:3px;padding:1px 6px;font-size:9pt;}}"
            f"QPushButton:hover{{background:{BTN_CHECKED_BG};}}"
        )
        self._btn_clear_filters.clicked.connect(self._on_clear_col_filters)
        self._btn_clear_filters.hide()

        # ── Single widget fills toolbar ─────────────────────────────────
        _tb_widget = QWidget()
        _tb_lay = QHBoxLayout(_tb_widget)
        _tb_lay.setContentsMargins(4, 2, 4, 2)
        _tb_lay.setSpacing(8)
        _tb_lay.addWidget(_scan_group)
        _tb_lay.addWidget(_view_group)
        _tb_lay.addWidget(_filter_group)
        _spacer = QWidget()
        _spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        _tb_lay.addWidget(_spacer)
        _tb_lay.addWidget(self._lbl_count)
        _tb_lay.addWidget(self._lbl_filters)
        _tb_lay.addWidget(self._btn_clear_filters)
        tb.addWidget(_tb_widget)

        # ── Central widget ─────────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Horizontal splitter: AP sidebar (left) + main content (right)
        self._h_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._h_splitter.setChildrenCollapsible(True)
        root.addWidget(self._h_splitter)

        # ── AP Group Sidebar ───────────────────────────────────────────────
        self._ap_sidebar = APGroupSidebar()
        self._h_splitter.addWidget(self._ap_sidebar)
        self._h_splitter.setCollapsible(0, True)

        # Vertical splitter: table on top, graphs on bottom
        splitter = QSplitter(Qt.Orientation.Vertical)
        self._h_splitter.addWidget(splitter)
        self._h_splitter.setCollapsible(1, False)
        self._h_splitter.setStretchFactor(0, 0)
        self._h_splitter.setStretchFactor(1, 1)
        # Give the sidebar a sensible initial width (180 px); the table gets the rest
        self._h_splitter.setSizes([180, 9999])
        self._sidebar_last_width = 180  # remembered width for collapse/expand

        # ── AP Table ───────────────────────────────────────────────────────
        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setIconSize(QSize(VENDOR_ICON_MAX_W, VENDOR_ICON_MAX_H))
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().hide()
        hdr = self._table.horizontalHeader()
        hdr.setMinimumSectionSize(36)
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        # Comfortable row height
        self._table.verticalHeader().setDefaultSectionSize(26)
        self._table.sortByColumn(COL_SIG, Qt.SortOrder.DescendingOrder)
        self._table.selectionModel().selectionChanged.connect(self._on_selection_change)
        # Right-click context menu
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.setMinimumHeight(200)
        # Initial column widths (all are user-draggable)
        _col_widths = {
            COL_INUSE: 10,
            COL_SSID: 180,
            COL_BSSID: 148,
            COL_MANUF: 180,
            COL_BAND: 72,
            COL_COUNTRY: 64,
            COL_CHAN: 44,
            COL_FREQ: 86,
            COL_BW: 96,
            COL_SPAN: 82,
            COL_SIG: 66,
            COL_DBM: 80,
            COL_RATE: 94,
            COL_SEC: 124,
            COL_MODE: 62,
            COL_GEN: 72,
            COL_UTIL: 72,
            COL_CLIENTS: 62,
            COL_KVR: 56,
            COL_APNAME: 160,
            COL_CISCO_PWR: 76,
        }
        for col, w in _col_widths.items():
            self._table.setColumnWidth(col, w)
        # AP Name column starts hidden; revealed dynamically in _on_data
        self._table.setColumnHidden(COL_APNAME, True)
        self._table.setColumnHidden(COL_CISCO_PWR, True)
        # Track columns the user has manually resized — skip auto-fit for those
        self._user_sized_cols: set = set()
        hdr.sectionResized.connect(self._on_col_resized)
        splitter.addWidget(self._table)

        # ── First-scan overlay ─────────────────────────────────────────────
        # Shown while the table is empty (initial scan not yet complete).
        # Hidden permanently once the first _on_data() fires.
        self._scan_overlay = QFrame(self._table)
        self._scan_overlay.setStyleSheet(
            f"QFrame {{ background-color: {SCAN_OVERLAY_BG}; border-radius: 0px; }}"
        )
        _ov_layout = QVBoxLayout(self._scan_overlay)
        _ov_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _ov_layout.setSpacing(14)
        _ov_icon = QLabel("📡")
        _ov_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _ov_icon.setStyleSheet("font-size:52px; background:transparent; border:none;")
        _ov_layout.addWidget(_ov_icon)
        self._scan_overlay_lbl = QLabel("Scanning for networks…")
        self._scan_overlay_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scan_overlay_lbl.setStyleSheet(
            f"color:{SCAN_OVERLAY_HEADING}; font-size:18px; font-weight:600;"
            "background:transparent; border:none;"
        )
        _ov_layout.addWidget(self._scan_overlay_lbl)
        _ov_sub = QLabel("First scan runs a full sweep — this may take a few seconds.")
        _ov_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _ov_sub.setStyleSheet(
            f"color:{SCAN_OVERLAY_SUB}; font-size:11px; background:transparent; border:none;"
        )
        _ov_layout.addWidget(_ov_sub)
        self._scan_overlay.setGeometry(self._table.rect())
        self._scan_overlay.raise_()
        self._table.installEventFilter(self)

        # ── Graph tabs ─────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setMinimumHeight(280)
        splitter.addWidget(self._tabs)

        self._channel_graph = ChannelGraphWidget()
        self._channel_graph.ap_highlighted.connect(self._on_graph_highlight)
        self._tabs.addTab(self._channel_graph, "📡  Channel Graph")

        self._history_graph = SignalHistoryWidget()
        self._tabs.addTab(self._history_graph, "📈  Signal History")

        # Details tab (selected AP)
        self._details_widget = QWidget()
        self._details_widget.setContentsMargins(0, 0, 0, 0)
        _det_outer = QVBoxLayout(self._details_widget)
        _det_outer.setContentsMargins(10, 10, 10, 10)
        _det_outer.setSpacing(10)
        # SSID header label
        self._det_ssid = QLabel("Select an access point to view details.")
        self._det_ssid.setTextFormat(Qt.TextFormat.RichText)
        self._det_ssid.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._det_ssid.setContentsMargins(14, 12, 14, 4)
        _det_outer.addWidget(self._det_ssid)
        # Separator line
        _det_sep = QFrame()
        _det_sep.setFrameShape(QFrame.Shape.HLine)
        _det_sep.setFrameShadow(QFrame.Shadow.Sunken)
        _det_outer.addWidget(_det_sep)
        # pre-create value labels for each row
        _DET_ROWS = [
            "bssid",
            "ap_name",
            "cisco_tx_power",
            "manufacturer",
            "wifi_gen",
            "mode_80211",
            "band",
            "channel",
            "frequency",
            "chan_width",
            "country",
            "beacon_interval",
            "dtim_period",
            "phy_caps",
            "he_features",
            "signal",
            "max_rate",
            "security",
            "wpa_flags",
            "rsn_flags",
            "rsn_caps",
            "vendor_ies",
            "akm_raw",
            "wps_manufacturer",
            "pmf",
            "chan_util",
            "clients",
            "roaming",
        ]
        _DET_LABELS = [
            "BSSID (AP MAC, 48-bit)",
            "AP Name",
            "Power Level",
            "Manufacturer",
            "WiFi Generation",
            "802.11 PHY / Amendment",
            "Band",
            "Channel",
            "Center Frequency",
            "Channel Width (MHz)",
            "Country Code (802.11d)",
            "Beacon Interval",
            "DTIM Period",
            "PHY Capability Summary",
            "HE/EHT Features",
            "Signal (RSSI)",
            "Max PHY Rate",
            "Security Profile",
            "WPA IE",
            "RSN IE",
            "RSN Capabilities",
            "Vendor IEs (OUIs)",
            "AKM Suites",
            "WPS Manufacturer (IE)",
            "PMF / 802.11w",
            "Channel Utilization (BSS Load)",
            "Station Count (BSS Load)",
            "Roaming Features (802.11k/v/r)",
        ]
        _DET_LABEL_BY_KEY = dict(zip(_DET_ROWS, _DET_LABELS))
        _DET_LEFT_KEYS = [
            "bssid",
            "ap_name",
            "cisco_tx_power",
            "manufacturer",
            "wifi_gen",
            "mode_80211",
            "band",
            "channel",
            "frequency",
            "chan_width",
            "country",
            "beacon_interval",
            "dtim_period",
            "phy_caps",
            "he_features",
            "signal",
        ]
        _DET_RIGHT_KEYS = [
            "max_rate",
            "security",
            "wpa_flags",
            "rsn_flags",
            "rsn_caps",
            "vendor_ies",
            "akm_raw",
            "wps_manufacturer",
            "pmf",
            "chan_util",
            "clients",
            "roaming",
        ]

        self._det_cards_wrap = QWidget()
        _det_cards = QHBoxLayout(self._det_cards_wrap)
        _det_cards.setContentsMargins(0, 0, 0, 0)
        _det_cards.setSpacing(12)

        self._det_card_left = QFrame()
        self._det_card_left.setObjectName("detailsCard")
        self._det_card_right = QFrame()
        self._det_card_right.setObjectName("detailsCard")

        _left_form = QFormLayout(self._det_card_left)
        _left_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        _left_form.setHorizontalSpacing(16)
        _left_form.setVerticalSpacing(9)
        _left_form.setContentsMargins(14, 12, 14, 12)

        _right_form = QFormLayout(self._det_card_right)
        _right_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        _right_form.setHorizontalSpacing(16)
        _right_form.setVerticalSpacing(9)
        _right_form.setContentsMargins(14, 12, 14, 12)

        _det_cards.addWidget(self._det_card_left, 1)
        _det_cards.addWidget(self._det_card_right, 1)
        _det_outer.addWidget(self._det_cards_wrap)
        _det_outer.addStretch()

        self._det_vals: dict[str, QLabel] = {}
        self._det_name_labels: dict[str, QLabel] = {}
        self._manufacturer_tip_widgets: list[QLabel] = []
        for key in _DET_ROWS:
            lbl_text = _DET_LABEL_BY_KEY[key]
            lbl = QLabel(f"<b>{lbl_text}</b>")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setProperty("detailRole", "name")
            val = QLabel("—")
            val.setTextFormat(Qt.TextFormat.RichText)
            val.setWordWrap(True)
            val.setProperty("detailRole", "value")
            val.setMargin(4)
            val.setMinimumHeight(24)
            if key == "manufacturer":
                val.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            else:
                val.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                    | Qt.TextInteractionFlag.TextSelectableByKeyboard
                )
            self._det_vals[key] = val
            self._det_name_labels[key] = lbl
            if key == "manufacturer":
                lbl.installEventFilter(self)
                val.installEventFilter(self)
                self._manufacturer_tip_widgets.extend((lbl, val))
            if key in _DET_LEFT_KEYS:
                _left_form.addRow(lbl, val)
            else:
                _right_form.addRow(lbl, val)

        _details_scroll = QScrollArea()
        _details_scroll.setWidgetResizable(True)
        _details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        _details_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        _details_scroll.setWidget(self._details_widget)
        self._details_tab_index = self._tabs.addTab(_details_scroll, "ℹ️  Details")

        # Connection tab (always current connected AP + connected-session telemetry)
        self._connection_widget = QWidget()
        self._connection_widget.setContentsMargins(0, 0, 0, 0)
        _conn_outer = QVBoxLayout(self._connection_widget)
        _conn_outer.setContentsMargins(10, 10, 10, 10)
        _conn_outer.setSpacing(10)

        self._conn_ssid = QLabel("Wifi not connected")
        self._conn_ssid.setTextFormat(Qt.TextFormat.RichText)
        self._conn_ssid.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._conn_ssid.setContentsMargins(14, 12, 14, 4)
        _conn_outer.addWidget(self._conn_ssid)

        _conn_sep = QFrame()
        _conn_sep.setFrameShape(QFrame.Shape.HLine)
        _conn_sep.setFrameShadow(QFrame.Shadow.Sunken)
        _conn_outer.addWidget(_conn_sep)

        self._conn_cards_wrap = QWidget()
        _conn_cards = QHBoxLayout(self._conn_cards_wrap)
        _conn_cards.setContentsMargins(0, 0, 0, 0)
        _conn_cards.setSpacing(12)

        self._conn_card_left = QFrame()
        self._conn_card_left.setObjectName("detailsCard")
        self._conn_card_right = QFrame()
        self._conn_card_right.setObjectName("detailsCard")

        _conn_left_form = QFormLayout(self._conn_card_left)
        _conn_left_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        _conn_left_form.setHorizontalSpacing(16)
        _conn_left_form.setVerticalSpacing(9)
        _conn_left_form.setContentsMargins(14, 12, 14, 12)

        _conn_right_form = QFormLayout(self._conn_card_right)
        _conn_right_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        _conn_right_form.setHorizontalSpacing(16)
        _conn_right_form.setVerticalSpacing(9)
        _conn_right_form.setContentsMargins(14, 12, 14, 12)

        _CONN_ROWS = [
            "status",
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
        ]
        _CONN_LABELS = [
            "Connection State",
            "SSID",
            "BSSID",
            "Manufacturer",
            "Band",
            "Channel",
            "Security Profile",
            "AKM",
            "PMF",
            "Beacon Interval",
            "DTIM Period",
            "RSN Capabilities",
            "Vendor IEs (OUIs)",
            "Signal (Connected AP)",
            "Interface",
            "RX PHY",
            "TX PHY",
            "Link Frequency",
            "RX Bitrate",
            "TX Bitrate",
            "Expected Throughput",
            "RX Packets",
            "TX Packets",
            "RX Bytes",
            "TX Bytes",
            "RX Drop/Misc",
            "Signal Avg",
            "TX Retries",
            "TX Retry Rate",
            "TX Failed",
            "TX Fail Rate",
            "Channel Busy",
            "Noise Floor",
            "Inactive Time",
            "Connected Time",
        ]
        _CONN_LEFT_KEYS = [
            "status",
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
        ]

        self._conn_vals: dict[str, QLabel] = {}
        for key, lbl_text in zip(_CONN_ROWS, _CONN_LABELS):
            lbl = QLabel(f"<b>{lbl_text}</b>")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setProperty("detailRole", "name")
            val = QLabel("—")
            val.setTextFormat(Qt.TextFormat.RichText)
            val.setWordWrap(True)
            val.setProperty("detailRole", "value")
            val.setMargin(4)
            val.setMinimumHeight(24)
            val.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            self._conn_vals[key] = val
            if key in _CONN_LEFT_KEYS:
                _conn_left_form.addRow(lbl, val)
            else:
                _conn_right_form.addRow(lbl, val)

        _conn_cards.addWidget(self._conn_card_left, 1)
        _conn_cards.addWidget(self._conn_card_right, 1)
        _conn_outer.addWidget(self._conn_cards_wrap)
        _conn_outer.addStretch()

        _connection_scroll = QScrollArea()
        _connection_scroll.setWidgetResizable(True)
        _connection_scroll.setFrameShape(QFrame.Shape.NoFrame)
        _connection_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        _connection_scroll.setWidget(self._connection_widget)
        self._connection_tab_index = self._tabs.addTab(
            _connection_scroll, "🔗  Connection"
        )

        splitter.setSizes([380, 350])

        # ── Status bar ─────────────────────────────────────────────────────
        # Left: transient messages via showMessage()
        # Right (permanent): Channel Allocations button, last scan time, theme
        sb = self.statusBar()

        # Channel allocations button in the status bar
        self._btn_allocations = QPushButton("🗺\ufe0f  Channel Allocations")
        self._btn_allocations.setToolTip(
            "Open 5 GHz & 6 GHz channel-allocation reference charts"
        )
        self._btn_allocations.setStyleSheet(
            f"QPushButton {{ color:{BTN_ACCENT}; border:1px solid {BTN_BORDER};"
            " border-radius:3px; padding:1px 6px; font-size:9pt; }"
            f"QPushButton:hover {{ background:{BTN_HOVER_BG}; }}"
        )
        self._btn_allocations.clicked.connect(self._on_open_allocations)
        sb.addPermanentWidget(self._btn_allocations)

        sb.addPermanentWidget(QLabel("   "))

        _sep2 = QFrame()
        _sep2.setFrameShape(QFrame.Shape.VLine)
        _sep2.setFrameShadow(QFrame.Shadow.Sunken)
        sb.addPermanentWidget(_sep2)

        self._lbl_updated = QLabel("  Last scan: —  ")
        sb.addPermanentWidget(self._lbl_updated)

        _sep3 = QFrame()
        _sep3.setFrameShape(QFrame.Shape.VLine)
        _sep3.setFrameShadow(QFrame.Shadow.Sunken)
        sb.addPermanentWidget(_sep3)

        sb.addPermanentWidget(QLabel("  Theme: "))
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["🌙 Dark", "☀ Light", "🖥 Auto"])
        self._theme_combo.setMinimumWidth(90)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_change)
        sb.addPermanentWidget(self._theme_combo)
        sb.addPermanentWidget(QLabel("  "))

        sb.showMessage("Starting scanner…")

        # ── AP Sidebar signal connections ─────────────────────────────────
        self._ap_sidebar.group_include_requested.connect(self._on_sidebar_include)
        self._ap_sidebar.group_exclude_requested.connect(self._on_sidebar_exclude)
        self._ap_sidebar.group_unexclude_requested.connect(self._on_sidebar_unexclude)
        # Track sidebar width so collapse/expand remembers the last size
        self._h_splitter.splitterMoved.connect(self._on_hsplitter_moved)
