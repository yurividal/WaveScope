"""Core base definitions.

Contains imports, constants, channel math, color helpers,
and low-level utility functions used across the application.
"""

"""Core domain and data layer.

Contains constants, channel math, vendor/OUI resolution, AP model,
scan parsers/enrichment, scanner worker thread, and table/proxy models.
"""

import sys
import os
import re
import math
import time
import json
import stat
import tempfile
import urllib.request
import subprocess
from pathlib import Path
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple

import numpy as np

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QSplitter,
    QTableView,
    QHeaderView,
    QAbstractItemView,
    QToolBar,
    QLabel,
    QComboBox,
    QPushButton,
    QStatusBar,
    QFrame,
    QSizePolicy,
    QLineEdit,
    QTabWidget,
    QCheckBox,
    QButtonGroup,
    QToolButton,
    QMenu,
    QScrollArea,
    QDialog,
    QDialogButtonBox,
    QProgressBar,
    QMessageBox,
    QToolTip,
    QTextEdit,
    QFileDialog,
    QPlainTextEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
)
from PyQt6.QtCore import (
    Qt,
    QEvent,
    QTimer,
    QThread,
    QItemSelectionModel,
    QProcess,
    pyqtSignal,
    QSortFilterProxyModel,
    QAbstractTableModel,
    QModelIndex,
    QVariant,
    QPointF,
    QRect,
    QRectF,
    QSize,
    QPersistentModelIndex,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QBrush,
    QPalette,
    QIcon,
    QImage,
    QPixmap,
    QPainter,
    QPen,
    QLinearGradient,
    QFontMetrics,
    QAction,
    QCursor,
)

import pyqtgraph as pg
from pyqtgraph import PlotWidget, mkPen, mkBrush
from .theme import (
    SSID_COLORS,
    IW_GEN_COLORS,
    UNII_NAME_COLORS,
    UNII_CHAN_COLORS,
    UNII6_CHAN_COLORS,
    BAND_SUBBAND_HEADERS,
    SIG_EXCELLENT,
    SIG_GOOD,
    SIG_FAIR,
    SIG_WEAK,
    SIG_POOR,
    SIG_FAIR_NM,
    SIG_WEAK_NM,
    SIG_POOR_NM,
    GRAPH_BG_DARK,
    GRAPH_BG_LIGHT,
    GRAPH_AXIS_DARK,
    GRAPH_AXIS_LIGHT,
    GRAPH_FG_DARK,
    GRAPH_FG_LIGHT,
    FALLBACK_GRAY,
    DFS_AXIS_COLOR,
    DFS_FILL_COLOR,
    ALLOC_GRID_DARK,
    ALLOC_GRID_LIGHT,
    ALLOC_CELL_BG_DARK,
    ALLOC_CELL_BG_LIGHT,
    ALLOC_LBL_BG_DARK,
    ALLOC_LBL_BG_LIGHT,
    ALLOC_TEXT_DARK,
    ALLOC_TEXT_LIGHT,
    ALLOC_DIM_DARK,
    ALLOC_DIM_LIGHT,
    ALLOC_WHITE,
    ALLOC_BLACK,
    ALLOC_ONBAND_DARK,
    DIALOG_BG_DARK,
    DIALOG_BG_LIGHT,
    DIALOG_BORDER_DARK,
    DIALOG_BORDER_LIGHT,
    DIALOG_TEXT_DARK,
    DIALOG_TEXT_LIGHT,
    DIALOG_NOTE_DARK,
    DIALOG_NOTE_LIGHT,
    CARD_BG_DARK,
    CARD_VALUE_BG_DARK,
    CARD_VALUE_BORDER_DARK,
    CARD_VALUE_BG_LIGHT,
    CARD_VALUE_BORDER_LIGHT,
    BTN_ACCENT,
    BTN_BORDER,
    BTN_HOVER_BG,
    BTN_CHECKED_TEXT,
    BTN_CHECKED_BORDER,
    BTN_CHECKED_BG,
    SCAN_OVERLAY_BG,
    SCAN_OVERLAY_HEADING,
    SCAN_OVERLAY_SUB,
    TABLE_LINGER_FG,
    SEC_BAD,
    SEC_WPA2,
    SEC_WPA3,
    SEC_OTHER,
    PMF_OPTIONAL,
    VENDOR_MUTED,
    VENDOR_SUCCESS,
    VENDOR_ERROR,
    MENU_BG,
    MENU_BORDER,
    MENU_TEXT,
    MENU_SELECTED,
    CONNECTED_GREEN,
    HTML_MUTED,
    CAPTURE_TITLE_FG,
    CAPTURE_CARD_MON_BG,
    CAPTURE_CARD_MON_HOVER,
    CAPTURE_CARD_MGD_BG,
    CAPTURE_CARD_MGD_HOVER,
    CAPTURE_CARD_BORDER,
    CAPTURE_CARD_TITLE_FG,
    CAPTURE_CARD_SUB_FG,
    CAPTURE_CARD_BODY_FG,
    CAPTURE_WARN_BG,
    CAPTURE_WARN_FG,
    CAPTURE_WARN_BORDER,
    CAPTURE_BTN_START_BG,
    CAPTURE_BTN_START_FG,
    CAPTURE_BTN_START_HOVER,
    CAPTURE_BTN_DIS_BG,
    CAPTURE_BTN_DIS_FG,
    CAPTURE_LOG_BG,
    CAPTURE_LOG_FG,
    CAPTURE_BTN_STOP_BG,
    CAPTURE_BTN_STOP_FG,
    CAPTURE_BTN_STOP_HOVER,
    CAPTURE_BANNER_BG,
    CAPTURE_BANNER_FG,
    CAPTURE_MGD_STATE_FG,
    CAPTURE_MGD_LOG_BG,
    CAPTURE_MGD_LOG_FG,
    PLAN_2G_ISM_HEADER,
    PLAN_2G_JP_HEADER,
    PLAN_CH1,
    PLAN_CH6,
    PLAN_CH11,
    PLAN_EU_CH5,
    PLAN_EU_CH13,
    PLAN_JP_CH5,
    PLAN_JP_CH10,
    ALLOC_5G_U1,
    ALLOC_5G_U2A,
    ALLOC_5G_U2C,
    ALLOC_5G_U3,
    ALLOC_5G_36_48,
    ALLOC_5G_52_116,
    ALLOC_5G_120_128,
    ALLOC_5G_132_144,
    ALLOC_5G_149_165,
    ALLOC_5G_DFS_BAND,
    ALLOC_6G_U5,
    ALLOC_6G_U6,
    ALLOC_6G_U7,
    ALLOC_6G_U8,
    _dark_palette,
    _light_palette,
)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

VERSION = "1.8.1"
APP_NAME = "WaveScope"

HISTORY_SECONDS = 120  # seconds of signal history to keep
REFRESH_INTERVALS = [1, 2, 5, 10]  # seconds

# 2.4 GHz channel → center frequency (MHz)
CH24 = {
    1: 2412,
    2: 2417,
    3: 2422,
    4: 2427,
    5: 2432,
    6: 2437,
    7: 2442,
    8: 2447,
    9: 2452,
    10: 2457,
    11: 2462,
    12: 2467,
    13: 2472,
    14: 2484,
}
# 5 GHz channels → center frequency
CH5 = {
    36: 5180,
    40: 5200,
    44: 5220,
    48: 5240,
    52: 5260,
    56: 5280,
    60: 5300,
    64: 5320,
    100: 5500,
    104: 5520,
    108: 5540,
    112: 5560,
    116: 5580,
    120: 5600,
    124: 5620,
    128: 5640,
    132: 5660,
    136: 5680,
    140: 5700,
    144: 5720,
    149: 5745,
    153: 5765,
    157: 5785,
    161: 5805,
    165: 5825,
    169: 5845,
    173: 5865,
    177: 5885,
}
# 6 GHz channels → center frequency (Wi-Fi 6E / IEEE 802.11ax)
# Primary 20 MHz channels: 1, 5, 9, …, 233  — formula: center_MHz = 5950 + (channel × 5)
# Band covers 5925–7125 MHz (UNII-5/6/7/8).  59 primary channels total.
CH6 = {ch: 5950 + ch * 5 for ch in range(1, 234, 4)}  # ch 1..233, step 4

ALL_CHANNELS = {**CH24, **CH5, **CH6}


def chan_to_freq(chan: int) -> int:
    """Return best-guess center frequency for a channel number."""
    return ALL_CHANNELS.get(chan, 0)


def freq_to_band(freq_mhz: int) -> str:
    if 2400 <= freq_mhz < 2500:
        return "2.4 GHz"
    if 5000 <= freq_mhz < 5900:
        return "5 GHz"
    if 5925 <= freq_mhz <= 7125:
        return "6 GHz"
    return "?"


# ─────────────────────────────────────────────────────────────────────────────
# 5 GHz bonded-channel group tables
#
# IEEE 802.11 defines fixed OFDM channel blocks for each bandwidth.
# When an AP reports its *primary* 20 MHz channel at a wider BW, the actual
# spectrum it occupies is the entire bonded block, not just ±BW/2 around the
# primary channel center.
#
# Example: primary ch 116 @ 80 MHz → block is ch 116-128 → center at ch 122
#          primary ch 100 @ 160 MHz → block is ch 100-128 → center at ch 114
# ─────────────────────────────────────────────────────────────────────────────

# Each entry: ([primary channels in block], center_freq_MHz)
_5GHZ_GROUPS_40: List[Tuple[List[int], int]] = [
    ([36, 40], 5190),
    ([44, 48], 5230),
    ([52, 56], 5270),
    ([60, 64], 5310),
    ([100, 104], 5510),
    ([108, 112], 5550),
    ([116, 120], 5590),
    ([124, 128], 5630),
    ([132, 136], 5670),
    ([140, 144], 5710),
    ([149, 153], 5755),
    ([157, 161], 5795),
    ([165, 169], 5835),
    ([173, 177], 5875),
]

_5GHZ_GROUPS_80: List[Tuple[List[int], int]] = [
    ([36, 40, 44, 48], 5210),
    ([52, 56, 60, 64], 5290),
    ([100, 104, 108, 112], 5530),
    ([116, 120, 124, 128], 5610),
    ([132, 136, 140, 144], 5690),
    ([149, 153, 157, 161], 5775),
    ([165, 169, 173, 177], 5855),
]

_5GHZ_GROUPS_160: List[Tuple[List[int], int]] = [
    ([36, 40, 44, 48, 52, 56, 60, 64], 5250),
    ([100, 104, 108, 112, 116, 120, 124, 128], 5570),
    ([149, 153, 157, 161, 165, 169, 173, 177], 5815),
]

# Fast lookup: (primary_chan, bw_mhz) → (center_freq_MHz, sorted_channels_list)
_5GHZ_BONDED: Dict[Tuple[int, int], Tuple[int, List[int]]] = {}
for _bw, _grps in [
    (40, _5GHZ_GROUPS_40),
    (80, _5GHZ_GROUPS_80),
    (160, _5GHZ_GROUPS_160),
]:
    for _chans, _cf in _grps:
        for _c in _chans:
            _5GHZ_BONDED[(_c, _bw)] = (_cf, _chans)


def get_5ghz_bonded_info(primary_chan: int, bw_mhz: int) -> Tuple[int, List[int]]:
    """
    Return (center_freq_MHz, [all_channels_in_block]) for a 5 GHz primary channel
    at the given bandwidth.  Falls back to primary channel's own freq if the
    combination is not in the standard block table.
    """
    key = (primary_chan, bw_mhz)
    if key in _5GHZ_BONDED:
        return _5GHZ_BONDED[key]
    # Fallback: primary channel is both center and only member
    return CH5.get(primary_chan, chan_to_freq(primary_chan)), [primary_chan]


# ─────────────────────────────────────────────────────────────────────────────
# 6 GHz bonded-channel group tables (derived from FCC/US standard-power plan)
#
# 20 MHz primaries: ch 1,5,9,…,233  (center_MHz = 5950 + ch*5)
# 40 MHz centers:   ch 3,11,…,179   (pairs)
# 80 MHz centers:   ch 7,23,…,167   (groups of 4)
# 160 MHz centers:  ch 15,47,79,111,143 (groups of 8)
# ─────────────────────────────────────────────────────────────────────────────


def _make_6ghz_group(center_chan: int, bw_mhz: int) -> Tuple[List[int], int]:
    n_20mhz = bw_mhz // 20
    start = center_chan - 2 * (n_20mhz - 1)
    chans = [start + 4 * i for i in range(n_20mhz)]
    center_freq = 5950 + center_chan * 5
    return chans, center_freq


_6GHZ_GROUPS_40: List[Tuple[List[int], int]] = [
    _make_6ghz_group(c, 40) for c in range(3, 180, 8)
]
_6GHZ_GROUPS_80: List[Tuple[List[int], int]] = [
    _make_6ghz_group(c, 80) for c in range(7, 168, 16)
]
_6GHZ_GROUPS_160: List[Tuple[List[int], int]] = [
    _make_6ghz_group(c, 160) for c in range(15, 144, 32)
]

# Fast lookup: (primary_chan, bw_mhz) → (center_freq_MHz, sorted_channels_list)
_6GHZ_BONDED: Dict[Tuple[int, int], Tuple[int, List[int]]] = {}
for _bw, _grps in [
    (40, _6GHZ_GROUPS_40),
    (80, _6GHZ_GROUPS_80),
    (160, _6GHZ_GROUPS_160),
]:
    for _chans, _cf in _grps:
        for _c in _chans:
            _6GHZ_BONDED[(_c, _bw)] = (_cf, _chans)


def get_6ghz_bonded_info(primary_chan: int, bw_mhz: int) -> Tuple[int, List[int]]:
    """
    Return (center_freq_MHz, [all_channels_in_block]) for a 6 GHz primary channel
    at the given bandwidth, based on the standard 6 GHz bonded block tables.
    Falls back to primary channel's own freq if not in table.
    """
    key = (primary_chan, bw_mhz)
    if key in _6GHZ_BONDED:
        return _6GHZ_BONDED[key]
    return CH6.get(primary_chan, chan_to_freq(primary_chan)), [primary_chan]


def _block_channel_range(
    center_freq: int, bw_mhz: int, chan_dict: Dict[int, int]
) -> Tuple[Optional[int], Optional[int]]:
    """
    Return (lo_chan, hi_chan) — the outermost primary channels that fall inside
    a bonded block of `bw_mhz` MHz centered at `center_freq` MHz.

    Each 20 MHz primary channel has its center `bw/2 - 10` MHz from the block
    edge, so the outermost centers are at center_freq ± (bw/2 - 10).
    Works for all bands: 2.4 GHz (40 MHz), 5 GHz, 6 GHz (up to 320 MHz).
    """
    half = bw_mhz // 2 - 10
    lo = center_freq - half
    hi = center_freq + half
    in_range = [c for c, f in chan_dict.items() if lo <= f <= hi]
    if not in_range:
        return None, None
    return min(in_range), max(in_range)


def get_ap_draw_center(ap: "AccessPoint") -> float:
    """
    MHz center to use when placing the spectrum shape for `ap`.
    5/6 GHz: uses bonded block lookup tables.
    2.4 GHz: uses iw_center_freq when available, else primary channel freq.
    """
    if ap.bandwidth_mhz > 20:
        # 5 GHz: IEEE block lookup table
        if ap.band == "5 GHz" and ap.channel:
            center, _ = get_5ghz_bonded_info(ap.channel, ap.bandwidth_mhz)
            if center:
                return float(center)
        # 6 GHz: FCC/US 6 GHz bonded block lookup table
        if ap.band == "6 GHz" and ap.channel:
            center, chans = get_6ghz_bonded_info(ap.channel, ap.bandwidth_mhz)
            if center and len(chans) > 1:
                return float(center)
        # 2.4 GHz (or unknown): use iw-reported bonded block center when available
        if ap.iw_center_freq:
            return float(ap.iw_center_freq)
    return float(ap.freq_mhz)


def get_ap_channel_span(ap: "AccessPoint") -> str:
    """
    Human-readable channel-span string for the table.
    5 GHz:   "116–128" (80 MHz), "100–128" (160 MHz), "36" (20 MHz).
    2.4 GHz: "6–10" (40 MHz HT40+), "2–6" (40 MHz HT40-).
    6 GHz:   "1–13" (80 MHz), "1–29" (160 MHz), "1–61" (320 MHz).
    """
    if ap.band == "5 GHz" and ap.channel:
        # Prefer iw center + formula; fall back to IEEE lookup table
        if ap.iw_center_freq and ap.bandwidth_mhz > 20:
            lo, hi = _block_channel_range(ap.iw_center_freq, ap.bandwidth_mhz, CH5)
            if lo is not None and lo != hi:
                return f"{lo}–{hi}"
        _, chans = get_5ghz_bonded_info(ap.channel, ap.bandwidth_mhz)
        if len(chans) > 1:
            return f"{chans[0]}–{chans[-1]}"
        return str(ap.channel)

    if ap.band == "2.4 GHz" and ap.channel:
        if ap.iw_center_freq and ap.bandwidth_mhz == 40:
            lo, hi = _block_channel_range(ap.iw_center_freq, 40, CH24)
            if lo is not None and lo != hi:
                return f"{lo}–{hi}"
        return str(ap.channel)

    if ap.band == "6 GHz" and ap.channel:
        if ap.bandwidth_mhz > 20:
            _cf, chans = get_6ghz_bonded_info(ap.channel, ap.bandwidth_mhz)
            if len(chans) > 1:
                return f"{chans[0]}–{chans[-1]}"
            if ap.iw_center_freq:
                lo, hi = _block_channel_range(ap.iw_center_freq, ap.bandwidth_mhz, CH6)
                if lo is not None and lo != hi:
                    return f"{lo}–{hi}"
        return str(ap.channel)

    return str(ap.channel) if ap.channel else "?"


def signal_color(signal: int) -> QColor:
    """Map 0-100 signal to red→yellow→green."""
    if signal >= 70:
        return QColor(SIG_EXCELLENT)
    if signal >= 50:
        return QColor(SIG_FAIR_NM)
    if signal >= 30:
        return QColor(SIG_WEAK_NM)
    return QColor(SIG_POOR_NM)


def signal_to_dbm(signal: int) -> int:
    """Approximate dBm from nmcli 0-100 SIGNAL."""
    return int((signal / 2) - 100)
