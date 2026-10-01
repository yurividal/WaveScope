# Changelog

## v2.1.3 — 2026-10-01

### AppImage: self-contained scanning
- **iw is bundled** (built from the iw 6.17 release, the version the parser follows; Ubuntu 22.04's packaged 5.16 predates Wi-Fi 7 decoding) together with libnl. The AppImage scans on hosts without iw; packet capture still uses the host's iw, tcpdump and pkexec, since root cannot read the user's AppImage mount.
- **No startup dialog for optional tools** — a system without NetworkManager, tcpdump or pkexec now gets the normal main window plus a dismissable in-window notice. The blocking dialog remains only when nothing can scan at all (neither iw nor nmcli).
- **Neutral state messages** — "No Wi-Fi interface detected" and "NetworkManager is absent" are shown as status notes instead of scanner errors, and the empty-table overlay explains the state. Wording is checked by a test against the AppImage catalog's screenshot error regexes, and the Xvfb launch test now requires the main window without any dialog on a bare host and verifies the bundled iw runs.

## v2.1.2 — 2026-10-01

### Verified against IEEE Std 802.11-2024 (the three questions the spec review left open)
- **6 GHz AP power type** — the Regulatory Info subfield is 4 bits (Figure 9-908) and decoded per Table E-13: 0 Indoor, 1 Standard Power, 2 Very Low Power, 3 Indoor Enabled, 7 "AP role not relevant", 8 Indoor Standard Power; 4 is the deprecated 3-bit encoding of Indoor SP; other values are shown as Reserved. Previously only 0-4 were mapped.
- **Country element** — the Country String's third octet is the Annex E table number in use (0x04 = Table E-4; Annex C and E.2.7), confirming the "Global (Table E-4 operating classes)" label. Channel spacing inside an Operating/Subband Sequence follows the operating class's bandwidth (9.4.2.7), so 40/80/160/320 MHz classes now get the right channel ranges, not just the 20 MHz class.
- **Mobility Domain ID** — a 2-octet identifier (9.4.2.45); shown as the octets in transmission order (hostapd's `mobility_domain=` form) with the little-endian numeric value (9.2.2) alongside, which is what Wireshark displays.
- **WPA3 modes** (WPA3 Specification v3.5 §2.2-2.4, §3.2-3.5, §11.2): labels and the 6 GHz / PMF checks match the specification; a WPA2-Enterprise BSS with PMF required is *not* WPA3-Enterprise (which requires AKM 5 and forbids AKM 1), so its "WPA2 (802.1X)" label stands.

## v2.1.1 — 2026-10-01

### Fixes — wrong data found in a spec review against iw, hostap, Wireshark and nmcli sources
- **Impossible 60-63 Mbps "rates" on Wi-Fi 6E/7 APs** — iw prints BSS membership selectors (HE, EHT, SAE-H2E-only …) as pseudo-rates such as `61.5*`; they were counted as basic/legacy rates. Real rates never exceed 54 Mbps, so selectors are now skipped.
- **Wi-Fi 4 APs showed 54 Mbps** — an HT MCS line of `0-15, 32` was read as "max index 32" and discarded; all ranges are now parsed and MCS 32 (the 40 MHz duplicate mode) ignored, giving e.g. 144 Mbps for HT20 2SS SGI.
- **Country IE power summary** — triplets with equal power were merged across gaps (`ch 36–165`); they now merge only when contiguous. 6 GHz triplets were printed by iw with 5 GHz-style end channels (`1–24` for channels 1–93) and are recomputed. The environment byte 0x04 (Table E-4 operating classes), shown by iw as "bogus", is now reported as "Global (Table E-4 operating classes)".
- **Group management cipher (BIP) was never shown** — iw prints "Group mgmt cipher suite:"; the parser expected "Group mgmt cipher:".
- **TPC / Cisco TX power of 128–255 dBm** — the Transmit Power octets are signed but iw prints them unsigned; they are now sign-converted and values outside −20…40 dBm discarded.
- **Open side of an OWE transition pair labelled "OWE"** (NetworkManager data source only) — nmcli emits the same `owe` flag for OWE and OWE-transition; the SECURITY column's `OWE-TM` is now honoured.
- **AKM 11 (802.1X Suite-B, 128-bit) labelled "WPA3 (802.1X-192)"** — only AKM 12 and FT-SHA-384 (13) are 192-bit.
- **Reduced Neighbor Report flags read from the wrong byte** — the "same SSID" / "co-located" flags sit at a length-dependent offset (802.11ax Table 9-281); they were only read for the 12/13/16-byte layouts. All layouts are handled and reserved lengths skipped.
- **80+80 MHz BSSs drawn as one 160 MHz block** — they are now detected like hostap does (any non-contiguous CCFS1) and drawn as the 80 MHz segment that holds the primary channel, labelled 80+80 with the second segment's centre in Details.
- **160 MHz max rate used the ≤80 MHz stream count** — the 160 MHz MCS/NSS set is used when the AP operates at 160 MHz, so an AP with 4 streams at 80 but 2 at 160 no longer shows double its real rate.
- **6 GHz and WPA3 PMF checks** — the Issues tab now checks the actual AKMs and PMF setting instead of the label text: PSK/transition modes and PMF-optional on 6 GHz are flagged, WPA3-Personal (SAE-only) and OWE must have PMF required, transition mode must have PMF capable.
- **PMF shows "N/A"** on Open / WEP / WPA1-only networks instead of "No".
- **WPA3 compatibility mode** (RSN Element Override carrying SAE) is marked "(+WPA3 override)" after the base WPA2 label.
- **802.11k** is detected from the exact "Neighbor Report" capability line (not "Neighbor Report TSF Offset").
- **Wireshark cross-check** now also compares basic/legacy rates, 802.11k/v bits, country power limits, TPC power and Reduced Neighbor Report BSSIDs/flags — the fields whose bugs it previously could not see. Live run: 23 fields, 0 mismatches.

## v2.1.0 — 2026-10-01

### New data source: the kernel scan cache via iw (single source of truth)
- **All BSS data now comes from one place** — the kernel's cfg80211 scan results as decoded by `iw` — instead of merging NetworkManager's list (wpa_supplicant's copy, re-interpreted by NM) with iw's. This removes the BSSID matching, the percent-vs-dBm and "0 MHz" reconciliation and the 30 s / 180 s cache-lifetime mismatch behind several earlier bugs.
- **NetworkManager is only used to trigger scans** (`nmcli dev wifi rescan`, allowed for active sessions by its polkit policy). Without NetworkManager the app still reads whatever the host's own scans leave in the kernel cache.
- **No root needed**: reading the scan cache, station and survey data is unprivileged (nl80211 GET_SCAN / GET_STATION / GET_SURVEY); only scan *triggering* requires CAP_NET_ADMIN, which is why it is delegated to the network manager.
- **Tools ▸ Data Source** switches between the new source (default) and the legacy NetworkManager + iw path; the status bar shows which one is active and falls back automatically when iw or a managed Wi-Fi interface is unavailable. The choice is saved.
- Built entirely from iw: SSID (iw's escaping reversed, UTF-8 safe), connected BSS, security (NM-equivalent tokens, so labels and filters are unchanged), Signal % (NetworkManager's own dBm mapping) and the max PHY rate (EHT/HE/VHT/HT/legacy).
- **Beacon-only IEs** — iw's `scan dump -u` prints just the first IE set; WaveScope now also reads `scan dump -b` (iw accepts only one option at a time) to pick up beacon-only elements such as TIM/DTIM.

### Troubleshooting features
- **Settings dialog** (Tools ▸ Settings…, Ctrl+,): General (theme, refresh, linger, data source), Graph, Columns, Labels, Issues and Find AP pages in one place; the toolbar controls remain as shortcuts.
- **Issues tab** — configuration problems found in the current scan, each with severity and a one-line explanation: WEP / open / WPA1-TKIP, 6 GHz without WPA3/OWE, WPA3-SAE without PMF, PMF disabled, 802.11b rates, 40 MHz on 2.4 GHz, overlapping 2.4 GHz channels, high channel utilization, congested channels, too many SSIDs per radio, BSS color collisions, inconsistent security/PMF/k-v-r/mobility domain/country across one SSID (the WPA3 6 GHz transition design is not flagged), hard-to-discover 6 GHz BSSs, unusual DTIM/beacon interval, hidden SSIDs. Pairwise checks are reported once per pair of radios. Click an issue to select the APs; checks and thresholds are configurable.
- **Compare** (select 2-4 rows ▸ right-click ▸ Compare) — every field side by side, differences highlighted, "only differences" toggle.
- **Labels** — per-BSSID labels with wildcard patterns (e.g. `74:11:b2:c7:22:4*` for all BSSIDs of one AP); set from the context menu, shown in a Label column, searchable, managed in Settings.
- **Column profiles** — built-in (Default, RF / Channel, Security, Roaming, Survey) and custom profiles with column choice, order and **pinned leading columns** that stay visible while scrolling sideways; switch from the toolbar. 17 more fields are available as columns (PMF, AKM suites, BSS color, DTIM, beacon interval, mobility domain, MLD MAC, RSNX, basic rates, …).
- **Find AP** (right-click ▸ Find this AP…) — signal meter with a beeper that gets faster and higher as the signal rises; uses the desktop's audio player (pw-play / paplay / aplay). The refresh interval is 1 s while it is open.
- **Sessions & export** — save the current scan to a session file and review it later (scanning paused, banner to resume); export the (filtered) table to CSV with every field. Shortcuts Ctrl+S / Ctrl+O / Ctrl+E.
- **Field registry** shared by table columns, CSV export and Compare, so all three always agree.

### Fixes
- **Table row striping** alternated wrongly (several dark rows in a row): rows were striped by model order, which since the in-place row diff no longer matches the sorted order on screen. Striping is now done by the views.
- **Channel axis labels overlapped** at normal window widths; labels now thin out to every 2nd/4th/8th channel as space requires (recomputed on resize and zoom), keeping the 1/6/11 plan on 2.4 GHz and the PSCs on 6 GHz.

### Changes
- **6 GHz PSC channels emphasized on the axis** — bold, in a vivid shade of their U-NII sub-band colour — instead of triangle markers on the plot floor; hovering a channel still says "Preferred Scanning Channel (PSC)".

### Verified against Wireshark
- **`devtools/crosscheck.py`** reads the kernel's raw IE bytes (unprivileged nl80211, via pyroute2), wraps them in synthetic beacons, decodes them with **tshark**, and compares Wireshark's values field by field with WaveScope's parse of the same frames (matched by TSF): SSID, primary channel, operating width and block center (CCFS rules), PMF, AKM suites, BSS color, BSS Load, country, DTIM, 802.11r MDID, MLD MAC, 6 GHz AP power type, EHT puncturing. First live run: 32 BSSs, 0 mismatches.
- `--save-fixture` stores an **anonymized** fixture (BSSIDs remapped component-wise so AP/radio relationships survive, MACs inside RNR/vendor IEs rewritten, SSIDs replaced, WPS identities and unused raw IEs removed) for **offline regression tests** (`tests/`), now run in CI.

## v2.0.3 — 2026-10-01

### Fixes
- **False BSS color collision warnings (⚠)** — SSIDs of one radio share a BSS color by design, but radios whose extra BSSIDs use the locally-administered first-octet scheme (e.g. EE, Karina-style `C2:…`/`DA:…`) were flagged as colliding with themselves. Collision detection now skips any pair on the same channel and width that the same-radio rule matches; collisions between different APs are still reported.

## v2.0.2 — 2026-10-01

### Fixes
- **Most BSSs lost their decoded beacon data** — iw prints the "Information elements from … frame" header only when probe-response data exists or differs from the beacon; for BSSs heard only via beacons (24 of 34 in a real scan) the parser treated every IE as metadata, so generation, width, security details, BSS Load, etc. were missing. IEs are now recognised by name, independent of that header.
- **Second SSID of a radio showed as Wi-Fi 6E / 20 MHz** — the kernel drops a BSS from `iw scan dump` 30 s after it was last heard (except the connected one), while wpa_supplicant — and so nmcli — keeps it until it is 180 s old and missed by 2 scans. Decoded iw data is now kept for as long as nmcli still lists the BSS (up to 180 s) instead of 5 cycles.
- **SSIDs of one radio not grouped on 6 GHz (and some 2.4 GHz APs)** — vendors that derive per-SSID BSSIDs by rewriting the first octet with the locally-administered bit set (e.g. `84:78:48:EA:44:D7` → `8A:78:48:EA:44:D7`) are now recognised. The rule requires 36 device-specific bits to match exactly, so neighbouring APs of the same vendor (e.g. Cisco `…:22:40` / `…:22:50`) are never merged.
- **BSSIDs iw never decoded** borrow radio-level data (width, center, puncturing, generation, BSS color, power, country) from a same-radio sibling on the same frequency and signal; Details shows the source. A band-based generation guess is shown as "≥ WiFi 6E" and always yields to decoded data.
- **Signal comparisons never mix sources** — exact iw dBm is compared with exact dBm, otherwise nmcli percentages are compared.

## v2.0.1 — 2026-10-01

### Fixes
- **AppImage exited without showing a window on minimal systems** — the PyPI Qt 6 wheels need X11 helper libraries that minimal installs (including the AppImage catalog tester) lack: `libxcb-cursor`, `-icccm`, `-image`, `-keysyms`, `-render-util`, `-render`, `-shape`, `-util`, `-xkb`, `libxkbcommon` and `libxkbcommon-x11`. Without `libxcb-cursor` Qt ≥ 6.5 refuses to load its X11 plugin and aborts. None of these are on the AppImage excludelist, so the AppImage now bundles them (the build fails if the build host lacks any).
- **Bundled runtime leaked into host tools** — inside the AppImage, `nmcli`, `iw` and other child processes inherited the bundled `LD_LIBRARY_PATH`/`PYTHONHOME`; they now get the host's original environment.

### Packaging
- **AppImage launch test in CI** — `scripts/test_appimage_xvfb.sh` starts the AppImage under Xvfb in a bare Ubuntu 22.04 container (only excludelisted host libraries installed) and requires both the missing-dependency dialog and, with `WAVESCOPE_SKIP_DEPENDENCY_CHECK=1`, the main window to appear and keep running. The release job runs it before uploading, so a non-starting AppImage is never published.

## v2.0.0 — 2026-09-30

Full correctness pass over the 802.11 parsing, plus Wi-Fi 6E/7 and RF-analysis features. iw and nmcli formats were checked against their upstream sources (iw `scan.c`/`util.c`/`station.c`/`link.c`, NetworkManager `nmcli/devices.c`, hostap `ieee802_11_defs.h`, Wireshark's 802.11 dissector).

### Fixes — wrong or misleading wireless data
- **RSN Capabilities decoded from the wrong IE** — the parser matched the first bare `Capabilities:` line (RM Enabled or HT capabilities) instead of the RSN IE, so every AP showed made-up RSN capabilities.
- **PMF bits swapped** — RSN Capabilities bit 6 is MFPR (required) and bit 7 is MFPC (capable); they were reversed. OCV capable (bit 14) is now decoded too.
- **Bonded-channel center wrong / APs missing from the graph** — iw's VHT "center freq segment" is a channel index, not MHz. A 2.4 GHz HT40 AP with a vendor VHT IE got a 3 MHz center and vanished from the spectrum graph. Centers now come from the HT/VHT/HE-6 GHz/EHT Operation elements with the standard CCFS0/CCFS1 rules, including 160 MHz signalled through CCFS1 and 80+80.
- **Security label wrong without iw data** — WPA3-SAE, WPA2/WPA3 transition and Enterprise networks fell back to "WPA2 (PSK)", and plain WPA2 could show as "WPA/WPA2". Labels now use iw's AKM suites, or nmcli's real `RSN-FLAGS`/`SECURITY` tokens, and distinguish WPA3-Enterprise, WPA2/WPA3-Enterprise and 192-bit (Suite B).
- **6 GHz bonding incomplete** — added the 40/80/160 MHz blocks above ch 181/167 and both 320 MHz channelizations (320-1 and 320-2, selected by the EHT Operation element).
- **Channel ↔ frequency collisions** — `chan_to_freq(1)` returned 5955 MHz (6 GHz) instead of 2412; channel math is now band-aware and handles 6 GHz ch 2 (5935 MHz).
- **dBm estimate up to 10 dB off** — when iw has no exact RSSI, dBm is now the exact inverse of NetworkManager's -100…-40 dBm quality mapping.
- **DTIM never shown** — the TIM IE format was mis-parsed; DTIM now also comes from `station dump` for the connected AP.
- **Connected link frequency never parsed** — iw 6.x prints `freq: 5745.0`.
- **"WiFi 5" on 2.4 GHz** — vendor VHT IEs on 2.4 GHz (Broadcom TurboQAM) are now labelled as proprietary 256-QAM on Wi-Fi 4/6.
- **Channel busy % was a lifetime average** — now computed from survey counter deltas between polls.
- **Vendor IEs ignored** — plain `iw scan dump` omits vendor-specific IEs, so the Vendor IEs field was always empty and the v1.9.5 Meraki detection never fired. A single `scan dump -u` pass now provides everything (and halves the iw calls).
- **Cisco AP name** — read from the fixed 16-byte field in IE 133, so a client count ≥ 32 is no longer appended to the name.
- **Max PHY rate** — computed per MCS/NSS/width from subcarrier counts, including EHT MCS 12/13 (4096-QAM).
- **Per-chain station signal** — `signal avg` with per-antenna values in brackets is now parsed.
- **Misc** — HE/EHT GI shown in µs, TWT only flagged for TWT responders, BSS color "disabled" honoured, negative TPC values accepted, nmcli SSIDs ending in a backslash no longer shift columns, localized nmcli output no longer breaks parsing, duplicate rows with two Wi-Fi adapters merged, iw data collected from every managed interface.
- **Vendor guess transparency** — the "OUI suffix" heuristic for randomized/LAA MACs is now labelled as a guess instead of "OUI database".

### Fixes — application
- **Root shell injection in packet capture** — capture paths and interface names were pasted unquoted into scripts run as root. Scripts are now fixed text taking validated positional arguments, stored in a private 0700 temp directory.
- **Networking left down after capture** — the monitor-mode script now restores the interface and NetworkManager from an EXIT trap, uses `nmcli device set … managed no` instead of stopping NetworkManager by default, and quitting WaveScope during a capture stops it and restores the interface first.
- **6 GHz monitor capture on the wrong channel** — tuning now uses `iw set freq` (with a width selector) for every band; setup failures are reported instead of silently capturing elsewhere.
- **Crash on pause/resume or exit** — the scanner thread now stops within ~200 ms (interruptible sleep and subprocesses) and is never dropped while running.
- **Table jumping / lost column widths** — scans are applied as a row diff, so selection, scroll position and user-set column widths survive refreshes.
- **Filters not reaching the channel graph** until the next scan; the graph now updates immediately.
- **Unbounded memory on long surveys** — signal history, legend and per-BSSID caches are now pruned.
- **Stale values** — lingering (vanished) APs no longer keep "connected" telemetry; the dBm column no longer freezes while iw misses a BSS; a restored frequency now also restores the band.
- **OUI download dialog** could be closed mid-download and crash; database reload now happens on the GUI thread.
- **Context menu "View details"** could open the wrong AP after a re-sort.
- **Refresh interval** combo and scanner disagreed at startup; NetworkManager rescans now follow its ~10 s rate limit.
- **Beacon-supplied strings** (SSID, AP name, WPS data) are HTML-escaped in the details panels.
- **Atomic writes** for the OUI database and Known SSIDs files.

### New Features
- **SSIDs grouped per radio in the channel graph** — BSSIDs sharing one radio (same AP, channel and width, within 3 dB) are drawn as one shape at the strongest member's RSSI instead of overlapping curves. A new setting above the graph, "Radios with several SSIDs", chooses the label: AP name with BSSID fallback (default), BSSID, the shortest SSID, or all SSIDs stacked. Hovering the label always lists every member; selecting any of its SSIDs (click or table) expands the label to the full list with the selected one marked. The choice is saved.
- **Settings saved between sessions** — theme, refresh interval, linger time, band filter, column widths, splitters and window geometry.
- **Channel congestion score** — per 20 MHz channel from overlapping BSS count, signal and BSS Load utilization (hover the channel graph or see Details).
- **BSS color collision alerts** — flagged in the graph (⚠), the status bar and Details.
- **Wi-Fi 6E/7 detail** — PSC markers on the 6 GHz panel, 6 GHz AP power type (LPI/SP/VLP), EHT punctured subchannels drawn as gaps, MLD MAC with multi-link AP grouping, co-located APs from the Reduced Neighbor Report.
- **Security detail** — RSNX (SAE H2E, SAE-PK), RSN Element Override AKMs, group management cipher, OWE transition pairs.
- **Roaming detail** — 802.11r Mobility Domain ID and FT-over-DS, roam candidates for the connected SSID with signal delta.
- **Link detail** — SNR, per-antenna-chain RSSI.
- **More AP detail** — basic rates and 802.11b-rates warning, Country IE per-channel power limits, Power Constraint, Transmit Power Envelope, iw "last seen" age, PSC/DFS notes, bonded block and block center.
- **AP grouping** — locally-administered BSSID variants now group with their base MAC.

### Packaging & repo
- **AppImage on minimal openSUSE** — the PyPI Qt 6 wheels need `libgthread-2.0.so.0`, a separate package on openSUSE; the AppImage now bundles it (it is not on the AppImage excludelist) and `install.sh` lists `libgthread-2_0-0` for zypper.
- **AppImage failed to start on Ubuntu 22.04 and older distros** — it bundles the build machine's Python, and the release job had moved to Ubuntu 24.04 (glibc 2.38). It is now built on Ubuntu 22.04 and needs only glibc 2.35, as the AppImage catalog test (AppImage/appimage.github.io#8302) requires.
- **Release packages missing from v1.9.5** — the AppImage and openSUSE RPM uploads raced to create the GitHub release; a `create-release` job now runs first.
- **.deb could not start the app** — pyqtgraph imports `PyQt6.uic`, which on Debian/Ubuntu lives in `pyqt6-dev-tools`; now a dependency. The .deb requires Debian 12+ / Ubuntu 24.04+ (documented).
- **Fedora RPM could not install** — `python3-qt6` does not exist on Fedora 44; now `python3-pyqt6`.
- Install-time venv setup is non-fatal with a recovery command (`sudo /opt/wavescope/setup-venv.sh`) and uses pinned `constraints.txt`.
- RPMs own `/opt/wavescope` and ship `%license`; the .deb ships a copyright file; AppStream metainfo added to all packages; desktop category fixed.
- AppImage: metainfo, desktop file and icon under `usr/share`; Docker build wrapper `scripts/build_appimage_docker.sh`.
- `install.sh` supports apt, dnf and zypper and checks for `nmcli`/`iw`/`tcpdump`/`pkexec`.
- Release CI: manual re-run for an existing tag (`workflow_dispatch`), pinned `fedora:44`, lint job (ruff + compileall).
- README updated (install commands matching real asset names, openSUSE section, dependencies, features); CONTRIBUTING.md, issue template and `pyproject.toml` added.

## v1.9.5 — 2026-09-17

### New Features
- **Cisco Meraki detection from vendor IE** — APs that advertise the Meraki vendor-specific IE (OUI `00:18:6e`) are now labelled "Cisco Meraki" even when their BSSID OUI is missing from the local OUI database, which is common on newer hardware.

## v1.9.4 — 2026-07-22

### New Features
- **Startup dependency check** — WaveScope now checks for `nmcli`, `iw`, `tcpdump`, and `pkexec` on launch. If any are missing, a dialog lists which ones and what breaks without them, with the choice to proceed anyway (degraded/inaccurate results) or quit and install them first.

### Fixes
- **`iw` not found on PATH** — on many distros (openSUSE, Fedora, …) `iw` lives in `/usr/sbin`, which isn't on a typical desktop session's `PATH`. WaveScope was invoking `iw` (and `nmcli`/`pkexec`) by bare name and silently swallowing the resulting `FileNotFoundError`, which disabled *all* `iw`-based enrichment (6 GHz channel width fallback, WiFi generation, BSS Load, k/v/r support, station link stats). WaveScope now resolves each tool's full path at startup, falling back to `/usr/sbin` and `/sbin` when it isn't on `PATH`. This is very likely the actual cause of 6 GHz networks still showing `0 MHz` width after the v1.9.3 fallback fix.

## v1.9.3 — 2026-06-01

### Fixes
- **6 GHz channel width fallback** — when NetworkManager/nmcli reports `BANDWIDTH=0 MHz` for a 6 GHz BSS, WaveScope now falls back to the explicit `iw` HE Operation `Channel Width:` value before using any capability-based heuristics. This fixes 20 MHz 6 GHz networks being misclassified as 80 MHz.

## v1.9.2 — 2026-05-16

### New Features
- **TX power for Aruba, Ruckus, and any 802.11h AP** — the "Power Level" column now populates for three sources (in priority order): Cisco proprietary IE 150, Ruckus OUI `00:13:92` (half-dBm encoded, reverse-engineered from a live SmartZone deployment), and the standard 802.11h TPC Report IE (covers Aruba, Juniper Mist, Extreme, and any other vendor that includes it).
- **Aruba AP name** — WaveScope now reads the AP name from the Aruba vendor IE (`OUI 00:0b:86`, subtype `0x03`). Requires "Include AP name in beacons" to be enabled on the Aruba Mobility Controller or Aruba Central WLAN profile.

## v1.9.1 — 2026-05-02

### New Features
- **Vendor beacon IE module** (`vendor_beacon.py`) — vendor-specific beacon IE parsers (Cisco IE 133 AP name, Cisco IE 150 TX power, Ubiquiti IE 221 AP name) are now modularised into a dedicated registry. Adding support for new vendors requires only writing a single parser function and appending it to the `_PARSERS` list.

### Fixes
- **Channel `?` for some APs** — nmcli returns `CHAN=0` for certain 5 GHz channels (observed on ch 144 / 5720 MHz). WaveScope now falls back to deriving the channel number from the reported frequency using the standard IEEE 802.11 formula, covering 2.4, 5, and 6 GHz bands.
- Added `channel` and `freq_mhz` to sticky-nonzero field cache so channel info is preserved across linger cycles even if nmcli misses a cycle.

### Improvements
- **Toolbar redesign** — replaced the flat single-row toolbar with grouped pill sections: SCAN (pause, refresh interval, linger, tools menu), VIEW (sidebar toggle), and Filters (search, band, known SSIDs, edit).
- **Known SSIDs** — persistent list of favourite/notable SSIDs stored in `~/.local/share/wavescope/known_ssids.json`. Filter toolbar combo (All / Only known / Hide known), context-menu add/remove, and an Edit dialog showing the count in the title.
- Light-mode fixes for toolbar pills, AP sidebar, Known SSIDs dialog, and Capture type dialog.

## v1.9.0 — 2026-05-02

### New Features
- **AP Group Sidebar** — a collapsible left-hand panel lists every detected physical access point, grouped by BSSID affinity (the low nibble of the last MAC octet is masked, capturing the 16-address block most enterprise APs allocate across their radios/SSIDs). Each group is labelled with a short vendor name and the masked nibble range (e.g. `Cisco:33:16:E#`), making multi-radio deployments immediately recognisable.
- **Sidebar filtering** — clicking an AP group in the sidebar narrows the main table to only those BSSIDs. Clicking again (or the **All APs** row at the top) restores the full view. Right-clicking an AP group offers *Show only this AP* and *Hide this AP* / *Unhide* actions.
- **Table context-menu AP filter** — the *Show only* and *Hide* sub-menus now include a **This AP** entry that applies the same physical-AP group filter directly from the table right-click menu.
- **Sidebar toggle** — a new **⊞ APs** toolbar button collapses or expands the sidebar panel. Dragging the splitter handle to zero also collapses it; the last width is remembered and restored on expand.

### Improvements
- *Clear filters* now clears AP-group filters in addition to column filters, and the filter badge reflects active AP-group selections.

## v1.8.7 — 2026-05-01

### New Features
- Added Ubiquiti AP-name detection from vendor-specific IE 221 (OUI `00:15:6d`, type `0x01`) in the `iw -u` enrichment path, feeding the existing **AP Name** field.
- Added Cisco **Power Level** parsing from IE 150 and surfaced it in both the table (auto-shown when present) and Details panel, with `dBm` units.

### Improvements
- Updated table sizing behavior to preserve natural column widths on narrow windows and rely on horizontal scrolling instead of compressing/cropping columns.

## v1.8.6 — 2026-05-01

### Fixes
- Fixed `.deb` installation dependency resolution on newer Ubuntu releases by updating the PolicyKit dependency alternatives in `build_deb.sh` to include currently installable package names (`polkitd`/`pkexec`) while preserving compatibility alternatives.

## v1.8.5 — 2026-05-01

### New Features
- **Cisco AP Name** — WaveScope now decodes the Cisco proprietary IE 133 present in beacons broadcast by Cisco/Meraki access points. When available, the physical AP system name (e.g. `SDA-Hall-B1-34-`) is shown in a new **AP Name** column in the main table and as a dedicated **AP Name** row in the Details panel. The column is hidden automatically when no APs in the current scan advertise this IE, and appears as soon as at least one name is resolved.

## v1.8.3 — 2026-02-25

### Fixes
- Fixed vendor icons missing in `.deb` builds; `build_deb.sh` now copies the full `assets/` directory (including `vendor-icons/`, `vendors.json`, and `vendor_urls.json`) instead of only `icon.svg`.

## v1.8.2 — 2026-02-24

### Fixes
- Fixed GNOME launcher icon not appearing due to conflicting user-level and system-level `.desktop` files; `install.sh` no longer creates a user-level entry when the `.deb` is installed.
- Fixed generic dock icon when launching from CLI by setting `GIO_LAUNCHED_DESKTOP_FILE` in the launcher script, allowing GNOME to correctly associate the running process with its `.desktop` entry.
- Fixed DBus portal error (`Connection already associated with an application ID`) by calling `setDesktopFileName` before `setApplicationName` in the Qt application setup.
- Fixed `.deb` postinst/postrm icon cache update failing silently on systems without `gtk-update-icon-cache`; now falls back to `gtk4-update-icon-cache` and `update-icon-caches`.

## v1.8.1 — 2026-02-24

### Fixes
- Details tab now applies dark-mode styling on first launch, matching the appearance after any subsequent theme switch (no more visible box borders appearing only after a theme change).
- Default linger duration reduced from 120 s to 60 s.

## v1.8.0 — 2026-02-24

### Highlights
- **2.4 GHz channel allocation graph** — redesigned with accurate ±1.5-channel RF spans, frequency-based positioning, and correct non-overlapping channel plan rows.
- **Hidden network fix** — double rescan on startup ensures hidden SSIDs appear on the first result instead of after 30–45 s.
- **UI improvements** — uniform toolbar button styles; first-scan overlay while the table is empty; Channel Allocations button moved to the status bar.

## v1.7.0 — 2026-02-24

### Highlights
- **Hidden network detection** — startup scan now runs two back-to-back `--rescan yes` sweeps so hidden APs (e.g. 5 GHz networks that require a probe response) appear on the very first result, instead of taking 30–45 s.
- **6 GHz rate fix** — 6 GHz APs no longer show 0 Mbit/s; theoretical max rate is now computed from HE Capabilities (NSS × MCS table per IEEE 802.11ax) when nmcli returns 0.
- **Channel Allocation graphs** — new "🗺️ Channel Allocations" toolbar button opens a combined reference dialog with 2.4 GHz, 5 GHz, and 6 GHz allocation tables, zoomable and horizontally stretching to fill the window.
- **Linger / ghost mode** — APs that disappear from scans remain visible (dimmed) for a configurable window (default 60 s) so transient dropouts don't cause entries to flicker in and out.
- **Sticky non-zero fields** — bandwidth, rate, Wi-Fi gen, country, and center frequency no longer blank out due to transient nmcli parse misses; last known good value is preserved.
- **Code modularisation** — core logic split into focused modules (`core_models`, `core_scanner`, `core_table`, `core_base`, `main_window_ui`, `main_window_logic`) for easier maintenance.
- **New vendor icon** — DASAN Networks added to the vendor icon set.

## v1.6.0 — 2026-02-22

### Highlights
- Added a new Connection tab focused on the currently connected BSSID.
- Expanded wireless engineering telemetry in Details/Connection (beacon/RSN/capability and link metrics).
- Improved Signal History with a dedicated resizable SSID pane and line hover tooltips.

## v1.5.2 — 2026-02-22

### Highlights
- Improvements to Details Tab.
- Removed colored background tags in Details for a cleaner, less noisy view.
- Improved Security and AKM dual-line display to avoid redundant second lines and hide source prefixes.
- Made Manufacturer source visibility more reliable and improved WPA/RSN display wording for network-engineering readability.

## v1.5.1 — 2026-02-22

### Highlights
- Added AppImage build support in GitHub Actions release workflow.
- Added Docker-based AppImage build path so AppImage can be built without host `appimagetool`.
- Moved package build scripts into `scripts/` (`build_deb.sh`, `build_rpm.sh`, `build_appimage.sh`) and updated references.
- Added AppImage build artifacts to `.gitignore`.

## v1.5.0 — 2026-02-22

### Highlights
- Improved vendor matching for difficult MAC addresses (including locally-administered / transformed BSSIDs).
- Added WPS-based vendor detection from `iw` scan data when available.
- Added vendor icon support in the UI for recognized manufacturers.
- Added manufacturer details in the Details tab, including source and raw WPS manufacturer value.
- Updated bundled vendor assets (`vendors.json`, `vendor_urls.json`, and vendor icons) and added a sync script for vendor assets.

## v1.4.0 — 2026-02-22

### Highlights
- Improved channel graph readability and consistency across 2.4 / 5 / 6 GHz panels.
- Added clear U-NII / ISM labels under channel ticks and improved 6 GHz channel coverage on the x-axis.
- Added DFS visual indication on 5 GHz so DFS channels are easier to identify.
- Added 6 GHz bonded-channel lookup tables for more accurate center/span rendering.
- Channel graph now preserves your zoom/pan view when data refreshes.
- Switched offline manufacturer fallback to bundled `assets/vendors.json` (downloaded database still preferred when available).

## v1.3.1 — 2026-02-22

### New features
- **2.4 GHz bonded-channel graph** — the spectrum graph now correctly centers 40 MHz (HT40) access points on the true bonded-block center. `iw` reports the secondary channel offset (`above`/`below`), which is used to compute the actual ±10 MHz shift. Example: ch 6 HT40+ renders over the ch 6–10 block.
- **6 GHz bonded-channel graph** — 40/80/160/320 MHz shapes are now correctly placed using the `center freq 1` value from `iw`. Example: 160 MHz on ch 1 renders over the ch 1–29 block.
- **Ch. Span for 2.4 / 6 GHz** — the Ch. Span table column now shows the actual bonded channel range for 2.4 GHz 40 MHz (e.g. `6–10`) and 6 GHz wider blocks (e.g. `1–29`).
- **iw field persistence** — Gen, Ch.Util%, Clients, k/v/r, AKM and other `iw`-enriched fields no longer blank out between scan cycles. The last known value is held for up to 5 consecutive missed cycles, after which it clears naturally.

### Fixes
- **5 GHz x-axis** — removed spurious channel 32 (5160 MHz); the 5 GHz panel now starts at channel 36 as per standard deployments.
- **Column widths** — Width (MHz) column widened to 96 px; Ch. Span column now has a proper initial width (82 px) instead of falling back to Qt's narrow default.

## v1.3.0 — 2026-02-22

### New features
- **Correct 5 GHz spectrum placement** — channel shapes in the graph are now centered on the true bonded-block center frequency, not just the primary 20 MHz channel center. Examples: ch 116 @ 80 MHz renders over 116–128; ch 100 @ 160 MHz renders over 100–128.
- **Ch. Span column** — new table column showing the full channel range an AP occupies (e.g. `116–128` for ch 116 @ 80 MHz on 5 GHz, or `100–128` for 160 MHz).
- **Filter-aware channel graph** — the spectrum graph now updates live as you type in the search box, change the band filter, or apply right-click Show/Hide column filters. Only visible APs are drawn.
- **Channel width right-click filter** — "Channel Width" (20/40/80/160 MHz) is now available in the Show only / Hide context-menu filter.
- **U-NII sub-band colours on 5 GHz x-axis** — channel tick labels are colour-coded by regulatory band: U-NII-1 (green), U-NII-2A (blue), U-NII-2C (amber), U-NII-3 (lighter green), U-NII-4 (red).

### Changes
- **Column renamed**: "BW (MHz)" → "Width (MHz)" — *channel width* is the correct IEEE 802.11 term for the bonded block size.
- **Unknown manufacturer is now blank** — the Manufacturer column shows an empty cell instead of "Unknown" when the OUI is not found.
- **Rebranded paths** — all internal paths and identifiers migrated from `nmcli-gui` to `wavescope` (`~/.local/share/wavescope`, User-Agent header, Qt organisation name).
- Removed deprecated `wifi-analyzer` launcher script.
