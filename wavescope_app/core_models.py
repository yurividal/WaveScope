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
    ap_name: str = ""  # Cisco AP system name from proprietary IE 133 (if advertised)
    cisco_tx_power_dbm: Optional[int] = None  # Cisco beacon radio power from IE 150
    ruckus_tx_power_dbm: Optional[float] = None  # Ruckus TX power (half-dBm units, OUI 00:13:92)
    tpc_tx_power_dbm: Optional[int] = None  # 802.11h TPC Report IE TX power (dBm)
    # ── Extended iw enrichment ──────────────────────────────────────────────
    nm_device: str = ""  # NetworkManager device that reported this BSS
    iw_seen: bool = False  # True when iw decoded this BSS on this cycle
    iw_iface: str = ""  # interface whose iw scan cache provided the data
    akm_suites: Tuple[str, ...] = ()  # normalised AKM tokens ("PSK", "SAE", "802.1X/SHA-256", …)
    has_wpa1_ie: bool = False  # legacy WPA (vendor) IE present
    has_rsn_ie: bool = False  # RSN IE present
    group_mgmt_cipher: str = ""  # BIP cipher (PMF) from RSN IE
    rsn_override_akm: str = ""  # AKMs from Wi-Fi Alliance RSN Element Override
    rsnx_caps: str = ""  # RSNX capabilities (SAE H2E, SAE-PK, …)
    mobility_domain: str = ""  # 802.11r Mobility Domain ID (octet string, hex)
    ft_over_ds: Optional[bool] = None  # FT over-the-DS supported
    country_env: str = ""  # Country IE environment (Indoor/Outdoor/…)
    country_power: str = ""  # Country IE per-channel max TX power summary
    iw_80p80: bool = False  # BSS uses non-contiguous 80+80 MHz
    bss_color: Optional[int] = None  # HE BSS color (1-63)
    bss_color_disabled: bool = False
    he_6ghz_ap_type: str = ""  # 6 GHz AP power type (LPI / SP / VLP …)
    punct_bitmap: int = 0  # EHT disabled-subchannel (puncturing) bitmap
    mld_mac: str = ""  # Wi-Fi 7 MLD MAC address (Multi-Link element)
    owe_transition_bssid: str = ""  # OWE transition twin BSSID
    owe_transition_ssid: str = ""  # OWE transition twin SSID
    rnr_neighbors: Tuple[Dict[str, object], ...] = ()  # Reduced Neighbor Report entries
    vht_24_proprietary: bool = False  # vendor VHT IE on 2.4 GHz (TurboQAM)
    power_constraint_db: Optional[int] = None  # 802.11h Power Constraint (dB)
    tpe_summary: str = ""  # Transmit Power Envelope summary
    basic_rates: str = ""  # basic (mandatory) legacy rates in Mbps
    has_11b_rates: Optional[bool] = None  # 802.11b DSSS/CCK rates enabled
    last_seen_ms: Optional[int] = None  # iw "last seen … ms ago"
    radio_params_from: str = ""  # sibling BSSID whose radio-level iw data was inherited
    gen_inferred: bool = False  # wifi_gen guessed from the band (no beacon data)
    iw_restored: bool = False  # iw fields restored from the GUI's miss-cache this cycle
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
    conn_signal_chains: str = ""  # per-antenna-chain RSSI, e.g. "-47, -46"
    conn_snr_db: Optional[float] = None  # signal − noise floor
    # ── Linger state (set by WiFiScanner, never from nmcli) ─────────────────
    is_lingering: bool = False  # True while AP is in the linger grace period
    # ── Computed in __post_init__ ────────────────────────────────────────────
    manufacturer: str = field(init=False)
    manufacturer_source: str = field(init=False)

    def __post_init__(self):
        self.manufacturer, self.manufacturer_source = get_manufacturer_with_source(self.bssid)

    @property
    def band(self) -> str:
        """Band derived from the current frequency (always in sync)."""
        return freq_to_band(self.freq_mhz)

    @property
    def is_psc(self) -> bool:
        """True for a 6 GHz Preferred Scanning Channel."""
        return self.band == BAND_6 and self.channel in PSC_6GHZ_CHANNELS

    @property
    def is_dfs(self) -> bool:
        return self.band == BAND_5 and self.channel in DFS_5GHZ_CHANNELS

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
        # No iw data: a > 20 MHz channel still proves HT (40) or VHT+ (80+).
        if self.bandwidth_mhz >= 80:
            return "≥AC"
        if self.bandwidth_mhz == 40:
            return "≥N"
        return "A" if self.freq_mhz >= 5000 else "B/G"

    @property
    def display_ssid(self) -> str:
        return self.ssid if self.ssid else f"<hidden> ({self.bssid})"

    @property
    def security_short(self) -> str:
        """Canonical security label for table/dashboard display.

        AKMs come from iw's decoded RSN IE when available and otherwise from
        nmcli's RSN-FLAGS tokens (psk, 802.1X, sae, owe,
        wpa-eap-suite-b-192 — see nmcli devices.c ap_wpa_rsn_flags_to_string)
        and SECURITY tokens (WPA1, WPA2, WPA3, OWE, OWE-TM, 802.1X).
        WPA3 mode naming follows the Wi-Fi Alliance WPA3 specification:
          Personal:   SAE only → WPA3; PSK+SAE → WPA2/WPA3 transition
          Enterprise: 802.1X-SHA256 with PMF required → WPA3;
                      with PMF optional → WPA2/WPA3; Suite-B-192 → WPA3 192-bit
        """
        sec_tokens = set((self.security or "").upper().split())
        rsn_tokens = set((self.rsn_flags or "").lower().split())
        wpa_tokens = set((self.wpa_flags or "").lower().split())
        akms = set(self.akm_suites)
        if not akms:
            # nmcli fallback (iw missed this BSS).  nmcli cannot distinguish
            # 802.1X from 802.1X-SHA256, so Enterprise shows as WPA2 here.
            if "psk" in rsn_tokens:
                akms.add("PSK")
            if "sae" in rsn_tokens:
                akms.add("SAE")
            if "802.1x" in rsn_tokens:
                akms.add("802.1X")
            if "wpa-eap-suite-b-192" in rsn_tokens:
                akms.add("802.1X/SUITE-B-192")
            if "owe" in rsn_tokens:
                akms.add("OWE")

        has_rsn = self.has_rsn_ie or bool(rsn_tokens - {"(none)", "--"}) or bool(
            sec_tokens & {"WPA2", "WPA3"}
        )
        has_wpa1 = self.has_wpa1_ie or bool(wpa_tokens - {"(none)", "--"}) or "WPA1" in sec_tokens

        if "WEP" in sec_tokens:
            return "WEP"
        if "OWE" in akms or "OWE" in sec_tokens:
            return "OWE"
        if not has_rsn and not has_wpa1:
            if "OWE-TM" in sec_tokens or self.owe_transition_bssid:
                return "Open (OWE transition)"
            return "Open"

        personal_psk = bool(akms & {"PSK", "FT/PSK", "PSK/SHA-256", "PSK/SHA-384", "FT/PSK/SHA-384"})
        personal_sae = bool(akms & {"SAE", "FT/SAE", "SAE-EXT-KEY", "FT/SAE-EXT-KEY"})
        ent_192 = bool(akms & {"802.1X/SUITE-B-192", "802.1X/SUITE-B", "FT/802.1X/SHA-384"})
        ent_sha256 = "802.1X/SHA-256" in akms
        ent_plain = bool(akms & {"802.1X", "FT/802.1X", "FILS/SHA-256", "FILS/SHA-384"})

        if ent_192:
            return "WPA3 (802.1X-192)"
        if ent_sha256 or ent_plain:
            if ent_sha256 and self.pmf == "Required":
                return "WPA3 (802.1X)"
            if ent_sha256:
                return "WPA2/WPA3 (802.1X)"
            return "WPA/WPA2 (802.1X)" if has_wpa1 else "WPA2 (802.1X)"
        if personal_sae and personal_psk:
            return "WPA2/WPA3 (PSK/SAE)"
        if personal_sae:
            return "WPA3 (SAE)"
        if personal_psk:
            if has_wpa1 and has_rsn:
                return "WPA/WPA2 (PSK)"
            return "WPA2 (PSK)" if has_rsn else "WPA (PSK)"

        # AKM unknown: fall back to nmcli's SECURITY summary.
        if "WPA3" in sec_tokens and "WPA2" in sec_tokens:
            return "WPA2/WPA3"
        if "WPA3" in sec_tokens:
            return "WPA3"
        if "WPA2" in sec_tokens and "WPA1" in sec_tokens:
            return "WPA/WPA2"
        if "WPA2" in sec_tokens:
            return "WPA2"
        if "WPA1" in sec_tokens:
            return "WPA"
        return "Unknown"

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
            + (f"\nRSN override AKM: {self.rsn_override_akm}" if self.rsn_override_akm else "")
            + (f"\nRSNX: {self.rsnx_caps}" if self.rsnx_caps else "")
        )

    @property
    def power_level(self) -> Tuple[Optional[float], str]:
        """(TX power in dBm, source) from the most specific IE available."""
        if self.cisco_tx_power_dbm is not None:
            return float(self.cisco_tx_power_dbm), "Cisco IE 150"
        if self.ruckus_tx_power_dbm is not None:
            return float(self.ruckus_tx_power_dbm), "Ruckus vendor IE"
        if self.tpc_tx_power_dbm is not None:
            return float(self.tpc_tx_power_dbm), "802.11h TPC Report"
        return None, ""


# ─────────────────────────────────────────────────────────────────────────────
# nmcli Scanner Thread
# ─────────────────────────────────────────────────────────────────────────────

# DEVICE is last so older column positions stay stable; it lets duplicate
# BSS entries from multiple Wi-Fi adapters be merged.
NMCLI_FIELDS = "IN-USE,SSID,BSSID,MODE,CHAN,FREQ,RATE,SIGNAL,SECURITY,WPA-FLAGS,RSN-FLAGS,BANDWIDTH,DEVICE"
