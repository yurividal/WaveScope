#!/usr/bin/env bash
# install.sh — Set up and launch WaveScope from source
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  WaveScope — Install & Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if ! command -v nmcli &>/dev/null; then
    echo "ERROR: nmcli not found."; echo "Install:  sudo apt install network-manager"; exit 1
fi
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found."; echo "Install:  sudo apt install python3 python3-venv python3-pip"; exit 1
fi

echo ""
echo "▸ Checking system Qt/XCB dependencies…"
MISSING_PKGS=""
for pkg in libxcb-cursor0 libxcb-xinerama0 libxcb-randr0; do
    dpkg -s "$pkg" &>/dev/null 2>&1 || MISSING_PKGS="$MISSING_PKGS $pkg"
done
[ -n "$MISSING_PKGS" ] && sudo apt-get install -y $MISSING_PKGS

[ ! -d "$VENV" ] && { echo ""; echo "▸ Creating Python venv…"; python3 -m venv "$VENV"; }

echo ""
echo "▸ Installing Python packages…"
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" -q

printf '#!/usr/bin/env bash\ncd "$(dirname "$0")"\nexport GIO_LAUNCHED_DESKTOP_FILE="$HOME/.local/share/applications/wavescope.desktop"\nexport GIO_LAUNCHED_DESKTOP_FILE_PID=$$\nexec .venv/bin/python main.py "$@"\n' > "$SCRIPT_DIR/wavescope"
chmod +x "$SCRIPT_DIR/wavescope"

DESKTOP_DIR="$HOME/.local/share/applications"
# Only install the user-level desktop file when NOT installed via .deb (which
# puts the authoritative entry in /usr/share/applications).  A user-level file
# shadows the system one and would point to the wrong launcher after a .deb install.
if ! [ -f /usr/share/applications/wavescope.desktop ]; then
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP_DIR/wavescope.desktop" << DESKEOF
[Desktop Entry]
Name=WaveScope
Comment=Modern WiFi Analyzer for Linux
Exec=$SCRIPT_DIR/wavescope
Icon=$SCRIPT_DIR/assets/icon.svg
Terminal=false
Type=Application
Categories=Network;Utility;
Keywords=wifi;wireless;network;
StartupWMClass=wavescope
DESKEOF
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Install complete!  Run: ./wavescope"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
