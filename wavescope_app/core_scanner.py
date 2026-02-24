"""Scanner and parser subsystem.

Contains nmcli/iw parsers, enrichment logic, and scanner worker thread.
"""

from .core_models import *
from .theme import IW_GEN_COLORS


def _split_terse(line: str) -> List[str]:
    """Split a nmcli terse line on unescaped ':' characters."""
    fields: List[str] = []
    cur: List[str] = []
    i = 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line) and line[i + 1] == ":":
            cur.append(":")
            i += 2
        elif line[i] == ":":
            fields.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(line[i])
            i += 1
    fields.append("".join(cur))
    return fields


def _parse_freq(freq_str: str) -> int:
    m = re.search(r"(\d+)", freq_str)
    return int(m.group(1)) if m else 0


def _parse_rate(rate_str: str) -> float:
    m = re.search(r"([\d.]+)", rate_str)
    return float(m.group(1)) if m else 0.0


# HE/EHT per-stream throughput in Mbps, 0.8 μs GI (IEEE 802.11ax Table 27-52)
# Keyed by (channel_width_MHz, mcs_index — rounded to 7/9/11 bracket)
_HE_RATE_1SS: Dict[Tuple[int, int], float] = {
    (20,   7):   86.0, (20,   9):  114.7, (20,  11):  143.4,
    (40,   7):  172.0, (40,   9):  229.4, (40,  11):  286.8,
    (80,   7):  360.3, (80,   9):  480.4, (80,  11):  600.4,
    (160,  7):  720.6, (160,  9):  960.8, (160, 11): 1201.0,
    (320,  7): 1441.2, (320,  9): 1921.6, (320, 11): 2402.0,
}


def _he_rate_mbps(bw_mhz: int, nss: int, max_mcs: int) -> int:
    """Theoretical max HE/EHT rate in Mbps (0.8 μs GI)."""
    mcs_key = 11 if max_mcs >= 10 else (9 if max_mcs >= 8 else 7)
    return int(round(_HE_RATE_1SS.get((bw_mhz, mcs_key), 0.0) * nss))


def _parse_bw(bw_str: str) -> int:
    m = re.search(r"(\d+)", bw_str)
    return int(m.group(1)) if m else 20


def parse_nmcli(output: str) -> List[AccessPoint]:
    aps: List[AccessPoint] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = _split_terse(line)
        if len(parts) < 12:
            continue
        try:
            in_use = parts[0].strip() == "*"
            ssid = parts[1].strip()
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
            # Derive freq from channel if not provided
            if freq == 0 and chan:
                freq = chan_to_freq(chan)
            aps.append(
                AccessPoint(
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
                )
            )
        except Exception:
            continue
    return aps


# ─────────────────────────────────────────────────────────────────────────────
# iw scan helpers  (enrich nmcli data with BSS Load, WiFi gen, 802.11k/v/r …)
# ─────────────────────────────────────────────────────────────────────────────

_IW_IFACE: Optional[str] = None


def _detect_wifi_iface() -> Optional[str]:
    """Return the first 'managed' wireless interface found by `iw dev`."""
    global _IW_IFACE
    if _IW_IFACE:
        return _IW_IFACE
    try:
        out = subprocess.run(
            ["iw", "dev"], capture_output=True, text=True, timeout=3
        ).stdout
        iface: Optional[str] = None
        for line in out.splitlines():
            s = line.strip()
            if s.startswith("Interface "):
                iface = s.split()[1]
            elif s.startswith("type managed") and iface:
                _IW_IFACE = iface
                return iface
    except Exception:
        pass
    return None


_IW_GEN_COLORS = IW_GEN_COLORS


def _decode_rsn_capabilities(raw_caps: str) -> str:
    """Decode RSN Capabilities using IEEE RSN Capabilities bit definitions."""
    text = (raw_caps or "").strip()
    if not text:
        return ""

    hex_m = re.search(r"0x[0-9a-f]+", text, re.IGNORECASE)
    if not hex_m:
        # Fallback when driver exposes only tokenized text
        fallback: List[str] = []
        if re.search(r"\bMFP-required\b", text, re.IGNORECASE):
            fallback.append("PMF required")
        elif re.search(r"\bMFP-capable\b", text, re.IGNORECASE):
            fallback.append("PMF capable")
        if re.search(r"\bPreAuth\b", text, re.IGNORECASE):
            fallback.append("Pre-authentication")
        if re.search(r"\bNoPairwise\b", text, re.IGNORECASE):
            fallback.append("No pairwise cipher")
        if re.search(r"\bPeerkey\b", text, re.IGNORECASE):
            fallback.append("PeerKey")
        if re.search(r"\bSPP-AMSDU-capable\b", text, re.IGNORECASE):
            fallback.append("SPP-A-MSDU capable")
        if re.search(r"\bSPP-AMSDU-required\b", text, re.IGNORECASE):
            fallback.append("SPP-A-MSDU required")
        if re.search(r"\bPBAC\b", text, re.IGNORECASE):
            fallback.append("PBAC")
        if re.search(r"\bExtended-Key-ID\b|\bExtKeyID\b", text, re.IGNORECASE):
            fallback.append("Extended Key ID")
        if re.search(r"\bOCVC\b", text, re.IGNORECASE):
            fallback.append("OCVC")
        return ", ".join(fallback) if fallback else text

    caps = int(hex_m.group(0), 16) & 0xFFFF
    replay_map = {0: 1, 1: 2, 2: 4, 3: 16}

    decoded: List[str] = []
    if caps & (1 << 0):
        decoded.append("Pre-authentication")
    if caps & (1 << 1):
        decoded.append("No pairwise cipher")

    ptk_rc = replay_map[(caps >> 2) & 0x3]
    gtk_rc = replay_map[(caps >> 4) & 0x3]
    decoded.append(f"PTKSA replay counters: {ptk_rc}")
    decoded.append(f"GTKSA replay counters: {gtk_rc}")

    if caps & (1 << 6):
        decoded.append("PMF capable")
    if caps & (1 << 7):
        decoded.append("PMF required")
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

    # Keep raw value only as a compact suffix for transparency/debugging.
    decoded.append(f"RSN caps {hex_m.group(0).upper()}")
    return ", ".join(decoded)


def parse_iw_scan(output: str) -> Dict[str, dict]:
    """
    Parse the text output of 'iw dev <iface> scan dump' into a dict
    keyed by lowercase BSSID.  Each value is a dict of enrichment fields.
    """
    result: Dict[str, dict] = {}
    # Split on BSS-header lines
    blocks = re.split(r"(?m)^BSS ", output)
    for block in blocks[1:]:
        lines = block.splitlines()
        if not lines:
            continue
        m = re.match(r"([0-9a-f:]{17})", lines[0], re.IGNORECASE)
        if not m:
            continue
        bssid = m.group(1).lower()
        text = "\n".join(lines)
        d: dict = {}

        # ── Exact dBm ────────────────────────────────────────────────────
        sig_m = re.search(r"signal:\s*([-\d.]+)\s*dBm", text)
        if sig_m:
            d["dbm_exact"] = float(sig_m.group(1))

        # ── WiFi generation ──────────────────────────────────────────────
        has_eht = "EHT capabilities" in text
        has_he = "HE capabilities" in text
        has_vht = "VHT capabilities" in text
        has_ht = "HT capabilities" in text
        freq_m = re.search(r"freq:\s*([\d.]+)", text)
        freq_val = float(freq_m.group(1)) if freq_m else 0
        if has_eht:
            d["wifi_gen"] = "WiFi 7"
        elif has_he:
            d["wifi_gen"] = "WiFi 6E" if freq_val >= 5925 else "WiFi 6"
        elif has_vht:
            d["wifi_gen"] = "WiFi 5"
        elif has_ht:
            d["wifi_gen"] = "WiFi 4"
        else:
            d["wifi_gen"] = ""

        fam: List[str] = []
        if has_ht:
            fam.append("HT")
        if has_vht:
            fam.append("VHT")
        if has_he:
            fam.append("HE")
        if has_eht:
            fam.append("EHT")
        width_vals = [
            int(x)
            for x in re.findall(r"\b(20|40|80|160|320)\s*MHz\b", text, re.IGNORECASE)
        ]
        cap_bits: List[str] = []
        if fam:
            cap_bits.append("/".join(fam))
        if width_vals:
            cap_bits.append(f"max width {max(width_vals)} MHz")
            d["iw_cap_max_bw"] = max(width_vals)
        if cap_bits:
            d["phy_cap_summary"] = " · ".join(cap_bits)

        # ── HE/EHT max spatial streams & max MCS index ──────────────────
        # iw reports "N streams: MCS 0-M" for each supported NSS; count how
        # many have a valid MCS range before hitting "not supported".
        he_nss_m = re.findall(
            r"(\d+)\s+streams?\s*:\s*MCS\s+0-(\d+)", text, re.IGNORECASE
        )
        if he_nss_m:
            d["iw_max_nss"] = max(int(n) for n, _ in he_nss_m)
            d["iw_max_mcs"] = max(int(m) for _, m in he_nss_m)

        he_feats: List[str] = []
        bss_color_m = re.search(r"BSS\s+color:\s*(\d+)", text, re.IGNORECASE)
        if bss_color_m:
            he_feats.append(f"BSS color {bss_color_m.group(1)}")
        if re.search(r"\bTWT\b", text, re.IGNORECASE):
            he_feats.append("TWT")
        if re.search(r"Spatial\s+Reuse", text, re.IGNORECASE):
            he_feats.append("Spatial reuse")
        if he_feats:
            d["he_eht_features"] = ", ".join(he_feats)

        # ── BSS Load ─────────────────────────────────────────────────────
        sc_m = re.search(r"station count:\s*(\d+)", text)
        cu_m = re.search(r"channel utilis[ae]tion:\s*(\d+)/255", text)
        if sc_m:
            d["station_count"] = int(sc_m.group(1))
        if cu_m:
            d["chan_util"] = int(cu_m.group(1))

        # ── RSN / AKM / PMF ──────────────────────────────────────────────
        akm_m = re.search(r"Authentication suites:(.*)", text)
        if akm_m:
            raw = akm_m.group(1)
            d["akm_raw"] = raw.strip()
            has_sae = "SAE" in raw
            has_psk = "PSK" in raw and "FT/PSK" not in raw or "PSK" in raw
            has_eap = "EAP" in raw or "802.1X" in raw
            has_owe = "OWE" in raw
            d["ft"] = "FT/" in raw
            if has_owe:
                label = "OWE (Enhanced Open)"
            elif has_eap:
                label = "Enterprise (EAP)"
            elif has_sae and has_psk:
                label = "WPA2+WPA3"
            elif has_sae:
                label = "WPA3-SAE"
            elif has_psk:
                label = "WPA2-PSK"
            else:
                label = raw.strip()
            if d["ft"]:
                label += " +FT"
            d["akm"] = label

        caps_m = re.search(
            r"Capabilities:.*?MFP-(capable|required)", text, re.IGNORECASE
        )
        if caps_m:
            d["pmf"] = (
                "Required" if "required" in caps_m.group(1).lower() else "Optional"
            )
        else:
            d["pmf"] = "No"

        # ── WPS manufacturer hint (often reveals branded vendor on LAA MACs) ──
        wps_manuf_m = re.search(r"(?im)^\s*\*\s*Manufacturer:\s*(.+?)\s*$", text)
        if wps_manuf_m:
            wps_name = wps_manuf_m.group(1).strip().strip('"')
            if wps_name and wps_name.lower() not in {"unknown", "private", "n/a"}:
                d["wps_manufacturer"] = wps_name

        # ── 802.11k / 802.11v ────────────────────────────────────────────
        d["rrm"] = "Neighbor Report" in text
        d["btm"] = "BSS Transition" in text

        # ── Country code ─────────────────────────────────────────────────
        cc_m = re.search(r"Country:\s+([A-Z]{2})", text)
        if cc_m:
            d["country"] = cc_m.group(1)

        # ── Beacon / TIM / RSN capabilities / Vendor IEs ────────────────
        bi_m = re.search(r"beacon\s+interval:\s*(\d+)\s*TU", text, re.IGNORECASE)
        if bi_m:
            d["beacon_interval_tu"] = int(bi_m.group(1))

        dtim_m = re.search(r"DTIM\s+period:\s*(\d+)", text, re.IGNORECASE)
        if dtim_m:
            d["dtim_period"] = int(dtim_m.group(1))

        rsn_caps_m = re.search(r"(?im)^\s*Capabilities:\s*(.+?)\s*$", text)
        if rsn_caps_m:
            decoded_caps = _decode_rsn_capabilities(rsn_caps_m.group(1))
            if decoded_caps:
                d["rsn_capabilities"] = decoded_caps

        vendor_ouis = sorted(
            {
                x.upper()
                for x in re.findall(
                    r"Vendor\s+specific:\s*OUI\s*([0-9a-f:]{8})", text, re.IGNORECASE
                )
            }
        )
        if vendor_ouis:
            d["vendor_ie_ouis"] = ", ".join(vendor_ouis)

        # ── Bonded-block center frequency ─────────────────────────────────
        # VHT (5 GHz 80/160) and HE/EHT (6 GHz) report "center freq 1: XXXX"
        cf1_m = re.search(r"\*\s*center freq(?:\s+segment)?\s*1\s*:\s*(\d+)", text)
        if cf1_m:
            cf = int(cf1_m.group(1))
            if cf > 0:
                d["iw_center_freq"] = cf
        # HT 40 MHz (2.4 GHz) reports secondary channel offset; compute center
        if "iw_center_freq" not in d and freq_val > 0:
            sec_m = re.search(r"\*\s*secondary channel offset:\s*(above|below)", text)
            if sec_m:
                offset = +10 if sec_m.group(1) == "above" else -10
                d["iw_center_freq"] = int(freq_val) + offset

        # ── Operational channel width (from HE/VHT Operation IE) ─────────
        # HE operation (6 GHz):  "* channel width: 160 MHz"
        # VHT operation (5 GHz): "* channel width: N" (numeric code 0-3)
        oper_bw_m = re.search(
            r"\*\s*channel\s+width\s*:\s*(?:\d+\s+\()?(\d+)\s*MHz",
            text, re.IGNORECASE,
        )
        if oper_bw_m:
            cw = int(oper_bw_m.group(1))
            if cw in (20, 40, 80, 160, 320):
                d["iw_oper_bw"] = cw
        if "iw_oper_bw" not in d and re.search(r"VHT\s+operation", text, re.IGNORECASE):
            vht_code_m = re.search(r"\*\s*channel\s+width:\s*(\d+)", text, re.IGNORECASE)
            if vht_code_m:
                _vht_bw = {0: 40, 1: 80, 2: 160, 3: 160}
                code = int(vht_code_m.group(1))
                bw_val = _vht_bw.get(code, 0)
                if bw_val:
                    d["iw_oper_bw"] = bw_val

        result[bssid] = d
    return result


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
        d["conn_signal_avg_dbm"] = _int_value(r"signal\s+avg:\s*(-?\d+)\s*dBm")
        d["conn_tx_packets"] = _int_value(r"tx\s+packets:\s*(\d+)")
        d["conn_tx_bytes"] = _int_value(r"tx\s+bytes:\s*(\d+)")
        d["conn_rx_packets"] = _int_value(r"rx\s+packets:\s*(\d+)")
        d["conn_rx_bytes"] = _int_value(r"rx\s+bytes:\s*(\d+)")
        d["conn_rx_drop_misc"] = _int_value(r"rx\s+drop\s+misc:\s*(\d+)")

        exp_m = re.search(r"expected\s+throughput:\s*([^\n]+)", text, re.IGNORECASE)
        if exp_m:
            d["conn_expected_tp"] = exp_m.group(1).strip()

        return d

    return {}


def _parse_bitrate_phy(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    parts: List[str] = []
    mode_m = re.search(r"\b(EHT|HE|VHT|HT)-MCS\b", text)
    if mode_m:
        parts.append(mode_m.group(1))
    mcs_m = re.search(r"\b(?:EHT|HE|VHT|HT)-MCS\s*(\d+)\b", text)
    if mcs_m:
        parts.append(f"MCS {mcs_m.group(1)}")
    nss_m = re.search(r"\b(?:EHT|HE|VHT|HT)-NSS\s*(\d+)\b", text)
    if nss_m:
        parts.append(f"NSS {nss_m.group(1)}")
    gi_m = re.search(r"\b(?:EHT|HE|VHT|HT)-GI\s*([\d.]+)\b", text)
    if gi_m:
        parts.append(f"GI {gi_m.group(1)}")
    dcm_m = re.search(r"\b(?:EHT|HE)-DCM\s*(\d+)\b", text)
    if dcm_m:
        parts.append(f"DCM {dcm_m.group(1)}")
    ru_m = re.search(r"\bRU\s*([0-9A-Za-z/]+)\b", text)
    if ru_m:
        parts.append(f"RU {ru_m.group(1)}")
    bw_m = re.search(r"\b(20|40|80|160|320)\s*MHz\b", text)
    if bw_m:
        parts.append(f"{bw_m.group(1)} MHz")
    return " · ".join(parts)


def _parse_iw_survey_dump(output: str, target_freq_mhz: Optional[int]) -> Dict[str, object]:
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

    active_ms = _int_value(r"channel\s+active\s+time:\s*(\d+)\s*ms")
    busy_ms = _int_value(r"channel\s+busy\s+time:\s*(\d+)\s*ms")
    noise_dbm = _int_value(r"noise:\s*(-?\d+)\s*dBm")

    d: Dict[str, object] = {}
    if active_ms and busy_ms is not None and active_ms > 0:
        d["conn_survey_busy_pct"] = (busy_ms / active_ms) * 100.0
    if noise_dbm is not None:
        d["conn_survey_noise_dbm"] = noise_dbm
    return d


def _get_connected_link_metrics(iface: str) -> Dict[str, object]:
    """Collect connected-link telemetry via `iw link` and `iw station dump`."""

    if not iface:
        return {}

    try:
        link_res = subprocess.run(
            ["iw", "dev", iface, "link"],
            capture_output=True,
            text=True,
            timeout=3,
        )
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

    freq_m = re.search(r"(?m)^\s*freq:\s*(\d+)\s*$", link_text)
    if freq_m:
        d["conn_link_freq_mhz"] = int(freq_m.group(1))

    sig_m = re.search(r"(?m)^\s*signal:\s*([\-\d.]+)\s*dBm\s*$", link_text)
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
        sta_res = subprocess.run(
            ["iw", "dev", iface, "station", "dump"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if sta_res.returncode == 0:
            sta = _parse_iw_station_dump(sta_res.stdout, str(d.get("conn_bssid", "")))
            if sta:
                d.update(sta)
    except Exception:
        pass

    try:
        survey_res = subprocess.run(
            ["iw", "dev", iface, "survey", "dump"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if survey_res.returncode == 0:
            survey = _parse_iw_survey_dump(
                survey_res.stdout, d.get("conn_link_freq_mhz")
            )
            if survey:
                d.update(survey)
    except Exception:
        pass

    return d


def enrich_with_iw(aps: List[AccessPoint]) -> None:
    """Run 'iw dev scan dump' and merge extra fields into each AccessPoint."""
    iface = _detect_wifi_iface()
    if not iface:
        return
    try:
        res = subprocess.run(
            ["iw", "dev", iface, "scan", "dump"],
            capture_output=True,
            text=True,
            timeout=6,
        )
        if res.returncode != 0:
            return
        iw_data = parse_iw_scan(res.stdout)
        conn_data = _get_connected_link_metrics(iface)
        conn_bssid = str(conn_data.get("conn_bssid", "")).lower()
        for ap in aps:
            d = iw_data.get(ap.bssid.lower())
            if not d:
                d = {}

            for attr in (
                "dbm_exact",
                "wifi_gen",
                "chan_util",
                "station_count",
                "pmf",
                "akm",
                "akm_raw",
                "wps_manufacturer",
                "rrm",
                "btm",
                "ft",
                "country",
                "iw_center_freq",
                "beacon_interval_tu",
                "dtim_period",
                "rsn_capabilities",
                "vendor_ie_ouis",
                "phy_cap_summary",
                "he_eht_features",
            ):
                if attr in d:
                    setattr(ap, attr, d[attr])

            # Prefer WPS-advertised manufacturer when OUI lookup is missing
            # or when BSSID is locally-administered (common synthetic radio MAC).
            wps_vendor = d.get("wps_manufacturer", "")
            if wps_vendor:
                use_wps = not ap.manufacturer
                try:
                    first_octet = int(ap.bssid[:2], 16)
                    if first_octet & 0x02:
                        use_wps = True
                except Exception:
                    pass
                if use_wps:
                    ap.manufacturer = wps_vendor
                    ap.manufacturer_source = "WPS (iw scan)"

            # ── Fix bandwidth=0 (nmcli doesn't populate BANDWIDTH for 6 GHz) ─
            if ap.bandwidth_mhz == 0:
                iw_bw = d.get("iw_oper_bw", 0)
                if iw_bw:
                    ap.bandwidth_mhz = iw_bw
                elif ap.iw_center_freq and ap.freq_mhz:
                    diff = abs(ap.iw_center_freq - ap.freq_mhz)
                    if diff <= 5:
                        ap.bandwidth_mhz = 20
                    elif diff <= 20:
                        ap.bandwidth_mhz = 40
                    elif diff <= 40:
                        ap.bandwidth_mhz = 80
                    elif diff <= 80:
                        ap.bandwidth_mhz = 160
                    elif diff <= 160:
                        ap.bandwidth_mhz = 320
                elif d.get("iw_cap_max_bw", 0) >= 20:
                    ap.bandwidth_mhz = d["iw_cap_max_bw"]

            # ── Compute theoretical HE rate when nmcli reports 0 Mbit/s ──
            # 6 GHz beacons have no legacy Supported-Rates IE, so nmcli
            # always returns 0.  Derive the value from the HE MCS/NSS set
            # that iw decodes from the beacon's HE Capabilities IE.
            if ap.rate_mbps == 0 and ap.bandwidth_mhz > 0:
                nss = d.get("iw_max_nss", 0)
                mcs = d.get("iw_max_mcs", 11)
                if nss > 0:
                    ap.rate_mbps = float(
                        _he_rate_mbps(ap.bandwidth_mhz, nss, mcs)
                    )
            if conn_bssid and ap.bssid.lower() == conn_bssid:
                for attr in (
                    "conn_iface",
                    "conn_link_ssid",
                    "conn_link_freq_mhz",
                    "conn_link_signal_dbm",
                    "conn_rx_bitrate",
                    "conn_tx_bitrate",
                    "conn_expected_tp",
                    "conn_signal_avg_dbm",
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
                ):
                    if attr in conn_data:
                        setattr(ap, attr, conn_data[attr])

        # ── Frequency-based wifi_gen fallback ─────────────────────────────
        # If iw scan dump missed the AP (no scan cache for 6 GHz radio),
        # infer generation from frequency — 6 GHz is always ≥ 802.11ax.
        for ap in aps:
            if not ap.wifi_gen and ap.freq_mhz >= 5925:
                ap.wifi_gen = "WiFi 6E"

        # ── LAA BSSID vendor inference from UAA sibling MACs ──────────────
        # MLO / multi-radio APs derive per-radio MACs from the same OUI base.
        # The 6 GHz radio commonly uses a locally-administered (LAA) variant of
        # the 5 GHz radio's universally-administered (UAA) MAC, sharing the
        # last 5 bytes unchanged.  If we matched a vendor for the UAA sibling,
        # apply it to the LAA counterpart.
        tail_to_vendor: Dict[str, str] = {}
        for ap in aps:
            try:
                if ap.manufacturer and not (int(ap.bssid[:2], 16) & 0x02):
                    tail_to_vendor[ap.bssid[3:]] = ap.manufacturer
            except Exception:
                pass
        for ap in aps:
            try:
                if not ap.manufacturer and (int(ap.bssid[:2], 16) & 0x02):
                    vendor = tail_to_vendor.get(ap.bssid[3:], "")
                    if vendor:
                        ap.manufacturer = vendor
                        ap.manufacturer_source = "LAA sibling OUI"
            except Exception:
                pass

    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
class WiFiScanner(QThread):
    """Background thread: periodically calls nmcli and emits fresh AP list."""

    data_ready = pyqtSignal(list)  # list[AccessPoint]
    scan_error = pyqtSignal(str)

    # How many poll cycles between active NM rescans.
    # NM rate-limits rescans to roughly one per 10 s; at the default 2 s
    # interval, every 5 cycles ≈ 10 s sits right at NM's minimum window,
    # keeping data fresh while staying within the rate limit.
    _RESCAN_EVERY = 5

    def __init__(self, interval_sec: int = 2, linger_secs: float = 30.0):
        super().__init__()
        self._interval = interval_sec
        self._linger_secs = linger_secs
        # bssid_lower → (AccessPoint, last_seen_monotonic)
        self._seen_cache: Dict[str, Tuple["AccessPoint", float]] = {}
        self._running = False

    def set_interval(self, secs: int):
        self._interval = secs

    def set_linger_secs(self, secs: float):
        """Update the linger window.  Thread-safe (single float assignment)."""
        self._linger_secs = secs

    def run(self):
        self._running = True
        _cycle = 0

        while self._running:
            # Hidden APs require two consecutive scans to reliably appear:
            # the first --rescan yes does the passive sweep + sends probe
            # requests; the second --rescan yes reads results that now include
            # probe *responses* from hidden APs that replied to the first sweep.
            # This matches observed NM behaviour: back-to-back --rescan yes
            # finds hidden APs that a single call misses.
            # On non-rescan cycles --rescan no returns cached data instantly.
            do_rescan = (_cycle % self._RESCAN_EVERY == 0 or _cycle == 2)
            cmd_timeout = 30 if do_rescan else 8

            try:
                if do_rescan:
                    # First sweep — triggers probe requests on all channels
                    subprocess.run(
                        ["nmcli", "-t", "-f", NMCLI_FIELDS, "dev", "wifi",
                         "list", "--rescan", "yes"],
                        capture_output=True,
                        text=True,
                        timeout=cmd_timeout,
                    )
                    # Second sweep — picks up probe responses from hidden APs
                    result = subprocess.run(
                        ["nmcli", "-t", "-f", NMCLI_FIELDS, "dev", "wifi",
                         "list", "--rescan", "yes"],
                        capture_output=True,
                        text=True,
                        timeout=cmd_timeout,
                    )
                else:
                    result = subprocess.run(
                        ["nmcli", "-t", "-f", NMCLI_FIELDS, "dev", "wifi",
                         "list", "--rescan", "no"],
                        capture_output=True,
                        text=True,
                        timeout=cmd_timeout,
                    )
                if result.returncode == 0:
                    aps = parse_nmcli(result.stdout)
                    enrich_with_iw(aps)  # merge iw BSS-Load / WiFi-gen / k-v-r data

                    # ── Linger merge ────────────────────────────────────────
                    now = time.monotonic()
                    fresh: set[str] = set()
                    for ap in aps:
                        key = ap.bssid.lower()
                        ap.is_lingering = False
                        self._seen_cache[key] = (ap, now)
                        fresh.add(key)

                    linger = self._linger_secs
                    if linger > 0:
                        expired: List[str] = []
                        for key, (cached_ap, last_seen) in self._seen_cache.items():
                            if key in fresh:
                                continue
                            age = now - last_seen
                            if age <= linger:
                                cached_ap.is_lingering = True
                                aps.append(cached_ap)
                            else:
                                expired.append(key)
                        for key in expired:
                            del self._seen_cache[key]
                    # ────────────────────────────────────────────────────────

                    self.data_ready.emit(aps)
                else:
                    self.scan_error.emit(result.stderr.strip())
            except FileNotFoundError:
                self.scan_error.emit("nmcli not found — is NetworkManager installed?")
                break
            except subprocess.TimeoutExpired:
                self.scan_error.emit("nmcli timed out")
            except Exception as e:
                self.scan_error.emit(str(e))

            _cycle += 1
            time.sleep(self._interval)

    def stop(self):
        self._running = False
        self.wait(2000)


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

