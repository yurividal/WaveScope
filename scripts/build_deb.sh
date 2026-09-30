#!/usr/bin/env bash
# build_deb.sh — Build a .deb package for WaveScope
# Usage: ./scripts/build_deb.sh [version]
# Example: ./scripts/build_deb.sh 1.0.0
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

VERSION="${1:-$(grep -m1 'VERSION' "$REPO_ROOT/wavescope_app/core_base.py" | grep -oP '[0-9]+\.[0-9]+\.[0-9]+')}" 
ARCH="all"
PKGNAME="wavescope"
BUILD_DIR="$REPO_ROOT/_deb_build"
DEB_ROOT="$BUILD_DIR/${PKGNAME}_${VERSION}_${ARCH}"
INSTALL_DIR="$DEB_ROOT/opt/wavescope"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Building WaveScope v${VERSION}  →  .deb"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Cleanup & scaffold ─────────────────────────────────────────────────────
rm -rf "$BUILD_DIR"
mkdir -p \
    "$INSTALL_DIR/assets" \
    "$DEB_ROOT/usr/bin" \
    "$DEB_ROOT/usr/share/applications" \
    "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps" \
    "$DEB_ROOT/usr/share/metainfo" \
    "$DEB_ROOT/usr/share/doc/$PKGNAME" \
    "$DEB_ROOT/DEBIAN"

# ── 2. Copy application files ─────────────────────────────────────────────────
cp "$REPO_ROOT/main.py" "$REPO_ROOT/requirements.txt" "$REPO_ROOT/constraints.txt" "$INSTALL_DIR/"
cp -r "$REPO_ROOT/wavescope_app" "$INSTALL_DIR/"
cp -r "$REPO_ROOT/assets/." "$INSTALL_DIR/assets/"
# Never ship stale bytecode from the developer's tree
find "$INSTALL_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$INSTALL_DIR" -name '*.py[co]' -delete
# venv (re)build helper, shared with the RPM packages
cp "$REPO_ROOT/scripts/setup_venv.sh" "$INSTALL_DIR/setup-venv.sh"

# Debian policy: copyright file in /usr/share/doc/<pkg>/
{
    echo "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/"
    echo "Upstream-Name: WaveScope"
    echo "Source: https://github.com/yurividal/WaveScope"
    echo ""
    echo "Files: *"
    echo "Copyright: 2026 WaveScope Contributors"
    echo "License: MIT"
    # License body: every line indented one space, blank lines as " ."
    sed -e 's/^$/./' -e 's/^/ /' "$REPO_ROOT/LICENSE"
} > "$DEB_ROOT/usr/share/doc/$PKGNAME/copyright"

# ── 3. DEBIAN/control ────────────────────────────────────────────────────────
# pyqt6-dev-tools: Debian/Ubuntu ship the PyQt6.uic module there, and
# pyqtgraph (>= 0.13) does `from PyQt6 import sip, uic` at import time.
cat > "$DEB_ROOT/DEBIAN/control" <<EOF
Package: $PKGNAME
Version: $VERSION
Architecture: $ARCH
Maintainer: WaveScope Contributors <https://github.com/yurividal/WaveScope>
Depends: python3 (>= 3.10), python3-pip, python3-venv, python3-pyqt6, pyqt6-dev-tools, network-manager, iw, tcpdump, polkitd | policykit-1 | polkit | pkexec, libxcb-cursor0, libxcb-xinerama0, libxcb-randr0
Section: net
Priority: optional
Homepage: https://github.com/yurividal/WaveScope
Description: Modern WiFi Analyzer for Linux
 WaveScope is a fast, modern WiFi analyzer for Linux built with PyQt6.
 It displays real-time channel occupancy graphs, signal history, 
 per-AP metadata (security, WiFi generation, OUI manufacturer, 
 channel utilization, k/v/r roaming support) and supports both
 dark and light themes.
 .
 Requires NetworkManager (nmcli) and iw for full functionality.
EOF

# ── 4. DEBIAN/postinst — install Python deps into /opt/wavescope/.venv ───────
# The pip step needs network access to PyPI.  It is deliberately non-fatal:
# a failure must not leave the package half-configured in dpkg (which would
# block every later apt run).  setup-venv.sh prints recovery instructions.
cat > "$DEB_ROOT/DEBIAN/postinst" <<'EOF'
#!/usr/bin/env bash
set -e
if [ "$1" = "configure" ]; then
    /opt/wavescope/setup-venv.sh || \
        echo "WaveScope: continuing without a Python environment (see warning above)." >&2
fi
# Refresh desktop and icon caches so GNOME/KDE launchers pick up the entry
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database /usr/share/applications || true
fi
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
fi
exit 0
EOF
chmod 0755 "$DEB_ROOT/DEBIAN/postinst"

# ── 5. DEBIAN/prerm — clean up venv on uninstall ─────────────────────────────
cat > "$DEB_ROOT/DEBIAN/prerm" <<'EOF'
#!/usr/bin/env bash
rm -rf /opt/wavescope/.venv /opt/wavescope/.venv.old
EOF
chmod 0755 "$DEB_ROOT/DEBIAN/prerm"

# ── 5b. DEBIAN/postrm — refresh caches after uninstall ───────────────────────
cat > "$DEB_ROOT/DEBIAN/postrm" <<'EOF'
#!/usr/bin/env bash
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database /usr/share/applications
fi
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor
fi
EOF
chmod 0755 "$DEB_ROOT/DEBIAN/postrm"

# ── 6. /usr/bin/wavescope launcher ───────────────────────────────────────────
cat > "$DEB_ROOT/usr/bin/wavescope" <<'EOF'
#!/usr/bin/env bash
if [ ! -x /opt/wavescope/.venv/bin/python ]; then
    echo "WaveScope: Python environment missing (install-time pip step failed?)." >&2
    echo "Fix with:  sudo /opt/wavescope/setup-venv.sh" >&2
    exit 1
fi
exec /opt/wavescope/.venv/bin/python /opt/wavescope/main.py "$@"
EOF
chmod 0755 "$DEB_ROOT/usr/bin/wavescope"

# ── 7. .desktop entry ────────────────────────────────────────────────────────
cat > "$DEB_ROOT/usr/share/applications/wavescope.desktop" <<EOF
[Desktop Entry]
Name=WaveScope
Comment=Modern WiFi Analyzer for Linux
Exec=wavescope
Icon=wavescope
Terminal=false
Type=Application
Categories=Network;Monitor;
Keywords=wifi;wireless;network;analyzer;
StartupWMClass=wavescope
EOF

# ── 8. Icon ──────────────────────────────────────────────────────────────────
cp "$REPO_ROOT/assets/icon.svg" "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps/wavescope.svg"

# ── 8b. AppStream metainfo (software centers) ───────────────────────────────
cp "$REPO_ROOT/assets/io.github.yurividal.WaveScope.appdata.xml" "$DEB_ROOT/usr/share/metainfo/"

# ── 9. Fix permissions ───────────────────────────────────────────────────────
find "$DEB_ROOT" -type d -exec chmod 0755 {} \;
find "$DEB_ROOT" -type f -exec chmod 0644 {} \;   # covers /opt AND /usr/share
chmod 0755 "$DEB_ROOT/usr/bin/wavescope" "$INSTALL_DIR/setup-venv.sh"
chmod 0755 "$DEB_ROOT/DEBIAN/postinst" "$DEB_ROOT/DEBIAN/prerm" "$DEB_ROOT/DEBIAN/postrm"

# ── 10. Build the .deb ───────────────────────────────────────────────────────
dpkg-deb --build --root-owner-group "$DEB_ROOT"
DEB_FILE="${PKGNAME}_${VERSION}_${ARCH}.deb"
mv -f "${DEB_ROOT}.deb" "$REPO_ROOT/$DEB_FILE"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Built: $DEB_FILE"
echo ""
echo "  Install:   sudo dpkg -i $DEB_FILE"
echo "  Run:       wavescope"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Cleanup
rm -rf "$BUILD_DIR"
