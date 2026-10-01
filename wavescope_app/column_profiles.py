"""Column profiles: which table columns are shown, in what order, how many pinned.

Profiles reference columns by stable key (core_table.COLUMN_KEYS), so they
survive column additions.  Built-in profiles cannot be deleted; custom ones
are stored in QSettings.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from .core_table import COLUMN_KEYS


@dataclass
class ColumnProfile:
    name: str
    columns: List[str]  # visible columns, in display order
    pinned: int = 2  # number of leading columns frozen while scrolling
    builtin: bool = False

    def sanitized(self) -> "ColumnProfile":
        cols = [c for c in dict.fromkeys(self.columns) if c in COLUMN_KEYS]
        return ColumnProfile(self.name, cols or ["ssid", "bssid"], max(0, min(self.pinned, len(cols))), self.builtin)


BUILTIN_PROFILES: List[ColumnProfile] = [
    ColumnProfile(
        "Default",
        ["inuse", "ssid", "bssid", "manufacturer", "band", "country", "channel", "freq", "width", "span",
         "signal", "dbm", "rate", "security", "phy", "gen", "util", "clients", "roaming", "apname", "power", "label"],
        pinned=2, builtin=True,
    ),
    ColumnProfile(
        "RF / Channel",
        ["inuse", "ssid", "bssid", "label", "band", "channel", "width", "span", "center", "dbm", "util",
         "clients", "bss_color", "ap_power_6g", "power", "country"],
        pinned=3, builtin=True,
    ),
    ColumnProfile(
        "Security",
        ["inuse", "ssid", "bssid", "label", "band", "security", "akm", "pmf", "group_mgmt", "rsnx", "dbm"],
        pinned=3, builtin=True,
    ),
    ColumnProfile(
        "Roaming",
        ["inuse", "ssid", "bssid", "label", "apname", "band", "channel", "dbm", "roaming", "mobility_domain",
         "beacon_interval", "dtim", "mld_mac"],
        pinned=3, builtin=True,
    ),
    ColumnProfile(
        "Survey",
        ["inuse", "ssid", "bssid", "label", "apname", "manufacturer", "band", "channel", "width", "dbm",
         "gen", "security", "util", "clients", "last_seen"],
        pinned=3, builtin=True,
    ),
]


class ProfileStore:
    """Built-in + custom profiles; custom ones persisted as JSON in QSettings."""

    KEY = "table/column_profiles"

    def __init__(self, settings):
        self._settings = settings
        self._custom: Dict[str, ColumnProfile] = {}
        raw = settings.value(self.KEY, "")
        try:
            for d in json.loads(raw) if raw else []:
                p = ColumnProfile(d["name"], list(d["columns"]), int(d.get("pinned", 2))).sanitized()
                if p.name and p.name not in self.builtin_names():
                    self._custom[p.name] = p
        except (ValueError, TypeError, KeyError):
            self._custom = {}

    @staticmethod
    def builtin_names() -> List[str]:
        return [p.name for p in BUILTIN_PROFILES]

    def names(self) -> List[str]:
        return self.builtin_names() + sorted(self._custom)

    def get(self, name: str) -> ColumnProfile:
        for p in BUILTIN_PROFILES:
            if p.name == name:
                return p.sanitized()
        return (self._custom.get(name) or BUILTIN_PROFILES[0]).sanitized()

    def save(self, profile: ColumnProfile) -> Optional[str]:
        """Store a custom profile; returns an error message or None."""
        name = profile.name.strip()
        if not name:
            return "A profile needs a name."
        if name in self.builtin_names():
            return f"'{name}' is a built-in profile; save under a different name."
        self._custom[name] = ColumnProfile(name, profile.columns, profile.pinned).sanitized()
        self._persist()
        return None

    def delete(self, name: str) -> None:
        if self._custom.pop(name, None) is not None:
            self._persist()

    def _persist(self) -> None:
        data = [{k: v for k, v in asdict(p).items() if k != "builtin"} for p in self._custom.values()]
        self._settings.setValue(self.KEY, json.dumps(data))
