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
from wavescope_app.theme import _dark_palette


def main():
    # ── Pyqtgraph config must come before QApplication ─────────────────────
    plot_bg = "#0d1117"
    pg.setConfigOptions(antialias=True, foreground="#a9b4cc", background=plot_bg)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("wavescope")  # GNOME dock grouping / WM_CLASS hint
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
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
