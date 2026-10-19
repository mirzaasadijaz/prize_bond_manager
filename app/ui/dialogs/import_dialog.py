"""Import bond numbers from a CSV, Excel or Word file (with a preview first)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout,
                             QLineEdit, QPlainTextEdit, QSpinBox, QVBoxLayout)

from ...models import AddResult
from ...processing.importer import (ImportOptions, ParsedFile, commit, held_in_database,
                                    load_records, plan_groups)
from ...processing.parsers import FILE_DIALOG_FILTER, ParseError
from ..context import AppContext
from ..table_model import Col
from ..widgets import TablePanel, button, dash, label, pick_open_file, set_role, warn
from .common import DateField, DenominationBox, LocationField

PREVIEW_ROWS = 500
REPEATED = "(repeated in this copy - ignored)"

MODES = [
    ("Automatic: use the Copy column or 'Copy 1' headings if the file has them, "
     "otherwise one copy per file / sheet", "auto"),
    ("One copy for the whole file", "single"),
    ("Split into copies of a fixed number of bonds", "chunks"),
    ("No copies (loose bonds)", "none"),
]


class ImportDialog(QDialog):
    COLUMNS = [
        Col("number", "Bond number", 120, sort_key="num"),
        Col("price", "Price (Rs)", 100, "right", fmt=lambda v, r: dash(v)),
        Col("date", "Purchased", 110, fmt=dash),
        Col("position", "Position", 80, "right", fmt=dash),
        Col("location", "Location", 130, fmt=dash),
        Col("copy", "Copy it goes into", 240, fmt=lambda v, r: v or "(loose)"),
    ]

    def __init__(self, ctx: AppContext, parent=None, path: str | None = None):
        super().__init__(parent)
        self.ctx, self.db = ctx, ctx.db
        self.parsed: ParsedFile | None = None
        self.result: AddResult | None = None
        self.setWindowTitle("Import bonds from a file")
        self.resize(900, 760)

        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("Choose a .csv, .xlsx or .docx file")
        browse = button("Browse...")
        browse.clicked.connect(self._browse)
        file_row = QHBoxLayout()
        file_row.addWidget(self.path_edit, 1)
        file_row.addWidget(browse)

        self.mode = QComboBox()
        for text, value in MODES:
            self.mode.addItem(text, value)
        self.chunk = QSpinBox()
        self.chunk.setRange(1, 100000)
        self.chunk.setValue(100)
        self.chunk.setSuffix(" bonds per copy")
        self.chunk.setEnabled(False)
        self.copy_name = QLineEdit()
        self.copy_name.setPlaceholderText("(file name)")
        self.price = DenominationBox(allow_blank=True)
        self.date = DateField()
        self.location = LocationField(self.db)
        self.location.setToolTip("Optional. Used for bonds whose row in the file has no Location "
                                 "of its own (a 'Location' column in the file is read "
                                 "automatically).")
        self.skip_existing = QCheckBox("Skip numbers I already have")
        self.skip_existing.setToolTip(
            "Off (default): a number you already hold is added again, as a bond of its own. The "
            "same number may sit in several copies - when it is drawn, all of them win.\n"
            "On: numbers already in your list are left out.")
        options = QGroupBox("How to import")
        form = QFormLayout(options)
        form.addRow("Copies", self.mode)
        form.addRow("", self.chunk)
        form.addRow("Copy name (or prefix)", self.copy_name)
        form.addRow("Price for bonds without one (Rs)", self.price)
        form.addRow("Date for bonds without one", self.date)
        form.addRow("Location for bonds without one", self.location)
        form.addRow("", self.skip_existing)

        self.summary = label("", wrap=True)
        self.held_note = label("", "muted", wrap=True)
        self.held_note.hide()
        self.plan = label("", "muted", wrap=True)
        self.problems = QPlainTextEdit()
        self.problems.setReadOnly(True)
        self.problems.setMaximumHeight(84)
        self.problems.hide()
        self.preview = TablePanel(self.COLUMNS, toolbar=False, empty_text="Choose a file to preview it.")

        self.import_button = button("Import", "primary")
        self.import_button.clicked.connect(self._import)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(self.import_button)

        layout = QVBoxLayout(self)
        layout.addLayout(file_row)
        layout.addWidget(options)
        layout.addWidget(self.summary)
        layout.addWidget(self.plan)
        layout.addWidget(self.held_note)
        layout.addWidget(self.problems)
        layout.addWidget(label(f"Preview (first {PREVIEW_ROWS} bonds)", "section"))
        layout.addWidget(self.preview, 1)
        layout.addLayout(footer)

        self.mode.currentIndexChanged.connect(self._refresh)
        self.chunk.valueChanged.connect(self._refresh)
        self.copy_name.textChanged.connect(self._refresh)
        self.price.editTextChanged.connect(self._refresh)
        self.date.edit.dateChanged.connect(self._refresh)
        self.location.textChanged.connect(self._refresh)
        self.skip_existing.toggled.connect(self._refresh)
        self._held_cache: dict[tuple, tuple[int, list[str]]] = {}
        self._refresh()
        if path:
            self.load(path)

    # -- loading ---------------------------------------------------------------
    def _browse(self) -> None:
        path = pick_open_file(self, "Choose a file with bond numbers", FILE_DIALOG_FILTER)
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        self.path_edit.setText(path)
        self._held_cache.clear()
        try:
            self.parsed = load_records(path)
        except ParseError as exc:
            self.parsed = None
            self._show_error(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - unexpected file problem, keep the dialog usable
            self.parsed = None
            self._show_error(f"Could not read this file: {exc}")
            return
        if not self.parsed.records:
            self._show_error("No bond numbers were found in this file.")
            return
        if self.parsed.missing_denomination:
            self.price.setEnabled(True)
            self.price.setCurrentIndex(0)           # force a deliberate choice
        else:
            self.price.setEnabled(False)
            self.price.setCurrentIndex(0)
        if not self.copy_name.text() and self.parsed.stem:
            self.copy_name.setPlaceholderText(self.parsed.stem)
        self._refresh()

    def _show_error(self, text: str) -> None:
        self.summary.setText(text)
        set_role(self.summary, "problem")
        self.plan.setText("")
        self.held_note.hide()
        self.problems.hide()
        self.preview.set_rows([])
        self.import_button.setEnabled(False)

    # -- preview ------------------------------------------------------------------
    def options(self) -> ImportOptions:
        return ImportOptions(mode=self.mode.currentData(), copy_name=self.copy_name.text().strip(),
                             chunk_size=self.chunk.value(),
                             default_denomination=self.price.value(),
                             default_date=self.date.value(),
                             default_location=self.location.value(),
                             skip_existing=self.skip_existing.isChecked())

    def _held(self, options: ImportOptions) -> tuple[int, list[str]]:
        """Numbers of the file that are already in the database (cached per default price)."""
        key = (options.default_denomination,)
        if key not in self._held_cache:
            self._held_cache[key] = held_in_database(self.db, self.parsed.records,
                                                     options.default_denomination)
        return self._held_cache[key]

    def _refresh(self, *_) -> None:
        self.chunk.setEnabled(self.mode.currentData() == "chunks")
        parsed = self.parsed
        if parsed is None or not parsed.records:
            self.import_button.setEnabled(False)
            return
        options = self.options()
        groups = plan_groups(parsed, options)
        self.summary.setText(parsed.summary() + ".")
        set_role(self.summary, None)
        if groups and groups[0].name is None:
            self.plan.setText("The bonds will be added without copies.")
        else:
            names = ", ".join(f"{g.name} ({len(g.items):,})" for g in groups[:6])
            more = f", ... (+{len(groups) - 6} more)" if len(groups) > 6 else ""
            self.plan.setText(f"{len(groups)} copy/copies will be created: {names}{more}"
                              + self._shared_in_file(groups, options))
        notes = list(parsed.problems[:40])
        if parsed.duplicates:
            notes.append(f"Repeated within one entry and ignored: {', '.join(parsed.duplicates[:12])}"
                         + (" ..." if len(parsed.duplicates) > 12 else ""))
        repeated = [number for g in groups for number in g.repeated]
        if repeated:
            notes.append(f"A copy holds each number once - repeated in the same copy and ignored: "
                         f"{', '.join(repeated[:12])}" + (" ..." if len(repeated) > 12 else ""))
        self.problems.setVisible(bool(notes))
        self.problems.setPlainText("\n".join(notes))
        self._show_held(options)

        owner = {id(rec): g.name for g in groups for rec in g.items}
        position_of = {id(rec): pos for g in groups if g.positions
                       for rec, pos in zip(g.items, g.positions)}
        rows = [{"number": rec.display, "num": rec.key,
                 "price": rec.denomination or options.default_denomination,
                 "date": rec.purchase_date or options.default_date,
                 "location": rec.location or options.default_location,
                 "copy": owner[id(rec)] if id(rec) in owner else REPEATED,
                 "position": position_of.get(id(rec))}
                for rec in parsed.records[:PREVIEW_ROWS]]
        self.preview.set_rows(rows)
        self.import_button.setEnabled(not parsed.missing_denomination
                                      or options.default_denomination is not None)

    @staticmethod
    def _shared_in_file(groups, options: ImportOptions) -> str:
        """Note numbers that appear in more than one copy of the file (they win together)."""
        holders: dict[tuple, int] = {}
        for group in groups:
            for rec in group.items:
                ident = (rec.denomination or options.default_denomination, rec.key)
                holders[ident] = holders.get(ident, 0) + 1
        shared = sum(1 for n in holders.values() if n > 1)
        if not shared or len(groups) < 2:
            return ""
        return (f"\n{shared:,} number(s) appear in more than one copy of this file - that is fine: "
                "when such a number is drawn, every bond holding it wins.")

    def _show_held(self, options: ImportOptions) -> None:
        count, examples = self._held(options)
        if not count:
            self.held_note.hide()
            return
        shown = ", ".join(examples) + (" ..." if count > len(examples) else "")
        if options.skip_existing:
            text = (f"{count:,} number(s) of this file are already in your list ({shown}). They "
                    "will be left out.")
        else:
            text = (f"{count:,} number(s) of this file are already in your list ({shown}). They "
                    "will be added again as extra bonds - the same number can sit in several "
                    "copies, and if it is drawn every bond holding it wins. Tick 'Skip numbers I "
                    "already have' to leave them out.")
        self.held_note.setText(text)
        self.held_note.show()

    # -- importing -----------------------------------------------------------------
    def _import(self) -> None:
        if self.parsed is None:
            return
        options = self.options()
        try:
            self.result = commit(self.db, plan_groups(self.parsed, options), options,
                                 Path(self.parsed.path).name)
        except ValueError as exc:
            warn(self, "Cannot import", str(exc))
            return
        self.price.remember()
        self.accept()
