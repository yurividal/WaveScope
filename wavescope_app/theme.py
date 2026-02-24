"""Theme palette helpers.

Contains dark/light QPalette builders used by the application entrypoint
and runtime theme switching.
"""

from PyQt6.QtGui import QColor, QPalette


# ── Shared color constants ──────────────────────────────────────────────────

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

IW_GEN_COLORS = {
    "WiFi 7": "#6A1B9A",  # deep purple
    "WiFi 6E": "#AD1457",  # raspberry
    "WiFi 6": "#1565C0",  # royal blue
    "WiFi 5": "#00695C",  # dark teal
    "WiFi 4": "#2E7D32",  # dark green
}

# Sub-band name → colour (for second-level tick labels on x-axis)
UNII_NAME_COLORS = {
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


def _build_unii_chan_colors() -> dict[int, str]:
    colors: dict[int, str] = {}
    for ch in [32, 36, 40, 44, 48]:
        colors[ch] = "#81c995"  # U-NII-1
    for ch in [52, 56, 60, 64]:
        colors[ch] = "#64b5f6"  # U-NII-2A
    for ch in [100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144]:
        colors[ch] = "#ffcc80"  # U-NII-2C
    for ch in [149, 153, 157, 161, 165]:
        colors[ch] = "#a5d6a7"  # U-NII-3
    for ch in [169, 173, 177]:
        colors[ch] = "#ef9a9a"  # U-NII-4
    return colors


def _build_unii6_chan_colors() -> dict[int, str]:
    colors: dict[int, str] = {}
    for ch in range(1, 94, 4):  # U-NII-5
        colors[ch] = "#81c995"
    for ch in range(97, 114, 4):  # U-NII-6
        colors[ch] = "#64b5f6"
    for ch in range(117, 186, 4):  # U-NII-7
        colors[ch] = "#ffcc80"
    for ch in range(189, 234, 4):  # U-NII-8
        colors[ch] = "#ef9a9a"
    return colors


UNII_CHAN_COLORS = _build_unii_chan_colors()
UNII6_CHAN_COLORS = _build_unii6_chan_colors()

# Sub-band header strip definitions for each WiFi band.
# Each tuple: (x_start_MHz, x_end_MHz, hex_fill_color, short_label)
BAND_SUBBAND_HEADERS = {
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


# ── Signal quality (dBm scale) ──────────────────────────────────────────────
SIG_EXCELLENT = "#4caf50"  # ≥ −50 dBm — green
SIG_GOOD = "#8bc34a"  # −60 … −50 dBm — lime
SIG_FAIR = "#ffc107"  # −70 … −60 dBm — amber
SIG_WEAK = "#ff9800"  # −80 … −70 dBm — orange
SIG_POOR = "#f44336"  # < −80 dBm — red

# nmcli 0-100 signal quality (slightly different shades from dBm tiers)
SIG_FAIR_NM = "#ffb300"  # nmcli ≥ 50 — deep amber
SIG_WEAK_NM = "#ff7043"  # nmcli ≥ 30 — orange-red
SIG_POOR_NM = "#ef5350"  # nmcli < 30 — red (also used for vendor error)

# ── Graph / plot neutral colours ─────────────────────────────────────────────
GRAPH_BG_DARK = "#0d1117"
GRAPH_BG_LIGHT = "#f0f4f8"
GRAPH_AXIS_DARK = "#8a96b0"
GRAPH_AXIS_LIGHT = "#445566"
GRAPH_FG_DARK = "#a9b4cc"
GRAPH_FG_LIGHT = "#444455"
FALLBACK_GRAY = "#888888"  # default colour when no SSID palette entry matched

# ── DFS channel indicators ────────────────────────────────────────────────────
DFS_AXIS_COLOR = "#64b5f6"  # DFS segment highlight on bottom axis (blue)
DFS_FILL_COLOR = "#a952bd"  # DFS overlay on channel graph (purple)

# ── Channel-allocation table painting ────────────────────────────────────────
ALLOC_GRID_DARK = "#3a4a5e"
ALLOC_GRID_LIGHT = "#8a9ab8"
ALLOC_CELL_BG_DARK = "#18203a"
ALLOC_CELL_BG_LIGHT = "#edf1fb"
ALLOC_LBL_BG_DARK = "#232d40"
ALLOC_LBL_BG_LIGHT = "#d8dfee"
ALLOC_TEXT_DARK = "#dde8f8"
ALLOC_TEXT_LIGHT = "#1a2438"
ALLOC_DIM_DARK = "#6a7e9a"
ALLOC_DIM_LIGHT = "#5a6a82"
ALLOC_WHITE = "#ffffff"
ALLOC_BLACK = "#0a0f1a"
ALLOC_ONBAND_DARK = "#f0f6ff"  # text drawn on top of coloured band cells (dark mode)

# ── Allocation dialog and details-card chrome ─────────────────────────────────
DIALOG_BG_DARK = "#0f1622"
DIALOG_BG_LIGHT = "#ffffff"
DIALOG_BORDER_DARK = "#273248"
DIALOG_BORDER_LIGHT = "#c7d2e3"
DIALOG_TEXT_DARK = "#dfe7f5"
DIALOG_TEXT_LIGHT = "#22314a"
DIALOG_NOTE_DARK = "#8ea0bf"
DIALOG_NOTE_LIGHT = "#4a5a73"
# Details card (slightly deeper background than the allocation dialog)
CARD_BG_DARK = "#121a27"
CARD_VALUE_BG_DARK = DIALOG_BG_DARK
CARD_VALUE_BORDER_DARK = "#2a3850"
CARD_VALUE_BG_LIGHT = "#eef3fb"
CARD_VALUE_BORDER_LIGHT = "#c8d6ee"

# ── Toolbar action buttons ────────────────────────────────────────────────────
BTN_ACCENT = "#7eb8f7"  # button text / link accent
BTN_BORDER = "#2a4a70"  # button border
BTN_HOVER_BG = "#1a2a40"  # hover background
BTN_CHECKED_TEXT = "#f9a825"  # checked / warning amber text
BTN_CHECKED_BORDER = "#7a5a00"  # checked border
BTN_CHECKED_BG = "#2a2010"  # checked background

# ── First-scan overlay ────────────────────────────────────────────────────────
SCAN_OVERLAY_BG = "rgba(10,15,30,210)"
SCAN_OVERLAY_HEADING = "#9bbfe0"
SCAN_OVERLAY_SUB = "#506070"

# ── Table row colours ─────────────────────────────────────────────────────────
TABLE_LINGER_FG = "#4a5a72"  # dimmed row foreground during AP linger period

# ── Security / PMF badge colours ──────────────────────────────────────────────
SEC_BAD = "#b71c1c"  # open / no security
SEC_WPA2 = "#0d47a1"  # WPA2
SEC_WPA3 = "#1b5e20"  # WPA3 or WPA2+WPA3
SEC_OTHER = "#37474F"  # unknown / other
PMF_OPTIONAL = "#e65100"  # PMF optional (amber-orange)
# PMF Required → reuse SEC_WPA3;  PMF None → reuse SEC_BAD

# ── Vendor-status dialog ──────────────────────────────────────────────────────
VENDOR_MUTED = GRAPH_AXIS_DARK  # "#8a96b0" — subdued info text
VENDOR_SUCCESS = SIG_EXCELLENT  # "#4caf50" — success green
VENDOR_ERROR = SIG_POOR_NM  # "#ef5350" — error red

# ── Context menu ──────────────────────────────────────────────────────────────
MENU_BG = "#131926"
MENU_BORDER = "#2a3350"
MENU_TEXT = "#d0d8f0"
MENU_SELECTED = "#1e4a80"

# ── Connected AP highlight ────────────────────────────────────────────────────
CONNECTED_GREEN = "#2e7d32"

# ── Muted / placeholder HTML text ────────────────────────────────────────────
HTML_MUTED = "#777"

# ── Capture window ────────────────────────────────────────────────────────────
CAPTURE_TITLE_FG = "#e0e0e0"
CAPTURE_CARD_MON_BG = "#1a3050"
CAPTURE_CARD_MON_HOVER = "#1e4a80"
CAPTURE_CARD_MGD_BG = "#1a3a1a"
CAPTURE_CARD_MGD_HOVER = "#1e5a22"
CAPTURE_CARD_BORDER = "#334"
CAPTURE_CARD_TITLE_FG = "#ffffff"
CAPTURE_CARD_SUB_FG = "#aad4ff"
CAPTURE_CARD_BODY_FG = "#b0c8d8"
CAPTURE_WARN_BG = "#2a1800"
CAPTURE_WARN_FG = "#ffcc66"
CAPTURE_WARN_BORDER = "#a06010"
CAPTURE_BTN_START_BG = "#1a5c2a"
CAPTURE_BTN_START_FG = "#ccffcc"
CAPTURE_BTN_START_HOVER = "#226b33"
CAPTURE_BTN_DIS_BG = "#1a2210"
CAPTURE_BTN_DIS_FG = "#446644"
CAPTURE_LOG_BG = "#090d14"
CAPTURE_LOG_FG = "#8fa8c0"
CAPTURE_BTN_STOP_BG = "#6b1a1a"
CAPTURE_BTN_STOP_FG = "#ffcccc"
CAPTURE_BTN_STOP_HOVER = "#7f2020"
CAPTURE_BANNER_BG = "#1e2e10"
CAPTURE_BANNER_FG = "#cceeaa"
# Managed-mode–specific
CAPTURE_MGD_STATE_FG = "#88bb88"
CAPTURE_MGD_LOG_BG = "#0e1a0e"
CAPTURE_MGD_LOG_FG = "#a0d8a0"

# ── 2.4 GHz channel plan colours ─────────────────────────────────────────────
PLAN_2G_ISM_HEADER = "#1B5E20"  # ISM band header (dark green)
PLAN_2G_JP_HEADER = "#BF360C"  # Japan ch-14 header (deep orange)
PLAN_CH1 = "#1B5E20"  # ch 1  (NA / EU / JP plans)
PLAN_CH6 = "#1565C0"  # ch 6  (NA) / ch 9 (EU / JP plans)
PLAN_CH11 = "#B71C1C"  # ch 11 (NA plan)
PLAN_EU_CH5 = "#E65100"  # ch 5  (EU 4-ch plan)
PLAN_EU_CH13 = "#880E4F"  # ch 13 (EU 4-ch plan)
PLAN_JP_CH5 = "#4527A0"  # ch 5  (JP 802.11b 22 MHz plan)
PLAN_JP_CH10 = "#00695C"  # ch 10 (JP 802.11b 22 MHz plan)

# ── 5 GHz allocation plan colours ────────────────────────────────────────────
ALLOC_5G_U1 = "#388E3C"  # UNII-1
ALLOC_5G_U2A = "#1976D2"  # UNII-2A
ALLOC_5G_U2C = "#0D47A1"  # UNII-2C (Extended)
ALLOC_5G_U3 = "#E64A19"  # UNII-3
ALLOC_5G_36_48 = "#81C784"  # 36–48: 1 W Tx, no DFS (light green)
ALLOC_5G_52_116 = "#64B5F6"  # 52–64 / 100–116: DFS required (light blue)
ALLOC_5G_120_128 = "#FFD54F"  # 120–128: newly allowed channels (amber)
ALLOC_5G_132_144 = "#5C8BB0"  # 132–144 (steel blue)
ALLOC_5G_149_165 = "#FF8A65"  # 149–165: 1 W EIRP, no DFS (light orange)
ALLOC_5G_DFS_BAND = "#546E7A"  # overall DFS band indicator (blue-grey)

# ── 6 GHz allocation plan colours ────────────────────────────────────────────
ALLOC_6G_U5 = "#2E7D32"  # UNII-5 (dark green)
ALLOC_6G_U6 = "#00695C"  # UNII-6 (dark teal)
ALLOC_6G_U7 = "#1565C0"  # UNII-7 (royal blue)
ALLOC_6G_U8 = "#6A1B9A"  # UNII-8 (deep purple)


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
