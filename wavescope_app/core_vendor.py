"""Vendor and OUI subsystem.

Contains manufacturer/OUI resolution, vendor icon/domain helpers,
and OUI download dialog/thread components.
"""

from .core_base import *

# ─────────────────────────────────────────────────────────────────────────────
# OUI / Manufacturer Lookup
# ─────────────────────────────────────────────────────────────────────────────

_oui_full: Optional[Dict[str, str]] = None
_oui_loaded = False
_oui_suffix_unique_vendor: Optional[Dict[str, str]] = None
_vendor_urls: Optional[Dict[str, str]] = None
_vendor_urls_norm: Optional[Dict[str, str]] = None
_vendor_urls_tokens: Optional[Dict[str, set[str]]] = None
_vendor_urls_loaded = False
_vendor_icon_cache: Dict[str, Optional[QIcon]] = {}
_vendor_icon_placeholder: Optional[QIcon] = None
VENDOR_ICON_MAX_W = 42
VENDOR_ICON_MAX_H = 16

# Path where we save the downloaded IEEE OUI database
OUI_DATA_DIR = Path.home() / ".local" / "share" / "wavescope"
OUI_JSON_PATH = OUI_DATA_DIR / "oui.json"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUI_VENDOR_FALLBACK_JSON_PATH = _PROJECT_ROOT / "assets" / "vendors.json"
VENDOR_URLS_JSON_PATH = _PROJECT_ROOT / "assets" / "vendor_urls.json"
VENDOR_ICONS_DIR = _PROJECT_ROOT / "assets" / "vendor-icons"
VENDOR_ICON_EXTS = (".png", ".ico", ".svg", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
OUI_IEEE_URL = "https://standards-oui.ieee.org/"
OUI_IEEE_RE = re.compile(r"([0-9A-F]{2}-[0-9A-F]{2}-[0-9A-F]{2})\s+\(hex\)\s+(.+?)\n")


def _norm_vendor_name(vendor: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (vendor or "").lower())


_MANUF_DISPLAY_SUFFIXES = {
    "inc",
    "ltd",
    "co",
    "corp",
    "llc",
}


def format_manufacturer_display(vendor: str) -> str:
    """Display-only manufacturer cleanup; never modifies DB values."""

    def _prettify_word(word: str) -> str:
        m = re.match(
            r"^([^A-Za-z0-9]*)([A-Za-z0-9][A-Za-z0-9'&\-/\.]*)([^A-Za-z0-9]*)$", word
        )
        if not m:
            return word
        prefix, core, suffix = m.groups()
        if len(core) <= 4:
            return word
        if core != core.upper():
            return word
        if re.search(r"\d", core):
            return word
        if not re.search(r"[A-Z]", core):
            return word
        return f"{prefix}{core.capitalize()}{suffix}"

    text = (vendor or "").strip()
    if not text:
        return ""
    parts = [p for p in text.split() if p]
    while parts:
        tail = re.sub(r"[\.,]+$", "", parts[-1]).lower()
        if tail in _MANUF_DISPLAY_SUFFIXES:
            parts.pop()
            continue
        break
    cleaned = " ".join(parts).strip(" ,")
    if not cleaned:
        return text
    return " ".join(_prettify_word(w) for w in cleaned.split())


_VENDOR_NOISE_TOKENS = {
    "inc",
    "corp",
    "corporation",
    "company",
    "co",
    "co.",
    "ltd",
    "ltd.",
    "limited",
    "llc",
    "gmbh",
    "srl",
    "spa",
    "s.p.a",
    "s.a",
    "ag",
    "nv",
    "plc",
    "group",
    "systems",
    "technology",
    "technologies",
    "electronics",
    "communication",
    "communications",
    "network",
    "networks",
}


def _vendor_tokens(vendor: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", (vendor or "").lower()))
    return {t for t in tokens if t and t not in _VENDOR_NOISE_TOKENS and len(t) > 1}


def _norm_domain(domain: str) -> str:
    d = (domain or "").strip().lower()
    if d.startswith("https://"):
        d = d[8:]
    elif d.startswith("http://"):
        d = d[7:]
    return d.rstrip("/")


def _load_downloaded_oui() -> Dict[str, str]:
    """Load our locally saved IEEE JSON.  Returns {} if not present."""
    if not OUI_JSON_PATH.exists():
        return {}
    try:
        raw: Dict[str, str] = json.loads(OUI_JSON_PATH.read_text(encoding="utf-8"))
        # Normalise keys to AA:BB:CC form (may be stored as AA-BB-CC)
        return {k.replace("-", ":").upper(): v for k, v in raw.items()}
    except Exception:
        return {}


def _load_embedded_oui() -> Dict[str, str]:
    """Load bundled fallback DB from assets/vendors.json."""
    if not OUI_VENDOR_FALLBACK_JSON_PATH.exists():
        return {}
    try:
        raw: Dict[str, str] = json.loads(
            OUI_VENDOR_FALLBACK_JSON_PATH.read_text(encoding="utf-8")
        )
        return {k.replace("-", ":").upper(): v for k, v in raw.items() if v}
    except Exception:
        return {}


def _load_oui_with_precedence() -> Dict[str, str]:
    """Merge OUI DBs with precedence: embedded > downloaded > system."""
    merged: Dict[str, str] = {}
    merged.update(_load_system_oui())
    merged.update(_load_downloaded_oui())
    merged.update(_load_embedded_oui())
    return merged


def _build_unique_oui_suffix_vendor_index(oui_db: Dict[str, str]) -> Dict[str, str]:
    """Build a conservative BB:CC -> vendor map from globally-administered OUIs.

    We only keep suffixes that map to exactly one globally-administered OUI
    prefix, to avoid broad false positives.
    """
    buckets: Dict[str, List[str]] = {}
    for prefix, vendor in (oui_db or {}).items():
        if not prefix or len(prefix) < 8 or not vendor:
            continue
        try:
            first_octet = int(prefix[:2], 16)
        except Exception:
            continue
        if first_octet & 0x02:
            continue
        suffix = prefix[3:8]
        buckets.setdefault(suffix, []).append(prefix)

    resolved: Dict[str, str] = {}
    for suffix, prefixes in buckets.items():
        if len(prefixes) != 1:
            continue
        only_prefix = prefixes[0]
        vendor = (oui_db or {}).get(only_prefix, "")
        if vendor:
            resolved[suffix] = vendor
    return resolved


def _load_vendor_urls() -> Dict[str, str]:
    if not VENDOR_URLS_JSON_PATH.exists():
        return {}
    try:
        raw: Dict[str, str] = json.loads(
            VENDOR_URLS_JSON_PATH.read_text(encoding="utf-8")
        )
        return {k.strip(): _norm_domain(v) for k, v in raw.items() if k and v}
    except Exception:
        return {}


def _ensure_vendor_urls_loaded() -> None:
    global _vendor_urls, _vendor_urls_norm, _vendor_urls_tokens, _vendor_urls_loaded
    if _vendor_urls_loaded:
        return
    _vendor_urls = _load_vendor_urls()
    _vendor_urls_norm = {}
    _vendor_urls_tokens = {}
    for name, domain in (_vendor_urls or {}).items():
        key = _norm_vendor_name(name)
        if key and key not in _vendor_urls_norm:
            _vendor_urls_norm[key] = domain
        _vendor_urls_tokens[name] = _vendor_tokens(name)
    _vendor_urls_loaded = True


def _resolve_vendor_domain(vendor_name: str) -> str:
    _ensure_vendor_urls_loaded()
    if not vendor_name:
        return ""

    if _vendor_urls:
        direct = _vendor_urls.get(vendor_name, "")
        if direct:
            return direct

    query_norm = _norm_vendor_name(vendor_name)
    if not query_norm:
        return ""

    if _vendor_urls_norm:
        exact = _vendor_urls_norm.get(query_norm, "")
        if exact:
            return exact

    if _vendor_urls_norm:
        contains_best = ""
        contains_len = 0
        for key, domain in _vendor_urls_norm.items():
            if key and (key in query_norm or query_norm in key):
                key_len = len(key)
                if key_len > contains_len:
                    contains_best = domain
                    contains_len = key_len
        if contains_best:
            return contains_best

    query_tokens = _vendor_tokens(vendor_name)
    if not query_tokens or not _vendor_urls_tokens or not _vendor_urls:
        return ""

    best_name = ""
    best_score = 0.0
    best_overlap = 0
    for name, tokens in _vendor_urls_tokens.items():
        if not tokens:
            continue
        overlap = len(query_tokens & tokens)
        if overlap == 0:
            continue
        score = overlap / max(1, len(tokens))
        if score > best_score or (
            abs(score - best_score) < 1e-9 and overlap > best_overlap
        ):
            best_name = name
            best_score = score
            best_overlap = overlap

    if best_name and (best_score >= 0.60 or best_overlap >= 2):
        return _vendor_urls.get(best_name, "")
    return ""


def _resolve_vendor_icon_path(vendor_name: str) -> Optional[Path]:
    domain = _resolve_vendor_domain(vendor_name)
    if not domain:
        return None

    base_names = [domain, f"www.{domain}"]
    if domain.startswith("www."):
        base_names.append(domain[4:])

    candidates: List[Path] = []
    for base in base_names:
        for ext in VENDOR_ICON_EXTS:
            candidates.append(VENDOR_ICONS_DIR / f"{base}{ext}")

    for path in candidates:
        if path.exists():
            return path
    return None


def _build_vendor_icon(path: Path) -> Optional[QIcon]:
    # Prefer QIcon pixmap selection first so containers like .ico can pick
    # the best embedded frame for our target size.
    target_w = VENDOR_ICON_MAX_W
    target_h = VENDOR_ICON_MAX_H
    req = max(target_w, target_h) * 8

    source_icon = QIcon(str(path))
    pixmap = source_icon.pixmap(req, req)
    if pixmap.isNull():
        pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None

    img = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    min_x = img.width()
    min_y = img.height()
    max_x = -1
    max_y = -1
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 0:
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y

    if max_x >= min_x and max_y >= min_y:
        img = img.copy(QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1))

    app = QApplication.instance()
    dpr = float(app.devicePixelRatio() if app is not None else 1.0)
    px_w = max(1, int(round(target_w * dpr)))
    px_h = max(1, int(round(target_h * dpr)))

    fit_scale = min(px_w / max(1, img.width()), px_h / max(1, img.height()))

    if fit_scale <= 1.0:
        target_scale = fit_scale
    else:
        min_w = max(1, int(round(px_w * 0.45)))
        min_h = max(1, int(round(px_h * 0.80)))
        desired_scale = max(
            min_w / max(1, img.width()),
            min_h / max(1, img.height()),
            1.0,
        )
        target_scale = min(fit_scale, min(desired_scale, 2.25))

    if abs(target_scale - 1.0) < 1e-6:
        scaled_img = img
    elif target_scale < 1.0:
        scaled_img = img.scaled(
            max(1, int(round(img.width() * target_scale))),
            max(1, int(round(img.height() * target_scale))),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    else:
        scaled_img = img.scaled(
            max(1, int(round(img.width() * target_scale))),
            max(1, int(round(img.height() * target_scale))),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

    canvas_img = QImage(px_w, px_h, QImage.Format.Format_ARGB32)
    canvas_img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas_img)
    x = (px_w - scaled_img.width()) // 2
    y = (px_h - scaled_img.height()) // 2
    painter.drawImage(x, y, scaled_img)
    painter.end()

    canvas = QPixmap.fromImage(canvas_img)
    canvas.setDevicePixelRatio(dpr)
    icon = QIcon(canvas)
    if icon.isNull():
        return None
    return icon


def get_vendor_placeholder_icon() -> QIcon:
    global _vendor_icon_placeholder
    if _vendor_icon_placeholder is not None:
        return _vendor_icon_placeholder

    canvas = QPixmap(VENDOR_ICON_MAX_W, VENDOR_ICON_MAX_H)
    canvas.fill(Qt.GlobalColor.transparent)
    _vendor_icon_placeholder = QIcon(canvas)
    return _vendor_icon_placeholder


def get_vendor_icon(vendor_name: str) -> Optional[QIcon]:
    if not vendor_name:
        return None
    if vendor_name in _vendor_icon_cache:
        return _vendor_icon_cache[vendor_name]

    icon_path = _resolve_vendor_icon_path(vendor_name)
    if icon_path is not None:
        icon = _build_vendor_icon(icon_path)
        if icon is not None:
            _vendor_icon_cache[vendor_name] = icon
            return icon

    _vendor_icon_cache[vendor_name] = None
    return None


def _load_system_oui() -> Dict[str, str]:
    """Fall back to wireshark/ieee-data system files if IEEE JSON not downloaded."""
    candidates = [
        "/usr/share/wireshark/manuf",
        "/usr/share/ieee-data/oui.txt",
        "/usr/share/misc/oui.txt",
        "/usr/share/nmap/nmap-mac-prefixes",
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            db: Dict[str, str] = {}
            with open(path, "r", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        mac_raw = parts[0].strip()
                        vendor = (
                            parts[-1].strip() if len(parts) > 2 else parts[1].strip()
                        )
                        mac = mac_raw.replace("-", ":").upper()
                        if len(mac) >= 8:
                            db[mac[:8]] = vendor
            if db:
                return db
        except Exception:
            pass
    return {}


def reload_oui_db():
    """Force reload of the OUI database (call after a fresh download)."""
    global _oui_full, _oui_loaded, _oui_suffix_unique_vendor, _vendor_urls_loaded
    _oui_full = _load_oui_with_precedence()
    _oui_loaded = True
    _oui_suffix_unique_vendor = None
    _vendor_urls_loaded = False
    _vendor_icon_cache.clear()


def get_manufacturer(bssid: str) -> str:
    global _oui_full, _oui_loaded, _oui_suffix_unique_vendor
    if not _oui_loaded:
        _oui_full = _load_oui_with_precedence()
        _oui_loaded = True
    if not bssid:
        return ""
    mac = bssid.upper().replace("-", ":")
    prefix = mac[:8]
    if _oui_full and prefix in _oui_full:
        return _oui_full[prefix]

    # Some AP radios use locally administered BSSIDs (U/L bit set), which
    # often map to an underlying globally administered vendor OUI with that
    # bit cleared. If direct lookup misses, try clearing the U/L bit.
    try:
        first_octet = int(prefix[:2], 16)
        if first_octet & 0x02:
            ga_octet = first_octet & 0xFD
            ga_prefix = f"{ga_octet:02X}{prefix[2:]}"
            if _oui_full and ga_prefix in _oui_full:
                return _oui_full[ga_prefix]

            # Conservative fallback for locally-administered addresses where
            # only the first OUI octet was transformed by firmware/tooling.
            # We only accept BB:CC suffixes that map to exactly one
            # globally-administered OUI prefix in the current DB.
            if not (first_octet & 0x01):
                if _oui_suffix_unique_vendor is None:
                    _oui_suffix_unique_vendor = _build_unique_oui_suffix_vendor_index(
                        _oui_full or {}
                    )
                suffix = prefix[3:8]
                vendor = (_oui_suffix_unique_vendor or {}).get(suffix, "")
                if vendor:
                    return vendor
    except Exception:
        pass
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# OUI Download Thread + First-Run Dialog
# ─────────────────────────────────────────────────────────────────────────────


class OuiDownloadThread(QThread):
    """Downloads and parses the IEEE OUI text file in a background thread."""

    progress = pyqtSignal(str)  # status message
    finished = pyqtSignal(bool, str)  # success, message

    def run(self):
        try:
            self.progress.emit("Connecting to standards-oui.ieee.org…")
            req = urllib.request.Request(
                OUI_IEEE_URL, headers={"User-Agent": "wavescope-wifi-analyzer/1.0"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.progress.emit("Downloading OUI data (may take a few seconds)…")
                raw = resp.read().decode("utf-8", errors="replace")

            self.progress.emit("Parsing entries…")
            matches = OUI_IEEE_RE.findall(raw)
            db = {m[0].replace("-", ":"): m[1].strip() for m in matches}

            if not db:
                self.finished.emit(False, "No OUI entries found in downloaded data.")
                return

            self.progress.emit(f"Saving {len(db):,} entries…")
            OUI_DATA_DIR.mkdir(parents=True, exist_ok=True)
            OUI_JSON_PATH.write_text(
                json.dumps(db, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            reload_oui_db()
            self.finished.emit(True, f"Downloaded {len(db):,} manufacturer entries.")

        except Exception as exc:
            self.finished.emit(False, str(exc))


class OuiDownloadDialog(QDialog):
    """Modal dialog that offers / performs the IEEE OUI database download."""

    def __init__(self, parent=None, first_run: bool = True):
        super().__init__(parent)
        self._first_run = first_run
        self._thread: Optional[OuiDownloadThread] = None
        self.setWindowTitle("Manufacturer Database")
        self.setMinimumWidth(460)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        if first_run:
            header = QLabel(
                "<b>Download IEEE OUI Manufacturer Database?</b><br><br>"
                "WiFi Analyzer can show the manufacturer name for each "
                'access point (e.g. "TP-Link", "ASUS", "Apple").  '
                "This requires downloading ~4 MB of data from "
                "<tt>standards-oui.ieee.org</tt> (run once, stored locally)."
            )
        else:
            header = QLabel(
                "<b>Update IEEE OUI Manufacturer Database</b><br><br>"
                "This will re-download the latest OUI data (~4 MB) from "
                "<tt>standards-oui.ieee.org</tt> and save it locally."
            )
        header.setWordWrap(True)
        header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(header)

        self._status = QLabel("Ready.")
        self._status.setStyleSheet("color:#8a96b0; font-size:9pt;")
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.hide()
        layout.addWidget(self._progress)

        btns = QDialogButtonBox()
        self._btn_download = btns.addButton(
            "Download", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._btn_skip = btns.addButton(
            "Skip" if first_run else "Close", QDialogButtonBox.ButtonRole.RejectRole
        )
        self._btn_download.clicked.connect(self._start_download)
        self._btn_skip.clicked.connect(self.reject)
        layout.addWidget(btns)

    def _start_download(self):
        self._btn_download.setEnabled(False)
        self._btn_skip.setEnabled(False)
        self._progress.show()
        self._status.setText("Starting…")

        self._thread = OuiDownloadThread(self)
        self._thread.progress.connect(self._status.setText)
        self._thread.finished.connect(self._on_finished)
        self._thread.start()

    def _on_finished(self, ok: bool, msg: str):
        self._progress.hide()
        if ok:
            self._status.setText(f"✓  {msg}")
            self._status.setStyleSheet("color:#4caf50; font-size:9pt;")
            self._btn_skip.setText("Close")
        else:
            self._status.setText(f"✗  {msg}")
            self._status.setStyleSheet("color:#ef5350; font-size:9pt;")
            self._btn_download.setEnabled(True)
        self._btn_skip.setEnabled(True)


# ─────────────────────────────────────────────────────────────────────────────
# Data Model
# ─────────────────────────────────────────────────────────────────────────────
