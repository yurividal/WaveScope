"""Scanner and parser subsystem.

Contains nmcli/iw parsers, enrichment logic, and scanner worker thread.

Output formats parsed here were checked against the upstream sources:
  * iw:  scan.c / util.c / station.c / link.c (git.kernel.org jberg/iw)
  * nmcli: src/nmcli/devices.c (NetworkManager)
"""

import copy
import threading

from .core_models import *
from .vendor_beacon import parse_vendor_ies


# ─────────────────────────────────────────────────────────────────────────────
# Subprocess helpers
# ─────────────────────────────────────────────────────────────────────────────


def _tool_env() -> Dict[str, str]:
    """Environment for nmcli / iw calls.

    nmcli localizes its output (`man nmcli`: use LC_ALL=C when parsing), e.g.
    "(none)" becomes a translated string.  Forcing LC_ALL=C would however also
    switch the character set to ASCII, and glib then mangles non-ASCII SSIDs.
    So only the *message* and *numeric* categories are forced to C, and the
    character type is pinned to UTF-8 when the session does not set one.
    """
    env = dict(os.environ)
    env.pop("LC_ALL", None)  # would override the per-category settings below
    env.pop("LANGUAGE", None)  # GNU gettext consults this before LC_MESSAGES
    env["LC_MESSAGES"] = "C"
    env["LC_NUMERIC"] = "C"
    if not env.get("LC_CTYPE") and not env.get("LANG"):
        env["LC_CTYPE"] = "C.UTF-8"
    return env


_TOOL_ENV = _tool_env()


class ScanCancelled(Exception):
    """Raised inside the scanner thread when a stop was requested mid-command."""


def run_tool(
    cmd: List[str],
    timeout: float,
    stop_event: Optional[threading.Event] = None,
) -> subprocess.CompletedProcess:
    """Run an external tool with the parsing-safe environment.

    When *stop_event* is given the call becomes interruptible: the child is
    polled every 200 ms and killed as soon as the event is set, so stopping
    the scanner never has to wait out a 30 s `nmcli --rescan yes`.
    """
    if stop_event is None:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_TOOL_ENV,
        )
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_TOOL_ENV,
    )
    deadline = time.monotonic() + timeout
    while True:
        try:
            out, err = proc.communicate(timeout=0.2)
            return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
        except subprocess.TimeoutExpired:
            if stop_event.is_set():
                proc.kill()
                proc.communicate()
                raise ScanCancelled()
            if time.monotonic() >= deadline:
                proc.kill()
                proc.communicate()
                raise


# ─────────────────────────────────────────────────────────────────────────────
# nmcli parsing
# ─────────────────────────────────────────────────────────────────────────────


def _split_terse(line: str) -> List[str]:
    """Split a nmcli terse (-t) line on unescaped ':' characters.

    In terse mode nmcli escapes ':' as '\\:' and '\\' as '\\\\' inside
    values, so an SSID ending in a backslash arrives as '...\\\\:' and must
    not be read as an escaped separator.
    """
    fields: List[str] = []
    cur: List[str] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line) and line[i + 1] in (":", "\\"):
            cur.append(line[i + 1])
            i += 2
        elif ch == ":":
            fields.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(ch)
            i += 1
    fields.append("".join(cur))
    return fields


def _parse_freq(freq_str: str) -> int:
    m = re.search(r"(\d+)", freq_str)
    return int(m.group(1)) if m else 0


def _parse_rate(rate_str: str) -> float:
    m = re.search(r"([\d.]+)", rate_str)
    return float(m.group(1)) if m else 0.0


def _parse_bw(bw_str: str) -> int:
    m = re.search(r"(\d+)", bw_str)
    return int(m.group(1)) if m else 20


def parse_nmcli(output: str) -> List[AccessPoint]:
    """Parse `nmcli -t -f NMCLI_FIELDS dev wifi list` output.

    nmcli lists every BSS once per Wi-Fi device, so with two adapters the
    same BSSID appears twice.  Duplicates are merged: the in-use entry wins,
    otherwise the strongest one.
    """
    by_bssid: Dict[str, AccessPoint] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = _split_terse(line)
        if len(parts) < 12:
            continue
        try:
            in_use = parts[0].strip() == "*"
            ssid = parts[1]
            bssid = parts[2].strip()
            mode = parts[3].strip()
            chan = int(parts[4]) if parts[4].strip().isdigit() else 0
            freq = _parse_freq(parts[5])
            rate = _parse_rate(parts[6])
            signal = int(parts[7]) if parts[7].strip().isdigit() else 0
            security = parts[8].strip()
            wpa = parts[9].strip()
            rsn = parts[10].strip()
            bw = _parse_bw(parts[11])
            device = parts[12].strip() if len(parts) > 12 else ""
            # Fallback: nmcli sometimes returns CHAN=0 for certain channels.
            # When freq is available, derive the channel from it instead.
            if chan == 0 and freq:
                chan = freq_to_chan(freq)
            # Derive freq from channel only as a last resort; without a band
            # the channel number is ambiguous (ch 1 exists in 2.4 and 6 GHz).
            if freq == 0 and chan:
                freq = chan_to_freq(chan)
            ap = AccessPoint(
                ssid=ssid,
                bssid=bssid,
                mode=mode,
                channel=chan,
                freq_mhz=freq,
                rate_mbps=rate,
                signal=signal,
                security=security,
                wpa_flags=wpa,
                rsn_flags=rsn,
                bandwidth_mhz=bw,
                in_use=in_use,
                nm_device=device,
            )
        except Exception:
            continue
        key = bssid.lower()
        prev = by_bssid.get(key)
        if prev is None or (ap.in_use and not prev.in_use) or (
            ap.in_use == prev.in_use and ap.signal > prev.signal
        ):
            by_bssid[key] = ap
    return list(by_bssid.values())


# ─────────────────────────────────────────────────────────────────────────────
# PHY-rate math (theoretical maximum, used when nmcli reports 0 Mbit/s)
# ─────────────────────────────────────────────────────────────────────────────

# MCS index → (coded bits per subcarrier, coding rate).  Identical for
# HT/VHT/HE/EHT up to MCS 11; MCS 12/13 (4096-QAM) are EHT-only.
_MCS_MOD: Dict[int, Tuple[int, float]] = {
    0: (1, 1 / 2),
    1: (2, 1 / 2),
    2: (2, 3 / 4),
    3: (4, 1 / 2),
    4: (4, 3 / 4),
    5: (6, 2 / 3),
    6: (6, 3 / 4),
    7: (6, 5 / 6),
    8: (8, 3 / 4),
    9: (8, 5 / 6),
    10: (10, 3 / 4),
    11: (10, 5 / 6),
    12: (12, 3 / 4),
    13: (12, 5 / 6),
}

# HE/EHT data subcarriers per full-bandwidth RU (802.11ax Table 27-15/27-16,
# 802.11be 36.3.x).  Symbol duration 12.8 µs + 0.8 µs GI = 13.6 µs.
_HE_NSD: Dict[int, int] = {20: 234, 40: 468, 80: 980, 160: 1960, 320: 3920}
_HE_SYMBOL_US = 13.6

# VHT data subcarriers (802.11ac Table 21-5).  3.6 µs symbol with short GI.
_VHT_NSD: Dict[int, int] = {20: 52, 40: 108, 80: 234, 160: 468}
_VHT_SGI_SYMBOL_US = 3.6


def phy_rate_mbps(family: str, bw_mhz: int, nss: int, mcs: int) -> float:
    """Theoretical PHY rate for one MCS/NSS/bandwidth, shortest GI.

    Examples: HE 80 MHz 1SS MCS11 = 600.5 Mbps; EHT 320 MHz 1SS MCS13 =
    2882.4 Mbps; VHT 80 MHz 1SS MCS9 = 433.3 Mbps.
    """
    if mcs not in _MCS_MOD or nss <= 0:
        return 0.0
    bits, rate = _MCS_MOD[mcs]
    if family in ("HE", "EHT"):
        nsd = _HE_NSD.get(bw_mhz, 0)
        return nsd * bits * rate * nss / _HE_SYMBOL_US
    nsd = _VHT_NSD.get(bw_mhz, 0)
    return nsd * bits * rate * nss / _VHT_SGI_SYMBOL_US


def _best_rate_mbps(family: str, bw_mhz: int, mcs_nss: List[Tuple[int, int]]) -> float:
    """Highest rate over (max_mcs, nss) pairs advertised for a PHY family."""
    return max((phy_rate_mbps(family, bw_mhz, nss, mcs) for mcs, nss in mcs_nss), default=0.0)


# ─────────────────────────────────────────────────────────────────────────────
# iw interface discovery
# ─────────────────────────────────────────────────────────────────────────────

_IFACE_CACHE: Tuple[float, List[str]] = (0.0, [])
_IFACE_CACHE_TTL = 30.0  # re-detect periodically (USB adapters come and go)


def _detect_wifi_ifaces() -> List[str]:
    """Return every managed (station) wireless interface from `iw dev`."""
    global _IFACE_CACHE
    ts, cached = _IFACE_CACHE
    if cached and time.monotonic() - ts < _IFACE_CACHE_TTL:
        return cached
    found: List[str] = []
    try:
        out = run_tool([IW_BIN, "dev"], timeout=3).stdout
        iface: Optional[str] = None
        for line in out.splitlines():
            s = line.strip()
            if s.startswith("Interface "):
                iface = s.split()[1]
            elif s.startswith("type ") and iface:
                if s.split()[1] == "managed":
                    found.append(iface)
                iface = None
    except Exception:
        pass
    _IFACE_CACHE = (time.monotonic(), found)
    return found


def _detect_wifi_iface() -> Optional[str]:
    """First managed wireless interface (kept for backwards compatibility)."""
    ifaces = _detect_wifi_ifaces()
    return ifaces[0] if ifaces else None


# ─────────────────────────────────────────────────────────────────────────────
# iw scan parsing
# ─────────────────────────────────────────────────────────────────────────────


def _decode_rsn_capabilities(raw_caps: str) -> str:
    """Decode the RSN Capabilities field (IEEE 802.11-2020 Figure 9-341).

    Bit layout (verified against hostap wpa_common.h and iw scan.c):
      B0 PreAuth · B1 No Pairwise · B2-3 PTKSA RC · B4-5 GTKSA RC ·
      B6 MFPR (PMF required) · B7 MFPC (PMF capable) · B8 Joint Multi-band ·
      B9 PeerKey · B10 SPP A-MSDU capable · B11 SPP A-MSDU required ·
      B12 PBAC · B13 Extended Key ID · B14 OCVC
    """
    text = (raw_caps or "").strip()
    if not text:
        return ""

    hex_m = re.search(r"0x[0-9a-f]+", text, re.IGNORECASE)
    if not hex_m:
        # Fallback when only iw's tokens are available
        fallback: List[str] = []
        if re.search(r"\bMFP-required\b", text, re.IGNORECASE):
            fallback.append("PMF required")
        elif re.search(r"\bMFP-capable\b", text, re.IGNORECASE):
            fallback.append("PMF capable")
        if re.search(r"\bPreAuth\b", text, re.IGNORECASE):
            fallback.append("Pre-authentication")
        if re.search(r"\bNoPairwise\b", text, re.IGNORECASE):
            fallback.append("No pairwise cipher")
        if re.search(r"\bPeerkey", text, re.IGNORECASE):
            fallback.append("PeerKey")
        if re.search(r"\bSPP-AMSDU-capable\b", text, re.IGNORECASE):
            fallback.append("SPP-A-MSDU capable")
        if re.search(r"\bSPP-AMSDU-required\b", text, re.IGNORECASE):
            fallback.append("SPP-A-MSDU required")
        if re.search(r"\bExtended-Key-ID\b", text, re.IGNORECASE):
            fallback.append("Extended Key ID")
        return ", ".join(fallback) if fallback else text

    caps = int(hex_m.group(0), 16) & 0xFFFF
    replay_map = {0: 1, 1: 2, 2: 4, 3: 16}

    decoded: List[str] = []
    if caps & (1 << 0):
        decoded.append("Pre-authentication")
    if caps & (1 << 1):
        decoded.append("No pairwise cipher")

    decoded.append(f"PTKSA replay counters: {replay_map[(caps >> 2) & 0x3]}")
    decoded.append(f"GTKSA replay counters: {replay_map[(caps >> 4) & 0x3]}")

    if caps & (1 << 6):
        decoded.append("PMF required")
    if caps & (1 << 7):
        decoded.append("PMF capable")
    if caps & (1 << 8):
        decoded.append("Joint multi-band RSNA")
    if caps & (1 << 9):
        decoded.append("PeerKey")
    if caps & (1 << 10):
        decoded.append("SPP-A-MSDU capable")
    if caps & (1 << 11):
        decoded.append("SPP-A-MSDU required")
    if caps & (1 << 12):
        decoded.append("PBAC")
    if caps & (1 << 13):
        decoded.append("Extended Key ID")
    if caps & (1 << 14):
        decoded.append("OCV capable")

    # Keep raw value only as a compact suffix for transparency/debugging.
    decoded.append(f"RSN caps 0x{caps:04X}")
    return ", ".join(decoded)


def _pmf_from_rsn_caps(raw_caps: str) -> str:
    """'Required' / 'Optional' / 'No' from the RSN Capabilities field."""
    hex_m = re.search(r"\(0x([0-9a-f]+)\)", raw_caps or "", re.IGNORECASE)
    if hex_m:
        caps = int(hex_m.group(1), 16)
        if caps & (1 << 6):  # MFPR
            return "Required"
        if caps & (1 << 7):  # MFPC
            return "Optional"
        return "No"
    if re.search(r"MFP-required", raw_caps or "", re.IGNORECASE):
        return "Required"
    if re.search(r"MFP-capable", raw_caps or "", re.IGNORECASE):
        return "Optional"
    return "No"


def _akm_suites(raw: str) -> Tuple[str, ...]:
    """Normalise iw's 'Authentication suites:' text into AKM tokens.

    iw prints names such as "IEEE 802.1X", "PSK", "FT/SAE", "SAE-EXT-KEY",
    "IEEE 802.1X/SHA-256", "IEEE 802.1X/SUITE-B-192" or, for unknown
    suites, "00-0f-ac:23".  "IEEE 802.1X" contains a space, so it is folded
    to "802.1X" before splitting.
    """
    text = (raw or "").replace("IEEE 802.1X", "802.1X")
    return tuple(t for t in text.split() if t)


# RSNX (IE 244) capability bits, indexed from bit 0 of the first octet, which
# carries the 4-bit field length (hostap ieee802_11_defs.h WLAN_RSNX_CAPAB_*).
_RSNX_BITS: Dict[int, str] = {
    4: "Protected TWT",
    5: "SAE Hash-to-Element",
    6: "SAE-PK",
    8: "Secure LTF",
    9: "Secure RTT",
    10: "URNM-MFPR-X20",
    14: "SPP A-MSDU",
    15: "URNM-MFPR",
    18: "KEK in PASN",
    21: "SSID protection",
}

# 6 GHz HE Operation "Regulatory Info" (Control field B3-B6, 4 bits —
# IEEE 802.11-2024 Figure 9-908) → AP power type per Table E-13 (the
# extended interpretation, which the 4-bit encoding is defined for).  Legacy
# STAs read only 3 bits (Table E-12, "value or value+8"); value 4 is the
# deprecated 3-bit encoding of "indoor standard power", now value 8.
_6GHZ_AP_TYPES: Dict[int, str] = {
    0: "Indoor (LPI)",
    1: "Standard Power (SP)",
    2: "Very Low Power (VLP)",
    3: "Indoor Enabled",
    4: "Indoor Standard Power (deprecated encoding)",
    7: "AP role not relevant",
    8: "Indoor Standard Power",
}

# 6 GHz operating classes (802.11ax Annex E Table E-4) used by the RNR parser.
_6GHZ_OP_CLASSES = frozenset({131, 132, 133, 134, 135, 136, 137})


def _hex_bytes(text: str) -> bytes:
    try:
        return bytes.fromhex(re.sub(r"[^0-9a-fA-F]", "", text or ""))
    except ValueError:
        return b""


# BSS-level lines iw prints before the IEs (iw scan.c print_bss_handler);
# every other single-tab "<Name>:" line is an information element.
_IW_BSS_META = frozenset({"TSF", "freq", "beacon interval", "capability", "signal", "last seen"})


def _iw_block_sections(lines: List[str]) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """Split one `iw scan dump` BSS block into top-level sections.

    iw prints every IE as a single-tab line "<Name>: <inline text>" followed
    by deeper-indented detail lines.  Returns (meta, ies): *meta* holds the
    BSS-level lines (_IW_BSS_META), *ies* the IE sections.

    The "Information elements from … frame:" header is NOT a reliable
    separator: iw prints it only when probe-response data exists or the
    beacon IEs differ from it, so a BSS heard only via beacons has no header
    at all.  Values are lists because names repeat ("Vendor specific",
    "Unknown IE (221)") and because iw may print a Probe Response set and a
    Beacon set; the probe-response set comes first.
    """
    meta: Dict[str, List[str]] = {}
    ies: Dict[str, List[str]] = {}
    cur_list: Optional[List[str]] = None
    for line in lines[1:]:
        if line.startswith("\t") and not line.startswith("\t\t"):
            body = line[1:]
            if body.startswith("Information elements from"):
                cur_list = None
                continue
            name, sep, rest = body.partition(":")
            if not sep:
                cur_list = None
                continue
            name = name.strip()
            target = meta if name in _IW_BSS_META else ies
            bucket = target.setdefault(name, [])
            bucket.append(rest)
            cur_list = bucket
        elif cur_list is not None:
            cur_list[-1] += "\n" + line
    return meta, ies


def _first(sections: Dict[str, List[str]], name: str) -> str:
    vals = sections.get(name)
    return vals[0] if vals else ""


def _re_int(pattern: str, text: str, flags: int = re.IGNORECASE) -> Optional[int]:
    m = re.search(pattern, text or "", flags)
    return int(m.group(1)) if m else None


# TBTT Information length → offset of the BSS Parameters octet (see _parse_rnr)
_RNR_PARAMS_OFFSET: Dict[int, int] = {2: 1, 6: 5, 8: 7, 9: 7, 12: 11, 13: 11}


def _parse_rnr(raw: bytes) -> List[Dict[str, object]]:
    """Parse a Reduced Neighbor Report element body (IE 201).

    Layout (IEEE 802.11-2020 9.4.2.170, hostap RNR_* definitions):
      Neighbor AP Information field, repeated:
        TBTT Information Header (2 octets):
          B0-1 field type · B2 filtered · B4-7 count-1 · B8-15 info length
        Operating Class (1) · Channel Number (1)
        TBTT Information Set: (count) × (info length) octets.  The field
        layout depends on the length (802.11ax Table 9-281; Wireshark
        packet-ieee80211.c tbtt_info_length):
           1: offset                       2: offset, params
           5: offset, short SSID           6: offset, short SSID, params
           7: offset, BSSID                8: offset, BSSID, params
           9: offset, BSSID, params, PSD  11: offset, BSSID, short SSID
          12: offset, BSSID, short SSID, params
          13: 12 + PSD                    16+: 13 + MLD parameters
        Lengths 0, 3, 4, 10, 14, 15 are reserved and carry no known fields.
    """
    out: List[Dict[str, object]] = []
    pos = 0
    while pos + 4 <= len(raw):
        hdr0, info_len, op_class, channel = raw[pos], raw[pos + 1], raw[pos + 2], raw[pos + 3]
        count = ((hdr0 >> 4) & 0x0F) + 1
        pos += 4
        if info_len == 0:
            return out  # cannot advance
        params_off = _RNR_PARAMS_OFFSET.get(info_len, 11 if info_len >= 16 else None)
        has_bssid = info_len in (7, 8, 9, 11, 12, 13) or info_len >= 16
        for _ in range(count):
            if pos + info_len > len(raw):
                return out
            info = raw[pos:pos + info_len]
            pos += info_len
            if not has_bssid and params_off is None:
                continue  # short-SSID-only or reserved layout: nothing we use
            entry: Dict[str, object] = {"op_class": op_class, "channel": channel}
            if has_bssid:
                entry["bssid"] = ":".join(f"{b:02x}" for b in info[1:7])
            if params_off is not None:
                params = info[params_off]
                entry["same_ssid"] = bool(params & 0x02)  # RNR_BSS_PARAM_SAME_SSID
                entry["colocated"] = bool(params & 0x40)  # RNR_BSS_PARAM_CO_LOCATED
            out.append(entry)
    return out


def _parse_rates(section_texts: List[str]) -> Tuple[List[float], List[float]]:
    """(all rates, basic rates) in Mbps from Supported/Extended rates IEs.

    iw marks basic rates with '*'.  BSS-membership selectors share the rate
    octet space (hostap BSS_MEMBERSHIP_SELECTOR_*: 120 UHR, 121 EHT, 122 HE,
    123 SAE-H2E-only, 124 EPD, 125 GLK, 126 VHT, 127 HT); iw prints 126/127
    as "VHT"/"HT" but the others as pseudo-rates "60.0*" … "62.5*" (iw
    scan.c print_supprates).  Real 802.11 rates never exceed 54 Mbps, so
    anything ≥ 60 is a selector and is skipped.
    """
    rates: List[float] = []
    basic: List[float] = []
    for text in section_texts:
        for tok in text.split():
            m = re.fullmatch(r"(\d+(?:\.\d+)?)(\*?)", tok)
            if not m:
                continue
            r = float(m.group(1))
            if r >= 60.0:
                continue  # BSS membership selector, not a rate
            rates.append(r)
            if m.group(2):
                basic.append(r)
    return rates, basic


# Global operating classes (IEEE 802.11-2024 Annex E Table E-4) → BSS
# bandwidth in MHz.  Inside an Operating/Subband Sequence of the Country
# element, "the channel numbers that are included in a group of channels are
# separated by the BSS bandwidth" of that class (9.4.2.7); outside one, by
# 20 MHz.  Classes 131-137 are the 6 GHz band.
_OP_CLASS_BW: Dict[int, int] = {
    **{c: 20 for c in (115, 118, 121, 124, 125, 131, 136)},
    **{c: 40 for c in (116, 117, 119, 120, 122, 123, 126, 127, 132)},
    **{c: 80 for c in (128, 130, 133, 135)},
    **{c: 160 for c in (129, 134)},
    137: 320,
}
_6GHZ_REG_CLASSES = frozenset(range(131, 138))


def _summarise_country(text: str, bss_band: str = "") -> Tuple[str, str, str]:
    """(country code, environment, power-limit summary) from the Country IE.

    Environment: the Country String's third octet is ' ' (all environments),
    'O' (outdoor), 'I' (indoor), 'X' (noncountry entity) or the Annex E
    operating-class table number in use, e.g. 0x04 for Table E-4 (IEEE
    802.11-2024 Annex C dot11CountryString; E.2.7 gives the 6 GHz US example
    0x55 0x53 0x04).  iw prints the first three as text and anything else as
    "bogus"; with a Regulatory Class line present that is the Table E-4 case.

    Triplets: iw computes the end channel as first + (n-1) when first ≤ 14
    and first + 4·(n-1) otherwise (iw scan.c print_country).  Per 9.4.2.7 the
    channels of a subband group are 5 MHz apart on 2.4 GHz, and otherwise
    separated by the BSS bandwidth: 20 MHz (4 channel numbers) for plain
    subband triplets, or the operating class's bandwidth inside an
    Operating/Subband Sequence.  So a 6 GHz triplet starting at ch 1-13 is
    printed by iw with the wrong end channel ([1 - 24] for 24 channels =
    ch 1-93), and wider classes need a wider step; both are recomputed here
    from the recovered channel count.  Triplets describe only the band the
    frame was sent on, so the BSS band is the default context.

    Adjacent triplets with the same power are merged only when their channel
    ranges are contiguous (step 1 on 2.4 GHz, 4 above), so [36-64]@30 and
    [149-165]@30 stay two ranges rather than "36–165".
    """
    first_line = (text or "").split("\n", 1)[0]
    cc_m = re.search(r"\b([A-Z]{2})\b", first_line)
    env_m = re.search(r"Environment:\s*(.+)", first_line)
    env = env_m.group(1).strip() if env_m else ""
    has_reg_class = "Regulatory Class:" in (text or "")
    if env == "bogus":
        env = "Global (Table E-4 operating classes)" if has_reg_class else "Unknown"

    runs: List[List[int]] = []  # [lo, hi, power, step]
    six_ghz = bss_band == "6 GHz"
    class_bw = 20  # bandwidth of the current Operating/Subband Sequence
    for line in (text or "").splitlines():
        rc = re.search(r"Regulatory Class:\s*(\d+)", line)
        if rc:
            op_class = int(rc.group(1))
            six_ghz = op_class in _6GHZ_REG_CLASSES
            class_bw = _OP_CLASS_BW.get(op_class, 20)
            continue
        m = re.search(r"Channels \[(\d+) - (\d+)\] @ (-?\d+) dBm", line)
        if not m:
            continue
        lo, hi, p = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if bss_band == "2.4 GHz" and not six_ghz:
            step = 1  # 5 MHz spacing on 2.4 GHz regardless of class
        else:
            iw_step = 1 if lo <= 14 else 4  # what iw assumed when printing
            n = (hi - lo) // iw_step + 1  # recover Number of Channels
            step = max(4, class_bw // 5)  # 20 MHz → 4, 40 → 8, 80 → 16, …
            hi = lo + step * (n - 1)
        if runs and runs[-1][2] == p and runs[-1][3] == step and lo == runs[-1][1] + step:
            runs[-1][1] = hi
        else:
            runs.append([lo, hi, p, step])
    parts = [
        (f"ch {lo}" if lo == hi else f"ch {lo}–{hi}") + f": {p} dBm" for lo, hi, p, _ in runs
    ]
    return cc_m.group(1) if cc_m else "", env, "; ".join(parts)


def _unescape_iw_ssid(text: str) -> str:
    """Reverse iw's print_ssid_escaped() (iw util.c).

    iw prints printable ASCII as-is and every other byte — non-printable,
    non-ASCII (UTF-8), backslash, and a space at either end — as "\\xNN".
    The escaping is therefore unambiguous: decode \\xNN back to bytes and
    the result as UTF-8.  A hidden SSID (zero length, or all NUL bytes) → "".
    """
    raw = bytearray()
    i = 0
    while i < len(text):
        if text.startswith("\\x", i) and i + 4 <= len(text):
            try:
                raw.append(int(text[i + 2:i + 4], 16))
                i += 4
                continue
            except ValueError:
                pass
        raw.extend(text[i].encode("utf-8"))
        i += 1
    if not raw.strip(b"\x00"):
        return ""
    return raw.decode("utf-8", errors="replace")


# HT MCS index → per-stream (bits, rate) is MCS % 8 in _MCS_MOD; data
# subcarriers per width are the same as VHT's (802.11n Table 19-6).
_HT_SYMBOL_US = {True: 3.6, False: 4.0}  # short GI / long GI


def _ht_rate_mbps(bw_mhz: int, max_index: int, sgi: bool) -> float:
    nss = max_index // 8 + 1
    bits, rate = _MCS_MOD[max_index % 8]
    nsd = _VHT_NSD.get(bw_mhz if bw_mhz in (20, 40) else 40, 0)
    return nsd * bits * rate * nss / _HT_SYMBOL_US[sgi]


def parse_iw_scan(output: str) -> Dict[str, dict]:
    """Parse `iw dev <iface> scan dump -u` into {bssid_lower: fields}.

    `-u` additionally prints IEs iw cannot decode (Cisco IE 133, Mobility
    Domain, RSNX, RNR …) and every vendor-specific IE; the decoded output is
    otherwise identical, so a single pass provides everything.
    """
    result: Dict[str, dict] = {}
    for block in re.split(r"(?m)^BSS ", output)[1:]:
        lines = block.splitlines()
        if not lines:
            continue
        m = re.match(r"([0-9a-f:]{17})", lines[0], re.IGNORECASE)
        if not m:
            continue
        bssid = m.group(1).lower()
        text = "BSS " + "\n".join(lines)
        meta, ies = _iw_block_sections(lines)
        d: dict = {"iw_seen": True}

        # ── BSS-level metadata ───────────────────────────────────────────
        sig_m = re.search(r"([-\d.]+)\s*dBm", _first(meta, "signal"))
        if sig_m:
            d["dbm_exact"] = float(sig_m.group(1))
        freq_m = re.search(r"([\d.]+)", _first(meta, "freq"))
        freq_val = float(freq_m.group(1)) if freq_m else 0.0
        band = freq_to_band(int(freq_val)) if freq_val else "?"
        for ls in meta.get("last seen", []):
            ms = _re_int(r"(\d+)\s*ms ago", ls)
            if ms is not None:
                d["last_seen_ms"] = ms
        bi = _re_int(r"(\d+)\s*TU", _first(meta, "beacon interval"))
        if bi is not None:
            d["beacon_interval_tu"] = bi
        d["freq_mhz"] = int(round(freq_val)) if freq_val else 0
        d["associated"] = "-- associated" in lines[0]
        d["capability_tokens"] = tuple(_first(meta, "capability").split("(")[0].split())
        if "SSID" in ies:
            ssid_txt = ies["SSID"][0].split("\n", 1)[0]
            d["ssid"] = _unescape_iw_ssid(ssid_txt[1:] if ssid_txt.startswith(" ") else ssid_txt)
        else:
            d["ssid"] = ""  # zero-length SSID IE (hidden) or none at all

        # ── PHY families present ─────────────────────────────────────────
        ht_caps = _first(ies, "HT capabilities")
        vht_caps = _first(ies, "VHT capabilities")
        he_caps = _first(ies, "HE capabilities")
        eht_caps = _first(ies, "EHT capabilities")
        has_ht, has_vht = "HT capabilities" in ies, "VHT capabilities" in ies
        has_he, has_eht = "HE capabilities" in ies, "EHT capabilities" in ies
        # VHT is defined for 5 GHz only (802.11ac Clause 21).  Some Broadcom
        # 2.4 GHz APs add a vendor VHT IE ("TurboQAM / 256-QAM"); that is a
        # proprietary 802.11n extension, not Wi-Fi 5.
        vht_valid = has_vht and band == BAND_5
        if has_vht and band == BAND_24:
            d["vht_24_proprietary"] = True
        if has_eht:
            d["wifi_gen"] = "WiFi 7"
        elif has_he:
            d["wifi_gen"] = "WiFi 6E" if band == BAND_6 else "WiFi 6"
        elif vht_valid:
            d["wifi_gen"] = "WiFi 5"
        elif has_ht:
            d["wifi_gen"] = "WiFi 4"
        else:
            d["wifi_gen"] = ""

        # ── Capability-level max width (what the AP *could* do) ──────────
        cap_bw = 20
        if has_ht and "HT20/HT40" in ht_caps:
            cap_bw = 40
        if vht_valid:
            cap_bw = max(cap_bw, 80)
            if re.search(r"Supported Channel Width:\s*160 MHz", vht_caps):
                cap_bw = max(cap_bw, 160)
        if has_he:
            if "HE40/HE80/5GHz" in he_caps:
                cap_bw = max(cap_bw, 80)
            if "HE160/5GHz" in he_caps or "HE160/HE80+80/5GHz" in he_caps:
                cap_bw = max(cap_bw, 160)
            if "HE40/2.4GHz" in he_caps:
                cap_bw = max(cap_bw, 40)
        if has_eht and "320MHz in 6GHz Supported" in eht_caps:
            cap_bw = max(cap_bw, 320)
        fam = [n for n, ok in (("HT", has_ht), ("VHT", vht_valid), ("HE", has_he), ("EHT", has_eht)) if ok]
        if d.get("vht_24_proprietary"):
            fam.append("VHT-256QAM (proprietary)")
        cap_bits: List[str] = []
        if fam:
            cap_bits.append("/".join(fam))
        if fam:
            cap_bits.append(f"max width {cap_bw} MHz")
            d["iw_cap_max_bw"] = cap_bw
        if cap_bits:
            d["phy_cap_summary"] = " · ".join(cap_bits)

        # ── Spatial streams / MCS (for theoretical rate) ─────────────────
        def _mcs_nss(section: str) -> List[Tuple[int, int]]:
            pairs = [
                (int(mcs_hi), int(nss))
                for nss, mcs_hi in re.findall(r"(\d+)\s+streams?\s*:\s*MCS\s+0-(\d+)", section)
            ]
            return pairs

        # iw prints one RX set per bandwidth class ("<= 80 MHz", "160 MHz",
        # "80+80 MHz"); APs often support fewer streams at 160 MHz, so the
        # set matching the operating width is chosen once that is known.
        he_rx_sets: Dict[str, List[Tuple[int, int]]] = {}
        if has_he:
            for m_set in re.finditer(r"HE RX MCS and NSS set (<= 80|160|80\+80) MHz\n((?:.*\n)*?)(?=\s*HE (?:RX|TX) MCS|\s*PPE|\Z)", he_caps):
                he_rx_sets[m_set.group(1)] = _mcs_nss(m_set.group(2))
        he_pairs = he_rx_sets.get("<= 80", [])
        eht_pairs = [
            (int(hi), int(nss))
            for hi, nss in re.findall(r"Rx Max NSS for MCS \d+-(\d+):\s*(\d+)", eht_caps)
            if int(nss) > 0
        ]
        if he_pairs:
            d["iw_max_nss"] = max(n for _, n in he_pairs)
            d["iw_max_mcs"] = max(m for m, _ in he_pairs)
        if eht_pairs:
            d["iw_max_nss"] = max(d.get("iw_max_nss", 0), max(n for _, n in eht_pairs))
            d["iw_max_mcs"] = max(d.get("iw_max_mcs", 0), max(m for m, _ in eht_pairs))
        d["_rate_pairs"] = (
            ("EHT", eht_pairs) if eht_pairs else ("HE", he_pairs) if he_pairs else ("", [])
        )
        d["_he_rx_sets"] = he_rx_sets

        # ── HE Operation: BSS color, TWT, 6 GHz operation info ───────────
        he_op = _first(ies, "HE Operation")
        he_feats: List[str] = []
        color = _re_int(r"BSS Color:\s*(\d+)", he_op)
        if color is not None:
            d["bss_color"] = color
            d["bss_color_disabled"] = "BSS Color Disabled" in he_op
            he_feats.append(
                f"BSS color {color}" + (" (disabled)" if d["bss_color_disabled"] else "")
            )
        ext_caps = _first(ies, "Extended capabilities")
        if (
            re.search(r"TWT Responder", he_caps)
            or "TWT Responder Support" in ext_caps
            or "TWT Required" in he_op
        ):
            he_feats.append("TWT responder")
        if "Broadcast TWT" in he_caps:
            he_feats.append("Broadcast TWT")
        # Spatial Reuse Parameter Set = extension element 39 (802.11ax 9.4.2.252).
        # SR Control B1 set means non-SRG OBSS-PD spatial reuse is disallowed.
        sr_raw = _hex_bytes(_first(ies, "Unknown Extension ID (39)"))
        if sr_raw:
            obss_pd = not (sr_raw[0] & 0x02)
            he_feats.append("Spatial reuse" + (" (OBSS-PD allowed)" if obss_pd else " (OBSS-PD disallowed)"))
        if he_feats:
            d["he_eht_features"] = ", ".join(he_feats)

        he6_primary = _re_int(r"Primary Channel:\s*(\d+)", he_op)
        he6_width_m = re.search(r"Channel Width:\s*([^\n]+)", he_op)
        he6_ccfs0 = _re_int(r"Center Frequency Segment 0:\s*(\d+)", he_op)
        he6_ccfs1 = _re_int(r"Center Frequency Segment 1:\s*(\d+)", he_op)
        reg_info = _re_int(r"Regulatory Info:\s*(\d+)", he_op)
        if reg_info is not None and band == BAND_6:
            d["he_6ghz_ap_type"] = _6GHZ_AP_TYPES.get(reg_info, f"Reserved ({reg_info})")

        # ── EHT Operation: width, CCFS, puncturing ───────────────────────
        eht_op = _first(ies, "EHT Operation")
        eht_w = _re_int(r"Channel Width:\s*(\d+)\s*MHz", eht_op)
        eht_ccfs0 = _re_int(r"Center Frequency Segment 0:\s*(\d+)", eht_op)
        eht_ccfs1 = _re_int(r"Center Frequency Segment 1:\s*(\d+)", eht_op)
        punct_m = re.search(r"Disabled Subchannel Bitmap:\s*0x([0-9a-f]{4})", eht_op, re.IGNORECASE)
        if punct_m:
            # iw prints the two octets in transmission order ("0x%02x%02x" of
            # ie[3], ie[4]); the field is little-endian (hostap: le16).
            hx = punct_m.group(1)
            d["punct_bitmap"] = int(hx[0:2], 16) | (int(hx[2:4], 16) << 8)

        # ── Multi-Link (Wi-Fi 7 MLD) ─────────────────────────────────────
        mld_m = re.search(r"MLD MAC:\s*([0-9a-f:]{17})", _first(ies, "Multi-Link"), re.IGNORECASE)
        if mld_m:
            d["mld_mac"] = mld_m.group(1).lower()

        # ── Operating width & bonded-block center ────────────────────────
        oper_bw: Optional[int] = None
        center_idx: Optional[int] = None
        non_contiguous = False
        if eht_w in (20, 40, 80, 160, 320):
            # 802.11be: for 160/320 MHz CCFS1 is the center of the whole
            # channel and CCFS0 the center of its primary half (hostap
            # ieee802_11_eht.c); for ≤ 80 MHz CCFS0 is the center.
            oper_bw = eht_w
            center_idx = eht_ccfs1 if eht_w >= 160 and eht_ccfs1 else eht_ccfs0
        elif he6_width_m and band == BAND_6:
            wtxt = he6_width_m.group(1)
            if wtxt.startswith("20"):
                oper_bw, center_idx = 20, he6_primary
            elif wtxt.startswith("40"):
                oper_bw, center_idx = 40, he6_ccfs0
            elif wtxt.startswith("80 MHz"):
                oper_bw, center_idx = 80, he6_ccfs0
            else:  # "80+80 or 160 MHz"
                oper_bw = 160
                if he6_ccfs1 and he6_ccfs0 and abs(he6_ccfs1 - he6_ccfs0) == 8:
                    center_idx = he6_ccfs1
                elif he6_ccfs1:
                    # 80+80: draw the 80 MHz segment holding the primary;
                    # the second segment is kept separately.
                    oper_bw, center_idx, non_contiguous = 80, he6_ccfs0, True
                    d["iw_center_freq2"] = chan_index_to_freq(he6_ccfs1, band)
                else:
                    center_idx = he6_ccfs0
        elif vht_valid and "VHT operation" in ies:
            vht_op = _first(ies, "VHT operation")
            code = _re_int(r"channel width:\s*(\d+)", vht_op)
            seg0 = _re_int(r"center freq segment 1:\s*(\d+)", vht_op)  # iw's "1" = CCFS0
            seg1 = _re_int(r"center freq segment 2:\s*(\d+)", vht_op)  # iw's "2" = CCFS1
            # 802.11-2016 Table 9-252: width 1 covers 80, 160 and 80+80
            # (CCFS1 decides); widths 2/3 are the deprecated 160 / 80+80.
            # hostap get_vht_operation_channel_width: CCFS1 set and 8 from
            # CCFS0 → 160; any other non-zero CCFS1 → 80+80; else 80.
            if code == 1:
                if seg1 and seg0 and abs(seg1 - seg0) == 8:
                    oper_bw, center_idx = 160, seg1
                elif seg1:
                    oper_bw, center_idx, non_contiguous = 80, seg0, True
                    d["iw_center_freq2"] = chan_index_to_freq(seg1, band)
                else:
                    oper_bw, center_idx = 80, seg0
            elif code == 2:
                oper_bw, center_idx = 160, seg0
            elif code == 3:
                oper_bw, center_idx, non_contiguous = 80, seg0, True
                if seg1:
                    d["iw_center_freq2"] = chan_index_to_freq(seg1, band)
        if oper_bw is None and "HT operation" in ies:
            ht_op = _first(ies, "HT operation")
            sec = re.search(r"secondary channel offset:\s*(\w+)", ht_op)
            sta_w = re.search(r"STA channel width:\s*(\S+)", ht_op)
            if sec and sec.group(1) in ("above", "below") and sta_w and sta_w.group(1) == "any":
                oper_bw = 40
                if freq_val:
                    d["iw_center_freq"] = int(freq_val) + (10 if sec.group(1) == "above" else -10)
            else:
                oper_bw = 20
        if oper_bw:
            d["iw_oper_bw"] = oper_bw
        if non_contiguous:
            d["iw_80p80"] = True
        # HE rate at 160 MHz uses the 160 MHz MCS/NSS set when advertised
        if oper_bw == 160 and he_rx_sets.get("160") and d["_rate_pairs"][0] == "HE":
            d["_rate_pairs"] = ("HE", he_rx_sets["160"])
            d["iw_max_nss"] = max(n for _, n in he_rx_sets["160"])
            d["iw_max_mcs"] = max(m for m, _ in he_rx_sets["160"])
        if center_idx and "iw_center_freq" not in d:
            cf = chan_index_to_freq(center_idx, band)
            if cf:
                d["iw_center_freq"] = cf

        # ── BSS Load ─────────────────────────────────────────────────────
        bss_load = _first(ies, "BSS Load")
        sc = _re_int(r"station count:\s*(\d+)", bss_load)
        cu = _re_int(r"channel utili[sz]ation:\s*(\d+)/255", bss_load)
        if sc is not None:
            d["station_count"] = sc
        if cu is not None:
            d["chan_util"] = cu

        # ── RSN / WPA / AKM / PMF ────────────────────────────────────────
        rsn = _first(ies, "RSN")
        wpa = _first(ies, "WPA")
        sec_ie = rsn or wpa
        akm_m = re.search(r"Authentication suites:\s*([^\n]*)", sec_ie)
        if akm_m:
            raw = akm_m.group(1).strip()
            suites = _akm_suites(raw)
            d["akm_raw"] = raw
            d["akm_suites"] = suites
            d["ft"] = any(s.startswith("FT/") for s in suites)
            d["akm"] = _akm_label(suites)
        caps_m = re.search(r"\*\s*Capabilities:\s*([^\n]*)", rsn)
        if caps_m:
            decoded_caps = _decode_rsn_capabilities(caps_m.group(1))
            if decoded_caps:
                d["rsn_capabilities"] = decoded_caps
            d["pmf"] = _pmf_from_rsn_caps(caps_m.group(1))
        elif rsn:
            d["pmf"] = "No"  # RSNE present without the optional Capabilities field = 0
        else:
            d["pmf"] = "N/A"  # Open / WEP / WPA1-only: PMF is an RSN feature
        d["has_wpa1_ie"] = bool(wpa)
        d["has_rsn_ie"] = bool(rsn)
        for prefix, sec_text in (("rsn", rsn), ("wpa", wpa)):
            if not sec_text:
                continue
            g = re.search(r"Group cipher:\s*(\S+)", sec_text)
            pw = re.search(r"Pairwise ciphers:\s*([^\n]*)", sec_text)
            ak = re.search(r"Authentication suites:\s*([^\n]*)", sec_text)
            d[f"{prefix}_group_cipher"] = g.group(1) if g else ""
            d[f"{prefix}_pairwise"] = tuple(pw.group(1).split()) if pw else ()
            d[f"{prefix}_akm_suites"] = _akm_suites(ak.group(1)) if ak else ()
        # iw scan.c print_rsn_ie: "\t * Group mgmt cipher suite: BIP-GMAC-256"
        grp_mgmt = re.search(r"Group mgmt cipher suite:\s*(\S+)", rsn)
        if grp_mgmt:
            d["group_mgmt_cipher"] = grp_mgmt.group(1)
        # WPA3 "RSN Element Override" (Wi-Fi Alliance compatibility mode):
        # the AP advertises extra AKMs (e.g. SAE-EXT-KEY) only to new clients.
        rsno_akms: List[str] = []
        for rsno in ies.get("RSN Element Override", []) + ies.get("RSN Element Override 2", []):
            mm = re.search(r"Authentication suites:\s*([^\n]*)", rsno)
            if mm:
                rsno_akms.extend(_akm_suites(mm.group(1)))
        if rsno_akms:
            d["rsn_override_akm"] = " ".join(dict.fromkeys(rsno_akms))

        # RSNX (IE 244) — SAE H2E / SAE-PK etc.
        rsnx = _hex_bytes(_first(ies, "Unknown IE (244)"))
        if rsnx:
            bits = int.from_bytes(rsnx, "little")
            d["rsnx_caps"] = ", ".join(name for bit, name in _RSNX_BITS.items() if bits & (1 << bit))

        # Mobility Domain (IE 54): MDID (2 octets) + FT Capability & Policy.
        mde = _hex_bytes(_first(ies, "Unknown IE (54)"))
        if len(mde) >= 3:
            # MDID is shown as an octet string, the same form hostapd's
            # `mobility_domain=` option and most controllers use.
            d["mobility_domain"] = mde[:2].hex()
            d["ft_over_ds"] = bool(mde[2] & 0x01)
            d["ft"] = True

        # OWE transition (Wi-Fi Alliance vendor IE type 28)
        owe = _first(ies, "OWE Transition Mode")
        if owe:
            ob = re.search(r"BSSID:\s*([0-9a-f:]{17})", owe, re.IGNORECASE)
            os_ = re.search(r"SSID:\s*([^\n]*)", owe)
            if ob:
                d["owe_transition_bssid"] = ob.group(1).lower()
            if os_:
                d["owe_transition_ssid"] = os_.group(1).strip()

        # ── Power: TPC report, Power Constraint, Transmit Power Envelope ─
        # The TPC Report "Transmit Power" field is a signed octet
        # (802.11-2020 9.4.2.17); iw prints it as unsigned (scan.c
        # print_tpcreport "%d" of a uint8), so 128-255 are negative values.
        tpc = _re_int(r"TX power:\s*(-?\d+)\s*dBm", _first(ies, "TPC report"))
        if tpc is not None:
            if tpc > 127:
                tpc -= 256
            if -20 <= tpc <= 40:  # anything else is vendor garbage, not a power
                d["tpc_tx_power_dbm"] = tpc
        pc = _re_int(r"(\d+)\s*dB", _first(ies, "Power constraint"))
        if pc is not None:
            d["power_constraint_db"] = pc
        tpe_lines: List[str] = []
        for tpe in ies.get("Transmit Power Envelope", []):
            for mm in re.finditer(r"\*\s*([^\n:]+):\s*([^\n]+)", tpe):
                label = mm.group(1).replace("Local Maximum Transmit Power For ", "").strip()
                tpe_lines.append(f"{label}: {mm.group(2).strip()}")
        if tpe_lines:
            d["tpe_summary"] = "; ".join(dict.fromkeys(tpe_lines))

        # ── Supported rates (legacy/basic rates) ─────────────────────────
        rates, basic = _parse_rates(ies.get("Supported rates", []) + ies.get("Extended supported rates", []))
        d["max_legacy_rate"] = max(rates) if rates else 0.0
        # iw util.c print_mcs_index prints ranges, e.g. "0-15, 32".  MCS 32 is
        # the 40 MHz duplicate (6 Mbps) mode, not a higher rate, so the
        # maximum is taken over indices ≤ 31 only.
        ht_line = re.search(r"HT (?:TX/)?RX MCS rate indexes supported:\s*([\d, -]+)", ht_caps)
        if ht_line:
            idx = [
                int(b or a)
                for a, b in re.findall(r"(\d+)(?:-(\d+))?", ht_line.group(1))
                if int(b or a) <= 31
            ]
            if idx:
                d["ht_max_mcs_index"] = max(idx)
                d["ht_sgi"] = bool(re.search(r"RX HT(20|40) SGI", ht_caps))
        if vht_valid:
            vht_rx = vht_caps.split("VHT TX MCS set")[0]
            vpairs = _mcs_nss(vht_rx)
            if vpairs:
                d["vht_rate_pairs"] = vpairs
        if rates:
            d["basic_rates"] = " ".join(f"{r:g}" for r in sorted(set(basic))) if basic else ""
            d["has_11b_rates"] = any(r in (1.0, 2.0, 5.5, 11.0) for r in rates)

        # ── WPS manufacturer hint (often reveals branded vendor on LAA MACs) ──
        wps_manuf_m = re.search(r"\*\s*Manufacturer:\s*(.+?)\s*$", _first(ies, "WPS"), re.MULTILINE)
        if wps_manuf_m:
            wps_name = wps_manuf_m.group(1).strip().strip('"')
            if wps_name and wps_name.lower() not in {"unknown", "private", "n/a"}:
                d["wps_manufacturer"] = wps_name

        # ── Vendor-specific IE parsers (AP name, TX power, Meraki …) ─────
        parse_vendor_ies(text, d)

        # ── 802.11k / 802.11v ────────────────────────────────────────────
        # Exact line: bit 28 prints as "Neighbor Report TSF Offset" (iw scan.c)
        d["rrm"] = bool(re.search(r"(?m)^\s*Neighbor Report\s*$", _first(ies, "RM enabled capabilities")))
        d["btm"] = "BSS Transition" in ext_caps
        d["_has_rm_ie"] = "RM enabled capabilities" in ies
        d["_has_extcap_ie"] = "Extended capabilities" in ies

        # ── Country (802.11d) ────────────────────────────────────────────
        if "Country" in ies:
            cc, env_txt, pwr = _summarise_country(_first(ies, "Country"), band)
            if cc:
                d["country"] = cc
            if env_txt:
                d["country_env"] = env_txt
            if pwr:
                d["country_power"] = pwr

        # ── TIM / DTIM (beacon only; probe responses carry no TIM) ───────
        for tim in ies.get("TIM", []):
            dtim = _re_int(r"DTIM Period\s+(\d+)", tim)
            if dtim is not None:
                d["dtim_period"] = dtim
                break

        # ── Reduced Neighbor Report (co-located 6 GHz discovery) ─────────
        rnr_entries: List[Dict[str, object]] = []
        for rnr_hex in ies.get("Unknown IE (201)", []):
            rnr_entries.extend(_parse_rnr(_hex_bytes(rnr_hex)))
        if rnr_entries:
            d["rnr_neighbors"] = tuple(rnr_entries)

        vendor_ouis = sorted(
            {
                x.upper()
                for x in re.findall(r"OUI\s*([0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2})", "\n".join(ies.get("Vendor specific", [])), re.IGNORECASE)
            }
        )
        if vendor_ouis:
            d["vendor_ie_ouis"] = ", ".join(vendor_ouis)

        result[bssid] = d
    return result


def _akm_label(suites: Tuple[str, ...]) -> str:
    """Compact AKM label from normalised iw AKM tokens."""
    s = set(suites)
    has = lambda *names: any(n in s for n in names)  # noqa: E731
    if has("OWE"):
        label = "OWE (Enhanced Open)"
    elif has("802.1X/SUITE-B-192", "FT/802.1X/SHA-384"):
        label = "Enterprise 192-bit (Suite B)"
    elif has("802.1X", "FT/802.1X", "802.1X/SHA-256", "802.1X/SUITE-B", "FILS/SHA-256", "FILS/SHA-384"):
        label = "Enterprise (802.1X)"
    elif has("SAE", "FT/SAE", "SAE-EXT-KEY", "FT/SAE-EXT-KEY") and has("PSK", "FT/PSK", "PSK/SHA-256"):
        label = "WPA2+WPA3 (PSK+SAE)"
    elif has("SAE", "FT/SAE", "SAE-EXT-KEY", "FT/SAE-EXT-KEY"):
        label = "WPA3-SAE"
    elif has("PSK", "FT/PSK", "PSK/SHA-256", "PSK/SHA-384", "FT/PSK/SHA-384"):
        label = "PSK"
    else:
        label = " ".join(suites)
    if any(t.startswith("FT/") for t in suites):
        label += " +FT"
    return label


# ─────────────────────────────────────────────────────────────────────────────
# Connected-link telemetry (iw link / station dump / survey dump)
# ─────────────────────────────────────────────────────────────────────────────


def _parse_iw_station_dump(output: str, target_bssid: str = "") -> Dict[str, object]:
    """Parse `iw dev <iface> station dump` for a station block (usually current AP)."""

    target = (target_bssid or "").lower()
    blocks = re.split(r"(?m)^Station\s+", output)
    for block in blocks[1:]:
        lines = block.splitlines()
        if not lines:
            continue
        m = re.match(r"([0-9a-f:]{17})", lines[0].strip(), re.IGNORECASE)
        if not m:
            continue
        bssid = m.group(1).lower()
        if target and bssid != target:
            continue

        text = "\n".join(lines)
        d: Dict[str, object] = {"conn_bssid": bssid}

        def _int_value(pattern: str) -> Optional[int]:
            mm = re.search(pattern, text, re.IGNORECASE)
            return int(mm.group(1)) if mm else None

        d["conn_inactive_ms"] = _int_value(r"inactive\s+time:\s*(\d+)\s*ms")
        d["conn_tx_retries"] = _int_value(r"tx\s+retries:\s*(\d+)")
        d["conn_tx_failed"] = _int_value(r"tx\s+failed:\s*(\d+)")
        d["conn_connected_time_s"] = _int_value(r"connected\s+time:\s*(\d+)\s*seconds")
        # iw station.c prints per-chain values in brackets before the unit:
        #   "signal:  \t-46 [-47, -46] dBm"   "signal avg:\t-37 [-38, -37] dBm"
        d["conn_signal_avg_dbm"] = _int_value(r"(?m)^\s*signal\s+avg:\s*(-?\d+)")
        chains_m = re.search(r"(?m)^\s*signal:\s*-?\d+\s*\[([^\]]+)\]", text)
        if chains_m:
            d["conn_signal_chains"] = chains_m.group(1).strip()
        d["conn_tx_packets"] = _int_value(r"tx\s+packets:\s*(\d+)")
        d["conn_tx_bytes"] = _int_value(r"tx\s+bytes:\s*(\d+)")
        d["conn_rx_packets"] = _int_value(r"rx\s+packets:\s*(\d+)")
        d["conn_rx_bytes"] = _int_value(r"rx\s+bytes:\s*(\d+)")
        d["conn_rx_drop_misc"] = _int_value(r"rx\s+drop\s+misc:\s*(\d+)")
        dtim = _int_value(r"DTIM\s+period:\s*(\d+)")
        if dtim is not None:
            d["conn_dtim_period"] = dtim

        exp_m = re.search(r"expected\s+throughput:\s*([^\n]+)", text, re.IGNORECASE)
        if exp_m:
            d["conn_expected_tp"] = exp_m.group(1).strip()

        return d

    return {}


# nl80211 guard-interval enums (NL80211_RATE_INFO_HE_GI_* / EHT_GI_*).
_GI_ENUM = {"0": "0.8 µs", "1": "1.6 µs", "2": "3.2 µs"}


def _parse_bitrate_phy(raw: str) -> str:
    """Compact PHY summary from an iw bitrate string.

    e.g. "1200.9 MBit/s 80MHz HE-MCS 11 HE-NSS 2 HE-GI 0 HE-DCM 0"
      →  "HE · MCS 11 · NSS 2 · GI 0.8 µs · DCM 0 · 80 MHz"
    """
    text = (raw or "").strip()
    if not text:
        return ""
    parts: List[str] = []
    mode_m = re.search(r"\b(EHT|HE|VHT)-MCS\b|\b(MCS)\s+\d+", text)
    if mode_m:
        parts.append(mode_m.group(1) or "HT")
    mcs_m = re.search(r"\b(?:EHT-|HE-|VHT-)?MCS\s*(\d+)\b", text)
    if mcs_m:
        parts.append(f"MCS {mcs_m.group(1)}")
    nss_m = re.search(r"\b(?:EHT|HE|VHT)-NSS\s*(\d+)\b", text)
    if nss_m:
        parts.append(f"NSS {nss_m.group(1)}")
    gi_m = re.search(r"\b(?:EHT|HE)-GI\s*(\d+)\b", text)
    if gi_m:
        parts.append(f"GI {_GI_ENUM.get(gi_m.group(1), gi_m.group(1))}")
    elif re.search(r"\bshort GI\b", text):
        parts.append("GI 0.4 µs")
    dcm_m = re.search(r"\b(?:EHT|HE)-DCM\s*(\d+)\b", text)
    if dcm_m:
        parts.append(f"DCM {dcm_m.group(1)}")
    ru_m = re.search(r"\bRU\s*([0-9A-Za-z/+-]+)", text)
    if ru_m:
        parts.append(f"RU {ru_m.group(1)}")
    bw_m = re.search(r"\b(20|40|80|160|320)\s*MHz", text)
    if bw_m:
        parts.append(f"{bw_m.group(1)} MHz")
    return " · ".join(parts)


def _parse_iw_survey_dump(output: str, target_freq_mhz: Optional[int]) -> Dict[str, object]:
    """Raw survey counters for the in-use (or target) channel.

    Returns active/busy times (ms, cumulative since driver start) and noise.
    Busy % must be computed from deltas between polls — see SurveyTracker.
    """
    blocks = re.split(r"(?m)^Survey\s+data\s+from", output)
    chosen: Optional[str] = None
    for block in blocks[1:]:
        b = block.strip()
        if not b:
            continue
        freq_m = re.search(r"frequency:\s*(\d+)\s*MHz", b, re.IGNORECASE)
        if not freq_m:
            continue
        freq = int(freq_m.group(1))
        if "[in use]" in b:
            chosen = b
            break
        if target_freq_mhz and freq == target_freq_mhz:
            chosen = b
            break
    if not chosen:
        return {}

    def _int_value(pattern: str) -> Optional[int]:
        mm = re.search(pattern, chosen, re.IGNORECASE)
        return int(mm.group(1)) if mm else None

    d: Dict[str, object] = {}
    freq = _int_value(r"frequency:\s*(\d+)\s*MHz")
    active = _int_value(r"channel\s+active\s+time:\s*(\d+)\s*ms")
    busy = _int_value(r"channel\s+busy\s+time:\s*(\d+)\s*ms")
    noise = _int_value(r"noise:\s*(-?\d+)\s*dBm")
    if freq is not None:
        d["freq"] = freq
    if active is not None:
        d["active_ms"] = active
    if busy is not None:
        d["busy_ms"] = busy
    if noise is not None:
        d["conn_survey_noise_dbm"] = noise
    return d


class SurveyTracker:
    """Turns cumulative survey counters into per-poll channel-busy %.

    `iw survey dump` reports channel active/busy time accumulated since the
    driver started, so busy/active of a single sample is a lifetime average.
    Keeping the previous sample per (iface, freq) gives the busy ratio over
    the last polling interval instead.
    """

    def __init__(self):
        self._prev: Dict[Tuple[str, int], Tuple[int, int]] = {}

    def busy_pct(self, iface: str, survey: Dict[str, object]) -> Optional[float]:
        freq = survey.get("freq")
        active = survey.get("active_ms")
        busy = survey.get("busy_ms")
        if freq is None or active is None or busy is None:
            return None
        key = (iface, int(freq))
        prev = self._prev.get(key)
        self._prev[key] = (int(active), int(busy))
        if prev:
            d_active = int(active) - prev[0]
            d_busy = int(busy) - prev[1]
            if d_active > 0 and 0 <= d_busy <= d_active:
                return d_busy / d_active * 100.0
        # First sample (or counter reset): fall back to the lifetime ratio.
        return (int(busy) / int(active) * 100.0) if int(active) > 0 else None


def _get_connected_link_metrics(
    iface: str,
    survey_tracker: Optional[SurveyTracker] = None,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, object]:
    """Collect connected-link telemetry via `iw link`, `station dump`, `survey dump`."""

    if not iface:
        return {}
    try:
        link_res = run_tool([IW_BIN, "dev", iface, "link"], timeout=3, stop_event=stop_event)
    except ScanCancelled:
        raise
    except Exception:
        return {}
    if link_res.returncode != 0:
        return {}

    link_text = link_res.stdout or ""
    if "Not connected." in link_text:
        return {}

    d: Dict[str, object] = {"conn_iface": iface}

    bssid_m = re.search(r"Connected\s+to\s+([0-9a-f:]{17})", link_text, re.IGNORECASE)
    if bssid_m:
        d["conn_bssid"] = bssid_m.group(1).lower()

    ssid_m = re.search(r"(?m)^\s*SSID:\s*(.+)\s*$", link_text)
    if ssid_m:
        d["conn_link_ssid"] = ssid_m.group(1).strip()

    # iw link.c prints "freq: %d.%d" (e.g. "freq: 5745.0") since iw 6.x
    freq_m = re.search(r"(?m)^\s*freq:\s*(\d+)(?:\.\d+)?\s*$", link_text)
    if freq_m:
        d["conn_link_freq_mhz"] = int(freq_m.group(1))

    sig_m = re.search(r"(?m)^\s*signal:\s*([\-\d.]+)", link_text)
    if sig_m:
        d["conn_link_signal_dbm"] = float(sig_m.group(1))

    rx_m = re.search(r"(?m)^\s*rx\s+bitrate:\s*(.+)\s*$", link_text)
    if rx_m:
        d["conn_rx_bitrate"] = rx_m.group(1).strip()
        d["conn_rx_phy"] = _parse_bitrate_phy(d["conn_rx_bitrate"])

    tx_m = re.search(r"(?m)^\s*tx\s+bitrate:\s*(.+)\s*$", link_text)
    if tx_m:
        d["conn_tx_bitrate"] = tx_m.group(1).strip()
        d["conn_tx_phy"] = _parse_bitrate_phy(d["conn_tx_bitrate"])

    try:
        sta_res = run_tool([IW_BIN, "dev", iface, "station", "dump"], timeout=3, stop_event=stop_event)
        if sta_res.returncode == 0:
            sta = _parse_iw_station_dump(sta_res.stdout, str(d.get("conn_bssid", "")))
            if sta:
                d.update(sta)
    except ScanCancelled:
        raise
    except Exception:
        pass

    try:
        survey_res = run_tool([IW_BIN, "dev", iface, "survey", "dump"], timeout=3, stop_event=stop_event)
        if survey_res.returncode == 0:
            survey = _parse_iw_survey_dump(survey_res.stdout, d.get("conn_link_freq_mhz"))
            if survey:
                if "conn_survey_noise_dbm" in survey:
                    d["conn_survey_noise_dbm"] = survey["conn_survey_noise_dbm"]
                busy = (survey_tracker or SurveyTracker()).busy_pct(iface, survey)
                if busy is not None:
                    d["conn_survey_busy_pct"] = busy
    except ScanCancelled:
        raise
    except Exception:
        pass

    # SNR = signal − noise floor (both in dBm) when the driver reports noise.
    sig = d.get("conn_link_signal_dbm")
    noise = d.get("conn_survey_noise_dbm")
    if sig is not None and noise is not None:
        d["conn_snr_db"] = float(sig) - float(noise)
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Enrichment: merge iw data into nmcli AccessPoints
# ─────────────────────────────────────────────────────────────────────────────

# iw fields copied verbatim onto the AccessPoint when present.
_IW_COPY_FIELDS = (
    "iw_seen",
    "dbm_exact",
    "wifi_gen",
    "chan_util",
    "station_count",
    "pmf",
    "akm",
    "akm_raw",
    "akm_suites",
    "has_wpa1_ie",
    "has_rsn_ie",
    "group_mgmt_cipher",
    "rsn_override_akm",
    "rsnx_caps",
    "wps_manufacturer",
    "rrm",
    "btm",
    "ft",
    "mobility_domain",
    "ft_over_ds",
    "country",
    "country_env",
    "country_power",
    "iw_center_freq",
    "iw_center_freq2",
    "iw_80p80",
    "beacon_interval_tu",
    "dtim_period",
    "rsn_capabilities",
    "vendor_ie_ouis",
    "phy_cap_summary",
    "he_eht_features",
    "bss_color",
    "bss_color_disabled",
    "he_6ghz_ap_type",
    "punct_bitmap",
    "mld_mac",
    "owe_transition_bssid",
    "owe_transition_ssid",
    "rnr_neighbors",
    "vht_24_proprietary",
    "ap_name",
    "cisco_tx_power_dbm",
    "ruckus_tx_power_dbm",
    "tpc_tx_power_dbm",
    "power_constraint_db",
    "tpe_summary",
    "basic_rates",
    "has_11b_rates",
    "last_seen_ms",
)

_CONN_COPY_FIELDS = (
    "conn_iface",
    "conn_link_ssid",
    "conn_link_freq_mhz",
    "conn_link_signal_dbm",
    "conn_rx_bitrate",
    "conn_tx_bitrate",
    "conn_expected_tp",
    "conn_signal_avg_dbm",
    "conn_signal_chains",
    "conn_tx_retries",
    "conn_tx_failed",
    "conn_inactive_ms",
    "conn_connected_time_s",
    "conn_tx_packets",
    "conn_tx_bytes",
    "conn_rx_packets",
    "conn_rx_bytes",
    "conn_rx_drop_misc",
    "conn_rx_phy",
    "conn_tx_phy",
    "conn_survey_busy_pct",
    "conn_survey_noise_dbm",
    "conn_snr_db",
)


def iw_scan_texts(iface: str, stop_event: Optional[threading.Event] = None) -> Tuple[str, str]:
    """(`scan dump -u` text, `scan dump -b` text) for *iface*.

    iw's dump command takes a single option (iw scan.c handle_scan_dump):
    `-u` adds undecoded IEs (Cisco IE 133, Mobility Domain, RSNX, RNR,
    vendor IEs) but prints only the first IE set, usually the probe
    response; `-b` prints the beacon IE set too, which carries beacon-only
    elements such as TIM (DTIM period).  Both are read back-to-back.
    """
    res_u = run_tool([IW_BIN, "dev", iface, "scan", "dump", "-u"], timeout=6, stop_event=stop_event)
    if res_u.returncode != 0:
        res_u = run_tool([IW_BIN, "dev", iface, "scan", "dump"], timeout=6, stop_event=stop_event)
    res_b = run_tool([IW_BIN, "dev", iface, "scan", "dump", "-b"], timeout=6, stop_event=stop_event)
    return (
        res_u.stdout if res_u.returncode == 0 else "",
        res_b.stdout if res_b.returncode == 0 else "",
    )


def parse_iw_scan_merged(u_text: str, b_text: str = "") -> Dict[str, dict]:
    """parse_iw_scan() of the `-u` dump, with fields present only in the
    beacon IE set (from the `-b` dump) filled in where missing."""
    data = parse_iw_scan(u_text)
    if b_text:
        for bssid, extra in parse_iw_scan(b_text).items():
            base = data.get(bssid)
            if base is None:
                continue  # BSS appeared between the two reads; skip it
            for k, v in extra.items():
                if k not in base and v not in (None, "", (), []):
                    base[k] = v
    return data


def _iw_scan_iface(iface: str, stop_event: Optional[threading.Event]) -> Dict[str, dict]:
    """Decoded scan cache of *iface* (both IE sets merged)."""
    u_text, b_text = iw_scan_texts(iface, stop_event)
    if not u_text:
        return {}
    data = parse_iw_scan_merged(u_text, b_text)
    for d in data.values():
        d["iw_iface"] = iface
    return data


def _collect_iw(
    survey_tracker: Optional[SurveyTracker],
    stop_event: Optional[threading.Event],
) -> Tuple[Dict[str, dict], Dict[str, Dict[str, object]]]:
    """`scan dump -u` + connected-link telemetry for every managed interface.

    Returns ({bssid_lower: iw fields}, {connected bssid_lower: link fields}).
    A BSS heard by two radios keeps the stronger observation.
    """
    iw_data: Dict[str, dict] = {}
    conn_by_bssid: Dict[str, Dict[str, object]] = {}
    for iface in _detect_wifi_ifaces():
        try:
            scan = _iw_scan_iface(iface, stop_event)
        except ScanCancelled:
            raise
        except Exception:
            scan = {}
        for bssid, d in scan.items():
            prev = iw_data.get(bssid)
            if prev is None or d.get("dbm_exact", -999) > prev.get("dbm_exact", -999):
                iw_data[bssid] = d
        try:
            conn = _get_connected_link_metrics(iface, survey_tracker, stop_event)
        except ScanCancelled:
            raise
        except Exception:
            conn = {}
        if conn.get("conn_bssid"):
            conn_by_bssid[str(conn["conn_bssid"]).lower()] = conn
    return iw_data, conn_by_bssid


def _apply_iw_fields(ap: AccessPoint, d: dict, conn: Optional[Dict[str, object]]) -> None:
    """Copy one BSS's decoded iw fields (and link telemetry) onto *ap*."""
    for attr in _IW_COPY_FIELDS:
        if attr in d:
            setattr(ap, attr, d[attr])
    if "iw_iface" in d:
        ap.iw_iface = d["iw_iface"]

    # Prefer WPS-advertised manufacturer when OUI lookup is missing
    # or when BSSID is locally-administered (common synthetic radio MAC).
    wps_vendor = d.get("wps_manufacturer", "")
    if wps_vendor:
        use_wps = not ap.manufacturer or ap.manufacturer_source.startswith("OUI suffix")
        try:
            if int(ap.bssid[:2], 16) & 0x02:
                use_wps = True
        except ValueError:
            pass
        if use_wps:
            ap.manufacturer = wps_vendor
            ap.manufacturer_source = "WPS / vendor IE (iw scan)"

    # ── Operating width: prefer the decoded Operation element ────────────
    # nmcli derives BANDWIDTH from the same IEs but reports 0 for some
    # 6 GHz BSSs and misreads proprietary 2.4 GHz VHT; the element decoded
    # by parse_iw_scan follows the standard exactly.
    iw_bw = d.get("iw_oper_bw", 0)
    if iw_bw:
        ap.bandwidth_mhz = iw_bw
    elif ap.bandwidth_mhz == 0 and d.get("iw_cap_max_bw", 0) >= 20:
        ap.bandwidth_mhz = d["iw_cap_max_bw"]

    # ── Theoretical max PHY rate when the source reports 0 Mbit/s ────────
    if ap.rate_mbps == 0 and ap.bandwidth_mhz > 0:
        ap.rate_mbps = _max_phy_rate(d, ap.bandwidth_mhz)

    if conn:
        for attr in _CONN_COPY_FIELDS:
            if attr in conn:
                setattr(ap, attr, conn[attr])
        if ap.dtim_period is None and conn.get("conn_dtim_period") is not None:
            ap.dtim_period = int(conn["conn_dtim_period"])
        if ap.dbm_exact is None and conn.get("conn_link_signal_dbm") is not None:
            ap.dbm_exact = float(conn["conn_link_signal_dbm"])


def _max_phy_rate(d: dict, bw_mhz: int) -> float:
    """Highest advertised PHY rate: EHT/HE, else VHT, else HT, else legacy."""
    family, pairs = d.get("_rate_pairs", ("", []))
    if pairs:
        return float(int(round(_best_rate_mbps(family, bw_mhz, pairs))))
    if d.get("vht_rate_pairs"):
        return float(int(round(_best_rate_mbps("VHT", min(bw_mhz, 160), d["vht_rate_pairs"]))))
    if d.get("ht_max_mcs_index") is not None:
        return float(int(round(_ht_rate_mbps(min(bw_mhz, 40), d["ht_max_mcs_index"], d.get("ht_sgi", False)))))
    return float(d.get("max_legacy_rate", 0.0))


def _nm_flag_tokens(pairwise: Tuple[str, ...], group: str, akms: Tuple[str, ...]) -> str:
    """nmcli-style WPA/RSN flag string (devices.c ap_wpa_rsn_flags_to_string)."""
    def cipher(c: str) -> str:
        return c.lower().replace("-", "")

    tokens = [f"pair_{cipher(c)}" for c in pairwise]
    if group:
        tokens.append(f"group_{cipher(group)}")
    s = set(akms)
    if s & {"PSK", "FT/PSK", "PSK/SHA-256", "PSK/SHA-384", "FT/PSK/SHA-384"}:
        tokens.append("psk")
    if s & {"802.1X", "FT/802.1X", "802.1X/SHA-256", "FT/802.1X/SHA-384"}:
        tokens.append("802.1X")
    if s & {"SAE", "FT/SAE", "SAE-EXT-KEY", "FT/SAE-EXT-KEY"}:
        tokens.append("sae")
    if "802.1X/SUITE-B-192" in s:
        tokens.append("wpa-eap-suite-b-192")
    if "OWE" in s:
        tokens.append("owe")
    return " ".join(tokens) if tokens else "(none)"


def _ap_from_iw(d: dict) -> Optional[AccessPoint]:
    """Build an AccessPoint purely from parse_iw_scan() fields (iw data source)."""
    bssid = d.get("bssid", "")
    freq = int(d.get("freq_mhz", 0))
    if not bssid or not freq:
        return None
    dbm = d.get("dbm_exact")
    caps = set(d.get("capability_tokens", ()))
    rsn_akms = tuple(d.get("rsn_akm_suites", ()))
    wpa_akms = tuple(d.get("wpa_akm_suites", ()))
    all_akms = set(rsn_akms) | set(wpa_akms)

    # nmcli-equivalent SECURITY tokens, so labels/filters behave identically
    sec: List[str] = []
    if "Privacy" in caps and not d.get("has_rsn_ie") and not d.get("has_wpa1_ie"):
        sec.append("WEP")
    if d.get("has_wpa1_ie"):
        sec.append("WPA1")
    if all_akms & {"PSK", "FT/PSK", "PSK/SHA-256", "802.1X", "FT/802.1X", "802.1X/SHA-256"} and d.get("has_rsn_ie"):
        sec.append("WPA2")
    if all_akms & {"SAE", "FT/SAE", "SAE-EXT-KEY", "FT/SAE-EXT-KEY"}:
        sec.append("WPA3")
    if "OWE" in all_akms:
        sec.append("OWE")
    elif d.get("owe_transition_bssid") and not d.get("has_rsn_ie"):
        sec.append("OWE-TM")
    if all_akms & {"802.1X", "FT/802.1X", "802.1X/SHA-256", "FT/802.1X/SHA-384"}:
        sec.append("802.1X")
    if "802.1X/SUITE-B-192" in all_akms:
        sec.append("WPA-EAP-SUITE-B-192")

    ap = AccessPoint(
        ssid=d.get("ssid", ""),
        bssid=bssid.upper(),
        mode="Ad-Hoc" if "IBSS" in caps else "Infra",
        channel=freq_to_chan(freq),
        freq_mhz=freq,
        rate_mbps=0.0,
        signal=dbm_to_nm_quality(dbm) if dbm is not None else 0,
        security=" ".join(sec),
        wpa_flags=_nm_flag_tokens(d.get("wpa_pairwise", ()), d.get("wpa_group_cipher", ""), wpa_akms)
        if d.get("has_wpa1_ie")
        else "(none)",
        rsn_flags=_nm_flag_tokens(d.get("rsn_pairwise", ()), d.get("rsn_group_cipher", ""), rsn_akms)
        if d.get("has_rsn_ie")
        else "(none)",
        bandwidth_mhz=int(d.get("iw_oper_bw", 0) or 20),
        in_use=bool(d.get("associated")),
        nm_device=str(d.get("iw_iface", "")),
    )
    return ap


def _post_process(aps: List[AccessPoint]) -> None:
    """Cross-BSS steps shared by both data sources."""
    _inherit_radio_params(aps)

    # ── Frequency-based wifi_gen fallback ─────────────────────────────────
    # If iw missed the AP (no scan cache for the 6 GHz radio), infer the
    # generation from frequency — 6 GHz operation requires 802.11ax or newer.
    for ap in aps:
        if not ap.wifi_gen and ap.freq_mhz >= 5925:
            ap.wifi_gen = "WiFi 6E"
            ap.gen_inferred = True  # a minimum, not a fact: could be Wi-Fi 7

    # ── OWE transition pairing ────────────────────────────────────────────
    # The open BSS names its hidden OWE twin; mirror the link on the twin.
    by_bssid = {ap.bssid.lower(): ap for ap in aps}
    for ap in aps:
        twin = by_bssid.get(ap.owe_transition_bssid or "")
        if twin is not None and not twin.owe_transition_bssid:
            twin.owe_transition_bssid = ap.bssid.lower()
            twin.owe_transition_ssid = ap.ssid

    # ── LAA BSSID vendor inference from UAA sibling MACs ──────────────────
    # MLO / multi-radio APs derive per-radio MACs from the same OUI base.
    # The 6 GHz radio commonly uses a locally-administered (LAA) variant of
    # the 5 GHz radio's universally-administered (UAA) MAC, sharing the
    # last 5 bytes unchanged.  If we matched a vendor for the UAA sibling,
    # apply it to the LAA counterpart.
    tail_to_vendor: Dict[str, str] = {}
    for ap in aps:
        try:
            if ap.manufacturer and not (int(ap.bssid[:2], 16) & 0x02):
                tail_to_vendor[ap.bssid[3:].lower()] = ap.manufacturer
        except ValueError:
            pass
    for ap in aps:
        try:
            if (not ap.manufacturer or ap.manufacturer_source.startswith("OUI suffix")) and (
                int(ap.bssid[:2], 16) & 0x02
            ):
                vendor = tail_to_vendor.get(ap.bssid[3:].lower(), "")
                if vendor:
                    ap.manufacturer = vendor
                    ap.manufacturer_source = "LAA sibling OUI"
        except ValueError:
            pass


def enrich_with_iw(
    aps: List[AccessPoint],
    survey_tracker: Optional[SurveyTracker] = None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Legacy data source: merge iw data into nmcli-built AccessPoints."""
    iw_data, conn_by_bssid = _collect_iw(survey_tracker, stop_event)
    for ap in aps:
        key = ap.bssid.lower()
        _apply_iw_fields(ap, iw_data.get(key, {}), conn_by_bssid.get(key))
    _post_process(aps)


def scan_from_iw(
    survey_tracker: Optional[SurveyTracker] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[AccessPoint]:
    """iw data source: every AccessPoint comes from the kernel scan cache.

    One source of truth — the kernel's cfg80211 BSS table as printed by iw —
    instead of merging nmcli's (wpa_supplicant-derived) view with iw's.
    """
    iw_data, conn_by_bssid = _collect_iw(survey_tracker, stop_event)
    aps: List[AccessPoint] = []
    for bssid, d in iw_data.items():
        d = dict(d, bssid=bssid)
        ap = _ap_from_iw(d)
        if ap is None:
            continue
        _apply_iw_fields(ap, d, conn_by_bssid.get(bssid))
        aps.append(ap)
    _post_process(aps)
    return aps


# Radio-level fields: identical for every virtual BSS of one radio, so a BSS
# iw did not decode may borrow them from a decoded sibling.  Per-BSS fields
# (security, SSID, station count, RSSI) are deliberately not shared.
_RADIO_LEVEL_FIELDS = (
    "wifi_gen",
    "iw_center_freq",
    "iw_80p80",
    "punct_bitmap",
    "phy_cap_summary",
    "he_eht_features",
    "bss_color",
    "bss_color_disabled",
    "he_6ghz_ap_type",
    "country",
    "country_env",
    "country_power",
    "tpe_summary",
    "power_constraint_db",
    "tpc_tx_power_dbm",
    "chan_util",
    "ap_name",
)


def _inherit_radio_params(aps: List[AccessPoint]) -> None:
    """Fill radio-level data for BSSs iw missed from a same-radio sibling.

    Some APs expose extra SSIDs that only NetworkManager lists (e.g. a 6 GHz
    radio whose second BSSID never appears in `iw scan dump`); nmcli then
    reports 0 MHz width and the BSS is drawn as a 20 MHz sliver.  A sibling is
    a decoded BSS on the same frequency, within 3 dB, with a related BSSID
    (see bssids_related).
    """
    # "Own" radio data: decoded by iw this cycle, or restored from the GUI's
    # short-lived iw cache — never data that was itself inherited or guessed.
    def _own(a: AccessPoint) -> bool:
        return (a.iw_seen or a.iw_restored) and not a.radio_params_from

    decoded = [a for a in aps if _own(a)]
    for ap in aps:
        if _own(ap) or not ap.freq_mhz:
            continue
        sib = next(
            (
                d
                for d in decoded
                if d.freq_mhz == ap.freq_mhz
                and similar_signal(ap, d)
                and bssids_related(ap, d)
            ),
            None,
        )
        if sib is None:
            continue
        for f in _RADIO_LEVEL_FIELDS:
            val = getattr(sib, f)
            if val in (None, "", 0, False):
                continue
            # A band-based generation guess always yields to the sibling's
            # decoded value; other fields only fill gaps.
            if getattr(ap, f) in (None, "", 0, False) or (f == "wifi_gen" and ap.gen_inferred):
                setattr(ap, f, val)
        if sib.wifi_gen and not sib.gen_inferred:
            ap.gen_inferred = False
        if sib.bandwidth_mhz and (ap.bandwidth_mhz == 0 or ap.bandwidth_mhz < sib.bandwidth_mhz):
            ap.bandwidth_mhz = sib.bandwidth_mhz
        if ap.rate_mbps == 0 and sib.rate_mbps:
            ap.rate_mbps = sib.rate_mbps
        ap.radio_params_from = sib.bssid


# ─────────────────────────────────────────────────────────────────────────────
class WiFiScanner(QThread):
    """Background thread: periodically calls nmcli and emits fresh AP list.

    Every emitted AccessPoint is a private copy, so the GUI thread can
    mutate what it receives without racing the worker's linger cache.
    """

    data_ready = pyqtSignal(list)  # list[AccessPoint]
    scan_error = pyqtSignal(str)
    source_active = pyqtSignal(str)  # data source actually used this cycle
    status_note = pyqtSignal(str)  # neutral state description (no interface, no NM, …)

    # Data sources
    SOURCE_IW = "iw"  # kernel scan cache via iw (single source of truth)
    SOURCE_NM = "nm"  # legacy: nmcli list, enriched with iw

    # NetworkManager rate-limits user-requested rescans (~10 s); rescanning
    # more often just returns the cached list, so rescans are time-based.
    _RESCAN_MIN_INTERVAL_S = 10.0

    def __init__(self, interval_sec: int = 2, linger_secs: float = 120.0, source: str = "iw"):
        super().__init__()
        self._source = source if source in (self.SOURCE_IW, self.SOURCE_NM) else self.SOURCE_IW
        self._interval = interval_sec
        self._linger_secs = linger_secs
        # bssid_lower → (AccessPoint, last_seen_monotonic)
        self._seen_cache: Dict[str, Tuple["AccessPoint", float]] = {}
        self._stop_event = threading.Event()
        self._clear_cache_requested = False
        self._survey = SurveyTracker()

    def set_interval(self, secs: int):
        self._interval = secs

    def set_linger_secs(self, secs: float):
        """Update the linger window.  Thread-safe (single float assignment)."""
        self._linger_secs = secs

    def request_cache_clear(self):
        """Drop lingering APs on the next cycle (e.g. after an OUI DB update)."""
        self._clear_cache_requested = True

    def _trigger_rescan(self) -> None:
        """Ask NetworkManager for a fresh scan (iw source).

        Triggering a scan needs CAP_NET_ADMIN (NL80211_CMD_TRIGGER_SCAN), so
        an unprivileged app asks the network manager; NetworkManager allows
        it for active local sessions (polkit org.freedesktop.NetworkManager.
        wifi.scan).  Without NetworkManager the app still reads whatever the
        host's own periodic scans leave in the kernel cache.
        """
        if not (os.path.isfile(NMCLI_BIN) and os.access(NMCLI_BIN, os.X_OK)):
            return
        try:
            run_tool([NMCLI_BIN, "dev", "wifi", "rescan"], timeout=10, stop_event=self._stop_event)
        except ScanCancelled:
            raise
        except Exception:
            pass  # rate-limited or not permitted: keep reading the cache

    def _iw_usable(self) -> bool:
        return os.path.isfile(IW_BIN) and os.access(IW_BIN, os.X_OK) and bool(_detect_wifi_ifaces())

    def _nmcli_list(self, rescan: bool) -> subprocess.CompletedProcess:
        return run_tool(
            [NMCLI_BIN, "-t", "-f", NMCLI_FIELDS, "dev", "wifi", "list", "--rescan", "yes" if rescan else "no"],
            timeout=30 if rescan else 8,
            stop_event=self._stop_event,
        )

    def run(self):
        last_rescan = -1e9
        cycle = 0
        while not self._stop_event.is_set():
            # Hidden APs need two consecutive scans to appear reliably: the
            # first --rescan yes sends probe requests, the second reads the
            # probe responses.  The extra rescan on cycle 2 mirrors that on
            # start-up; afterwards rescans follow NM's ~10 s rate limit.
            now = time.monotonic()
            do_rescan = (now - last_rescan) >= self._RESCAN_MIN_INTERVAL_S or cycle == 2
            iw_ok = os.path.isfile(IW_BIN) and os.access(IW_BIN, os.X_OK)
            nm_ok = os.path.isfile(NMCLI_BIN) and os.access(NMCLI_BIN, os.X_OK)
            try:
                if iw_ok and not _detect_wifi_ifaces():
                    # Nothing to scan with: a plain state, not an error.
                    self._emit_note("No Wi-Fi interface detected — connect or enable a wireless adapter.")
                    self.data_ready.emit(self._merge_linger([]))
                    cycle += 1
                    self._stop_event.wait(max(self._interval, 2))
                    continue
                if not iw_ok and not nm_ok:
                    self._emit_note("No scan data source available: neither iw nor NetworkManager is present.")
                    cycle += 1
                    self._stop_event.wait(max(self._interval, 2))
                    continue
                if self._source == self.SOURCE_IW and self._iw_usable():
                    if not nm_ok:
                        self._emit_note(
                            "Showing the kernel's scan cache; NetworkManager is absent, so scans refresh "
                            "only when the system itself scans."
                        )
                    else:
                        self._emit_note("")
                    if do_rescan:
                        self._trigger_rescan()
                        last_rescan = time.monotonic()
                    aps = scan_from_iw(self._survey, self._stop_event)
                    self.source_active.emit(self.SOURCE_IW)
                    self.data_ready.emit(self._merge_linger(aps))
                else:
                    if do_rescan:
                        self._nmcli_list(rescan=True)
                        result = self._nmcli_list(rescan=True)
                        last_rescan = time.monotonic()
                    else:
                        result = self._nmcli_list(rescan=False)
                    if result.returncode == 0:
                        aps = parse_nmcli(result.stdout)
                        enrich_with_iw(aps, self._survey, self._stop_event)
                        self.source_active.emit(self.SOURCE_NM)
                        self.data_ready.emit(self._merge_linger(aps))
                    else:
                        self.scan_error.emit(result.stderr.strip())
            except ScanCancelled:
                break
            except FileNotFoundError:
                self._emit_note("NetworkManager (nmcli) is absent and iw is unavailable; nothing to scan with.")
                self._stop_event.wait(max(self._interval, 5))
            except subprocess.TimeoutExpired:
                self.scan_error.emit("nmcli timed out")
            except Exception as e:
                self.scan_error.emit(str(e))

            cycle += 1
            # Interruptible sleep: stop() wakes this immediately.
            self._stop_event.wait(self._interval)

    def _emit_note(self, text: str) -> None:
        """Emit status_note only when the text changes (keeps the GUI quiet)."""
        if text != getattr(self, "_last_note", None):
            self._last_note = text
            self.status_note.emit(text)

    def _merge_linger(self, aps: List[AccessPoint]) -> List[AccessPoint]:
        """Append recently-vanished APs (dimmed) and return private copies."""
        if self._clear_cache_requested:
            self._seen_cache.clear()
            self._clear_cache_requested = False
        now = time.monotonic()
        fresh: set[str] = set()
        out: List[AccessPoint] = []
        for ap in aps:
            key = ap.bssid.lower()
            ap.is_lingering = False
            self._seen_cache[key] = (ap, now)
            fresh.add(key)
            out.append(copy.copy(ap))

        linger = self._linger_secs
        expired: List[str] = []
        for key, (cached_ap, last_seen) in self._seen_cache.items():
            if key in fresh:
                continue
            if linger > 0 and now - last_seen <= linger:
                ghost = copy.copy(cached_ap)
                ghost.is_lingering = True
                # A vanished BSS is by definition not the live connection.
                ghost.in_use = False
                for attr in _CONN_COPY_FIELDS:
                    setattr(ghost, attr, AccessPoint.__dataclass_fields__[attr].default)
                out.append(ghost)
            else:
                expired.append(key)
        for key in expired:
            del self._seen_cache[key]
        return out

    def stop(self, wait_ms: Optional[int] = 5000) -> bool:
        """Ask the thread to exit; returns True once it has finished.

        Running subprocesses are killed within ~200 ms (see run_tool), so the
        default 5 s wait is ample.  Pass wait_ms=None to wait indefinitely.
        """
        self._stop_event.set()
        if wait_ms is None:
            return self.wait()
        return self.wait(wait_ms)


# ─────────────────────────────────────────────────────────────────────────────
# Table Model
# ─────────────────────────────────────────────────────────────────────────────

TABLE_HEADERS = [
    "▲",
    "SSID",
    "BSSID (MAC)",
    "Manufacturer",
    "Band",
    "Country",
    "Ch",
    "Freq (MHz)",
    "Width (MHz)",
    "Ch. Span",
    "Signal",
    "dBm",
    "Rate (Mbps)",
    "Security",
    "802.11",
    "Gen",
    "Ch.Util%",
    "Clients",
    "Roaming",
    "AP Name",
    "Power Level",
]

COL_INUSE = 0
COL_SSID = 1
COL_BSSID = 2
COL_MANUF = 3
COL_BAND = 4
COL_COUNTRY = 5
COL_CHAN = 6
COL_FREQ = 7
COL_BW = 8
COL_SPAN = 9  # Channel span, e.g. "116–128" for ch116@80MHz on 5 GHz
COL_SIG = 10
COL_DBM = 11
COL_RATE = 12
COL_SEC = 13
COL_MODE = 14
COL_GEN = 15  # WiFi generation (WiFi 4/5/6/6E/7)
COL_UTIL = 16  # Channel utilisation %  (BSS Load)
COL_CLIENTS = 17  # Station count          (BSS Load)
COL_KVR = 18  # 802.11k/v/r roaming flags
COL_APNAME = 19  # Cisco AP system name (IE 133, vendor-optional)
COL_CISCO_PWR = 20  # Cisco beacon radio power from IE 150, in dBm
