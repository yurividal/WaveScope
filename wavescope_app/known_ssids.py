"""Known-SSID store and management dialog.

KnownSSIDStore  — thread-safe, JSON-backed set of user-marked SSIDs.
KnownSSIDDialog — Qt dialog for viewing and editing the list.
"""

from .core import *


KNOWN_SSIDS_PATH = OUI_DATA_DIR / "known_ssids.json"


# ─────────────────────────────────────────────────────────────────────────────
# Store
# ─────────────────────────────────────────────────────────────────────────────

class KnownSSIDStore:
    """Persistent set of user-defined "known" SSIDs.

    The list is saved to *KNOWN_SSIDS_PATH* (same directory as the OUI DB)
    as a plain JSON array of strings.  All mutations save immediately so the
    list survives crashes.
    """

    def __init__(self):
        self._ssids: set[str] = set()
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if KNOWN_SSIDS_PATH.exists():
                data = json.loads(KNOWN_SSIDS_PATH.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._ssids = {s for s in data if isinstance(s, str)}
        except Exception:
            self._ssids = set()

    def _save(self) -> None:
        try:
            KNOWN_SSIDS_PATH.parent.mkdir(parents=True, exist_ok=True)
            KNOWN_SSIDS_PATH.write_text(
                json.dumps(sorted(self._ssids), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ── Mutation ──────────────────────────────────────────────────────────

    def add(self, ssid: str) -> bool:
        """Add *ssid*; return True if it was newly added."""
        if ssid and ssid not in self._ssids:
            self._ssids.add(ssid)
            self._save()
            return True
        return False

    def remove(self, ssid: str) -> bool:
        """Remove *ssid*; return True if it was present."""
        if ssid in self._ssids:
            self._ssids.discard(ssid)
            self._save()
            return True
        return False

    def set_all(self, ssids: list[str]) -> None:
        """Replace the entire list (used by the editor dialog)."""
        self._ssids = {s for s in ssids if s}
        self._save()

    # ── Query ─────────────────────────────────────────────────────────────

    def __contains__(self, ssid: str) -> bool:
        return ssid in self._ssids

    def as_frozenset(self) -> frozenset:
        return frozenset(self._ssids)

    def all_sorted(self) -> list[str]:
        return sorted(self._ssids, key=str.casefold)

    def __len__(self) -> int:
        return len(self._ssids)


# ─────────────────────────────────────────────────────────────────────────────
# Management Dialog
# ─────────────────────────────────────────────────────────────────────────────

class KnownSSIDDialog(QDialog):
    """Dialog for viewing, adding, and removing known SSIDs.

    Emits *changed* whenever the store is modified so the caller can
    refresh the proxy filter.
    """

    changed = pyqtSignal()

    def __init__(self, store: KnownSSIDStore, parent=None):
        super().__init__(parent)
        self._store = store
        self.setWindowTitle(f"Known SSIDs ({len(store)})")
        self.setMinimumSize(420, 380)

        is_dark = (
            self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        )
        bg   = DIALOG_BG_DARK   if is_dark else DIALOG_BG_LIGHT
        fg   = DIALOG_TEXT_DARK if is_dark else DIALOG_TEXT_LIGHT
        bdr  = DIALOG_BORDER_DARK if is_dark else DIALOG_BORDER_LIGHT
        note = DIALOG_NOTE_DARK if is_dark else DIALOG_NOTE_LIGHT
        inp_bg = MENU_BG if is_dark else "#ffffff"
        inp_fg = MENU_TEXT if is_dark else DIALOG_TEXT_LIGHT
        sel_bg = MENU_SELECTED if is_dark else "#cde0f7"

        self.setStyleSheet(
            f"QDialog {{ background:{bg}; color:{fg}; }}"
            f"QLabel {{ color:{fg}; }}"
            f"QListWidget {{"
            f"  background:{inp_bg}; color:{inp_fg};"
            f"  border:1px solid {bdr}; border-radius:4px;"
            f"}}"
            f"QListWidget::item:selected {{ background:{sel_bg}; }}"
            f"QLineEdit {{"
            f"  background:{inp_bg}; color:{inp_fg};"
            f"  border:1px solid {bdr}; border-radius:3px; padding:3px 6px;"
            f"}}"
            f"QPushButton {{"
            f"  color:{BTN_ACCENT}; border:1px solid {BTN_BORDER};"
            f"  border-radius:3px; padding:3px 10px;"
            f"}}"
            f"QPushButton:hover {{ background:{BTN_HOVER_BG}; }}"
            f"QPushButton:disabled {{ color:{note}; border-color:{bdr}; }}"
        )

        vlay = QVBoxLayout(self)
        vlay.setSpacing(8)
        vlay.setContentsMargins(14, 14, 14, 14)

        # ── Description ───────────────────────────────────────────────────
        desc = QLabel(
            "SSIDs in this list can be filtered with the <b>Known</b> toolbar control."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{note}; font-size:9.5pt;")
        vlay.addWidget(desc)

        # ── Search bar ───────────────────────────────────────────────────
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search…")
        self._search.textChanged.connect(self._apply_search)
        vlay.addWidget(self._search)

        # ── List ──────────────────────────────────────────────────────────
        self._list = QListWidget()
        self._list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._list.setSortingEnabled(False)
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        vlay.addWidget(self._list)

        # ── Add row ───────────────────────────────────────────────────────
        add_row = QHBoxLayout()
        self._add_edit = QLineEdit()
        self._add_edit.setPlaceholderText("Type an SSID to add…")
        self._add_edit.returnPressed.connect(self._do_add)
        add_row.addWidget(self._add_edit)
        self._btn_add = QPushButton("＋ Add")
        self._btn_add.setDefault(False)
        self._btn_add.clicked.connect(self._do_add)
        self._add_edit.textChanged.connect(
            lambda t: self._btn_add.setEnabled(bool(t.strip()))
        )
        self._btn_add.setEnabled(False)
        add_row.addWidget(self._btn_add)
        vlay.addLayout(add_row)

        # ── Action buttons ────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._btn_remove = QPushButton("✕ Remove selected")
        self._btn_remove.clicked.connect(self._do_remove)
        self._btn_remove.setEnabled(False)
        btn_row.addWidget(self._btn_remove)
        btn_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        vlay.addLayout(btn_row)

        self._reload_list()

    # ── Internal helpers ──────────────────────────────────────────────────

    def _reload_list(self) -> None:
        query = self._search.text().strip().lower()
        self._list.blockSignals(True)
        self._list.clear()
        for ssid in self._store.all_sorted():
            if query and query not in ssid.lower():
                continue
            self._list.addItem(ssid)
        self._list.blockSignals(False)
        self._sync_buttons()
        # Update title with count
        self.setWindowTitle(f"Known SSIDs  ({len(self._store)})")

    def _apply_search(self, _: str) -> None:
        self._reload_list()

    def _sync_buttons(self) -> None:
        self._btn_remove.setEnabled(bool(self._list.selectedItems()))

    def _do_add(self) -> None:
        ssid = self._add_edit.text().strip()
        if not ssid:
            return
        if self._store.add(ssid):
            self.changed.emit()
        self._add_edit.clear()
        self._reload_list()
        # Scroll to the newly added item
        items = self._list.findItems(ssid, Qt.MatchFlag.MatchExactly)
        if items:
            self._list.scrollToItem(items[0])

    def _do_remove(self) -> None:
        selected = [item.text() for item in self._list.selectedItems()]
        for ssid in selected:
            self._store.remove(ssid)
        if selected:
            self.changed.emit()
        self._reload_list()
