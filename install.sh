#!/usr/bin/env bash
# install.sh — Set up and launch WaveScope from source
#
# Supported distros (package manager auto-detected):
#   apt     Debian 12+, Ubuntu 22.04+ and derivatives
#   dnf     Fedora 39+ (RHEL-likes with the same package names)
#   zypper  openSUSE Tumbleweed / Leap
# Other distros: install the equivalent packages by hand, then re-run.
#
# Creates ./.venv (PyQt6 + pyqtgraph + numpy from PyPI, pinned by
# constraints.txt), writes the ./wavescope launcher and a user-level
# desktop entry.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  WaveScope — Install & Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Detect package manager and the system packages it needs ─────────────
# Python + runtime tools (nmcli, iw, tcpdump, pkexec) + the XCB libs the
# PyQt6 pip wheels need for the Qt xcb platform plugin.
PKG_MGR=""
if command -v apt-get &>/dev/null && command -v dpkg &>/dev/null; then
    PKG_MGR="apt"
    PKGS="python3 python3-venv python3-pip network-manager iw tcpdump pkexec libxcb-cursor0 libxcb-xinerama0 libxcb-randr0"
    INSTALL_CMD="sudo apt-get install -y"
elif command -v dnf &>/dev/null; then
    PKG_MGR="dnf"
    PKGS="python3 python3-pip NetworkManager iw tcpdump polkit xcb-util-cursor"
    INSTALL_CMD="sudo dnf install -y"
elif command -v zypper &>/dev/null; then
    PKG_MGR="zypper"
    PKGS="python3 python3-pip NetworkManager iw tcpdump polkit libxcb-cursor0"
    INSTALL_CMD="sudo zypper install -y"
fi

# Return 0 if a package (or something providing it) is installed
pkg_installed() {
    case "$PKG_MGR" in
        apt)        dpkg -s "$1" &>/dev/null ;;
        dnf|zypper) rpm -q --whatprovides "$1" &>/dev/null ;;
        *)          return 1 ;;
    esac
}

echo ""
if [ -z "$PKG_MGR" ]; then
    echo "▸ No supported package manager found (apt/dnf/zypper)."
    echo "  Make sure these are installed: python3 (>= 3.10) with venv + pip,"
    echo "  NetworkManager (nmcli), iw, tcpdump, polkit (pkexec), libxcb-cursor."
else
    echo "▸ Checking system packages ($PKG_MGR)…"
    MISSING_PKGS=""
    for pkg in $PKGS; do
        pkg_installed "$pkg" || MISSING_PKGS="$MISSING_PKGS $pkg"
    done
    if [ -n "$MISSING_PKGS" ]; then
        echo "  Missing:$MISSING_PKGS"
        echo "  Install with:"
        echo "      $INSTALL_CMD$MISSING_PKGS"
        # Only offer to run it when a human is at the terminal
        if [ -t 0 ]; then
            read -r -p "  Run that now? [y/N] " reply
            if [[ "$reply" =~ ^[Yy]$ ]]; then
                # shellcheck disable=SC2086  # word splitting is intended
                $INSTALL_CMD $MISSING_PKGS
            fi
        fi
    else
        echo "  All system packages present."
    fi
fi

# ── 2. Python (hard requirement) ────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install the packages listed above and re-run."
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "ERROR: WaveScope needs Python >= 3.10 (found $(python3 -V 2>&1))."
    exit 1
fi

# ── 3. Runtime tools (WaveScope starts without them, but degraded) ─────────
# iw / tcpdump often live in /usr/sbin, which is not on every user's PATH;
# WaveScope itself falls back to /usr/sbin and /sbin, so do the same here.
have_tool() {
    command -v "$1" &>/dev/null || [ -x "/usr/sbin/$1" ] || [ -x "/sbin/$1" ]
}
echo ""
echo "▸ Checking runtime tools…"
TOOLS_OK=1
have_tool nmcli   || { echo "  WARNING: nmcli not found (NetworkManager) - scanning will not work"; TOOLS_OK=0; }
have_tool iw      || { echo "  WARNING: iw not found - WiFi gen, BSS load, k/v/r and vendor IE data unavailable"; TOOLS_OK=0; }
have_tool tcpdump || { echo "  WARNING: tcpdump not found - packet capture unavailable"; TOOLS_OK=0; }
have_tool pkexec  || { echo "  WARNING: pkexec not found (polkit) - packet capture cannot get root"; TOOLS_OK=0; }
[ "$TOOLS_OK" -eq 1 ] && echo "  nmcli, iw, tcpdump, pkexec: OK"

# ── 4. Python venv ──────────────────────────────────────────────────────────
[ ! -d "$VENV" ] && { echo ""; echo "▸ Creating Python venv…"; python3 -m venv "$VENV"; }

echo ""
echo "▸ Installing Python packages…"
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt" -c "$SCRIPT_DIR/constraints.txt"

# ── 5. Launcher (same content as the committed ./wavescope) ────────────────
cat > "$SCRIPT_DIR/wavescope" <<'LAUNCHEOF'
#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    echo "WaveScope: .venv not found. Run ./install.sh first." >&2
    exit 1
fi
export GIO_LAUNCHED_DESKTOP_FILE="$HOME/.local/share/applications/wavescope.desktop"
export GIO_LAUNCHED_DESKTOP_FILE_PID=$$
exec .venv/bin/python main.py "$@"
LAUNCHEOF
chmod +x "$SCRIPT_DIR/wavescope"

# ── 6. User-level desktop entry + icon ──────────────────────────────────────
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
# Only install the user-level desktop file when NOT installed via .deb/.rpm
# (which puts the authoritative entry in /usr/share/applications).  A
# user-level file shadows the system one and would point to the wrong
# launcher after a package install.
if ! [ -f /usr/share/applications/wavescope.desktop ]; then
    mkdir -p "$DESKTOP_DIR" "$ICON_DIR"
    cp "$SCRIPT_DIR/assets/icon.svg" "$ICON_DIR/wavescope.svg"
    cat > "$DESKTOP_DIR/wavescope.desktop" << DESKEOF
[Desktop Entry]
Name=WaveScope
Comment=Modern WiFi Analyzer for Linux
Exec=$SCRIPT_DIR/wavescope
Icon=wavescope
Terminal=false
Type=Application
Categories=Network;Monitor;
Keywords=wifi;wireless;network;analyzer;
StartupWMClass=wavescope
DESKEOF
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Install complete!  Run: ./wavescope"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
