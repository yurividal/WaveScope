# WaveScope

> A modern, fast WiFi analyzer for Linux — built with PyQt6 and Python.

![WaveScope Screenshot](assets/screenshot.png)

---

## About

WaveScope is an open-source WiFi analyzer designed for Linux desktops. It gives you a real-time, high-detail view of the wireless networks around you — from signal strength and channel occupancy to security modes, WiFi generations, and manufacturer data.

> 🤖 This application was built mostly using **Claude Code AI** (by Anthropic), with iterative development driven by human feedback.

---

## Features

- 📡 **Real-time channel graph** — per-band panels (2.4 GHz / 5 GHz / 6 GHz), no dead spectrum
- 📈 **Signal history plot** — rolling 2-minute time series per access point
- 🔍 **Rich AP metadata** — SSID, BSSID, manufacturer (OUI), band, channel, bandwidth, signal (dBm), security, WiFi generation, channel utilization, connected clients, 802.11k/v/r roaming support
- 🎨 **Dark / Light / Auto theme**
- 🏷️ **DFS channel indicator** — subtle amber marker on DFS channels in the 5 GHz band
- 🔒 **OUI manufacturer lookup** — downloads the IEEE database on demand
- ⚡ **Configurable refresh rate** — 1s to 30s
- 🖱️ **Interactive graphs** — click labels to highlight, scroll to zoom, drag to pan
- 🔎 **Filter & sort** — by any column, with text search
- 📦 **Packet capture** — two modes available via the toolbar:
  - **Monitor Mode**: raw 802.11 over-the-air capture of all frames on a chosen channel (all devices); temporarily disconnects WiFi, restored automatically on stop
  - **Managed Mode**: capture your own machine's traffic without disconnecting from the network; WiFi stays connected throughout
  - Both modes output standard `.pcap` files (Wireshark-compatible) and require a single root prompt

---

## Platform

| | |
|---|---|
| **OS** | Linux |
| **Tested on** | Ubuntu 22.04 / 24.04, Fedora 39+ |
| **Requires** | NetworkManager (`nmcli`), `iw` |
| **Python** | 3.10 or newer |

---

## Installation

### Option A — Debian/Ubuntu (.deb package) ✅ Recommended

Download the latest `.deb` from the [Releases](https://github.com/yurividal/WaveScope/releases) page:

```bash
sudo dpkg -i wavescope_*.deb
wavescope
```

The installer will automatically create a Python virtual environment and install all Python dependencies (`PyQt6`, `pyqtgraph`, `numpy`).

**System dependencies** (installed automatically as `.deb` dependencies):
```
python3 (≥3.10), python3-pip, python3-venv,
network-manager, iw, tcpdump, policykit-1,
libxcb-cursor0, libxcb-xinerama0, libxcb-randr0
```

---

### Option B — Fedora / RHEL (.rpm package) ✅ Recommended

Download the latest `.rpm` from the [Releases](https://github.com/yurividal/WaveScope/releases) page:

```bash
sudo dnf install ./wavescope_*.rpm
wavescope
```

**System dependencies** (installed automatically as `.rpm` dependencies):
```
python3 (≥3.10), python3-pip,
NetworkManager, iw, tcpdump, polkit, xcb-util-cursor
```

---

### Option C — Run from source

```bash
# Clone
git clone https://github.com/yurividal/WaveScope.git
cd WaveScope

# Install & run (creates .venv, installs packages)
chmod +x install.sh
./install.sh
./wavescope
```

### Option D — AppImage

Download the latest `.AppImage` from the [Releases](https://github.com/yurividal/WaveScope/releases) page:

```bash
chmod +x WaveScope-*.AppImage
./WaveScope-*.AppImage
```

Notes:
- AppImage bundles Python + Python dependencies.
- `nmcli`, `iw`, and `tcpdump` are still expected on the host system.

---

## Build packages from source

### .deb (Debian/Ubuntu)

```bash
# Requires: dpkg-dev
chmod +x scripts/build_deb.sh
./scripts/build_deb.sh
sudo dpkg -i wavescope_*.deb
```

### .rpm (Fedora/RHEL)

```bash
# Requires: rpm-build
# sudo dnf install rpm-build
chmod +x scripts/build_rpm.sh
./scripts/build_rpm.sh
sudo dnf install ./wavescope_*.rpm
```

### AppImage

```bash
# Requires: appimagetool
# (Download from AppImageKit releases or install from your distro if available)
chmod +x scripts/build_appimage.sh
./scripts/build_appimage.sh

chmod +x WaveScope-*.AppImage
./WaveScope-*.AppImage
```

### AppImage (Docker, no host appimagetool needed)

```bash
# Requires: docker
chmod +x build_appimage_docker.sh
./build_appimage_docker.sh

chmod +x WaveScope-*.AppImage
./WaveScope-*.AppImage
```

---

## Requirements

### System
- `nmcli` — provided by `network-manager`
- `iw` — for enriched scan data (WiFi generation, exact dBm, BSS load, etc.)
- `tcpdump` — required for packet capture (Monitor & Managed modes)
- `pkexec` — provided by `policykit-1`; used for root privilege during packet capture

### Python packages (auto-installed by installer or `.deb`)
- `PyQt6 >= 6.4.0`
- `pyqtgraph >= 0.13.0`
- `numpy >= 1.23.0`

---

## Changelog
See [CHANGELOG.md](CHANGELOG.md) for release history.

---

## License

MIT License. See [LICENSE](LICENSE).
