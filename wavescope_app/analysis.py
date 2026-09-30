"""Cross-AP RF analysis.

Derives per-channel and per-BSS insights that need the whole scan result:
channel congestion, HE BSS-color collisions and roaming candidates.
Everything here is pure computation on AccessPoint lists (no Qt widgets),
so it can be unit-tested without a display.
"""

from .core_models import *

# Signal above which an overlapping BSS is considered a strong interferer.
# -82 dBm is the 802.11 minimum-sensitivity / CCA preamble-detect threshold
# for a 20 MHz OFDM PPDU; BSSs above it defer each other's transmissions.
CCA_PD_THRESHOLD_DBM = -82


def ap_block(ap: AccessPoint) -> Tuple[float, float]:
    """(lo_MHz, hi_MHz) of the spectrum a BSS occupies."""
    center = get_ap_draw_center(ap)
    half = max(ap.bandwidth_mhz, 20) / 2.0
    return center - half, center + half


def _overlaps(a: Tuple[float, float], b: Tuple[float, float]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


@dataclass
class ChannelStats:
    """Occupancy summary for one 20 MHz channel."""

    band: str
    channel: int
    bss_count: int = 0  # BSSs whose block covers this channel
    strong_count: int = 0  # …of which above the CCA threshold
    primary_count: int = 0  # BSSs using it as their primary channel
    max_util_pct: Optional[int] = None  # highest BSS Load utilization reported
    score: int = 0  # 0-100 congestion heuristic (see compute_channel_stats)

    def summary(self) -> str:
        util = f", max reported utilization {self.max_util_pct}%" if self.max_util_pct is not None else ""
        return (
            f"Congestion {self.score}/100 — {self.bss_count} BSS overlap "
            f"({self.strong_count} above {CCA_PD_THRESHOLD_DBM} dBm, "
            f"{self.primary_count} primary here){util}"
        )


def compute_channel_stats(aps: List[AccessPoint]) -> Dict[Tuple[str, int], ChannelStats]:
    """Per-20 MHz-channel congestion for every band present in *aps*.

    Heuristic score (0-100), shown to the user as such:
      * occupancy term = 20 points per strong overlapping BSS (≥ CCA
        threshold) + 5 per weaker one, capped at 100;
      * when any overlapping BSS advertises BSS Load, the score is the mean
        of the occupancy term and the highest reported utilization, because
        airtime utilization is the direct measure of contention.
    """
    stats: Dict[Tuple[str, int], ChannelStats] = {}
    live = [a for a in aps if not a.is_lingering and a.band in (BAND_24, BAND_5, BAND_6)]
    tables = {BAND_24: CH24, BAND_5: CH5, BAND_6: CH6}
    for band in {a.band for a in live}:
        band_aps = [(a, ap_block(a)) for a in live if a.band == band]
        for ch, f in tables[band].items():
            chan_block = (f - 10.0, f + 10.0)
            st = ChannelStats(band=band, channel=ch)
            for ap, blk in band_aps:
                if not _overlaps(chan_block, blk):
                    continue
                st.bss_count += 1
                if ap.dbm >= CCA_PD_THRESHOLD_DBM:
                    st.strong_count += 1
                if ap.channel == ch:
                    st.primary_count += 1
                util = ap.chan_util_pct
                if util is not None:
                    st.max_util_pct = util if st.max_util_pct is None else max(st.max_util_pct, util)
            if st.bss_count == 0:
                continue
            occupancy = min(100, 20 * st.strong_count + 5 * (st.bss_count - st.strong_count))
            st.score = (
                int(round((occupancy + st.max_util_pct) / 2)) if st.max_util_pct is not None else occupancy
            )
            stats[(band, ch)] = st
    return stats


def ap_congestion(ap: AccessPoint, stats: Dict[Tuple[str, int], ChannelStats]) -> Optional[ChannelStats]:
    """Worst ChannelStats across the 20 MHz channels an AP occupies."""
    _center, chans = bonded_block(ap.band, ap.channel, ap.bandwidth_mhz, ap.iw_center_freq)
    worst: Optional[ChannelStats] = None
    for ch in chans or [ap.channel]:
        st = stats.get((ap.band, ch))
        if st and (worst is None or st.score > worst.score):
            worst = st
    return worst


def find_bss_color_collisions(aps: List[AccessPoint]) -> Dict[str, List[AccessPoint]]:
    """Map bssid → other APs using the same HE BSS color on overlapping spectrum.

    BSS coloring (802.11ax 26.17) lets a STA ignore inter-BSS frames by
    color; two *different* APs on overlapping channels with the same color
    defeat that and should be re-colored.  BSSs of the same physical AP
    (same AP group / MLD) intentionally share a color and are skipped, as
    are BSSs with coloring disabled.
    """
    colored = [
        (a, ap_block(a), ap_group_key_for(a))
        for a in aps
        if a.bss_color is not None and not a.bss_color_disabled and not a.is_lingering
    ]
    out: Dict[str, List[AccessPoint]] = {}
    for i, (a, blk_a, grp_a) in enumerate(colored):
        for b, blk_b, grp_b in colored[i + 1:]:
            if a.bss_color != b.bss_color or a.band != b.band or grp_a == grp_b:
                continue
            if not _overlaps(blk_a, blk_b):
                continue
            out.setdefault(a.bssid.lower(), []).append(b)
            out.setdefault(b.bssid.lower(), []).append(a)
    return out


def roam_candidates(connected: AccessPoint, aps: List[AccessPoint]) -> List[AccessPoint]:
    """Other BSSIDs of the connected SSID with the same security, strongest first."""
    if not connected.ssid:
        return []
    return sorted(
        (
            a
            for a in aps
            if a.ssid == connected.ssid
            and a.bssid.lower() != connected.bssid.lower()
            and a.security_short == connected.security_short
            and not a.is_lingering
        ),
        key=lambda a: -a.dbm,
    )


def mobility_domain_members(ap: AccessPoint, aps: List[AccessPoint]) -> int:
    """How many visible BSSIDs share this AP's 802.11r Mobility Domain."""
    if not ap.mobility_domain:
        return 0
    return sum(1 for a in aps if a.mobility_domain == ap.mobility_domain and a.ssid == ap.ssid)
