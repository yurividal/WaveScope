"""Unit tests for parsing, channel math, grouping and caching.

Each case pins down behaviour that was verified against an external
reference (iw / NetworkManager / hostap / Wireshark source) or that fixed a
real-world bug; the comment on each test says which.
"""

import copy
import types

import pytest
from PyQt6.QtCore import QCoreApplication

_app = QCoreApplication.instance() or QCoreApplication([])

import wavescope_app.core_scanner as sc  # noqa: E402
from wavescope_app.core import (  # noqa: E402
    AccessPoint,
    bonded_block,
    bssids_related,
    chan_to_freq,
    dbm_to_nm_quality,
    find_bss_color_collisions,
    laa_derived_pair,
    parse_iw_scan,
    phy_rate_mbps,
    signal_to_dbm,
)

T = "\t"


def _ap(**kw) -> AccessPoint:
    base = dict(
        ssid="x", bssid="00:11:22:33:44:55", mode="Infra", channel=36, freq_mhz=5180, rate_mbps=0,
        signal=60, security="", wpa_flags="(none)", rsn_flags="(none)", bandwidth_mhz=20, in_use=False,
    )
    base.update(kw)
    return AccessPoint(**base)


# ── iw text format ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "printed, expected",
    [
        ("Ohana", "Ohana"),
        ("Caf\\xc3\\xa9", "Café"),  # UTF-8 bytes are escaped by iw
        ("\\x20lead", " lead"),  # leading space is escaped
        ("a\\x5cb", "a\\b"),  # a literal backslash is escaped
        ("", ""),
        ("\\x00\\x00\\x00", ""),  # all-NUL = hidden SSID
    ],
)
def test_unescape_iw_ssid(printed, expected):
    # iw util.c print_ssid_escaped()
    assert sc._unescape_iw_ssid(printed) == expected


def test_headerless_bss_block_is_decoded():
    # iw omits "Information elements from …" for beacon-only BSSs; v2.0.1
    # treated all their IEs as metadata (24 of 34 BSSs lost their data).
    blk = (
        f"BSS 8a:78:48:ea:44:d7(on wlan0)\n{T}freq: 6135.0\n{T}signal: -56.00 dBm\n"
        f"{T}SSID: Ohana-6Ghz\n{T}TIM: DTIM Count 1 DTIM Period 3 Bitmap Control 0x0 Bitmap[0] 0x0\n"
        f"{T}RSN:{T} * Version: 1\n{T}{T} * Authentication suites: SAE\n"
        f"{T}{T} * Capabilities: 16-PTKSA-RC 1-GTKSA-RC MFP-required MFP-capable (0x00cc)\n"
        f"{T}EHT capabilities:\n{T}EHT Operation:\n{T}{T}EHT Operation Info: 0x03272f\n"
        f"{T}{T}{T}Channel Width: 160 MHz\n{T}{T}{T}Center Frequency Segment 0: 39\n"
        f"{T}{T}{T}Center Frequency Segment 1: 47\n"
    )
    d = parse_iw_scan(blk)["8a:78:48:ea:44:d7"]
    assert (d["wifi_gen"], d["iw_oper_bw"], d["iw_center_freq"], d["pmf"], d["dtim_period"], d["ssid"]) == (
        "WiFi 7", 160, 6185, "Required", 3, "Ohana-6Ghz",
    )


def test_rsn_pmf_bits():
    # hostap wpa_common.h: B6 = MFPR (required), B7 = MFPC (capable)
    assert sc._pmf_from_rsn_caps("1-PTKSA-RC (0x0080)") == "Optional"
    assert sc._pmf_from_rsn_caps("(0x00c0)") == "Required"
    assert sc._pmf_from_rsn_caps("(0x0028)") == "No"


def test_vht_160_via_ccfs1():
    # 802.11-2016 Table 9-252: width 1 with |CCFS1−CCFS0| = 8 → 160 @ CCFS1
    blk = (
        f"BSS 00:11:22:33:44:55(on wlan0)\n{T}freq: 5180.0\n{T}VHT capabilities:\n"
        f"{T}VHT operation:\n{T}{T} * channel width: 1 (80 MHz)\n"
        f"{T}{T} * center freq segment 1: 42\n{T}{T} * center freq segment 2: 50\n"
    )
    d = parse_iw_scan(blk)["00:11:22:33:44:55"]
    assert (d["iw_oper_bw"], d["iw_center_freq"]) == (160, 5250)


# ── channel math / signal / rates ────────────────────────────────────────────


def test_band_aware_channels():
    assert chan_to_freq(1) == 2412 and chan_to_freq(1, "6 GHz") == 5955
    assert chan_to_freq(149, "5 GHz") == 5745 and chan_to_freq(149, "6 GHz") == 6695


@pytest.mark.parametrize(
    "band, ch, bw, cf, center, first, last",
    [
        ("5 GHz", 149, 80, None, 5775, 149, 161),
        ("5 GHz", 36, 160, None, 5250, 36, 64),
        ("6 GHz", 37, 80, None, 6145, 33, 45),
        ("6 GHz", 37, 320, None, 6105, 1, 61),  # 320-1 by default
        ("6 GHz", 37, 320, 6265, 6265, 33, 93),  # 320-2 selected by CCFS1
        ("6 GHz", 197, 320, None, 6905, 161, 221),
        ("2.4 GHz", 6, 40, 2447, 2447, 6, 10),
    ],
)
def test_bonded_block(band, ch, bw, cf, center, first, last):
    c, chans = bonded_block(band, ch, bw, cf)
    assert (c, chans[0], chans[-1]) == (center, first, last)


def test_nm_signal_mapping_roundtrip():
    # NetworkManager nm_wifi_utils_level_to_quality(): -100..-40 dBm → 0..100 %
    assert signal_to_dbm(100) == -40 and signal_to_dbm(0) == -100
    assert dbm_to_nm_quality(-40) == 100 and dbm_to_nm_quality(-100) == 0
    for q in (10, 37, 50, 85):
        assert abs(dbm_to_nm_quality(signal_to_dbm(q)) - q) <= 1


def test_phy_rates():
    assert round(phy_rate_mbps("HE", 80, 1, 11), 1) == 600.5
    assert round(phy_rate_mbps("EHT", 320, 1, 13), 1) == 2882.4
    assert round(phy_rate_mbps("VHT", 80, 1, 9), 1) == 433.3
    assert round(sc._ht_rate_mbps(40, 15, True)) == 300  # HT40 2SS SGI MCS15


# ── security labels (nmcli token fallback) ──────────────────────────────────


@pytest.mark.parametrize(
    "kw, label",
    [
        (dict(security="WPA2", rsn_flags="pair_ccmp group_ccmp psk"), "WPA2 (PSK)"),
        (dict(security="WPA2 WPA3", rsn_flags="pair_ccmp group_ccmp psk sae"), "WPA2/WPA3 (PSK/SAE)"),
        (dict(security="WPA1 WPA2", wpa_flags="pair_tkip group_tkip psk", rsn_flags="pair_ccmp psk"), "WPA/WPA2 (PSK)"),
        (dict(security="OWE-TM"), "Open (OWE transition)"),
        (dict(akm_suites=("802.1X/SHA-256",), pmf="Required", has_rsn_ie=True, security="WPA2 802.1X"), "WPA3 (802.1X)"),
    ],
)
def test_security_labels(kw, label):
    assert _ap(**kw).security_short == label


# ── same-radio rule / grouping / collisions ─────────────────────────────────


def test_laa_derivation_rule():
    assert laa_derived_pair("84:78:48:EA:44:D7", "8A:78:48:EA:44:D7")
    assert laa_derived_pair("54:B7:BD:F9:AB:9D", "6A:B7:BD:F9:AB:99")
    # neighbouring APs of one vendor (universally administered) never match
    assert not laa_derived_pair("74:11:B2:C7:22:40", "74:11:B2:C7:22:50")


def test_neighbouring_same_vendor_aps_are_not_one_radio():
    a = _ap(bssid="74:11:B2:C7:22:40", bandwidth_mhz=80)
    b = _ap(bssid="74:11:B2:C7:22:50", bandwidth_mhz=80)
    assert not bssids_related(a, b)


def test_bss_color_collisions_skip_same_radio():
    mk = lambda b, ch, col: _ap(bssid=b, channel=ch, freq_mhz=5000 + 5 * ch, bandwidth_mhz=80, bss_color=col, dbm_exact=-60.0)  # noqa: E731
    aps = [
        mk("74:11:B2:C7:22:40", 36, 12),
        mk("74:11:B2:C7:22:50", 36, 12),  # different AP, same color → collision
        mk("74:11:B2:C7:22:41", 36, 12),  # 2nd SSID of the first AP → not with it
        mk("84:78:48:EA:44:D7", 149, 7),
        mk("8A:78:48:EA:44:D7", 149, 7),  # LAA sibling → not a collision
    ]
    res = find_bss_color_collisions(aps)
    assert set(res) == {"74:11:b2:c7:22:40", "74:11:b2:c7:22:50", "74:11:b2:c7:22:41"}
    assert "74:11:B2:C7:22:41" not in [o.bssid for o in res["74:11:b2:c7:22:40"]]


# ── time-based iw cache (GUI-side logic, tested without a window) ───────────


def test_iw_cache_keeps_data_while_nmcli_lists_bss():
    # kernel drops a BSS after 30 s, wpa_supplicant/nmcli keeps it 180 s
    from wavescope_app.main_window_logic import MainWindowLogicMixin as MW

    mw = types.SimpleNamespace(
        _iw_cache={}, _iw_seen_at={}, IW_CACHE_MAX_AGE_S=MW.IW_CACHE_MAX_AGE_S, _IW_PERSIST_FIELDS=MW._IW_PERSIST_FIELDS
    )
    seen = _ap(bssid="8A:78:48:EA:44:D7", freq_mhz=6135, channel=37, iw_seen=True, wifi_gen="WiFi 7")
    MW._restore_iw_fields(mw, [seen], 0.0)
    later = _ap(bssid="8A:78:48:EA:44:D7", freq_mhz=6135, channel=37, wifi_gen="WiFi 6E", gen_inferred=True)
    MW._restore_iw_fields(mw, [later], 120.0)
    assert later.wifi_gen == "WiFi 7" and later.iw_restored and not later.gen_inferred
    expired = _ap(bssid="8A:78:48:EA:44:D7", freq_mhz=6135, channel=37, wifi_gen="WiFi 6E", gen_inferred=True)
    MW._restore_iw_fields(mw, [expired], 200.0)
    assert expired.wifi_gen == "WiFi 6E" and not expired.iw_restored


# ── iw data source ──────────────────────────────────────────────────────────


def test_iw_only_source_builds_access_points(monkeypatch):
    blk = (
        f"BSS 84:78:48:ea:44:d7(on wlan0) -- associated\n{T}TSF: 1 usec\n{T}freq: 6135.0\n"
        f"{T}capability: ESS Privacy (0x0011)\n{T}signal: -57.00 dBm\n"
        f"{T}SSID: Ohana\n{T}RSN:{T} * Version: 1\n{T}{T} * Group cipher: CCMP\n"
        f"{T}{T} * Pairwise ciphers: CCMP\n{T}{T} * Authentication suites: SAE\n"
        f"{T}{T} * Capabilities: 1-PTKSA-RC 1-GTKSA-RC MFP-required MFP-capable (0x00c0)\n"
    )
    data = parse_iw_scan(blk)
    monkeypatch.setattr(sc, "_detect_wifi_ifaces", lambda: ["wlan0"])
    monkeypatch.setattr(sc, "_iw_scan_iface", lambda i, e: copy.deepcopy(data))
    monkeypatch.setattr(sc, "_get_connected_link_metrics", lambda *a, **k: {})
    (ap,) = sc.scan_from_iw()
    assert (ap.ssid, ap.bssid, ap.in_use, ap.channel, ap.security_short) == (
        "Ohana", "84:78:48:EA:44:D7", True, 37, "WPA3 (SAE)",
    )
    assert ap.rsn_flags == "pair_ccmp group_ccmp sae" and ap.signal == dbm_to_nm_quality(-57)


# ── 2.1.1 spec-review fixes (verified against iw scan.c / hostap / Wireshark) ──


def test_membership_selectors_are_not_rates():
    # iw prints selectors 121-125 as pseudo-rates "60.5*" … "62.5*"
    rates, basic = sc._parse_rates(["6.0* 9.0 12.0* 18.0 24.0* 36.0 48.0 54.0 ", "61.5* "])
    assert max(rates) == 54.0 and basic == [6.0, 12.0, 24.0]


def test_ht_mcs_index_with_mcs32():
    # "0-15, 32": MCS 32 is the 40 MHz duplicate mode, not a higher rate
    blk = (
        f"BSS 00:11:22:33:44:55(on wlan0)\n{T}freq: 2437.0\n{T}HT capabilities:\n"
        f"{T}{T}Capabilities: 0x1ad\n{T}{T}{T}RX HT20 SGI\n{T}{T}{T}RX HT40 SGI\n"
        f"{T}{T}HT RX MCS rate indexes supported: 0-15, 32\n"
    )
    d = parse_iw_scan(blk)["00:11:22:33:44:55"]
    assert (d["ht_max_mcs_index"], d["ht_sgi"]) == (15, True)
    assert round(sc._ht_rate_mbps(20, 15, True), 1) == 144.4


def test_country_summary_6ghz_and_contiguity():
    text = (
        f" GB{T}Environment: bogus\n"
        f"{T}{T}Extension ID: 201 Regulatory Class: 131 Coverage class: 0 (up to 0m)\n"
        f"{T}{T}Channels [1 - 24] @ 0 dBm\n"  # iw's step-1 end channel for 24 6 GHz channels
    )
    cc, env, pwr = sc._summarise_country(text, "6 GHz")
    assert (cc, env, pwr) == ("GB", "Global (Table E-4 operating classes)", "ch 1–93: 0 dBm")
    text5 = (
        f" US{T}Environment: Indoor/Outdoor\n"
        f"{T}{T}Channels [36 - 64] @ 30 dBm\n{T}{T}Channels [149 - 165] @ 30 dBm\n"
        f"{T}{T}Channels [100 - 144] @ 24 dBm\n"
    )
    assert sc._summarise_country(text5, "5 GHz")[2] == "ch 36–64: 30 dBm; ch 149–165: 30 dBm; ch 100–144: 24 dBm"
    text24 = f" DE{T}Environment: Indoor/Outdoor\n{T}{T}Channels [1 - 11] @ 20 dBm\n{T}{T}Channels [12 - 13] @ 20 dBm\n"
    assert sc._summarise_country(text24, "2.4 GHz")[2] == "ch 1–13: 20 dBm"


def test_group_mgmt_cipher_and_tpc_sign():
    blk = (
        f"BSS 00:11:22:33:44:55(on wlan0)\n{T}freq: 5180.0\n{T}TPC report: TX power: 250 dBm\n"
        f"{T}RSN:{T} * Version: 1\n{T}{T} * Group cipher: GCMP-256\n{T}{T} * Pairwise ciphers: GCMP-256\n"
        f"{T}{T} * Authentication suites: IEEE 802.1X/SUITE-B-192\n"
        f"{T}{T} * Capabilities: 1-PTKSA-RC 1-GTKSA-RC MFP-required MFP-capable (0x00c0)\n"
        f"{T}{T} * Group mgmt cipher suite: BIP-GMAC-256\n"
    )
    d = parse_iw_scan(blk)["00:11:22:33:44:55"]
    assert d["group_mgmt_cipher"] == "BIP-GMAC-256"
    assert d["tpc_tx_power_dbm"] == -6  # 250 as a signed octet
    blk_junk = f"BSS 00:11:22:33:44:66(on wlan0)\n{T}freq: 5180.0\n{T}TPC report: TX power: 63 dBm\n"
    assert "tpc_tx_power_dbm" not in parse_iw_scan(blk_junk)["00:11:22:33:44:66"]


def test_suite_b_128_is_not_192bit():
    assert _ap(akm_suites=("802.1X/SUITE-B",), has_rsn_ie=True, pmf="Required").security_short == "WPA2 (802.1X)"
    assert _ap(akm_suites=("802.1X/SUITE-B-192",), has_rsn_ie=True, pmf="Required").security_short == "WPA3 (802.1X-192)"
    assert sc._akm_label(("802.1X/SUITE-B",)) == "Enterprise (802.1X)"


def test_nmcli_fallback_owe_transition_open_side():
    # nmcli: RSN-FLAGS "owe" is emitted for both OWE and OWE-TM; SECURITY differs
    assert _ap(security="OWE-TM", rsn_flags="pair_ccmp group_ccmp owe").security_short == "Open (OWE transition)"
    assert _ap(security="OWE", rsn_flags="pair_ccmp group_ccmp owe").security_short == "OWE"
