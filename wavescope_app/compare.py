"""Side-by-side comparison of two (or more) BSSs, field by field."""

from __future__ import annotations

from typing import List

from .core import *  # noqa: F401,F403
from .fields import FIELDS


class CompareDialog(QDialog):
    """Rows = registry fields, columns = BSSs; differing rows highlighted."""

    def __init__(self, aps: List[AccessPoint], parent=None):
        super().__init__(parent)
        self._aps = aps
        self.setWindowTitle(f"Compare {len(aps)} access points")
        self.resize(900, 700)
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        self._chk_diff = QCheckBox("Only differences")
        self._chk_diff.setChecked(True)
        self._chk_diff.toggled.connect(self._fill)
        top.addWidget(self._chk_diff)
        self._lbl_summary = QLabel("")
        top.addWidget(self._lbl_summary)
        top.addStretch()
        lay.addLayout(top)

        self._table = QTableWidget()
        self._table.setColumnCount(1 + len(aps))
        self._table.setHorizontalHeaderLabels(
            ["Field"] + [f"{a.display_ssid}\n{a.bssid}" for a in aps]
        )
        self._table.verticalHeader().hide()
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setWordWrap(True)
        lay.addWidget(self._table)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self._fill()

    def _rows(self):
        """[(group, label, values, differs)] for every registry field."""
        rows = []
        for f in FIELDS:
            vals = [f.fmt(a) for a in self._aps]
            if not any(vals):
                continue
            rows.append((f.group, f.label, vals, len(set(vals)) > 1))
        return rows

    def _fill(self) -> None:
        rows = self._rows()
        n_diff = sum(1 for r in rows if r[3])
        self._lbl_summary.setText(f"  {n_diff} of {len(rows)} fields differ")
        shown = [r for r in rows if r[3] or not self._chk_diff.isChecked()]
        self._table.setRowCount(len(shown))
        hl = QColor(SEC_OTHER)
        hl.setAlpha(60)
        for i, (group, label, vals, differs) in enumerate(shown):
            item = QTableWidgetItem(f"{group} · {label}")
            self._table.setItem(i, 0, item)
            for j, v in enumerate(vals):
                cell = QTableWidgetItem(v or "—")
                if differs:
                    cell.setBackground(QBrush(hl))
                self._table.setItem(i, j + 1, cell)
        self._table.resizeColumnToContents(0)
        self._table.resizeRowsToContents()
