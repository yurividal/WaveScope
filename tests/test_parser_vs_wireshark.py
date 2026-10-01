"""WaveScope's iw parser vs. Wireshark, on stored (anonymized) real scans.

Each fixture under tests/fixtures/<name>/ was captured with
`devtools/crosscheck.py --save-fixture <name>`:
  iw_scan.txt / iw_scan_b.txt — `iw scan dump -u` / `-b` output
  oracle.json                 — the same frames decoded by Wireshark (tshark)
"""

import glob
import json
import os

import pytest

import ie_oracle
from wavescope_app.core_scanner import parse_iw_scan_merged

FIXTURES = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "fixtures", "*", "oracle.json")))


def _read(path: str) -> str:
    return open(path, encoding="utf-8").read() if os.path.exists(path) else ""


@pytest.mark.parametrize("oracle_path", FIXTURES, ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_parser_matches_wireshark(oracle_path):
    fx = os.path.dirname(oracle_path)
    ours = parse_iw_scan_merged(_read(os.path.join(fx, "iw_scan.txt")), _read(os.path.join(fx, "iw_scan_b.txt")))
    oracle = json.load(open(oracle_path, encoding="utf-8"))
    assert oracle, "empty fixture"
    mismatches = []
    for bssid, ref in oracle.items():
        assert bssid in ours, f"{bssid} missing from WaveScope's parse"
        for field, mine, theirs in ie_oracle.compare(ie_oracle.normalize_wavescope(ours[bssid]), ref):
            mismatches.append(f"{bssid} {field}: wavescope={mine!r} wireshark={theirs!r}")
    assert not mismatches, "\n".join(mismatches)


def test_fixtures_present():
    assert FIXTURES, "no Wireshark fixtures found under tests/fixtures/"
