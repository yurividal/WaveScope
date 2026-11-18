# Contributing to WaveScope

Bug reports and pull requests are welcome. For bugs, please use the issue
template: scan results depend heavily on the adapter, driver and scan backend.
On Linux include `nmcli` / `iw` versions; on macOS include the OS, Python and
PyObjC versions, launch method, signing status and Location Services state.

## Development setup

Requires Python 3.10+ and Qt. Linux uses NetworkManager (`nmcli`) and `iw`,
with `tcpdump` and polkit (`pkexec`) for capture. macOS uses CoreWLAN and
CoreLocation through PyObjC; `install.sh` selects the platform dependencies.
See the README's macOS section for executable signing and location permission.

```bash
git clone https://github.com/yurividal/WaveScope.git
cd WaveScope
./install.sh          # installs/prints system packages, creates .venv, writes ./wavescope
./wavescope           # run
```

Manual equivalent of the venv step:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -c constraints.txt
.venv/bin/python main.py
```

- `requirements.txt` holds loose lower bounds; `constraints.txt` holds the
  exact pins every package format installs. Bump pins there and re-test the
  .deb, .rpm and AppImage builds.
- The app version lives in `VERSION` in `wavescope_app/core_base.py` (the
  build scripts read it from there). Keep `version` in `pyproject.toml` and the
  `<releases>` list in `assets/io.github.yurividal.WaveScope.appdata.xml` in
  step with it.

## Lint

CI runs this before building any release. Run it before opening a PR:

```bash
python3 -m compileall -q wavescope_app main.py
pipx run ruff check          # or: .venv/bin/pip install ruff && .venv/bin/ruff check
```

Ruff is configured in `pyproject.toml` to report syntax errors and undefined
names only (the code uses star imports on purpose).

## Adding a vendor IE parser

Vendor-specific beacon IEs (AP names, TX power, vendor detection) are parsed
in `wavescope_app/vendor_beacon.py`:

1. Write `def _parse_<vendor>(text: str, d: dict) -> None`. `text` is the
   full `iw` scan block for one BSS; set keys on `d` (for example
   `d["ap_name"]`). Use the `_hex_ie()` and `_printable()` helpers for raw IEs.
2. Leave `d["ap_name"]` alone if it is already set: parsers run in order and
   earlier ones win.
3. Append the function to the `_PARSERS` list at the bottom of the file.
4. Put the OUI and IE layout in the docstring, and say where it came from
   (spec, vendor docs, or a capture from a real AP).

## Building packages

Package build scripts take an optional version argument and otherwise read
`VERSION` from `core_base.py`. Linux packages go to the repository root;
the macOS bundle goes to `dist/WaveScope.app`.

| Package | Command | Needs |
|---|---|---|
| .deb | `./scripts/build_deb.sh` | `dpkg-deb` |
| .rpm (Fedora/RHEL) | `./scripts/build_rpm.sh` | `rpm-build` |
| .rpm (openSUSE) | `./scripts/build_opensuse.sh` | `rpm-build` |
| AppImage | `./scripts/build_appimage.sh` | `appimagetool` on the host |
| AppImage (Docker) | `./scripts/build_appimage_docker.sh` | `docker` |
| AppImage launch test (Xvfb, bare Ubuntu 22.04) | `./scripts/test_appimage_xvfb.sh WaveScope-*.AppImage` | `docker` |
| macOS `.app` | `./scripts/build_macos.sh` | macOS, runtime dependencies, `requirements-macos-build.txt` |

Linux release builds run in `.github/workflows/release.yml` when a `vX.Y.Z` tag is
pushed. To rebuild an existing tag, run the workflow manually from the Actions
tab and enter the tag. macOS builds are local / CI development artifacts until
the maintainer configures signing and notarization for distribution.

### macOS validation

`.github/workflows/test.yml` runs the suite on Ubuntu and macOS 15 (Apple Silicon
and Intel). The macOS jobs import the real native bindings and build / smoke-test
the `.app`, without requesting Location Services or requiring Wi-Fi hardware.
The backend's framework fakes exercise metadata conversion and error handling on
every OS. An ad-hoc CI signature does not validate access to Wi-Fi identifiers.

Before claiming live macOS support verified, test a properly signed build on a
Mac with Wi-Fi:

- Launch from Finder, grant Location Services, and compare SSID, BSSID, channel,
  width, RSSI and security with a known access point or Wireless Diagnostics.
- Deny permission, disable Location Services, and revoke an existing grant;
  each state must produce an actionable notice rather than an empty-scan claim.
- Turn Wi-Fi off / on, disconnect / reconnect, and verify connected state and
  telemetry refresh without stale data.
- Check 2.4 GHz / 5 GHz and, with capable hardware, 6 GHz. Do not assume all Macs
  or adapters support the same bands or PHY versions.
- Pause, resume and close during a scan; verify the UI stays responsive and
  shutdown safely waits for any in-flight native call.
- Confirm packet-capture controls are unavailable on macOS, and sessions / CSV
  export / labels / Find AP work without Linux tools.

Record the macOS version, architecture, adapter, Python / PyObjC versions and
signing identity type with the results. Do not commit real SSIDs or BSSIDs.

## Tests and the Wireshark cross-check

```bash
pip install -r requirements.txt -c constraints.txt -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests
```

`tests/test_parser_vs_wireshark.py` compares WaveScope's parser with
Wireshark's decoding of the same frames, using stored fixtures. To check
the parser against live data (needs `iw`, `tshark` and pyroute2; no root):

```bash
nmcli dev wifi rescan; sleep 8
python3 devtools/crosscheck.py                      # report only
python3 devtools/crosscheck.py --save-fixture NAME  # also store an anonymized fixture
```

Fixtures are anonymized by default (real BSSIDs are location-identifying).
Never commit a fixture made with `--no-anonymize`.
