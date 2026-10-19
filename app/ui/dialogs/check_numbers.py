"""Check a list of bond numbers (any number of them) against the recorded draws, at once."""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QGroupBox, QHBoxLayout, QPlainTextEdit, QVBoxLayout

from ...api.checker import WinningIndex, check_bonds, held_bonds
from ...processing.numbers import parse_pattern
from ..context import AppContext
from ..table_model import Col
from ..widgets import TablePanel, button, dash, label, money, set_role
from .common import DenominationBox

HEADERS_SHOWN = 300           # unreadable entries listed in the message before "..."


class CheckNumbersDialog(QDialog):
    """Paste thousands of numbers (or whole ranges) and see which of them were drawn.

    Nothing is saved: this is a quick look-up, independent of the bonds in your list.  The
    same checker answers ``POST /check`` when the program is started with ``--serve``.
    """

    COLUMNS = [
        Col("number", "Bond number", 110, sort_key="num"),
        Col("price", "Price", 90, "right", fmt=lambda v, r: money(v) if v else "any"),
        Col("ref", "Where it is", 130, fmt=dash),
        Col("draw_date", "Draw date", 100),
        Col("draw_label", "Draw", 120, fmt=dash),
        Col("location", "Held in", 110, fmt=dash),
        Col("prize_label", "Prize", 100),
        Col("prize_amount", "Prize amount", 120, "right", numeric=True, export_raw=True,
            fmt=lambda v, r: money(v) or "-"),
    ]

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx, self.db = ctx, ctx.db
        self.summary = None
        self.setWindowTitle("Check a list of numbers")
        self.resize(900, 720)

        self.numbers = QPlainTextEdit()
        self.numbers.setPlaceholderText("Paste bond numbers - one per line, or separated by "
                                        "commas or spaces. Ranges such as 100001-100500 work too. "
                                        "Thousands at a time are fine.")
        self.numbers.setMaximumHeight(150)
        self.price = DenominationBox(allow_any=True)
        self.price.set_value(None)
        self.price.setToolTip("The price these bonds were sold at. 'Any' also matches draws "
                              "of every price.")
        self.check_button = button("Check these numbers", "primary")
        self.check_button.clicked.connect(self.check_text)
        self.mine_button = button("Check all the bonds I hold",
                                  tooltip="The same check the win-checking agent does, without "
                                          "queueing anything")
        self.mine_button.clicked.connect(self.check_mine)
        row = QHBoxLayout()
        row.addWidget(label("Bond price", "muted"))
        row.addWidget(self.price)
        row.addStretch(1)
        row.addWidget(self.mine_button)
        row.addWidget(self.check_button)

        input_box = QGroupBox("Numbers to check")
        inner = QVBoxLayout(input_box)
        inner.addWidget(self.numbers)
        inner.addLayout(row)

        self.message = label("", wrap=True)
        self.table = TablePanel(self.COLUMNS, export_name="checked_numbers", sheet_name="Hits",
                                empty_text="Winning numbers found among the ones you check "
                                           "appear here.")
        self.problems = QPlainTextEdit()
        self.problems.setReadOnly(True)
        self.problems.setMaximumHeight(70)
        self.problems.hide()
        close = button("Close")
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(input_box)
        layout.addWidget(self.message)
        layout.addWidget(self.problems)
        layout.addWidget(self.table, 1)
        layout.addLayout(footer)

    # -- the two checks -----------------------------------------------------------------------
    def _index(self) -> WinningIndex:
        return WinningIndex.from_connection(self.db.conn)

    def check_text(self) -> None:
        text = self.numbers.toPlainText()
        parsed = parse_pattern(text)
        if not parsed.numbers:
            self.problems.hide()
            self._say("Type or paste at least one bond number." if not parsed.errors
                      else parsed.problems(), problem=True)
            return
        summary = check_bonds(self._index(), ((n, None, None) for n, _ in parsed.numbers),
                              default_denomination=self.price.value())
        notes = [f"{len(parsed.errors):,} entry/entries could not be read, e.g. "
                 + ", ".join(parsed.errors[:5])] if parsed.errors else []
        self._show(summary, notes)

    def check_mine(self) -> None:
        bonds = held_bonds(self.db.conn)
        summary = check_bonds(self._index(), ((n, d, r) for n, d, r, _ in bonds),
                              owned_at={i: s for i, (_, _, _, s) in enumerate(bonds) if s})
        self._show(summary, [])

    def _show(self, summary, notes: list[str]) -> None:
        self.summary = summary
        rows = [{"number": h.number, "num": h.num, "price": h.denomination or h.row.denomination,
                 "ref": h.ref, "draw_date": h.row.draw_date, "draw_label": h.row.draw_label,
                 "location": h.row.location, "prize_label": h.row.prize_label,
                 "prize_amount": h.row.prize_amount} for h in summary.hits]
        self.table.set_rows(rows)
        if not summary.draws_searched:
            self._say("No draws are recorded yet, so there is nothing to compare with. Add the "
                      "results on the Draw Results page first.", problem=True)
            return
        text = (f"{summary.checked:,} number(s) checked against {summary.numbers_searched:,} "
                f"winning numbers from {summary.draws_searched:,} draw(s) in "
                f"{summary.elapsed_ms:.1f} ms: ")
        text += (f"{summary.winners:,} won ({len(summary.hits):,} hit(s))." if summary.winners
                 else "none of them won.")
        if summary.invalid:
            shown = ", ".join(t for _, t, _ in summary.invalid[:5])
            notes.append(f"{len(summary.invalid):,} number(s) could not be read ({shown}"
                         f"{' ...' if len(summary.invalid) > 5 else ''}).")
        self.problems.setVisible(bool(notes))
        self.problems.setPlainText("\n".join(notes))
        self._say(text, problem=False)

    def _say(self, text: str, problem: bool) -> None:
        self.message.setText(text)
        set_role(self.message, "problem" if problem else "ok")
