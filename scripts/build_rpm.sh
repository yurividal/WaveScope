#!/usr/bin/env bash
# build_rpm.sh — Build an .rpm package for WaveScope
# Usage: ./scripts/build_rpm.sh [version]
# Example: ./scripts/build_rpm.sh 1.3.1
#
# Requires: rpm-build
#   Fedora/RHEL:  sudo dnf install rpm-build
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

VERSION="${1:-$(grep -m1 'VERSION' "$REPO_ROOT/main.py" | grep -oP '"[0-9]+\.[0-9]+\.[0-9]+"' | tr -d '"')}"
PKGNAME="wavescope"
RPM_BUILD_DIR="$REPO_ROOT/_rpm_build"
TARBALL_NAME="${PKGNAME}-${VERSION}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Building WaveScope v${VERSION}  →  .rpm"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Cleanup & scaffold ─────────────────────────────────────────────────────
rm -rf "$RPM_BUILD_DIR"
mkdir -p \
    "$RPM_BUILD_DIR/SPECS" \
    "$RPM_BUILD_DIR/SOURCES" \
    "$RPM_BUILD_DIR/BUILD" \
    "$RPM_BUILD_DIR/RPMS" \
    "$RPM_BUILD_DIR/SRPMS"

# ── 2. Create source tarball ──────────────────────────────────────────────────
STAGING="$RPM_BUILD_DIR/$TARBALL_NAME"
mkdir -p "$STAGING/assets"
cp "$REPO_ROOT/main.py" "$REPO_ROOT/requirements.txt" "$STAGING/"
cp "$REPO_ROOT/assets/icon.svg" "$STAGING/assets/"
[ -f "$REPO_ROOT/assets/screenshot.png" ] && cp "$REPO_ROOT/assets/screenshot.png" "$STAGING/assets/" || true
tar -czf "$RPM_BUILD_DIR/SOURCES/${TARBALL_NAME}.tar.gz" \
    -C "$RPM_BUILD_DIR" "$TARBALL_NAME"

# ── 3. Write spec file ────────────────────────────────────────────────────────
HAS_SCREENSHOT=0
[ -f "$REPO_ROOT/assets/screenshot.png" ] && HAS_SCREENSHOT=1

cat > "$RPM_BUILD_DIR/SPECS/${PKGNAME}.spec" <<SPEC
Name:           ${PKGNAME}
Version:        ${VERSION}
Release:        1%{?dist}
Summary:        Modern WiFi Analyzer for Linux
License:        MIT
URL:            https://github.com/yurividal/WaveScope
Source0:        ${TARBALL_NAME}.tar.gz
BuildArch:      noarch

# ── Runtime dependencies (Fedora/RHEL package names) ─────────────────────────
Requires:       python3 >= 3.10
Requires:       python3-pip
Requires:       NetworkManager
Requires:       iw
Requires:       tcpdump
Requires:       polkit
Requires:       xcb-util-cursor
# PyQt6 is available in Fedora repos; pip fallback handled in %%post
Recommends:     python3-pyqt6

%description
WaveScope is a fast, modern WiFi analyzer for Linux built with PyQt6.
It displays real-time channel occupancy graphs, signal history,
per-AP metadata (security, WiFi generation, OUI manufacturer,
channel utilization, k/v/r roaming support) and supports both
dark and light themes.

Requires NetworkManager (nmcli) and iw for full functionality.

%prep
%autosetup -n ${TARBALL_NAME}

%install
install -dm 755 %{buildroot}/opt/wavescope/assets
install -pm 644 main.py requirements.txt %{buildroot}/opt/wavescope/
install -pm 644 assets/icon.svg %{buildroot}/opt/wavescope/assets/
if [ -f assets/screenshot.png ]; then
    install -pm 644 assets/screenshot.png %{buildroot}/opt/wavescope/assets/
fi

install -dm 755 %{buildroot}/usr/bin
install -dm 755 %{buildroot}/usr/share/applications
install -dm 755 %{buildroot}/usr/share/icons/hicolor/scalable/apps

# ── /usr/bin/wavescope launcher ───────────────────────────────────────────────
cat > %{buildroot}/usr/bin/wavescope <<'LAUNCHER'
#!/usr/bin/env bash
exec /opt/wavescope/.venv/bin/python /opt/wavescope/main.py "\$@"
LAUNCHER
chmod 0755 %{buildroot}/usr/bin/wavescope

# ── .desktop entry ────────────────────────────────────────────────────────────
cat > %{buildroot}/usr/share/applications/wavescope.desktop <<'DESKTOP'
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
DESKTOP

# ── Icon ──────────────────────────────────────────────────────────────────────
install -pm 644 assets/icon.svg \
    %{buildroot}/usr/share/icons/hicolor/scalable/apps/wavescope.svg

%post
VENV="/opt/wavescope/.venv"
echo "▸ Setting up Python environment for WaveScope…"
python3 -m venv "\$VENV"
"\$VENV/bin/pip" install --upgrade pip -q
"\$VENV/bin/pip" install --quiet \\
    "PyQt6>=6.4.0" \\
    "pyqtgraph>=0.13.0" \\
    "numpy>=1.23.0"
echo "✓ WaveScope ready. Run: wavescope"

%preun
if [ \$1 -eq 0 ]; then
    rm -rf /opt/wavescope/.venv
fi

%files
/opt/wavescope/main.py
/opt/wavescope/requirements.txt
/opt/wavescope/assets/icon.svg
/usr/bin/wavescope
/usr/share/applications/wavescope.desktop
/usr/share/icons/hicolor/scalable/apps/wavescope.svg

%changelog
* $(date "+%a %b %d %Y") WaveScope Contributors <https://github.com/yurividal/WaveScope> - ${VERSION}-1
- See https://github.com/yurividal/WaveScope/releases for full changelog
SPEC

# Append screenshot to %files if it exists
if [ "$HAS_SCREENSHOT" -eq 1 ]; then
    sed -i 's|/opt/wavescope/assets/icon.svg|/opt/wavescope/assets/icon.svg\n/opt/wavescope/assets/screenshot.png|' \
        "$RPM_BUILD_DIR/SPECS/${PKGNAME}.spec"
fi

# ── 4. Build the RPM ──────────────────────────────────────────────────────────
rpmbuild --define "_topdir $RPM_BUILD_DIR" \
         -bb "$RPM_BUILD_DIR/SPECS/${PKGNAME}.spec"

# ── 5. Copy output to project root ───────────────────────────────────────────
RPM_FILE=$(find "$RPM_BUILD_DIR/RPMS" -name "*.rpm" | head -1)
if [[ -n "$RPM_FILE" ]]; then
    cp "$RPM_FILE" "$REPO_ROOT/"
    RPM_BASENAME="$(basename "$RPM_FILE")"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  ✓ Built: $RPM_BASENAME"
    echo ""
    echo "  Install:  sudo dnf install ./$RPM_BASENAME"
    echo "  Run:      wavescope"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
fi

# Cleanup
rm -rf "$RPM_BUILD_DIR"
