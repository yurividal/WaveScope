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
import html
import time
import json
import stat
import tempfile
import urllib.request
import subprocess
import shutil
from pathlib import Path
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, List, Dict, Tuple

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
    QPointF,
    QRect,
    QRectF,
    QSize,
    QSettings,
    QByteArray,
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
    QFontMetrics,
    QAction,
    QCursor,
)

import pyqtgraph as pg

if TYPE_CHECKING:  # annotation-only; importing at runtime would be circular
    from .core_models import AccessPoint
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

VERSION = "2.0.2"
APP_NAME = "WaveScope"


def _find_binary(name: str, extra_dirs: Tuple[str, ...] = ()) -> str:
    """Resolve an external tool, falling back to sbin dirs not on PATH.

    Desktop sessions commonly run with a PATH that omits the sbin dirs
    (e.g. "/usr/bin:/bin" only), even though tools like `iw` are installed
    under /usr/sbin on most distros. subprocess.run([name, ...]) then fails
    with FileNotFoundError, which several call sites silently swallow —
    disabling the feature that depends on it without any indication why
    (e.g. all iw-based enrichment: 6 GHz channel width fallback, WiFi
    generation, BSS Load, etc.).
    """
    found = shutil.which(name)
    if found:
        return found
    for directory in extra_dirs:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return name


_SBIN_DIRS = ("/usr/sbin", "/sbin")

NMCLI_BIN = _find_binary("nmcli", _SBIN_DIRS)
IW_BIN = _find_binary("iw", _SBIN_DIRS)
TCPDUMP_BIN = _find_binary("tcpdump", _SBIN_DIRS)
PKEXEC_BIN = _find_binary("pkexec", _SBIN_DIRS)

# Tools required for full functionality, checked at startup so the user gets
# an explicit warning instead of features silently degrading.
#   name shown to the user, resolved path, impact if missing
REQUIRED_TOOLS: List[Tuple[str, str, str]] = [
    (
        "nmcli",
        NMCLI_BIN,
        "Wi-Fi scanning will not work at all — nmcli is how WaveScope "
        "discovers access points (part of NetworkManager).",
    ),
    (
        "iw",
        IW_BIN,
        "6 GHz channel width, WiFi generation, BSS Load, and 802.11k/v/r "
        "details will be missing or inaccurate.",
    ),
    (
        "tcpdump",
        TCPDUMP_BIN,
        "Packet capture will not work.",
    ),
    (
        "pkexec",
        PKEXEC_BIN,
        "Packet capture will not work (requires a root prompt via Polkit).",
    ),
]


def find_missing_tools() -> List[Tuple[str, str]]:
    """Return (name, impact) for each required tool not found on disk."""
    missing = []
    for name, resolved, impact in REQUIRED_TOOLS:
        if not (os.path.isfile(resolved) and os.access(resolved, os.X_OK)):
            missing.append((name, impact))
    return missing


def warn_missing_tools_and_confirm(missing: List[Tuple[str, str]]) -> bool:
    """Show a blocking popup listing missing dependencies.

    Returns True if the user chose to proceed anyway, False if they chose
    to quit. Requires a QApplication to already exist.
    """
    names = ", ".join(name for name, _ in missing)
    lines = "\n".join(f"• {name} — {impact}" for name, impact in missing)
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(f"{APP_NAME} — Missing dependencies")
    box.setText(f"{APP_NAME} could not find: {names}")
    box.setInformativeText(
        f"{lines}\n\nInstall the missing package(s) with your system's "
        "package manager, then restart WaveScope for full functionality."
    )
    proceed_btn = box.addButton("Proceed Anyway", QMessageBox.ButtonRole.AcceptRole)
    quit_btn = box.addButton("Quit", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(quit_btn)
    box.exec()
    return box.clickedButton() is proceed_btn


def atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* atomically (temp file + rename).

    A crash mid-write leaves the previous file intact instead of a truncated
    JSON document that would later be silently ignored.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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

# 6 GHz 20 MHz channel 2 (5935 MHz) sits below the regular 5955 MHz raster
# (IEEE 802.11ax-2021 Annex E, operating class 136).  It never bonds.
CH6_SPECIAL = {2: 5935}

# 6 GHz Preferred Scanning Channels (PSC): every 4th 20 MHz channel starting
# at ch 5 (5, 21, 37, … 229).  6 GHz-only APs are expected to sit on a PSC so
# that clients can find them without scanning all 59 channels.
PSC_6GHZ_CHANNELS = frozenset(range(5, 230, 16))

# 5 GHz channels that require DFS / radar detection (U-NII-2A and U-NII-2C).
# The exact set is regulatory-domain specific (e.g. ch 144 is not permitted
# in ETSI); this is the common FCC/ETSI superset used for display only.
DFS_5GHZ_CHANNELS = frozenset(list(range(52, 65, 4)) + list(range(100, 145, 4)))

BAND_24 = "2.4 GHz"
BAND_5 = "5 GHz"
BAND_6 = "6 GHz"

_BAND_CHANNELS: Dict[str, Dict[int, int]] = {
    BAND_24: CH24,
    BAND_5: CH5,
    BAND_6: {**CH6_SPECIAL, **CH6},
}

# Legacy band-less lookup table.  Channel numbers are ambiguous across bands
# (ch 1 exists in 2.4 and 6 GHz, ch 149 in 5 and 6 GHz), so the precedence is
# 2.4 GHz → 5 GHz → 6 GHz.  Prefer chan_to_freq(chan, band) wherever possible.
ALL_CHANNELS = {**CH6, **CH5, **CH24}


def chan_index_to_freq(index: int, band: str) -> int:
    """Convert any channel *index* (primary or bonded-block center) to MHz.

    Unlike chan_to_freq() this accepts block-center indices such as 42/155
    (5 GHz VHT CCFS) or 7/15/31 (6 GHz HE/EHT CCFS), which are not primary
    20 MHz channels.  Formulae from IEEE 802.11-2020 §E.1:
      2.4 GHz: 2407 + 5·n  (n=14 is the Japan-only 2484 MHz special case)
      5 GHz:   5000 + 5·n
      6 GHz:   5950 + 5·n  (n=2 is the 5935 MHz special case)
    Returns 0 for indices outside the band.
    """
    if index <= 0:
        return 0
    if band == BAND_24:
        if index == 14:
            return 2484
        return 2407 + 5 * index if 1 <= index <= 13 else 0
    if band == BAND_5:
        return 5000 + 5 * index if 32 <= index <= 181 else 0
    if band == BAND_6:
        if index == 2:
            return 5935
        return 5950 + 5 * index if 1 <= index <= 233 else 0
    return 0


def chan_to_freq(chan: int, band: Optional[str] = None) -> int:
    """Return the center frequency (MHz) of a primary 20 MHz channel.

    Pass *band* whenever it is known: without it the lookup falls back to the
    2.4 → 5 → 6 GHz precedence of ALL_CHANNELS, which is wrong for 6 GHz.
    """
    if band in _BAND_CHANNELS:
        return _BAND_CHANNELS[band].get(chan, 0)
    return ALL_CHANNELS.get(chan, 0)


def freq_to_chan(freq_mhz: int) -> int:
    """Derive primary channel number from a center frequency.

    Used as a fallback when nmcli reports CHAN=0 but provides a valid frequency.
    Covers 2.4 GHz, 5 GHz, and 6 GHz bands.  Returns 0 if freq is unrecognised.
    """
    if 2412 <= freq_mhz <= 2472:
        return (freq_mhz - 2407) // 5
    if freq_mhz == 2484:
        return 14
    if 5160 <= freq_mhz <= 5885:
        return (freq_mhz - 5000) // 5
    if freq_mhz == 5935:
        return 2
    if 5955 <= freq_mhz <= 7115:
        return (freq_mhz - 5950) // 5
    return 0


def freq_to_band(freq_mhz: int) -> str:
    if 2400 <= freq_mhz < 2500:
        return BAND_24
    if 5000 <= freq_mhz < 5900:
        return BAND_5
    if 5925 <= freq_mhz <= 7125:
        return BAND_6
    return "?"


# ─────────────────────────────────────────────────────────────────────────────
# Bonded-channel block tables (5 GHz and 6 GHz)
#
# IEEE 802.11 defines fixed channel blocks for each bandwidth.  When an AP
# reports its *primary* 20 MHz channel at a wider BW, the spectrum it occupies
# is the whole bonded block, not ±BW/2 around the primary.
#
# Example: primary ch 116 @ 80 MHz → block ch 116-128 → center ch 122
#          primary ch 100 @ 160 MHz → block ch 100-128 → center ch 114
#
# Each table entry is (center_channel_index, [primary channels in block]).
# ─────────────────────────────────────────────────────────────────────────────


def _block(center_idx: int, bw_mhz: int) -> Tuple[int, List[int]]:
    """Primaries of a block of *bw_mhz* centered on channel index *center_idx*.

    Primary channel indices are 4 apart (20 MHz); the outermost primaries sit
    10 MHz (2 indices) inside the block edges.
    """
    n_20 = bw_mhz // 20
    first = center_idx - 2 * (n_20 - 1)
    return center_idx, [first + 4 * i for i in range(n_20)]


# 5 GHz (IEEE 802.11-2020 Annex E, Table E-4 plus the U-NII-4 channels
# 169-177 added by 802.11ax-2021 for FCC).
_5GHZ_BLOCKS: Dict[int, List[Tuple[int, List[int]]]] = {
    40: [_block(c, 40) for c in (38, 46, 54, 62, 102, 110, 118, 126, 134, 142,
                                 151, 159, 167, 175)],
    80: [_block(c, 80) for c in (42, 58, 106, 122, 138, 155, 171)],
    160: [_block(c, 160) for c in (50, 114, 163)],
}

# 6 GHz (IEEE 802.11ax-2021 / 802.11be-2024 Annex E, op classes 132-134, 137).
#   40 MHz centers:  3, 11, … 227        (29 blocks, ch 1-229)
#   80 MHz centers:  7, 23, … 215        (14 blocks, ch 1-221)
#   160 MHz centers: 15, 47, … 207       (7 blocks,  ch 1-221)
#   320 MHz centers: 31/95/159 ("320-1") and 63/127/191 ("320-2") overlap by
#   design; the EHT Operation element's CCFS1 says which one is in use.
_6GHZ_BLOCKS: Dict[int, List[Tuple[int, List[int]]]] = {
    40: [_block(c, 40) for c in range(3, 228, 8)],
    80: [_block(c, 80) for c in range(7, 216, 16)],
    160: [_block(c, 160) for c in range(15, 208, 32)],
    # 320-1 first so it wins when CCFS is unknown and both channelizations
    # contain the primary; 320-2 covers primaries 193-221 that 320-1 cannot.
    320: [_block(c, 320) for c in (31, 95, 159, 63, 127, 191)],
}


def _lookup_block(band: str, primary_chan: int, bw_mhz: int) -> Optional[Tuple[int, List[int]]]:
    tables = _5GHZ_BLOCKS if band == BAND_5 else _6GHZ_BLOCKS if band == BAND_6 else {}
    for center_idx, chans in tables.get(bw_mhz, []):
        if primary_chan in chans:
            return center_idx, chans
    return None


def bonded_block(
    band: str,
    primary_chan: int,
    bw_mhz: int,
    center_freq: Optional[int] = None,
) -> Tuple[int, List[int]]:
    """Resolve (center_MHz, [primary channels]) of the block an AP occupies.

    Resolution order:
      1. *center_freq* — the operating block center decoded from the beacon's
         HT/VHT/HE/EHT Operation element (MHz).  Used only when the primary
         channel actually lies inside that block, so a stale or malformed
         center can never move the AP to the wrong part of the band.
      2. The standard 5/6 GHz block table for (primary, width).
      3. The primary channel alone (20 MHz, or 2.4 GHz 40 MHz with unknown
         secondary-channel direction).
    """
    chan_dict = _BAND_CHANNELS.get(band, {})
    primary_freq = chan_dict.get(primary_chan, 0)
    if bw_mhz <= 20 or not primary_freq:
        return primary_freq, [primary_chan] if primary_chan else []

    half = bw_mhz / 2.0
    if center_freq and abs(primary_freq - center_freq) < half:
        # Primaries whose 20 MHz sub-channel lies wholly inside the block.
        chans = sorted(
            c for c, f in chan_dict.items() if abs(f - center_freq) <= half - 10
        )
        if primary_chan in chans:
            return int(center_freq), chans

    found = _lookup_block(band, primary_chan, bw_mhz)
    if found:
        center_idx, chans = found
        return chan_index_to_freq(center_idx, band), chans
    return primary_freq, [primary_chan]


def get_ap_draw_center(ap: "AccessPoint") -> float:
    """MHz center to use when placing the spectrum shape for *ap*."""
    center, _ = bonded_block(ap.band, ap.channel, ap.bandwidth_mhz, ap.iw_center_freq)
    return float(center or ap.freq_mhz)


def get_ap_channel_span(ap: "AccessPoint") -> str:
    """Human-readable channel span for the table, e.g. "116–128" or "36".

    5 GHz:   "116–128" (80 MHz), "100–128" (160 MHz), "36" (20 MHz).
    2.4 GHz: "6–10" (40 MHz HT40+), "2–6" (40 MHz HT40-).
    6 GHz:   "1–13" (80 MHz), "1–29" (160 MHz), "1–61" (320 MHz).
    """
    if not ap.channel:
        return "?"
    _center, chans = bonded_block(ap.band, ap.channel, ap.bandwidth_mhz, ap.iw_center_freq)
    if len(chans) > 1:
        return f"{chans[0]}–{chans[-1]}"
    return str(ap.channel)


def punctured_subchannels(center_mhz: float, bw_mhz: int, bitmap: int) -> List[Tuple[float, float]]:
    """(lo_MHz, hi_MHz) ranges of EHT-punctured 20 MHz subchannels.

    Bit *i* of the Disabled Subchannel Bitmap (802.11be 9.4.2.322) marks the
    i-th 20 MHz subchannel, counted from the lowest frequency of the BSS
    bandwidth, as punctured.
    """
    if not bitmap or bw_mhz < 80:
        return []
    lo_edge = center_mhz - bw_mhz / 2.0
    out: List[Tuple[float, float]] = []
    for i in range(bw_mhz // 20):
        if bitmap & (1 << i):
            out.append((lo_edge + 20 * i, lo_edge + 20 * (i + 1)))
    return out


# Signal-quality zones in dBm.  Shared by the table, the details panel and the
# graph axes so every view colours the same RSSI identically.
DBM_EXCELLENT = -50
DBM_GOOD = -60
DBM_FAIR = -70
DBM_WEAK = -80


def dbm_color(dbm: float) -> QColor:
    """Map an RSSI in dBm to the shared green → red quality palette."""
    if dbm >= DBM_EXCELLENT:
        return QColor(SIG_EXCELLENT)
    if dbm >= DBM_GOOD:
        return QColor(SIG_GOOD)
    if dbm >= DBM_FAIR:
        return QColor(SIG_FAIR)
    if dbm >= DBM_WEAK:
        return QColor(SIG_WEAK)
    return QColor(SIG_POOR)


def signal_color(signal: int) -> QColor:
    """Map a 0-100 nmcli SIGNAL percentage to the shared dBm palette."""
    return dbm_color(signal_to_dbm(signal))


def signal_to_dbm(signal: int) -> int:
    """Approximate dBm from the nmcli 0-100 SIGNAL value.

    Exact inverse of NetworkManager's nm_wifi_utils_level_to_quality()
    (src/core/nm-core-utils.c), which maps the scan RSSI linearly from
    -100 dBm (0 %) to -40 dBm (100 %):
        quality = 100 - (|clamp(dBm, -100, -40) + 40| × 100 / 60)
    Only used when iw did not report the exact dBm for this BSS.
    """
    q = max(0, min(100, int(signal)))
    return int(round(-40 - (100 - q) * 0.6))


def ap_group_key(bssid: str) -> str:
    """Compute the AP-group key for a BSSID.

    Groups BSSIDs belonging to the same physical AP by:
      * masking the low nibble (4 bits) of the last octet — most enterprise
        APs allocate a contiguous 16-address BSSID block for their SSIDs; and
      * clearing the locally-administered (U/L) bit of the first octet — many
        vendors derive extra radio/SSID BSSIDs by setting that bit on the
        base MAC (e.g. 5C:22:8B:… and 5E:22:8B:…).

    Returns a normalised upper-case string, e.g. 'AC:2A:A1:33:16:E0'.
    If the BSSID is malformed the uppercased input is returned unchanged.
    """
    parts = re.split(r"[:\-]", bssid.strip().upper())
    if len(parts) != 6:
        return bssid.upper()
    try:
        first = int(parts[0], 16) & 0xFD  # clear U/L bit
        last = int(parts[5], 16) & 0xF0
        parts[0] = f"{first:02X}"
        parts[5] = f"{last:02X}"
        return ":".join(parts)
    except ValueError:
        return bssid.upper()


def _mac_octets(mac: str) -> Optional[List[int]]:
    parts = re.split(r"[:\-]", (mac or "").strip())
    if len(parts) != 6:
        return None
    try:
        return [int(x, 16) for x in parts]
    except ValueError:
        return None


def laa_derived_pair(a: str, b: str) -> bool:
    """True when one BSSID looks derived from the other by the common
    "locally-administered first octet" scheme.

    Several vendors create extra per-SSID/per-radio BSSIDs by rewriting the
    first octet of the base MAC and setting its locally-administered (U/L)
    bit, sometimes also using the low nibble of the last octet as an index:
        84:78:48:EA:44:D7  →  8A:78:48:EA:44:D7
        54:B7:BD:F9:AB:9D  →  6A:B7:BD:F9:AB:99
    Rule: at least one address is locally administered, octets 2-5 are
    identical and the high nibble of octet 6 is identical — i.e. 36
    device-specific bits match exactly.  Two *different* APs of one vendor
    have unique MACs, so they never satisfy this; two universally-
    administered BSSIDs (e.g. neighbouring Cisco APs …:22:40 / …:22:50) are
    never matched by it at all.
    """
    oa, ob = _mac_octets(a), _mac_octets(b)
    if oa is None or ob is None or oa == ob:
        return False
    if not ((oa[0] | ob[0]) & 0x02):
        return False
    return oa[1:5] == ob[1:5] and (oa[5] & 0xF0) == (ob[5] & 0xF0)


def similar_signal(a: "AccessPoint", b: "AccessPoint", max_db: float = 3.0) -> bool:
    """True when two BSSs are received at about the same level.

    Never mixes sources: an exact iw dBm and a dBm estimated from nmcli's
    percentage can disagree by several dB.  When either BSS lacks an exact
    value both are compared on nmcli's SIGNAL scale, where NetworkManager
    maps 60 dB onto 100 %, so max_db dB ≈ max_db × 100/60 percentage points.
    """
    if a.dbm_exact is not None and b.dbm_exact is not None:
        return abs(a.dbm_exact - b.dbm_exact) <= max_db
    return abs(a.signal - b.signal) <= max_db * 100.0 / 60.0


def bssids_related(a: "AccessPoint", b: "AccessPoint") -> bool:
    """BSSID-level evidence that two BSSs belong to the same physical AP.

    Used only together with RF evidence (same channel, width, block center
    and similar RSSI) by the channel graph and radio-parameter inheritance.
    """
    if a.mld_mac and a.mld_mac == b.mld_mac:
        return True
    if ap_group_key_for(a) == ap_group_key_for(b):
        return True
    return laa_derived_pair(a.bssid, b.bssid)


def ap_group_key_for(ap: "AccessPoint") -> str:
    """AP-group key for an AccessPoint.

    Wi-Fi 7 multi-link APs advertise an MLD MAC address shared by every
    affiliated link (2.4/5/6 GHz radio); when present it identifies the
    physical AP far more reliably than BSSID bit patterns.
    """
    mld = getattr(ap, "mld_mac", "") or ""
    return ap_group_key(mld if mld else ap.bssid)
