# Changelog

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
