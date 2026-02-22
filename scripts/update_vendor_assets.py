#!/usr/bin/env python3
"""Update WaveScope vendor assets from a Vendors export folder.

Usage:
  python scripts/update_vendor_assets.py /path/to/Vendors
  python scripts/update_vendor_assets.py /path/to/Vendors --overwrite-icons
"""

from __future__ import annotations

import argparse
import json
import plistlib
import shutil
from pathlib import Path
from typing import Dict

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".ico", ".svg"}


def norm_prefix(key: str) -> str:
    s = (key or "").strip().upper().replace("-", ":")
    parts = [p for p in s.split(":") if p]
    if len(parts) >= 3:
        return ":".join(p.zfill(2) for p in parts[:3])
    hexd = "".join(ch for ch in s if ch in "0123456789ABCDEF")
    if len(hexd) >= 6:
        return f"{hexd[0:2]}:{hexd[2:4]}:{hexd[4:6]}"
    return s


def norm_vendor(v: str) -> str:
    return " ".join((v or "").strip().split())


def norm_domain(d: str) -> str:
    d = (d or "").strip().lower()
    if d.startswith("https://"):
        d = d[8:]
    elif d.startswith("http://"):
        d = d[7:]
    return d.rstrip("/")


def load_json_map(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def write_json_map(path: Path, data: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync vendors.json, vendor_urls.json and vendor icons from a Vendors folder."
    )
    parser.add_argument(
        "vendors_dir",
        type=Path,
        help="Path to Vendors folder (must contain vendors.plist and urls.plist)",
    )
    parser.add_argument(
        "--overwrite-icons",
        action="store_true",
        help="Overwrite existing icons when same filename exists.",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent

    source_dir = args.vendors_dir.expanduser().resolve()
    vendors_plist = source_dir / "vendors.plist"
    urls_plist = source_dir / "urls.plist"

    if not source_dir.exists() or not source_dir.is_dir():
        raise SystemExit(f"Vendors folder not found: {source_dir}")
    if not vendors_plist.exists() or not urls_plist.exists():
        raise SystemExit(
            f"Missing plist files in {source_dir} (need vendors.plist and urls.plist)"
        )

    target_vendors_json = repo_root / "assets" / "vendors.json"
    target_urls_json = repo_root / "assets" / "vendor_urls.json"
    target_icons_dir = repo_root / "assets" / "vendor-icons"

    with vendors_plist.open("rb") as fh:
        src_vendors_raw = plistlib.load(fh)
    with urls_plist.open("rb") as fh:
        src_urls_raw = plistlib.load(fh)

    src_vendors: Dict[str, str] = {}
    for k, v in src_vendors_raw.items():
        nk = norm_prefix(str(k))
        nv = norm_vendor(str(v))
        if nk and nv:
            src_vendors[nk] = nv

    src_urls: Dict[str, str] = {}
    for k, v in src_urls_raw.items():
        nk = norm_vendor(str(k))
        nv = norm_domain(str(v))
        if nk and nv:
            src_urls[nk] = nv

    vendors_existing = {
        norm_prefix(k): norm_vendor(v) for k, v in load_json_map(target_vendors_json).items() if k and v
    }
    urls_existing = {
        norm_vendor(k): norm_domain(v) for k, v in load_json_map(target_urls_json).items() if k and v
    }

    merged_vendors = dict(vendors_existing)
    merged_vendors.update(src_vendors)  # latest source wins

    merged_urls = dict(urls_existing)
    merged_urls.update(src_urls)  # latest source wins

    write_json_map(target_vendors_json, merged_vendors)
    write_json_map(target_urls_json, merged_urls)

    target_icons_dir.mkdir(parents=True, exist_ok=True)
    copied_new = 0
    overwritten = 0
    skipped_existing = 0

    for item in source_dir.iterdir():
        if not item.is_file() or item.suffix.lower() not in IMAGE_EXTS:
            continue
        dst = target_icons_dir / item.name
        existed_before = dst.exists()
        if dst.exists() and not args.overwrite_icons:
            skipped_existing += 1
            continue
        shutil.copy2(item, dst)
        if existed_before:
            overwritten += 1
        else:
            copied_new += 1

    print("Vendor asset sync complete")
    print(f"Source Vendors dir: {source_dir}")
    print(f"vendors.json entries: {len(vendors_existing)} -> {len(merged_vendors)}")
    print(f"vendor_urls.json entries: {len(urls_existing)} -> {len(merged_urls)}")
    print(f"icons added: {copied_new}")
    print(f"icons overwritten: {overwritten if args.overwrite_icons else 0}")
    print(f"icons skipped existing: {skipped_existing if not args.overwrite_icons else 0}")
    print(f"updated: {target_vendors_json}")
    print(f"updated: {target_urls_json}")
    print(f"icons dir: {target_icons_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
