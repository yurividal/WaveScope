"""Location authorization behavior without native prompts or macOS frameworks."""

import builtins
import sys
import threading
from types import SimpleNamespace

import pytest

from wavescope_app import macos_permissions


@pytest.fixture
def native(monkeypatch):
    state = SimpleNamespace(
        enabled=True,
        status=0,
        calls=0,
        bundle_reads=[],
        descriptions={
            "NSLocationUsageDescription": "Show nearby Wi-Fi networks.",
            "NSLocationWhenInUseUsageDescription": "Show nearby Wi-Fi networks.",
        },
        request_error=None,
    )

    class Manager:
        @classmethod
        def locationServicesEnabled(cls):
            return state.enabled

        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

        def authorizationStatus(self):
            return state.status

        def requestWhenInUseAuthorization(self):
            state.calls += 1
            if state.request_error is not None:
                raise state.request_error

    class Bundle:
        @classmethod
        def mainBundle(cls):
            return cls()

        def objectForInfoDictionaryKey_(self, key):
            state.bundle_reads.append(key)
            return state.descriptions.get(key)

    location = SimpleNamespace(
        CLLocationManager=Manager,
        kCLAuthorizationStatusNotDetermined=0,
        kCLAuthorizationStatusRestricted=1,
        kCLAuthorizationStatusDenied=2,
        kCLAuthorizationStatusAuthorizedAlways=3,
        kCLAuthorizationStatusAuthorizedWhenInUse=4,
    )
    monkeypatch.setitem(sys.modules, "CoreLocation", location)
    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace(NSBundle=Bundle))
    monkeypatch.setattr(macos_permissions, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(macos_permissions, "_manager", None)
    monkeypatch.setattr(macos_permissions, "_request_attempted", False)
    monkeypatch.setattr(macos_permissions, "_request_failure", "")
    state.manager_class = Manager
    return state


def test_non_macos_does_not_load_native_frameworks(monkeypatch):
    monkeypatch.setattr(macos_permissions, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setitem(sys.modules, "CoreLocation", None)
    monkeypatch.setitem(sys.modules, "Foundation", None)
    assert macos_permissions.request_location_access() == (None, "")


def test_missing_dependency_reports_installation_help(native, monkeypatch):
    monkeypatch.setitem(sys.modules, "CoreLocation", None)
    manager, note = macos_permissions.request_location_access()
    assert manager is None
    assert "pyobjc-framework-CoreLocation" in note


def test_native_framework_load_failure_is_reported(native, monkeypatch):
    real_import = builtins.__import__

    def broken_framework(name, *args, **kwargs):
        if name == "CoreLocation":
            raise OSError("incompatible architecture")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken_framework)
    manager, note = macos_permissions.request_location_access()
    assert manager is None
    assert "macOS Python dependencies" in note


def test_background_thread_does_not_create_manager_or_prompt(native):
    result = []
    worker = threading.Thread(target=lambda: result.append(macos_permissions.request_location_access()))
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert result[0][0] is None
    assert "main thread" in result[0][1]
    assert native.calls == 0
    assert macos_permissions._manager is None


def test_disabled_services_return_global_settings_help(native):
    native.enabled = False
    manager, note = macos_permissions.request_location_access()
    assert manager is None
    assert "Enable Location Services" in note
    assert native.calls == 0


@pytest.mark.parametrize("status, expected", [(1, "restricted"), (2, "Allow WaveScope"), (17, "unknown")])
def test_non_requestable_status_is_explained_without_prompt(native, status, expected):
    native.status = status
    manager, note = macos_permissions.request_location_access()
    assert isinstance(manager, native.manager_class)
    assert expected in note
    assert native.calls == 0
    assert native.bundle_reads == []


@pytest.mark.parametrize("status", [3, 4])
def test_pregranted_source_interpreter_needs_no_usage_description(native, status):
    native.status = status
    native.descriptions.clear()
    manager, note = macos_permissions.request_location_access()
    assert isinstance(manager, native.manager_class)
    assert note == ""
    assert native.calls == 0
    assert native.bundle_reads == []


@pytest.mark.parametrize("key", ["NSLocationUsageDescription", "NSLocationWhenInUseUsageDescription"])
@pytest.mark.parametrize("value", [None, "", "   ", 42])
def test_missing_or_invalid_usage_description_does_not_prompt_or_modify_bundle(native, key, value):
    native.descriptions[key] = value
    original = dict(native.descriptions)
    manager, note = macos_permissions.request_location_access()
    assert isinstance(manager, native.manager_class)
    assert "signed WaveScope.app" in note
    assert "python.org" in note
    assert native.calls == 0
    assert native.descriptions == original


def test_requests_once_retains_manager_and_observes_later_grant(native):
    manager, note = macos_permissions.request_location_access()
    assert "macOS prompt" in note
    assert native.calls == 1
    again, waiting = macos_permissions.request_location_access()
    assert again is manager
    assert "Waiting" in waiting
    assert native.calls == 1
    native.status = 4
    granted, note = macos_permissions.request_location_access()
    assert granted is manager
    assert note == ""
    assert native.calls == 1


def test_native_request_error_is_actionable_and_not_repeated(native):
    native.request_error = RuntimeError("framework failure")
    manager, note = macos_permissions.request_location_access()
    assert isinstance(manager, native.manager_class)
    assert "framework failure" in note
    assert "signed WaveScope.app" in note
    _, repeated_note = macos_permissions.request_location_access()
    assert repeated_note == note
    assert native.calls == 1


def test_older_runtime_without_authorization_request_is_explained(native, monkeypatch):
    monkeypatch.delattr(native.manager_class, "requestWhenInUseAuthorization")
    manager, note = macos_permissions.request_location_access()
    assert isinstance(manager, native.manager_class)
    assert "Update macOS" in note
    assert native.calls == 0
