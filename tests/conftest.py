"""Shared test setup: import paths and a headless Qt platform."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "devtools"))
# wavescope_app imports PyQt6 widgets; no display is needed for these tests.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
