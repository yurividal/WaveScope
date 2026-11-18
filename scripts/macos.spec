# Build with ./scripts/build_macos.sh on macOS.
import os
import platform
from pathlib import Path

root = Path(SPECPATH).resolve().parent
identity = os.environ.get("WAVESCOPE_CODESIGN_IDENTITY") or None
version = os.environ["WAVESCOPE_BUILD_VERSION"]
usage = "WaveScope needs Location Services to show nearby Wi-Fi network names and BSSIDs."

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "assets"), "assets"),
        (str(root / "LICENSE"), "."),
    ],
    hiddenimports=["CoreWLAN", "CoreLocation", "Foundation", "objc"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "PyQt5", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WaveScope",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=identity,
    entitlements_file=str(root / "assets/macos/entitlements.plist") if identity else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="WaveScope")
app = BUNDLE(
    coll,
    name="WaveScope.app",
    icon=str(root / "build/macos/WaveScope.icns"),
    bundle_identifier="io.github.yurividal.WaveScope",
    version=version,
    info_plist={
        "CFBundleName": "WaveScope",
        "CFBundleDisplayName": "WaveScope",
        "CFBundleVersion": version,
        "NSPrincipalClass": "NSApplication",
        "NSHighResolutionCapable": True,
        "NSLocationUsageDescription": usage,
        "NSLocationWhenInUseUsageDescription": usage,
        # Do not advertise an older deployment target than the build host.
        "LSMinimumSystemVersion": platform.mac_ver()[0],
    },
)
