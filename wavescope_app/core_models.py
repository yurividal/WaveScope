"""Domain models.

Contains primary data structures representing access points and
related computed properties.
"""

from .core_vendor import *


@dataclass
class AccessPoint:
    # ── Required fields (nmcli) ─────────────────────────────────────────────
    ssid: str
    bssid: str
    mode: str
    channel: int
    freq_mhz: int
    rate_mbps: float
    signal: int  # 0-100 (nmcli)
    security: str
    wpa_flags: str
    rsn_flags: str
    bandwidth_mhz: int
    in_use: bool
    # ── Optional enrichment fields (from iw dev scan dump) ──────────────────
    dbm_exact: Optional[float] = None  # real dBm from iw, more precise
    wifi_gen: str = ""  # "WiFi 4" / "WiFi 5" / "WiFi 6" / "WiFi 6E" / "WiFi 7"
    chan_util: Optional[int] = None  # BSS Load channel utilization 0-255
    station_count: Optional[int] = None  # BSS Load station count
    pmf: str = ""  # "No" / "Optional" / "Required"
    akm: str = ""  # "WPA2-PSK" / "WPA3-SAE" / "Enterprise" / …
    akm_raw: str = ""  # raw AKM string from iw (Authentication suites)
    wps_manufacturer: str = ""  # Manufacturer from WPS IE (if advertised)
    rrm: bool = False  # 802.11k Radio Resource Measurement
    btm: bool = False  # 802.11v BSS Transition Management
    ft: bool = False  # 802.11r Fast Transition
    country: str = ""  # Country code from beacon (e.g. "DE")
    iw_center_freq: Optional[int] = None  # bonded-block center MHz from iw (all bands)
    beacon_interval_tu: Optional[int] = None  # Beacon interval in TU
    dtim_period: Optional[int] = None  # DTIM period from beacon TIM IE
    rsn_capabilities: str = ""  # Parsed RSN capabilities text
    vendor_ie_ouis: str = ""  # Vendor-specific IE OUIs seen in beacon
    phy_cap_summary: str = ""  # HT/VHT/HE/EHT families + max width summary
    he_eht_features: str = ""  # HE/EHT extras (BSS color, TWT, spatial reuse)
    # ── Connected-session telemetry (iw link / iw station dump) ────────────
    conn_iface: str = ""
    conn_link_ssid: str = ""
    conn_link_freq_mhz: Optional[int] = None
    conn_link_signal_dbm: Optional[float] = None
    conn_rx_bitrate: str = ""
    conn_tx_bitrate: str = ""
    conn_expected_tp: str = ""
    conn_signal_avg_dbm: Optional[int] = None
    conn_tx_retries: Optional[int] = None
    conn_tx_failed: Optional[int] = None
    conn_inactive_ms: Optional[int] = None
    conn_connected_time_s: Optional[int] = None
    conn_tx_packets: Optional[int] = None
    conn_tx_bytes: Optional[int] = None
    conn_rx_packets: Optional[int] = None
    conn_rx_bytes: Optional[int] = None
    conn_rx_drop_misc: Optional[int] = None
    conn_rx_phy: str = ""
    conn_tx_phy: str = ""
    conn_tx_retry_rate_pct: Optional[float] = None
    conn_tx_fail_rate_pct: Optional[float] = None
    conn_survey_busy_pct: Optional[float] = None
    conn_survey_noise_dbm: Optional[int] = None
    # ── Linger state (set by WiFiScanner, never from nmcli) ─────────────────
    is_lingering: bool = False  # True while AP is in the linger grace period
    # ── Computed in __post_init__ ────────────────────────────────────────────
    band: str = field(init=False)
    manufacturer: str = field(init=False)
    manufacturer_source: str = field(init=False)

    def __post_init__(self):
        self.band = freq_to_band(self.freq_mhz)
        self.manufacturer = get_manufacturer(self.bssid)
        self.manufacturer_source = "OUI database" if self.manufacturer else "Unknown"

    @property
    def dbm(self) -> int:
        """Prefer exact iw dBm; fall back to nmcli signal approximation."""
        if self.dbm_exact is not None:
            return int(round(self.dbm_exact))
        return signal_to_dbm(self.signal)

    @property
    def chan_util_pct(self) -> Optional[int]:
        """Channel utilization as 0-100 percent (None if unavailable)."""
        if self.chan_util is not None:
            return int(round(self.chan_util / 255 * 100))
        return None

    @property
    def kvr_flags(self) -> str:
        """Compact 802.11k/v/r roaming-feature badge, e.g. 'k v r' or ''."""
        flags = []
        if self.rrm:
            flags.append("k")
        if self.btm:
            flags.append("v")
        if self.ft:
            flags.append("r")
        return " ".join(flags) if flags else ""

    @property
    def protocol(self) -> str:
        """IEEE 802.11 amendment letter(s) — e.g. 'AX', 'AC', 'N', 'A/B/G'."""
        _GEN_PROTO = {
            "WiFi 7": "BE  (802.11be)",
            "WiFi 6E": "AX  (802.11ax)",
            "WiFi 6": "AX  (802.11ax)",
            "WiFi 5": "AC  (802.11ac)",
            "WiFi 4": "N   (802.11n)",
        }
        if self.wifi_gen in _GEN_PROTO:
            return _GEN_PROTO[self.wifi_gen]
        # Legacy — infer from band
        if self.freq_mhz >= 5000:
            return "A   (802.11a)"
        return "B/G (802.11b/g)"

    @property
    def phy_mode(self) -> str:
        """Compact 802.11 PHY mode for table display (e.g. B/G, A, A/N, AX)."""
        if self.wifi_gen == "WiFi 7":
            return "BE"
        if self.wifi_gen in ("WiFi 6", "WiFi 6E"):
            return "AX"
        if self.wifi_gen == "WiFi 5":
            return "AC"
        if self.wifi_gen == "WiFi 4":
            return "A/N" if self.freq_mhz >= 5000 else "B/G/N"
        return "A" if self.freq_mhz >= 5000 else "B/G"

    @property
    def display_ssid(self) -> str:
        return self.ssid if self.ssid else f"<hidden> ({self.bssid})"

    @property
    def security_short(self) -> str:
        """Compact canonical security label for table/dashboard display."""

        def _nz(v: str) -> str:
            return (v or "").strip()

        sec = _nz(self.security).upper()
        wpa = _nz(self.wpa_flags).upper()
        rsn = _nz(self.rsn_flags).upper()
        akm = _nz(getattr(self, "akm_raw", "") or self.akm).upper()

        has_wpa_ie = wpa not in ("", "--", "(NONE)")
        has_rsn_ie = rsn not in ("", "--", "(NONE)")
        has_wep = "WEP" in sec
        has_sae = "SAE" in akm
        has_psk = "PSK" in akm or "PSK" in sec or "PSK" in wpa or "PSK" in rsn
        has_eap = (
            "EAP" in akm
            or "802.1X" in akm
            or "8021X" in akm
            or "ENTERPRISE" in akm
            or "EAP" in sec
        )
        has_owe = "OWE" in akm or "OWE" in sec

        if not sec and not has_wpa_ie and not has_rsn_ie and not akm:
            return "Open"
        if has_wep:
            return "WEP"
        if has_owe:
            return "OWE"

        if has_sae and has_psk:
            return "WPA2/WPA3 (PSK/SAE)"
        if has_sae:
            return "WPA3 (SAE)"

        if has_eap:
            if has_wpa_ie and has_rsn_ie:
                return "WPA/WPA2 (802.1X)"
            if has_rsn_ie:
                return "WPA2 (802.1X)"
            return "Enterprise (802.1X)"

        if has_wpa_ie and has_rsn_ie:
            return "WPA/WPA2 (PSK)"
        if has_rsn_ie:
            return "WPA2 (PSK)"
        if has_wpa_ie:
            return "WPA (PSK)"

        if "WPA3" in sec and "WPA2" in sec:
            return "WPA2/WPA3 (PSK/SAE)"
        if "WPA3" in sec:
            return "WPA3"
        if "WPA2" in sec and "WPA" in sec:
            return "WPA/WPA2"
        if "WPA2" in sec:
            return "WPA2"
        if "WPA" in sec:
            return "WPA"
        return "Open"

    @property
    def security_tooltip(self) -> str:
        """Detailed security info for table tooltip."""

        def _nz(v: str) -> str:
            s = (v or "").strip()
            return s if s else "—"

        return (
            f"Security: {_nz(self.security_short)}\n"
            f"nmcli SECURITY: {_nz(self.security)}\n"
            f"WPA flags: {_nz(self.wpa_flags)}\n"
            f"RSN flags: {_nz(self.rsn_flags)}\n"
            f"AKM (iw): {_nz(getattr(self, 'akm_raw', '') or self.akm)}\n"
            f"PMF: {_nz(self.pmf)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# nmcli Scanner Thread
# ─────────────────────────────────────────────────────────────────────────────

NMCLI_FIELDS = "IN-USE,SSID,BSSID,MODE,CHAN,FREQ,RATE,SIGNAL,SECURITY,WPA-FLAGS,RSN-FLAGS,BANDWIDTH"
