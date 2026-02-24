#!/usr/bin/env python3
"""WaveScope application entrypoint.

This file bootstraps QApplication and launches the modularized MainWindow.
Core logic and UI components are split under the `wavescope_app` package.
"""

import sys
from pathlib import Path

import pyqtgraph as pg
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication

from wavescope_app.core import APP_NAME
from wavescope_app.main_window import MainWindow
from wavescope_app.theme import _dark_palette, GRAPH_BG_DARK, GRAPH_AXIS_DARK


def main():
    # ── Pyqtgraph config must come before QApplication ─────────────────────
    pg.setConfigOptions(
        antialias=True, foreground=GRAPH_AXIS_DARK, background=GRAPH_BG_DARK
    )

    app = QApplication(sys.argv)
    # setDesktopFileName must come before setApplicationName / setOrganizationName
    # to avoid the portal "Connection already associated with an application ID" error.
    app.setDesktopFileName("wavescope")  # GNOME dock grouping / WM_CLASS hint
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("wavescope")
    app.setStyle("Fusion")

    icon_path = Path(__file__).parent / "assets" / "icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    app.setPalette(_dark_palette())

    for name in ("Inter", "Segoe UI", "Ubuntu", "Noto Sans", "DejaVu Sans"):
        font = QFont(name, 10)
        if font.exactMatch():
            break
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)

    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
