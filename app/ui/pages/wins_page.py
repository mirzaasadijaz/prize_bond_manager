"""Win List: approved wins with copy, 1st bond number of the copy and position."""
from __future__ import annotations

from ...processing import reports
from .. import actions
from ..context import AppContext
from ..dialogs.win_report import save_report
from ..table_model import Col, same_number_col
from ..widgets import PageHeader, TablePanel, button, confirm, dash
from .base import BasePage


class WinsPage(BasePage):
    COLUMNS = [
        Col("draw_date", "Draw date", 92),
        Col("draw_label", "Draw", 100, fmt=dash),
        Col("bond_number", "Bond number", 104),
        Col("denomination", "Price (Rs)", 86, "right", numeric=True, export_raw=True,
            fmt=lambda v, r: f"{v:,}"),
        Col("prize", "Prize", 175),
        same_number_col(),
        Col("copy", "Copy (book)", 104),
        Col("copy_first_number", "1st bond of copy", 126, fmt=dash),
        Col("where", "Position in copy", 124),
        Col("approved_at", "Approved", 130),
    ]

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        header = PageHeader("Win List", "Approved wins. Each one shows which copy the bond is in, "
                            "the 1st bond number of that copy and its position - double-click a "
                            "row for the full report. A number held in several copies wins in "
                            "every copy, one row per bond.")
        self.report_button = header.add_action(button("Show report", "primary"))
        self.save_button = header.add_action(button("Save report..."))
        self.revert_button = header.add_action(button("Move back to waiting list", "danger"))
        self.report_button.clicked.connect(self._show)
        self.save_button.clicked.connect(self._save)
        self.revert_button.clicked.connect(self._revert)
        self.root.addWidget(header)
        self.panel = TablePanel(self.COLUMNS, export_name="win_list", sheet_name="Win list",
                                placeholder="Search wins ...",
                                empty_text="No wins yet.\nApproved matches from the Pending Wins "
                                           "page are listed here.")
        self.panel.selection_changed.connect(self._update_buttons)
        self.panel.row_activated.connect(lambda r: actions.show_win_report(
            self, reports.with_same_number([r], self.panel.all_rows()), "Win report"))
        self.root.addWidget(self.panel, 1)
        self.total = self.panel.count_label

    def refresh(self) -> None:
        rows = self.db.list_wins()
        for r in rows:
            r["prize"] = reports.prize_text(r)
            r["copy"] = reports.copy_text(r) if r["copy_name"] else "-"
            r["where"] = reports.position_text(r) or "-"
        self.panel.set_rows(rows)
        self._update_buttons()

    def _targets(self) -> list[dict]:
        """Selected wins (or everything shown when nothing is selected) for a report.

        A winning number's report always covers every bond that won with it.
        """
        chosen = self.panel.selected_rows()
        if not chosen:
            return self.panel.visible_rows()
        return reports.with_same_number(chosen, self.panel.all_rows())

    def _update_buttons(self) -> None:
        has_rows = bool(self.panel.visible_rows())
        self.report_button.setEnabled(has_rows)
        self.save_button.setEnabled(has_rows)
        self.revert_button.setEnabled(bool(self.panel.selected_rows()))

    def _show(self) -> None:
        actions.show_win_report(self, self._targets(), "Win report")

    def _save(self) -> None:
        wins = self._targets()
        if wins:
            save_report(self, wins)

    def _revert(self) -> None:
        rows = self.panel.selected_rows()
        if not rows:
            return
        others = sum(1 for r in rows if (r.get("same_number_count") or 1) > 1)
        note = ("\n\nOnly the selected bond(s) move back; other bonds holding the same number stay "
                "in the Win List unless you select them too." if others else "")
        if not confirm(self, "Move back to waiting list",
                       f"Remove {len(rows):,} win(s) from the Win List and put the bond(s) back in "
                       f"your waiting list?\n\nUse this if a win was approved by mistake.{note}",
                       yes="Move back", danger=True):
            return
        self.db.revert_wins([r["id"] for r in rows])
        self.ctx.changed()
