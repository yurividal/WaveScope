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
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from wavescope_app.core import APP_NAME, can_scan_at_all, find_missing_tools, tool_notices, warn_missing_tools_and_confirm
from wavescope_app.main_window import MainWindow
from wavescope_app.theme import _dark_palette, GRAPH_BG_DARK, GRAPH_AXIS_DARK


def main():
    # Exercise packaged imports, assets and the complete window in CI without
    # Wi-Fi hardware, dependency dialogs or a Location Services prompt.
    smoke_test = "--smoke-test" in sys.argv
    # ── Pyqtgraph config must come before QApplication ─────────────────────
    pg.setConfigOptions(
        antialias=True, foreground=GRAPH_AXIS_DARK, background=GRAPH_BG_DARK
    )

    app = QApplication([arg for arg in sys.argv if arg != "--smoke-test"])
    # setDesktopFileName must come before setApplicationName / setOrganizationName
    # to avoid the portal "Connection already associated with an application ID" error.
    app.setDesktopFileName("wavescope")  # GNOME dock grouping / WM_CLASS hint
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("wavescope")
    app.setStyle("Fusion")

    icon_path = Path(__file__).parent / "assets" / "icon.svg"
    if smoke_test:
        for name in ("icon.svg", "vendors.json", "vendor_urls.json"):
            if not (icon_path.parent / name).is_file():
                raise RuntimeError(f"Packaged asset is missing: {name}")
        if sys.platform == "darwin":
            from wavescope_app.macos_wifi import corewlan_available

            if not corewlan_available():
                raise RuntimeError("Packaged CoreWLAN / CoreLocation bindings are missing")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    app.setPalette(_dark_palette())

    # Only when no data source can work at all is a blocking dialog shown;
    # absent optional tools (NetworkManager, tcpdump, pkexec) are reported in
    # an in-window notice so the app always opens with its normal window.
    if not smoke_test and not can_scan_at_all():
        missing = find_missing_tools()
        if missing and not warn_missing_tools_and_confirm(missing):
            sys.exit(1)

    for name in ("Inter", "Segoe UI", "Ubuntu", "Noto Sans", "DejaVu Sans"):
        font = QFont(name, 10)
        if font.exactMatch():
            break
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)

    win = MainWindow(start_scanner=not smoke_test)
    win.show_tool_notices(tool_notices())
    win.showMaximized()
    if smoke_test:
        QTimer.singleShot(250, win.close)
    elif sys.platform == "darwin":
        from wavescope_app.macos_permissions import request_location_access

        def request_macos_permission():
            # CoreLocation must be created on the foreground GUI thread;
            # retain the manager for the lifetime of the window.
            win._location_manager, notice = request_location_access()
            if notice and notice != getattr(win, "_location_notice", ""):
                win._on_status_note(notice)
            win._location_notice = notice

        QTimer.singleShot(0, request_macos_permission)
        # Enabling global Location Services while the app is open may still
        # require the first authorization request. The helper is idempotent.
        win._location_timer = QTimer(win)
        win._location_timer.timeout.connect(request_macos_permission)
        win._location_timer.start(2000)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
