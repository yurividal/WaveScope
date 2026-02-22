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
| **Tested on** | Ubuntu 22.04 / 24.04 |
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

### Option B — Run from source

```bash
# Clone
git clone https://github.com/yurividal/WaveScope.git
cd WaveScope

# Install & run (creates .venv, installs packages)
chmod +x install.sh
./install.sh
./wavescope
```

---

## Build .deb from source

```bash
# Requires: dpkg-dev
chmod +x build_deb.sh
./build_deb.sh 1.0.0
sudo dpkg -i wavescope_1.0.0_all.deb
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

### v1.3.1 — 2026-02-22

#### New features
- **2.4 GHz bonded-channel graph** — the spectrum graph now correctly centers 40 MHz (HT40) access points on the true bonded-block center. `iw` reports the secondary channel offset (`above`/`below`), which is used to compute the actual ±10 MHz shift. Example: ch 6 HT40+ renders over the ch 6–10 block.
- **6 GHz bonded-channel graph** — 40/80/160/320 MHz shapes are now correctly placed using the `center freq 1` value from `iw`. Example: 160 MHz on ch 1 renders over the ch 1–29 block.
- **Ch. Span for 2.4 / 6 GHz** — the Ch. Span table column now shows the actual bonded channel range for 2.4 GHz 40 MHz (e.g. `6–10`) and 6 GHz wider blocks (e.g. `1–29`).
- **iw field persistence** — Gen, Ch.Util%, Clients, k/v/r, AKM and other `iw`-enriched fields no longer blank out between scan cycles. The last known value is held for up to 5 consecutive missed cycles, after which it clears naturally.

#### Fixes
- **5 GHz x-axis** — removed spurious channel 32 (5160 MHz); the 5 GHz panel now starts at channel 36 as per standard deployments.
- **Column widths** — Width (MHz) column widened to 96 px; Ch. Span column now has a proper initial width (82 px) instead of falling back to Qt's narrow default.

---

### v1.3.0 — 2026-02-22

#### New features
- **Correct 5 GHz spectrum placement** — channel shapes in the graph are now centered on the true bonded-block center frequency, not just the primary 20 MHz channel center. Examples: ch 116 @ 80 MHz renders over 116–128; ch 100 @ 160 MHz renders over 100–128.
- **Ch. Span column** — new table column showing the full channel range an AP occupies (e.g. `116–128` for ch 116 @ 80 MHz on 5 GHz, or `100–128` for 160 MHz).
- **Filter-aware channel graph** — the spectrum graph now updates live as you type in the search box, change the band filter, or apply right-click Show/Hide column filters. Only visible APs are drawn.
- **Channel width right-click filter** — "Channel Width" (20/40/80/160 MHz) is now available in the Show only / Hide context-menu filter.
- **U-NII sub-band colours on 5 GHz x-axis** — channel tick labels are colour-coded by regulatory band: U-NII-1 (green), U-NII-2A (blue), U-NII-2C (amber), U-NII-3 (lighter green), U-NII-4 (red).

#### Changes
- **Column renamed**: "BW (MHz)" → "Width (MHz)" — *channel width* is the correct IEEE 802.11 term for the bonded block size.
- **Unknown manufacturer is now blank** — the Manufacturer column shows an empty cell instead of "Unknown" when the OUI is not found.
- **Rebranded paths** — all internal paths and identifiers migrated from `nmcli-gui` to `wavescope` (`~/.local/share/wavescope`, User-Agent header, Qt organisation name).
- Removed deprecated `wifi-analyzer` launcher script.

---

## License

MIT License. See [LICENSE](LICENSE).
