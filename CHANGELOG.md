# Changelog

## [1.0.3] – 2026-02-21

### Fixed — 6 GHz (Wi-Fi 6E) channel graph

- **Empty-panel axes bug**: the 6 GHz panel previously showed a useless 0–1 x-axis
  when the band was selected but no APs had been detected yet. The panel now always
  renders the correct 5930–7130 MHz range regardless of whether any APs are visible.

- **Corrected CH6 channel map**: rewrote the formula as `5950 + channel × 5 MHz`
  (primary 20 MHz channels 1, 5, 9, …, 233) matching IEEE 802.11ax exactly.

- **Proportional panel width**: the 6 GHz panel stretch factor raised from 5 → 8,
  reflecting the band's ~1200 MHz span vs. ~840 MHz for 5 GHz.

- **Readable tick labels**: replaced the coarse stride-8 sampling with the
  standard **Preferred Scanning Channels (PSC)** set — ch 1, 5, 21, 37, 53, 69,
  85, 101, 117, 133, 149, 165, 181, 197, 213, 229, 233 — the channels Wi-Fi 6E
  routers actually use for 20/80/160/320 MHz operation.

- **UNII sub-band markers**: added colour-coded floor bars and dashed boundary
  lines for UNII-5/6/7/8, mirroring the existing DFS indicator on the 5 GHz panel:
  - 🟢 **UNII-5** (5925–6425 MHz) — Low-Power Indoor / VLP, no AFC required
  - 🟠 **UNII-6** (6425–6525 MHz) — Standard Power, AFC required
  - 🟠 **UNII-7** (6525–6875 MHz) — Standard Power, AFC required
  - 🟠 **UNII-8** (6875–7125 MHz) — Standard Power, AFC required

- **Dynamic panel**: 6 GHz panel continues to appear only when Wi-Fi 6E APs are
  actually detected, keeping the layout clean on hardware without 6 GHz support.

---

## [1.0.1] – 2025

### Changed
- UI overhaul: Details panel redesigned with QFormLayout, larger text, readable badge colours.
- Fix: GNOME dock icon grouping (StartupWMClass + setDesktopFileName).

---

## [1.0.0] – 2025

- Initial release.
