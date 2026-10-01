"""Settings dialog: one place for every preference.

Pages: General · Graph · Columns · Labels · Issues · Find AP.
The dialog edits copies; OK/Apply hand them to the main window
(apply_settings), which owns persistence.  Toolbar controls (refresh,
linger, theme) stay as quick shortcuts for the same values.
"""

from __future__ import annotations

import dataclasses
from typing import List

from .core import *  # noqa: F401,F403
from .annotations import is_valid_pattern, normalize_pattern
from .beeper import find_player, ToneBeeper
from .column_profiles import ColumnProfile
from .issues import CHECKS, IssueSettings

_COLUMN_LABEL = dict(zip(COLUMN_KEYS, COLUMN_HEADERS))
_COLUMN_LABEL["inuse"] = "▲ Connected"


class SettingsDialog(QDialog):
    def __init__(self, mw, parent=None):
        super().__init__(parent if parent is not None else (mw if isinstance(mw, QWidget) else None))
        self._mw = mw
        self.setWindowTitle(f"{APP_NAME} — Settings")
        self.resize(820, 560)

        outer = QVBoxLayout(self)
        body = QHBoxLayout()
        outer.addLayout(body, 1)
        self._nav = QListWidget()
        self._nav.setFixedWidth(150)
        self._pages = QStackedWidget()
        body.addWidget(self._nav)
        body.addWidget(self._pages, 1)
        self._nav.currentRowChanged.connect(self._pages.setCurrentIndex)

        for title, builder in (
            ("General", self._page_general),
            ("Graph", self._page_graph),
            ("Columns", self._page_columns),
            ("Labels", self._page_labels),
            ("Issues", self._page_issues),
            ("Find AP", self._page_find),
        ):
            self._nav.addItem(title)
            self._pages.addWidget(builder())
        self._nav.setCurrentRow(0)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._ok)
        btns.rejected.connect(self.reject)
        btns.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        outer.addWidget(btns)

    # ── helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _page(title: str, note: str = "") -> tuple:
        w = QWidget()
        lay = QVBoxLayout(w)
        hdr = QLabel(f"<b style='font-size:12pt'>{title}</b>")
        lay.addWidget(hdr)
        if note:
            n = QLabel(note)
            n.setWordWrap(True)
            n.setStyleSheet(f"color:{HTML_MUTED}; font-size:9pt;")
            lay.addWidget(n)
        return w, lay

    # ── General ─────────────────────────────────────────────────────────────

    def _page_general(self) -> QWidget:
        w, lay = self._page("General")
        form = QFormLayout()
        mw = self._mw
        self._theme = QComboBox()
        for i in range(mw._theme_combo.count()):
            self._theme.addItem(mw._theme_combo.itemText(i))
        self._theme.setCurrentIndex(mw._theme_combo.currentIndex())
        form.addRow("Theme", self._theme)
        self._interval = QComboBox()
        for s in REFRESH_INTERVALS:
            self._interval.addItem(f"{s} s", s)
        self._interval.setCurrentIndex(mw._interval_combo.currentIndex())
        form.addRow("Refresh interval", self._interval)
        self._linger = QSpinBox()
        self._linger.setRange(0, 600)
        self._linger.setSuffix(" s")
        self._linger.setValue(mw._linger_spin.value())
        self._linger.setToolTip("Keep vanished APs (dimmed) for this long; 0 = remove immediately")
        form.addRow("Linger", self._linger)
        lay.addLayout(form)

        box = QGroupBox("Data source")
        bl = QVBoxLayout(box)
        self._src_iw = QRadioButton("Kernel scan cache via iw (recommended)")
        self._src_nm = QRadioButton("NetworkManager + iw (legacy)")
        (self._src_iw if mw._data_source == "iw" else self._src_nm).setChecked(True)
        bl.addWidget(self._src_iw)
        bl.addWidget(self._src_nm)
        lay.addWidget(box)
        lay.addStretch()
        return w

    # ── Graph ───────────────────────────────────────────────────────────────

    def _page_graph(self) -> QWidget:
        w, lay = self._page(
            "Channel graph",
            "SSIDs that share one radio are drawn as a single shape; choose what its label shows. "
            "Hovering the label, or selecting one of its SSIDs, always lists every SSID.",
        )
        form = QFormLayout()
        self._label_mode = QComboBox()
        g = self._mw._channel_graph
        for key, text in g.LABEL_MODES:
            self._label_mode.addItem(text, key)
        self._label_mode.setCurrentIndex(max(0, self._label_mode.findData(g.label_mode())))
        form.addRow("Radios with several SSIDs", self._label_mode)
        lay.addLayout(form)
        lay.addStretch()
        return w

    # ── Columns ─────────────────────────────────────────────────────────────

    def _page_columns(self) -> QWidget:
        w, lay = self._page(
            "Column profiles",
            "Tick the columns to show and drag to reorder. Pinned columns stay in view while scrolling "
            "sideways. Built-in profiles can be used as templates: change them and 'Save as…'.",
        )
        self._store = self._mw._profile_store
        top = QHBoxLayout()
        self._prof = QComboBox()
        self._prof.addItems(self._store.names())
        self._prof.setCurrentText(self._mw._active_profile)
        self._prof.currentTextChanged.connect(self._load_profile)
        top.addWidget(QLabel("Profile:"))
        top.addWidget(self._prof, 1)
        b_save = QPushButton("Save")
        b_save.clicked.connect(lambda: self._save_profile(self._prof.currentText()))
        b_as = QPushButton("Save as…")
        b_as.clicked.connect(self._save_profile_as)
        self._b_del = QPushButton("Delete")
        self._b_del.clicked.connect(self._delete_profile)
        for b in (b_save, b_as, self._b_del):
            top.addWidget(b)
        lay.addLayout(top)

        self._cols = QListWidget()
        self._cols.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        lay.addWidget(self._cols, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Pinned leading columns:"))
        self._pinned = QSpinBox()
        self._pinned.setRange(0, 8)
        row.addWidget(self._pinned)
        row.addStretch()
        lay.addLayout(row)
        self._load_profile(self._prof.currentText())
        return w

    def _load_profile(self, name: str) -> None:
        p = self._store.get(name)
        self._cols.clear()
        for key in p.columns + [k for k in COLUMN_KEYS if k not in p.columns]:
            it = QListWidgetItem(_COLUMN_LABEL.get(key, key))
            it.setData(Qt.ItemDataRole.UserRole, key)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            it.setCheckState(Qt.CheckState.Checked if key in p.columns else Qt.CheckState.Unchecked)
            self._cols.addItem(it)
        self._pinned.setValue(p.pinned)
        self._b_del.setEnabled(name not in self._store.builtin_names())

    def _edited_profile(self, name: str) -> ColumnProfile:
        cols = [
            self._cols.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._cols.count())
            if self._cols.item(i).checkState() == Qt.CheckState.Checked
        ]
        return ColumnProfile(name, cols, self._pinned.value())

    def _save_profile(self, name: str) -> None:
        if name in self._store.builtin_names():
            self._save_profile_as()
            return
        err = self._store.save(self._edited_profile(name))
        if err:
            QMessageBox.warning(self, "Column profiles", err)

    def _save_profile_as(self) -> None:
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:")
        if not ok or not name.strip():
            return
        err = self._store.save(self._edited_profile(name.strip()))
        if err:
            QMessageBox.warning(self, "Column profiles", err)
            return
        self._prof.blockSignals(True)
        self._prof.clear()
        self._prof.addItems(self._store.names())
        self._prof.setCurrentText(name.strip())
        self._prof.blockSignals(False)
        self._b_del.setEnabled(True)

    def _delete_profile(self) -> None:
        name = self._prof.currentText()
        if name in self._store.builtin_names():
            return
        self._store.delete(name)
        self._prof.clear()
        self._prof.addItems(self._store.names())

    # ── Labels ──────────────────────────────────────────────────────────────

    def _page_labels(self) -> QWidget:
        w, lay = self._page(
            "BSSID labels",
            "Label BSSIDs, e.g. 'Room 204 AP'. Patterns may use * and ? — 74:11:b2:c7:22:4* labels all "
            "16 BSSIDs of one AP. An exact BSSID wins over a pattern; the longest pattern wins otherwise.",
        )
        self._labels = QTableWidget(0, 2)
        self._labels.setHorizontalHeaderLabels(["BSSID or pattern", "Label"])
        self._labels.horizontalHeader().setStretchLastSection(True)
        self._labels.verticalHeader().hide()
        for pat, label in self._mw._annotations.items():
            self._add_label_row(pat, label)
        self._labels.resizeColumnToContents(0)
        lay.addWidget(self._labels, 1)
        row = QHBoxLayout()
        b_add = QPushButton("Add")
        b_add.clicked.connect(lambda: self._add_label_row("", ""))
        b_rm = QPushButton("Remove")
        b_rm.clicked.connect(lambda: [self._labels.removeRow(r) for r in sorted({i.row() for i in self._labels.selectedIndexes()}, reverse=True)])
        row.addWidget(b_add)
        row.addWidget(b_rm)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _add_label_row(self, pattern: str, label: str) -> None:
        r = self._labels.rowCount()
        self._labels.insertRow(r)
        self._labels.setItem(r, 0, QTableWidgetItem(pattern))
        self._labels.setItem(r, 1, QTableWidgetItem(label))

    def _label_items(self) -> List[tuple]:
        out = []
        for r in range(self._labels.rowCount()):
            p = (self._labels.item(r, 0).text() if self._labels.item(r, 0) else "").strip()
            l = (self._labels.item(r, 1).text() if self._labels.item(r, 1) else "").strip()  # noqa: E741
            if p or l:
                out.append((p, l))
        return out

    # ── Issues ──────────────────────────────────────────────────────────────

    def _page_issues(self) -> QWidget:
        w, lay = self._page("Issue checks", "Checks shown on the Issues tab.")
        cfg: IssueSettings = self._mw._issue_cfg
        grid = QFormLayout()
        self._checks = {}
        for key, (sev, desc) in CHECKS.items():
            cb = QCheckBox(f"{desc}  ({sev})")
            cb.setChecked(cfg.enabled.get(key, True))
            self._checks[key] = cb
            grid.addRow(cb)
        lay.addLayout(grid)
        thr = QFormLayout()
        self._thr_overlap = QSpinBox()
        self._thr_overlap.setRange(-100, -30)
        self._thr_overlap.setSuffix(" dBm")
        self._thr_overlap.setValue(cfg.overlap_dbm)
        thr.addRow("2.4 GHz overlap: ignore neighbours weaker than", self._thr_overlap)
        self._thr_util = QSpinBox()
        self._thr_util.setRange(10, 100)
        self._thr_util.setSuffix(" %")
        self._thr_util.setValue(cfg.util_pct)
        thr.addRow("High channel utilization from", self._thr_util)
        self._thr_ssids = QSpinBox()
        self._thr_ssids.setRange(1, 16)
        self._thr_ssids.setValue(cfg.max_ssids)
        thr.addRow("Many SSIDs on one radio: more than", self._thr_ssids)
        self._thr_cong = QSpinBox()
        self._thr_cong.setRange(10, 100)
        self._thr_cong.setValue(cfg.congestion_score)
        thr.addRow("Congestion score from", self._thr_cong)
        lay.addLayout(thr)
        lay.addStretch()
        return w

    # ── Find AP ─────────────────────────────────────────────────────────────

    def _page_find(self) -> QWidget:
        player = find_player()
        w, lay = self._page(
            "Find AP",
            "Right-click an AP ▸ Find this AP… opens a signal meter whose beep gets faster and higher as "
            "the signal gets stronger. While it is open the refresh interval is set to 1 s.",
        )
        self._sound = QCheckBox("Beep by default")
        self._sound.setChecked(self._mw._find_sound_default)
        lay.addWidget(self._sound)
        lay.addWidget(QLabel(f"Audio player: {player or 'none found (pw-play / paplay / aplay) — system beep'}"))
        b = QPushButton("Test tone")
        b.clicked.connect(self._test_tone)
        lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch()
        return w

    def _test_tone(self) -> None:
        if not hasattr(self, "_test_beeper"):
            self._test_beeper = ToneBeeper()
        self._test_beeper.beep(-50)

    # ── apply ───────────────────────────────────────────────────────────────

    def _apply(self) -> bool:
        bad = [p for p, _ in self._label_items() if not is_valid_pattern(p)]
        if bad:
            QMessageBox.warning(self, "Labels", "Not a BSSID or BSSID pattern:\n" + "\n".join(bad))
            self._nav.setCurrentRow(3)
            return False
        cfg = dataclasses.replace(
            self._mw._issue_cfg,
            enabled={k: cb.isChecked() for k, cb in self._checks.items()},
            overlap_dbm=self._thr_overlap.value(),
            util_pct=self._thr_util.value(),
            max_ssids=self._thr_ssids.value(),
            congestion_score=self._thr_cong.value(),
        )
        self._mw.apply_settings(
            theme_index=self._theme.currentIndex(),
            interval_index=self._interval.currentIndex(),
            linger_s=self._linger.value(),
            source="iw" if self._src_iw.isChecked() else "nm",
            label_mode=self._label_mode.currentData(),
            profile=self._prof.currentText(),
            profile_override=self._edited_profile(self._prof.currentText()),
            labels=[(normalize_pattern(p), l) for p, l in self._label_items()],
            issue_cfg=cfg,
            find_sound=self._sound.isChecked(),
        )
        return True

    def _ok(self) -> None:
        if self._apply():
            self.accept()

    def done(self, r):
        if hasattr(self, "_test_beeper"):
            self._test_beeper.close()
        super().done(r)
