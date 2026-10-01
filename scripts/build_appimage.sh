#!/usr/bin/env bash
# build_appimage.sh — Build an AppImage package for WaveScope
# Usage: ./scripts/build_appimage.sh [version]
# Example: ./scripts/build_appimage.sh 1.5.0
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

VERSION="${1:-$(grep -m1 'VERSION' "$REPO_ROOT/wavescope_app/core_base.py" | grep -oP '[0-9]+\.[0-9]+\.[0-9]+')}" 
APP_ID="wavescope"
APP_NAME="WaveScope"
ARCH="$(uname -m)"
BUILD_DIR="$REPO_ROOT/_appimage_build"
APPDIR="$BUILD_DIR/${APP_NAME}.AppDir"
APP_PREFIX="$APPDIR/usr/share/${APP_ID}"
PY_RUNTIME="$APP_PREFIX/python-runtime"
OUTPUT_FILE="${APP_NAME}-${VERSION}-${ARCH}.AppImage"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Building ${APP_NAME} v${VERSION}  →  AppImage"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found"
    exit 1
fi
if ! command -v appimagetool >/dev/null 2>&1; then
    echo "ERROR: appimagetool not found"
    echo "Install appimagetool, then run this script again."
    exit 1
fi

# ── 1. Cleanup & scaffold ───────────────────────────────────────────────────
rm -rf "$BUILD_DIR"
mkdir -p \
    "$APPDIR/usr/bin" \
    "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
    "$APPDIR/usr/share/metainfo" \
    "$APP_PREFIX" \
    "$PY_RUNTIME/lib" \
    "$PY_RUNTIME/lib64"

# ── 2. Copy application files ───────────────────────────────────────────────
cp -a "$REPO_ROOT/main.py" "$REPO_ROOT/requirements.txt" "$REPO_ROOT/constraints.txt" \
      "$REPO_ROOT/assets" "$REPO_ROOT/wavescope_app" "$APP_PREFIX/"
# Never ship stale bytecode from the developer's tree
find "$APP_PREFIX" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$APP_PREFIX" -name '*.py[co]' -delete
[ -f "$REPO_ROOT/LICENSE" ] && cp "$REPO_ROOT/LICENSE" "$APP_PREFIX/" || true
[ -f "$REPO_ROOT/README.md" ] && cp "$REPO_ROOT/README.md" "$APP_PREFIX/" || true

# ── 3. Create in-AppImage Python environment ────────────────────────────────
# Use --copies so the venv does not rely on host /usr/bin/python symlinks
# at runtime (important for AppImage portability).
python3 -m venv --copies "$APP_PREFIX/.venv"
"$APP_PREFIX/.venv/bin/python" -m pip install --upgrade pip -q
"$APP_PREFIX/.venv/bin/python" -m pip install -q \
    -r "$APP_PREFIX/requirements.txt" -c "$APP_PREFIX/constraints.txt"

# ── 3b. Bundle Python runtime (stdlib + libpython) for portability ─────────
PY_STDLIB_SRC="$(python3 - <<'PY'
import sysconfig
print(sysconfig.get_path('stdlib'))
PY
)"
PY_LIBDIR="$(python3 - <<'PY'
import sysconfig
print(sysconfig.get_config_var('LIBDIR') or '')
PY
)"
PY_LDLIB="$(python3 - <<'PY'
import sysconfig
print(sysconfig.get_config_var('LDLIBRARY') or '')
PY
)"

if [ -z "$PY_STDLIB_SRC" ] || [ ! -d "$PY_STDLIB_SRC" ]; then
    echo "ERROR: Could not locate Python stdlib directory"
    exit 1
fi
cp -a "$PY_STDLIB_SRC" "$PY_RUNTIME/lib/"

if [ -n "$PY_LIBDIR" ] && [ -n "$PY_LDLIB" ] && [ -f "$PY_LIBDIR/$PY_LDLIB" ]; then
    cp -a "$PY_LIBDIR/$PY_LDLIB" "$PY_RUNTIME/lib/"
    cp -a "$PY_LIBDIR/$PY_LDLIB" "$PY_RUNTIME/lib64/"
fi

# ── 3c. Bundle host libraries the PyPI Qt 6 wheels need ───────────────────
# The Qt wheels bundle Qt itself but link these system libraries.  None of
# them is on the AppImage excludelist (pkg2appimage/excludelist), and minimal
# systems — including the AppImage catalog tester — lack them.  Without the
# xcb helper libraries Qt >= 6.5 refuses to load its X11 platform plugin
# ("xcb-cursor0 or libxcb-cursor0 is needed") and the app exits before any
# window appears.  libgthread is a separate package on openSUSE.
# Deliberately NOT bundled (host-provided everywhere, and bundling can break
# the host): glibc, libxcb/libX11 (excludelisted), libEGL/libGL, fontconfig,
# freetype, harfbuzz, glib/gobject/gio, dbus.
BUNDLE_LIBS=(
    libxcb-cursor.so.0
    libxcb-icccm.so.4
    libxcb-image.so.0
    libxcb-keysyms.so.1
    libxcb-render-util.so.0
    libxcb-render.so.0
    libxcb-shape.so.0
    libxcb-util.so.1
    libxcb-xkb.so.1
    libxkbcommon.so.0
    libxkbcommon-x11.so.0
    libgthread-2.0.so.0
    libnl-3.so.200
    libnl-genl-3.so.200
)
MISSING_LIBS=()
for lib in "${BUNDLE_LIBS[@]}"; do
    src="$(ldconfig -p | awk -v l="$lib" '$1 == l && /x86-64/ {print $NF; exit}')"
    if [ -n "$src" ] && [ -f "$src" ]; then
        cp -L "$src" "$PY_RUNTIME/lib/$lib"
    else
        MISSING_LIBS+=("$lib")
    fi
done
if [ "${#MISSING_LIBS[@]}" -gt 0 ]; then
    echo "ERROR: build host lacks libraries the AppImage must bundle: ${MISSING_LIBS[*]}"
    echo "       Install: libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1"
    echo "                libxcb-render-util0 libxcb-render0 libxcb-shape0 libxcb-util1"
    echo "                libxcb-xkb1 libxkbcommon0 libxkbcommon-x11-0 libglib2.0-0"
    echo "                libnl-3-200 libnl-genl-3-200"
    exit 1
fi

# ── 3d. Bundle iw (built from source) ──────────────────────────────────────
# WaveScope's parser follows iw's current text format (Wi-Fi 7 / 6 GHz
# elements were added in iw 6.x); Ubuntu 22.04 ships iw 5.16, so the build
# host's package is not usable.  Build the release matching the parser from
# kernel.org and ship it in the AppImage ("one app = one file", as the
# AppImage catalog requires).  Packet capture still runs the *host* iw as
# root (a root process cannot read the user's FUSE mount).
IW_VERSION="6.17"
IW_SHA256="7d182e498289ab39b257da6780d562e415377107f50358ee5b55b8cfe40b1e33"
IW_URL="https://www.kernel.org/pub/software/network/iw/iw-${IW_VERSION}.tar.xz"
IW_SRC="$BUILD_DIR/iw-src"
mkdir -p "$IW_SRC"
if [ -n "${WAVESCOPE_IW_TARBALL:-}" ] && [ -f "$WAVESCOPE_IW_TARBALL" ]; then
    cp "$WAVESCOPE_IW_TARBALL" "$IW_SRC/iw.tar.xz"
else
    wget -qO "$IW_SRC/iw.tar.xz" "$IW_URL"
fi
echo "${IW_SHA256}  $IW_SRC/iw.tar.xz" | sha256sum -c - >/dev/null
tar -xJf "$IW_SRC/iw.tar.xz" -C "$IW_SRC"
make -C "$IW_SRC/iw-${IW_VERSION}" -j"$(nproc)" >/dev/null
install -m 0755 "$IW_SRC/iw-${IW_VERSION}/iw" "$APPDIR/usr/bin/iw"
"$APPDIR/usr/bin/iw" --version

# ── 4. Internal launcher ─────────────────────────────────────────────────────
cat > "$APPDIR/usr/bin/${APP_ID}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APPDIR="$(cd "$HERE/../.." && pwd)"
APP_PREFIX="$APPDIR/usr/share/wavescope"

PY_SITE="$(echo "$APP_PREFIX/.venv/lib/python"*/site-packages)"
# main.py restores these for child processes (nmcli, iw, …) so the bundled
# Python/libraries never leak into host tools.
export WAVESCOPE_APPIMAGE=1
export WAVESCOPE_HOST_LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"
# Bundled iw (version matching the parser); the host's iw is still used for
# packet capture, which runs as root outside the AppImage mount.
export WAVESCOPE_BUNDLED_IW="$APPDIR/usr/bin/iw"
export PYTHONHOME="$APP_PREFIX/python-runtime"
export PYTHONPATH="$PY_SITE"
export LD_LIBRARY_PATH="$APP_PREFIX/python-runtime/lib:$APP_PREFIX/python-runtime/lib64:${LD_LIBRARY_PATH:-}"

exec "$APP_PREFIX/.venv/bin/python" "$APP_PREFIX/main.py" "$@"
EOF
chmod 0755 "$APPDIR/usr/bin/${APP_ID}"

# ── 5. AppImage metadata files ──────────────────────────────────────────────
cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HERE/usr/bin:$PATH"
exec "$HERE/usr/bin/wavescope" "$@"
EOF
chmod 0755 "$APPDIR/AppRun"

# Desktop file + icon live in the standard XDG locations (for AppStream and
# desktop integration tools); appimagetool also needs copies at the AppDir root.
cat > "$APPDIR/usr/share/applications/${APP_ID}.desktop" <<EOF
[Desktop Entry]
Name=${APP_NAME}
Comment=Modern WiFi Analyzer for Linux
Exec=${APP_ID}
Icon=${APP_ID}
Terminal=false
Type=Application
Categories=Network;Monitor;
Keywords=wifi;wireless;network;analyzer;
StartupWMClass=wavescope
EOF
cp "$APPDIR/usr/share/applications/${APP_ID}.desktop" "$APPDIR/${APP_ID}.desktop"

cp "$REPO_ROOT/assets/icon.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/${APP_ID}.svg"
cp "$REPO_ROOT/assets/icon.svg" "$APPDIR/${APP_ID}.svg"

# AppStream metainfo (launchable desktop-id must match the desktop file above)
cp "$REPO_ROOT/assets/io.github.yurividal.WaveScope.appdata.xml" "$APPDIR/usr/share/metainfo/"

# ── 5b. Validate metadata ───────────────────────────────────────────────────
# appimagetool only looks for usr/share/metainfo/<desktop-basename>.appdata.xml
# (i.e. wavescope.appdata.xml), but AppStream requires the metainfo filename to
# match the reverse-DNS component id (metainfo-filename-cid-mismatch).  The
# desktop id must stay wavescope.desktop (main.py setDesktopFileName), so we
# validate the tree ourselves and run appimagetool with --no-appstream.
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$APPDIR/usr/share/applications/${APP_ID}.desktop"
fi
if command -v appstreamcli >/dev/null 2>&1; then
    appstreamcli validate-tree --no-net "$APPDIR"
else
    echo "NOTE: appstreamcli not found; skipping AppStream metainfo validation"
fi

# ── 6. Build AppImage ───────────────────────────────────────────────────────
appimagetool --no-appstream "$APPDIR" "$REPO_ROOT/$OUTPUT_FILE"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Built: $OUTPUT_FILE"
echo ""
echo "  Run:"
echo "    chmod +x $OUTPUT_FILE"
echo "    ./$OUTPUT_FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Cleanup
rm -rf "$BUILD_DIR"
