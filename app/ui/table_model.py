"""A light, fast table model over a list of dict rows (plus sort/filter proxy)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PyQt6.QtGui import QBrush, QColor

_ALIGN = {
    "left": int((Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter).value),
    "right": int((Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter).value),
    "center": int((Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter).value),
}


@dataclass
class Col:
    """One column: which dict key it shows and how it is formatted, sorted, exported."""

    key: str
    title: str
    width: int = 110
    align: str = "left"                                   # left | right | center
    fmt: Callable[[Any, dict], str] | None = None         # display text
    numeric: bool = False                                 # sort as numbers (None first)
    sort_key: str | None = None                           # sort by another key of the row
    export: bool = True
    export_raw: bool = False                              # export the raw value, not the text
    export_title: str | None = None                       # heading in exported files

    def text(self, row: dict) -> str:
        value = row.get(self.key)
        if self.fmt:
            return self.fmt(value, row)
        return "" if value is None else str(value)

    def sort_value(self, row: dict):
        value = row.get(self.sort_key or self.key)
        if self.numeric or self.sort_key:
            return -1 if value is None else value
        return self.text(row).casefold()

    def export_value(self, row: dict):
        if self.export_raw:
            return row.get(self.key)
        return self.text(row)


def same_number_col(key: str = "same_number_count", single: str = "1 bond",
                    width: int = 112) -> Col:
    """'Same number' column: how many bonds hold this number (they all win together)."""
    return Col(key, "Same number", width, "right", numeric=True, export_raw=True,
               export_title="Bonds with this number",
               fmt=lambda v, r: f"{v} bonds" if (v or 0) > 1 else single)


# (foreground, background) hex colours for a whole row, or None
RowStyle = Callable[[dict], "tuple[str | None, str | None] | None"]


class RowsTableModel(QAbstractTableModel):
    def __init__(self, columns: list[Col], parent=None, row_style: RowStyle | None = None):
        super().__init__(parent)
        self.columns = columns
        self.row_style = row_style
        self._rows: list[dict] = []

    # -- data access ------------------------------------------------------
    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rows(self) -> list[dict]:
        return self._rows

    def row_at(self, index: int) -> dict:
        return self._rows[index]

    # -- Qt model interface ------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section].title
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = self._rows[index.row()], self.columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return col.text(row)
        if role == Qt.ItemDataRole.UserRole:
            return col.sort_value(row)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return _ALIGN[col.align]
        if role in (Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.BackgroundRole):
            style = self.row_style(row) if self.row_style else None
            if style:
                colour = style[0] if role == Qt.ItemDataRole.ForegroundRole else style[1]
                if colour:
                    return QBrush(QColor(colour))
        return None


class RowsProxy(QSortFilterProxyModel):
    """Sorts on the typed sort value; filters every column by a plain substring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterKeyColumn(-1)
