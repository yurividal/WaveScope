"""Field registry: every per-BSS value WaveScope can show, export or compare.

One definition per field — key, label, group, formatter and (optionally) a
numeric sort key — shared by the table's extra columns, CSV export and the
Compare view, so the three never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .core_models import (
    AccessPoint,
    get_ap_channel_span,
    get_ap_draw_center,
    punctured_subchannels,
)


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str
    fmt: Callable[[AccessPoint], str]
    sort: Optional[Callable[[AccessPoint], float]] = None  # numeric sort key
    table: bool = False  # offered as an extra table column


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, (tuple, list)):
        return " ".join(str(x) for x in v)
    return str(v)


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("-inf")


def _power(ap: AccessPoint) -> str:
    pwr, src = ap.power_level
    return f"{pwr:g} dBm ({src})" if pwr is not None else ""


def _punct(ap: AccessPoint) -> str:
    subs = punctured_subchannels(get_ap_draw_center(ap), ap.bandwidth_mhz, ap.punct_bitmap)
    return ", ".join(f"{int(lo)}–{int(hi)}" for lo, hi in subs)


def _rnr(ap: AccessPoint) -> str:
    return "; ".join(
        f"op{n.get('op_class')} ch{n.get('channel')} {n.get('bssid', '?')}" for n in ap.rnr_neighbors
    )


FIELDS: List[Field] = [
    # ── Identity ───────────────────────────────────────────────────────────
    Field("ssid", "SSID", "Identity", lambda a: a.display_ssid),
    Field("bssid", "BSSID", "Identity", lambda a: a.bssid),
    Field("label", "Label", "Identity", lambda a: a.label, table=True),
    Field("manufacturer", "Manufacturer", "Identity", lambda a: a.manufacturer),
    Field("manufacturer_source", "Manufacturer source", "Identity", lambda a: a.manufacturer_source),
    Field("ap_name", "AP name", "Identity", lambda a: a.ap_name),
    Field("wps_manufacturer", "WPS manufacturer", "Identity", lambda a: a.wps_manufacturer),
    Field("mld_mac", "MLD MAC", "Identity", lambda a: a.mld_mac, table=True),
    Field("iface", "Interface", "Identity", lambda a: a.iw_iface or a.nm_device, table=True),
    Field("in_use", "Connected", "Identity", lambda a: _s(a.in_use)),
    # ── RF / channel ───────────────────────────────────────────────────────
    Field("band", "Band", "RF", lambda a: a.band),
    Field("channel", "Channel", "RF", lambda a: _s(a.channel), lambda a: _num(a.channel)),
    Field("freq", "Primary frequency (MHz)", "RF", lambda a: _s(a.freq_mhz), lambda a: _num(a.freq_mhz)),
    Field("width", "Width (MHz)", "RF", lambda a: _s(a.bandwidth_mhz), lambda a: _num(a.bandwidth_mhz)),
    Field("span", "Channel span", "RF", get_ap_channel_span),
    Field(
        "center", "Block center (MHz)", "RF",
        lambda a: f"{get_ap_draw_center(a):.0f}", lambda a: get_ap_draw_center(a), table=True,
    ),
    Field("psc", "6 GHz PSC", "RF", lambda a: _s(a.is_psc) if a.band == "6 GHz" else ""),
    Field("dfs", "DFS channel", "RF", lambda a: _s(a.is_dfs) if a.band == "5 GHz" else ""),
    Field("signal", "Signal (%)", "RF", lambda a: _s(a.signal), lambda a: _num(a.signal)),
    Field("dbm", "RSSI (dBm)", "RF", lambda a: _s(a.dbm), lambda a: _num(a.dbm)),
    Field(
        "dbm_source", "RSSI source", "RF",
        lambda a: "iw (exact)" if a.dbm_exact is not None else "nmcli % (estimate)",
    ),
    Field("country", "Country", "RF", lambda a: a.country),
    Field("country_env", "Country environment", "RF", lambda a: a.country_env),
    Field("country_power", "Country power limits", "RF", lambda a: a.country_power),
    Field("power", "TX power (source)", "RF", _power),
    Field("power_constraint", "Power constraint (dB)", "RF", lambda a: _s(a.power_constraint_db)),
    Field("tpe", "Transmit power envelope", "RF", lambda a: a.tpe_summary),
    Field("ap_power_6g", "6 GHz AP power type", "RF", lambda a: a.he_6ghz_ap_type, table=True),
    Field("chan_util", "Channel utilization (%)", "RF", lambda a: _s(a.chan_util_pct), lambda a: _num(a.chan_util_pct)),
    Field("clients", "Station count", "RF", lambda a: _s(a.station_count), lambda a: _num(a.station_count)),
    # ── PHY ────────────────────────────────────────────────────────────────
    Field("wifi_gen", "Wi-Fi generation", "PHY", lambda a: ("≥" if a.gen_inferred else "") + a.wifi_gen),
    Field("phy_mode", "802.11 PHY", "PHY", lambda a: a.phy_mode),
    Field("max_rate", "Max PHY rate (Mbps)", "PHY", lambda a: _s(int(a.rate_mbps)), lambda a: _num(a.rate_mbps)),
    Field("phy_caps", "PHY capabilities", "PHY", lambda a: a.phy_cap_summary, table=True),
    Field("he_features", "HE/EHT features", "PHY", lambda a: a.he_eht_features),
    Field(
        "bss_color", "BSS color", "PHY",
        lambda a: _s(a.bss_color) + (" (disabled)" if a.bss_color_disabled else "") if a.bss_color is not None else "",
        lambda a: _num(a.bss_color), table=True,
    ),
    Field("punct", "Punctured subchannels (MHz)", "PHY", _punct),
    Field("basic_rates", "Basic rates (Mbps)", "PHY", lambda a: a.basic_rates, table=True),
    Field("b_rates", "802.11b rates enabled", "PHY", lambda a: _s(a.has_11b_rates), table=True),
    # ── Security ───────────────────────────────────────────────────────────
    Field("security", "Security", "Security", lambda a: a.security_short),
    Field("security_nm", "Security (nmcli tokens)", "Security", lambda a: a.security),
    Field("akm", "AKM suites", "Security", lambda a: _s(a.akm_suites) or a.akm_raw, table=True),
    Field("pmf", "PMF (802.11w)", "Security", lambda a: a.pmf, table=True),
    Field("group_mgmt", "Group mgmt cipher", "Security", lambda a: a.group_mgmt_cipher, table=True),
    Field("wpa_flags", "WPA flags", "Security", lambda a: a.wpa_flags),
    Field("rsn_flags", "RSN flags", "Security", lambda a: a.rsn_flags),
    Field("rsn_caps", "RSN capabilities", "Security", lambda a: a.rsn_capabilities),
    Field("rsnx", "RSNX capabilities", "Security", lambda a: a.rsnx_caps, table=True),
    Field("rsn_override", "RSN override AKMs", "Security", lambda a: a.rsn_override_akm),
    Field("owe_pair", "OWE transition pair", "Security", lambda a: a.owe_transition_bssid),
    # ── Roaming / management ──────────────────────────────────────────────
    Field("kvr", "802.11k/v/r", "Roaming", lambda a: a.kvr_flags),
    Field("mobility_domain", "Mobility domain (MDID)", "Roaming", lambda a: a.mobility_domain, table=True),
    Field("ft_over_ds", "FT over DS", "Roaming", lambda a: _s(a.ft_over_ds)),
    Field(
        "beacon_interval", "Beacon interval (TU)", "Roaming",
        lambda a: _s(a.beacon_interval_tu), lambda a: _num(a.beacon_interval_tu), table=True,
    ),
    Field("dtim", "DTIM period", "Roaming", lambda a: _s(a.dtim_period), lambda a: _num(a.dtim_period), table=True),
    Field("rnr", "Reduced neighbor report", "Roaming", _rnr),
    Field("vendor_ies", "Vendor IE OUIs", "Roaming", lambda a: a.vendor_ie_ouis),
    Field(
        "last_seen", "Last seen (s)", "Roaming",
        lambda a: f"{a.last_seen_ms / 1000:.1f}" if a.last_seen_ms is not None else "",
        lambda a: _num(a.last_seen_ms), table=True,
    ),
]

FIELD_BY_KEY: Dict[str, Field] = {f.key: f for f in FIELDS}
TABLE_EXTRA_FIELDS: List[Field] = [f for f in FIELDS if f.table]
