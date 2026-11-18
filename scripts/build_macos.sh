#!/usr/bin/env bash
# Build a native-architecture .app. No signing identity is needed for CI.
# For live Wi-Fi identifiers, set WAVESCOPE_CODESIGN_IDENTITY to an
# Apple-issued signing identity from your login keychain (not "-").
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${WAVESCOPE_PYTHON:-$REPO_ROOT/.venv/bin/python}"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "Build WaveScope.app on macOS; PyInstaller does not cross-compile macOS apps." >&2
    exit 1
fi
if [ "$#" -gt 1 ]; then
    echo "Usage: $0 [version]" >&2
    exit 1
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Run ./install.sh first, or set WAVESCOPE_PYTHON to your build environment's Python." >&2
    exit 1
fi
if ! "$PYTHON_BIN" -c 'import PyInstaller, PyQt6, CoreWLAN, CoreLocation' >/dev/null 2>&1; then
    echo "Install build dependencies with:" >&2
    echo "  $PYTHON_BIN -m pip install -r requirements.txt -c constraints.txt -r requirements-macos-build.txt" >&2
    exit 1
fi
if [ "${WAVESCOPE_CODESIGN_IDENTITY:-}" = "-" ]; then
    echo "Omit WAVESCOPE_CODESIGN_IDENTITY for an ad-hoc development build, or supply an Apple-issued identity." >&2
    exit 1
fi

WAVESCOPE_BUILD_VERSION="${1:-$("$PYTHON_BIN" - "$REPO_ROOT/wavescope_app/core_base.py" <<'PY'
import ast
import sys
from pathlib import Path

tree = ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))
for node in tree.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in node.targets):
        print(ast.literal_eval(node.value))
        break
else:
    raise SystemExit("VERSION is missing from core_base.py")
PY
)}"
if [[ ! "$WAVESCOPE_BUILD_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "The macOS bundle version must have the form X.Y.Z." >&2
    exit 1
fi
export WAVESCOPE_BUILD_VERSION

# Generate the native icon from the existing SVG, without another image library.
QT_QPA_PLATFORM=offscreen "$PYTHON_BIN" - "$REPO_ROOT" <<'PY'
import sys
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

root = Path(sys.argv[1])
iconset = root / "build/macos/WaveScope.iconset"
iconset.mkdir(parents=True, exist_ok=True)
app = QGuiApplication([])
renderer = QSvgRenderer(str(root / "assets/icon.svg"))
if not renderer.isValid():
    raise SystemExit("Invalid application SVG icon")
for size in (16, 32, 128, 256, 512):
    for scale in (1, 2):
        pixels = size * scale
        image = QImage(pixels, pixels, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        suffix = "@2x" if scale == 2 else ""
        if not image.save(str(iconset / f"icon_{size}x{size}{suffix}.png")):
            raise SystemExit("Could not write application icon")
PY
/usr/bin/iconutil -c icns "$REPO_ROOT/build/macos/WaveScope.iconset" -o "$REPO_ROOT/build/macos/WaveScope.icns"

"$PYTHON_BIN" -m PyInstaller --noconfirm --clean \
    --distpath "$REPO_ROOT/dist" --workpath "$REPO_ROOT/build/macos/pyinstaller" \
    "$SCRIPT_DIR/macos.spec"

APP_PATH="$REPO_ROOT/dist/WaveScope.app"
/usr/bin/codesign --verify --deep --strict "$APP_PATH"
echo "Built $APP_PATH ($(uname -m), macOS $(sw_vers -productVersion))."
if [ -n "${WAVESCOPE_CODESIGN_IDENTITY:-}" ]; then
    echo "Signed with the requested identity. Open the app and allow Location Services."
    echo "Notarization is a separate step before public distribution."
else
    echo "This is an ad-hoc signed development build for UI/build checks."
    echo "macOS may redact Wi-Fi identifiers; use an Apple-issued signing identity for live scanning."
fi
