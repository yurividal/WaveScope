#!/usr/bin/env python3
"""Render WaveScope with a synthetic RF environment and save screenshots.

Used for the README screenshot.  Runs on Qt's offscreen platform with a
throw-away HOME / XDG config, so the user's real settings, labels and Known
SSIDs are never read or written, and no scanning happens.

Usage:  python3 devtools/demo_screenshot.py [OUT_DIR]   (default: ./demo-shots)
"""

from __future__ import annotations

import math
import os
import random
import sys
import tempfile

# ── isolate *before* importing Qt / WaveScope (paths are resolved at import) ──
_TMP = tempfile.mkdtemp(prefix="wavescope-demo-")
os.environ["HOME"] = _TMP
os.environ["XDG_CONFIG_HOME"] = os.path.join(_TMP, ".config")
os.environ["XDG_DATA_HOME"] = os.path.join(_TMP, ".local", "share")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pyqtgraph as pg  # noqa: E402
from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtGui import QFont, QIcon  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from wavescope_app.core import (  # noqa: E402
    AccessPoint,
    chan_to_freq,
    dbm_to_nm_quality,
    phy_rate_mbps,
)
from wavescope_app.main_window import MainWindow  # noqa: E402
from wavescope_app.theme import GRAPH_AXIS_DARK, GRAPH_BG_DARK, _dark_palette  # noqa: E402

random.seed(7)

# OUIs taken from the bundled vendor database (all have vendor icons)
OUI = {
    "cisco": "E8:0A:B9", "meraki": "9C:E3:30", "aruba": "14:02:EC", "ubiquiti": "F0:9F:C2",
    "tplink": "34:F7:16", "netgear": "40:5D:82", "ruckus": "D4:BD:4F", "mist": "00:3E:73",
    "eero": "08:F0:1E", "google": "60:70:6C", "avm": "BC:05:43", "sagemcom": "58:1D:D8",
    "espressif": "D4:8A:FC", "samsung": "00:02:78", "fortinet": "74:78:A6", "extreme": "88:7E:25",
    "asus": "00:26:18",
}

SEC = {
    # name: (nmcli SECURITY, RSN flags, WPA flags, AKM suites, PMF)
    "wpa3e": ("WPA2 802.1X", "pair_ccmp group_ccmp 802.1X", "(none)", ("802.1X/SHA-256",), "Required"),
    "wpa23e": ("WPA2 802.1X", "pair_ccmp group_ccmp 802.1X", "(none)", ("802.1X", "802.1X/SHA-256"), "Optional"),
    "sae": ("WPA3", "pair_ccmp group_ccmp sae", "(none)", ("SAE", "SAE-EXT-KEY"), "Required"),
    "trans": ("WPA2 WPA3", "pair_ccmp group_ccmp psk sae", "(none)", ("PSK", "SAE"), "Optional"),
    "psk": ("WPA2", "pair_ccmp group_ccmp psk", "(none)", ("PSK",), "No"),
    "tkip": ("WPA1 WPA2", "pair_ccmp pair_tkip group_tkip psk", "pair_tkip group_tkip psk", ("PSK",), "No"),
    "owe": ("OWE", "pair_ccmp group_ccmp owe", "(none)", ("OWE",), "Required"),
    "open": ("", "(none)", "(none)", (), ""),
}

GEN_FAMILY = {"WiFi 7": ("EHT", 13), "WiFi 6E": ("HE", 11), "WiFi 6": ("HE", 11), "WiFi 5": ("VHT", 9), "WiFi 4": ("VHT", 7)}


def mk(vendor, suffix, ssid, band, ch, bw, dbm, sec, gen, **extra) -> AccessPoint:
    nm_sec, rsn, wpa, akms, pmf = SEC[sec]
    freq = chan_to_freq(ch, band)
    fam, mcs = GEN_FAMILY.get(gen, ("VHT", 7))
    nss = extra.pop("nss", 2)
    rate = phy_rate_mbps(fam, bw if fam in ("HE", "EHT") else min(bw, 160), nss, mcs) if gen else 54.0
    ap = AccessPoint(
        ssid=ssid, bssid=f"{OUI[vendor]}:{suffix}".upper(), mode="Infra", channel=ch, freq_mhz=freq,
        rate_mbps=float(int(rate)), signal=dbm_to_nm_quality(dbm), security=nm_sec, wpa_flags=wpa,
        rsn_flags=rsn, bandwidth_mhz=bw, in_use=extra.pop("in_use", False),
    )
    ap.dbm_exact = float(dbm)
    ap.wifi_gen = gen
    ap.akm_suites, ap.pmf = akms, pmf or "No"
    ap.has_rsn_ie, ap.has_wpa1_ie = rsn != "(none)", wpa != "(none)"
    ap.iw_seen = True
    ap.akm = ap.akm or " ".join(akms)
    ap.beacon_interval_tu = 100
    ap.dtim_period = extra.pop("dtim", 1)
    ap.last_seen_ms = random.randint(150, 4000)
    ap.phy_cap_summary = {"EHT": "HT/VHT/HE/EHT", "HE": "HT/VHT/HE", "VHT": "HT/VHT"}.get(fam, "HT") + f" · max width {bw} MHz"
    for k, v in extra.items():
        setattr(ap, k, v)
    if ap.bss_color is not None:
        ap.he_eht_features = f"BSS color {ap.bss_color}, TWT responder"
    return ap


def build_scene():
    aps = []
    # ── Contoso HQ: Cisco Catalyst APs, three SSIDs per radio, all bands ─────
    for ap_i, (base, name, ch24, ch5, ch6, d24, d5, d6, col) in enumerate(
        [
            ("C7:22:40", "HQ-3F-EAST", 1, 149, 37, -48, -45, -43, 11),
            ("C7:23:80", "HQ-3F-WEST", 6, 36, 101, -66, -64, -70, 23),
            ("C7:25:C0", "HQ-2F-LOBBY", 11, 100, 165, -76, -74, -79, 37),
        ]
    ):
        oct4, oct5, last = base.split(":")
        lb = int(last, 16)
        common = dict(ap_name=name, country="US", country_env="Indoor/Outdoor", rrm=True, btm=True, ft=True,
                      mobility_domain="a1c3", cisco_tx_power_dbm=17 - ap_i * 2, power_constraint_db=0)
        for i, (ssid, sec) in enumerate((("Contoso-Corp", "wpa23e"), ("Contoso-Guest", "owe"), ("Contoso-IoT", "psk"))):
            aps.append(mk("cisco", f"{oct4}:{oct5}:{lb + i:02X}", ssid, "2.4 GHz", ch24, 20, d24 - i, sec, "WiFi 6",
                          chan_util=random.randint(18, 52), station_count=random.randint(3, 14), bss_color=col,
                          basic_rates="12 24", has_11b_rates=False, **common))
            aps.append(mk("cisco", f"{oct4}:{oct5}:{lb + 0x0E - i:02X}", ssid, "5 GHz", ch5, 80, d5 - i, sec, "WiFi 6",
                          chan_util=random.randint(8, 35), station_count=random.randint(5, 22), bss_color=col + 1,
                          basic_rates="12 24", **common))
        # 6 GHz radio: Wi-Fi 7, WPA3 only (6 GHz requires WPA3/OWE)
        for i, (ssid, sec) in enumerate((("Contoso-Corp", "wpa3e"), ("Contoso-Guest", "owe"))):
            six = mk("cisco", f"{oct4}:{oct5}:{lb + 0x08 + i:02X}", ssid, "6 GHz", ch6, 320 if ap_i == 0 else 160,
                     d6 - i, sec, "WiFi 7", chan_util=random.randint(3, 15), station_count=random.randint(1, 9),
                     bss_color=col + 2, he_6ghz_ap_type="Standard Power (SP)",
                     **dict(common, mobility_domain="a1c3"))
            if ap_i == 0:
                six.punct_bitmap = 0x0010  # one punctured 20 MHz subchannel
                six.iw_center_freq = 6105
            aps.append(six)

    # connected: HQ-3F-EAST 6 GHz Contoso-Corp
    conn = next(a for a in aps if a.ap_name == "HQ-3F-EAST" and a.band == "6 GHz" and a.ssid == "Contoso-Corp")
    conn.in_use = True
    conn.conn_iface = "wlp0s20f3"
    conn.conn_link_freq_mhz = conn.freq_mhz
    conn.conn_link_signal_dbm = conn.dbm_exact
    conn.conn_rx_bitrate = "4803.9 MBit/s 320MHz EHT-MCS 13 EHT-NSS 2 EHT-GI 0"
    conn.conn_tx_bitrate = "2161.8 MBit/s 320MHz EHT-MCS 9 EHT-NSS 2 EHT-GI 0"
    conn.conn_rx_phy = "EHT · MCS 13 · NSS 2 · GI 0.8 µs · 320 MHz"
    conn.conn_tx_phy = "EHT · MCS 9 · NSS 2 · GI 0.8 µs · 320 MHz"
    conn.conn_signal_chains = "-44, -42"
    conn.conn_signal_avg_dbm = -43
    conn.conn_tx_retries, conn.conn_tx_failed, conn.conn_tx_packets = 412, 3, 58233
    conn.conn_rx_packets, conn.conn_rx_bytes, conn.conn_tx_bytes = 91822, 188_334_120, 21_993_871
    conn.conn_connected_time_s, conn.conn_inactive_ms = 3725, 12
    conn.conn_tx_retry_rate_pct, conn.conn_tx_fail_rate_pct = 1.8, 0.0
    conn.conn_survey_busy_pct, conn.conn_survey_noise_dbm, conn.conn_snr_db = 12.4, -95, 52.0

    # ── neighbours ───────────────────────────────────────────────────────────
    aps += [
        mk("meraki", "4A:10:21", "Bean & Leaf Café", "2.4 GHz", 6, 20, -58, "open", "WiFi 6", chan_util=58,
           station_count=27, bss_color=23, country="US"),
        mk("meraki", "4A:10:2C", "Bean & Leaf Café", "5 GHz", 44, 40, -52, "open", "WiFi 6", chan_util=22,
           station_count=11, bss_color=9, country="US"),
        mk("aruba", "8F:31:A0", "Northwind-Staff", "5 GHz", 52, 80, -70, "wpa3e", "WiFi 6", chan_util=31,
           station_count=8, bss_color=14, rrm=True, btm=True, country="US"),
        mk("aruba", "8F:31:B0", "Northwind-Staff", "6 GHz", 69, 160, -63, "sae", "WiFi 6E", bss_color=15,
           he_6ghz_ap_type="Indoor (LPI)", country="US"),
        mk("ubiquiti", "2B:77:10", "Fabrikam-Studio", "5 GHz", 157, 80, -55, "trans", "WiFi 6", chan_util=17,
           station_count=4, bss_color=40),
        mk("ubiquiti", "2B:77:11", "Fabrikam-Studio", "6 GHz", 133, 160, -60, "sae", "WiFi 7", bss_color=41,
           he_6ghz_ap_type="Indoor (LPI)"),
        mk("tplink", "A9:01:5E", "TP-Link_5E9C", "2.4 GHz", 3, 40, -77, "tkip", "WiFi 4", has_11b_rates=True,
           basic_rates="1 2 5.5 11", iw_center_freq=2432, chan_util=64),
        mk("netgear", "11:C4:02", "NETGEAR42", "5 GHz", 116, 160, -88, "psk", "WiFi 5", dtim=5),
        mk("eero", "77:31:9A", "Wintergarden", "5 GHz", 149, 80, -71, "trans", "WiFi 6", bss_color=11),
        mk("google", "3E:88:01", "Nest-Wifi-Pro", "6 GHz", 197, 160, -72, "sae", "WiFi 6E",
           he_6ghz_ap_type="Indoor (LPI)"),
        mk("avm", "19:5A:7C", "FRITZ!Box 7590", "5 GHz", 60, 80, -79, "trans", "WiFi 5"),
        mk("samsung", "5F:21:33", "[TV] Samsung Q90 Series", "5 GHz", 165, 20, -66, "psk", "WiFi 4"),
        mk("ruckus", "2C:44:90", "Adatum-Secure", "5 GHz", 132, 40, -77, "wpa23e", "WiFi 6",
           ruckus_tx_power_dbm=18.5, bss_color=31, rrm=True, btm=True),
        mk("mist", "9A:6E:20", "Litware-WLAN", "5 GHz", 165, 20, -80, "wpa3e", "WiFi 6", bss_color=5),
        mk("fortinet", "81:0C:1D", "Tailspin-Office", "5 GHz", 120, 40, -66, "wpa23e", "WiFi 6", bss_color=7),
        mk("extreme", "3D:5B:90", "Woodgrove-BYOD", "5 GHz", 100, 40, -84, "psk", "WiFi 6", bss_color=38),
        mk("asus", "4E:12:A8", "ASUS_RT-BE96U", "6 GHz", 197, 320, -62, "sae", "WiFi 7",
           he_6ghz_ap_type="Indoor (LPI)", iw_center_freq=6745),
    ]
    # one that just vanished (dimmed, lingering)
    ghost = mk("netgear", "11:C4:09", "NETGEAR42-Guest", "2.4 GHz", 8, 20, -89, "psk", "WiFi 5")
    ghost.is_lingering = True
    aps.append(ghost)
    return aps, conn


def fill_history(mw, aps) -> None:
    """Two minutes of plausible RSSI history for the strongest BSSs."""
    hg = mw._history_graph
    now = 120.0
    hg._t0 -= now
    for ap in sorted((a for a in aps if not a.is_lingering), key=lambda a: -a.dbm)[:12]:
        level, drift = float(ap.dbm), 0.0
        hg._ssid_map[ap.bssid] = ap.display_ssid
        for t in range(0, 121, 2):
            drift = 0.7 * drift + random.gauss(0, 1.1)
            walk = 3.0 * math.sin(t / 19.0 + hash(ap.bssid) % 7)  # slow fade
            hg._history[ap.bssid].append((float(t), level + walk + drift - (2.0 if t < 60 else 0.0)))
    hg._redraw(now)


def main() -> int:
    out_dir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "demo-shots")
    os.makedirs(out_dir, exist_ok=True)
    pg.setConfigOptions(antialias=True, foreground=GRAPH_AXIS_DARK, background=GRAPH_BG_DARK)
    app = QApplication(sys.argv)
    app.setDesktopFileName("wavescope")
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    app.setWindowIcon(QIcon(os.path.join(ROOT, "assets", "icon.svg")))
    for name in ("Inter", "Noto Sans", "Ubuntu", "DejaVu Sans"):
        font = QFont(name, 10)
        if font.exactMatch():
            break
    app.setFont(font)

    # No scanning, no first-run OUI prompt.
    MainWindow._start_scanner = lambda self: None
    MainWindow._prompt_oui_download = lambda self: None
    mw = MainWindow()
    mw.resize(1720, 1010)
    mw._annotations.set("e8:0a:b9:c7:22:4*", "3F East · Room 312")
    mw._annotations.set("e8:0a:b9:c7:25:c*", "Lobby")

    aps, conn = build_scene()
    mw.show()
    mw._on_source_active("iw")
    mw._on_data(aps)
    fill_history(mw, aps)
    mw.statusBar().showMessage(f"Found {len(aps)} access points  |  Showing {len(aps)}")

    shots = []

    def snap(name: str) -> None:
        for _ in range(5):
            app.processEvents()
        path = os.path.join(out_dir, f"{name}.png")
        mw.grab().save(path)
        shots.append(path)

    def run() -> None:
        mw._tabs.setCurrentIndex(0)
        snap("1-channel-graph")
        mw._tabs.setCurrentIndex(1)
        snap("2-signal-history")
        mw._open_details_for_bssid(conn.bssid)
        snap("3-details")
        mw._tabs.setCurrentIndex(mw._issues_tab_index)
        snap("4-issues")
        mw._tabs.setCurrentIndex(mw._connection_tab_index)
        snap("5-connection")
        print("\n".join(shots))
        app.quit()

    QTimer.singleShot(400, run)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
