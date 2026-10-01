"""Wireshark-backed oracle for WaveScope's 802.11 IE parsing.

WaveScope decodes beacon/probe-response information elements from
`iw scan dump` text.  This module checks that decoding against Wireshark,
the de-facto reference decoder, using *the same frames*:

  1. Raw IE bytes are read from the kernel scan cache over nl80211
     (NL80211_CMD_GET_SCAN — unprivileged; via pyroute2).
  2. Each BSS's IEs are wrapped in a synthetic 802.11 beacon and written to
     a pcap (linktype 105, IEEE 802.11 without radiotap).
  3. tshark decodes the pcap; the fields below are taken from Wireshark's
     dissector (epan/dissectors/packet-ieee80211.c) field abbreviations.
  4. Derived values (operating width, block center, PMF …) are computed
     from Wireshark's raw fields with a small, independent implementation
     of the standard's rules, then compared with WaveScope's parse.

Only the comparison helpers (normalize_wavescope, compare) are needed by the
offline regression tests; the live parts need pyroute2 and tshark.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

# ── AKM suite numbers (IEEE 802.11-2020 Table 9-151) ↔ iw names (iw scan.c print_auth)
AKM_IW_NAME = {
    1: "802.1X",
    2: "PSK",
    3: "FT/802.1X",
    4: "FT/PSK",
    5: "802.1X/SHA-256",
    6: "PSK/SHA-256",
    7: "TDLS/TPK",
    8: "SAE",
    9: "FT/SAE",
    11: "802.1X/SUITE-B",
    12: "802.1X/SUITE-B-192",
    13: "FT/802.1X/SHA-384",
    14: "FILS/SHA-256",
    15: "FILS/SHA-384",
    16: "FT/FILS/SHA-256",
    17: "FT/FILS/SHA-384",
    18: "OWE",
    19: "FT/PSK/SHA-384",
    20: "PSK/SHA-384",
    24: "SAE-EXT-KEY",
    25: "FT/SAE-EXT-KEY",
}

# tshark fields (abbreviations verified in packet-ieee80211.c)
FIELDS = [
    "frame.number",
    "wlan.bssid",
    "wlan.ssid",
    "wlan.ds.current_channel",
    "wlan.ht.info.primarychannel",
    "wlan.ht.info.secchanoffset",
    "wlan.ht.info.chanwidth",
    "wlan.vht.op.channelwidth",
    "wlan.vht.op.channelcenter0",
    "wlan.vht.op.channelcenter1",
    "wlan.ext_tag.he_operation.6ghz.primary_channel",
    "wlan.ext_tag.he_operation.6ghz.control.channel_width",
    "wlan.ext_tag.he_operation.6ghz.control.regulatory_info",
    "wlan.ext_tag.he_operation.6ghz.chan_center_freq_seg_0",
    "wlan.ext_tag.he_operation.6ghz.chan_center_freq_seg_1",
    "wlan.eht.eht_operation_information.control.channel_width",
    "wlan.eht.eht_operation_information.ccfs0",
    "wlan.eht.eht_operation_information.ccfs1",
    "wlan.eht.eht_operation_information.disabled_subchannel_bitmap",
    "wlan.ext_tag.bss_color_information.bss_color",
    "wlan.ext_tag.bss_color_information.bss_color_disabled",
    "wlan.rsn.capabilities.mfpr",
    "wlan.rsn.capabilities.mfpc",
    "wlan.rsn.akms.type",
    "wlan.qbss.scount",
    "wlan.qbss.cu",
    "wlan.country_info.code",
    "wlan.tim.dtim_period",
    "wlan.mobility_domain.mdid",
    "wlan.eht.multi_link.common_info.ap_mld_mac_address",
]

# Fields compared, in report order.
COMPARED = [
    "ssid",
    "primary_channel",
    "oper_bw",
    "center_mhz",
    "pmf",
    "akms",
    "bss_color",
    "bss_color_disabled",
    "station_count",
    "chan_util",
    "country",
    "dtim",
    "mdid",
    "mld_mac",
    "ap_power_type",
    "punct_bitmap",
]


# ─────────────────────────────────────────────────────────────────────────────
# Independent implementation of the channelization rules (oracle side)
# ─────────────────────────────────────────────────────────────────────────────


def _idx_to_mhz(idx: int, band: str) -> int:
    if band == "2.4":
        return 2484 if idx == 14 else 2407 + 5 * idx
    if band == "5":
        return 5000 + 5 * idx
    if band == "6":
        return 5935 if idx == 2 else 5950 + 5 * idx
    return 0


def _band(freq: int) -> str:
    if 2400 <= freq < 2500:
        return "2.4"
    if 5000 <= freq < 5900:
        return "5"
    if 5925 <= freq <= 7125:
        return "6"
    return "?"


def derive_operation(f: Dict[str, str], freq: int) -> Tuple[Optional[int], Optional[int]]:
    """(operating width MHz, block center MHz) from Wireshark's raw fields.

    Rules (written from the standard, not copied from WaveScope):
      EHT Operation (802.11be 9.4.2.322): width code 0-4 = 20/40/80/160/320;
        for 160/320 CCFS1 is the channel center, else CCFS0.
      HE 6 GHz Operation Info (802.11ax 9.4.2.249): width 0-2 = 20/40/80;
        3 = 160 (|CCFS1−CCFS0| = 8 → center CCFS1) or 80+80.
      VHT Operation (802.11-2016 Table 9-252), 5 GHz only: width 1 with
        CCFS1 = 0 → 80 @ CCFS0; |CCFS1−CCFS0| = 8 → 160 @ CCFS1;
        > 16 → 80+80; width 2 → 160 @ CCFS0 (deprecated); 0 → use HT.
      HT Operation: secondary offset 1/3 (above/below) and STA channel
        width 1 (any) → 40 MHz at primary ± 10 MHz, else 20.
    80+80 has no single center → (160, None).
    """
    band = _band(freq)

    def num(key: str) -> Optional[int]:
        v = f.get(key, "")
        v = v.split(",")[0].strip()
        if not v:
            return None
        try:
            return int(v, 0)
        except ValueError:
            return 1 if v.lower() in ("true", "1") else 0 if v.lower() in ("false", "0") else None

    eht_w = num("wlan.eht.eht_operation_information.control.channel_width")
    if eht_w is not None and 0 <= eht_w <= 4:
        bw = (20, 40, 80, 160, 320)[eht_w]
        c0 = num("wlan.eht.eht_operation_information.ccfs0")
        c1 = num("wlan.eht.eht_operation_information.ccfs1")
        idx = c1 if bw >= 160 and c1 else c0
        return bw, (_idx_to_mhz(idx, band) if idx else None)

    he_w = num("wlan.ext_tag.he_operation.6ghz.control.channel_width")
    if he_w is not None and band == "6":
        prim = num("wlan.ext_tag.he_operation.6ghz.primary_channel")
        c0 = num("wlan.ext_tag.he_operation.6ghz.chan_center_freq_seg_0")
        c1 = num("wlan.ext_tag.he_operation.6ghz.chan_center_freq_seg_1")
        if he_w == 0:
            return 20, _idx_to_mhz(prim, band) if prim else None
        if he_w in (1, 2):
            return (40, 80)[he_w - 1], _idx_to_mhz(c0, band) if c0 else None
        if c0 and c1 and abs(c1 - c0) == 8:
            return 160, _idx_to_mhz(c1, band)
        if c1:
            return 160, None  # 80+80
        return 160, _idx_to_mhz(c0, band) if c0 else None

    vht_w = num("wlan.vht.op.channelwidth")
    if vht_w is not None and band == "5":
        c0 = num("wlan.vht.op.channelcenter0")
        c1 = num("wlan.vht.op.channelcenter1")
        if vht_w == 1:
            if c0 and c1 and abs(c1 - c0) == 8:
                return 160, _idx_to_mhz(c1, band)
            if c0 and c1 and abs(c1 - c0) > 16:
                return 160, None
            return 80, _idx_to_mhz(c0, band) if c0 else None
        if vht_w == 2:
            return 160, _idx_to_mhz(c0, band) if c0 else None
        if vht_w == 3:
            return 160, None
        # vht_w == 0: fall through to HT

    off = num("wlan.ht.info.secchanoffset")
    sta_w = num("wlan.ht.info.chanwidth")
    if off is not None:
        if off in (1, 3) and sta_w == 1:
            return 40, freq + (10 if off == 1 else -10)
        return 20, None
    return None, None


def _pmf(mfpr: str, mfpc: str) -> Optional[str]:
    def truthy(v: str) -> Optional[bool]:
        v = (v or "").split(",")[0].strip().lower()
        if v in ("1", "true"):
            return True
        if v in ("0", "false"):
            return False
        return None

    r, c = truthy(mfpr), truthy(mfpc)
    if r is None and c is None:
        return None
    if r:
        return "Required"
    if c:
        return "Optional"
    return "No"


_AP_TYPES = {
    0: "Indoor (LPI)",
    1: "Standard Power (SP)",
    2: "Very Low Power (VLP)",
    3: "Indoor Enabled",
    4: "Indoor Standard Power",
}


def normalize_tshark(rows: List[Dict[str, str]], freq: int) -> Dict[str, object]:
    """Merge one BSS's decoded frames (probe-response set first, then beacon
    set — WaveScope's precedence) into comparable values."""
    f: Dict[str, str] = {}
    for row in rows:
        for k, v in row.items():
            if v and not f.get(k):
                f[k] = v

    def first(key: str) -> str:
        return (f.get(key, "") or "").split(",")[0].strip()

    def as_int(key: str) -> Optional[int]:
        v = first(key)
        try:
            return int(v, 0) if v else None
        except ValueError:
            return None

    out: Dict[str, object] = {}
    bw, center = derive_operation(f, freq)
    out["oper_bw"] = bw
    out["center_mhz"] = center
    prim = as_int("wlan.ext_tag.he_operation.6ghz.primary_channel") if _band(freq) == "6" else None
    out["primary_channel"] = prim or as_int("wlan.ds.current_channel") or as_int("wlan.ht.info.primarychannel")
    out["pmf"] = _pmf(f.get("wlan.rsn.capabilities.mfpr", ""), f.get("wlan.rsn.capabilities.mfpc", ""))
    akms = [int(x, 0) for x in (f.get("wlan.rsn.akms.type", "") or "").split(",") if x.strip()]
    out["akms"] = sorted({AKM_IW_NAME.get(a, f"akm{a}") for a in akms}) or None
    out["bss_color"] = as_int("wlan.ext_tag.bss_color_information.bss_color")
    dis = first("wlan.ext_tag.bss_color_information.bss_color_disabled").lower()
    out["bss_color_disabled"] = None if not dis else dis in ("1", "true")
    out["station_count"] = as_int("wlan.qbss.scount")
    out["chan_util"] = as_int("wlan.qbss.cu")
    cc = first("wlan.country_info.code")
    out["country"] = cc[:2] if cc else None
    out["dtim"] = as_int("wlan.tim.dtim_period")
    md = as_int("wlan.mobility_domain.mdid")
    # Wireshark shows the MDID as a little-endian uint16; WaveScope shows
    # the two octets in transmission order (hostapd's mobility_domain= form).
    out["mdid"] = struct.pack("<H", md).hex() if md is not None else None
    mld = first("wlan.eht.multi_link.common_info.ap_mld_mac_address")
    out["mld_mac"] = mld.lower() or None
    reg = as_int("wlan.ext_tag.he_operation.6ghz.control.regulatory_info")
    out["ap_power_type"] = _AP_TYPES.get(reg, f"Unknown ({reg})") if reg is not None and _band(freq) == "6" else None
    pb = as_int("wlan.eht.eht_operation_information.disabled_subchannel_bitmap")
    out["punct_bitmap"] = pb if pb else None
    out["ssid"] = _tshark_ssid(f.get("wlan.ssid", ""))
    return out


def _tshark_ssid(value: str) -> str:
    """wlan.ssid is an FT_BYTES field: tshark prints hex, and "<MISSING>"
    for a zero-length (hidden) SSID.  Several values = several SSID
    elements (e.g. Multiple-BSSID profiles); the first is the BSS's own."""
    first = (value or "").split(",")[0].strip()
    if not first or first == "<MISSING>":
        return ""
    try:
        raw = bytes.fromhex(first.replace(":", ""))
    except ValueError:
        return first
    if not raw.strip(b"\x00"):
        return ""
    return raw.decode("utf-8", errors="replace")


def normalize_wavescope(d: dict) -> Dict[str, object]:
    """The same values from one parse_iw_scan() entry."""
    freq = int(d.get("freq_mhz", 0) or 0)
    band = _band(freq)
    if band == "6":
        prim = 2 if freq == 5935 else (freq - 5950) // 5
    elif band == "5":
        prim = (freq - 5000) // 5
    elif band == "2.4":
        prim = 14 if freq == 2484 else (freq - 2407) // 5
    else:
        prim = None
    mld = d.get("mld_mac") or None
    return {
        "ssid": d.get("ssid"),
        "primary_channel": prim,
        "oper_bw": d.get("iw_oper_bw"),
        "center_mhz": d.get("iw_center_freq"),
        "pmf": d.get("pmf") if d.get("has_rsn_ie") else None,
        "akms": sorted(set(d.get("rsn_akm_suites", ()))) or None,
        "bss_color": d.get("bss_color"),
        "bss_color_disabled": d.get("bss_color_disabled") if d.get("bss_color") is not None else None,
        "station_count": d.get("station_count"),
        "chan_util": d.get("chan_util"),
        "country": d.get("country") or None,
        "dtim": d.get("dtim_period"),
        "mdid": d.get("mobility_domain") or None,
        "mld_mac": mld,
        "ap_power_type": d.get("he_6ghz_ap_type") or None,
        "punct_bitmap": d.get("punct_bitmap") or None,
    }


def compare(ours: Dict[str, object], oracle: Dict[str, object]) -> List[Tuple[str, object, object]]:
    """[(field, ours, wireshark)] for every field where they disagree.

    A field is skipped when *both* sides have no value.  The HT-derived
    center for a 20 MHz BSS is not reported by WaveScope (it draws 20 MHz
    at the primary), so a missing center at 20 MHz is not a mismatch.
    """
    out = []
    for k in COMPARED:
        a, b = ours.get(k), oracle.get(k)
        if a in (None, "", [], ()) and b in (None, "", [], ()):
            continue
        if k == "center_mhz" and ours.get("oper_bw") == 20 and a is None:
            continue
        # WaveScope's channel comes from the kernel's frequency; only compare
        # it when the frame itself carries a channel (DS / HT / HE 6 GHz IE).
        if k == "primary_channel" and b is None:
            continue
        if a != b:
            out.append((k, a, b))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Live capture side (pyroute2 + tshark)
# ─────────────────────────────────────────────────────────────────────────────


def dump_raw_scan(iface: str) -> List[Dict[str, object]]:
    """Kernel scan cache with raw IE bytes (NL80211_CMD_GET_SCAN, unprivileged)."""
    from pyroute2.netlink import NLM_F_DUMP, NLM_F_REQUEST
    from pyroute2.netlink.nl80211 import NL80211, NL80211_NAMES, nl80211cmd

    # pyroute2 decodes IEs into its own dict; we need the untouched bytes.
    bss_cls = nl80211cmd.bss
    raw_map = []
    for e in bss_cls.nla_map:
        name = e[1] if isinstance(e[0], int) else e[0]
        if name in ("NL80211_BSS_INFORMATION_ELEMENTS", "NL80211_BSS_BEACON_IES"):
            e = (e[0], e[1], "cdata") if isinstance(e[0], int) else (e[0], "cdata")
        raw_map.append(e)
    bss_cls.nla_map = tuple(raw_map)

    sock = NL80211()
    sock.bind()
    try:
        msg = nl80211cmd()
        msg["cmd"] = NL80211_NAMES["NL80211_CMD_GET_SCAN"]
        msg["attrs"] = [["NL80211_ATTR_IFINDEX", socket.if_nametoindex(iface)]]
        replies = sock.nlm_request(msg, msg_type=sock.prid, msg_flags=NLM_F_REQUEST | NLM_F_DUMP)
        def val(x, default=0):
            # pyroute2 wraps some attributes as {"VALUE": n, ...}
            if isinstance(x, dict):
                x = x.get("VALUE", default)
            return int(x) if x is not None else default

        out = []
        for r in replies:
            b = r.get_attr("NL80211_ATTR_BSS")
            if b is None:
                continue
            out.append(
                {
                    "bssid": str(b.get_attr("NL80211_BSS_BSSID")).lower(),
                    "freq": val(b.get_attr("NL80211_BSS_FREQUENCY")),
                    "tsf": val(b.get_attr("NL80211_BSS_TSF")),  # what iw prints as "TSF:"
                    "ies": bytes(b.get_attr("NL80211_BSS_INFORMATION_ELEMENTS") or b""),
                    "beacon_ies": bytes(b.get_attr("NL80211_BSS_BEACON_IES") or b""),
                    "beacon_interval": val(b.get_attr("NL80211_BSS_BEACON_INTERVAL"), 100),
                    "capability": val(b.get_attr("NL80211_BSS_CAPABILITY")),
                }
            )
        return out
    finally:
        sock.close()


def _beacon_frame(bssid: str, interval: int, capability: int, ies: bytes) -> bytes:
    mac = bytes.fromhex(bssid.replace(":", ""))
    hdr = struct.pack("<HH", 0x0080, 0) + b"\xff" * 6 + mac + mac + struct.pack("<H", 0)
    fixed = struct.pack("<QHH", 0, interval, capability)
    return hdr + fixed + ies


def write_pcap(path: str, entries: List[Dict[str, object]]) -> List[Tuple[str, str]]:
    """One frame per IE set; returns [(bssid, "presp"|"beacon")] per frame."""
    index: List[Tuple[str, str]] = []
    with open(path, "wb") as fh:
        fh.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 105))
        for e in entries:
            sets = [("presp", e["ies"])]
            if e["beacon_ies"] and e["beacon_ies"] != e["ies"]:
                sets.append(("beacon", e["beacon_ies"]))
            for kind, ies in sets:
                if not ies:
                    continue
                frame = _beacon_frame(e["bssid"], e["beacon_interval"], e["capability"], ies)
                fh.write(struct.pack("<IIII", 0, 0, len(frame), len(frame)) + frame)
                index.append((e["bssid"], kind))
    return index


def run_tshark(pcap: str) -> List[Dict[str, str]]:
    cmd = ["tshark", "-r", pcap, "-T", "fields", "-E", "separator=\t", "-E", "occurrence=a", "-E", "aggregator=,"]
    for f in FIELDS:
        cmd += ["-e", f]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True, env={**os.environ, "LC_ALL": "C"}).stdout
    rows = []
    for line in out.splitlines():
        vals = line.split("\t")
        rows.append({k: (vals[i] if i < len(vals) else "") for i, k in enumerate(FIELDS)})
    return rows


def oracle_for_iface(iface: str) -> Dict[str, Dict[str, object]]:
    """{bssid: {"tsf", "freq", "values"}} decoded by Wireshark from the kernel's raw IEs."""
    entries = dump_raw_scan(iface)
    with tempfile.TemporaryDirectory() as td:
        pcap = os.path.join(td, "scan.pcap")
        index = write_pcap(pcap, entries)
        rows = run_tshark(pcap)
    by_bssid: Dict[str, List[Dict[str, str]]] = {}
    for (bssid, _kind), row in zip(index, rows):
        by_bssid.setdefault(bssid, []).append(row)
    meta = {e["bssid"]: e for e in entries}
    return {
        b: {"tsf": meta[b]["tsf"], "freq": meta[b]["freq"], "values": normalize_tshark(rs, meta[b]["freq"])}
        for b, rs in by_bssid.items()
    }


def save_json(path: str, data: object) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True, ensure_ascii=False)
