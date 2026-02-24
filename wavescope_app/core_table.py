"""Table-model subsystem.

Contains table headers/columns plus Qt table and filter proxy models.
"""

from .core_scanner import *
from .theme import IW_GEN_COLORS


class APTableModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._aps: List[AccessPoint] = []
        self._ssid_colors: Dict[str, QColor] = {}
        self._color_idx = 0

    def _color_for_ssid(self, ssid: str) -> QColor:
        key = ssid if ssid else "__hidden__"
        if key not in self._ssid_colors:
            c = SSID_COLORS[self._color_idx % len(SSID_COLORS)]
            self._ssid_colors[key] = QColor(c)
            self._color_idx += 1
        return self._ssid_colors[key]

    def update(self, aps: List[AccessPoint]):
        self.beginResetModel()
        self._aps = sorted(aps, key=lambda a: -a.signal)
        # Eagerly assign colors so ssid_colors() is always fully populated
        # before the graph widgets request them.
        for ap in self._aps:
            self._color_for_ssid(ap.ssid)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._aps)

    def columnCount(self, parent=QModelIndex()):
        return len(TABLE_HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
        ):
            return TABLE_HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        ap = self._aps[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(ap, col)

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_SEC:
                return ap.security_tooltip
            return None

        if role == Qt.ItemDataRole.DecorationRole:
            if col == COL_MANUF:
                icon = get_vendor_icon(ap.manufacturer)
                return icon if icon is not None else get_vendor_placeholder_icon()
            return None

        if role == Qt.ItemDataRole.ForegroundRole:
            # Dim the entire row while an AP is in its linger grace period
            if ap.is_lingering:
                return QBrush(QColor("#4a5a72"))
            if col == COL_SSID:
                # Color the SSID text with its network colour (replaces tinted rows)
                c = QColor(self._color_for_ssid(ap.ssid))
                c.setAlpha(230)
                return QBrush(c)
            if col == COL_SIG:
                return QBrush(signal_color(ap.signal))
            if col == COL_DBM:
                return QBrush(signal_color(ap.signal))
            if col == COL_INUSE:
                return QBrush(QColor("#4caf50")) if ap.in_use else None
            if col == COL_GEN:
                c = IW_GEN_COLORS.get(ap.wifi_gen)
                return QBrush(QColor(c)) if c else None
            if col == COL_UTIL:
                pct = ap.chan_util_pct
                if pct is not None:
                    if pct >= 75:
                        return QBrush(QColor("#f44336"))
                    if pct >= 50:
                        return QBrush(QColor("#ff9800"))
                    if pct >= 25:
                        return QBrush(QColor("#ffc107"))
                    return QBrush(QColor("#4caf50"))
            if col == COL_SEC:
                sec = ap.security_short
                if sec == "Open" or sec == "":
                    return QBrush(QColor("#f44336"))
                if "WPA3" in sec or "WPA2+WPA3" in sec:
                    return QBrush(QColor("#4caf50"))
            return None

        if role == Qt.ItemDataRole.BackgroundRole:
            # Alternate very subtle row shading for readability
            if index.row() % 2 == 1:
                return (
                    QApplication.instance()
                    .palette()
                    .brush(QPalette.ColorRole.AlternateBase)
                )
            return None

        if role == Qt.ItemDataRole.TextAlignmentRole:
            numeric_cols = {
                COL_CHAN,
                COL_FREQ,
                COL_BW,
                COL_SPAN,
                COL_SIG,
                COL_DBM,
                COL_RATE,
                COL_UTIL,
                COL_CLIENTS,
            }
            if col in numeric_cols or col == COL_KVR or col == COL_COUNTRY:
                return Qt.AlignmentFlag.AlignCenter
            return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft

        if role == Qt.ItemDataRole.FontRole:
            if ap.in_use:
                f = QFont()
                f.setBold(True)
                return f
            if col == COL_SSID:
                f = QFont()
                f.setWeight(QFont.Weight.Medium)
                return f

        if role == Qt.ItemDataRole.UserRole:
            return ap

        return None

    def _display(self, ap: AccessPoint, col: int) -> str:
        if col == COL_INUSE:
            return "▲" if ap.in_use else ""
        if col == COL_SSID:
            return ap.display_ssid
        if col == COL_BSSID:
            return ap.bssid
        if col == COL_MANUF:
            return format_manufacturer_display(ap.manufacturer)
        if col == COL_BAND:
            return ap.band
        if col == COL_COUNTRY:
            return ap.country or ""
        if col == COL_CHAN:
            return str(ap.channel) if ap.channel else "?"
        if col == COL_FREQ:
            return str(ap.freq_mhz)
        if col == COL_BW:
            return str(ap.bandwidth_mhz)
        if col == COL_SPAN:
            return get_ap_channel_span(ap)
        if col == COL_SIG:
            return f"{ap.signal}%"
        if col == COL_DBM:
            return f"{ap.dbm} dBm"
        if col == COL_RATE:
            return str(int(ap.rate_mbps))
        if col == COL_SEC:
            return ap.security_short
        if col == COL_MODE:
            return ap.phy_mode
        if col == COL_GEN:
            if ap.wifi_gen:
                return ap.wifi_gen
            return "Legacy" if ap.phy_mode in ("A", "B/G") else ""
        if col == COL_UTIL:
            pct = ap.chan_util_pct
            return f"{pct}%" if pct is not None else ""
        if col == COL_CLIENTS:
            return str(ap.station_count) if ap.station_count is not None else ""
        if col == COL_KVR:
            return ap.kvr_flags
        return ""

    def ap_at(self, row: int) -> Optional[AccessPoint]:
        if 0 <= row < len(self._aps):
            return self._aps[row]
        return None

    def ssid_colors(self) -> Dict[str, QColor]:
        return self._ssid_colors


class APFilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self._band_filter = "All"
        self._text_filter = ""
        # Column-level filters: col → set of display-string values
        self._includes: Dict[int, set] = {}  # row must match one value per col
        self._excludes: Dict[int, set] = {}  # row must not match any value per col
        self.setSortRole(Qt.ItemDataRole.UserRole + 1)

    # ── Band / text ─────────────────────────────────────────────────────
    def set_band(self, band: str):
        self._band_filter = band
        self.invalidateFilter()

    def set_text(self, txt: str):
        self._text_filter = txt.lower()
        self.invalidateFilter()

    # ── Column include / exclude ─────────────────────────────────────────
    def add_include(self, col: int, value: str):
        self._includes.setdefault(col, set()).add(value)
        self.invalidateFilter()

    def add_exclude(self, col: int, value: str):
        self._excludes.setdefault(col, set()).add(value)
        self.invalidateFilter()

    def remove_include(self, col: int, value: str):
        if col in self._includes:
            self._includes[col].discard(value)
            if not self._includes[col]:
                del self._includes[col]
        self.invalidateFilter()

    def remove_exclude(self, col: int, value: str):
        if col in self._excludes:
            self._excludes[col].discard(value)
            if not self._excludes[col]:
                del self._excludes[col]
        self.invalidateFilter()

    def clear_col_filters(self):
        self._includes.clear()
        self._excludes.clear()
        self.invalidateFilter()

    def has_col_filters(self) -> bool:
        return bool(self._includes or self._excludes)

    _COL_NAMES = {
        COL_SSID: "SSID",
        COL_BSSID: "MAC",
        COL_MANUF: "Vendor",
        COL_BAND: "Band",
        COL_COUNTRY: "Country",
        COL_CHAN: "Ch",
        COL_SEC: "Security",
        COL_GEN: "Gen",
        COL_KVR: "Roaming",
    }

    def active_filter_text(self) -> str:
        parts = []
        for col, vals in self._includes.items():
            n = self._COL_NAMES.get(col, str(col))
            parts.append(f"+ {n}: {', '.join(sorted(vals))}")
        for col, vals in self._excludes.items():
            n = self._COL_NAMES.get(col, str(col))
            parts.append(f"− {n}: {', '.join(sorted(vals))}")
        return "  ·  ".join(parts)

    # ── Filter logic ─────────────────────────────────────────────────────
    def filterAcceptsRow(self, src_row, src_parent):
        src = self.sourceModel()
        ap: AccessPoint = src.ap_at(src_row)
        if ap is None:
            return False
        if self._band_filter != "All" and ap.band != self._band_filter:
            return False
        if self._text_filter:
            haystack = (
                f"{ap.display_ssid} {ap.bssid} {ap.manufacturer} {ap.band}".lower()
            )
            if self._text_filter not in haystack:
                return False
        # Column includes: each constrained column must match one of its values
        for col, vals in self._includes.items():
            cell = src.data(src.index(src_row, col), Qt.ItemDataRole.DisplayRole) or ""
            if cell not in vals:
                return False
        # Column excludes: must not match any excluded value
        for col, vals in self._excludes.items():
            cell = src.data(src.index(src_row, col), Qt.ItemDataRole.DisplayRole) or ""
            if cell in vals:
                return False
        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        col = left.column()
        numeric = {
            COL_CHAN,
            COL_FREQ,
            COL_BW,
            COL_SIG,
            COL_DBM,
            COL_RATE,
            COL_UTIL,
            COL_CLIENTS,
        }
        lv = self.sourceModel().data(left, Qt.ItemDataRole.DisplayRole)
        rv = self.sourceModel().data(right, Qt.ItemDataRole.DisplayRole)
        if col in numeric:
            try:
                return float(re.sub(r"[^\d.\-]", "", lv or "0")) < float(
                    re.sub(r"[^\d.\-]", "", rv or "0")
                )
            except Exception:
                pass
        return str(lv or "") < str(rv or "")


# ─────────────────────────────────────────────────────────────────────────────
# Channel Graph — flat-top occupancy view (like WiFi Analyzer for Windows)
# ─────────────────────────────────────────────────────────────────────────────

# dBm display constants for the channel graph
CHAN_DBM_FLOOR = -100  # baseline (bottom of every shape)
CHAN_DBM_CEIL = -20  # top of y-axis (you never see > -20 in practice)
