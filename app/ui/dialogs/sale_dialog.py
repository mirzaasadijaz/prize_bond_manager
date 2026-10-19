"""Record a sale: some of your bonds were sold to somebody else."""
from __future__ import annotations

from collections import defaultdict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QButtonGroup, QComboBox, QCompleter, QDialog, QFormLayout, QGroupBox,
                             QHBoxLayout, QLineEdit, QRadioButton, QVBoxLayout)

from ...db import SaleError
from ...processing.numbers import parse_pattern
from ...processing.sales import parse_amount, prices_for
from ..context import AppContext
from ..table_model import Col
from ..widgets import TablePanel, button, dash, label, money, set_role, warn
from .common import DateField, DenominationBox, LocationField

SHOWN = 6          # numbers named in a message before "..."


def buyer_field(db) -> QLineEdit:
    """Text box for the buyer's name that suggests people you have sold to before."""
    edit = QLineEdit()
    edit.setPlaceholderText("who bought them (optional)")
    names = db.known_buyers()
    if names:
        completer = QCompleter(names, edit)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        edit.setCompleter(completer)
    return edit


def _list_text(items: list[str]) -> str:
    return ", ".join(items[:SHOWN]) + (f" ... (+{len(items) - SHOWN})" if len(items) > SHOWN else "")


class SaleDialog(QDialog):
    """Pick the bonds, say who bought them and for how much.

    Bonds can be handed in (``bonds``, e.g. the selection of the My Bonds page), added by
    number, or added as a whole copy.  A number that is held in several copies is never
    guessed: it is reported, and you choose the copy to say which bond you mean.
    """

    COLUMNS = [
        Col("number", "Bond number", 120, sort_key="num"),
        Col("denomination", "Face value (Rs)", 110, "right", numeric=True,
            fmt=lambda v, r: f"{v:,}"),
        Col("copy_name", "Copy (book)", 140, fmt=dash),
        Col("position", "Position", 80, "right", numeric=True, fmt=dash),
        Col("location", "Kept at", 130, fmt=dash),
        Col("note", "Check", 220, fmt=lambda v, r: v or ""),
    ]

    def __init__(self, ctx: AppContext, parent=None, bonds: list[dict] | None = None):
        super().__init__(parent)
        self.ctx, self.db = ctx, ctx.db
        self.sale_id: int | None = None
        self._bonds: list[dict] = []
        self._ids: set[int] = set()
        self.setWindowTitle("Sell bonds")
        self.resize(940, 800)

        # -- who / when ----------------------------------------------------------------
        self.date = DateField(allow_unknown=False)
        self.buyer = buyer_field(self.db)
        self.contact = QLineEdit()
        self.contact.setPlaceholderText("phone or address (optional)")
        self.location = LocationField(self.db, "where the sale took place (optional)")
        self.note = QLineEdit()
        self.note.setPlaceholderText("optional")
        who = QGroupBox("The sale")
        form = QFormLayout(who)
        form.addRow("Date of sale", self.date)
        form.addRow("Sold to", self.buyer)
        form.addRow("Contact", self.contact)
        form.addRow("Location", self.location)
        form.addRow("Note", self.note)

        # -- which bonds --------------------------------------------------------------
        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText("bond numbers: 100001-100020, 555001 ... (empty = a whole "
                                        "copy)")
        self.copy_combo = QComboBox()
        self.copy_combo.addItem("Any copy", None)
        for copy in self.db.list_copies():
            held = copy["bonds"]
            self.copy_combo.addItem(f"{copy['name']}  ({held} held)", copy["id"])
        self.copy_combo.setToolTip("Limit the numbers to one copy - needed when the same number "
                                   "is held in several copies. With no numbers typed, the whole "
                                   "copy is added.")
        self.price_filter = DenominationBox(allow_blank=True)
        self.price_filter.setToolTip("Only bonds of this price (leave empty for any)")
        self.price_filter.setMaximumWidth(110)
        add = button("Add", "primary")
        add.clicked.connect(self._add)
        self.pattern.returnPressed.connect(self._add)
        remove = button("Remove selected")
        remove.clicked.connect(self._remove)
        pick = QHBoxLayout()
        pick.addWidget(self.pattern, 1)
        pick.addWidget(self.copy_combo)
        pick.addWidget(self.price_filter)
        pick.addWidget(add)
        pick.addWidget(remove)
        self.message = label("", "muted", wrap=True)
        self.table = TablePanel(self.COLUMNS, export_name="sale_bonds", toolbar=False,
                                empty_text="No bonds chosen yet.\nType their numbers above, or "
                                           "pick a copy and press Add.")
        bonds_box = QGroupBox("Bonds sold")
        inner = QVBoxLayout(bonds_box)
        inner.addLayout(pick)
        inner.addWidget(self.message)
        inner.addWidget(self.table, 1)

        # -- price ---------------------------------------------------------------------------
        self.mode_face = QRadioButton("Face value (each bond for the price printed on it)")
        self.mode_each = QRadioButton("The same price for each bond (enter it below)")
        self.mode_total = QRadioButton("One total for all the bonds (enter it below; it is shared out by face value)")
        self.mode_face.setChecked(True)
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("Rs")
        self.amount.setMaximumWidth(140)
        self.amount.setEnabled(False)
        group = QButtonGroup(self)
        for radio in (self.mode_face, self.mode_each, self.mode_total):
            group.addButton(radio)
        self.total_label = label("", wrap=True)
        amount_row = QHBoxLayout()
        amount_row.addSpacing(24)
        amount_row.addWidget(label("Amount (Rs)", "muted"))
        amount_row.addWidget(self.amount)
        amount_row.addStretch(1)
        priced = QGroupBox("What you received")
        column = QVBoxLayout(priced)
        column.addWidget(self.mode_face)
        column.addWidget(self.mode_each)
        column.addWidget(self.mode_total)
        column.addLayout(amount_row)
        column.addWidget(self.total_label)

        self.warnings = label("", "problem", wrap=True)
        self.save_button = button("Record sale", "primary")
        self.save_button.clicked.connect(self._save)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(label("Selling bonds takes them out of your list: they stop taking part "
                               "in draws held on or after the sale date, the copy and bond tables "
                               "show them as sold, and the sale is kept on the Sales page. You can "
                               "undo it there at any time.", "muted", wrap=True))
        layout.addWidget(who)
        layout.addWidget(bonds_box, 1)
        layout.addWidget(priced)
        layout.addWidget(self.warnings)
        layout.addLayout(footer)

        self.date.edit.dateChanged.connect(self._refresh)
        self.amount.textChanged.connect(self._refresh)
        for radio in (self.mode_face, self.mode_each, self.mode_total):
            radio.toggled.connect(self._mode_changed)
        if bonds:
            self.add_bonds([b for b in bonds if b.get("sale_id") is None])
        self._refresh()

    # -- choosing bonds ----------------------------------------------------------------
    def add_bonds(self, bonds: list[dict]) -> int:
        """Add held bonds (those already in the list are ignored).  Returns how many were new."""
        fresh = [b for b in bonds if b["id"] not in self._ids]
        for bond in fresh:
            self._ids.add(bond["id"])
            self._bonds.append(bond)
        self._refresh()
        return len(fresh)

    def _say(self, text: str, problem: bool = False) -> None:
        """Show the result of the last 'Add' under the number box."""
        self.message.setText(text)
        set_role(self.message, "problem" if problem else "muted")

    def _add(self) -> None:
        copy_id, price = self.copy_combo.currentData(), self.price_filter.value()
        text = self.pattern.text().strip()
        if not text:
            if copy_id is None:
                self._say("Type the bond numbers, or choose a copy to add all of its bonds.", True)
                return
            found = self.db.list_bonds(copy_id=copy_id, sold=False, denomination=price)
            added = self.add_bonds(found)
            self._say(f"{added:,} bond(s) of the copy added." if found else
                      "That copy holds no bonds you have not sold.", not found)
            return
        parsed = parse_pattern(text)
        if not parsed.ok or not parsed.numbers:
            self._say(parsed.problems() or "Enter at least one bond number.", True)
            return
        keys = [key for _, key in parsed.numbers]
        held = defaultdict(list)
        for bond in self.db.list_bonds(sold=False, denomination=price, copy_id=copy_id,
                                       number_from=min(keys), number_to=max(keys)):
            held[bond["num"]].append(bond)
        chosen, missing, several, again = [], [], [], []
        for display, key in parsed.numbers:
            options = held.get(key, [])
            free = [b for b in options if b["id"] not in self._ids]
            if not options:
                missing.append(display)
            elif not free:
                again.append(display)
            elif len(free) == 1:
                chosen.append(free[0])
            else:
                where = ", ".join(sorted({b["copy_name"] or f"Rs {b['denomination']:,}"
                                          for b in free}))
                several.append(f"{display} ({where})")
        added = self.add_bonds(chosen)
        parts = [f"{added:,} bond(s) added."] if added else []
        if again:
            parts.append(f"Already in the list: {_list_text(again)}.")
        if missing:
            parts.append(f"Not among the bonds you hold: {_list_text(missing)}.")
        if several:
            parts.append(f"Held more than once - choose the copy (or the price) to say which "
                         f"bond you mean: {_list_text(several)}.")
        self._say(" ".join(parts) or "Nothing to add.",
                  problem=bool(several) or (bool(missing) and not added))
        if added and not (missing or several):
            self.pattern.clear()

    def _remove(self) -> None:
        gone = {r["id"] for r in self.table.selected_rows()}
        if not gone:
            return
        self._bonds = [b for b in self._bonds if b["id"] not in gone]
        self._ids -= gone
        self._refresh()

    # -- price ------------------------------------------------------------------------------
    def _mode(self) -> str:
        return "each" if self.mode_each.isChecked() else "total" if self.mode_total.isChecked() \
            else "face"

    def _mode_changed(self, *_) -> None:
        self.amount.setEnabled(self._mode() != "face")
        self._refresh()

    def prices(self) -> list[int] | None:
        """One price per bond, or None while the amount is missing / unreadable."""
        mode = self._mode()
        amount = parse_amount(self.amount.text()) if mode != "face" else None
        if mode != "face" and amount is None:
            return None
        return prices_for(mode, [b["denomination"] for b in self._bonds], amount)

    # -- the live summary --------------------------------------------------------------------
    def _checks(self, when: str) -> tuple[list[str], dict[int, str]]:
        """Things worth a second look: returns (warning lines, a short note per bond id)."""
        notes: dict[int, str] = {}
        lines: list[str] = []
        late = [b for b in self._bonds if b["purchase_date"] and b["purchase_date"] > when]
        for bond in late:
            notes[bond["id"]] = "bought after the sale date"
        if late:
            lines.append(f"{len(late):,} bond(s) were bought after this sale date "
                         f"({_list_text([b['number'] for b in late])}) - check the dates.")
        if self._ids:
            gone = [p for p in self.db.list_pending() if p["bond_id"] in self._ids
                    and p["draw_date"] >= when]
            kept = [p for p in self.db.list_pending() if p["bond_id"] in self._ids
                    and p["draw_date"] < when]
            for p in gone:
                notes[p["bond_id"]] = "possible win goes to the buyer"
            for p in kept:
                notes.setdefault(p["bond_id"], "possible win from before the sale: yours")
            if gone:
                lines.append(f"{len(gone):,} possible win(s) waiting for approval come from draws "
                             f"on or after {when}. They belong to the buyer, so they will be "
                             "removed from the waiting list.")
            if kept:
                lines.append(f"{len(kept):,} possible win(s) come from draws before {when}: they "
                             "stay yours and remain in Pending Wins.")
        return lines, notes

    def _refresh(self, *_) -> None:
        when = self.date.value()
        lines, notes = self._checks(when)
        for bond in self._bonds:
            bond["note"] = notes.get(bond["id"], "")
        self.table.set_rows(self._bonds)
        count = len(self._bonds)
        face = sum(b["denomination"] for b in self._bonds)
        prices = self.prices()
        if not count:
            self.total_label.setText("Choose the bonds first.")
            set_role(self.total_label, "muted")
        elif prices is None:
            self.total_label.setText(f"{count:,} bond(s), face value {money(face)}. "
                                     "Enter the amount in whole rupees.")
            set_role(self.total_label, "problem" if self.amount.text().strip() else "muted")
        else:
            total, diff = sum(prices), sum(prices) - face
            sign = "+" if diff > 0 else "-" if diff < 0 else ""
            self.total_label.setText(
                f"{count:,} bond(s), face value {money(face)} - you receive {money(total)}"
                + (f" ({sign}{money(abs(diff))} against face value)." if diff else "."))
            set_role(self.total_label, "ok")
        self.warnings.setText("\n".join(lines))
        set_role(self.warnings, "problem")
        self.save_button.setEnabled(bool(count) and prices is not None)

    # -- saving -------------------------------------------------------------------------------
    def _save(self) -> None:
        prices = self.prices()
        if not self._bonds or prices is None:
            return
        try:
            self.sale_id = self.db.record_sale(
                [b["id"] for b in self._bonds], self.date.value(), self.buyer.text(),
                self.contact.text(), self.location.text(), self.note.text(), prices)
        except SaleError as exc:
            warn(self, "Cannot record the sale", str(exc))
            return
        self.accept()
