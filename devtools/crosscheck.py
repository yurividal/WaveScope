#!/usr/bin/env python3
"""Cross-check WaveScope's iw parser against Wireshark on live scan data.

Usage:
    python3 devtools/crosscheck.py [--iface wlan0] [--save-fixture NAME]

Needs (developer machine only): iw, tshark (Wireshark CLI), pyroute2
(see requirements-dev.txt).  No root: reading the kernel scan cache is
unprivileged.  Run `nmcli dev wifi rescan` first for fresh data.

--save-fixture NAME writes tests/fixtures/NAME/{iw_scan.txt,oracle.json}
so the comparison runs offline in CI (tests/test_parser_vs_wireshark.py).
"""

from __future__ import annotations

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ie_oracle  # noqa: E402
from wavescope_app.core_scanner import _detect_wifi_ifaces, iw_scan_texts, parse_iw_scan_merged  # noqa: E402


def _iw_escape(ssid: str) -> str:
    """iw's print_ssid_escaped() form of an SSID (for consistent mapping)."""
    raw = ssid.encode("utf-8")
    out = []
    for i, b in enumerate(raw):
        if 32 < b < 127 and b != 0x5C:
            out.append(chr(b))
        elif b == 0x20 and 0 < i < len(raw) - 1:
            out.append(" ")
        else:
            out.append(f"\\x{b:02x}")
    return "".join(out)


def iw_tsf_by_bssid(iw_text: str) -> dict:
    """TSF per BSSID as printed by iw, to pair identical observations."""
    out = {}
    for blk in re.split(r"(?m)^BSS ", iw_text)[1:]:
        m = re.match(r"([0-9a-f:]{17})", blk)
        t = re.search(r"(?m)^\tTSF: (\d+) usec", blk)
        if m and t:
            out[m.group(1).lower()] = int(t.group(1))
    return out


class Anonymizer:
    """Consistent, relationship-preserving anonymization for fixtures.

    BSSIDs are location-identifying (public Wi-Fi maps), so fixtures from
    real scans must not carry them.  Each MAC is remapped component-wise:
      octet 1  → high 6 bits remapped, U/L + multicast bits kept
      octets 2-3, 4-5 → remapped as pairs
      octet 6  → high nibble remapped, low nibble kept
    Every component map is a function, so the relationships the parser and
    grouping rules rely on survive: shared octets 2-5, the U/L bit, the
    16-address low-nibble AP blocks.  MACs are rewritten in colon form and
    as raw byte runs inside undecoded / vendor IEs (RNR, vendor data …).
    SSIDs become "ssid-N" (hidden stays empty).
    """

    MAC_RE = re.compile(r"\b([0-9a-f]{2}(?::[0-9a-f]{2}){5})\b", re.IGNORECASE)

    def __init__(self, salt: str = "wavescope-fixture"):
        import hashlib

        self._h = lambda tag, v: hashlib.sha256(f"{salt}|{tag}|{v}".encode()).digest()
        self._macs: dict = {}
        self._ssids: dict = {}

    def mac(self, mac: str) -> str:
        key = mac.lower()
        if key not in self._macs:
            o = [int(x, 16) for x in key.split(":")]
            n1 = (self._h("o1", o[0] >> 2)[0] & 0xFC) | (o[0] & 0x03)
            p23 = self._h("o23", (o[1], o[2]))[:2]
            p45 = self._h("o45", (o[3], o[4]))[:2]
            n6 = (self._h("o6", o[5] >> 4)[0] & 0xF0) | (o[5] & 0x0F)
            new = [n1, p23[0], p23[1], p45[0], p45[1], n6]
            self._macs[key] = ":".join(f"{b:02x}" for b in new)
        return self._macs[key]

    def ssid(self, ssid: str) -> str:
        # Hidden SSIDs (empty, or iw's escaped NUL bytes) identify nothing;
        # keep them so the parser still sees a hidden network.
        if re.fullmatch(r"(?:\\x00)*", ssid):
            return ssid
        if ssid not in self._ssids:
            self._ssids[ssid] = f"ssid-{len(self._ssids) + 1}"
        return self._ssids[ssid]

    def collect(self, text: str) -> None:
        for m in self.MAC_RE.finditer(text):
            self.mac(m.group(1))

    def text(self, text: str) -> str:
        # 1. colon-form MACs
        text = self.MAC_RE.sub(lambda m: self.mac(m.group(1)) if m.group(1)[0].isalnum() else m.group(1), text)
        # 2. RNR (IE 201), BEFORE the generic byte-run pass so each neighbour
        #    BSSID is mapped exactly once (mapping fake bytes again would
        #    diverge from the oracle's single mapping).
        #    RNR: rewrite every neighbor BSSID and short-SSID field
        #     structurally — neighbors may never be heard directly, so their
        #     MACs are not in the colon-form map yet.
        def rnr(m: "re.Match") -> str:
            raw = bytearray(bytes.fromhex(m.group(2).replace(" ", "")))
            pos = 0
            while pos + 4 <= len(raw):
                count = ((raw[pos] >> 4) & 0x0F) + 1
                info_len = raw[pos + 1]
                pos += 4
                for _ in range(count):
                    if info_len == 0 or pos + info_len > len(raw):
                        pos = len(raw)
                        break
                    if info_len >= 7:
                        real = ":".join(f"{b:02x}" for b in raw[pos + 1:pos + 7])
                        raw[pos + 1:pos + 7] = bytes.fromhex(self.mac(real).replace(":", ""))
                    if info_len >= 11:
                        raw[pos + 7:pos + 11] = self._h("short-ssid", bytes(raw[pos + 7:pos + 11]).hex())[:4]
                    pos += info_len
            return m.group(1) + " ".join(f"{b:02x}" for b in raw)
        text = re.sub(r"(?m)^(\tUnknown IE \(201\): )([0-9a-f ]+?)\s*$", rnr, text)
        # 3. raw byte runs of known MACs inside hex dumps ("aa bb cc dd ee ff")
        for real, fake in list(self._macs.items()):
            text = text.replace(real.replace(":", " "), fake.replace(":", " "))
        # 3. raw IEs the parser does not use can hide SSIDs/names (e.g. the
        #    Multiple-BSSID element 71 carries other SSIDs): drop them.
        keep_ids = {"54", "133", "150", "201", "244"}
        text = re.sub(
            r"(?m)^\tUnknown IE \((\d+)\):.*\n",
            lambda m: m.group(0) if m.group(1) in keep_ids else "",
            text,
        )
        # 3c. vendor IE data can embed MACs/serials: keep only short payloads
        #     (≤ 5 bytes, e.g. the Ruckus TX-power element), else the subtype.
        text = re.sub(
            r"(?m)^(\tVendor specific: OUI [0-9a-f:]{8}, data: )([0-9a-f ]+?)\s*$",
            lambda m: m.group(0) if len(m.group(2).split()) <= 5 else m.group(1) + m.group(2).split()[0],
            text,
        )
        # 4. printable text inside vendor IE / Cisco IE 133 data (AP names,
        #    model strings): overwrite with 'x', keeping byte lengths.
        def mask_hex(m: "re.Match") -> str:
            raw = bytearray(bytes.fromhex(m.group(2).replace(" ", "")))
            i = 0
            while i < len(raw):
                j = i
                while j < len(raw) and 32 <= raw[j] < 127:
                    j += 1
                if j - i >= 4:
                    raw[i:j] = b"x" * (j - i)
                i = max(j, i + 1)
            return m.group(1) + " ".join(f"{b:02x}" for b in raw)
        text = re.sub(r"(?m)^(\tVendor specific: OUI [0-9a-f:]{8}, data: )([0-9a-f ]+?)\s*$", mask_hex, text)
        text = re.sub(r"(?m)^(\tUnknown IE \(133\): )([0-9a-f ]+?)\s*$", mask_hex, text)
        # 5. WPS identity strings (serials, models, UUIDs); keep Manufacturer
        text = re.sub(
            r"(?m)^(\t\t \* (?:Device name|Model|Model Number|Serial Number|UUID|Primary Device Type): ).*$",
            lambda m: m.group(1) + "redacted",
            text,
        )
        # 6. SSID lines (iw prints them escaped; map the printed form)
        def ssid_line(m: "re.Match") -> str:
            return m.group(1) + self.ssid(m.group(2))
        text = re.sub(r"(?m)^(\tSSID: )(.*)$", ssid_line, text)
        text = re.sub(r"(?m)^(\t\tSSID: )(.*)$", ssid_line, text)
        return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iface", help="wireless interface (default: first managed)")
    ap.add_argument("--save-fixture", metavar="NAME", help="store iw dump + oracle under tests/fixtures/NAME")
    ap.add_argument(
        "--no-anonymize",
        action="store_true",
        help="keep real BSSIDs/SSIDs in the saved fixture (never commit such a fixture)",
    )
    args = ap.parse_args()

    iface = args.iface or (_detect_wifi_ifaces() or [None])[0]
    if not iface:
        print("No managed Wi-Fi interface found.")
        return 2

    # Read both views back-to-back; only identical observations (same TSF)
    # are compared, so a scan landing in between cannot cause false alarms.
    oracle = ie_oracle.oracle_for_iface(iface)
    # Exactly what the app reads: `scan dump -u` merged with `scan dump -b`
    iw_text, iw_b_text = iw_scan_texts(iface)
    ours = parse_iw_scan_merged(iw_text, iw_b_text)
    tsf_iw = iw_tsf_by_bssid(iw_text)

    common = [b for b in ours if b in oracle and tsf_iw.get(b) == oracle[b]["tsf"]]
    skipped = len([b for b in ours if b in oracle]) - len(common)
    total_mismatch = 0
    per_field = {k: [0, 0] for k in ie_oracle.COMPARED}  # [compared, mismatched]
    for b in sorted(common):
        mine = ie_oracle.normalize_wavescope(ours[b])
        ref = oracle[b]["values"]
        diffs = ie_oracle.compare(mine, ref)
        for k in ie_oracle.COMPARED:
            if mine.get(k) not in (None, "", [], ()) or ref.get(k) not in (None, "", [], ()):
                per_field[k][0] += 1
        for k, a, w in diffs:
            per_field[k][1] += 1
            total_mismatch += 1
            print(f"MISMATCH {b} {ours[b].get('ssid', '')!r:24} {k:18} wavescope={a!r}  wireshark={w!r}")

    print(f"\nInterface {iface}: {len(common)} BSS compared ({skipped} skipped: scan cache changed between reads)")
    print(f"{'field':20} {'compared':>9} {'mismatch':>9}")
    for k, (n, m) in per_field.items():
        if n:
            print(f"{k:20} {n:9} {m:9}")
    print("RESULT:", "PASS" if total_mismatch == 0 else f"FAIL ({total_mismatch} mismatches)")

    if args.save_fixture:
        fx = os.path.join(ROOT, "tests", "fixtures", args.save_fixture)
        os.makedirs(fx, exist_ok=True)
        values = {b: dict(oracle[b]["values"]) for b in common}
        if not args.no_anonymize:
            anon = Anonymizer()
            for t in (iw_text, iw_b_text):
                anon.collect(t)
            # map SSIDs in the same order the iw text would, then rewrite
            iw_text, iw_b_text = anon.text(iw_text), anon.text(iw_b_text)
            anon_vals = {}
            for b, v in values.items():
                if v.get("ssid") is not None:
                    v["ssid"] = anon.ssid(_iw_escape(v["ssid"]))
                if v.get("mld_mac"):
                    v["mld_mac"] = anon.mac(v["mld_mac"])
                if v.get("rnr_bssids"):
                    v["rnr_bssids"] = sorted(anon.mac(b) for b in v["rnr_bssids"])
                anon_vals[anon.mac(b)] = v
            values = anon_vals
        with open(os.path.join(fx, "iw_scan.txt"), "w", encoding="utf-8") as fh:
            fh.write(iw_text)
        with open(os.path.join(fx, "iw_scan_b.txt"), "w", encoding="utf-8") as fh:
            fh.write(iw_b_text)
        ie_oracle.save_json(os.path.join(fx, "oracle.json"), values)
        print(f"Saved fixture: {fx} ({len(common)} BSS{'' if args.no_anonymize else ', anonymized'})")
    return 0 if total_mismatch == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
