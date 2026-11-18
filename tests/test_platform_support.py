"""Platform routing, UI capabilities and incomplete native scan evidence."""

import pytest
from PyQt6.QtCore import QObject, QSettings, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from wavescope_app import core_base, core_scanner, macos_wifi
from wavescope_app.core import AccessPoint, APTableModel, COL_RATE, COL_BW
from wavescope_app.fields import FIELDS
from wavescope_app.issues import detect_issues, IssueSettings


def ap(**kwargs):
    values = dict(
        ssid="Test", bssid="02:11:22:33:44:55", mode="Infra", channel=5,
        freq_mhz=5975, rate_mbps=0, signal=60, security="Unknown",
        wpa_flags="", rsn_flags="", bandwidth_mhz=0, in_use=False,
    )
    values.update(kwargs)
    return AccessPoint(**values)


def test_macos_dependency_checks_do_not_probe_linux_tools(monkeypatch):
    monkeypatch.setattr(core_base, "IS_MACOS", True)
    monkeypatch.setattr(core_base, "_tool_ok", lambda *_: pytest.fail("probed a Linux tool"))
    monkeypatch.setattr(macos_wifi, "corewlan_available", lambda: True)
    assert core_base.can_scan_at_all()
    assert core_base.find_missing_tools() == []
    assert [key for key, *_ in core_base.scan_source_options()] == ["corewlan"]
    assert "Location Services" in " ".join(core_base.tool_notices())
    monkeypatch.setattr(macos_wifi, "corewlan_available", lambda: False)
    assert not core_base.can_scan_at_all()
    assert "PyObjC" in core_base.find_missing_tools()[0][0]


@pytest.mark.parametrize("is_macos,source,expected", [
    (True, "iw", "corewlan"), (True, "nm", "corewlan"),
    (False, "corewlan", "iw"), (False, "nm", "nm"),
])
def test_stored_source_is_normalized_for_current_platform(monkeypatch, is_macos, source, expected):
    monkeypatch.setattr(core_scanner, "IS_MACOS", is_macos)
    assert core_scanner.WiFiScanner(source=source)._source == expected


def test_native_worker_routes_results_and_preserves_linger_copy(monkeypatch):
    monkeypatch.setattr(core_scanner, "IS_MACOS", True)
    monkeypatch.setattr(core_scanner, "run_tool", lambda *_a, **_k: pytest.fail("Linux scanner called"))
    scanner = core_scanner.WiFiScanner()
    result = ap()
    monkeypatch.setattr(macos_wifi, "scan_corewlan", lambda _event: ([result], ""))
    sources, scans = [], []
    scanner.source_active.connect(sources.append)

    def received(aps):
        scans.append(aps)
        aps[0].ssid = "UI edit"
        scanner._stop_event.set()

    scanner.data_ready.connect(received)
    scanner.run()
    assert sources == ["corewlan"] and len(scans) == 1
    assert result.ssid == "Test"
    assert scanner._seen_cache[result.bssid][0].ssid == "Test"


def test_native_failure_keeps_last_observation_and_reports_error(monkeypatch):
    monkeypatch.setattr(core_scanner, "IS_MACOS", True)
    scanner = core_scanner.WiFiScanner()
    scanner._merge_linger([ap()])
    scans, errors, notes = [], [], []

    def fail(_event):
        raise RuntimeError("Allow WaveScope in Location Services")

    monkeypatch.setattr(macos_wifi, "scan_corewlan", fail)
    scanner.data_ready.connect(scans.append)
    scanner.status_note.connect(notes.append)
    scanner.scan_error.connect(lambda msg: (errors.append(msg), scanner._stop_event.set()))
    scanner.run()
    assert scans == []
    assert len(scanner._seen_cache) == 1
    assert notes == errors == ["Allow WaveScope in Location Services"]


def test_native_scan_finishing_after_stop_does_not_publish(monkeypatch):
    monkeypatch.setattr(core_scanner, "IS_MACOS", True)
    scanner = core_scanner.WiFiScanner()
    scans = []

    def finish_after_stop(event):
        event.set()
        return [ap()], ""

    monkeypatch.setattr(macos_wifi, "scan_corewlan", finish_after_stop)
    scanner.data_ready.connect(scans.append)
    scanner.run()
    assert scans == [] and scanner._seen_cache == {}


def test_unknown_security_and_phy_rate_are_not_invented():
    network = ap()
    assert network.security_short == "Unknown"
    model = APTableModel()
    model.update([network])
    assert model.data(model.index(0, COL_RATE)) == ""
    assert model.data(model.index(0, COL_BW)) == ""
    assert next(f for f in FIELDS if f.key == "max_rate").fmt(network) == ""
    assert not {i.check for i in detect_issues([network], IssueSettings())} & {"open", "six_ghz_security"}


@pytest.mark.parametrize("suite", ["SAE", "OWE", "802.1X/SHA-256"])
def test_missing_pmf_evidence_is_not_a_configuration_error(suite):
    network = ap(security="WPA3", akm_suites=(suite,), iw_seen=True)
    checks = {i.check for i in detect_issues([network], IssueSettings())}
    assert not checks & {"six_ghz_security", "sae_without_pmf"}
    network.pmf = "Optional"
    assert "six_ghz_security" in {i.check for i in detect_issues([network], IssueSettings())}


def test_macos_window_and_settings_expose_only_native_capabilities(monkeypatch, tmp_path):
    from wavescope_app import main_window, main_window_ui, main_window_logic
    from wavescope_app.settings_dialog import SettingsDialog

    monkeypatch.setattr(core_base, "IS_MACOS", True)
    monkeypatch.setattr(main_window_ui, "IS_MACOS", True)
    monkeypatch.setattr(main_window_logic, "IS_MACOS", True)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("scan/source", "nm")  # source restored from a Linux session
    monkeypatch.setattr(main_window, "QSettings", lambda *_: settings)
    window = main_window.MainWindow(start_scanner=False)
    try:
        assert window._data_source == "corewlan"
        assert list(window._source_actions) == ["corewlan"]
        assert not window._capture_action.isEnabled()
        window._on_source_active("corewlan")
        assert "CoreWLAN" in window._lbl_source.text()
        window._on_monitor_mode()
        assert "Linux only" in window.statusBar().currentMessage()
        calls = {}
        monkeypatch.setattr(window, "apply_settings", lambda **kw: calls.update(kw))
        dialog = SettingsDialog(window)
        assert list(dialog._source_buttons) == ["corewlan"]
        assert dialog._apply()
        assert calls["source"] == "corewlan"
        dialog.close()
    finally:
        window.close()


def test_resuming_macos_scan_does_not_restore_evidence_from_imported_linux_session(monkeypatch, tmp_path):
    from wavescope_app import main_window, main_window_ui, main_window_logic

    monkeypatch.setattr(core_base, "IS_MACOS", True)
    monkeypatch.setattr(main_window_ui, "IS_MACOS", True)
    monkeypatch.setattr(main_window_logic, "IS_MACOS", True)
    settings = QSettings(str(tmp_path / "review.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_window, "QSettings", lambda *_: settings)
    window = main_window.MainWindow(start_scanner=False)
    monkeypatch.setattr(window, "_start_scanner", lambda: None)
    try:
        saved = ap(
            freq_mhz=5180, channel=36, bandwidth_mhz=160, rate_mbps=999,
            iw_seen=True, wifi_gen="WiFi 7", security="WPA3",
            pmf="Required", akm_suites=("SAE",),
        )
        window._enter_review_mode("linux-session.json", {"source": "iw"}, [saved])
        assert window._iw_cache and window._sticky_cache
        assert window._btn_pause.isChecked()

        # Resume through the actual button signal, without starting a real radio scan.
        window._btn_pause.setChecked(False)
        native = ap(
            freq_mhz=5180, channel=36, bandwidth_mhz=0, wifi_gen="WiFi 5",
            security="WPA2", pmf="No", akm_suites=("PSK",),
        )
        window._on_data([native])
        assert not window._review_mode
        assert (native.wifi_gen, native.pmf, native.security_short) == ("WiFi 5", "No", "WPA2 (PSK)")
        assert native.rate_mbps == 0 and native.bandwidth_mhz == 0
        assert not native.iw_restored and not window._iw_cache
    finally:
        window.close()


def test_macos_close_defers_without_blocking_native_scan(monkeypatch, tmp_path):
    from wavescope_app import main_window, main_window_logic

    class PendingScanner(QObject):
        finished = pyqtSignal()
        running = True

        def stop(self, wait_ms):
            assert wait_ms == 0  # Never wait on an uninterruptible native call in the GUI.
            return False

        def isRunning(self):
            return self.running

    monkeypatch.setattr(main_window_logic, "IS_MACOS", True)
    settings = QSettings(str(tmp_path / "close.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_window, "QSettings", lambda *_: settings)
    window = main_window.MainWindow(start_scanner=False)
    scanner = PendingScanner()
    window._scanner = scanner
    window.show()
    assert not window.close()
    assert window.isVisible() and not window.isEnabled()
    assert window._scanner is None and scanner in window._retired_scanners
    scanner.running = False
    scanner.finished.emit()
    assert not window.isVisible()
    assert window._retired_scanners == []


def test_macos_close_catches_scan_finishing_during_running_check(monkeypatch, tmp_path):
    from wavescope_app import main_window, main_window_logic

    class QueuedSignal:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

        def emit(self):
            # A native worker queues only the slots connected when it emits.
            callbacks = tuple(self.callbacks)

            def deliver():
                for callback in callbacks:
                    callback()

            QTimer.singleShot(0, deliver)

    class FinishingScanner:
        def __init__(self):
            self.finished = QueuedSignal()
            self.running = True

        def stop(self, wait_ms):
            assert wait_ms == 0
            return False

        def isRunning(self):
            observed = self.running
            if observed:
                self.running = False
                self.finished.emit()
            return observed

    monkeypatch.setattr(main_window_logic, "IS_MACOS", True)
    settings = QSettings(str(tmp_path / "close-race.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(main_window, "QSettings", lambda *_: settings)
    window = main_window.MainWindow(start_scanner=False)
    scanner = FinishingScanner()
    window._scanner = scanner
    window.show()
    try:
        assert not window.close()
        assert window.isVisible() and not window.isEnabled()
        QApplication.processEvents()
        assert not window.isVisible()
        assert window._retired_scanners == []
    finally:
        window.close()
