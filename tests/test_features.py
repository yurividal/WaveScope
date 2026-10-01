"""Tests for 2.1 features: labels, column profiles, sessions/CSV, issues,
Find AP, compare, settings.  Widgets run on Qt's offscreen platform."""

import csv
import types

import pytest

from wavescope_app.annotations import AnnotationStore, is_valid_pattern
from wavescope_app.beeper import FindAPDialog, beep_interval_ms, pitch_index, PITCHES_HZ
from wavescope_app.column_profiles import BUILTIN_PROFILES, ColumnProfile, ProfileStore
from wavescope_app.column_view import FrozenTableView, apply_profile
from wavescope_app.compare import CompareDialog
from wavescope_app.core import AccessPoint, APFilterProxy, APTableModel, COLUMN_INDEX, COLUMN_KEYS
from wavescope_app.issues import IssueSettings, detect_issues
from wavescope_app.session import export_csv, load_session, save_session


def ap(**kw) -> AccessPoint:
    base = dict(
        ssid="Corp", bssid="74:11:B2:C7:22:40", mode="Infra", channel=36, freq_mhz=5180, rate_mbps=0,
        signal=60, security="WPA2", wpa_flags="(none)", rsn_flags="pair_ccmp group_ccmp psk",
        bandwidth_mhz=20, in_use=False,
    )
    base.update(kw)
    a = AccessPoint(**base)
    a.iw_seen = kw.get("iw_seen", True)
    return a


class FakeSettings(dict):
    def value(self, k, default=None):
        return self.get(k, default)

    def setValue(self, k, v):  # noqa: N802
        self[k] = v


# ── labels ───────────────────────────────────────────────────────────────────


def test_annotations_exact_beats_wildcard_and_longest_wins(tmp_path):
    st = AnnotationStore(tmp_path / "a.json")
    assert st.set("74:11:B2:C7:22:4*", "Lobby AP")
    assert st.set("74:11:b2:c7:2*", "Floor 2")
    assert st.set("74:11:b2:c7:22:4F", "Lobby 5 GHz")
    assert st.label_for("74:11:B2:C7:22:4F") == "Lobby 5 GHz"  # exact
    assert st.label_for("74:11:B2:C7:22:41") == "Lobby AP"  # longest pattern
    assert st.label_for("74:11:B2:C7:29:00") == "Floor 2"
    assert st.label_for("00:00:00:00:00:00") == ""
    # persisted and reloaded
    assert AnnotationStore(tmp_path / "a.json").label_for("74:11:b2:c7:22:41") == "Lobby AP"
    st.set("74:11:B2:C7:22:4F", "")  # empty label removes
    assert st.label_for("74:11:B2:C7:22:4F") == "Lobby AP"


@pytest.mark.parametrize("p, ok", [("74:11:b2:c7:22:4f", True), ("74:11:B2:*", True), ("foo", False), ("", False), ("74:11", False)])
def test_label_pattern_validation(p, ok):
    assert is_valid_pattern(p) is ok


# ── column profiles ──────────────────────────────────────────────────────────


def test_builtin_profiles_reference_real_columns():
    for p in BUILTIN_PROFILES:
        assert all(k in COLUMN_KEYS for k in p.columns), p.name


def test_profile_store_save_delete_and_protect_builtins():
    st = ProfileStore(FakeSettings())
    assert st.save(ColumnProfile("Default", ["ssid"])) is not None  # built-in name refused
    assert st.save(ColumnProfile("Mine", ["ssid", "nope", "bssid"], pinned=5)) is None
    p = ProfileStore(st._settings).get("Mine")  # reload from settings
    assert p.columns == ["ssid", "bssid"] and p.pinned == 2  # unknown key dropped, pinned clamped
    st.delete("Mine")
    assert "Mine" not in st.names()


def test_frozen_view_applies_profile():
    model, proxy = APTableModel(), APFilterProxy()
    proxy.setSourceModel(model)
    view = FrozenTableView()
    view.setModel(proxy)
    model.update([ap(), ap(bssid="74:11:B2:C7:22:41", ssid="Guest")])
    prof = ColumnProfile("t", ["bssid", "ssid", "dbm", "pmf"], pinned=2)
    apply_profile(view, prof)
    hdr = view.horizontalHeader()
    visible = [hdr.logicalIndex(v) for v in range(hdr.count()) if not hdr.isSectionHidden(hdr.logicalIndex(v))]
    assert visible == [COLUMN_INDEX[k] for k in prof.columns]
    assert view.pinned_logical_columns() == [COLUMN_INDEX["bssid"], COLUMN_INDEX["ssid"]]
    # auto-hidden columns stay hidden even if the profile lists them
    apply_profile(view, prof, auto_hidden={COLUMN_INDEX["pmf"]})
    assert view.isColumnHidden(COLUMN_INDEX["pmf"])


# ── sessions / CSV ───────────────────────────────────────────────────────────


def test_session_roundtrip_and_csv(tmp_path):
    a = ap(akm_suites=("SAE",), rnr_neighbors=({"channel": 37, "bssid": "84:78:48:ea:44:d7"},), label="Lobby")
    a.manufacturer, a.manufacturer_source = "Cisco Systems", "OUI database"
    path = tmp_path / "s.wavescope.json"
    save_session(path, [a], "iw")
    meta, (b,) = load_session(path)
    assert meta["source"] == "iw"
    assert (b.bssid, b.akm_suites, b.rnr_neighbors[0]["channel"], b.manufacturer, b.label) == (
        a.bssid, ("SAE",), 37, "Cisco Systems", "Lobby",
    )
    csv_path = tmp_path / "x.csv"
    export_csv(csv_path, [a, b])
    rows = list(csv.reader(open(csv_path, encoding="utf-8")))
    assert rows[0][0] == "SSID" and len(rows) == 3


def test_load_rejects_other_json(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"hello": 1}')
    with pytest.raises(ValueError):
        load_session(p)


# ── issues ───────────────────────────────────────────────────────────────────


def checks(aps, cfg=None):
    return {i.check for i in detect_issues(aps, cfg)}


def test_security_issue_checks():
    assert "wep" in checks([ap(security="WEP", rsn_flags="(none)")])
    assert "open" in checks([ap(security="", rsn_flags="(none)")])
    assert "tkip" in checks([ap(security="WPA1 WPA2", wpa_flags="pair_tkip group_tkip psk")])
    six = ap(band_dummy=None) if False else ap(freq_mhz=6135, channel=37)
    assert "six_ghz_security" in checks([six])  # WPA2 on 6 GHz
    assert "sae_without_pmf" in checks([ap(akm_suites=("SAE",), pmf="No", has_rsn_ie=True, security="WPA3")])


def test_rf_issue_checks():
    b = ap(freq_mhz=2412, channel=1, has_11b_rates=True, basic_rates="1 2 5.5 11")
    assert "b_rates" in checks([b])
    assert "wide_24" in checks([ap(freq_mhz=2437, channel=6, bandwidth_mhz=40)])
    # overlap: different APs on ch 1 and ch 3, both strong
    o1 = ap(bssid="00:11:22:33:44:50", freq_mhz=2412, channel=1, dbm_exact=-60.0)
    o2 = ap(bssid="00:aa:bb:cc:dd:e0", freq_mhz=2422, channel=3, dbm_exact=-65.0)
    assert "overlap_24" in checks([o1, o2])
    # not when one is too weak for the threshold
    o2.dbm_exact = -90.0
    assert "overlap_24" not in checks([o1, o2])


def test_ssid_consistency_ignores_6ghz_transition_design():
    a5 = ap(bssid="84:78:48:ea:44:d6", freq_mhz=5745, channel=149, pmf="Optional", security="WPA2 WPA3",
            rsn_flags="pair_ccmp psk sae", akm_suites=("PSK", "SAE"))
    a6 = ap(bssid="84:78:48:ea:44:d7", freq_mhz=6135, channel=37, pmf="Required", security="WPA3",
            rsn_flags="pair_ccmp sae", akm_suites=("SAE",))
    assert "ssid_mismatch" not in checks([a5, a6])
    a5b = ap(bssid="84:78:48:ea:44:e6", freq_mhz=5180, channel=36, pmf="No", security="WPA2 WPA3",
             rsn_flags="pair_ccmp psk sae", akm_suites=("PSK", "SAE"))
    assert "ssid_mismatch" in checks([a5, a6, a5b])  # PMF differs on 5 GHz


def test_disabled_check_is_skipped_and_thresholds():
    cfg = IssueSettings()
    cfg.enabled["wep"] = False
    assert "wep" not in checks([ap(security="WEP", rsn_flags="(none)")], cfg)
    radio = [ap(bssid=f"74:11:b2:c7:22:4{i}", ssid=f"S{i}") for i in range(5)]
    assert "many_ssids" in checks(radio)  # 5 > 4
    cfg.max_ssids = 5
    assert "many_ssids" not in checks(radio, cfg)


def test_6ghz_discovery_check():
    off_psc = ap(bssid="84:78:48:ea:44:d7", freq_mhz=6155, channel=41, security="WPA3",
                 rsn_flags="pair_ccmp sae", akm_suites=("SAE",), pmf="Required")
    assert "six_ghz_discovery" in checks([off_psc])
    adv = ap(bssid="84:78:48:ea:44:d6", rnr_neighbors=({"bssid": "84:78:48:ea:44:d7", "channel": 41},))
    assert "six_ghz_discovery" not in checks([off_psc, adv])


# ── Find AP / compare / settings widgets ────────────────────────────────────


def test_beeper_mapping():
    assert beep_interval_ms(-95) == 1500 and beep_interval_ms(-30) == 120
    assert beep_interval_ms(-60) < beep_interval_ms(-80)
    assert pitch_index(-100) == 0 and pitch_index(-20) == len(PITCHES_HZ) - 1


def test_find_ap_dialog_updates():
    dlg = FindAPDialog("74:11:B2:C7:22:40", "Corp", sound=False)
    dlg.update_aps([ap(dbm_exact=-61.0)])
    assert dlg._lbl_dbm.text() == "-61 dBm"
    dlg.close()


def test_compare_dialog_counts_differences():
    a, b = ap(), ap(bssid="74:11:B2:C7:22:41", ssid="Guest", channel=40, freq_mhz=5200)
    dlg = CompareDialog([a, b])
    assert dlg._table.rowCount() >= 3  # SSID, BSSID, channel, frequency differ
    dlg._chk_diff.setChecked(False)
    assert dlg._table.rowCount() > 3


def test_settings_dialog_applies_values(monkeypatch):
    from PyQt6.QtWidgets import QComboBox, QMessageBox, QSpinBox

    # the invalid-pattern path shows a modal warning: don't block the test
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))

    from wavescope_app.graphs import ChannelGraphWidget
    from wavescope_app.settings_dialog import SettingsDialog

    calls = {}
    theme = QComboBox()
    theme.addItems(["Dark", "Light", "Auto"])
    interval = QComboBox()
    interval.addItems(["1s", "2s", "5s", "10s"])
    linger = QSpinBox()
    linger.setRange(0, 600)
    linger.setValue(60)
    mw = types.SimpleNamespace(
        _theme_combo=theme, _interval_combo=interval, _linger_spin=linger, _data_source="iw",
        _channel_graph=ChannelGraphWidget(), _profile_store=ProfileStore(FakeSettings()),
        _active_profile="Security", _annotations=types.SimpleNamespace(items=lambda: [("74:11:b2:*", "Cisco")]),
        _issue_cfg=IssueSettings(), _find_sound_default=False,
        apply_settings=lambda **kw: calls.update(kw),
    )
    dlg = SettingsDialog(mw, parent=None)
    dlg._linger.setValue(30)
    dlg._src_nm.setChecked(True)
    assert dlg._apply()
    assert calls["linger_s"] == 30 and calls["source"] == "nm" and calls["profile"] == "Security"
    assert calls["labels"] == [("74:11:b2:*", "Cisco")]
    # an invalid label pattern blocks Apply
    dlg._add_label_row("not-a-mac", "x")
    assert not dlg._apply()


def test_notice_wording_is_not_error_like():
    """The AppImage catalog OCRs the first screenshot and fails the app when
    the text matches these regexes (appimage.github.io code/check-screenshot.sh).
    Our optional-tool notices and scanner state notes must stay clear of them."""
    import re

    from wavescope_app import core_base, core_scanner
    hard = re.compile(
        r"traceback|exception|segmentation fault|fatal|error while loading|glibc|not installed|"
        r"cannot open display|permission denied|no such file|could not (load|find|open|start|initiali)|"
        r"failed to (load|start|open|initiali|create)|cannot (load|find|open|execute|configure)|"
        r"unable to (load|find|open|start)|command not found|core dumped", re.I)
    soft = re.compile(r"error|failed|failure|could not|cannot|unable to|not found", re.I)
    # every notice string regardless of which tools exist on this machine
    src = open(core_base.__file__, encoding="utf-8").read() + open(core_scanner.__file__, encoding="utf-8").read()
    notes = re.findall(r'_emit_note\(\s*"([^"]+)"', src) + re.findall(r'notes\.append\(\s*f?"([^"]+)"', src)
    notes += re.findall(r'_emit_note\(\s*\n\s*"([^"]+)"\s*\n\s*"([^"]+)"', src) and [
        "".join(t) for t in re.findall(r'_emit_note\(\s*\n\s*"([^"]+)"\s*\n\s*"([^"]+)"', src)
    ]
    assert notes, "no notice strings found"
    bad = [n for n in notes if hard.search(n) or soft.search(n)]
    assert not bad, bad
