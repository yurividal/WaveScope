"""Save / load scan sessions and export CSV.

A session is a JSON snapshot of the AccessPoints shown at save time plus
some context (time, app version, data source).  Loading one puts the main
window into review mode (scanning paused, banner shown).
"""

from __future__ import annotations

import csv
import dataclasses
import json
import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from .core_base import APP_NAME, VERSION, atomic_write_text
from .core_models import AccessPoint
from .fields import FIELDS, Field

SESSION_FORMAT = "wavescope-session"
SESSION_VERSION = 1

# AccessPoint init fields; manufacturer/manufacturer_source are init=False.
_INIT_FIELDS = {f.name for f in dataclasses.fields(AccessPoint) if f.init}


def _ap_to_dict(ap: AccessPoint) -> dict:
    d = {}
    for f in dataclasses.fields(AccessPoint):
        v = getattr(ap, f.name)
        if isinstance(v, tuple):
            v = list(v)
        d[f.name] = v
    return d


def _ap_from_dict(d: dict) -> AccessPoint:
    kwargs = {k: v for k, v in d.items() if k in _INIT_FIELDS}
    # JSON has no tuples: restore tuple-typed fields
    for name in ("akm_suites",):
        if isinstance(kwargs.get(name), list):
            kwargs[name] = tuple(kwargs[name])
    if isinstance(kwargs.get("rnr_neighbors"), list):
        kwargs["rnr_neighbors"] = tuple(dict(x) for x in kwargs["rnr_neighbors"])
    ap = AccessPoint(**kwargs)
    # keep the vendor that was resolved at capture time (OUI DB may differ now)
    if d.get("manufacturer"):
        ap.manufacturer = d["manufacturer"]
        ap.manufacturer_source = d.get("manufacturer_source", ap.manufacturer_source)
    return ap


def save_session(path: Path, aps: Sequence[AccessPoint], source: str, note: str = "") -> None:
    doc = {
        "format": SESSION_FORMAT,
        "version": SESSION_VERSION,
        "app": f"{APP_NAME} {VERSION}",
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": source,
        "note": note,
        "access_points": [_ap_to_dict(a) for a in aps],
    }
    atomic_write_text(Path(path), json.dumps(doc, ensure_ascii=False, indent=1))


def load_session(path: Path) -> Tuple[Dict[str, object], List[AccessPoint]]:
    """(metadata, access points).  Raises ValueError on a non-session file."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("format") != SESSION_FORMAT:
        raise ValueError("not a WaveScope session file")
    if int(doc.get("version", 0)) > SESSION_VERSION:
        raise ValueError(f"session format v{doc.get('version')} is newer than this WaveScope supports")
    aps = []
    for d in doc.get("access_points", []):
        try:
            aps.append(_ap_from_dict(d))
        except (TypeError, ValueError):
            continue  # skip malformed entries rather than refusing the file
    meta = {k: doc.get(k) for k in ("app", "saved_at", "source", "note")}
    return meta, aps


def export_csv(path: Path, aps: Sequence[AccessPoint], fields: Sequence[Field] = FIELDS) -> None:
    """One row per BSS, one column per registry field (display formatting)."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([f.label for f in fields])
        for ap in aps:
            w.writerow([f.fmt(ap) for f in fields])
    tmp.replace(path)
