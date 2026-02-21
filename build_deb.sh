#!/usr/bin/env bash
# build_deb.sh — Build a .deb package for WaveScope
# Usage: ./build_deb.sh [version]
# Example: ./build_deb.sh 1.0.0
set -euo pipefail

VERSION="${1:-$(grep -m1 'VERSION' main.py | grep -oP '\"[0-9]+\.[0-9]+\.[0-9]+\"' | tr -d '"')}"
ARCH="all"
PKGNAME="wavescope"
BUILD_DIR="$(pwd)/_deb_build"
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
    "$DEB_ROOT/DEBIAN"

# ── 2. Copy application files ─────────────────────────────────────────────────
cp main.py requirements.txt "$INSTALL_DIR/"
cp assets/icon.svg "$INSTALL_DIR/assets/"
[[ -f assets/screenshot.png ]] && cp assets/screenshot.png "$INSTALL_DIR/assets/"

# ── 3. DEBIAN/control ────────────────────────────────────────────────────────
cat > "$DEB_ROOT/DEBIAN/control" <<EOF
Package: $PKGNAME
Version: $VERSION
Architecture: $ARCH
Maintainer: WaveScope Contributors <https://github.com/yurividal/WaveScope>
Depends: python3 (>= 3.10), python3-pip, python3-venv, network-manager, iw, libxcb-cursor0, libxcb-xinerama0, libxcb-randr0
Recommends: python3-pyqt6
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
cat > "$DEB_ROOT/DEBIAN/postinst" <<'EOF'
#!/usr/bin/env bash
set -e
VENV="/opt/wavescope/.venv"
echo "▸ Setting up Python environment for WaveScope…"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install --quiet \
    "PyQt6>=6.4.0" \
    "pyqtgraph>=0.13.0" \
    "numpy>=1.23.0"
echo "✓ WaveScope ready. Run: wavescope"
EOF
chmod 0755 "$DEB_ROOT/DEBIAN/postinst"

# ── 5. DEBIAN/prerm — clean up venv on uninstall ─────────────────────────────
cat > "$DEB_ROOT/DEBIAN/prerm" <<'EOF'
#!/usr/bin/env bash
rm -rf /opt/wavescope/.venv
EOF
chmod 0755 "$DEB_ROOT/DEBIAN/prerm"

# ── 6. /usr/bin/wavescope launcher ───────────────────────────────────────────
cat > "$DEB_ROOT/usr/bin/wavescope" <<'EOF'
#!/usr/bin/env bash
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
Categories=Network;Utility;
Keywords=wifi;wireless;network;analyzer;
StartupWMClass=wavescope
EOF

# ── 8. Icon ──────────────────────────────────────────────────────────────────
cp assets/icon.svg "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps/wavescope.svg"

# ── 9. Fix permissions ───────────────────────────────────────────────────────
find "$DEB_ROOT" -type d -exec chmod 0755 {} \;
find "$DEB_ROOT/opt" -type f -exec chmod 0644 {} \;
chmod 0755 "$DEB_ROOT/DEBIAN/postinst" "$DEB_ROOT/DEBIAN/prerm"

# ── 10. Build the .deb ───────────────────────────────────────────────────────
dpkg-deb --build --root-owner-group "$DEB_ROOT"
DEB_FILE="${PKGNAME}_${VERSION}_${ARCH}.deb"
mv "${DEB_ROOT}.deb" "./$DEB_FILE"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Built: $DEB_FILE"
echo ""
echo "  Install:   sudo dpkg -i $DEB_FILE"
echo "  Run:       wavescope"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Cleanup
rm -rf "$BUILD_DIR"
