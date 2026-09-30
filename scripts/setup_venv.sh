#!/usr/bin/env bash
# setup_venv.sh — (Re)build the WaveScope Python environment for the
# system-wide .deb / .rpm install.  Installed as /opt/wavescope/setup-venv.sh
# and run by the package postinst / %post.  Safe to re-run by hand:
#
#     sudo /opt/wavescope/setup-venv.sh
#
# PyQt6 comes from the distro (python3-pyqt6 / python3-qt6) via
# --system-site-packages; only pyqtgraph + numpy are fetched from PyPI,
# pinned by /opt/wavescope/constraints.txt.
#
# Any existing venv is moved aside first and restored if the rebuild fails,
# so a failed run never leaves a half-populated venv behind.  (The venv is
# built at its final path because venv scripts embed absolute paths.)
# Exit status: 0 on success, 1 on failure (the package scripts treat a
# failure as non-fatal and print instructions instead).
set -uo pipefail

APP_DIR="/opt/wavescope"
VENV="$APP_DIR/.venv"
OLD_VENV="$APP_DIR/.venv.old"
CONSTRAINTS="$APP_DIR/constraints.txt"
MOVED_ASIDE=0

fail() {
    echo "" >&2
    echo "WARNING: WaveScope Python environment setup failed: $1" >&2
    echo "  The package is installed, but 'wavescope' will not start until" >&2
    echo "  pyqtgraph and numpy are available.  Check network access to" >&2
    echo "  https://pypi.org, then re-run:" >&2
    echo "      sudo $APP_DIR/setup-venv.sh" >&2
    echo "" >&2
    # Roll back to the previous working venv, if we already moved it aside
    if [ "$MOVED_ASIDE" -eq 1 ]; then
        rm -rf "$VENV"
        [ -d "$OLD_VENV" ] && mv "$OLD_VENV" "$VENV"
    fi
    exit 1
}

command -v python3 >/dev/null 2>&1 || fail "python3 not found"

echo "Setting up Python environment for WaveScope..."
rm -rf "$OLD_VENV"
if [ -d "$VENV" ]; then
    mv "$VENV" "$OLD_VENV" || fail "could not move old venv aside"
fi
MOVED_ASIDE=1
python3 -m venv --system-site-packages "$VENV" \
    || fail "could not create venv (is the python3 venv module installed?)"

PIP_ARGS=(--disable-pip-version-check --no-input --quiet --timeout 30 --retries 3)
[ -f "$CONSTRAINTS" ] && PIP_ARGS+=(-c "$CONSTRAINTS")

"$VENV/bin/python" -m pip install "${PIP_ARGS[@]}" pyqtgraph numpy \
    || fail "pip could not install pyqtgraph/numpy"

# Sanity check: the distro PyQt6 must be visible through system site-packages
"$VENV/bin/python" -c "import PyQt6.QtWidgets, pyqtgraph, numpy" \
    || fail "import check failed (is the distro PyQt6 package installed?)"

# New venv is known good: drop the previous one
rm -rf "$OLD_VENV"

echo "WaveScope ready. Run: wavescope"
exit 0
