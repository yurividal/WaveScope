"""Table view with pinned (frozen) leading columns, and column-profile application.

FrozenTableView follows Qt's "Frozen Column" example: a second QTableView is
laid over the left edge of the main one, shares its model and selection
model, shows only the pinned columns and scrolls vertically in lockstep.
The main view keeps every column (the pinned ones sit underneath the
overlay), so indexAt(), selection and the context menu work unchanged.
"""

from __future__ import annotations

from typing import List

from .core import *  # noqa: F401,F403
from .column_profiles import ColumnProfile


class FrozenTableView(QTableView):
    # Divider between pinned and scrolling columns — only while scrolled
    # sideways, i.e. when content actually slides underneath the pinned area.
    _FROZEN_SS_FLAT = "QTableView { border: none; }"
    _FROZEN_SS_DIVIDER = "QTableView { border: none; border-right: 1px solid palette(mid); }"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pinned = 0
        self._frozen = QTableView(self)
        fz = self._frozen
        fz.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        fz.verticalHeader().hide()
        fz.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        fz.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fz.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fz.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        fz.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        fz.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        fz.setShowGrid(False)
        fz.setWordWrap(False)
        fz.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        fz.customContextMenuRequested.connect(self._forward_context_menu)
        fz.horizontalHeader().sectionClicked.connect(self._forward_sort)
        fz.setStyleSheet(self._FROZEN_SS_FLAT)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.viewport().stackUnder(fz)
        fz.hide()

        # keep both views in lockstep
        self.horizontalHeader().sectionResized.connect(self._on_section_resized)
        self.horizontalHeader().sectionMoved.connect(lambda *_: self.sync_frozen())
        self.verticalHeader().sectionResized.connect(
            lambda idx, _old, new: self._frozen.setRowHeight(idx, new)
        )
        self.horizontalScrollBar().valueChanged.connect(
            lambda v: fz.setStyleSheet(self._FROZEN_SS_DIVIDER if v > 0 else self._FROZEN_SS_FLAT)
        )
        fz.verticalScrollBar().valueChanged.connect(self.verticalScrollBar().setValue)
        self.verticalScrollBar().valueChanged.connect(fz.verticalScrollBar().setValue)
        self.horizontalHeader().sortIndicatorChanged.connect(
            lambda col, order: fz.horizontalHeader().setSortIndicator(col, order)
        )

    # ── public API ──────────────────────────────────────────────────────────

    def setAlternatingRowColors(self, enable):  # noqa: N802
        super().setAlternatingRowColors(enable)
        self._frozen.setAlternatingRowColors(enable)

    def setModel(self, model):  # noqa: N802 (Qt naming)
        super().setModel(model)
        self._frozen.setModel(model)
        self._frozen.setSelectionModel(self.selectionModel())
        self._frozen.horizontalHeader().setSortIndicatorShown(True)
        self.sync_frozen()

    def setIconSize(self, size):  # noqa: N802
        super().setIconSize(size)
        self._frozen.setIconSize(size)

    def pinned_count(self) -> int:
        return self._pinned

    def set_pinned(self, n: int) -> None:
        self._pinned = max(0, n)
        self.sync_frozen()

    def pinned_logical_columns(self) -> List[int]:
        """The first N *visible* columns in the main view's visual order."""
        hdr = self.horizontalHeader()
        out = []
        for visual in range(hdr.count()):
            logical = hdr.logicalIndex(visual)
            if not hdr.isSectionHidden(logical):
                out.append(logical)
                if len(out) == self._pinned:
                    break
        return out

    def sync_frozen(self) -> None:
        model = self.model()
        fz = self._frozen
        if model is None or self._pinned == 0:
            fz.hide()
            return
        pinned = self.pinned_logical_columns()
        fhdr = fz.horizontalHeader()
        for col in range(model.columnCount()):
            fz.setColumnHidden(col, col not in pinned)
            fz.setColumnWidth(col, self.columnWidth(col))
        # mirror the main view's visual order for the pinned columns
        for target_visual, logical in enumerate(sorted(pinned, key=self.horizontalHeader().visualIndex)):
            fhdr.moveSection(fhdr.visualIndex(logical), target_visual)
        fhdr.setFixedHeight(self.horizontalHeader().height())
        fz.verticalHeader().setDefaultSectionSize(self.verticalHeader().defaultSectionSize())
        fz.show()
        fz.raise_()
        self._update_geometry()

    # ── internals ───────────────────────────────────────────────────────────

    def _on_section_resized(self, logical: int, _old: int, new: int) -> None:
        if self._pinned and logical in self.pinned_logical_columns():
            self._frozen.setColumnWidth(logical, new)
            self._update_geometry()

    def _update_geometry(self) -> None:
        if not self._frozen.isVisible():
            return
        width = sum(self.columnWidth(c) for c in self.pinned_logical_columns())
        self._frozen.setGeometry(
            self.verticalHeader().width() + self.frameWidth(),
            self.frameWidth(),
            width,
            self.viewport().height() + self.horizontalHeader().height(),
        )

    def _forward_context_menu(self, pos) -> None:
        mapped = self._frozen.viewport().mapTo(self.viewport(), pos)
        self.customContextMenuRequested.emit(mapped)

    def _forward_sort(self, logical: int) -> None:
        hdr = self.horizontalHeader()
        if hdr.sortIndicatorSection() == logical:
            order = (
                Qt.SortOrder.AscendingOrder
                if hdr.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
                else Qt.SortOrder.DescendingOrder
            )
        else:
            order = Qt.SortOrder.DescendingOrder
        self.sortByColumn(logical, order)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._update_geometry()

    def updateGeometries(self):  # noqa: N802 (Qt override: header heights change)
        super().updateGeometries()
        self._update_geometry()

    def moveCursor(self, action, modifiers):  # noqa: N802
        # Keyboard navigation: keep the current cell visible beside the pinned area.
        current = super().moveCursor(action, modifiers)
        if (
            action == QAbstractItemView.CursorAction.MoveLeft
            and current.column() not in self.pinned_logical_columns()
            and self.visualRect(current).topLeft().x() < self._frozen.width()
        ):
            new_value = self.horizontalScrollBar().value() + self.visualRect(current).topLeft().x() - self._frozen.width()
            self.horizontalScrollBar().setValue(new_value)
        return current


def apply_profile(view: FrozenTableView, profile: ColumnProfile, auto_hidden: set = frozenset()) -> None:
    """Show *profile*'s columns in its order, hide the rest, pin its first N.

    *auto_hidden* holds logical columns hidden for lack of data (e.g. AP Name
    when no AP advertises one) even if the profile includes them.
    """
    hdr = view.horizontalHeader()
    wanted = [COLUMN_INDEX[k] for k in profile.columns if k in COLUMN_INDEX]
    rest = [i for i in range(len(COLUMN_KEYS)) if i not in wanted]
    for target, logical in enumerate(wanted + rest):
        hdr.moveSection(hdr.visualIndex(logical), target)
    for logical in range(len(COLUMN_KEYS)):
        view.setColumnHidden(logical, logical not in wanted or logical in auto_hidden)
    view.set_pinned(profile.pinned)


def current_layout(view: FrozenTableView) -> ColumnProfile:
    """The view's present visible columns/order as an (unnamed) profile."""
    hdr = view.horizontalHeader()
    cols = []
    for visual in range(hdr.count()):
        logical = hdr.logicalIndex(visual)
        if not hdr.isSectionHidden(logical):
            cols.append(COLUMN_KEYS[logical])
    return ColumnProfile("", cols, view.pinned_count())
