"""Vendor-specific beacon IE parsers.

Each parser function receives the full ``iw`` BSS text block for one AP and
a mutable result dict ``d``.  It should populate one or more of:

    d["ap_name"]            – human-readable AP/radio name (str)
    d["cisco_tx_power_dbm"] – transmit power in dBm (int)

To add a new vendor:
  1. Write a function with signature  ``def _parse_<vendor>(text, d) -> None``
  2. Append it to the ``_PARSERS`` list at the bottom of this file.

Parsers are called in order; earlier parsers take priority for ``ap_name``
(later parsers skip ``ap_name`` when it is already set).
"""

from __future__ import annotations

import re
from typing import Callable, Dict


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _hex_ie(text: str, ie_id: int) -> bytes | None:
    """Return raw bytes for an Unknown IE with the given element ID, or None."""
    m = re.search(
        rf"Unknown IE \({ie_id}\):\s*([0-9a-f ]+)", text, re.IGNORECASE
    )
    if not m:
        return None
    try:
        return bytes.fromhex(m.group(1).replace(" ", ""))
    except Exception:
        return None


def _printable(raw: bytes) -> str:
    """Extract printable ASCII from a byte sequence, skipping non-printable bytes."""
    return "".join(chr(b) for b in raw if 32 <= b < 127)


# ─────────────────────────────────────────────────────────────────────────────
# Parsers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_cisco_ap_name(text: str, d: dict) -> None:
    """Cisco AP system name from IE 133 (element ID 0x85).

    Format: <8-byte header> 0x40 <ASCII name> 0x00 ...
    iw -u output: Unknown IE (133): xx xx xx xx xx xx xx xx 40 <hex name> ...
    """
    if d.get("ap_name"):
        return
    raw = _hex_ie(text, 133)
    if raw is None:
        return
    try:
        idx = raw.find(0x40)
        if idx != -1 and idx + 1 < len(raw):
            name = _printable(raw[idx + 1:]).rstrip(" ,\x00")
            if name:
                d["ap_name"] = name
    except Exception:
        pass


def _parse_cisco_tx_power(text: str, d: dict) -> None:
    """Cisco beacon radio power from IE 150.

    iw -u output: Unknown IE (150): 00 40 96 00 XX 00
    where XX is the transmit power in dBm.
    """
    raw = _hex_ie(text, 150)
    if raw is None:
        return
    try:
        if len(raw) >= 6 and raw[:4] == bytes([0x00, 0x40, 0x96, 0x00]):
            d["cisco_tx_power_dbm"] = int(raw[4])
    except Exception:
        pass


def _parse_ubiquiti_ap_name(text: str, d: dict) -> None:
    """Ubiquiti AP name from Vendor-specific IE 221 / OUI 00:15:6D, type 0x01.

    iw output: Vendor specific: OUI 00:15:6d, data: 01 <name-bytes...>
    Two observed sub-formats:
      - [type=0x01][len][value...]  (len == remaining bytes)
      - [type=0x01][ascii-name...]
    """
    if d.get("ap_name"):
        return
    matches = re.findall(
        r"Vendor\s+specific:\s*OUI\s*00:15:6d,\s*data:\s*([0-9a-f ]+)",
        text,
        re.IGNORECASE,
    )
    for hex_data in matches:
        try:
            raw = bytes.fromhex(hex_data.replace(" ", ""))
        except Exception:
            continue
        if not raw or raw[0] != 0x01:
            continue
        # [type][len][value...] when len == remaining bytes
        if len(raw) >= 3 and raw[1] == len(raw) - 2:
            name_bytes = raw[2:]
        else:
            name_bytes = raw[1:]
        name = _printable(name_bytes).strip()
        if len(name) >= 3:
            d["ap_name"] = name
            break


# ─────────────────────────────────────────────────────────────────────────────
# Registry — add new vendor parsers here
# ─────────────────────────────────────────────────────────────────────────────

_PARSERS: list[Callable[[str, dict], None]] = [
    _parse_cisco_ap_name,
    _parse_cisco_tx_power,
    _parse_ubiquiti_ap_name,
]


def parse_vendor_ies(text: str, d: dict) -> None:
    """Run all registered vendor parsers against one AP's iw text block."""
    for parser in _PARSERS:
        parser(text, d)
