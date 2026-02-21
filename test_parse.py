#!/usr/bin/env python3
"""Quick smoke test — no display required."""
import sys, ast

with open("main.py") as f:
    src = f.read()
ast.parse(src)
print("Syntax OK")

import main

print("Import OK")
print("Testing nmcli parser…")

# Sample line as nmcli would emit with escaped colons in BSSID
sample = r"*:MyNetwork:AA\:BB\:CC\:DD\:EE\:FF:Infra:6:2437 MHz:270 Mbit/s:85:WPA2:(none):pair_ccmp group_ccmp psk:40"
aps = main.parse_nmcli(sample)
assert len(aps) == 1, f"Expected 1 AP, got {len(aps)}"
ap = aps[0]
assert ap.ssid == "MyNetwork", f"SSID mismatch: {ap.ssid!r}"
assert ap.bssid == "AA:BB:CC:DD:EE:FF", f"BSSID mismatch: {ap.bssid!r}"
assert ap.channel == 6
assert ap.freq_mhz == 2437
assert ap.signal == 85
assert ap.bandwidth_mhz == 40
assert ap.band == "2.4 GHz", f"Band: {ap.band!r}"
assert ap.in_use == True
print(f"  SSID={ap.ssid!r} BSSID={ap.bssid} ch={ap.channel} "
      f"freq={ap.freq_mhz}MHz bw={ap.bandwidth_mhz}MHz "
      f"sig={ap.signal}% ({ap.dbm}dBm) band={ap.band}")
print(f"  Security={ap.security_short!r}  Manufacturer={ap.manufacturer!r}")

# Test manufacturer lookup
m = main.get_manufacturer("E0:3F:49:11:22:33")
print(f"  get_manufacturer('E0:3F:49:…') = {m!r}")

# Test freq → band
assert main.freq_to_band(2437) == "2.4 GHz"
assert main.freq_to_band(5260) == "5 GHz"
assert main.freq_to_band(6000) == "6 GHz"

# Test signal_to_dbm
assert main.signal_to_dbm(100) == -50
assert main.signal_to_dbm(0) == -100

print("All assertions passed ✓")
