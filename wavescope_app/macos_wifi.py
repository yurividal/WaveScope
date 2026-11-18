"""Native macOS scanning through the public CoreWLAN framework.

PyObjC is imported only when this backend is selected.  CoreWLAN scans block
until the OS finishes, so callers must use a worker thread and keep it alive
until the native call returns.  Location authorization is requested separately
on the GUI thread; this module only checks it.

API reference: https://developer.apple.com/documentation/corewlan/cwnetwork
IE layouts: IEEE 802.11-2020 section 9.4.2; hostap src/common/ieee802_11_defs.h.
Fields not supplied by CoreWLAN or decoded from an actual IE stay unknown.
"""

from __future__ import annotations

import importlib
import math
import re
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from threading import Event
    from .core_models import AccessPoint

LOCATION_HELP = (
    "Allow WaveScope in System Settings > Privacy & Security > Location Services "
    "and enable Location Services. Use a properly signed WaveScope.app; macOS "
    "can withhold Wi-Fi identities from unsigned apps or a Python interpreter."
)


def _load_frameworks():
    return tuple(importlib.import_module(name) for name in ("objc", "CoreWLAN", "CoreLocation"))


def corewlan_available() -> bool:
    """Whether the optional native bridge can load on this platform."""
    if sys.platform != "darwin":
        return False
    try:
        _load_frameworks()
    except (ImportError, OSError, RuntimeError):
        return False
    return True


def _value(obj, selector, default=None):
    method = getattr(obj, selector, None)
    return method() if method is not None else default


def _supports(network, framework, selector, constant):
    value = getattr(framework, constant, None)
    method = getattr(network, selector, None)
    if value is None or method is None:
        return False
    # New PyObjC wheels can know enums that an older OS does not support.
    try:
        return bool(method(value))
    except (ValueError, TypeError):
        return False


def _signal(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    # CoreWLAN returns 0 for unavailable link metrics.
    return value if math.isfinite(value) and -200 < value < 0 else None


def _bssid(value):
    value = str(value or "").lower()
    if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", value):
        return ""
    if value in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
        return ""
    return value


def _channel(channel, framework):
    from .core_base import chan_index_to_freq

    if channel is None:
        return 0, 0, 0
    number = int(_value(channel, "channelNumber", 0))
    raw_band = _value(channel, "channelBand")
    band = ""
    for constant, label in (("kCWChannelBand2GHz", "2.4 GHz"),
                            ("kCWChannelBand5GHz", "5 GHz"),
                            ("kCWChannelBand6GHz", "6 GHz")):
        enum = getattr(framework, constant, None)
        if enum is not None and enum == raw_band:
            band = label
            break
    raw_width = _value(channel, "channelWidth")
    width = next((mhz for mhz in (20, 40, 80, 160)
                  if getattr(framework, f"kCWChannelWidth{mhz}MHz", None) is not None
                  and raw_width == getattr(framework, f"kCWChannelWidth{mhz}MHz")), 0)
    return number, chan_index_to_freq(number, band), width


def _native_security(network, framework):
    """CoreWLAN classifications, without guessing missing RSN capabilities."""
    supports = lambda name: _supports(network, framework, "supportsSecurity_", "kCWSecurity" + name)
    tokens, akms = [], []
    if supports("WEP") or supports("DynamicWEP"):
        return "WEP", ()
    if supports("WPAPersonal") or supports("WPAEnterprise") or supports("WPAPersonalMixed") or supports("WPAEnterpriseMixed"):
        tokens.append("WPA1")
    if supports("WPA2Personal") or supports("WPAPersonalMixed") or supports("WPA3Transition"):
        tokens.append("WPA2")
        akms.append("PSK")
    if supports("WPA2Enterprise") or supports("WPAEnterpriseMixed"):
        tokens.extend(("WPA2", "802.1X"))
        akms.append("802.1X")
    if supports("WPA3Personal") or supports("WPA3Transition"):
        tokens.append("WPA3")
        akms.append("SAE")
    if supports("WPA3Enterprise"):
        tokens.extend(("WPA3", "802.1X"))
        # The API does not expose the negotiated/advertised AKM or PMF bits.
        # Leave those to the RSN IE instead of inventing SHA-256 or Suite B.
        akms = [a for a in akms if a != "802.1X"]
    if supports("OWE"):
        tokens.append("OWE")
        akms.append("OWE")
    if tokens:
        if tokens == ["WPA1"]:
            akms = ["802.1X" if supports("WPAEnterprise") else "PSK"]
        return " ".join(dict.fromkeys(tokens)), tuple(dict.fromkeys(akms))
    if supports("None"):
        return ("OWE-TM" if supports("OWETransition") else ""), ()
    return "Unknown", ()


_AKMS = {
    1: "802.1X", 2: "PSK", 3: "FT/802.1X", 4: "FT/PSK", 5: "802.1X/SHA-256",
    6: "PSK/SHA-256", 8: "SAE", 9: "FT/SAE", 11: "802.1X/SUITE-B",
    12: "802.1X/SUITE-B-192", 13: "FT/802.1X/SHA-384", 14: "FILS/SHA-256",
    15: "FILS/SHA-384", 16: "FT/FILS/SHA-256", 17: "FT/FILS/SHA-384",
    18: "OWE", 24: "SAE-EXT-KEY", 25: "FT/SAE-EXT-KEY",
}


def _rsn(data):
    """Read complete RSN suite lists and optional capabilities; reject truncation."""
    if len(data) < 8 or data[:2] != b"\x01\x00":
        return None
    pos = 6  # version + group cipher
    for kind in ("pairwise", "akm"):
        if pos + 2 > len(data):
            return None
        count = int.from_bytes(data[pos:pos + 2], "little")
        pos += 2
        end = pos + 4 * count
        if not count or end > len(data):
            return None
        if kind == "akm":
            suites = []
            for off in range(pos, end, 4):
                raw = data[off:off + 4]
                suites.append(_AKMS.get(raw[3], raw.hex()) if raw[:3] == b"\x00\x0f\xac" else raw.hex())
        pos = end
    if len(data) - pos == 1:
        return None
    caps = int.from_bytes(data[pos:pos + 2], "little") if pos < len(data) else 0
    return tuple(suites), caps


def _information_elements(raw):
    pos = 0
    while pos + 2 <= len(raw):
        tag, length = raw[pos:pos + 2]
        pos += 2
        if pos + length > len(raw):
            return
        yield tag, raw[pos:pos + length]
        pos += length


def _enrich_ies(ap, raw):
    """Small, bounds-checked subset of public beacon/probe-response IEs."""
    from .core_base import chan_index_to_freq

    families, vendors, rates, basic = set(), set(), [], []
    for tag, data in _information_elements(raw):
        if tag == 48:
            ap.has_rsn_ie = True
            parsed = _rsn(data)
            if parsed is not None:
                ap.akm_suites, caps = parsed
                ap.akm_raw = " ".join(ap.akm_suites)
                ap.akm = ap.akm_raw
                ap.pmf = "Required" if caps & 0x40 else "Optional" if caps & 0x80 else "No"
                ap.rsn_capabilities = f"0x{caps:04x}"
                ap.ft = ap.ft or any(a.startswith("FT/") for a in ap.akm_suites)
                # Raw suites take precedence over the OS's coarse classification.
                ap.security = "WPA1" if ap.has_wpa1_ie else ""
                ap.rsn_flags = "(none)"
        elif tag == 11 and len(data) == 5:
            ap.station_count = int.from_bytes(data[:2], "little")
            ap.chan_util = data[2]
        elif tag == 7 and len(data) >= 3:
            country = data[:2].decode("ascii", errors="ignore")
            if len(country) == 2 and country.isalpha():
                ap.country = country
        elif tag == 5 and len(data) >= 4:
            ap.dtim_period = data[1]
        elif tag == 54 and len(data) == 3:
            ap.mobility_domain = data[:2].hex()
            ap.ft_over_ds = bool(data[2] & 1)
            ap.ft = True
        elif tag == 70 and len(data) == 5:
            ap.rrm = bool(data[0] & 2)  # Neighbor Report capability
        elif tag == 127 and len(data) >= 3:
            ap.btm = bool(data[2] & 8)  # BSS Transition, bit 19
        elif tag == 45 and len(data) >= 26:
            families.add("HT")
        elif tag == 191 and len(data) >= 12:
            families.add("VHT")
        elif tag == 255 and data:
            if (data[0] == 35 and len(data) >= 22) or (data[0] == 36 and len(data) >= 7):
                families.add("HE")
            elif (data[0] == 108 and len(data) >= 12) or (data[0] == 106 and len(data) >= 6):
                families.add("EHT")
                # EHT Operation: extension ID, params, basic MCS/NSS (4),
                # optional operation info (control, CCFS0, CCFS1).
                if data[0] == 106 and data[1] & 1 and len(data) >= 9:
                    code = data[6] & 7
                    valid_width = code <= 4 and (code < 4 or ap.band == "6 GHz")
                    if valid_width and (ap.band != "2.4 GHz" or code <= 1):
                        ap.bandwidth_mhz = 20 << code
                        center = data[8] if code >= 3 and data[8] else data[7]
                        ap.iw_center_freq = chan_index_to_freq(center, ap.band) or None
        elif tag == 221 and len(data) >= 3:
            vendors.add(":".join(f"{n:02X}" for n in data[:3]))
            if data[:4] == b"\x00\x50\xf2\x01":
                ap.has_wpa1_ie = True
        elif tag in (1, 50):
            for value in data:
                # Membership selectors are not 60.5-63.5 Mbps rates.
                value_without_basic = value & 0x7f
                if 0 < value_without_basic < 121:
                    rate = value_without_basic / 2
                    rates.append(rate)
                    if value & 0x80:
                        basic.append(rate)
    if rates:
        ap.basic_rates = " ".join(f"{r:g}" for r in sorted(set(basic)))
        ap.has_11b_rates = any(r in (1, 2, 5.5, 11) for r in rates)
    ap.vendor_ie_ouis = ", ".join(sorted(vendors))
    generations = {"HT": "WiFi 4", "VHT": "WiFi 5", "HE": "WiFi 6E" if ap.band == "6 GHz" else "WiFi 6", "EHT": "WiFi 7"}
    for family in ("HT", "VHT", "HE", "EHT"):
        if family in families:
            generation = generations[family]
            if not ap.wifi_gen or _GENERATIONS.index(generation) > _GENERATIONS.index(ap.wifi_gen):
                ap.wifi_gen = generation
    ap.phy_cap_summary = "/".join(f for f in ("HT", "VHT", "HE", "EHT") if f in families)


_GENERATIONS = ("WiFi 4", "WiFi 5", "WiFi 6", "WiFi 6E", "WiFi 7")


def _ssid(network):
    value = _value(network, "ssid")
    if value is not None:
        return str(value)
    # ssid() can be nil when the octets cannot be decoded by CoreWLAN;
    # that does not make the AP hidden. Keep a readable replacement string.
    raw = _value(network, "ssidData")
    if raw is not None:
        raw = bytes(raw)
        if any(raw):
            return raw.decode("utf-8", errors="replace")
    return ""


def _network_ap(network, iface_name, framework):
    from .core_models import AccessPoint
    from .core_base import dbm_to_nm_quality

    bssid = _bssid(_value(network, "bssid"))
    if not bssid:
        return None, "identity"
    channel, frequency, width = _channel(_value(network, "wlanChannel"), framework)
    signal = _signal(_value(network, "rssiValue"))
    if not frequency or signal is None:
        return None, "metadata"
    security, akms = _native_security(network, framework)
    ap = AccessPoint(
        ssid=_ssid(network), bssid=bssid.upper(),
        mode="Ad-Hoc" if _value(network, "ibss", False) else "Infra",
        channel=channel, freq_mhz=frequency, bandwidth_mhz=width,
        dbm_exact=signal, signal=dbm_to_nm_quality(signal), rate_mbps=0.0,
        security=security, akm_suites=akms,
        wpa_flags="(none)", rsn_flags="(none)", in_use=False,
        country=str(_value(network, "countryCode") or ""), nm_device=iface_name,
    )
    for mode, generation in (("11n", "WiFi 4"), ("11ac", "WiFi 5"),
                             ("11ax", "WiFi 6E" if ap.band == "6 GHz" else "WiFi 6"),
                             ("11be", "WiFi 7")):
        if _supports(network, framework, "supportsPHYMode_", "kCWPHYMode" + mode):
            ap.wifi_gen = generation
    raw = _value(network, "informationElementData")
    if raw is not None:
        _enrich_ies(ap, bytes(raw))
    return ap, ""


def _connected_metrics(ap, iface, iface_name, framework):
    def optional(selector, default=None):
        # Losing one optional link statistic must not erase a valid scan AP.
        try:
            return _value(iface, selector, default)
        except Exception:
            return default

    ap.in_use = True
    ap.conn_iface = iface_name
    ap.conn_link_ssid = str(optional("ssid") or ap.ssid)
    try:
        _, frequency, _ = _channel(optional("wlanChannel"), framework)
    except (TypeError, ValueError, OverflowError):
        frequency = 0
    ap.conn_link_freq_mhz = frequency or ap.freq_mhz
    signal = _signal(optional("rssiValue"))
    noise = _signal(optional("noiseMeasurement"))
    ap.conn_link_signal_dbm = signal
    if noise is not None:
        ap.conn_survey_noise_dbm = int(noise)
    if signal is not None and noise is not None:
        ap.conn_snr_db = signal - noise
    try:
        rate = float(optional("transmitRate", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        rate = 0
    if math.isfinite(rate) and rate > 0:
        ap.conn_tx_bitrate = f"{rate:g} MBit/s"
    mode = optional("activePHYMode")
    for suffix, label in (("11a", "802.11a"), ("11b", "802.11b"), ("11g", "802.11g"),
                          ("11n", "HT"), ("11ac", "VHT"), ("11ax", "HE"), ("11be", "EHT")):
        value = getattr(framework, "kCWPHYMode" + suffix, None)
        if value is not None and mode == value:
            ap.conn_tx_phy = label
            break


def _error_text(error):
    return str(_value(error, "localizedDescription", None) or error)


def scan_corewlan(stop_event: Event | None = None) -> tuple[list[AccessPoint], str]:
    """Scan all native Wi-Fi interfaces, returning APs and an optional notice.

    A failed/denied scan raises RuntimeError; it must never look like a
    successful empty result. Cancellation is observed between native calls.
    """
    if stop_event is not None and stop_event.is_set():
        return [], ""
    try:
        objc, framework, location = _load_frameworks()
    except (ImportError, OSError, RuntimeError) as exc:
        raise RuntimeError("macOS scanning requires pyobjc-framework-CoreWLAN and pyobjc-framework-CoreLocation. Run ./install.sh again.") from exc
    with objc.autorelease_pool():
        manager = location.CLLocationManager
        if not manager.locationServicesEnabled():
            raise RuntimeError(LOCATION_HELP)
        status = manager.authorizationStatus()
        if status in (location.kCLAuthorizationStatusDenied, location.kCLAuthorizationStatusRestricted):
            raise RuntimeError(LOCATION_HELP)
        if status == location.kCLAuthorizationStatusNotDetermined:
            return [], "Waiting for Location Services permission. " + LOCATION_HELP
        if status not in (location.kCLAuthorizationStatusAuthorizedAlways,
                          location.kCLAuthorizationStatusAuthorizedWhenInUse):
            raise RuntimeError(f"Unknown Location Services authorization status ({status}). " + LOCATION_HELP)

        client = framework.CWWiFiClient.sharedWiFiClient()
        # interfaces() has been an instance method since macOS 10.10;
        # interfaceNames() moved from a class to an instance method later.
        interfaces = client.interfaces()
        if interfaces is None:
            raise RuntimeError("CoreWLAN could not enumerate Wi-Fi interfaces.")
        if not interfaces:
            return [], "No Wi-Fi interface detected — connect or enable a supported wireless adapter."
        aps, errors = {}, []
        successful = powered = redacted = malformed = 0
        for iface in interfaces:
            if stop_event is not None and stop_event.is_set():
                return [], ""
            name = str(_value(iface, "interfaceName") or "Wi-Fi")
            if not iface.powerOn():
                continue
            powered += 1
            try:
                networks, error = iface.scanForNetworksWithName_error_(None, None)
                if error is not None or networks is None:
                    errors.append(f"{name}: {_error_text(error) if error is not None else 'scan returned no result'}")
                    continue
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                continue
            if stop_event is not None and stop_event.is_set():
                return [], ""
            successful += 1
            connected = _bssid(_value(iface, "bssid"))
            for network in networks:
                try:
                    ap, reason = _network_ap(network, name, framework)
                    if reason == "identity":
                        redacted += 1
                    elif reason:
                        malformed += 1
                    if ap is None:
                        continue
                    if ap.bssid.lower() == connected:
                        _connected_metrics(ap, iface, name, framework)
                except (ValueError, TypeError, OverflowError):
                    malformed += 1
                    continue
                old = aps.get(ap.bssid)
                if old is None or (ap.in_use, ap.dbm_exact) > (old.in_use, old.dbm_exact):
                    aps[ap.bssid] = ap
        if not successful and errors:
            raise RuntimeError("CoreWLAN scan failed: " + "; ".join(errors))
        if not powered:
            return [], "Wi-Fi is turned off — enable Wi-Fi in macOS to scan."
        if redacted and not aps:
            raise RuntimeError("macOS withheld network BSSIDs. " + LOCATION_HELP)
        notes = []
        if errors:
            notes.append("Some interfaces could not be scanned: " + "; ".join(errors))
        if redacted:
            notes.append(f"macOS withheld {redacted} network identities. " + LOCATION_HELP)
        if malformed:
            notes.append(f"Skipped {malformed} networks with unavailable channel or signal data.")
        return list(aps.values()), " ".join(notes)
