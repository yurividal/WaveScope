#!/usr/bin/env python3
"""WaveScope application entrypoint.

This file bootstraps QApplication and launches the modularized MainWindow.
Core logic and UI components are split under the `wavescope_app` package.
"""

import os
import sys
from pathlib import Path


def _restore_host_env_for_children() -> None:
    """Inside the AppImage, stop the bundled runtime leaking into subprocesses.

    The AppImage launcher points PYTHONHOME/PYTHONPATH and LD_LIBRARY_PATH at
    the bundled Python and libraries.  This process has already consumed them
    (the dynamic loader reads LD_LIBRARY_PATH once, at startup, and keeps
    using it for Qt's plugin dlopen), so resetting os.environ here only
    changes what child processes — nmcli, iw, pkexec, systemctl — inherit.
    """
    if os.environ.get("WAVESCOPE_APPIMAGE") != "1":
        return
    for var in ("PYTHONHOME", "PYTHONPATH"):
        os.environ.pop(var, None)
    host_ld = os.environ.pop("WAVESCOPE_HOST_LD_LIBRARY_PATH", "")
    if host_ld:
        os.environ["LD_LIBRARY_PATH"] = host_ld
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)


_restore_host_env_for_children()

import pyqtgraph as pg
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication

from wavescope_app.core import APP_NAME, can_scan_at_all, find_missing_tools, tool_notices, warn_missing_tools_and_confirm
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

    # Only when no data source can work at all is a blocking dialog shown;
    # absent optional tools (NetworkManager, tcpdump, pkexec) are reported in
    # an in-window notice so the app always opens with its normal window.
    if not can_scan_at_all():
        missing = find_missing_tools()
        if missing and not warn_missing_tools_and_confirm(missing):
            sys.exit(1)

    for name in ("Inter", "Segoe UI", "Ubuntu", "Noto Sans", "DejaVu Sans"):
        font = QFont(name, 10)
        if font.exactMatch():
            break
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)

    win = MainWindow()
    win.show_tool_notices(tool_notices())
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
