#!/usr/bin/env python3
"""
wavescope — Modern WiFi Analyzer for Linux
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


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

VERSION = "1.5.0"
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

_oui_full: Optional[Dict[str, str]] = None
_oui_loaded = False
_oui_suffix_unique_vendor: Optional[Dict[str, str]] = None
_vendor_urls: Optional[Dict[str, str]] = None
_vendor_urls_norm: Optional[Dict[str, str]] = None
_vendor_urls_tokens: Optional[Dict[str, set[str]]] = None
_vendor_urls_loaded = False
_vendor_icon_cache: Dict[str, Optional[QIcon]] = {}
_vendor_icon_placeholder: Optional[QIcon] = None
VENDOR_ICON_MAX_W = 42
VENDOR_ICON_MAX_H = 16

# Path where we save the downloaded IEEE OUI database
OUI_DATA_DIR = Path.home() / ".local" / "share" / "wavescope"
OUI_JSON_PATH = OUI_DATA_DIR / "oui.json"
OUI_VENDOR_FALLBACK_JSON_PATH = (
    Path(__file__).resolve().parent / "assets" / "vendors.json"
)
VENDOR_URLS_JSON_PATH = Path(__file__).resolve().parent / "assets" / "vendor_urls.json"
VENDOR_ICONS_DIR = Path(__file__).resolve().parent / "assets" / "vendor-icons"
VENDOR_ICON_EXTS = (".png", ".ico", ".svg", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
OUI_IEEE_URL = "https://standards-oui.ieee.org/"
OUI_IEEE_RE = re.compile(r"([0-9A-F]{2}-[0-9A-F]{2}-[0-9A-F]{2})\s+\(hex\)\s+(.+?)\n")


def _norm_vendor_name(vendor: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (vendor or "").lower())


_MANUF_DISPLAY_SUFFIXES = {
    "inc",
    "ltd",
    "co",
    "corp",
    "llc",
}


def format_manufacturer_display(vendor: str) -> str:
    """Display-only manufacturer cleanup; never modifies DB values."""
    text = (vendor or "").strip()
    if not text:
        return ""
    parts = [p for p in text.split() if p]
    while parts:
        tail = re.sub(r"[\.,]+$", "", parts[-1]).lower()
        if tail in _MANUF_DISPLAY_SUFFIXES:
            parts.pop()
            continue
        break
    cleaned = " ".join(parts).strip(" ,")
    return cleaned or text


_VENDOR_NOISE_TOKENS = {
    "inc",
    "corp",
    "corporation",
    "company",
    "co",
    "co.",
    "ltd",
    "ltd.",
    "limited",
    "llc",
    "gmbh",
    "srl",
    "spa",
    "s.p.a",
    "s.a",
    "ag",
    "nv",
    "plc",
    "group",
    "systems",
    "technology",
    "technologies",
    "electronics",
    "communication",
    "communications",
    "network",
    "networks",
}


def _vendor_tokens(vendor: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", (vendor or "").lower()))
    return {t for t in tokens if t and t not in _VENDOR_NOISE_TOKENS and len(t) > 1}


def _norm_domain(domain: str) -> str:
    d = (domain or "").strip().lower()
    if d.startswith("https://"):
        d = d[8:]
    elif d.startswith("http://"):
        d = d[7:]
    return d.rstrip("/")


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


def _load_embedded_oui() -> Dict[str, str]:
    """Load bundled fallback DB from assets/vendors.json."""
    if not OUI_VENDOR_FALLBACK_JSON_PATH.exists():
        return {}
    try:
        raw: Dict[str, str] = json.loads(
            OUI_VENDOR_FALLBACK_JSON_PATH.read_text(encoding="utf-8")
        )
        return {k.replace("-", ":").upper(): v for k, v in raw.items() if v}
    except Exception:
        return {}


def _load_oui_with_precedence() -> Dict[str, str]:
    """Merge OUI DBs with precedence: embedded > downloaded > system."""
    merged: Dict[str, str] = {}
    merged.update(_load_system_oui())
    merged.update(_load_downloaded_oui())
    merged.update(_load_embedded_oui())
    return merged


def _build_unique_oui_suffix_vendor_index(oui_db: Dict[str, str]) -> Dict[str, str]:
    """Build a conservative BB:CC -> vendor map from globally-administered OUIs.

    We only keep suffixes that map to exactly one globally-administered OUI
    prefix, to avoid broad false positives.
    """
    buckets: Dict[str, List[str]] = {}
    for prefix, vendor in (oui_db or {}).items():
        if not prefix or len(prefix) < 8 or not vendor:
            continue
        try:
            first_octet = int(prefix[:2], 16)
        except Exception:
            continue
        if first_octet & 0x02:
            continue
        suffix = prefix[3:8]
        buckets.setdefault(suffix, []).append(prefix)

    resolved: Dict[str, str] = {}
    for suffix, prefixes in buckets.items():
        if len(prefixes) != 1:
            continue
        only_prefix = prefixes[0]
        vendor = (oui_db or {}).get(only_prefix, "")
        if vendor:
            resolved[suffix] = vendor
    return resolved


def _load_vendor_urls() -> Dict[str, str]:
    if not VENDOR_URLS_JSON_PATH.exists():
        return {}
    try:
        raw: Dict[str, str] = json.loads(
            VENDOR_URLS_JSON_PATH.read_text(encoding="utf-8")
        )
        return {k.strip(): _norm_domain(v) for k, v in raw.items() if k and v}
    except Exception:
        return {}


def _ensure_vendor_urls_loaded() -> None:
    global _vendor_urls, _vendor_urls_norm, _vendor_urls_tokens, _vendor_urls_loaded
    if _vendor_urls_loaded:
        return
    _vendor_urls = _load_vendor_urls()
    _vendor_urls_norm = {}
    _vendor_urls_tokens = {}
    for name, domain in (_vendor_urls or {}).items():
        key = _norm_vendor_name(name)
        if key and key not in _vendor_urls_norm:
            _vendor_urls_norm[key] = domain
        _vendor_urls_tokens[name] = _vendor_tokens(name)
    _vendor_urls_loaded = True


def _resolve_vendor_domain(vendor_name: str) -> str:
    _ensure_vendor_urls_loaded()
    if not vendor_name:
        return ""

    if _vendor_urls:
        direct = _vendor_urls.get(vendor_name, "")
        if direct:
            return direct

    query_norm = _norm_vendor_name(vendor_name)
    if not query_norm:
        return ""

    if _vendor_urls_norm:
        exact = _vendor_urls_norm.get(query_norm, "")
        if exact:
            return exact

    if _vendor_urls_norm:
        contains_best = ""
        contains_len = 0
        for key, domain in _vendor_urls_norm.items():
            if key and (key in query_norm or query_norm in key):
                key_len = len(key)
                if key_len > contains_len:
                    contains_best = domain
                    contains_len = key_len
        if contains_best:
            return contains_best

    query_tokens = _vendor_tokens(vendor_name)
    if not query_tokens or not _vendor_urls_tokens or not _vendor_urls:
        return ""

    best_name = ""
    best_score = 0.0
    best_overlap = 0
    for name, tokens in _vendor_urls_tokens.items():
        if not tokens:
            continue
        overlap = len(query_tokens & tokens)
        if overlap == 0:
            continue
        score = overlap / max(1, len(tokens))
        if score > best_score or (
            abs(score - best_score) < 1e-9 and overlap > best_overlap
        ):
            best_name = name
            best_score = score
            best_overlap = overlap

    if best_name and (best_score >= 0.60 or best_overlap >= 2):
        return _vendor_urls.get(best_name, "")
    return ""


def _resolve_vendor_icon_path(vendor_name: str) -> Optional[Path]:
    domain = _resolve_vendor_domain(vendor_name)
    if not domain:
        return None

    base_names = [domain, f"www.{domain}"]
    if domain.startswith("www."):
        base_names.append(domain[4:])

    candidates: List[Path] = []
    for base in base_names:
        for ext in VENDOR_ICON_EXTS:
            candidates.append(VENDOR_ICONS_DIR / f"{base}{ext}")

    for path in candidates:
        if path.exists():
            return path
    return None


def _build_vendor_icon(path: Path) -> Optional[QIcon]:
    # Prefer QIcon pixmap selection first so containers like .ico can pick
    # the best embedded frame for our target size.
    target_w = VENDOR_ICON_MAX_W
    target_h = VENDOR_ICON_MAX_H
    req = max(target_w, target_h) * 8

    source_icon = QIcon(str(path))
    pixmap = source_icon.pixmap(req, req)
    if pixmap.isNull():
        pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None

    img = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    min_x = img.width()
    min_y = img.height()
    max_x = -1
    max_y = -1
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 0:
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y

    if max_x >= min_x and max_y >= min_y:
        img = img.copy(QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1))

    app = QApplication.instance()
    dpr = float(app.devicePixelRatio() if app is not None else 1.0)
    px_w = max(1, int(round(target_w * dpr)))
    px_h = max(1, int(round(target_h * dpr)))

    fit_scale = min(px_w / max(1, img.width()), px_h / max(1, img.height()))

    if fit_scale <= 1.0:
        target_scale = fit_scale
    else:
        min_w = max(1, int(round(px_w * 0.45)))
        min_h = max(1, int(round(px_h * 0.80)))
        desired_scale = max(
            min_w / max(1, img.width()),
            min_h / max(1, img.height()),
            1.0,
        )
        target_scale = min(fit_scale, min(desired_scale, 2.25))

    if abs(target_scale - 1.0) < 1e-6:
        scaled_img = img
    elif target_scale < 1.0:
        scaled_img = img.scaled(
            max(1, int(round(img.width() * target_scale))),
            max(1, int(round(img.height() * target_scale))),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    else:
        scaled_img = img.scaled(
            max(1, int(round(img.width() * target_scale))),
            max(1, int(round(img.height() * target_scale))),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

    canvas_img = QImage(px_w, px_h, QImage.Format.Format_ARGB32)
    canvas_img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas_img)
    x = (px_w - scaled_img.width()) // 2
    y = (px_h - scaled_img.height()) // 2
    painter.drawImage(x, y, scaled_img)
    painter.end()

    canvas = QPixmap.fromImage(canvas_img)
    canvas.setDevicePixelRatio(dpr)
    icon = QIcon(canvas)
    if icon.isNull():
        return None
    return icon


def get_vendor_placeholder_icon() -> QIcon:
    global _vendor_icon_placeholder
    if _vendor_icon_placeholder is not None:
        return _vendor_icon_placeholder

    canvas = QPixmap(VENDOR_ICON_MAX_W, VENDOR_ICON_MAX_H)
    canvas.fill(Qt.GlobalColor.transparent)
    _vendor_icon_placeholder = QIcon(canvas)
    return _vendor_icon_placeholder


def get_vendor_icon(vendor_name: str) -> Optional[QIcon]:
    if not vendor_name:
        return None
    if vendor_name in _vendor_icon_cache:
        return _vendor_icon_cache[vendor_name]

    icon_path = _resolve_vendor_icon_path(vendor_name)
    if icon_path is not None:
        icon = _build_vendor_icon(icon_path)
        if icon is not None:
            _vendor_icon_cache[vendor_name] = icon
            return icon

    _vendor_icon_cache[vendor_name] = None
    return None


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
    global _oui_full, _oui_loaded, _oui_suffix_unique_vendor, _vendor_urls_loaded
    _oui_full = _load_oui_with_precedence()
    _oui_loaded = True
    _oui_suffix_unique_vendor = None
    _vendor_urls_loaded = False
    _vendor_icon_cache.clear()


def get_manufacturer(bssid: str) -> str:
    global _oui_full, _oui_loaded, _oui_suffix_unique_vendor
    if not _oui_loaded:
        _oui_full = _load_oui_with_precedence()
        _oui_loaded = True
    if not bssid:
        return ""
    mac = bssid.upper().replace("-", ":")
    prefix = mac[:8]
    if _oui_full and prefix in _oui_full:
        return _oui_full[prefix]

    # Some AP radios use locally administered BSSIDs (U/L bit set), which
    # often map to an underlying globally administered vendor OUI with that
    # bit cleared. If direct lookup misses, try clearing the U/L bit.
    try:
        first_octet = int(prefix[:2], 16)
        if first_octet & 0x02:
            ga_octet = first_octet & 0xFD
            ga_prefix = f"{ga_octet:02X}{prefix[2:]}"
            if _oui_full and ga_prefix in _oui_full:
                return _oui_full[ga_prefix]

            # Conservative fallback for locally-administered addresses where
            # only the first OUI octet was transformed by firmware/tooling.
            # We only accept BB:CC suffixes that map to exactly one
            # globally-administered OUI prefix in the current DB.
            if not (first_octet & 0x01):
                if _oui_suffix_unique_vendor is None:
                    _oui_suffix_unique_vendor = _build_unique_oui_suffix_vendor_index(
                        _oui_full or {}
                    )
                suffix = prefix[3:8]
                vendor = (_oui_suffix_unique_vendor or {}).get(suffix, "")
                if vendor:
                    return vendor
    except Exception:
        pass
    return ""


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
                OUI_IEEE_URL, headers={"User-Agent": "wavescope-wifi-analyzer/1.0"}
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
    akm_raw: str = ""  # raw AKM string from iw (Authentication suites)
    wps_manufacturer: str = ""  # Manufacturer from WPS IE (if advertised)
    rrm: bool = False  # 802.11k Radio Resource Measurement
    btm: bool = False  # 802.11v BSS Transition Management
    ft: bool = False  # 802.11r Fast Transition
    country: str = ""  # Country code from beacon (e.g. "DE")
    iw_center_freq: Optional[int] = None  # bonded-block center MHz from iw (all bands)
    # ── Computed in __post_init__ ────────────────────────────────────────────
    band: str = field(init=False)
    manufacturer: str = field(init=False)
    manufacturer_source: str = field(init=False)

    def __post_init__(self):
        self.band = freq_to_band(self.freq_mhz)
        self.manufacturer = get_manufacturer(self.bssid)
        self.manufacturer_source = "OUI database" if self.manufacturer else "Unknown"

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
        """Compact 802.11k/v/r roaming-feature badge, e.g. 'k v r' or ''."""
        flags = []
        if self.rrm:
            flags.append("k")
        if self.btm:
            flags.append("v")
        if self.ft:
            flags.append("r")
        return " ".join(flags) if flags else ""

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
    def phy_mode(self) -> str:
        """Compact 802.11 PHY mode for table display (e.g. B/G, A, A/N, AX)."""
        if self.wifi_gen == "WiFi 7":
            return "BE"
        if self.wifi_gen in ("WiFi 6", "WiFi 6E"):
            return "AX"
        if self.wifi_gen == "WiFi 5":
            return "AC"
        if self.wifi_gen == "WiFi 4":
            return "A/N" if self.freq_mhz >= 5000 else "B/G/N"
        return "A" if self.freq_mhz >= 5000 else "B/G"

    @property
    def display_ssid(self) -> str:
        return self.ssid if self.ssid else f"<hidden> ({self.bssid})"

    @property
    def security_short(self) -> str:
        """Compact canonical security label for table/dashboard display."""

        def _nz(v: str) -> str:
            return (v or "").strip()

        sec = _nz(self.security).upper()
        wpa = _nz(self.wpa_flags).upper()
        rsn = _nz(self.rsn_flags).upper()
        akm = _nz(getattr(self, "akm_raw", "") or self.akm).upper()

        has_wpa_ie = wpa not in ("", "--", "(NONE)")
        has_rsn_ie = rsn not in ("", "--", "(NONE)")
        has_wep = "WEP" in sec
        has_sae = "SAE" in akm
        has_psk = "PSK" in akm or "PSK" in sec or "PSK" in wpa or "PSK" in rsn
        has_eap = (
            "EAP" in akm
            or "802.1X" in akm
            or "8021X" in akm
            or "ENTERPRISE" in akm
            or "EAP" in sec
        )
        has_owe = "OWE" in akm or "OWE" in sec

        if not sec and not has_wpa_ie and not has_rsn_ie and not akm:
            return "Open"
        if has_wep:
            return "WEP"
        if has_owe:
            return "OWE"

        if has_sae and has_psk:
            return "WPA2/WPA3 (PSK/SAE)"
        if has_sae:
            return "WPA3 (SAE)"

        if has_eap:
            if has_wpa_ie and has_rsn_ie:
                return "WPA/WPA2 (802.1X)"
            if has_rsn_ie:
                return "WPA2 (802.1X)"
            return "Enterprise (802.1X)"

        if has_wpa_ie and has_rsn_ie:
            return "WPA/WPA2 (PSK)"
        if has_rsn_ie:
            return "WPA2 (PSK)"
        if has_wpa_ie:
            return "WPA (PSK)"

        if "WPA3" in sec and "WPA2" in sec:
            return "WPA2/WPA3 (PSK/SAE)"
        if "WPA3" in sec:
            return "WPA3"
        if "WPA2" in sec and "WPA" in sec:
            return "WPA/WPA2"
        if "WPA2" in sec:
            return "WPA2"
        if "WPA" in sec:
            return "WPA"
        return "Open"

    @property
    def security_tooltip(self) -> str:
        """Detailed security info for table tooltip."""

        def _nz(v: str) -> str:
            s = (v or "").strip()
            return s if s else "—"

        return (
            f"Security: {_nz(self.security_short)}\n"
            f"nmcli SECURITY: {_nz(self.security)}\n"
            f"WPA flags: {_nz(self.wpa_flags)}\n"
            f"RSN flags: {_nz(self.rsn_flags)}\n"
            f"AKM (iw): {_nz(getattr(self, 'akm_raw', '') or self.akm)}\n"
            f"PMF: {_nz(self.pmf)}"
        )


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
            d["akm_raw"] = raw.strip()
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

        # ── WPS manufacturer hint (often reveals branded vendor on LAA MACs) ──
        wps_manuf_m = re.search(r"(?im)^\s*\*\s*Manufacturer:\s*(.+?)\s*$", text)
        if wps_manuf_m:
            wps_name = wps_manuf_m.group(1).strip().strip('"')
            if wps_name and wps_name.lower() not in {"unknown", "private", "n/a"}:
                d["wps_manufacturer"] = wps_name

        # ── 802.11k / 802.11v ────────────────────────────────────────────
        d["rrm"] = "Neighbor Report" in text
        d["btm"] = "BSS Transition" in text

        # ── Country code ─────────────────────────────────────────────────
        cc_m = re.search(r"Country:\s+([A-Z]{2})", text)
        if cc_m:
            d["country"] = cc_m.group(1)

        # ── Bonded-block center frequency ─────────────────────────────────
        # VHT (5 GHz 80/160) and HE/EHT (6 GHz) report "center freq 1: XXXX"
        cf1_m = re.search(r"\*\s*center freq(?:\s+segment)?\s*1\s*:\s*(\d+)", text)
        if cf1_m:
            cf = int(cf1_m.group(1))
            if cf > 0:
                d["iw_center_freq"] = cf
        # HT 40 MHz (2.4 GHz) reports secondary channel offset; compute center
        if "iw_center_freq" not in d and freq_val > 0:
            sec_m = re.search(r"\*\s*secondary channel offset:\s*(above|below)", text)
            if sec_m:
                offset = +10 if sec_m.group(1) == "above" else -10
                d["iw_center_freq"] = int(freq_val) + offset

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
                "akm_raw",
                "wps_manufacturer",
                "rrm",
                "btm",
                "ft",
                "country",
                "iw_center_freq",
            ):
                if attr in d:
                    setattr(ap, attr, d[attr])

            # Prefer WPS-advertised manufacturer when OUI lookup is missing
            # or when BSSID is locally-administered (common synthetic radio MAC).
            wps_vendor = d.get("wps_manufacturer", "")
            if wps_vendor:
                use_wps = not ap.manufacturer
                try:
                    first_octet = int(ap.bssid[:2], 16)
                    if first_octet & 0x02:
                        use_wps = True
                except Exception:
                    pass
                if use_wps:
                    ap.manufacturer = wps_vendor
                    ap.manufacturer_source = "WPS (iw scan)"
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
    "Country",
    "Ch",
    "Freq (MHz)",
    "Width (MHz)",
    "Ch. Span",
    "Signal",
    "dBm",
    "Rate (Mbps)",
    "Security",
    "802.11",
    "Gen",
    "Ch.Util%",
    "Clients",
    "Roaming",
]

COL_INUSE = 0
COL_SSID = 1
COL_BSSID = 2
COL_MANUF = 3
COL_BAND = 4
COL_COUNTRY = 5
COL_CHAN = 6
COL_FREQ = 7
COL_BW = 8
COL_SPAN = 9  # Channel span, e.g. "116–128" for ch116@80MHz on 5 GHz
COL_SIG = 10
COL_DBM = 11
COL_RATE = 12
COL_SEC = 13
COL_MODE = 14
COL_GEN = 15  # WiFi generation (WiFi 4/5/6/6E/7)
COL_UTIL = 16  # Channel utilisation %  (BSS Load)
COL_CLIENTS = 17  # Station count          (BSS Load)
COL_KVR = 18  # 802.11k/v/r roaming flags


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
                COL_SPAN,
                COL_SIG,
                COL_DBM,
                COL_RATE,
                COL_UTIL,
                COL_CLIENTS,
            }
            if col in numeric_cols or col == COL_KVR:
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


# ─── U-NII sub-band colour map for 5 GHz x-axis tick labels ─────────────────
# Source: IEEE 802.11 / FCC U-NII band definitions
#   U-NII-1  (5150–5250 MHz)  ch 32–48    — no DFS required
#   U-NII-2A (5250–5350 MHz)  ch 52–64    — DFS/TPC required
#   U-NII-2C (5470–5725 MHz)  ch 96–144   — DFS/TPC required (TDWR avoidance)
#   U-NII-3  (5725–5850 MHz)  ch 149–165  — no DFS required
#   U-NII-4  (5850–5925 MHz)  ch 169–177  — proposed / limited use
_UNII_CHAN_COLORS: Dict[int, str] = {}
for _ch in [32, 36, 40, 44, 48]:
    _UNII_CHAN_COLORS[_ch] = "#81c995"  # U-NII-1  — soft green
for _ch in [52, 56, 60, 64]:
    _UNII_CHAN_COLORS[_ch] = "#64b5f6"  # U-NII-2A — soft blue
for _ch in [100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144]:
    _UNII_CHAN_COLORS[_ch] = "#ffcc80"  # U-NII-2C — soft amber
for _ch in [149, 153, 157, 161, 165]:
    _UNII_CHAN_COLORS[_ch] = "#a5d6a7"  # U-NII-3  — lighter green
for _ch in [169, 173, 177]:
    _UNII_CHAN_COLORS[_ch] = "#ef9a9a"  # U-NII-4  — light red (proposed)

# Sub-band name → colour (for second-level tick labels on 5 GHz x-axis)
_UNII_NAME_COLORS: Dict[str, str] = {
    "U-NII-1": "#81c995",
    "U-NII-2A": "#64b5f6",
    "U-NII-2C": "#ffcc80",
    "U-NII-3": "#a5d6a7",
    "U-NII-4": "#ef9a9a",
    "U-NII-5": "#81c995",
    "U-NII-6": "#64b5f6",
    "U-NII-7": "#ffcc80",
    "U-NII-8": "#ef9a9a",
}

# Sub-band header strip definitions for each WiFi band.
# Each tuple: (x_start_MHz, x_end_MHz, hex_fill_color, short_label)
_BAND_SUBBAND_HEADERS: Dict[str, List[Tuple[float, float, str, str]]] = {
    "2.4 GHz": [
        (2400.0, 2500.0, "#8a9bb0", "ISM"),
    ],
    "5 GHz": [
        (5150.0, 5250.0, "#81c995", "U-NII-1"),
        (5250.0, 5350.0, "#64b5f6", "U-NII-2A"),
        (5470.0, 5730.0, "#ffcc80", "U-NII-2C"),
        (5730.0, 5850.0, "#a5d6a7", "U-NII-3"),
        (5850.0, 5925.0, "#ef9a9a", "U-NII-4"),
    ],
    "6 GHz": [
        (5925.0, 6425.0, "#81c995", "U-NII-5"),
        (6425.0, 6525.0, "#64b5f6", "U-NII-6"),
        (6525.0, 6875.0, "#ffcc80", "U-NII-7"),
        (6875.0, 7125.0, "#ef9a9a", "U-NII-8"),
    ],
}

# 6 GHz channel → U-NII sub-band colour  (5950 + ch*5 MHz)
_UNII6_CHAN_COLORS: Dict[int, str] = {}
for _ch in range(1, 94, 4):  # U-NII-5  (5955–6415 MHz)
    _UNII6_CHAN_COLORS[_ch] = "#81c995"
for _ch in range(97, 114, 4):  # U-NII-6  (6435–6515 MHz)
    _UNII6_CHAN_COLORS[_ch] = "#64b5f6"
for _ch in range(117, 186, 4):  # U-NII-7  (6535–6875 MHz)
    _UNII6_CHAN_COLORS[_ch] = "#ffcc80"
for _ch in range(189, 234, 4):  # U-NII-8  (6895–7115 MHz)
    _UNII6_CHAN_COLORS[_ch] = "#ef9a9a"


class FiveGhzBottomAxisItem(pg.AxisItem):
    """X-axis for the 5 GHz panel — tick labels colour-coded by U-NII sub-band."""

    _CHAN_COLORS = _UNII_CHAN_COLORS
    _DRAW_DFS_SEGMENT = True
    _DFS_FREQ_RANGE = (5260.0, 5720.0)  # ch52 .. ch144 centers

    def drawPicture(self, p, axisSpec, tickSpecs, textSpecs):
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing, False)
        p.setRenderHint(p.RenderHint.TextAntialiasing, True)
        pen, p1, p2 = axisSpec
        base_pen = pen
        if base_pen is None:
            c = QColor("#8a96b0")
            c.setAlpha(140)
            base_pen = pg.mkPen(c, width=1)
        p.setPen(base_pen)
        p.drawLine(p1, p2)
        if self._DRAW_DFS_SEGMENT and self.orientation == "bottom":
            dfs_lo, dfs_hi = self._DFS_FREQ_RANGE
            v1 = self.mapFromView(QPointF(dfs_lo, 0.0))
            v2 = self.mapFromView(QPointF(dfs_hi, 0.0))
            x_min = min(p1.x(), p2.x())
            x_max = max(p1.x(), p2.x())
            dfs_x1 = max(min(v1.x(), v2.x()), x_min)
            dfs_x2 = min(max(v1.x(), v2.x()), x_max)
            if dfs_x2 > dfs_x1:
                dfs_pen = QColor("#64b5f6")
                dfs_pen.setAlpha(255)
                p.setPen(pg.mkPen(dfs_pen, width=2))
                p.drawLine(QPointF(dfs_x1, p1.y()), QPointF(dfs_x2, p2.y()))
        for pen, p1, p2 in tickSpecs:
            p.setPen(pen)
            p.drawLine(p1, p2)
        if self.style.get("tickFont") is not None:
            p.setFont(self.style["tickFont"])
        default_pen = self.style.get("pen") or pg.mkPen("#8a96b0")
        for rect, flags, text in textSpecs:
            clean_text = text.strip()
            try:
                ch = int(clean_text)
                hex_c = self._CHAN_COLORS.get(ch)
            except ValueError:
                hex_c = _UNII_NAME_COLORS.get(clean_text)
            p.setPen(pg.mkPen(hex_c) if hex_c else default_pen)
            p.drawText(rect, int(flags), text)
        p.restore()


class SixGhzBottomAxisItem(FiveGhzBottomAxisItem):
    """X-axis for the 6 GHz panel — tick labels colour-coded by U-NII sub-band."""

    _CHAN_COLORS = _UNII6_CHAN_COLORS
    _DRAW_DFS_SEGMENT = False


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
        "6 GHz": 1,  # ch 1,5,9,…,233 (all 20 MHz primaries)
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
        self._view_ranges: Dict[
            str, Tuple[Tuple[float, float], Tuple[float, float]]
        ] = {}

    # ── Public API ────────────────────────────────────────────────────────

    def set_theme(self, bg: str, fg: str):
        self._theme_bg = bg
        self._theme_fg = fg
        for i, (band, pw) in enumerate(self._plots.items()):
            pw.setBackground(bg)
            if i == 0:
                pw.setLabel("left", "Signal (dBm)", color=fg, size="10pt")
            for ax in ("left", "bottom"):
                pw.getAxis(ax).setTextPen(fg)
                pw.getAxis(ax).setPen(fg)
        # Redraw so band-label TextItems inside the plot pick up the new fg
        self._redraw()

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
        if band == "5 GHz":
            axis_items["bottom"] = FiveGhzBottomAxisItem(orientation="bottom")
        elif band == "6 GHz":
            axis_items["bottom"] = SixGhzBottomAxisItem(orientation="bottom")
        pw = PlotWidget(axisItems=axis_items)
        pw.setBackground(self._theme_bg)
        pw.showGrid(x=True, y=True, alpha=0.18)
        fg = self._theme_fg
        if is_leftmost:
            pw.setLabel("left", "Signal (dBm)", color=fg, size="10pt")
        else:
            # Keep axis present (needed for y-grid lines) but invisible.
            # setWidth must be ≥1 — width=0 gives a zero bounding rect and
            # Qt skips painting the item entirely, suppressing grid lines.
            ax = pw.getAxis("left")
            ax.setWidth(1)
            ax.setStyle(showValues=False, tickLength=0)
            grid_pen = QColor(self._theme_fg)
            grid_pen.setAlpha(80)
            ax.setPen(pg.mkPen(grid_pen))
        # Bottom axis: two text rows (channels + sub-band labels)
        bottom_ax = pw.getAxis("bottom")
        bottom_ax.setTextPen(fg)
        axis_line_c = QColor(fg)
        axis_line_c.setAlpha(140)
        bottom_ax.setPen(pg.mkPen(axis_line_c, width=1))
        bottom_ax.setHeight(56)
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

    # ── Sub-band header strips ────────────────────────────────────────────────

    def _draw_band_overlays(
        self, band: str, pw: "PlotWidget", xmin: float, xmax: float
    ):
        """Band name label in the top-right corner."""
        floor = float(CHAN_DBM_FLOOR)

        # 5 GHz DFS highlight (ch52..144): draw directly on the plot floor so it
        # is visible in the canvas, not only in the axis widget area.
        if band == "5 GHz":
            dfs_lo = max(5260.0, xmin)
            dfs_hi = min(5720.0, xmax)
            if dfs_hi > dfs_lo:
                dfs_color = QColor("#a952bd")
                dfs_color.setAlpha(235)
                dfs_line = pg.PlotCurveItem(
                    [dfs_lo, dfs_hi],
                    [floor + 0.15, floor + 0.15],
                    pen=pg.mkPen(dfs_color, width=2),
                )
                dfs_line.setZValue(20)
                pw.addItem(dfs_line)

                # Small label to explain the highlighted DFS range.
                dfs_lbl_color = QColor(dfs_color)
                dfs_lbl_color.setAlpha(240)
                dfs_lbl = pg.TextItem(
                    text="DFS (52–144)",
                    anchor=(0.5, 1.0),
                    color=dfs_lbl_color,
                )
                dfs_font = QFont()
                dfs_font.setPointSize(7)
                dfs_font.setBold(True)
                dfs_lbl.setFont(dfs_font)
                dfs_lbl.setPos((dfs_lo + dfs_hi) / 2.0, floor + 0.1)
                dfs_lbl.setZValue(21)
                pw.addItem(dfs_lbl)

        # -- band name label, just inside top-right corner --
        band_color = QColor(self._theme_fg)
        band_color.setAlpha(180)
        band_lbl = pg.TextItem(text=band, anchor=(1.0, 0.0), color=band_color)
        bfont = QFont()
        bfont.setPointSize(8)
        bfont.setBold(True)
        band_lbl.setFont(bfont)
        # anchor (1.0, 0.0) pins top-right of text to this point → text hangs downward
        band_lbl.setPos(xmax, float(CHAN_DBM_CEIL) - 1.0)
        band_lbl.setZValue(5)
        pw.addItem(band_lbl)

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

        # Capture current per-band view ranges before any clear/rebuild so zoom/pan
        # persists across refreshes.
        for band, pw in self._plots.items():
            try:
                xr, yr = pw.getViewBox().viewRange()
                self._view_ranges[band] = (
                    (float(xr[0]), float(xr[1])),
                    (float(yr[0]), float(yr[1])),
                )
            except Exception:
                pass

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
                # Use the bonded-block center for 5 GHz (not just primary channel)
                draw_center = get_ap_draw_center(ap)
                unit = _channel_shape_unit(xs, draw_center, max(ap.bandwidth_mhz, 20))
                active = unit > 1e-6
                if not np.any(active):
                    continue
                xs_act = xs[active]
                unit_act = unit[active]
                ys = floor + (ap.dbm - floor) * unit
                ys_act = floor + (ap.dbm - floor) * unit_act
                floor_ys_act = np.full_like(xs_act, float(floor))

                bc = QColor(color)
                bc.setAlpha(55)
                zero_item = pg.PlotCurveItem(xs_act, floor_ys_act, pen=pg.mkPen(None))
                curve_item = pg.PlotCurveItem(
                    xs_act, ys_act, pen=mkPen(color=color, width=2)
                )
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
                label.setPos(draw_center, ap.dbm)
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
            # Build channel ticks
            stride = self._BAND_TICK_STRIDE.get(band, 1)
            sorted_chan = sorted(tick_src.items(), key=lambda x: x[1])
            ticks = [
                (f, str(c))
                for i, (c, f) in enumerate(sorted_chan)
                if xmin <= f <= xmax and i % stride == 0
            ]
            if ticks:
                subband_ticks = [
                    (((x0 + x1) / 2.0), "\n" + lbl)
                    for x0, x1, _c, lbl in _BAND_SUBBAND_HEADERS.get(band, [])
                    if xmin <= ((x0 + x1) / 2.0) <= xmax
                ]
                mixed_ticks = sorted(ticks + subband_ticks, key=lambda t: t[0])
                pw.getAxis("bottom").setTicks([mixed_ticks])

            # ── Band-specific spectrum annotations ─────────────────────────
            self._draw_band_overlays(band, pw, xmin, xmax)

            # Restore last user zoom/pan if available, otherwise use defaults.
            vr = self._view_ranges.get(band)
            if vr:
                (x0, x1), (y0, y1) = vr
                pw.setXRange(x0, x1, padding=0.0)
                pw.setYRange(y0, y1, padding=0.0)
            else:
                pw.setXRange(xmin, xmax, padding=0.01)
                pw.setYRange(floor, CHAN_DBM_CEIL, padding=0.0)

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
            "#1a3050",
            "#1e4a80",
        )
        btn_mon.clicked.connect(lambda: self._pick("monitor"))
        layout.addWidget(btn_mon)

        btn_mgd = self._make_card(
            "\U0001f310  Managed Mode",
            "Capture your own machine's traffic — WiFi stays connected",
            "Keeps your WiFi connection intact. Captures only traffic\n"
            "to/from this machine on the current network.\n"
            "Ideal for debugging your own connection without losing internet.",
            "#1a3a1a",
            "#1e5a22",
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
                self._bg = bg
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

    _ST_IDLE = "idle"
    _ST_CAPTURE = "capture"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("\U0001f310  Managed Capture  \u2014  Packet Capture")
        self.setMinimumSize(560, 540)
        self.setModal(False)

        self._state = self._ST_IDLE
        self._proc = None
        self._cleanup_proc = None
        self._capture_script = ""
        self._pid_file = ""
        self._stdout_buf = ""
        self._start_time = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._iface_name = ""
        self._output_path = ""

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
        self._lbl_state = QLabel("Idle")
        self._lbl_elapsed = QLabel("00:00")
        self._lbl_size = QLabel("File:  0 KB")
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
            self,
            "Save Capture File",
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
        iface = (
            self._iface_combo.currentData() or self._iface_combo.currentText()
        ).strip()
        output = self._out_edit.text().strip()
        if not iface:
            QMessageBox.warning(self, "No Interface", "Select a WiFi interface.")
            return
        if not output:
            QMessageBox.warning(self, "No Output", "Choose an output file.")
            return
        self._iface_name = iface
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
        self._stdout_buf += bytes(self._proc.readAllStandardOutput()).decode(
            errors="replace"
        )
        while "\n" in self._stdout_buf:
            line, self._stdout_buf = self._stdout_buf.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            if line == "WAVESCOPE_CAPTURE_OK":
                self._log_line(
                    "\u2713  tcpdump running \u2014 WiFi connection is intact."
                )
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
        self._stdout_buf += bytes(self._proc.readAllStandardOutput()).decode(
            errors="replace"
        )
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
        data = bytes(self._cleanup_proc.readAllStandardOutput()).decode(
            errors="replace"
        )
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
            self._log_line(
                "\u26a0  Still running after 20 s \u2014 force-killing\u2026"
            )
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
        # Cache for iw-enriched fields — persisted across up to 5 missed cycles
        self._iw_cache: Dict[str, dict] = {}  # bssid.lower() → field snapshot
        self._iw_miss: Dict[str, int] = {}  # bssid.lower() → consecutive-miss count
        self._scanner = WiFiScanner(interval_sec=2)
        self._scanner.data_ready.connect(self._on_data)
        self._scanner.scan_error.connect(self._on_error)

        self._model = APTableModel()
        self._proxy = APFilterProxy()
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self._setup_ui()
        # Whenever any filter changes (text, band, column include/exclude) the
        # proxy emits layoutChanged — refresh the graph to show only visible APs.
        self._proxy.layoutChanged.connect(self._on_filter_changed)
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
        }
        for col, w in _col_widths.items():
            self._table.setColumnWidth(col, w)
        # Track columns the user has manually resized — skip auto-fit for those
        self._user_sized_cols: set = set()
        hdr.sectionResized.connect(self._on_col_resized)
        splitter.addWidget(self._table)

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
            "manufacturer",
            "manufacturer_source",
            "wifi_gen",
            "mode_80211",
            "band",
            "channel",
            "frequency",
            "chan_width",
            "country",
            "signal",
            "max_rate",
            "security",
            "security_nmcli",
            "wpa_flags",
            "rsn_flags",
            "akm_raw",
            "wps_manufacturer",
            "pmf",
            "chan_util",
            "clients",
            "roaming",
        ]
        _DET_LABELS = [
            "BSSID (MAC)",
            "Manufacturer",
            "Manufacturer Source",
            "WiFi Generation",
            "802.11 PHY",
            "Band",
            "Channel",
            "Frequency",
            "Channel Width",
            "Country",
            "Signal",
            "Max Rate",
            "Security (Compact)",
            "nmcli SECURITY",
            "WPA Flags",
            "RSN Flags",
            "AKM (iw)",
            "WPS Manufacturer (iw)",
            "PMF (802.11w)",
            "Channel Util",
            "Clients",
            "Roaming (k/v/r)",
        ]
        _DET_LABEL_BY_KEY = dict(zip(_DET_ROWS, _DET_LABELS))
        _DET_LEFT_KEYS = [
            "bssid",
            "manufacturer",
            "manufacturer_source",
            "wifi_gen",
            "mode_80211",
            "band",
            "channel",
            "frequency",
            "chan_width",
            "country",
            "signal",
        ]
        _DET_RIGHT_KEYS = [
            "max_rate",
            "security",
            "security_nmcli",
            "wpa_flags",
            "rsn_flags",
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
            val.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            self._det_vals[key] = val
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

        splitter.setSizes([380, 350])

        # ── Status bar ─────────────────────────────────────────────────────
        self.statusBar().showMessage("Starting scanner…")

    # ── Slots ─────────────────────────────────────────────────────────────────

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
        manuf_raw = ap.manufacturer or ""
        manuf_text = manuf_raw
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
            v["manufacturer_source"].setText(ap.manufacturer_source or dim("Unknown"))
        v["wifi_gen"].setText(gen_html)
        v["mode_80211"].setText(ap.phy_mode)
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
        v["security_nmcli"].setText(ap.security or dim("—"))
        v["wpa_flags"].setText(ap.wpa_flags or dim("—"))
        v["rsn_flags"].setText(ap.rsn_flags or dim("—"))
        v["akm_raw"].setText((ap.akm_raw or ap.akm) or dim("—"))
        v["wps_manufacturer"].setText(ap.wps_manufacturer or dim("Not advertised"))
        v["pmf"].setText(pmf_html)
        v["chan_util"].setText(util_html)
        v["clients"].setText(
            str(ap.station_count) if ap.station_count is not None else dim("Unknown")
        )
        v["roaming"].setText(kvr_html)

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
    app.setOrganizationName("wavescope")
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
