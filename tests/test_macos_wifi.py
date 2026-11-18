"""CoreWLAN contract tests using fake Objective-C objects (no Mac/radio needed)."""

from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace

import pytest

from wavescope_app import macos_wifi as mac


# Values from CoreWLANTypes.h, also checked by PyObjC's own CoreWLAN tests.
CONSTANTS = {
    'kCWChannelBand2GHz': 1, 'kCWChannelBand5GHz': 2, 'kCWChannelBand6GHz': 3,
    'kCWChannelWidth20MHz': 1, 'kCWChannelWidth40MHz': 2,
    'kCWChannelWidth80MHz': 3, 'kCWChannelWidth160MHz': 4,
    'kCWPHYMode11a': 1, 'kCWPHYMode11b': 2, 'kCWPHYMode11g': 3,
    'kCWPHYMode11n': 4, 'kCWPHYMode11ac': 5, 'kCWPHYMode11ax': 6, 'kCWPHYMode11be': 7,
    'kCWSecurityNone': 0, 'kCWSecurityWEP': 1, 'kCWSecurityWPAPersonal': 2,
    'kCWSecurityWPAPersonalMixed': 3, 'kCWSecurityWPA2Personal': 4,
    'kCWSecurityPersonal': 5, 'kCWSecurityDynamicWEP': 6,
    'kCWSecurityWPAEnterprise': 7, 'kCWSecurityWPAEnterpriseMixed': 8,
    'kCWSecurityWPA2Enterprise': 9, 'kCWSecurityEnterprise': 10,
    'kCWSecurityWPA3Personal': 11, 'kCWSecurityWPA3Enterprise': 12,
    'kCWSecurityWPA3Transition': 13, 'kCWSecurityOWE': 14, 'kCWSecurityOWETransition': 15,
}


def channel(number=36, band=2, width=3):
    return SimpleNamespace(channelNumber=lambda: number, channelBand=lambda: band, channelWidth=lambda: width)


def network(bssid='02:00:00:00:00:01', ssid='Café:東京', dbm=-57, chan=None, security=(4,), phy=(5,), ies=None):
    return SimpleNamespace(
        bssid=lambda: bssid, ssid=lambda: ssid, rssiValue=lambda: dbm,
        wlanChannel=lambda: chan or channel(), countryCode=lambda: 'TW',
        supportsSecurity_=lambda value: value in security,
        supportsPHYMode_=lambda value: value in phy,
        informationElementData=lambda: ies,
        # The documented unit is milliseconds, not the model's TU.
        beaconInterval=lambda: 100,
    )


def interface(name='en7', networks=None, error=None, on=True, connected=None, stop=None):
    state = SimpleNamespace(calls=0)

    def scan(ssid, err):
        assert ssid is None and err is None
        state.calls += 1
        if stop is not None:
            stop.set()
        return ([] if networks is None else networks), error

    state.interfaceName = lambda: name
    state.scanForNetworksWithName_error_ = scan
    state.powerOn = lambda: on
    state.bssid = lambda: connected
    state.ssid = lambda: 'connected'
    state.wlanChannel = lambda: channel()
    state.rssiValue = lambda: -50
    state.noiseMeasurement = lambda: -95
    state.transmitRate = lambda: 866.7
    state.activePHYMode = lambda: 5
    return state


@pytest.fixture
def bridge(monkeypatch):
    state = SimpleNamespace(interfaces=[], enabled=True, status=3, pools=0)

    @contextmanager
    def pool():
        state.pools += 1
        try:
            yield
        finally:
            state.pools -= 1

    client = SimpleNamespace(interfaces=lambda: state.interfaces)
    framework = SimpleNamespace(**CONSTANTS, CWWiFiClient=SimpleNamespace(sharedWiFiClient=lambda: client))
    location = SimpleNamespace(
        CLLocationManager=SimpleNamespace(locationServicesEnabled=lambda: state.enabled, authorizationStatus=lambda: state.status),
        kCLAuthorizationStatusNotDetermined=0, kCLAuthorizationStatusRestricted=1,
        kCLAuthorizationStatusDenied=2, kCLAuthorizationStatusAuthorizedAlways=3,
        kCLAuthorizationStatusAuthorizedWhenInUse=4,
    )
    monkeypatch.setattr(mac, '_load_frameworks', lambda: (SimpleNamespace(autorelease_pool=pool), framework, location))
    state.framework = framework
    return state


def ie(tag, data):
    return bytes((tag, len(data))) + data


def rsn(akms=(2,), caps=0x80):
    selector = b'\x00\x0f\xac'
    return (b'\x01\x00' + selector + b'\x04' + b'\x01\x00' + selector + b'\x04'
            + len(akms).to_bytes(2, 'little')
            + b''.join(selector + bytes((akm,)) for akm in akms)
            + (b'' if caps is None else caps.to_bytes(2, 'little')))


def scan_one(bridge, net):
    bridge.interfaces = [interface(networks=[net])]
    aps, note = mac.scan_corewlan()
    assert note == '' and len(aps) == 1
    assert bridge.pools == 0
    return aps[0]


def test_native_metadata_and_connected_metrics_keep_rate_semantics(bridge):
    iface = interface(networks=[network()], connected='02:00:00:00:00:01')
    bridge.interfaces = [iface]
    aps, note = mac.scan_corewlan()
    ap = aps[0]
    assert note == '' and iface.calls == 1
    assert (ap.ssid, ap.bssid, ap.freq_mhz, ap.channel, ap.bandwidth_mhz) == ('Café:東京', '02:00:00:00:00:01', 5180, 36, 80)
    assert (ap.dbm_exact, ap.wifi_gen, ap.country, ap.nm_device) == (-57, 'WiFi 5', 'TW', 'en7')
    assert ap.in_use and not ap.iw_seen
    assert (ap.conn_iface, ap.conn_tx_bitrate, ap.conn_tx_phy) == ('en7', '866.7 MBit/s', 'VHT')
    assert (ap.conn_link_signal_dbm, ap.conn_survey_noise_dbm, ap.conn_snr_db) == (-50, -95, 45)
    assert ap.rate_mbps == 0  # current TX bitrate is not maximum AP rate
    assert ap.beacon_interval_tu is None  # milliseconds must not be copied as TU


@pytest.mark.parametrize('ch,band,freq', [(1, 1, 2412), (14, 1, 2484), (149, 2, 5745), (1, 3, 5955), (2, 3, 5935), (149, 3, 6695)])
def test_channels_are_band_aware(bridge, ch, band, freq):
    ap = scan_one(bridge, network(chan=channel(ch, band, 1), phy=(6,)))
    assert ap.freq_mhz == freq
    assert ap.wifi_gen == ('WiFi 6E' if band == 3 else 'WiFi 6')


@pytest.mark.parametrize('security,label', [
    ((0,), 'Open'), ((1,), 'WEP'), ((6,), 'WEP'), ((2,), 'WPA (PSK)'),
    ((4,), 'WPA2 (PSK)'), ((3,), 'WPA/WPA2 (PSK)'), ((9,), 'WPA2 (802.1X)'),
    ((7,), 'WPA (802.1X)'), ((8,), 'WPA/WPA2 (802.1X)'),
    ((11,), 'WPA3 (SAE)'), ((13,), 'WPA2/WPA3 (PSK/SAE)'), ((12,), 'WPA3 (802.1X)'),
    ((14,), 'OWE'), ((0, 15), 'Open (OWE transition)'), ((), 'Unknown'),
])
def test_native_security_classes(bridge, security, label):
    assert scan_one(bridge, network(security=security)).security_short == label


@pytest.mark.parametrize('akms,caps,label,pmf', [
    ((8,), 0xc0, 'WPA3 (SAE)', 'Required'), ((2, 8), 0x80, 'WPA2/WPA3 (PSK/SAE)', 'Optional'),
    ((12,), 0xc0, 'WPA3 (802.1X-192)', 'Required'), ((5,), 0xc0, 'WPA3 (802.1X)', 'Required'),
    ((18,), 0xc0, 'OWE', 'Required'), ((24,), 0xc0, 'WPA3 (SAE)', 'Required'),
    ((2,), None, 'WPA2 (PSK)', 'No'), ((99,), 0, 'Unknown', 'No'),
])
def test_rsn_overrides_coarse_os_classification(bridge, akms, caps, label, pmf):
    ap = scan_one(bridge, network(security=(), ies=ie(48, rsn(akms, caps))))
    assert (ap.security_short, ap.pmf, ap.has_rsn_ie) == (label, pmf, True)


def test_information_elements_supply_real_optional_data(bridge):
    raw = b''.join((
        ie(11, b'\x04\x00\x80\x00\x00'), ie(54, b'\x12\x34\x01'),
        ie(70, b'\x02\x00\x00\x00\x00'), ie(127, b'\x00\x00\x08'),
        ie(5, b'\x00\x03\x00\x00'), ie(7, b'JP '),
        ie(1, bytes((0x82, 0x84, 12, 0xfe))), ie(221, b'\x00\x11\x22\x03'),
    ))
    ap = scan_one(bridge, network(ies=raw))
    assert (ap.station_count, ap.chan_util, ap.mobility_domain, ap.ft_over_ds) == (4, 128, '1234', True)
    assert ap.kvr_flags == 'k v r'
    assert (ap.dtim_period, ap.country, ap.basic_rates, ap.has_11b_rates) == (3, 'JP', '1 2', True)
    assert ap.vendor_ie_ouis == '00:11:22'
    assert ap.rate_mbps == 0


def test_eht_ie_recovers_320mhz_without_new_sdk_enums(bridge):
    del bridge.framework.kCWPHYMode11be
    # EHT op info: 320 MHz, primary 160-MHz center 39, 320-MHz center 31.
    raw = ie(255, bytes((106, 1, 0, 0, 0, 0, 4, 39, 31)))
    ap = scan_one(bridge, network(chan=channel(37, 3, 4), phy=(6,), ies=raw))
    assert (ap.wifi_gen, ap.bandwidth_mhz, ap.iw_center_freq) == ('WiFi 7', 320, 6105)
    assert ap.phy_cap_summary == 'EHT'


def test_missing_new_enums_keep_older_api_usable(bridge):
    del bridge.framework.kCWSecurityOWE
    del bridge.framework.kCWSecurityOWETransition
    del bridge.framework.kCWPHYMode11ax
    del bridge.framework.kCWPHYMode11be
    ap = scan_one(bridge, network())
    assert (ap.wifi_gen, ap.security_short) == ('WiFi 5', 'WPA2 (PSK)')


@pytest.mark.parametrize('raw', [
    b'\x30', b'\x30\xffshort', ie(48, b'\x01\x00'),
    ie(48, rsn()[:-1]), ie(48, b'\x01\x00\x00\x0f\xac\x04\xff\xff'),
    ie(11, b'\x01\x00'), ie(255, b'\x6a\x01'),
])
def test_truncated_or_malformed_ies_do_not_invent_metadata(bridge, raw):
    ap = scan_one(bridge, network(ies=raw))
    assert ap.pmf == '' and ap.chan_util is None and ap.station_count is None
    assert ap.wifi_gen == 'WiFi 5'


def test_hidden_ssid_with_real_bssid_is_preserved(bridge):
    ap = scan_one(bridge, network(ssid=None))
    assert ap.ssid == '' and ap.display_ssid.startswith('<hidden>')


@pytest.mark.parametrize('bssid', [None, '', '<redacted>', '00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff'])
def test_redacted_identities_raise_actionable_error(bridge, bssid):
    bridge.interfaces = [interface(networks=[network(bssid=bssid)])]
    with pytest.raises(RuntimeError, match='withheld network BSSIDs.*Location Services'):
        mac.scan_corewlan()


def test_partially_redacted_results_keep_real_identities_and_notice(bridge):
    bridge.interfaces = [interface(networks=[network(), network(bssid=None)])]
    aps, note = mac.scan_corewlan()
    assert len(aps) == 1 and 'withheld 1' in note


@pytest.mark.parametrize('kwargs', [{'dbm': 0}, {'dbm': float('nan')}, {'dbm': None}, {'chan': channel(1, 0)}, {'chan': channel(999, 2)}])
def test_bad_channel_or_rssi_is_not_reported_as_excellent_signal(bridge, kwargs):
    bridge.interfaces = [interface(networks=[network(**kwargs)])]
    aps, note = mac.scan_corewlan()
    assert aps == [] and 'Skipped 1' in note


def test_multiple_interfaces_prefer_connected_then_strongest(bridge):
    bssid = '02:00:00:00:00:01'
    bridge.interfaces = [
        interface('en1', [network(dbm=-40)]),
        interface('en2', [network(dbm=-70)], connected=bssid),
        interface('en3', [network(dbm=-30)]),
    ]
    aps, _ = mac.scan_corewlan()
    assert len(aps) == 1 and aps[0].nm_device == 'en2' and aps[0].in_use
    bridge.interfaces[1].bssid = lambda: None
    aps, _ = mac.scan_corewlan()
    assert len(aps) == 1 and aps[0].nm_device == 'en3'


def test_no_adapter_and_powered_off_are_distinct(bridge):
    assert 'No Wi-Fi interface' in mac.scan_corewlan()[1]
    iface = interface(on=False)
    bridge.interfaces = [iface]
    assert 'turned off' in mac.scan_corewlan()[1] and iface.calls == 0


def test_interface_enumeration_failure_is_not_no_adapter(bridge):
    bridge.interfaces = None
    with pytest.raises(RuntimeError, match='enumerate'):
        mac.scan_corewlan()


@pytest.mark.parametrize('enabled,status', [(False, 3), (True, 1), (True, 2)])
def test_permission_denial_never_triggers_scan(bridge, enabled, status):
    bridge.enabled, bridge.status = enabled, status
    iface = interface(networks=[network()])
    bridge.interfaces = [iface]
    with pytest.raises(RuntimeError, match='Location Services'):
        mac.scan_corewlan()
    assert iface.calls == 0 and bridge.pools == 0


def test_pending_authorization_has_notice_and_does_not_request_from_worker(bridge):
    bridge.status = 0
    iface = interface(networks=[network()])
    bridge.interfaces = [iface]
    aps, note = mac.scan_corewlan()
    assert aps == [] and 'Waiting for Location Services permission' in note
    assert iface.calls == 0


def test_all_scan_failures_raise_and_partial_failures_are_visible(bridge):
    bad = interface('en1', error=SimpleNamespace(localizedDescription=lambda: 'radio busy'))
    bridge.interfaces = [bad]
    with pytest.raises(RuntimeError, match='en1: radio busy'):
        mac.scan_corewlan()
    bridge.interfaces.append(interface('en2', [network()]))
    aps, note = mac.scan_corewlan()
    assert len(aps) == 1 and 'en1: radio busy' in note


def test_no_result_is_a_failure_not_successful_empty_scan(bridge):
    iface = interface()
    iface.scanForNetworksWithName_error_ = lambda *_: (None, None)
    bridge.interfaces = [iface]
    with pytest.raises(RuntimeError, match='scan returned no result'):
        mac.scan_corewlan()


def test_cancellation_before_or_between_native_calls(bridge):
    stop = Event()
    stop.set()
    assert mac.scan_corewlan(stop) == ([], '')
    stop.clear()
    first = interface('en1', [network()], stop=stop)
    second = interface('en2', [network()])
    bridge.interfaces = [first, second]
    assert mac.scan_corewlan(stop) == ([], '')
    assert first.calls == 1 and second.calls == 0 and bridge.pools == 0


def test_optional_import_failure_is_actionable(monkeypatch):
    def missing():
        raise ImportError('CoreWLAN')
    monkeypatch.setattr(mac, '_load_frameworks', missing)
    monkeypatch.setattr(mac.sys, 'platform', 'darwin')
    assert not mac.corewlan_available()
    with pytest.raises(RuntimeError, match='pyobjc-framework-CoreWLAN'):
        mac.scan_corewlan()


def test_linux_does_not_attempt_optional_framework_import(monkeypatch):
    monkeypatch.setattr(mac.sys, 'platform', 'linux')
    monkeypatch.setattr(mac, '_load_frameworks', lambda: pytest.fail('must not import CoreWLAN on Linux'))
    assert not mac.corewlan_available()


def test_ssid_octets_and_adhoc_are_preserved(bridge):
    net = network(ssid=None)
    net.ssidData = lambda: b'Cafe\xff'
    net.ibss = lambda: True
    ap = scan_one(bridge, net)
    assert ap.ssid == 'Cafe\ufffd' and ap.mode == 'Ad-Hoc'
    net.ssidData = lambda: b'\x00' * 8
    assert scan_one(bridge, net).ssid == ''


def test_unknown_authorization_status_does_not_scan(bridge):
    bridge.status = 999
    iface = interface(networks=[network()])
    bridge.interfaces = [iface]
    with pytest.raises(RuntimeError, match='Unknown Location Services authorization'):
        mac.scan_corewlan()
    assert iface.calls == 0


@pytest.mark.parametrize('value', [None, 0, float('nan'), 'unavailable'])
def test_bad_optional_link_rate_preserves_ap(bridge, value):
    iface = interface(networks=[network()], connected='02:00:00:00:00:01')
    iface.transmitRate = lambda: value
    bridge.interfaces = [iface]
    aps, note = mac.scan_corewlan()
    assert len(aps) == 1 and aps[0].in_use and note == ''
    assert aps[0].conn_tx_bitrate == '' and aps[0].conn_snr_db == 45


def test_optional_native_metric_exception_preserves_ap(bridge):
    def unavailable():
        raise RuntimeError('native statistic unavailable')
    iface = interface(networks=[network()], connected='02:00:00:00:00:01')
    iface.transmitRate = iface.rssiValue = iface.noiseMeasurement = unavailable
    bridge.interfaces = [iface]
    aps, _ = mac.scan_corewlan()
    assert len(aps) == 1 and aps[0].in_use
    assert aps[0].conn_tx_bitrate == '' and aps[0].conn_snr_db is None


def test_native_bridge_initialization_failure_is_actionable(monkeypatch):
    def unavailable():
        raise RuntimeError('cannot load native framework')
    monkeypatch.setattr(mac, '_load_frameworks', unavailable)
    monkeypatch.setattr(mac.sys, 'platform', 'darwin')
    assert not mac.corewlan_available()
    with pytest.raises(RuntimeError, match='CoreWLAN'):
        mac.scan_corewlan()
