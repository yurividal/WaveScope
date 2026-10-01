"""Configuration-issue detection ("Issues" tab).

Pure analysis over one scan: each check returns Issue records with a
severity, the affected BSSIDs and a one-line explanation of why it matters.
Checks and thresholds are configurable (IssueSettings).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from .analysis import ap_congestion, compute_channel_stats, find_bss_color_collisions, same_radio
from .core_models import PSC_6GHZ_CHANNELS, AccessPoint

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Issue:
    severity: str  # "error" | "warning" | "info"
    check: str  # check key (see CHECKS)
    title: str
    detail: str
    bssids: List[str] = field(default_factory=list)  # lower-case
    ssid: str = ""


# key → (default severity, short description shown in Settings)
CHECKS: Dict[str, tuple] = {
    "wep": ("error", "WEP encryption"),
    "open": ("warning", "Open network (no encryption)"),
    "tkip": ("warning", "WPA1 / TKIP still enabled"),
    "six_ghz_security": ("error", "6 GHz BSS without WPA3 / OWE"),
    "sae_without_pmf": ("error", "WPA3-SAE without PMF"),
    "pmf_off": ("info", "PMF disabled on WPA2"),
    "b_rates": ("warning", "802.11b rates enabled (2.4 GHz)"),
    "wide_24": ("warning", "40 MHz channel on 2.4 GHz"),
    "overlap_24": ("warning", "Overlapping 2.4 GHz channels"),
    "high_util": ("warning", "High channel utilization (BSS Load)"),
    "congestion": ("info", "Congested channel"),
    "many_ssids": ("warning", "Many SSIDs on one radio"),
    "color_collision": ("warning", "BSS color collision"),
    "ssid_mismatch": ("warning", "Inconsistent settings across one SSID"),
    "six_ghz_discovery": ("warning", "6 GHz BSS hard to discover"),
    "dtim": ("info", "Unusual DTIM / beacon interval"),
    "hidden": ("info", "Hidden SSID"),
}


@dataclass
class IssueSettings:
    enabled: Dict[str, bool] = field(default_factory=lambda: {k: True for k in CHECKS})
    overlap_dbm: int = -80  # neighbours weaker than this are ignored (2.4 GHz overlap)
    util_pct: int = 60  # BSS Load utilization threshold
    max_ssids: int = 4  # SSIDs per radio before beacon overhead is flagged
    congestion_score: int = 70  # analysis.compute_channel_stats score


def _live(aps: Sequence[AccessPoint]) -> List[AccessPoint]:
    return [a for a in aps if not a.is_lingering]


def _radios(aps: Sequence[AccessPoint]) -> List[List[AccessPoint]]:
    """Group BSSs into physical radios (same_radio), strongest first."""
    radios: List[List[AccessPoint]] = []
    for ap in sorted(aps, key=lambda a: -a.dbm):
        for r in radios:
            if same_radio(r[0], ap):
                r.append(ap)
                break
        else:
            radios.append([ap])
    return radios


def _ssids(radio: Sequence[AccessPoint]) -> str:
    return ", ".join(dict.fromkeys(a.display_ssid for a in radio))


def detect_issues(aps: Sequence[AccessPoint], cfg: IssueSettings = None) -> List[Issue]:
    cfg = cfg or IssueSettings()
    on = lambda k: cfg.enabled.get(k, True)  # noqa: E731
    sev = lambda k: CHECKS[k][0]  # noqa: E731
    live = _live(aps)
    out: List[Issue] = []

    def add(check: str, title: str, detail: str, bss: Sequence[AccessPoint]) -> None:
        if on(check):
            out.append(Issue(sev(check), check, title, detail, [a.bssid.lower() for a in bss], bss[0].display_ssid if bss else ""))

    # ── per-BSS security / PHY checks ───────────────────────────────────────
    for ap in live:
        sec = ap.security_short
        akms = set(ap.akm_suites)
        if sec == "WEP":
            add("wep", "WEP encryption", "WEP is broken and limits clients to legacy rates; use WPA2/WPA3.", [ap])
        elif sec == "Open":
            add("open", "Open network", "No encryption. Consider OWE (Enhanced Open) or WPA2/WPA3.", [ap])
        if ap.has_wpa1_ie or "pair_tkip" in (ap.rsn_flags or "") or "pair_tkip" in (ap.wpa_flags or ""):
            add(
                "tkip", "WPA1 / TKIP enabled",
                "TKIP is deprecated and HT/VHT/HE rates are not allowed with it; clients on TKIP fall back to 54 Mbps.",
                [ap],
            )
        if ap.band == "6 GHz" and not ("WPA3" in sec or sec == "OWE"):
            add("six_ghz_security", "6 GHz without WPA3/OWE", f"6 GHz requires WPA3 or OWE (with PMF); this BSS shows {sec}.", [ap])
        if akms & {"SAE", "FT/SAE", "SAE-EXT-KEY", "FT/SAE-EXT-KEY"} and ap.pmf == "No":
            add("sae_without_pmf", "WPA3-SAE without PMF", "WPA3 requires Protected Management Frames (PMF).", [ap])
        if sec.startswith("WPA2 (") and ap.pmf == "No":
            add("pmf_off", "PMF disabled", "WPA2 with PMF capable (optional) is recommended; it protects deauth/disassoc frames.", [ap])
        if ap.band == "2.4 GHz" and ap.has_11b_rates:
            add(
                "b_rates", "802.11b rates enabled",
                f"Basic/supported rates include 1-11 Mbps (basic: {ap.basic_rates or '?'}); "
                "beacons and legacy clients then use slow DSSS/CCK airtime.",
                [ap],
            )
        if ap.band == "2.4 GHz" and ap.bandwidth_mhz >= 40:
            add("wide_24", "40 MHz on 2.4 GHz", "A 40 MHz channel covers most of the 2.4 GHz band and overlaps every neighbour.", [ap])
        util = ap.chan_util_pct
        if util is not None and util >= cfg.util_pct:
            add("high_util", f"Channel utilization {util}%", f"BSS Load reports {util}% airtime in use (threshold {cfg.util_pct}%).", [ap])
        if ap.dtim_period is not None and ap.dtim_period > 3:
            add("dtim", f"DTIM {ap.dtim_period}", "A DTIM above 3 delays broadcast/multicast for power-saving clients.", [ap])
        if ap.beacon_interval_tu is not None and ap.beacon_interval_tu != 100:
            add("dtim", f"Beacon interval {ap.beacon_interval_tu} TU", "Non-default beacon interval (100 TU is the norm).", [ap])
        if not ap.ssid and not ap.is_lingering:
            add("hidden", "Hidden SSID", "Hiding the SSID adds no security and makes clients probe for it.", [ap])

    # ── 2.4 GHz adjacent-channel overlap ────────────────────────────────────
    radios = _radios(live)
    if on("overlap_24"):
        # one issue per pair of *radios* (all SSIDs of a radio share its channel)
        strong = [r for r in radios if r[0].band == "2.4 GHz" and r[0].dbm >= cfg.overlap_dbm and r[0].channel]
        for i, ra in enumerate(strong):
            for rb in strong[i + 1:]:
                a, b = ra[0], rb[0]
                d = abs(a.channel - b.channel)
                if 1 <= d <= 4:
                    add(
                        "overlap_24", f"Overlap: ch {a.channel} / ch {b.channel}",
                        f"{_ssids(ra)} (ch {a.channel}) and {_ssids(rb)} (ch {b.channel}): 20 MHz channels "
                        f"{d * 5} MHz apart overlap partially and interfere without being able to share airtime "
                        "(use 1/6/11, or 1/5/9/13 where allowed).",
                        ra + rb,
                    )

    # ── congestion / colors ─────────────────────────────────────────────────
    if on("congestion"):
        stats = compute_channel_stats(live)
        flagged = set()
        for ap in live:
            st = ap_congestion(ap, stats)
            if st and st.score >= cfg.congestion_score and (ap.band, st.channel) not in flagged:
                flagged.add((ap.band, st.channel))
                add("congestion", f"Congested {ap.band} ch {st.channel}", st.summary() + " (heuristic).", [ap])
    if on("color_collision"):
        radio_of = {a.bssid.lower(): i for i, r in enumerate(radios) for a in r}
        seen = set()
        for b, others in find_bss_color_collisions(live).items():
            for o in others:
                ia, ib = radio_of.get(b), radio_of.get(o.bssid.lower())
                if ia is None or ib is None or ia == ib:
                    continue
                pair = (min(ia, ib), max(ia, ib))
                if pair in seen:
                    continue
                seen.add(pair)
                ra, rb = radios[pair[0]], radios[pair[1]]
                add(
                    "color_collision", f"BSS color {ra[0].bss_color} collision",
                    f"{_ssids(ra)} ({ra[0].band} ch {ra[0].channel}) and {_ssids(rb)} (ch {rb[0].channel}) "
                    "use the same BSS color on overlapping channels.",
                    ra + rb,
                )

    # ── many SSIDs per radio ────────────────────────────────────────────────
    if on("many_ssids"):
        for r in radios:
            if len(r) > cfg.max_ssids:
                add(
                    "many_ssids", f"{len(r)} SSIDs on one radio",
                    f"Each SSID sends its own beacons; more than {cfg.max_ssids} per radio costs noticeable airtime.",
                    r,
                )

    # ── consistency across the BSSIDs of one SSID ───────────────────────────
    if on("ssid_mismatch"):
        by_ssid: Dict[str, List[AccessPoint]] = defaultdict(list)
        for ap in live:
            if ap.ssid:
                by_ssid[ap.ssid].append(ap)
        for ssid, group in by_ssid.items():
            if len(group) < 2:
                continue
            for attr, what in (
                ("security_short", "security"),
                ("pmf", "PMF"),
                ("kvr_flags", "802.11k/v/r"),
                ("mobility_domain", "mobility domain (802.11r)"),
                ("country", "country code"),
            ):
                members = group
                if attr in ("security_short", "pmf"):
                    # WPA3 transition design: WPA2/WPA3 on 2.4/5 GHz, WPA3-only
                    # with PMF required on 6 GHz (mandatory there) — not a mismatch.
                    members = [a for a in group if a.band != "6 GHz"]
                if attr != "security_short":
                    # only BSSs with decoded beacon data carry these fields
                    members = [a for a in members if a.iw_seen or a.iw_restored]
                if attr == "mobility_domain" and not any(a.ft for a in members):
                    continue
                values = {getattr(a, attr) or "—" for a in members}
                if len(values) > 1:
                    add(
                        "ssid_mismatch", f"'{ssid}': {what} differs",
                        f"BSSIDs of one SSID advertise different {what}: {', '.join(sorted(values))}. "
                        "Clients roaming between them may fail or behave inconsistently.",
                        group,
                    )

    # ── 6 GHz discoverability ───────────────────────────────────────────────
    if on("six_ghz_discovery"):
        advertised = {
            str(n.get("bssid", "")).lower() for a in live if a.band != "6 GHz" for n in a.rnr_neighbors
        }
        for ap in live:
            if ap.band == "6 GHz" and ap.channel not in PSC_6GHZ_CHANNELS and ap.bssid.lower() not in advertised:
                add(
                    "six_ghz_discovery", "6 GHz off-PSC, not advertised",
                    f"Primary ch {ap.channel} is not a Preferred Scanning Channel and no visible 2.4/5 GHz BSS "
                    "advertises it in a Reduced Neighbor Report, so many clients will not find it.",
                    [ap],
                )

    out.sort(key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.check, i.ssid))
    return out
