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

# ── 3c. Bundle libgthread-2.0 ───────────────────────────────────────────────
# The PyPI Qt 6 wheels link libgthread-2.0.so.0.  openSUSE ships it as a
# separate package (libgthread-2_0-0) that minimal installs lack, and it is
# *not* on the AppImage excludelist (pkg2appimage/excludelist lists it as
# "bundle").  It is a tiny compatibility shim over the host's libglib-2.0,
# so bundling it is safe; glib/gobject themselves stay host-provided.
GTHREAD_LIB="$(ldconfig -p | awk '/libgthread-2\.0\.so\.0 .*x86-64/ {print $NF; exit}')"
if [ -n "$GTHREAD_LIB" ] && [ -f "$GTHREAD_LIB" ]; then
    cp -L "$GTHREAD_LIB" "$PY_RUNTIME/lib/libgthread-2.0.so.0"
else
    echo "WARNING: libgthread-2.0.so.0 not found on the build host; not bundled"
fi

# ── 4. Internal launcher ─────────────────────────────────────────────────────
cat > "$APPDIR/usr/bin/${APP_ID}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APPDIR="$(cd "$HERE/../.." && pwd)"
APP_PREFIX="$APPDIR/usr/share/wavescope"

PY_SITE="$(echo "$APP_PREFIX/.venv/lib/python"*/site-packages)"
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
