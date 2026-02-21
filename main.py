#!/usr/bin/env python3
"""
nmcli-gui — Modern WiFi Analyzer for Linux
Requires: PyQt6, pyqtgraph, numpy
Data source: nmcli (NetworkManager CLI)
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
)
from PyQt6.QtCore import (
    Qt,
    QTimer,
    QThread,
    pyqtSignal,
    QSortFilterProxyModel,
    QAbstractTableModel,
    QModelIndex,
    QVariant,
    QPointF,
    QRectF,
    QPersistentModelIndex,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QBrush,
    QPalette,
    QIcon,
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


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

VERSION = "1.2.0"
APP_NAME = "WaveScope"

HISTORY_SECONDS = 120  # seconds of signal history to keep
REFRESH_INTERVALS = [1, 2, 5, 10]  # seconds

# Color palette for SSIDs (hex strings) — vivid, well-separated hues
SSID_COLORS = [
    "#4FC3F7",
    "#81C784",
    "#FFB74D",
    "#E57373",
    "#CE93D8",
    "#4DB6AC",
    "#F06292",
    "#AED581",
    "#FFD54F",
    "#4DD0E1",
    "#FF8A65",
    "#A5D6A7",
    "#90CAF9",
    "#FFCC80",
    "#EF9A9A",
    "#80CBC4",
    "#9FA8DA",
    "#F48FB1",
    "#B0BEC5",
    "#FFF176",
]

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
    32: 5160,
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


def signal_color(signal: int) -> QColor:
    """Map 0-100 signal to red→yellow→green."""
    if signal >= 70:
        return QColor("#4caf50")  # green
    if signal >= 50:
        return QColor("#ffb300")  # amber
    if signal >= 30:
        return QColor("#ff7043")  # orange
    return QColor("#ef5350")  # red


def signal_to_dbm(signal: int) -> int:
    """Approximate dBm from nmcli 0-100 SIGNAL."""
    return int((signal / 2) - 100)


# ─────────────────────────────────────────────────────────────────────────────
# OUI / Manufacturer Lookup
# ─────────────────────────────────────────────────────────────────────────────

_EMBEDDED_OUI: Dict[str, str] = {
    # Apple
    "00:03:93": "Apple",
    "00:0A:95": "Apple",
    "00:0D:93": "Apple",
    "00:11:24": "Apple",
    "00:14:51": "Apple",
    "00:16:CB": "Apple",
    "00:17:F2": "Apple",
    "00:1B:63": "Apple",
    "00:1C:B3": "Apple",
    "00:1E:52": "Apple",
    "00:1F:5B": "Apple",
    "00:1F:F3": "Apple",
    "00:21:E9": "Apple",
    "00:23:12": "Apple",
    "00:23:6C": "Apple",
    "00:25:00": "Apple",
    "00:25:BC": "Apple",
    "00:26:B0": "Apple",
    "00:26:BB": "Apple",
    "04:52:F3": "Apple",
    "04:4B:ED": "Apple",
    "08:74:02": "Apple",
    "10:40:F3": "Apple",
    "18:81:0E": "Apple",
    "20:A2:E4": "Apple",
    "28:E0:2C": "Apple",
    "3C:22:FB": "Apple",
    "40:6C:8F": "Apple",
    "40:D3:2D": "Apple",
    "44:00:10": "Apple",
    "48:43:7C": "Apple",
    "54:26:96": "Apple",
    "60:69:44": "Apple",
    "68:FB:7E": "Apple",
    "70:CD:60": "Apple",
    "78:31:C1": "Apple",
    "7C:D1:C3": "Apple",
    "88:1F:A1": "Apple",
    "8C:85:90": "Apple",
    "90:3C:92": "Apple",
    "98:F0:AB": "Apple",
    "A4:C3:61": "Apple",
    "A8:96:8A": "Apple",
    "AC:7F:3E": "Apple",
    "B8:17:C2": "Apple",
    "BC:92:6B": "Apple",
    "C0:84:7A": "Apple",
    "C8:2A:14": "Apple",
    "D4:90:9C": "Apple",
    "DC:86:D8": "Apple",
    "E4:CE:8F": "Apple",
    "F0:B4:79": "Apple",
    "F4:37:B7": "Apple",
    # Samsung
    "00:00:F0": "Samsung",
    "00:12:47": "Samsung",
    "00:15:99": "Samsung",
    "00:17:D5": "Samsung",
    "00:1A:8A": "Samsung",
    "00:1B:98": "Samsung",
    "00:21:19": "Samsung",
    "00:23:39": "Samsung",
    "08:08:C2": "Samsung",
    "08:D4:2B": "Samsung",
    "10:D5:42": "Samsung",
    "18:22:7E": "Samsung",
    "1C:66:AA": "Samsung",
    "20:64:32": "Samsung",
    "24:4B:03": "Samsung",
    "30:19:66": "Samsung",
    "34:47:90": "Samsung",
    "38:AA:3C": "Samsung",
    "40:0E:85": "Samsung",
    "44:4E:1A": "Samsung",
    "50:F5:20": "Samsung",
    "54:9B:12": "Samsung",
    "5C:49:79": "Samsung",
    "60:A1:0A": "Samsung",
    "64:B3:10": "Samsung",
    "6C:2F:2C": "Samsung",
    "74:45:8A": "Samsung",
    "78:40:E4": "Samsung",
    "7C:61:93": "Samsung",
    "84:25:DB": "Samsung",
    "88:32:9B": "Samsung",
    "8C:71:F8": "Samsung",
    "94:51:03": "Samsung",
    "98:52:B1": "Samsung",
    "9C:3A:AF": "Samsung",
    "A0:82:1F": "Samsung",
    "A8:06:00": "Samsung",
    "AC:5A:14": "Samsung",
    "B0:C4:E7": "Samsung",
    "BC:20:A4": "Samsung",
    "C0:BD:D1": "Samsung",
    "CC:07:AB": "Samsung",
    # Intel
    "00:02:B3": "Intel",
    "00:03:47": "Intel",
    "00:0C:F1": "Intel",
    "00:0E:35": "Intel",
    "00:13:02": "Intel",
    "00:13:20": "Intel",
    "00:13:E8": "Intel",
    "00:15:00": "Intel",
    "00:16:EA": "Intel",
    "00:18:DE": "Intel",
    "00:19:D1": "Intel",
    "00:1B:21": "Intel",
    "00:1C:BF": "Intel",
    "00:21:6A": "Intel",
    "00:21:D8": "Intel",
    "00:22:FA": "Intel",
    "00:23:14": "Intel",
    "00:24:D6": "Intel",
    "24:77:03": "Intel",
    "28:D2:44": "Intel",
    "34:02:86": "Intel",
    "38:DE:AD": "Intel",
    "3C:A9:F4": "Intel",
    "40:25:C2": "Intel",
    "48:45:20": "Intel",
    "4C:34:88": "Intel",
    "54:35:30": "Intel",
    "60:02:B4": "Intel",
    "60:57:18": "Intel",
    "68:05:CA": "Intel",
    "6C:88:14": "Intel",
    "78:92:9C": "Intel",
    "7C:76:35": "Intel",
    "80:19:34": "Intel",
    "84:3A:4B": "Intel",
    "8C:8D:28": "Intel",
    "90:48:9A": "Intel",
    "94:65:9C": "Intel",
    "98:4F:EE": "Intel",
    "A0:A8:CD": "Intel",
    "A4:34:D9": "Intel",
    "A8:7E:EA": "Intel",
    "AC:37:43": "Intel",
    "B0:10:41": "Intel",
    "B4:6B:FC": "Intel",
    "C4:D9:87": "Intel",
    "C8:5B:76": "Intel",
    "D0:7E:35": "Intel",
    # TP-Link
    "1C:3B:F3": "TP-Link",
    "50:C7:BF": "TP-Link",
    "54:C8:0F": "TP-Link",
    "64:70:02": "TP-Link",
    "6C:19:8F": "TP-Link",
    "70:4F:57": "TP-Link",
    "74:DA:38": "TP-Link",
    "98:DA:C4": "TP-Link",
    "A0:F3:C1": "TP-Link",
    "AC:84:C6": "TP-Link",
    "B0:48:7A": "TP-Link",
    "C4:E9:84": "TP-Link",
    "C8:D3:A3": "TP-Link",
    "D8:0D:17": "TP-Link",
    "E4:8D:8C": "TP-Link",
    "E8:DE:27": "TP-Link",
    "EC:08:6B": "TP-Link",
    "F4:EC:38": "TP-Link",
    "F8:1A:67": "TP-Link",
    "10:27:F5": "TP-Link",
    "18:A6:F7": "TP-Link",
    "24:4B:FE": "TP-Link",
    "2C:27:D7": "TP-Link",
    "30:FC:68": "TP-Link",
    "34:60:F9": "TP-Link",
    "40:3F:8C": "TP-Link",
    "44:94:FC": "TP-Link",
    "50:3E:AA": "TP-Link",
    "58:D5:6E": "TP-Link",
    "5C:89:9A": "TP-Link",
    "60:E3:27": "TP-Link",
    "68:FF:7B": "TP-Link",
    "6C:5A:B0": "TP-Link",
    "84:16:F9": "TP-Link",
    "90:F6:52": "TP-Link",
    "98:25:4A": "TP-Link",
    "A0:F3:C1": "TP-Link",
    "B4:B0:24": "TP-Link",
    "C0:4A:00": "TP-Link",
    # NETGEAR
    "00:09:5B": "NETGEAR",
    "00:0F:B5": "NETGEAR",
    "00:14:6C": "NETGEAR",
    "00:18:4D": "NETGEAR",
    "00:1B:2F": "NETGEAR",
    "00:1E:2A": "NETGEAR",
    "00:1F:33": "NETGEAR",
    "00:22:3F": "NETGEAR",
    "00:24:B2": "NETGEAR",
    "00:26:F2": "NETGEAR",
    "20:4E:7F": "NETGEAR",
    "28:C6:8E": "NETGEAR",
    "2C:B0:5D": "NETGEAR",
    "30:46:9A": "NETGEAR",
    "6C:B0:CE": "NETGEAR",
    "84:1B:5E": "NETGEAR",
    "A0:21:B7": "NETGEAR",
    "A0:40:A0": "NETGEAR",
    "C0:3F:0E": "NETGEAR",
    "E0:46:9A": "NETGEAR",
    "10:0C:6B": "NETGEAR",
    "1C:1B:0D": "NETGEAR",
    "20:E5:2A": "NETGEAR",
    "2C:30:33": "NETGEAR",
    "30:B5:C2": "NETGEAR",
    "44:94:FC": "NETGEAR",
    "6C:4B:90": "NETGEAR",
    "9C:3D:CF": "NETGEAR",
    "A4:2B:8C": "NETGEAR",
    # ASUS
    "00:0C:6E": "ASUS",
    "00:0E:A6": "ASUS",
    "00:11:2F": "ASUS",
    "00:13:D4": "ASUS",
    "00:15:F2": "ASUS",
    "00:17:31": "ASUS",
    "00:18:F3": "ASUS",
    "00:1A:92": "ASUS",
    "00:1D:60": "ASUS",
    "00:1E:8C": "ASUS",
    "00:1F:C6": "ASUS",
    "00:22:15": "ASUS",
    "00:23:54": "ASUS",
    "00:24:8C": "ASUS",
    "00:25:22": "ASUS",
    "00:26:18": "ASUS",
    "10:02:B5": "ASUS",
    "10:BF:48": "ASUS",
    "14:DA:E9": "ASUS",
    "1C:87:2C": "ASUS",
    "2C:56:DC": "ASUS",
    "30:85:A9": "ASUS",
    "3C:97:0E": "ASUS",
    "40:16:7E": "ASUS",
    "48:5B:39": "ASUS",
    "50:46:5D": "ASUS",
    "54:04:A6": "ASUS",
    "60:45:CB": "ASUS",
    "6C:72:20": "ASUS",
    "74:D0:2B": "ASUS",
    "88:D7:F6": "ASUS",
    "90:E6:BA": "ASUS",
    "94:DE:80": "ASUS",
    "A8:5E:45": "ASUS",
    "AC:22:0B": "ASUS",
    "B0:6E:BF": "ASUS",
    "BC:AE:C5": "ASUS",
    "C8:60:00": "ASUS",
    "D0:17:C2": "ASUS",
    "E0:3F:49": "ASUS",
    "E8:9F:80": "ASUS",
    "F0:2F:74": "ASUS",
    # D-Link
    "00:05:5D": "D-Link",
    "00:0D:88": "D-Link",
    "00:0F:3D": "D-Link",
    "00:11:95": "D-Link",
    "00:13:46": "D-Link",
    "00:15:E9": "D-Link",
    "00:17:9A": "D-Link",
    "00:19:5B": "D-Link",
    "00:1B:11": "D-Link",
    "00:1C:F0": "D-Link",
    "00:1E:58": "D-Link",
    "00:21:91": "D-Link",
    "00:22:B0": "D-Link",
    "00:24:01": "D-Link",
    "00:26:5A": "D-Link",
    "14:D6:4D": "D-Link",
    "1C:7E:E5": "D-Link",
    "28:10:7B": "D-Link",
    "34:08:04": "D-Link",
    "5C:D9:98": "D-Link",
    "6C:72:20": "D-Link",
    "78:54:2E": "D-Link",
    "84:C9:B2": "D-Link",
    "90:2B:34": "D-Link",
    "A0:AB:1B": "D-Link",
    "BC:F6:85": "D-Link",
    "C8:BE:19": "D-Link",
    # Ubiquiti
    "00:15:6D": "Ubiquiti",
    "00:27:22": "Ubiquiti",
    "04:18:D6": "Ubiquiti",
    "18:E8:29": "Ubiquiti",
    "24:A4:3C": "Ubiquiti",
    "44:D9:E7": "Ubiquiti",
    "68:72:51": "Ubiquiti",
    "74:83:C2": "Ubiquiti",
    "78:8A:20": "Ubiquiti",
    "80:2A:A8": "Ubiquiti",
    "B4:FB:E4": "Ubiquiti",
    "DC:9F:DB": "Ubiquiti",
    "E0:63:DA": "Ubiquiti",
    "F0:9F:C2": "Ubiquiti",
    "FC:EC:DA": "Ubiquiti",
    "00:AA:BB": "Ubiquiti",
    "24:5A:4C": "Ubiquiti",
    "60:22:32": "Ubiquiti",
    # Huawei
    "00:18:82": "Huawei",
    "00:1E:10": "Huawei",
    "00:22:A1": "Huawei",
    "00:25:9E": "Huawei",
    "04:25:C5": "Huawei",
    "04:BD:70": "Huawei",
    "0C:37:DC": "Huawei",
    "10:1B:54": "Huawei",
    "14:B9:68": "Huawei",
    "20:08:ED": "Huawei",
    "20:2B:C1": "Huawei",
    "20:F3:A3": "Huawei",
    "24:DF:6A": "Huawei",
    "28:31:52": "Huawei",
    "2C:AB:00": "Huawei",
    "34:6B:D3": "Huawei",
    "38:B1:DB": "Huawei",
    "40:4D:8E": "Huawei",
    "48:00:31": "Huawei",
    "4C:1F:CC": "Huawei",
    "54:51:1B": "Huawei",
    "5C:C3:07": "Huawei",
    "60:DE:44": "Huawei",
    "64:3E:8C": "Huawei",
    "68:8A:F0": "Huawei",
    "6C:8D:C1": "Huawei",
    "70:72:3C": "Huawei",
    # Xiaomi / Mi
    "00:9E:C8": "Xiaomi",
    "04:CF:8C": "Xiaomi",
    "0C:1D:AF": "Xiaomi",
    "10:2A:B3": "Xiaomi",
    "14:F6:5A": "Xiaomi",
    "18:59:36": "Xiaomi",
    "20:82:C0": "Xiaomi",
    "28:6C:07": "Xiaomi",
    "2C:4D:54": "Xiaomi",
    "34:80:B3": "Xiaomi",
    "38:A4:ED": "Xiaomi",
    "3C:BD:D8": "Xiaomi",
    "50:64:2B": "Xiaomi",
    "58:44:98": "Xiaomi",
    "64:09:80": "Xiaomi",
    "64:B4:73": "Xiaomi",
    "68:DF:DD": "Xiaomi",
    "74:51:BA": "Xiaomi",
    "78:02:F8": "Xiaomi",
    "78:11:DC": "Xiaomi",
    "7C:1D:D9": "Xiaomi",
    "8C:BE:BE": "Xiaomi",
    "98:FA:E3": "Xiaomi",
    "9C:99:A0": "Xiaomi",
    "A0:86:C6": "Xiaomi",
    "AC:C1:EE": "Xiaomi",
    "B0:E2:35": "Xiaomi",
    "C4:0B:CB": "Xiaomi",
    "D4:97:0B": "Xiaomi",
    "F4:8E:08": "Xiaomi",
    # Google
    "F4:F5:D8": "Google",
    "54:60:09": "Google",
    "3C:28:6D": "Google",
    "1A:55:A4": "Google",
    "48:D6:D5": "Google",
    "20:DF:B9": "Google",
    "DA:E5:F9": "Google",
    "7C:2E:BD": "Google",
    "B4:CE:F6": "Google",
    "F0:EF:86": "Google",
    # AVM (FRITZ!Box)
    "00:04:0E": "AVM",
    "C4:A8:1D": "AVM",
    "DC:39:6F": "AVM",
    "E4:67:70": "AVM",
    "9C:C7:A6": "AVM",
    "00:24:FE": "AVM",
    "3C:A1:0D": "AVM",
    "5C:49:79": "AVM",
    "74:31:70": "AVM",
    "A0:24:EC": "AVM",
    "A8:17:58": "AVM",
    # Linksys
    "00:03:6C": "Linksys",
    "00:06:25": "Linksys",
    "00:0C:41": "Linksys",
    "00:0F:66": "Linksys",
    "00:12:17": "Linksys",
    "00:13:10": "Linksys",
    "00:14:BF": "Linksys",
    "00:16:B6": "Linksys",
    "00:18:39": "Linksys",
    "00:1A:70": "Linksys",
    "00:1C:10": "Linksys",
    "00:1D:7E": "Linksys",
    "00:1E:E5": "Linksys",
    "00:21:29": "Linksys",
    "00:22:6B": "Linksys",
    "00:23:69": "Linksys",
    "00:25:9C": "Linksys",
    "20:AA:4B": "Linksys",
    "58:6D:8F": "Linksys",
    "68:7F:74": "Linksys",
    # Eero
    "F8:BB:BF": "Eero",
    "64:FF:0A": "Eero",
    "F0:5C:19": "Eero",
    "50:91:E3": "Eero",
    "6C:19:C0": "Eero",
    # Qualcomm/Atheros (NICs)
    "00:03:7F": "Atheros",
    "00:05:88": "Atheros",
    # MediaTek/Ralink
    "00:0C:43": "Ralink/MT",
    "00:21:F7": "Ralink/MT",
    # Realtek
    "00:E0:4C": "Realtek",
    "52:54:00": "QEMU/VBox",
}

_oui_full: Optional[Dict[str, str]] = None
_oui_loaded = False

# Path where we save the downloaded IEEE OUI database
OUI_DATA_DIR = Path.home() / ".local" / "share" / "nmcli-gui"
OUI_JSON_PATH = OUI_DATA_DIR / "oui.json"
OUI_IEEE_URL = "https://standards-oui.ieee.org/"
OUI_IEEE_RE = re.compile(r"([0-9A-F]{2}-[0-9A-F]{2}-[0-9A-F]{2})\s+\(hex\)\s+(.+?)\n")


def _load_downloaded_oui() -> Dict[str, str]:
    """Load our locally saved IEEE JSON.  Returns {} if not present."""
    if not OUI_JSON_PATH.exists():
        return {}
    try:
        raw: Dict[str, str] = json.loads(OUI_JSON_PATH.read_text(encoding="utf-8"))
        # Normalise keys to AA:BB:CC form (may be stored as AA-BB-CC)
        return {k.replace("-", ":").upper(): v for k, v in raw.items()}
    except Exception:
        return {}


def _load_system_oui() -> Dict[str, str]:
    """Fall back to wireshark/ieee-data system files if IEEE JSON not downloaded."""
    candidates = [
        "/usr/share/wireshark/manuf",
        "/usr/share/ieee-data/oui.txt",
        "/usr/share/misc/oui.txt",
        "/usr/share/nmap/nmap-mac-prefixes",
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            db: Dict[str, str] = {}
            with open(path, "r", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        mac_raw = parts[0].strip()
                        vendor = (
                            parts[-1].strip() if len(parts) > 2 else parts[1].strip()
                        )
                        mac = mac_raw.replace("-", ":").upper()
                        if len(mac) >= 8:
                            db[mac[:8]] = vendor
            if db:
                return db
        except Exception:
            pass
    return {}


def reload_oui_db():
    """Force reload of the OUI database (call after a fresh download)."""
    global _oui_full, _oui_loaded
    _oui_full = _load_downloaded_oui() or _load_system_oui()
    _oui_loaded = True


def get_manufacturer(bssid: str) -> str:
    global _oui_full, _oui_loaded
    if not _oui_loaded:
        _oui_full = _load_downloaded_oui() or _load_system_oui()
        _oui_loaded = True
    if not bssid:
        return "Unknown"
    mac = bssid.upper().replace("-", ":")
    prefix = mac[:8]
    if _oui_full and prefix in _oui_full:
        return _oui_full[prefix]
    return _EMBEDDED_OUI.get(prefix, "Unknown")


# ─────────────────────────────────────────────────────────────────────────────
# OUI Download Thread + First-Run Dialog
# ─────────────────────────────────────────────────────────────────────────────


class OuiDownloadThread(QThread):
    """Downloads and parses the IEEE OUI text file in a background thread."""

    progress = pyqtSignal(str)  # status message
    finished = pyqtSignal(bool, str)  # success, message

    def run(self):
        try:
            self.progress.emit("Connecting to standards-oui.ieee.org…")
            req = urllib.request.Request(
                OUI_IEEE_URL, headers={"User-Agent": "nmcli-gui-wifi-analyzer/1.0"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.progress.emit("Downloading OUI data (may take a few seconds)…")
                raw = resp.read().decode("utf-8", errors="replace")

            self.progress.emit("Parsing entries…")
            matches = OUI_IEEE_RE.findall(raw)
            db = {m[0].replace("-", ":"): m[1].strip() for m in matches}

            if not db:
                self.finished.emit(False, "No OUI entries found in downloaded data.")
                return

            self.progress.emit(f"Saving {len(db):,} entries…")
            OUI_DATA_DIR.mkdir(parents=True, exist_ok=True)
            OUI_JSON_PATH.write_text(
                json.dumps(db, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            reload_oui_db()
            self.finished.emit(True, f"Downloaded {len(db):,} manufacturer entries.")

        except Exception as exc:
            self.finished.emit(False, str(exc))


class OuiDownloadDialog(QDialog):
    """Modal dialog that offers / performs the IEEE OUI database download."""

    def __init__(self, parent=None, first_run: bool = True):
        super().__init__(parent)
        self._first_run = first_run
        self._thread: Optional[OuiDownloadThread] = None
        self.setWindowTitle("Manufacturer Database")
        self.setMinimumWidth(460)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        if first_run:
            header = QLabel(
                "<b>Download IEEE OUI Manufacturer Database?</b><br><br>"
                "WiFi Analyzer can show the manufacturer name for each "
                'access point (e.g. "TP-Link", "ASUS", "Apple").  '
                "This requires downloading ~4 MB of data from "
                "<tt>standards-oui.ieee.org</tt> (run once, stored locally)."
            )
        else:
            header = QLabel(
                "<b>Update IEEE OUI Manufacturer Database</b><br><br>"
                "This will re-download the latest OUI data (~4 MB) from "
                "<tt>standards-oui.ieee.org</tt> and save it locally."
            )
        header.setWordWrap(True)
        header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(header)

        self._status = QLabel("Ready.")
        self._status.setStyleSheet("color:#8a96b0; font-size:9pt;")
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.hide()
        layout.addWidget(self._progress)

        btns = QDialogButtonBox()
        self._btn_download = btns.addButton(
            "Download", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._btn_skip = btns.addButton(
            "Skip" if first_run else "Close", QDialogButtonBox.ButtonRole.RejectRole
        )
        self._btn_download.clicked.connect(self._start_download)
        self._btn_skip.clicked.connect(self.reject)
        layout.addWidget(btns)

    def _start_download(self):
        self._btn_download.setEnabled(False)
        self._btn_skip.setEnabled(False)
        self._progress.show()
        self._status.setText("Starting…")

        self._thread = OuiDownloadThread(self)
        self._thread.progress.connect(self._status.setText)
        self._thread.finished.connect(self._on_finished)
        self._thread.start()

    def _on_finished(self, ok: bool, msg: str):
        self._progress.hide()
        if ok:
            self._status.setText(f"✓  {msg}")
            self._status.setStyleSheet("color:#4caf50; font-size:9pt;")
            self._btn_skip.setText("Close")
        else:
            self._status.setText(f"✗  {msg}")
            self._status.setStyleSheet("color:#ef5350; font-size:9pt;")
            self._btn_download.setEnabled(True)
        self._btn_skip.setEnabled(True)


# ─────────────────────────────────────────────────────────────────────────────
# Data Model
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class AccessPoint:
    # ── Required fields (nmcli) ─────────────────────────────────────────────
    ssid: str
    bssid: str
    mode: str
    channel: int
    freq_mhz: int
    rate_mbps: float
    signal: int  # 0-100 (nmcli)
    security: str
    wpa_flags: str
    rsn_flags: str
    bandwidth_mhz: int
    in_use: bool
    # ── Optional enrichment fields (from iw dev scan dump) ──────────────────
    dbm_exact: Optional[float] = None  # real dBm from iw, more precise
    wifi_gen: str = ""  # "WiFi 4" / "WiFi 5" / "WiFi 6" / "WiFi 6E" / "WiFi 7"
    chan_util: Optional[int] = None  # BSS Load channel utilization 0-255
    station_count: Optional[int] = None  # BSS Load station count
    pmf: str = ""  # "No" / "Optional" / "Required"
    akm: str = ""  # "WPA2-PSK" / "WPA3-SAE" / "Enterprise" / …
    rrm: bool = False  # 802.11k Radio Resource Measurement
    btm: bool = False  # 802.11v BSS Transition Management
    ft: bool = False  # 802.11r Fast Transition
    country: str = ""  # Country code from beacon (e.g. "DE")
    # ── Computed in __post_init__ ────────────────────────────────────────────
    band: str = field(init=False)
    manufacturer: str = field(init=False)

    def __post_init__(self):
        self.band = freq_to_band(self.freq_mhz)
        self.manufacturer = get_manufacturer(self.bssid)

    @property
    def dbm(self) -> int:
        """Prefer exact iw dBm; fall back to nmcli signal approximation."""
        if self.dbm_exact is not None:
            return int(round(self.dbm_exact))
        return signal_to_dbm(self.signal)

    @property
    def chan_util_pct(self) -> Optional[int]:
        """Channel utilization as 0-100 percent (None if unavailable)."""
        if self.chan_util is not None:
            return int(round(self.chan_util / 255 * 100))
        return None

    @property
    def kvr_flags(self) -> str:
        """Compact 802.11k/v/r roaming-feature badge, e.g. 'k v r' or '—'."""
        flags = []
        if self.rrm:
            flags.append("k")
        if self.btm:
            flags.append("v")
        if self.ft:
            flags.append("r")
        return " ".join(flags) if flags else "—"

    @property
    def protocol(self) -> str:
        """IEEE 802.11 amendment letter(s) — e.g. 'AX', 'AC', 'N', 'A/B/G'."""
        _GEN_PROTO = {
            "WiFi 7": "BE  (802.11be)",
            "WiFi 6E": "AX  (802.11ax)",
            "WiFi 6": "AX  (802.11ax)",
            "WiFi 5": "AC  (802.11ac)",
            "WiFi 4": "N   (802.11n)",
        }
        if self.wifi_gen in _GEN_PROTO:
            return _GEN_PROTO[self.wifi_gen]
        # Legacy — infer from band
        if self.freq_mhz >= 5000:
            return "A   (802.11a)"
        return "B/G (802.11b/g)"

    @property
    def display_ssid(self) -> str:
        return self.ssid if self.ssid else f"<hidden> ({self.bssid})"

    @property
    def security_short(self) -> str:
        """Human-readable security summary; uses iw AKM info when available."""
        if self.akm:
            return self.akm
        if self.rsn_flags and self.rsn_flags not in ("(none)", "--", ""):
            return "WPA2/3"
        if self.wpa_flags and self.wpa_flags not in ("(none)", "--", ""):
            return "WPA"
        if not self.security or self.security in ("--", ""):
            return "Open"
        return self.security


# ─────────────────────────────────────────────────────────────────────────────
# nmcli Scanner Thread
# ─────────────────────────────────────────────────────────────────────────────

NMCLI_FIELDS = "IN-USE,SSID,BSSID,MODE,CHAN,FREQ,RATE,SIGNAL,SECURITY,WPA-FLAGS,RSN-FLAGS,BANDWIDTH"


def _split_terse(line: str) -> List[str]:
    """Split a nmcli terse line on unescaped ':' characters."""
    fields: List[str] = []
    cur: List[str] = []
    i = 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line) and line[i + 1] == ":":
            cur.append(":")
            i += 2
        elif line[i] == ":":
            fields.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(line[i])
            i += 1
    fields.append("".join(cur))
    return fields


def _parse_freq(freq_str: str) -> int:
    m = re.search(r"(\d+)", freq_str)
    return int(m.group(1)) if m else 0


def _parse_rate(rate_str: str) -> float:
    m = re.search(r"([\d.]+)", rate_str)
    return float(m.group(1)) if m else 0.0


def _parse_bw(bw_str: str) -> int:
    m = re.search(r"(\d+)", bw_str)
    return int(m.group(1)) if m else 20


def parse_nmcli(output: str) -> List[AccessPoint]:
    aps: List[AccessPoint] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = _split_terse(line)
        if len(parts) < 12:
            continue
        try:
            in_use = parts[0].strip() == "*"
            ssid = parts[1].strip()
            bssid = parts[2].strip()
            mode = parts[3].strip()
            chan = int(parts[4]) if parts[4].strip().isdigit() else 0
            freq = _parse_freq(parts[5])
            rate = _parse_rate(parts[6])
            signal = int(parts[7]) if parts[7].strip().isdigit() else 0
            security = parts[8].strip()
            wpa = parts[9].strip()
            rsn = parts[10].strip()
            bw = _parse_bw(parts[11])
            # Derive freq from channel if not provided
            if freq == 0 and chan:
                freq = chan_to_freq(chan)
            aps.append(
                AccessPoint(
                    ssid=ssid,
                    bssid=bssid,
                    mode=mode,
                    channel=chan,
                    freq_mhz=freq,
                    rate_mbps=rate,
                    signal=signal,
                    security=security,
                    wpa_flags=wpa,
                    rsn_flags=rsn,
                    bandwidth_mhz=bw,
                    in_use=in_use,
                )
            )
        except Exception:
            continue
    return aps


# ─────────────────────────────────────────────────────────────────────────────
# iw scan helpers  (enrich nmcli data with BSS Load, WiFi gen, 802.11k/v/r …)
# ─────────────────────────────────────────────────────────────────────────────

_IW_IFACE: Optional[str] = None


def _detect_wifi_iface() -> Optional[str]:
    """Return the first 'managed' wireless interface found by `iw dev`."""
    global _IW_IFACE
    if _IW_IFACE:
        return _IW_IFACE
    try:
        out = subprocess.run(
            ["iw", "dev"], capture_output=True, text=True, timeout=3
        ).stdout
        iface: Optional[str] = None
        for line in out.splitlines():
            s = line.strip()
            if s.startswith("Interface "):
                iface = s.split()[1]
            elif s.startswith("type managed") and iface:
                _IW_IFACE = iface
                return iface
    except Exception:
        pass
    return None


_IW_GEN_COLORS = {
    "WiFi 7": "#6A1B9A",  # deep purple
    "WiFi 6E": "#AD1457",  # raspberry
    "WiFi 6": "#1565C0",  # royal blue
    "WiFi 5": "#00695C",  # dark teal
    "WiFi 4": "#2E7D32",  # dark green
}


def parse_iw_scan(output: str) -> Dict[str, dict]:
    """
    Parse the text output of 'iw dev <iface> scan dump' into a dict
    keyed by lowercase BSSID.  Each value is a dict of enrichment fields.
    """
    result: Dict[str, dict] = {}
    # Split on BSS-header lines
    blocks = re.split(r"(?m)^BSS ", output)
    for block in blocks[1:]:
        lines = block.splitlines()
        if not lines:
            continue
        m = re.match(r"([0-9a-f:]{17})", lines[0], re.IGNORECASE)
        if not m:
            continue
        bssid = m.group(1).lower()
        text = "\n".join(lines)
        d: dict = {}

        # ── Exact dBm ────────────────────────────────────────────────────
        sig_m = re.search(r"signal:\s*([-\d.]+)\s*dBm", text)
        if sig_m:
            d["dbm_exact"] = float(sig_m.group(1))

        # ── WiFi generation ──────────────────────────────────────────────
        has_eht = "EHT capabilities" in text
        has_he = "HE capabilities" in text
        has_vht = "VHT capabilities" in text
        has_ht = "HT capabilities" in text
        freq_m = re.search(r"freq:\s*([\d.]+)", text)
        freq_val = float(freq_m.group(1)) if freq_m else 0
        if has_eht:
            d["wifi_gen"] = "WiFi 7"
        elif has_he:
            d["wifi_gen"] = "WiFi 6E" if freq_val >= 5925 else "WiFi 6"
        elif has_vht:
            d["wifi_gen"] = "WiFi 5"
        elif has_ht:
            d["wifi_gen"] = "WiFi 4"
        else:
            d["wifi_gen"] = ""

        # ── BSS Load ─────────────────────────────────────────────────────
        sc_m = re.search(r"station count:\s*(\d+)", text)
        cu_m = re.search(r"channel utilis[ae]tion:\s*(\d+)/255", text)
        if sc_m:
            d["station_count"] = int(sc_m.group(1))
        if cu_m:
            d["chan_util"] = int(cu_m.group(1))

        # ── RSN / AKM / PMF ──────────────────────────────────────────────
        akm_m = re.search(r"Authentication suites:(.*)", text)
        if akm_m:
            raw = akm_m.group(1)
            has_sae = "SAE" in raw
            has_psk = "PSK" in raw and "FT/PSK" not in raw or "PSK" in raw
            has_eap = "EAP" in raw or "802.1X" in raw
            has_owe = "OWE" in raw
            d["ft"] = "FT/" in raw
            if has_owe:
                label = "OWE (Enhanced Open)"
            elif has_eap:
                label = "Enterprise (EAP)"
            elif has_sae and has_psk:
                label = "WPA2+WPA3"
            elif has_sae:
                label = "WPA3-SAE"
            elif has_psk:
                label = "WPA2-PSK"
            else:
                label = raw.strip()
            if d["ft"]:
                label += " +FT"
            d["akm"] = label

        caps_m = re.search(
            r"Capabilities:.*?MFP-(capable|required)", text, re.IGNORECASE
        )
        if caps_m:
            d["pmf"] = (
                "Required" if "required" in caps_m.group(1).lower() else "Optional"
            )
        else:
            d["pmf"] = "No"

        # ── 802.11k / 802.11v ────────────────────────────────────────────
        d["rrm"] = "Neighbor Report" in text
        d["btm"] = "BSS Transition" in text

        # ── Country code ─────────────────────────────────────────────────
        cc_m = re.search(r"Country:\s+([A-Z]{2})", text)
        if cc_m:
            d["country"] = cc_m.group(1)

        result[bssid] = d
    return result


def enrich_with_iw(aps: List[AccessPoint]) -> None:
    """Run 'iw dev scan dump' and merge extra fields into each AccessPoint."""
    iface = _detect_wifi_iface()
    if not iface:
        return
    try:
        res = subprocess.run(
            ["iw", "dev", iface, "scan", "dump"],
            capture_output=True,
            text=True,
            timeout=6,
        )
        if res.returncode != 0:
            return
        iw_data = parse_iw_scan(res.stdout)
        for ap in aps:
            d = iw_data.get(ap.bssid.lower())
            if not d:
                continue
            for attr in (
                "dbm_exact",
                "wifi_gen",
                "chan_util",
                "station_count",
                "pmf",
                "akm",
                "rrm",
                "btm",
                "ft",
                "country",
            ):
                if attr in d:
                    setattr(ap, attr, d[attr])
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
class WiFiScanner(QThread):
    """Background thread: periodically calls nmcli and emits fresh AP list."""

    data_ready = pyqtSignal(list)  # list[AccessPoint]
    scan_error = pyqtSignal(str)

    def __init__(self, interval_sec: int = 2):
        super().__init__()
        self._interval = interval_sec
        self._running = False

    def set_interval(self, secs: int):
        self._interval = secs

    def run(self):
        self._running = True
        while self._running:
            try:
                result = subprocess.run(
                    ["nmcli", "-t", "-f", NMCLI_FIELDS, "dev", "wifi"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                if result.returncode == 0:
                    aps = parse_nmcli(result.stdout)
                    enrich_with_iw(aps)  # merge iw BSS-Load / WiFi-gen / k-v-r data
                    self.data_ready.emit(aps)
                else:
                    self.scan_error.emit(result.stderr.strip())
            except FileNotFoundError:
                self.scan_error.emit("nmcli not found — is NetworkManager installed?")
                break
            except subprocess.TimeoutExpired:
                self.scan_error.emit("nmcli timed out")
            except Exception as e:
                self.scan_error.emit(str(e))
            time.sleep(self._interval)

    def stop(self):
        self._running = False
        self.wait(2000)


# ─────────────────────────────────────────────────────────────────────────────
# Table Model
# ─────────────────────────────────────────────────────────────────────────────

TABLE_HEADERS = [
    "▲",
    "SSID",
    "BSSID (MAC)",
    "Manufacturer",
    "Band",
    "Ch",
    "Freq (MHz)",
    "BW (MHz)",
    "Signal",
    "dBm",
    "Rate (Mbps)",
    "Security",
    "Mode",
    "Gen",
    "Ch.Util%",
    "Clients",
    "k/v/r",
]

COL_INUSE = 0
COL_SSID = 1
COL_BSSID = 2
COL_MANUF = 3
COL_BAND = 4
COL_CHAN = 5
COL_FREQ = 6
COL_BW = 7
COL_SIG = 8
COL_DBM = 9
COL_RATE = 10
COL_SEC = 11
COL_MODE = 12
COL_GEN = 13  # WiFi generation (WiFi 4/5/6/6E/7)
COL_UTIL = 14  # Channel utilisation %  (BSS Load)
COL_CLIENTS = 15  # Station count          (BSS Load)
COL_KVR = 16  # 802.11k/v/r roaming flags


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

        if role == Qt.ItemDataRole.ForegroundRole:
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
                c = _IW_GEN_COLORS.get(ap.wifi_gen)
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
                COL_SIG,
                COL_DBM,
                COL_RATE,
                COL_UTIL,
                COL_CLIENTS,
            }
            if col in numeric_cols:
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
            return ap.manufacturer
        if col == COL_BAND:
            return ap.band
        if col == COL_CHAN:
            return str(ap.channel) if ap.channel else "?"
        if col == COL_FREQ:
            return str(ap.freq_mhz)
        if col == COL_BW:
            return str(ap.bandwidth_mhz)
        if col == COL_SIG:
            return f"{ap.signal}%"
        if col == COL_DBM:
            return f"{ap.dbm} dBm"
        if col == COL_RATE:
            return str(int(ap.rate_mbps))
        if col == COL_SEC:
            return ap.security_short
        if col == COL_MODE:
            return ap.mode
        if col == COL_GEN:
            return ap.wifi_gen or "—"
        if col == COL_UTIL:
            pct = ap.chan_util_pct
            return f"{pct}%" if pct is not None else "—"
        if col == COL_CLIENTS:
            return str(ap.station_count) if ap.station_count is not None else "—"
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
        COL_CHAN: "Ch",
        COL_SEC: "Security",
        COL_GEN: "Gen",
        COL_KVR: "k/v/r",
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


def _channel_shape_unit(xs: np.ndarray, fc: float, bw: float) -> np.ndarray:
    """
    Returns a 0..1 flat-top shape with cosine rolloff shoulders.
    Multiply by (amplitude - floor) and shift by floor for dBm display.
    """
    half = bw / 2.0
    shoulder = max(half * 0.12, 5.0)  # 12 % of half-BW, min 5 MHz
    d = np.abs(xs - fc)
    in_flat = d <= (half - shoulder)
    in_roll = (~in_flat) & (d <= half)
    t = np.where(in_roll, (d - (half - shoulder)) / shoulder, 0.0)
    return np.where(
        in_flat, 1.0, np.where(in_roll, 0.5 * (1.0 + np.cos(np.pi * t)), 0.0)
    )


# ─── Color-coded dBm axis ────────────────────────────────────────────────────
class DbmAxisItem(pg.AxisItem):
    """
    Y-axis whose tick labels are colour-coded by signal-quality zone:
      green  ≥ -50 dBm  (excellent)
      lime   -50 … -60  (good)
      amber  -60 … -70  (fair)
      orange -70 … -80  (weak)
      red    < -80       (poor)
    """

    _BANDS = [
        (-50, 0, "#4caf50"),  # excellent — green
        (-60, -50, "#8bc34a"),  # good      — lime
        (-70, -60, "#ffc107"),  # fair      — amber
        (-80, -70, "#ff9800"),  # weak      — orange
        (-200, -80, "#f44336"),  # poor      — red
    ]

    def _dbm_color(self, text: str):
        try:
            v = float(text)
        except ValueError:
            pass
        else:
            for lo, hi, hex_c in self._BANDS:
                if lo <= v < hi:
                    return pg.mkColor(hex_c)
        is_dark = (
            QApplication.instance()
            .palette()
            .color(QPalette.ColorRole.Window)
            .lightness()
            < 128
        )
        return pg.mkColor("#8a96b0" if is_dark else "#445566")

    def drawPicture(self, p, axisSpec, tickSpecs, textSpecs):
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing, False)
        p.setRenderHint(p.RenderHint.TextAntialiasing, True)
        pen, p1, p2 = axisSpec
        p.setPen(pen)
        p.drawLine(p1, p2)
        for pen, p1, p2 in tickSpecs:
            p.setPen(pen)
            p.drawLine(p1, p2)
        if self.style.get("tickFont") is not None:
            p.setFont(self.style["tickFont"])
        for rect, flags, text in textSpecs:
            p.setPen(self._dbm_color(text))
            p.drawText(rect, int(flags), text)
        p.restore()


# ─── Clickable label for channel graph ───────────────────────────────────────
class _ClickableLabel(pg.TextItem):
    """TextItem that fires a callback with the AP bssid when clicked."""

    def __init__(self, bssid: str, on_click, **kwargs):
        super().__init__(**kwargs)
        self._bssid = bssid
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._on_click(self._bssid)
            ev.accept()


class ChannelGraphWidget(QWidget):
    """Multi-panel channel view — one panel per WiFi band, dead spectrum removed."""

    ap_highlighted = pyqtSignal(object)  # str | None

    _BANDS_ORDER: List[str] = ["2.4 GHz", "5 GHz", "6 GHz"]
    _BAND_EXTENTS: Dict[str, Tuple[int, int]] = {
        "2.4 GHz": (2385, 2500),
        "5 GHz": (5080, 5920),
        # 6 GHz: band edges 5925–7125 MHz; ch1 center=5955, ch233 center=7115
        "6 GHz": (5930, 7130),
    }
    _BAND_TICKS: Dict[str, dict] = {
        "2.4 GHz": CH24,
        "5 GHz": CH5,
        "6 GHz": CH6,
    }
    # Visual panel width weights — proportional to MHz span
    # 2.4 GHz ~115 MHz, 5 GHz ~840 MHz, 6 GHz ~1200 MHz
    _BAND_STRETCH: Dict[str, int] = {
        "2.4 GHz": 2,
        "5 GHz": 5,
        "6 GHz": 8,  # wider: 1200 MHz span vs 840 for 5 GHz
    }
    # Tick stride per band — subsample dense channel grids for readability
    _BAND_TICK_STRIDE: Dict[str, int] = {
        "2.4 GHz": 1,  # 14 channels → show all
        "5 GHz": 1,  # ~36 channels → show all
        "6 GHz": 1,  # handled via _BAND_TICK_SET override below
    }
    # For 6 GHz: show the 80/160/320 MHz anchor channels used by Wi-Fi 6E/7 APs
    # These are the standard 6 GHz preferred scanning channels (PSC) for 20 MHz:
    # every 4th primary, i.e. ch 5, 21, 37, 53, 69, 85, 101, 117, 133, 149, 165,
    # 181, 197, 213, 229 — plus ch 1 and 233 as band-edge anchors.
    _6GHZ_TICK_CHANS: List[int] = [
        1,
        5,
        21,
        37,
        53,
        69,
        85,
        101,
        117,
        133,
        149,
        165,
        181,
        197,
        213,
        229,
        233,
    ]

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._panels_widget = QWidget()
        self._panels_layout = QHBoxLayout(self._panels_widget)
        self._panels_layout.setContentsMargins(0, 0, 0, 0)
        self._panels_layout.setSpacing(2)
        outer.addWidget(self._panels_widget)

        # band → PlotWidget (rebuilt whenever active band set changes)
        self._plots: Dict[str, PlotWidget] = {}
        self._active_bands: List[str] = []
        # bssid → {color, zero, fill, curve, label}
        self._items: Dict[str, dict] = {}
        self._aps: List[AccessPoint] = []
        self._ssid_colors: Dict[str, QColor] = {}
        self._band = "All"
        self._highlighted: Optional[str] = None
        self._theme_bg = "#0d1117"
        self._theme_fg = "#a9b4cc"
        self._band_channels: Dict[str, Dict[float, int]] = {}  # band → {freq_mhz: chan}

    # ── Public API ────────────────────────────────────────────────────────

    def set_theme(self, bg: str, fg: str):
        self._theme_bg = bg
        self._theme_fg = fg
        for i, (band, pw) in enumerate(self._plots.items()):
            pw.setBackground(bg)
            if i == 0:
                pw.setLabel("left", "Signal (dBm)", color=fg, size="10pt")
            pw.setLabel("bottom", band, color=fg, size="10pt")
            for ax in ("left", "bottom"):
                pw.getAxis(ax).setTextPen(fg)
                pw.getAxis(ax).setPen(fg)

    def set_band(self, band: str):
        self._band = band
        self._redraw()

    def set_ssid_colors(self, colors: Dict[str, QColor]):
        self._ssid_colors = colors

    def update_aps(self, aps: List[AccessPoint], colors: Dict[str, QColor]):
        self._aps = aps
        self._ssid_colors = colors
        self._redraw()

    def highlight_bssid(self, bssid: Optional[str]):
        self._highlighted = bssid
        self._apply_highlight()

    # ── Internal ──────────────────────────────────────────────────────────

    def _make_plot(self, band: str, is_leftmost: bool) -> "PlotWidget":
        axis_items: dict = {}
        if is_leftmost:
            axis_items["left"] = DbmAxisItem(orientation="left")
        pw = PlotWidget(axisItems=axis_items)
        pw.setBackground(self._theme_bg)
        pw.showGrid(x=True, y=True, alpha=0.18)
        fg = self._theme_fg
        if is_leftmost:
            pw.setLabel("left", "Signal (dBm)", color=fg, size="10pt")
        else:
            pw.getAxis("left").setWidth(0)
            pw.getAxis("left").hide()
        pw.setLabel("bottom", band, color=fg, size="10pt")
        pw.getAxis("bottom").setTextPen(fg)
        pw.setMenuEnabled(False)
        pw.getViewBox().setMouseEnabled(x=True, y=False)
        pw.scene().sigMouseClicked.connect(self._on_bg_click)
        pw.scene().sigMouseMoved.connect(
            lambda pos, b=band, p=pw: self._on_mouse_hover(b, p, pos)
        )
        return pw

    def _rebuild_panels(self, bands: List[str]):
        for pw in self._plots.values():
            self._panels_layout.removeWidget(pw)
            pw.setParent(None)
            pw.deleteLater()
        self._plots.clear()

        for i, band in enumerate(bands):
            pw = self._make_plot(band, i == 0)
            self._panels_layout.addWidget(pw, self._BAND_STRETCH.get(band, 3))
            self._plots[band] = pw

        self._active_bands = list(bands)

    def _on_label_click(self, bssid: str):
        self._highlighted = None if self._highlighted == bssid else bssid
        self._apply_highlight()
        self.ap_highlighted.emit(self._highlighted)

    def _on_bg_click(self, ev):
        if ev.isAccepted():
            return
        if self._highlighted is not None:
            self._highlighted = None
            self._apply_highlight()
            self.ap_highlighted.emit(None)

    def _apply_highlight(self):
        h = self._highlighted
        for bssid, items in self._items.items():
            if h is None or bssid == h:
                alpha_curve, alpha_fill, alpha_label = 255, 55, 255
            else:
                alpha_curve, alpha_fill, alpha_label = 28, 12, 40
            color: QColor = items["color"]
            c = QColor(color)
            c.setAlpha(alpha_curve)
            items["curve"].setPen(mkPen(color=c, width=2))
            fc = QColor(color)
            fc.setAlpha(alpha_fill)
            items["fill"].setBrush(mkBrush(fc))
            items["label"].setColor(
                QColor(color.red(), color.green(), color.blue(), alpha_label)
            )

    def _on_mouse_hover(self, band: str, pw: "PlotWidget", pos) -> None:
        if not pw.sceneBoundingRect().contains(pos):
            QToolTip.hideText()
            return
        view_pos = pw.plotItem.vb.mapSceneToView(pos)
        freq = view_pos.x()
        channels = self._band_channels.get(band, {})
        if not channels:
            return
        nearest_f = min(channels, key=lambda f: abs(f - freq))
        if abs(nearest_f - freq) < 25:
            QToolTip.showText(
                QCursor.pos(),
                f"Channel {channels[nearest_f]}  ·  {int(nearest_f)} MHz",
                pw,
            )
        else:
            QToolTip.hideText()

    def _needed_bands(self, visible: List[AccessPoint]) -> List[str]:
        if self._band != "All":
            return [self._band] if self._band in self._BAND_EXTENTS else []
        present = {a.band for a in visible if a.band in self._BAND_EXTENTS}
        return [b for b in self._BANDS_ORDER if b in present]

    def _redraw(self):
        self._items = {}
        visible = [a for a in self._aps if self._band == "All" or a.band == self._band]
        needed = self._needed_bands(visible)

        if needed != self._active_bands:
            self._rebuild_panels(needed)

        for pw in self._plots.values():
            pw.clear()

        # If no bands are needed at all (unknown band selected) bail out.
        # Do NOT bail when visible is empty — we still need correct axes.
        if not needed:
            return

        floor = CHAN_DBM_FLOOR
        y_ticks = [(v, str(v)) for v in range(floor, CHAN_DBM_CEIL + 1, 10)]

        for band, pw in self._plots.items():
            band_aps = [a for a in visible if a.band == band]
            xmin, xmax = self._BAND_EXTENTS[band]
            xs = np.linspace(xmin, xmax, 2000)
            floor_ys = np.full_like(xs, float(floor))
            tick_src = self._BAND_TICKS[band]

            for ap in band_aps:
                color = self._ssid_colors.get(ap.ssid, QColor("#888888"))
                unit = _channel_shape_unit(xs, ap.freq_mhz, max(ap.bandwidth_mhz, 20))
                ys = floor + (ap.dbm - floor) * unit

                bc = QColor(color)
                bc.setAlpha(55)
                zero_item = pg.PlotCurveItem(xs, floor_ys)
                curve_item = pg.PlotCurveItem(xs, ys, pen=mkPen(color=color, width=2))
                fill_item = pg.FillBetweenItem(zero_item, curve_item, brush=mkBrush(bc))
                pw.addItem(zero_item)
                pw.addItem(fill_item)
                pw.addItem(curve_item)

                label = _ClickableLabel(
                    bssid=ap.bssid,
                    on_click=self._on_label_click,
                    text=ap.display_ssid,
                    color=color,
                    anchor=(0.5, 1.1),
                )
                lf = QFont()
                lf.setPointSize(8)
                lf.setBold(True)
                label.setFont(lf)
                label.setPos(ap.freq_mhz, ap.dbm)
                pw.addItem(label)

                self._items[ap.bssid] = {
                    "color": color,
                    "zero": zero_item,
                    "fill": fill_item,
                    "curve": curve_item,
                    "label": label,
                }

            pw.getAxis("left").setTicks([y_ticks])
            self._band_channels[band] = {
                float(f): c for c, f in tick_src.items() if xmin <= f <= xmax
            }
            # Build channel ticks — use curated anchor-channel set for 6 GHz
            if band == "6 GHz":
                allowed = set(self._6GHZ_TICK_CHANS)
                ticks = [
                    (float(f), str(c))
                    for c, f in tick_src.items()
                    if xmin <= f <= xmax and c in allowed
                ]
                ticks.sort()
            else:
                stride = self._BAND_TICK_STRIDE.get(band, 1)
                sorted_chan = sorted(tick_src.items(), key=lambda x: x[1])
                ticks = [
                    (f, str(c))
                    for i, (c, f) in enumerate(sorted_chan)
                    if xmin <= f <= xmax and i % stride == 0
                ]
            if ticks:
                pw.getAxis("bottom").setTicks([ticks])

            # ── Band-specific spectrum annotations ─────────────────────────
            if band == "5 GHz":
                # DFS channels — thin amber bar along the bottom edge
                dfs_bar = pg.PlotCurveItem(
                    [5250, 5730],
                    [floor, floor],
                    pen=pg.mkPen(QColor(255, 170, 30), width=5),
                )
                dfs_bar.setZValue(10)
                pw.addItem(dfs_bar)

            elif band == "6 GHz":
                # ── UNII sub-band markers ──────────────────────────────────
                # UNII-5 (5925–6425 MHz): Low-Power Indoor + VLP, no AFC needed
                # UNII-6 (6425–6525 MHz): Standard Power, AFC required
                # UNII-7 (6525–6875 MHz): Standard Power, AFC required
                # UNII-8 (6875–7125 MHz): Standard Power, AFC required
                _UNII_SEGMENTS = [
                    (5925, 6425, QColor("#26a65b"), "UNII-5 (LPI)"),  # green
                    (6425, 6525, QColor("#e67e22"), "UNII-6 (AFC)"),  # orange
                    (6525, 6875, QColor("#e67e22"), "UNII-7 (AFC)"),  # orange
                    (6875, 7125, QColor("#e67e22"), "UNII-8 (AFC)"),  # orange
                ]
                for seg_start, seg_end, seg_color, seg_label in _UNII_SEGMENTS:
                    bar = pg.PlotCurveItem(
                        [seg_start, seg_end],
                        [floor, floor],
                        pen=pg.mkPen(seg_color, width=4),
                    )
                    bar.setZValue(10)
                    pw.addItem(bar)
                # Vertical boundary lines at UNII transitions
                for boundary_mhz in (6425, 6525, 6875):
                    vline = pg.InfiniteLine(
                        pos=boundary_mhz,
                        angle=90,
                        pen=pg.mkPen(
                            QColor(180, 140, 60, 90),
                            width=1,
                            style=Qt.PenStyle.DashLine,
                        ),
                    )
                    pw.addItem(vline)

            pw.setXRange(xmin, xmax, padding=0.01)
            pw.setYRange(floor, CHAN_DBM_CEIL, padding=0.02)

        self._apply_highlight()


# ─────────────────────────────────────────────────────────────────────────────
# Signal History Graph
# ─────────────────────────────────────────────────────────────────────────────


class SignalHistoryWidget(QWidget):
    """Time-series plot of signal strength per BSSID."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot = PlotWidget(axisItems={"left": DbmAxisItem(orientation="left")})
        self._plot.setBackground("#0d1117")
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel("left", "Signal (dBm)", color="#8a96b0", size="10pt")
        self._plot.setLabel("bottom", "Time (s ago)", color="#8a96b0", size="10pt")
        self._plot.getAxis("bottom").setTextPen("#8a96b0")
        self._plot.setMenuEnabled(True)
        self._plot.getViewBox().setMouseEnabled(x=True, y=True)
        self._plot.setYRange(CHAN_DBM_FLOOR, CHAN_DBM_CEIL, padding=0.02)
        y_ticks = [(v, str(v)) for v in range(CHAN_DBM_FLOOR, CHAN_DBM_CEIL + 1, 10)]
        self._plot.getAxis("left").setTicks([y_ticks])
        layout.addWidget(self._plot)

        # legend
        self._legend = self._plot.addLegend(offset=(10, 10))

        self._history: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=HISTORY_SECONDS)
        )
        self._curves: Dict[str, pg.PlotDataItem] = {}
        self._ssid_colors: Dict[str, QColor] = {}
        self._ssid_map: Dict[str, str] = {}  # bssid → ssid
        self._t0 = time.time()
        self._filter_bssids: Optional[set] = None  # None = show all

    def set_theme(self, bg: str, fg: str):
        self._plot.setBackground(bg)
        self._plot.setLabel("left", "Signal (dBm)", color=fg, size="10pt")
        self._plot.setLabel("bottom", "Time (s ago)", color=fg, size="10pt")
        for _ax in ("left", "bottom"):
            self._plot.getAxis(_ax).setTextPen(fg)
            self._plot.getAxis(_ax).setPen(fg)

    def set_ssid_colors(self, colors: Dict[str, QColor]):
        self._ssid_colors = colors

    def filter_bssids(self, bssids: Optional[set]):
        self._filter_bssids = bssids

    def push(self, aps: List[AccessPoint]):
        now = time.time()
        elapsed = now - self._t0
        for ap in aps:
            self._ssid_map[ap.bssid] = ap.display_ssid
            self._history[ap.bssid].append((elapsed, ap.dbm))  # store dBm
        self._redraw(elapsed)

    def _redraw(self, now_t: float):
        visible_bssids = set(self._history.keys())
        if self._filter_bssids is not None:
            visible_bssids &= self._filter_bssids

        # Remove stale curves
        for bssid in list(self._curves.keys()):
            if bssid not in visible_bssids:
                self._plot.removeItem(self._curves.pop(bssid))

        for bssid in visible_bssids:
            pts = list(self._history[bssid])
            if len(pts) < 2:
                continue
            ts = np.array([now_t - p[0] for p in pts])  # seconds ago (positive = older)
            ss = np.array([p[1] for p in pts])
            # Flip so most recent is on the right
            ts = -ts  # negative = past

            ssid = self._ssid_map.get(bssid, bssid)
            color = self._ssid_colors.get(ssid, QColor("#888888"))

            if bssid not in self._curves:
                pen = mkPen(color=color, width=2)
                curve = self._plot.plot(ts, ss, pen=pen, name=f"{ssid} ({bssid[-5:]})")
                self._curves[bssid] = curve
            else:
                self._curves[bssid].setData(ts, ss)


# ─────────────────────────────────────────────────────────────────────────────
# Monitor Mode — Packet Capture
# ─────────────────────────────────────────────────────────────────────────────


def _detect_wifi_interfaces() -> List[Dict[str, str]]:
    """
    Parse `iw dev` output and return a list of dicts:
      { name, phy, type, connected_ssid }
    connected_ssid is "" when the interface is not associated.
    """
    try:
        out = subprocess.run(
            ["iw", "dev"], capture_output=True, text=True, timeout=4
        ).stdout
    except Exception:
        return []

    interfaces: List[Dict[str, str]] = []
    current_phy = ""
    current_if: Dict[str, str] = {}

    for raw in out.splitlines():
        line = raw.strip()
        if line.startswith("phy#"):
            current_phy = line
        elif line.startswith("Interface "):
            current_if = {
                "name": line.split()[1],
                "phy": current_phy,
                "type": "",
                "connected_ssid": "",
            }
            interfaces.append(current_if)
        elif line.startswith("type ") and current_if:
            current_if["type"] = line.split(None, 1)[1]
        elif line.startswith("ssid ") and current_if:
            current_if["connected_ssid"] = line.split(None, 1)[1]

    # Only managed (station) interfaces — skip existing monitor interfaces
    return [i for i in interfaces if i["type"] in ("managed", "AP", "")]


def _iw_chan_arg(channel: int, band: str) -> List[str]:
    """
    Return the `iw set channel` argument list for the given channel.
    For 6 GHz we pass the frequency directly; for 2.4/5 GHz the channel number.
    """
    if band == "6 GHz":
        freq = CH6.get(channel, 0)
        if freq:
            return [str(freq)]
    return [str(channel)]


_MONITOR_MASTER_TMPL = """\
#!/bin/bash
IFACE={iface}
MON=mon0
OUTPUT={output}
PID_FILE={pid_file}

# ── SETUP ──────────────────────────────────────────────
{nm_stop}ip link set "$IFACE" down
iw dev "$IFACE" interface add "$MON" type monitor 2>/dev/null || true
ip link set "$MON" up
iw dev "$MON" set channel {chan_args}
echo "WAVESCOPE_SETUP_OK"

# ── CAPTURE ─────────────────────────────────────────
tcpdump -i "$MON" -e -nn -U -w "$OUTPUT" &
TDPID=$!
echo "$TDPID" > "$PID_FILE"
wait "$TDPID"
rm -f "$PID_FILE" 2>/dev/null
echo "WAVESCOPE_CAPTURE_DONE"

# ── TEARDOWN ────────────────────────────────────────
ip link set "$MON" down 2>/dev/null || true
iw dev "$MON" del 2>/dev/null || true
ip link set "$IFACE" up 2>/dev/null || true
{nm_start}echo "WAVESCOPE_TEARDOWN_OK"
"""

_MONITOR_CLEANUP_TMPL = """\
#!/bin/bash
# Emergency cleanup — kills tcpdump by saved PID, tears down mon0, restores wifi
IFACE={iface}
MON=mon0
PID_FILE={pid_file}

if [[ -f "$PID_FILE" ]]; then
    TDPID=$(cat "$PID_FILE")
    kill -INT "$TDPID" 2>/dev/null || true
    sleep 1
    kill -KILL "$TDPID" 2>/dev/null || true
    rm -f "$PID_FILE"
fi
ip link set "$MON" down 2>/dev/null || true
iw dev "$MON" del 2>/dev/null || true
ip link set "$IFACE" up 2>/dev/null || true
{nm_start}echo "WAVESCOPE_CLEANUP_OK"
"""

_MANAGED_CAPTURE_TMPL = """\
#!/bin/bash
# Managed-mode capture — WiFi stays connected; only your machine's traffic.
IFACE={iface}
OUTPUT={output}
PID_FILE={pid_file}

tcpdump -i "$IFACE" -e -nn -U -w "$OUTPUT" &
TDPID=$!
echo "$TDPID" > "$PID_FILE"
echo "WAVESCOPE_CAPTURE_OK"
wait "$TDPID"
rm -f "$PID_FILE" 2>/dev/null
echo "WAVESCOPE_CAPTURE_DONE"
"""

_MANAGED_CLEANUP_TMPL = """\
#!/bin/bash
# Clean stop — sends SIGINT to tcpdump so it flushes the pcap properly.
PID_FILE={pid_file}

if [[ -f "$PID_FILE" ]]; then
    TDPID=$(cat "$PID_FILE")
    kill -INT "$TDPID" 2>/dev/null || true
    sleep 1
    kill -KILL "$TDPID" 2>/dev/null || true
    rm -f "$PID_FILE"
fi
echo "WAVESCOPE_CLEANUP_OK"
"""

class CaptureTypeDialog(QDialog):
    """Small picker — user chooses between Monitor Mode and Managed Mode capture."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("\U0001f4e1  Packet Capture")
        self.setModal(True)
        self.setMinimumWidth(580)
        self._choice = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 18, 20, 18)

        title = QLabel("Choose capture type")
        title.setStyleSheet("font-size:13pt; font-weight:bold; color:#e0e0e0;")
        layout.addWidget(title)

        note = QLabel("Both modes require a root password prompt (pkexec / Polkit).")
        note.setStyleSheet("font-size:9pt; color:#888;")
        layout.addWidget(note)
        layout.addSpacing(4)

        btn_mon = self._make_card(
            "\U0001f4e1  Monitor Mode",
            "True 802.11 over-the-air capture — all devices, all frames",
            "Disconnects your WiFi and creates a raw monitor interface (mon0).\n"
            "Captures ALL frames on the chosen channel — beacons, probes, data\n"
            "from every nearby device. Best for deep wireless analysis.",
            "#1a3050", "#1e4a80",
        )
        btn_mon.clicked.connect(lambda: self._pick("monitor"))
        layout.addWidget(btn_mon)

        btn_mgd = self._make_card(
            "\U0001f310  Managed Mode",
            "Capture your own machine's traffic — WiFi stays connected",
            "Keeps your WiFi connection intact. Captures only traffic\n"
            "to/from this machine on the current network.\n"
            "Ideal for debugging your own connection without losing internet.",
            "#1a3a1a", "#1e5a22",
        )
        btn_mgd.clicked.connect(lambda: self._pick("managed"))
        layout.addWidget(btn_mgd)

        layout.addSpacing(4)
        cancel = QPushButton("Cancel")
        cancel.setFixedWidth(90)
        cancel.clicked.connect(self.reject)
        hbox = QHBoxLayout()
        hbox.addStretch()
        hbox.addWidget(cancel)
        layout.addLayout(hbox)

    def _make_card(self, title, subtitle, body, bg, hover):
        # Use a QFrame subclass — embedding QLabels inside QPushButton
        # makes click detection unreliable in Qt6.
        class _Card(QFrame):
            clicked = pyqtSignal()

            def __init__(self, bg, hover):
                super().__init__()
                self._bg    = bg
                self._hover = hover
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                self.setMinimumHeight(110)
                self._apply_style(bg)

            def _apply_style(self, color):
                self.setStyleSheet(
                    f"QFrame {{ background:{color}; border:1px solid #334;"
                    f" border-radius:8px; }}"
                )

            def enterEvent(self, _e):
                self._apply_style(self._hover)

            def leaveEvent(self, _e):
                self._apply_style(self._bg)

            def mousePressEvent(self, e):
                if e.button() == Qt.MouseButton.LeftButton:
                    self.clicked.emit()

        card = _Card(bg, hover)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.setSpacing(3)
        lbl_t = QLabel(title)
        lbl_t.setStyleSheet("font-size:12pt; font-weight:bold; color:#ffffff;")
        lbl_s = QLabel(subtitle)
        lbl_s.setStyleSheet("font-size:9.5pt; color:#aad4ff; font-style:italic;")
        lbl_b = QLabel(body)
        lbl_b.setStyleSheet("font-size:9pt; color:#b0c8d8; margin-top:4px;")
        lbl_b.setWordWrap(True)
        for lbl in (lbl_t, lbl_s, lbl_b):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner.addWidget(lbl_t)
        inner.addWidget(lbl_s)
        inner.addWidget(lbl_b)
        return card

    def _pick(self, choice: str):
        self._choice = choice
        self.accept()

    def chosen(self):
        return self._choice


class MonitorModeWindow(QDialog):
    """
    Packet-capture window using a temporary monitor-mode interface (mon0).
    Requires root via pkexec / Polkit.
    """

    # Internal capture states
    _ST_IDLE = "idle"
    _ST_SETUP = "setup"
    _ST_CAPTURE = "capture"
    _ST_TEARDOWN = "teardown"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📡  Monitor Mode  —  Packet Capture")
        self.setMinimumSize(620, 640)
        self.setModal(False)

        self._state = self._ST_IDLE
        self._proc = None
        self._cleanup_proc = None  # second pkexec for stop/teardown
        self._master_script = ""  # path to single temp script
        self._pid_file = ""  # tcpdump PID written here by master script
        self._stdout_buf = ""  # partial-line buffer for stdout
        self._start_time = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._nm_was_running = False

        self._build_ui()
        self._populate_interfaces()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 14, 16, 14)

        # ── Warning banner ────────────────────────────────────────────────
        warn = QLabel(
            "⚠  Monitor mode requires <b>root privileges</b>.<br>"
            "The selected interface will be <b>temporarily disconnected</b> from WiFi "
            "while capture is running."
        )
        warn.setWordWrap(True)
        warn.setTextFormat(Qt.TextFormat.RichText)
        warn.setStyleSheet(
            "QLabel { background:#2a1800; color:#ffcc66; border:1px solid #a06010;"
            " border-radius:5px; padding:8px 12px; }"
        )
        layout.addWidget(warn)

        # ── Interface / channel configuration ────────────────────────────
        cfg = QFrame()
        cfg.setFrameShape(QFrame.Shape.StyledPanel)
        cfg_layout = QFormLayout(cfg)
        cfg_layout.setVerticalSpacing(8)
        cfg_layout.setHorizontalSpacing(14)
        cfg_layout.setContentsMargins(12, 10, 12, 10)

        self._iface_combo = QComboBox()
        self._iface_combo.setMinimumWidth(220)
        self._iface_combo.currentIndexChanged.connect(self._on_iface_change)
        cfg_layout.addRow("Interface:", self._iface_combo)

        self._band_sel = QComboBox()
        self._band_sel.addItems(["2.4 GHz", "5 GHz", "6 GHz"])
        self._band_sel.currentTextChanged.connect(self._on_band_sel)
        cfg_layout.addRow("Band:", self._band_sel)

        self._chan_combo = QComboBox()
        self._chan_combo.setMinimumWidth(180)
        cfg_layout.addRow("Channel:", self._chan_combo)

        # Output file row
        out_row = QWidget()
        out_hl = QHBoxLayout(out_row)
        out_hl.setContentsMargins(0, 0, 0, 0)
        out_hl.setSpacing(6)
        self._out_edit = QLineEdit()
        default_out = str(Path.home() / "capture.pcap")
        self._out_edit.setText(default_out)
        self._out_edit.setPlaceholderText("/path/to/output.pcap")
        out_hl.addWidget(self._out_edit)
        btn_browse = QPushButton("Browse…")
        btn_browse.setMaximumWidth(80)
        btn_browse.clicked.connect(self._on_browse)
        out_hl.addWidget(btn_browse)
        cfg_layout.addRow("Output file:", out_row)

        layout.addWidget(cfg)

        # ── Start / Stop button ───────────────────────────────────────────
        self._btn_start = QPushButton("▶  Start Capture")
        self._btn_start.setMinimumHeight(38)
        self._btn_start.setStyleSheet(
            "QPushButton { background:#1a5c2a; color:#ccffcc; border:none;"
            " border-radius:5px; font-size:11pt; font-weight:bold; }"
            "QPushButton:hover { background:#226b33; }"
            "QPushButton:disabled { background:#1a2210; color:#446644; }"
        )
        self._btn_start.clicked.connect(self._on_start_stop)
        layout.addWidget(self._btn_start)

        # ── Status row ────────────────────────────────────────────────────
        stats_row = QHBoxLayout()
        self._lbl_state = QLabel("Idle")
        self._lbl_state.setStyleSheet("font-weight:bold; color:#7eb8f7;")
        self._lbl_elapsed = QLabel("00:00")
        self._lbl_elapsed.setStyleSheet("color:#a9b4cc; font-family:monospace;")
        self._lbl_size = QLabel("")
        self._lbl_size.setStyleSheet("color:#a9b4cc;")
        stats_row.addWidget(self._lbl_state)
        stats_row.addStretch()
        stats_row.addWidget(QLabel("Elapsed: "))
        stats_row.addWidget(self._lbl_elapsed)
        stats_row.addWidget(QLabel("   File: "))
        stats_row.addWidget(self._lbl_size)
        layout.addLayout(stats_row)

        # ── Log area ──────────────────────────────────────────────────────
        from PyQt6.QtWidgets import QPlainTextEdit

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        self._log.setStyleSheet(
            "QPlainTextEdit { background:#090d14; color:#8fa8c0;"
            " font-family:monospace; font-size:9pt; border-radius:4px; }"
        )
        layout.addWidget(self._log)

        # Populate band → channel on start
        self._on_band_sel(self._band_sel.currentText())

    # ── Populate helpers ──────────────────────────────────────────────────

    def _populate_interfaces(self):
        self._ifaces = _detect_wifi_interfaces()
        self._iface_combo.clear()
        if not self._ifaces:
            self._iface_combo.addItem("No WiFi interfaces found")
            self._btn_start.setEnabled(False)
            return
        for ifc in self._ifaces:
            label = ifc["name"]
            if ifc["connected_ssid"]:
                label += f"  (connected: {ifc['connected_ssid']})"
            self._iface_combo.addItem(label, ifc["name"])

    def _on_iface_change(self, _idx):
        pass  # could refresh band capabilities in future

    def _on_band_sel(self, band: str):
        self._chan_combo.clear()
        if band == "2.4 GHz":
            src = CH24
        elif band == "5 GHz":
            src = CH5
        else:
            src = CH6
        for ch, freq in sorted(src.items(), key=lambda x: x[1]):
            self._chan_combo.addItem(f"Ch {ch}  ({freq} MHz)", ch)

    def _on_browse(self):
        from PyQt6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Choose output file",
            str(Path.home()),
            "PCAP files (*.pcap);;All files (*)",
        )
        if path:
            if not path.endswith(".pcap"):
                path += ".pcap"
            self._out_edit.setText(path)

    # ── Capture control ───────────────────────────────────────────────────

    def _on_start_stop(self):
        if self._state == self._ST_IDLE:
            self._start_capture()
        else:
            self._request_stop()

    def _start_capture(self):
        iface = self._iface_combo.currentData()
        if not iface:
            self._log_line("⚠  No interface selected.")
            return
        channel = self._chan_combo.currentData()
        if not channel:
            self._log_line("⚠  No channel selected.")
            return
        output = self._out_edit.text().strip()
        if not output:
            self._log_line("⚠  No output file specified.")
            return

        band = self._band_sel.currentText()
        self._iface_name = iface
        self._output_path = output
        self._channel = channel
        self._band = band

        # Check & record if NetworkManager is running so we restore it
        nm_check = subprocess.run(
            ["systemctl", "is-active", "NetworkManager"], capture_output=True, text=True
        )
        self._nm_was_running = nm_check.returncode == 0

        self._log_line(f"Interface : {iface}")
        self._log_line(f"Band/Chan : {band}  ch {channel}")
        self._log_line(f"Output    : {output}")
        self._log_line(f"NM active : {self._nm_was_running}")
        self._log_line("─" * 50)

        self._run_master()

    def _run_master(self):
        """Build and launch the single combined pkexec script."""
        self._set_state(self._ST_SETUP, "Setting up monitor interface…")

        chan_args = " ".join(_iw_chan_arg(self._channel, self._band))
        nm_stop = "systemctl stop NetworkManager\n" if self._nm_was_running else ""
        nm_start = "systemctl start NetworkManager\n" if self._nm_was_running else ""

        import tempfile as _tf

        self._pid_file = _tf.mktemp(prefix="wavescope_tdpid_", suffix=".pid")
        script_body = _MONITOR_MASTER_TMPL.format(
            iface=self._iface_name,
            output=self._output_path,
            chan_args=chan_args,
            nm_stop=nm_stop,
            nm_start=nm_start,
            pid_file=self._pid_file,
        )
        self._master_script = self._write_temp_script(script_body)
        self._stdout_buf = ""

        self._proc = self._make_process()
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(self._on_proc_finished)
        self._proc.start("pkexec", ["bash", self._master_script])
        self._log_line("▶  Starting (Polkit authentication may appear…)")

    def _on_stdout(self):
        self._stdout_buf += bytes(self._proc.readAllStandardOutput()).decode(
            errors="replace"
        )
        while "\n" in self._stdout_buf:
            line, self._stdout_buf = self._stdout_buf.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            if line == "WAVESCOPE_SETUP_OK":
                self._log_line("✓  Monitor interface mon0 ready.")
                self._set_state(self._ST_CAPTURE, "Capturing…")
                self._start_time = time.monotonic()
                self._timer.start()
                self._log_line("▶  tcpdump running — click Stop to end capture.")
            elif line == "WAVESCOPE_CAPTURE_DONE":
                self._timer.stop()
                self._set_state(self._ST_TEARDOWN, "Restoring interface…")
                self._log_line("▶  Restoring interface and NetworkManager…")
            elif line == "WAVESCOPE_TEARDOWN_OK":
                self._log_line("✓  Interface and NetworkManager restored.")
            else:
                self._log_line(f"  {line}")

    def _on_stderr(self):
        data = bytes(self._proc.readAllStandardError()).decode(errors="replace")
        for line in data.splitlines():
            s = line.strip()
            if s:
                self._log_line(f"  {s}")

    def _on_proc_finished(self, exit_code: int, _exit_status):
        self._timer.stop()
        self._stdout_buf += bytes(self._proc.readAllStandardOutput()).decode(
            errors="replace"
        )
        for line in self._stdout_buf.splitlines():
            ln = line.strip()
            if ln and not ln.startswith("WAVESCOPE_"):
                self._log_line(f"  {ln}")
        self._stdout_buf = ""

        if exit_code != 0 and self._state == self._ST_SETUP:
            self._log_line(
                f"✗  Setup/auth failed (exit {exit_code}). "
                "Check pkexec and iw are installed."
            )

        try:
            sz = os.path.getsize(self._output_path)
            self._log_line(f"📁  Saved {sz / 1024:.1f} KB → {self._output_path}")
        except OSError:
            pass

        # Only reset UI if cleanup hasn't already done it
        if self._state != self._ST_IDLE:
            self._reset_ui_to_idle("Idle — capture complete")
        try:
            if self._master_script:
                os.unlink(self._master_script)
                self._master_script = ""
        except OSError:
            pass
        try:
            if self._pid_file and os.path.exists(self._pid_file):
                os.unlink(self._pid_file)
                self._pid_file = ""
        except OSError:
            pass

    def _reset_ui_to_idle(self, label: str = "Idle"):
        self._set_state(self._ST_IDLE, label)
        self._btn_start.setText("▶  Start Capture")
        self._btn_start.setStyleSheet(
            "QPushButton { background:#1a5c2a; color:#ccffcc; border:none;"
            " border-radius:5px; font-size:11pt; font-weight:bold; }"
            "QPushButton:hover { background:#226b33; }"
            "QPushButton:disabled { background:#1a2210; color:#446644; }"
        )
        self._btn_start.setEnabled(True)
        try:
            sz = os.path.getsize(self._output_path)
            self._log_line(f"📁  Saved {sz / 1024:.1f} KB → {self._output_path}")
        except OSError:
            pass

    def _request_stop(self):
        if self._state in (self._ST_CAPTURE, self._ST_SETUP) and self._proc:
            self._btn_start.setEnabled(False)
            self._btn_start.setText("⏳  Stopping…")
            self._log_line(
                "⏹  Stopping — launching cleanup (a password prompt may appear)…"
            )
            self._set_state(self._ST_TEARDOWN, "Stopping…")
            self._run_cleanup()
            # Last-resort force-kill if cleanup pkexec itself hangs
            QTimer.singleShot(20000, self._force_kill_capture)

    def _run_cleanup(self):
        nm_start = "systemctl start NetworkManager\n" if self._nm_was_running else ""
        script_body = _MONITOR_CLEANUP_TMPL.format(
            iface=self._iface_name,
            pid_file=self._pid_file,
            nm_start=nm_start,
        )
        cleanup_path = self._write_temp_script(script_body)
        self._cleanup_proc = self._make_process()
        self._cleanup_proc.readyReadStandardOutput.connect(self._on_cleanup_stdout)
        self._cleanup_proc.readyReadStandardError.connect(self._on_cleanup_stderr)
        self._cleanup_proc.finished.connect(
            lambda code, _s, p=cleanup_path: self._on_cleanup_finished(code, p)
        )
        self._cleanup_proc.start("pkexec", ["bash", cleanup_path])
        self._log_line("▶  Cleanup running…")

    def _on_cleanup_stdout(self):
        data = bytes(self._cleanup_proc.readAllStandardOutput()).decode(
            errors="replace"
        )
        for line in data.splitlines():
            ln = line.strip()
            if ln == "WAVESCOPE_CLEANUP_OK":
                self._log_line("✓  Interface and NetworkManager restored.")
            elif ln:
                self._log_line(f"  {ln}")

    def _on_cleanup_stderr(self):
        data = bytes(self._cleanup_proc.readAllStandardError()).decode(errors="replace")
        for line in data.splitlines():
            s = line.strip()
            if s:
                self._log_line(f"  {s}")

    def _on_cleanup_finished(self, exit_code: int, cleanup_path: str):
        try:
            os.unlink(cleanup_path)
        except OSError:
            pass
        self._cleanup_proc = None
        if exit_code != 0:
            self._log_line(f"⚠  Cleanup exited with code {exit_code}.")
        # Reset UI — master process may still be exiting but that's fine
        if self._state != self._ST_IDLE:
            self._reset_ui_to_idle("Idle — capture stopped")

    def _force_kill_capture(self):
        from PyQt6.QtCore import QProcess

        if (
            self._state != self._ST_IDLE
            and self._proc
            and self._proc.state() != QProcess.ProcessState.NotRunning
        ):
            self._log_line(
                "⚠  Still running after 20 s — force-killing master process…"
            )
            self._proc.kill()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _make_process(self) -> "QProcess":
        from PyQt6.QtCore import QProcess

        p = QProcess(self)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        return p

    def _write_temp_script(self, body: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".sh", prefix="wavescope_")
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
        os.chmod(
            path,
            stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
        )
        return path

    def _set_state(self, state: str, label: str):
        self._state = state
        self._lbl_state.setText(label)
        idle = state == self._ST_IDLE
        self._iface_combo.setEnabled(idle)
        self._band_sel.setEnabled(idle)
        self._chan_combo.setEnabled(idle)
        self._out_edit.setEnabled(idle)
        if state == self._ST_CAPTURE:
            self._btn_start.setText("⏹  Stop Capture")
            self._btn_start.setStyleSheet(
                "QPushButton { background:#6b1a1a; color:#ffcccc; border:none;"
                " border-radius:5px; font-size:11pt; font-weight:bold; }"
                "QPushButton:hover { background:#7f2020; }"
            )
            self._btn_start.setEnabled(True)
        elif state in (self._ST_SETUP, self._ST_TEARDOWN):
            self._btn_start.setText("⏹  Stop Capture")
            self._btn_start.setEnabled(state == self._ST_SETUP)
        elif idle:
            self._btn_start.setEnabled(True)

    def _tick(self):
        elapsed = int(time.monotonic() - self._start_time)
        m, s = divmod(elapsed, 60)
        self._lbl_elapsed.setText(f"{m:02d}:{s:02d}")
        try:
            sz = os.path.getsize(self._output_path)
            if sz < 1024 * 1024:
                self._lbl_size.setText(f"{sz / 1024:.1f} KB")
            else:
                self._lbl_size.setText(f"{sz / 1024 / 1024:.2f} MB")
        except OSError:
            self._lbl_size.setText("—")

    def _log_line(self, text: str):
        self._log.appendPlainText(text)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event):
        if self._state != self._ST_IDLE:
            from PyQt6.QtWidgets import QMessageBox

            r = QMessageBox.question(
                self,
                "Capture in progress",
                "A capture is running. Stop it and restore the interface before closing?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if r == QMessageBox.StandardButton.Yes:
                self._request_stop()
                event.ignore()  # re-close after teardown finishes
                # Reconnect to close after teardown
                return
            else:
                event.ignore()
                return
        event.accept()


class ManagedCaptureWindow(QDialog):
    """
    Managed-mode packet capture — WiFi stays connected.
    Only captures traffic to/from this machine. Requires root via pkexec.
    """

    _ST_IDLE    = "idle"
    _ST_CAPTURE = "capture"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("\U0001f310  Managed Capture  \u2014  Packet Capture")
        self.setMinimumSize(560, 540)
        self.setModal(False)

        self._state          = self._ST_IDLE
        self._proc           = None
        self._cleanup_proc   = None
        self._capture_script = ""
        self._pid_file       = ""
        self._stdout_buf     = ""
        self._start_time     = 0.0
        self._timer          = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._iface_name     = ""
        self._output_path    = ""

        self._build_ui()
        self._populate_interfaces()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 14, 16, 14)

        banner = QLabel(
            "\u2139  Your WiFi connection stays active. Only traffic to/from "
            "this machine is captured."
        )
        banner.setWordWrap(True)
        banner.setStyleSheet(
            "background:#1e2e10; color:#cceeaa; padding:8px 10px;"
            " border-radius:5px; font-size:9pt;"
        )
        layout.addWidget(banner)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._iface_combo = QComboBox()
        form.addRow("Interface:", self._iface_combo)

        out_row = QHBoxLayout()
        self._out_edit = QLineEdit(
            os.path.expanduser(f"~/Desktop/managed_{int(time.time())}.pcap")
        )
        btn_browse = QPushButton("Browse\u2026")
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self._out_edit)
        out_row.addWidget(btn_browse)
        form.addRow("Output file:", out_row)
        layout.addLayout(form)

        status_row = QHBoxLayout()
        self._lbl_state   = QLabel("Idle")
        self._lbl_elapsed = QLabel("00:00")
        self._lbl_size    = QLabel("File:  0 KB")
        self._lbl_state.setStyleSheet("color:#88bb88; font-weight:bold;")
        status_row.addWidget(self._lbl_state)
        status_row.addStretch()
        status_row.addWidget(QLabel("Elapsed:"))
        status_row.addWidget(self._lbl_elapsed)
        status_row.addSpacing(12)
        status_row.addWidget(self._lbl_size)
        layout.addLayout(status_row)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            "background:#0e1a0e; color:#a0d8a0; font-family:monospace;"
            " font-size:9pt; border-radius:4px;"
        )
        layout.addWidget(self._log, 1)

        self._btn_start = QPushButton("\u25b6  Start Capture")
        self._btn_start.setMinimumHeight(42)
        self._btn_start.setStyleSheet(
            "QPushButton { background:#1a5c2a; color:#ccffcc; border:none;"
            " border-radius:5px; font-size:11pt; font-weight:bold; }"
            "QPushButton:hover { background:#226b33; }"
            "QPushButton:disabled { background:#1a2210; color:#446644; }"
        )
        self._btn_start.clicked.connect(self._on_btn)
        layout.addWidget(self._btn_start)

    def _populate_interfaces(self):
        ifaces = _detect_wifi_interfaces()
        self._iface_combo.clear()
        if not ifaces:
            self._iface_combo.addItem("No WiFi interfaces found")
            self._btn_start.setEnabled(False)
            return
        for ifc in ifaces:
            label = ifc["name"]
            if ifc["connected_ssid"]:
                label += f"  (connected: {ifc['connected_ssid']})"
            self._iface_combo.addItem(label, ifc["name"])

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Capture File",
            os.path.expanduser("~/Desktop"),
            "PCAP files (*.pcap);;All files (*)",
        )
        if path:
            self._out_edit.setText(path)

    # ── Capture lifecycle ─────────────────────────────────────────────────

    def _on_btn(self):
        if self._state == self._ST_IDLE:
            self._start_capture()
        else:
            self._request_stop()

    def _start_capture(self):
        iface  = (self._iface_combo.currentData() or self._iface_combo.currentText()).strip()
        output = self._out_edit.text().strip()
        if not iface:
            QMessageBox.warning(self, "No Interface", "Select a WiFi interface.")
            return
        if not output:
            QMessageBox.warning(self, "No Output", "Choose an output file.")
            return
        self._iface_name  = iface
        self._output_path = output
        self._log.clear()
        self._log_line(f"Interface : {iface}")
        self._log_line(f"Output    : {output}")
        self._log_line("\u2500" * 50)
        self._run_capture()

    def _run_capture(self):
        import tempfile as _tf
        self._pid_file = _tf.mktemp(prefix="wavescope_tdpid_", suffix=".pid")
        script_body = _MANAGED_CAPTURE_TMPL.format(
            iface=self._iface_name,
            output=self._output_path,
            pid_file=self._pid_file,
        )
        self._capture_script = self._write_temp_script(script_body)
        self._stdout_buf = ""
        self._proc = self._make_process()
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(self._on_proc_finished)
        self._proc.start("pkexec", ["bash", self._capture_script])
        self._set_state(self._ST_CAPTURE, "Starting\u2026")
        self._btn_start.setText("\u23f9  Stop Capture")
        self._btn_start.setStyleSheet(
            "QPushButton { background:#6b1a1a; color:#ffcccc; border:none;"
            " border-radius:5px; font-size:11pt; font-weight:bold; }"
            "QPushButton:hover { background:#7f2020; }"
        )
        self._log_line("\u25b6  Starting (Polkit authentication may appear\u2026)")

    def _on_stdout(self):
        self._stdout_buf += bytes(self._proc.readAllStandardOutput()).decode(errors="replace")
        while "\n" in self._stdout_buf:
            line, self._stdout_buf = self._stdout_buf.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            if line == "WAVESCOPE_CAPTURE_OK":
                self._log_line("\u2713  tcpdump running \u2014 WiFi connection is intact.")
                self._set_state(self._ST_CAPTURE, "Capturing\u2026")
                self._start_time = time.monotonic()
                self._timer.start()
                self._log_line("\u25b6  Click Stop to end capture.")
            elif line == "WAVESCOPE_CAPTURE_DONE":
                self._log_line("\u2713  Capture complete.")
            else:
                self._log_line(f"  {line}")

    def _on_stderr(self):
        data = bytes(self._proc.readAllStandardError()).decode(errors="replace")
        for line in data.splitlines():
            s = line.strip()
            if s:
                self._log_line(f"  {s}")

    def _on_proc_finished(self, exit_code: int, _exit_status):
        self._timer.stop()
        self._stdout_buf += bytes(self._proc.readAllStandardOutput()).decode(errors="replace")
        for line in self._stdout_buf.splitlines():
            ln = line.strip()
            if ln and not ln.startswith("WAVESCOPE_"):
                self._log_line(f"  {ln}")
        self._stdout_buf = ""
        if exit_code != 0 and self._state == self._ST_CAPTURE:
            self._log_line(
                f"\u2717  Capture failed (exit {exit_code}). Check pkexec is available."
            )
        if self._state != self._ST_IDLE:
            self._reset_ui_to_idle("Idle \u2014 capture complete")
        self._cleanup_temps()

    def _request_stop(self):
        if self._state == self._ST_CAPTURE and self._proc:
            self._btn_start.setEnabled(False)
            self._btn_start.setText("\u23f3  Stopping\u2026")
            self._log_line(
                "\u23f9  Stopping \u2014 launching cleanup (a password prompt may appear)\u2026"
            )
            self._run_cleanup()
            QTimer.singleShot(20000, self._force_kill)

    def _run_cleanup(self):
        script_body = _MANAGED_CLEANUP_TMPL.format(pid_file=self._pid_file)
        cleanup_path = self._write_temp_script(script_body)
        self._cleanup_proc = self._make_process()
        self._cleanup_proc.readyReadStandardOutput.connect(self._on_cleanup_stdout)
        self._cleanup_proc.readyReadStandardError.connect(self._on_cleanup_stderr)
        self._cleanup_proc.finished.connect(
            lambda code, _s, p=cleanup_path: self._on_cleanup_finished(code, p)
        )
        self._cleanup_proc.start("pkexec", ["bash", cleanup_path])
        self._log_line("\u25b6  Cleanup running\u2026")

    def _on_cleanup_stdout(self):
        data = bytes(self._cleanup_proc.readAllStandardOutput()).decode(errors="replace")
        for line in data.splitlines():
            ln = line.strip()
            if ln == "WAVESCOPE_CLEANUP_OK":
                self._log_line("\u2713  Capture stopped cleanly.")
            elif ln:
                self._log_line(f"  {ln}")

    def _on_cleanup_stderr(self):
        data = bytes(self._cleanup_proc.readAllStandardError()).decode(errors="replace")
        for line in data.splitlines():
            s = line.strip()
            if s:
                self._log_line(f"  {s}")

    def _on_cleanup_finished(self, exit_code: int, cleanup_path: str):
        try:
            os.unlink(cleanup_path)
        except OSError:
            pass
        self._cleanup_proc = None
        if exit_code != 0:
            self._log_line(f"\u26a0  Cleanup exited with code {exit_code}.")
        if self._state != self._ST_IDLE:
            self._reset_ui_to_idle("Idle \u2014 capture stopped")
        self._cleanup_temps()

    def _force_kill(self):
        from PyQt6.QtCore import QProcess
        if (
            self._state != self._ST_IDLE
            and self._proc
            and self._proc.state() != QProcess.ProcessState.NotRunning
        ):
            self._log_line("\u26a0  Still running after 20 s \u2014 force-killing\u2026")
            self._proc.kill()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _reset_ui_to_idle(self, label: str = "Idle"):
        self._set_state(self._ST_IDLE, label)
        self._btn_start.setText("\u25b6  Start Capture")
        self._btn_start.setStyleSheet(
            "QPushButton { background:#1a5c2a; color:#ccffcc; border:none;"
            " border-radius:5px; font-size:11pt; font-weight:bold; }"
            "QPushButton:hover { background:#226b33; }"
            "QPushButton:disabled { background:#1a2210; color:#446644; }"
        )
        self._btn_start.setEnabled(True)
        try:
            sz = os.path.getsize(self._output_path)
            self._log_line(
                f"\U0001f4c1  Saved {sz / 1024:.1f} KB \u2192 {self._output_path}"
            )
        except OSError:
            pass

    def _cleanup_temps(self):
        for attr in ("_capture_script", "_pid_file"):
            path = getattr(self, attr, "")
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
                setattr(self, attr, "")

    def _set_state(self, state: str, label: str):
        self._state = state
        self._lbl_state.setText(label)
        idle = state == self._ST_IDLE
        self._iface_combo.setEnabled(idle)
        self._out_edit.setEnabled(idle)

    def _tick(self):
        elapsed = int(time.monotonic() - self._start_time)
        m, s = divmod(elapsed, 60)
        self._lbl_elapsed.setText(f"{m:02d}:{s:02d}")
        try:
            sz = os.path.getsize(self._output_path)
            if sz < 1024 * 1024:
                self._lbl_size.setText(f"File:  {sz / 1024:.1f} KB")
            else:
                self._lbl_size.setText(f"File:  {sz / 1024 / 1024:.2f} MB")
        except OSError:
            pass

    def _log_line(self, text: str):
        self._log.append(text)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _make_process(self):
        from PyQt6.QtCore import QProcess
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        return p

    def _write_temp_script(self, body: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".sh", prefix="wavescope_")
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
        os.chmod(
            path,
            stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
        )
        return path

    def closeEvent(self, event):
        if self._state != self._ST_IDLE:
            self._request_stop()
            event.ignore()
        else:
            event.accept()


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1400, 850)

        self._aps: List[AccessPoint] = []
        self._scanner = WiFiScanner(interval_sec=2)
        self._scanner.data_ready.connect(self._on_data)
        self._scanner.scan_error.connect(self._on_error)

        self._model = APTableModel()
        self._proxy = APFilterProxy()
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self._setup_ui()
        self._scanner.start()
        self._status("Scanning…")

        # First-run OUI prompt (only if IEEE JSON not yet downloaded)
        if not OUI_JSON_PATH.exists():
            QTimer.singleShot(800, self._prompt_oui_download)

    # ── UI Construction ───────────────────────────────────────────────────────

    def _setup_ui(self):
        # ── Toolbar ────────────────────────────────────────────────────────
        tb = QToolBar("Main Toolbar")
        tb.setMovable(False)
        tb.setIconSize(pg.QtCore.QSize(16, 16))
        self.addToolBar(tb)

        # Band filter
        tb.addWidget(QLabel("  Band: "))
        self._band_combo = QComboBox()
        self._band_combo.addItems(["All", "2.4 GHz", "5 GHz", "6 GHz"])
        self._band_combo.setMinimumWidth(90)
        self._band_combo.currentTextChanged.connect(self._on_band_change)
        tb.addWidget(self._band_combo)

        tb.addSeparator()

        # Search / filter
        tb.addWidget(QLabel("  Filter: "))
        self._search = QLineEdit()
        self._search.setPlaceholderText("SSID / MAC / vendor…")
        self._search.setMaximumWidth(200)
        self._search.textChanged.connect(self._proxy.set_text)
        tb.addWidget(self._search)

        tb.addSeparator()

        # Refresh interval
        tb.addWidget(QLabel("  Refresh: "))
        self._interval_combo = QComboBox()
        for s in REFRESH_INTERVALS:
            self._interval_combo.addItem(f"{s}s", s)
        self._interval_combo.setMinimumWidth(60)
        self._interval_combo.currentIndexChanged.connect(self._on_interval_change)
        tb.addWidget(self._interval_combo)

        tb.addSeparator()

        # Pause / resume
        self._btn_pause = QPushButton("⏸ Pause")
        self._btn_pause.setCheckable(True)
        self._btn_pause.toggled.connect(self._on_pause)
        tb.addWidget(self._btn_pause)

        tb.addSeparator()

        # OUI database button
        self._btn_oui = QPushButton("📖 Update OUI DB")
        self._btn_oui.setToolTip("Download / refresh the IEEE manufacturer database")
        self._btn_oui.clicked.connect(self._on_update_oui)
        tb.addWidget(self._btn_oui)

        tb.addSeparator()

        # Monitor mode button
        self._btn_monitor = QPushButton("📡 Packet Capture")
        self._btn_monitor.setToolTip(
            "Open packet-capture window (monitor mode)\n"
            "Requires root — will temporarily disconnect WiFi"
        )
        self._btn_monitor.setStyleSheet(
            "QPushButton { color:#7eb8f7; border:1px solid #2a4a70;"
            " border-radius:3px; padding:2px 8px; }"
            "QPushButton:hover { background:#1a2a40; }"
        )
        self._btn_monitor.clicked.connect(self._on_monitor_mode)
        tb.addWidget(self._btn_monitor)

        tb.addSeparator()

        # AP count label
        self._lbl_count = QLabel("  0 APs")
        tb.addWidget(self._lbl_count)

        tb.addSeparator()

        # Active column-filter badge + clear button
        self._lbl_filters = QLabel()
        self._lbl_filters.setStyleSheet("color:#f9a825; font-size:9pt;")
        self._lbl_filters.hide()
        tb.addWidget(self._lbl_filters)

        self._btn_clear_filters = QPushButton("✕ Clear filters")
        self._btn_clear_filters.setStyleSheet(
            "QPushButton{color:#f9a825;border:1px solid #f9a825;"
            "border-radius:3px;padding:1px 6px;font-size:9pt;}"
            "QPushButton:hover{background:#2a2010;}"
        )
        self._btn_clear_filters.clicked.connect(self._on_clear_col_filters)
        self._btn_clear_filters.hide()
        tb.addWidget(self._btn_clear_filters)

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        # Last updated
        self._lbl_updated = QLabel("  Last scan: —  ")
        tb.addWidget(self._lbl_updated)

        tb.addSeparator()

        # Theme
        tb.addWidget(QLabel("  Theme: "))
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["🌙 Dark", "☀ Light", "🖥 Auto"])
        self._theme_combo.setMinimumWidth(90)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_change)
        tb.addWidget(self._theme_combo)
        tb.addWidget(QLabel("  "))

        # ── Central widget ─────────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Vertical splitter: table on top, graphs on bottom
        splitter = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(splitter)

        # ── AP Table ───────────────────────────────────────────────────────
        self._table = QTableView()
        self._table.setModel(self._proxy)
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
            COL_INUSE: 26,
            COL_SSID: 180,
            COL_BSSID: 148,
            COL_MANUF: 180,
            COL_BAND: 72,
            COL_CHAN: 44,
            COL_FREQ: 86,
            COL_BW: 72,
            COL_SIG: 66,
            COL_DBM: 80,
            COL_RATE: 94,
            COL_SEC: 124,
            COL_MODE: 62,
            COL_GEN: 72,
            COL_UTIL: 72,
            COL_CLIENTS: 62,
            COL_KVR: 56,
        }
        for col, w in _col_widths.items():
            self._table.setColumnWidth(col, w)
        # Track columns the user has manually resized — skip auto-fit for those
        self._user_sized_cols: set = set()
        hdr.sectionResized.connect(self._on_col_resized)
        splitter.addWidget(self._table)

        # ── Graph tabs ─────────────────────────────────────────────────────
        tabs = QTabWidget()
        tabs.setMinimumHeight(280)
        splitter.addWidget(tabs)

        self._channel_graph = ChannelGraphWidget()
        self._channel_graph.ap_highlighted.connect(self._on_graph_highlight)
        tabs.addTab(self._channel_graph, "📡  Channel Graph")

        self._history_graph = SignalHistoryWidget()
        tabs.addTab(self._history_graph, "📈  Signal History")

        # Details tab (selected AP)
        self._details_widget = QWidget()
        self._details_widget.setContentsMargins(0, 0, 0, 0)
        _det_outer = QVBoxLayout(self._details_widget)
        _det_outer.setContentsMargins(0, 0, 0, 0)
        # SSID header label
        self._det_ssid = QLabel("Select an access point to view details.")
        self._det_ssid.setTextFormat(Qt.TextFormat.RichText)
        self._det_ssid.setContentsMargins(20, 16, 20, 4)
        _det_outer.addWidget(self._det_ssid)
        # Separator line
        _det_sep = QFrame()
        _det_sep.setFrameShape(QFrame.Shape.HLine)
        _det_sep.setFrameShadow(QFrame.Shadow.Sunken)
        _det_outer.addWidget(_det_sep)
        # Form rows
        _det_form_w = QWidget()
        self._det_form = QFormLayout(_det_form_w)
        self._det_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._det_form.setHorizontalSpacing(18)
        self._det_form.setVerticalSpacing(10)
        self._det_form.setContentsMargins(20, 12, 20, 20)
        _det_outer.addWidget(_det_form_w)
        _det_outer.addStretch()
        # pre-create value labels for each row
        _DET_ROWS = [
            "bssid",
            "manufacturer",
            "wifi_gen",
            "band",
            "channel",
            "frequency",
            "chan_width",
            "country",
            "signal",
            "max_rate",
            "security",
            "pmf",
            "chan_util",
            "clients",
            "roaming",
            "mode",
        ]
        _DET_LABELS = [
            "BSSID (MAC)",
            "Manufacturer",
            "WiFi Generation",
            "Band",
            "Channel",
            "Frequency",
            "Channel Width",
            "Country",
            "Signal",
            "Max Rate",
            "Security",
            "PMF (802.11w)",
            "Channel Util",
            "Clients",
            "Roaming (k/v/r)",
            "Mode",
        ]
        self._det_vals: dict[str, QLabel] = {}
        for key, lbl_text in zip(_DET_ROWS, _DET_LABELS):
            lbl = QLabel(f"<b>{lbl_text}</b>")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            val = QLabel("—")
            val.setTextFormat(Qt.TextFormat.RichText)
            val.setWordWrap(True)
            self._det_vals[key] = val
            self._det_form.addRow(lbl, val)
        _details_scroll = QScrollArea()
        _details_scroll.setWidgetResizable(True)
        _details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        _details_scroll.setWidget(self._details_widget)
        tabs.addTab(_details_scroll, "ℹ️  Details")

        splitter.setSizes([380, 350])

        # ── Status bar ─────────────────────────────────────────────────────
        self.statusBar().showMessage("Starting scanner…")

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_data(self, aps: List[AccessPoint]):
        self._aps = aps
        self._model.update(aps)
        self._channel_graph.update_aps(aps, self._model.ssid_colors())
        self._history_graph.set_ssid_colors(self._model.ssid_colors())
        self._history_graph.push(aps)
        # Auto-fit SSID and Manufacturer to their content, unless the user
        # has manually dragged those columns (tracked via _user_sized_cols).
        _AUTO_FIT_MAX = 320
        for col in (COL_SSID, COL_MANUF):
            if col not in self._user_sized_cols:
                self._table.resizeColumnToContents(col)
                if self._table.columnWidth(col) > _AUTO_FIT_MAX:
                    self._table.setColumnWidth(col, _AUTO_FIT_MAX)

        total = len(aps)
        shown = self._proxy.rowCount()
        self._lbl_count.setText(f"  {shown}/{total} APs")
        ts = time.strftime("%H:%M:%S")
        self._lbl_updated.setText(f"  Last scan: {ts}  ")
        self.statusBar().showMessage(f"Found {total} access points  |  Showing {shown}")

    def _on_theme_change(self, idx: int):
        modes = ["dark", "light", "auto"]
        self._apply_theme(modes[idx])

    def _apply_theme(self, mode: str):
        app = QApplication.instance()
        if mode == "dark":
            app.setPalette(_dark_palette())
            plot_bg, plot_fg = "#0d1117", "#a9b4cc"
        elif mode == "light":
            app.setPalette(_light_palette())
            plot_bg, plot_fg = "#f0f4f8", "#444455"
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
        self._table.viewport().update()

    def _on_error(self, msg: str):
        self.statusBar().showMessage(f"⚠ Scanner error: {msg}")

    def _on_col_resized(self, col: int, old_size: int, new_size: int):
        """Record that the user explicitly resized this column."""
        self._user_sized_cols.add(col)

    def _on_band_change(self, band: str):
        self._proxy.set_band(band)
        self._channel_graph.set_band(band)
        self._channel_graph.update_aps(self._aps, self._model.ssid_colors())
        cnt = self._proxy.rowCount()
        self._lbl_count.setText(f"  {cnt}/{len(self._aps)} APs")

    def _on_interval_change(self, idx: int):
        secs = REFRESH_INTERVALS[idx]
        self._scanner.set_interval(secs)

    def _on_pause(self, paused: bool):
        if paused:
            self._scanner.stop()
            self._btn_pause.setText("▶ Resume")
            self.statusBar().showMessage("Paused — click Resume to continue scanning")
        else:
            self._scanner = WiFiScanner(
                interval_sec=REFRESH_INTERVALS[self._interval_combo.currentIndex()]
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
            (COL_MANUF, ap.manufacturer, "Manufacturer"),
            (COL_BSSID, ap.bssid, "MAC address"),
            (COL_CHAN, str(ap.channel), "Channel"),
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
        det.triggered.connect(lambda: self._show_details(ap))

        menu.exec(self._table.viewport().mapToGlobal(pos))

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

        def badge(text, bg, fg="white"):
            return (
                f'<span style="background:{bg};color:{fg};padding:3px 10px;'
                f'border-radius:4px;font-size:13px;font-weight:500">{text}</span>'
            )

        def dim(text):
            return f"<span style='color:#777'>{text}</span>"

        # ── SSID header ───────────────────────────────────────────────────
        in_use = (
            (
                ' &nbsp;<span style="background:#2e7d32;color:white;padding:2px 8px;'
                'border-radius:4px;font-size:13px"> ▲ CONNECTED </span>'
            )
            if ap.in_use
            else ""
        )
        self._det_ssid.setText(
            f'<span style="font-size:20px;font-weight:700;color:{color}">{ap.display_ssid}</span>{in_use}'
        )

        # ── WiFi generation ───────────────────────────────────────────────
        gen_color = _IW_GEN_COLORS.get(ap.wifi_gen, "#37474F")
        if ap.wifi_gen:
            gen_html = badge(f"{ap.wifi_gen}  ·  {ap.protocol}", gen_color)
        else:
            gen_html = ap.protocol or dim("Unknown")

        # ── Security ──────────────────────────────────────────────────────
        sec = ap.security_short
        if sec == "Open":
            sec_html = badge(sec, "#b71c1c")
        elif "WPA3" in sec:
            sec_html = badge(sec, "#1b5e20")
        elif "WPA2" in sec:
            sec_html = badge(sec, "#0d47a1")
        else:
            sec_html = badge(sec, "#37474F")

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
        kvr_html = ""
        if ap.rrm:
            kvr_html += badge("802.11k", "#1565C0") + "&nbsp; "
        if ap.btm:
            kvr_html += badge("802.11v", "#1565C0") + "&nbsp; "
        if ap.ft:
            kvr_html += badge("802.11r", "#1565C0") + "&nbsp; "
        if not kvr_html:
            kvr_html = dim("None detected")

        # ── Populate rows ─────────────────────────────────────────────────
        v = self._det_vals
        v["bssid"].setText(ap.bssid)
        v["manufacturer"].setText(ap.manufacturer or dim("Unknown"))
        v["wifi_gen"].setText(gen_html)
        v["band"].setText(ap.band)
        v["channel"].setText(str(ap.channel))
        v["frequency"].setText(f"{ap.freq_mhz} MHz")
        v["chan_width"].setText(f"{ap.bandwidth_mhz} MHz")
        v["country"].setText(ap.country or dim("Unknown"))
        v["signal"].setText(
            f'<span style="color:{sig_col};font-size:15px;font-weight:700">'
            f"{ap.signal}%&nbsp;</span>"
            f'<span style="color:{sig_col}">({ap.dbm} dBm)</span>'
        )
        v["max_rate"].setText(f"{int(ap.rate_mbps)} Mbps")
        v["security"].setText(sec_html)
        v["pmf"].setText(pmf_html)
        v["chan_util"].setText(util_html)
        v["clients"].setText(
            str(ap.station_count) if ap.station_count is not None else dim("Unknown")
        )
        v["roaming"].setText(kvr_html)
        v["mode"].setText(ap.mode)

    def _prompt_oui_download(self):
        dlg = OuiDownloadDialog(self, first_run=True)
        dlg.exec()
        # After a successful download the OUI DB is already reloaded globally;
        # trigger a fresh scan so new AP objects pick up the better names.
        if OUI_JSON_PATH.exists():
            self._scanner.stop()
            self._scanner = WiFiScanner(
                interval_sec=REFRESH_INTERVALS[self._interval_combo.currentIndex()]
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
                interval_sec=REFRESH_INTERVALS[self._interval_combo.currentIndex()]
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


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────


def main():
    # ── Pyqtgraph config must come before QApplication ─────────────────────
    PLOT_BG = "#0d1117"
    pg.setConfigOptions(antialias=True, foreground="#a9b4cc", background=PLOT_BG)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("wavescope")  # GNOME dock grouping / WM_CLASS hint
    app.setOrganizationName("nmcli-gui")
    app.setStyle("Fusion")
    _icon_path = Path(__file__).parent / "assets" / "icon.svg"
    if _icon_path.exists():
        app.setWindowIcon(QIcon(str(_icon_path)))

    app.setPalette(_dark_palette())

    # ── Font ───────────────────────────────────────────────────────────────
    for name in ("Inter", "Segoe UI", "Ubuntu", "Noto Sans", "DejaVu Sans"):
        font = QFont(name, 10)
        if font.exactMatch():
            break
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


# ── Theme palette helpers ────────────────────────────────────────────────────
def _dark_palette() -> QPalette:
    p, C = QPalette(), QColor
    p.setColor(QPalette.ColorRole.Window, C("#0d1117"))
    p.setColor(QPalette.ColorRole.WindowText, C("#d0d8f0"))
    p.setColor(QPalette.ColorRole.Base, C("#11151f"))
    p.setColor(QPalette.ColorRole.AlternateBase, C("#161b27"))
    p.setColor(QPalette.ColorRole.ToolTipBase, C("#1c2236"))
    p.setColor(QPalette.ColorRole.ToolTipText, C("#d0d8f0"))
    p.setColor(QPalette.ColorRole.Text, C("#d0d8f0"))
    p.setColor(QPalette.ColorRole.Button, C("#1c2236"))
    p.setColor(QPalette.ColorRole.ButtonText, C("#d0d8f0"))
    p.setColor(QPalette.ColorRole.BrightText, C("#ffffff"))
    p.setColor(QPalette.ColorRole.Link, C("#7eb8f7"))
    p.setColor(QPalette.ColorRole.Highlight, C("#1e4a80"))
    p.setColor(QPalette.ColorRole.HighlightedText, C("#ffffff"))
    p.setColor(QPalette.ColorRole.Mid, C("#1f2638"))
    p.setColor(QPalette.ColorRole.Dark, C("#090c14"))
    p.setColor(QPalette.ColorRole.Midlight, C("#19202f"))
    p.setColor(QPalette.ColorRole.Shadow, C("#04060e"))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, C("#4a5068"))
    p.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, C("#4a5068")
    )
    return p


def _light_palette() -> QPalette:
    p, C = QPalette(), QColor
    p.setColor(QPalette.ColorRole.Window, C("#f0f2f5"))
    p.setColor(QPalette.ColorRole.WindowText, C("#1a1c22"))
    p.setColor(QPalette.ColorRole.Base, C("#ffffff"))
    p.setColor(QPalette.ColorRole.AlternateBase, C("#f5f7fa"))
    p.setColor(QPalette.ColorRole.ToolTipBase, C("#fffff0"))
    p.setColor(QPalette.ColorRole.ToolTipText, C("#1a1c22"))
    p.setColor(QPalette.ColorRole.Text, C("#1a1c22"))
    p.setColor(QPalette.ColorRole.Button, C("#e2e6ef"))
    p.setColor(QPalette.ColorRole.ButtonText, C("#1a1c22"))
    p.setColor(QPalette.ColorRole.BrightText, C("#000000"))
    p.setColor(QPalette.ColorRole.Link, C("#1565c0"))
    p.setColor(QPalette.ColorRole.Highlight, C("#1976d2"))
    p.setColor(QPalette.ColorRole.HighlightedText, C("#ffffff"))
    p.setColor(QPalette.ColorRole.Mid, C("#c8cdd8"))
    p.setColor(QPalette.ColorRole.Dark, C("#b0b6c4"))
    p.setColor(QPalette.ColorRole.Midlight, C("#d8dce8"))
    p.setColor(QPalette.ColorRole.Shadow, C("#909090"))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, C("#a0a4b0"))
    p.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, C("#a0a4b0")
    )
    return p


if __name__ == "__main__":
    main()
