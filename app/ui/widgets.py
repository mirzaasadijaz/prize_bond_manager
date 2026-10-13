"""Reusable widgets and small helpers shared by every page and dialog."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from PyQt6.QtCore import QEvent, QSettings, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFrame, QHBoxLayout,
                             QLabel, QLineEdit, QMessageBox, QPushButton, QTableView,
                             QVBoxLayout, QWidget)

from ..processing import exporter
from . import theme
from .table_model import Col, RowsProxy, RowsTableModel, RowStyle


# ----------------------------------------------------------------- helpers
def button(text: str, kind: str = "default", tooltip: str | None = None) -> QPushButton:
    """Push button; ``kind`` is 'default', 'primary' or 'danger' (styled in theme.py)."""
    widget = QPushButton(text)
    widget.setProperty("kind", kind)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        widget.setToolTip(tooltip)
    return widget


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def set_role(widget: QWidget, role: str | None) -> None:
    widget.setProperty("role", role)
    repolish(widget)


def money(amount) -> str:
    return "" if amount in (None, "") else f"Rs {int(amount):,}"


def dash(value, row=None) -> str:
    return "-" if value in (None, "") else str(value)


def thousands(value, row=None) -> str:
    return "" if value in (None, "") else f"{int(value):,}"


# --------------------------------------------------------- messages / files
def info(parent, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def warn(parent, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def confirm(parent, title: str, text: str, yes: str = "Yes", danger: bool = False) -> bool:
    box = QMessageBox(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question,
                      title, text, QMessageBox.StandardButton.NoButton, parent)
    accept = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is accept


def _settings() -> QSettings:
    return QSettings("PrizeBondManager", "PrizeBondManager")


def last_dir() -> str:
    try:
        saved = str(_settings().value("last_dir", ""))
    except Exception:
        saved = ""
    return saved if saved and Path(saved).is_dir() else str(Path.home())


def remember_dir(path: Path) -> None:
    try:
        _settings().setValue("last_dir", str(path))
    except Exception:
        pass


def pick_open_file(parent, title: str, file_filter: str) -> str | None:
    path, _ = QFileDialog.getOpenFileName(parent, title, last_dir(), file_filter)
    if not path:
        return None
    remember_dir(Path(path).parent)
    return path


def pick_save_file(parent, title: str, default_name: str, file_filter: str) -> Path | None:
    path, chosen = QFileDialog.getSaveFileName(
        parent, title, str(Path(last_dir()) / default_name), file_filter)
    if not path:
        return None
    target = Path(path)
    if not target.suffix:
        match = re.search(r"\*(\.\w+)", chosen or "")
        target = target.with_suffix(match.group(1) if match else ".xlsx")
    remember_dir(target.parent)
    return target


def export_table(parent, headers: list[str], rows: list[list], default_name: str,
                 sheet_name: str = "Data") -> Path | None:
    """Ask for a file name and save the table as .xlsx or .csv."""
    target = pick_save_file(parent, "Export", f"{default_name}_{date.today().isoformat()}.xlsx",
                            exporter.EXPORT_DIALOG_FILTER)
    if target is None:
        return None
    try:
        exporter.write_table(target, headers, rows, sheet_name)
    except PermissionError:
        warn(parent, "Export failed",
             f"Could not write '{target.name}'. Is it open in another program?")
        return None
    except Exception as exc:  # noqa: BLE001 - show any writer problem to the user
        warn(parent, "Export failed", str(exc))
        return None
    info(parent, "Export complete", f"{len(rows):,} row(s) saved to:\n{target}")
    return target


# ------------------------------------------------------------------ widgets
class StatCard(QFrame):
    """A white card with a caption, one big number and a small note."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(2)
        self.value = label("0", "statvalue")
        self.sub = label("", "muted")
        layout.addWidget(label(title, "muted"))
        layout.addWidget(self.value)
        layout.addWidget(self.sub)

    def set(self, value, sub: str = "") -> None:
        self.value.setText(str(value))
        self.sub.setText(sub)


class PageHeader(QWidget):
    """Title + subtitle on the left, action buttons on the right."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(title, "title"))
        self.subtitle = label(subtitle, "subtitle", wrap=True)
        text.addWidget(self.subtitle)
        outer.addLayout(text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        outer.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget)
        return widget


class Note(QFrame):
    """A soft teal explanatory box."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Note")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self.text = label(text, wrap=True)
        layout.addWidget(self.text)


class _EmptyOverlay(QLabel):
    """Centered hint shown over a table while it has no rows."""

    def __init__(self, view: QTableView):
        super().__init__(view.viewport())
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setStyleSheet(f"color: {theme.MUTED}; background: transparent; padding: 24px;")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        view.viewport().installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
        return False


class _CopyableTable(QTableView):
    """Ctrl+C copies the selected rows as tab-separated text (pastes into Excel)."""

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            rows = sorted({i.row() for i in self.selectionModel().selectedRows()})
            model = self.model()
            lines = ["\t".join(str(model.index(r, c).data() or "")
                               for c in range(model.columnCount())) for r in rows]
            if lines:
                QApplication.clipboard().setText("\n".join(lines))
            return
        super().keyPressEvent(event)


class TablePanel(QWidget):
    """Sortable, searchable table with an Export button.

    Click a header to sort; type in the search box to filter every column.
    Export writes exactly what is on screen (current filter and sort order).
    """

    selection_changed = pyqtSignal()
    row_activated = pyqtSignal(dict)

    def __init__(self, columns: list[Col], export_name: str = "export", sheet_name: str = "Data",
                 row_style: RowStyle | None = None, toolbar: bool = True,
                 placeholder: str = "Search...", empty_text: str = "Nothing to show.",
                 parent=None):
        super().__init__(parent)
        self.columns = columns
        self.export_name = export_name
        self.sheet_name = sheet_name
        self.empty_text = empty_text
        self.model = RowsTableModel(columns, self, row_style)
        self.proxy = RowsProxy(self)
        self.proxy.setSourceModel(self.model)

        self.view = _CopyableTable()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.setWordWrap(False)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(30)
        header = self.view.horizontalHeader()
        header.setStretchLastSection(True)
        header.setHighlightSections(False)
        for index, col in enumerate(columns):
            self.view.setColumnWidth(index, col.width)
        self.overlay = _EmptyOverlay(self.view)

        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        self.export_button = button("Export...", tooltip="Save what is shown as Excel or CSV")
        self.export_button.clicked.connect(self.export)
        self.count_label = label("", "muted")

        self.tools = QHBoxLayout()
        self.tools.setSpacing(8)
        self.tools.addWidget(self.search, 1)
        self.tools.addWidget(self.export_button)
        self._toolbar_visible = toolbar
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        if toolbar:
            layout.addLayout(self.tools)
        else:
            self.search.hide()
            self.export_button.hide()
        layout.addWidget(self.view, 1)
        layout.addWidget(self.count_label)

        self.view.selectionModel().selectionChanged.connect(lambda *_: self.selection_changed.emit())
        self.view.doubleClicked.connect(self._on_double_click)
        self._update_state()

    # -- data -------------------------------------------------------------
    def set_rows(self, rows: list[dict]) -> None:
        self.model.set_rows(rows)
        self._update_state()

    def add_tool(self, widget: QWidget) -> None:
        """Put a filter/control widget in the toolbar, before the Export button."""
        self.tools.insertWidget(self.tools.count() - 1, widget)

    def all_rows(self) -> list[dict]:
        return self.model.rows()

    def visible_rows(self) -> list[dict]:
        return [self.model.row_at(self.proxy.mapToSource(self.proxy.index(r, 0)).row())
                for r in range(self.proxy.rowCount())]

    def selected_rows(self) -> list[dict]:
        indexes = self.view.selectionModel().selectedRows()
        return [self.model.row_at(self.proxy.mapToSource(i).row())
                for i in sorted(indexes, key=lambda i: i.row())]

    def clear_search(self) -> None:
        self.search.clear()

    # -- internals -----------------------------------------------------------
    def _on_search(self, text: str) -> None:
        self.proxy.setFilterFixedString(text.strip())
        self._update_state()

    def _on_double_click(self, index) -> None:
        if index.isValid():
            self.row_activated.emit(self.model.row_at(self.proxy.mapToSource(index).row()))

    def _update_state(self) -> None:
        total, shown = self.model.rowCount(), self.proxy.rowCount()
        if total == 0:
            self.count_label.setText("")
            self.overlay.setText(self.empty_text)
            self.overlay.show()
            self.overlay.setGeometry(self.view.viewport().rect())
        else:
            self.overlay.hide()
            self.count_label.setText(f"{shown:,} of {total:,} shown" if shown != total
                                     else f"{total:,} row(s)")
        self.export_button.setEnabled(shown > 0)

    # -- export ---------------------------------------------------------------
    def export_data(self) -> tuple[list[str], list[list]]:
        columns = [c for c in self.columns if c.export]
        headers = [c.export_title or c.title for c in columns]
        return headers, [[c.export_value(r) for c in columns] for r in self.visible_rows()]

    def export(self) -> Path | None:
        headers, rows = self.export_data()
        return export_table(self, headers, rows, self.export_name, self.sheet_name)
