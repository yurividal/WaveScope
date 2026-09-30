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

VERSION="${1:-$(grep -m1 'VERSION' "$REPO_ROOT/wavescope_app/core_base.py" | grep -oP '[0-9]+\.[0-9]+\.[0-9]+')}" 
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
cp "$REPO_ROOT/main.py" "$REPO_ROOT/requirements.txt" "$REPO_ROOT/constraints.txt" \
   "$REPO_ROOT/LICENSE" "$STAGING/"
cp "$REPO_ROOT/scripts/setup_venv.sh" "$STAGING/setup-venv.sh"
cp -r "$REPO_ROOT/wavescope_app" "$STAGING/"
cp -r "$REPO_ROOT/assets/." "$STAGING/assets/"
# Never ship stale bytecode from the developer's tree
find "$STAGING" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGING" -name '*.py[co]' -delete
tar -czf "$RPM_BUILD_DIR/SOURCES/${TARBALL_NAME}.tar.gz" \
    -C "$RPM_BUILD_DIR" "$TARBALL_NAME"

# ── 3. Write spec file ────────────────────────────────────────────────────────
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
# Qt Python bindings from distro packages (Fedora/RHEL).  python3-pyqt6
# pulls in python3-pyqt6-base, which also carries PyQt6.uic (pyqtgraph
# imports it).  The old name python3-qt6 is not provided on Fedora 44.
Requires:       python3-pyqt6

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
install -dm 755 %{buildroot}/opt/wavescope
install -pm 644 main.py requirements.txt constraints.txt %{buildroot}/opt/wavescope/
install -pm 755 setup-venv.sh %{buildroot}/opt/wavescope/
cp -r wavescope_app %{buildroot}/opt/wavescope/
cp -r assets %{buildroot}/opt/wavescope/

install -dm 755 %{buildroot}/usr/bin
install -dm 755 %{buildroot}/usr/share/applications
install -dm 755 %{buildroot}/usr/share/icons/hicolor/scalable/apps
install -dm 755 %{buildroot}/usr/share/metainfo

# ── /usr/bin/wavescope launcher ───────────────────────────────────────────────
cat > %{buildroot}/usr/bin/wavescope <<'LAUNCHER'
#!/usr/bin/env bash
if [ ! -x /opt/wavescope/.venv/bin/python ]; then
    echo "WaveScope: Python environment missing (install-time pip step failed?)." >&2
    echo "Fix with:  sudo /opt/wavescope/setup-venv.sh" >&2
    exit 1
fi
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
Categories=Network;Monitor;
Keywords=wifi;wireless;network;analyzer;
StartupWMClass=wavescope
DESKTOP

# ── Icon ──────────────────────────────────────────────────────────────────────
install -pm 644 assets/icon.svg \
    %{buildroot}/usr/share/icons/hicolor/scalable/apps/wavescope.svg
install -pm 644 assets/io.github.yurividal.WaveScope.appdata.xml \
    %{buildroot}/usr/share/metainfo/

%post
# pip needs network access to PyPI.  Deliberately non-fatal so a failure
# never makes the rpm transaction report a scriptlet error; setup-venv.sh
# prints recovery instructions (sudo /opt/wavescope/setup-venv.sh).
/opt/wavescope/setup-venv.sh || \
    echo "WaveScope: continuing without a Python environment (see warning above)." >&2
exit 0

%preun
if [ \$1 -eq 0 ]; then
    rm -rf /opt/wavescope/.venv /opt/wavescope/.venv.old
fi

%files
%license LICENSE
%dir /opt/wavescope
/opt/wavescope/main.py
/opt/wavescope/requirements.txt
/opt/wavescope/constraints.txt
/opt/wavescope/setup-venv.sh
/opt/wavescope/wavescope_app/
/opt/wavescope/assets/
/usr/bin/wavescope
/usr/share/applications/wavescope.desktop
/usr/share/icons/hicolor/scalable/apps/wavescope.svg
/usr/share/metainfo/io.github.yurividal.WaveScope.appdata.xml

%changelog
* $(date "+%a %b %d %Y") WaveScope Contributors <https://github.com/yurividal/WaveScope> - ${VERSION}-1
- See https://github.com/yurividal/WaveScope/releases for full changelog
SPEC

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
