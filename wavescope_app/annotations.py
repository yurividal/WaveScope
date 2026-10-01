"""Per-BSSID labels ("Room 204 AP"), with wildcard patterns.

Patterns are matched case-insensitively against the BSSID with shell-style
wildcards (`*`, `?`, `[...]`), e.g. ``74:11:B2:C7:22:4*`` labels every BSSID
of one Cisco AP.  An exact BSSID beats a wildcard; among wildcards the most
specific (longest pattern) wins.  Stored as JSON next to the OUI database.
"""

from __future__ import annotations

import fnmatch
import json
import re
from typing import Dict, List, Optional, Tuple

from .core_base import atomic_write_text
from .core_vendor import OUI_DATA_DIR

ANNOTATIONS_PATH = OUI_DATA_DIR / "annotations.json"

_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def normalize_pattern(pattern: str) -> str:
    return (pattern or "").strip().lower().replace("-", ":")


def is_valid_pattern(pattern: str) -> bool:
    p = normalize_pattern(pattern)
    if not p:
        return False
    if _MAC_RE.match(p):
        return True
    # wildcard pattern: only MAC characters plus wildcard syntax
    return bool(re.fullmatch(r"[0-9a-f:*?\[\]!]+", p)) and any(c in p for c in "*?[")


class AnnotationStore:
    """JSON-backed {pattern: label} map; every mutation is saved atomically."""

    def __init__(self, path=ANNOTATIONS_PATH):
        self._path = path
        self._labels: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._labels = {
                        normalize_pattern(k): str(v) for k, v in data.items() if is_valid_pattern(k) and str(v).strip()
                    }
        except (OSError, ValueError):
            self._labels = {}

    def _save(self) -> None:
        try:
            atomic_write_text(self._path, json.dumps(dict(sorted(self._labels.items())), ensure_ascii=False, indent=2))
        except OSError:
            pass

    # ── query ───────────────────────────────────────────────────────────────

    def label_for(self, bssid: str) -> str:
        b = normalize_pattern(bssid)
        if b in self._labels:
            return self._labels[b]
        best: Optional[Tuple[int, str]] = None
        for pat, label in self._labels.items():
            if any(c in pat for c in "*?[") and fnmatch.fnmatchcase(b, pat):
                if best is None or len(pat) > best[0]:
                    best = (len(pat), label)
        return best[1] if best else ""

    def items(self) -> List[Tuple[str, str]]:
        return sorted(self._labels.items())

    def exact(self, bssid: str) -> str:
        return self._labels.get(normalize_pattern(bssid), "")

    # ── mutation ────────────────────────────────────────────────────────────

    def set(self, pattern: str, label: str) -> bool:
        p = normalize_pattern(pattern)
        if not is_valid_pattern(p):
            return False
        if label.strip():
            self._labels[p] = label.strip()
        else:
            self._labels.pop(p, None)
        self._save()
        return True

    def remove(self, pattern: str) -> None:
        self._labels.pop(normalize_pattern(pattern), None)
        self._save()

    def replace_all(self, items: List[Tuple[str, str]]) -> None:
        self._labels = {
            normalize_pattern(p): l.strip() for p, l in items if is_valid_pattern(p) and l.strip()
        }
        self._save()
