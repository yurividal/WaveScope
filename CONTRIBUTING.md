# Contributing to WaveScope

Bug reports and pull requests are welcome. For bugs, please use the issue
template: scan results depend heavily on the adapter, driver, `nmcli` and
`iw` versions, and the template asks for all of them.

## Development setup

Requires Python 3.10+, NetworkManager (`nmcli`), `iw`, `tcpdump` and polkit
(`pkexec`).

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

All scripts take an optional version argument and otherwise read `VERSION`
from `core_base.py`. Output goes to the repository root.

| Package | Command | Needs |
|---|---|---|
| .deb | `./scripts/build_deb.sh` | `dpkg-deb` |
| .rpm (Fedora/RHEL) | `./scripts/build_rpm.sh` | `rpm-build` |
| .rpm (openSUSE) | `./scripts/build_opensuse.sh` | `rpm-build` |
| AppImage | `./scripts/build_appimage.sh` | `appimagetool` on the host |
| AppImage (Docker) | `./scripts/build_appimage_docker.sh` | `docker` |
| AppImage launch test (Xvfb, bare Ubuntu 22.04) | `./scripts/test_appimage_xvfb.sh WaveScope-*.AppImage` | `docker` |

Release builds run in `.github/workflows/release.yml` when a `vX.Y.Z` tag is
pushed. To rebuild an existing tag, run the workflow manually from the Actions
tab and enter the tag.
