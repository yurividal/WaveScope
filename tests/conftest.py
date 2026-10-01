"""Shared test setup: import paths and a headless Qt platform."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "devtools"))
# wavescope_app imports PyQt6 widgets; no display is needed for these tests.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# One QApplication for the whole session (widget tests need it; tests that
# only need an event loop reuse it via QCoreApplication.instance()).
from PyQt6.QtWidgets import QApplication  # noqa: E402

_qapp = QApplication.instance() or QApplication([])
