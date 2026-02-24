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
