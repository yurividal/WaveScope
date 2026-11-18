"""Request macOS Wi-Fi privacy permission from the GUI's main thread."""

import sys
import threading


_manager = None
_request_attempted = False
_request_failure = ""
_SETTINGS = "System Settings > Privacy & Security > Location Services"
_BUNDLE_HELP = (
    "Open a properly signed WaveScope.app with location usage descriptions. "
    "For source development, use the signed Python installer from python.org "
    "with Location Services permission already granted."
)


def request_location_access() -> tuple[object | None, str]:
    """Return a retained CLLocationManager and an optional actionable notice.

    Call after showing the main window, while Qt's main event loop is running.
    Core Location delivers authorization asynchronously through that run loop;
    the scanner checks the current status on subsequent cycles. No geographic
    location updates are started. Native frameworks remain optional on Linux.
    """
    global _manager, _request_attempted, _request_failure

    if sys.platform != "darwin":
        return None, ""
    if threading.current_thread() is not threading.main_thread():
        return None, "macOS location permission must be requested from the application's main thread."

    try:
        import CoreLocation
    except Exception:
        return None, (
            "macOS Wi-Fi scanning requires pyobjc-framework-CoreLocation. "
            "Install WaveScope's macOS Python dependencies and restart the app."
        )

    try:
        manager_class = CoreLocation.CLLocationManager
        if not manager_class.locationServicesEnabled():
            return _manager, f"Enable Location Services in {_SETTINGS} to scan Wi-Fi networks."

        if _manager is None:
            _manager = manager_class.alloc().init()
        if _manager is None:
            return None, "macOS could not initialize Location Services. Restart WaveScope and try again."

        status_method = getattr(_manager, "authorizationStatus", None)
        status = status_method() if status_method else manager_class.authorizationStatus()
        if status in (
            CoreLocation.kCLAuthorizationStatusAuthorizedAlways,
            CoreLocation.kCLAuthorizationStatusAuthorizedWhenInUse,
        ):
            return _manager, ""
        if status == CoreLocation.kCLAuthorizationStatusDenied:
            return _manager, f"Allow WaveScope (or Python when running from source) in {_SETTINGS}."
        if status == CoreLocation.kCLAuthorizationStatusRestricted:
            return _manager, (
                "Location Services access is restricted by macOS or device policy. "
                f"Check {_SETTINGS} or contact your device administrator."
            )
        if status != CoreLocation.kCLAuthorizationStatusNotDetermined:
            return _manager, f"macOS reported an unknown location authorization state. Check {_SETTINGS}."

        if _request_attempted:
            if _request_failure:
                return _manager, _request_failure
            return _manager, "Waiting for macOS Location Services permission. Respond to the system prompt."

        from Foundation import NSBundle

        bundle = NSBundle.mainBundle()
        required_keys = ("NSLocationUsageDescription", "NSLocationWhenInUseUsageDescription")
        if bundle is None or any(
            not isinstance(value := bundle.objectForInfoDictionaryKey_(key), str) or not value.strip()
            for key in required_keys
        ):
            return _manager, "This executable cannot request Location Services permission. " + _BUNDLE_HELP

        request = getattr(_manager, "requestWhenInUseAuthorization", None)
        if request is None:
            return _manager, (
                "This macOS/PyObjC runtime cannot request Location Services authorization. "
                "Update macOS and WaveScope's macOS Python dependencies."
            )

        _request_attempted = True
        request()
        return _manager, "Allow Location Services in the macOS prompt to display Wi-Fi names and BSSIDs."
    except Exception as exc:
        note = f"Could not request macOS Location Services permission: {exc}. " + _BUNDLE_HELP
        if _request_attempted:
            _request_failure = note
        return _manager, note
