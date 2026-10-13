"""Dashboard: totals, holdings by price, recent wins and a reminder to approve pending wins."""
from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout

from ...processing import reports
from .. import actions
from ..context import AppContext
from ..table_model import Col, same_number_col
from ..widgets import PageHeader, StatCard, TablePanel, button, label, money
from .base import BasePage


def _total_style(row):
    return (None, "#F0FDFA") if row.get("is_total") else None


class DashboardPage(BasePage):
    HOLDINGS = [
        Col("price", "Price", 110, "left"),
        Col("active", "Waiting bonds", 120, "right", numeric=True, fmt=lambda v, r: f"{v:,}"),
        Col("won", "Drawn", 90, "right", numeric=True, fmt=lambda v, r: f"{v:,}"),
        Col("value", "Value waiting (Rs)", 150, "right", numeric=True, fmt=lambda v, r: f"{v:,}"),
    ]
    RECENT = [
        Col("draw_date", "Draw date", 100),
        Col("bond_number", "Bond", 90),
        Col("denomination", "Price", 80, "right", numeric=True, fmt=lambda v, r: f"{v:,}"),
        Col("copy", "Copy (book)", 110),
        Col("where", "Position", 100),
        same_number_col(single="-"),
    ]

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self.root.addWidget(PageHeader("Dashboard", "Your prize bonds at a glance"))

        self.banner = QFrame()
        self.banner.setObjectName("Banner")
        row = QHBoxLayout(self.banner)
        row.setContentsMargins(16, 10, 16, 10)
        self.banner_text = label("")
        review = button("Review pending wins", "primary")
        review.clicked.connect(lambda: self.ctx.navigate.emit("pending"))
        row.addWidget(self.banner_text, 1)
        row.addWidget(review)
        self.root.addWidget(self.banner)

        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.card_active = StatCard("Active bonds")
        self.card_value = StatCard("Investment value (active bonds)")
        self.card_wins = StatCard("Wins so far")
        self.card_pending = StatCard("Waiting for your approval")
        for card in (self.card_active, self.card_value, self.card_wins, self.card_pending):
            cards.addWidget(card, 1)
        self.root.addLayout(cards)

        self.holdings = TablePanel(self.HOLDINGS, toolbar=False, row_style=_total_style,
                                   empty_text="No bonds yet. Add or import some to see them here.")
        self.recent = TablePanel(self.RECENT, toolbar=False,
                                 empty_text="No approved wins yet.")
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(label("Holdings by price", "section"))
        left.addWidget(self.holdings, 1)
        right.addWidget(label("Recent draw hits", "section"))
        right.addWidget(self.recent, 1)
        tables = QHBoxLayout()
        tables.setSpacing(18)
        tables.addLayout(left, 1)
        tables.addLayout(right, 1)
        self.root.addLayout(tables, 1)

        actions_row = QHBoxLayout()
        buttons = [
            ("Add bonds...", "primary", lambda: actions.add_bonds(self.ctx, self)),
            ("Import file...", "default", lambda: actions.import_file(self.ctx, self)),
            ("Record draw results", "default", lambda: self.ctx.navigate.emit("draws")),
            ("Run win-checking agent", "default", self._run_agent),
        ]
        for text, kind, handler in buttons:
            widget = button(text, kind)
            widget.clicked.connect(handler)
            actions_row.addWidget(widget)
        actions_row.addStretch(1)
        self.root.addLayout(actions_row)

    def _run_agent(self) -> None:
        result = self.ctx.run_agent("manual", force=True)
        self.ctx.offer_review(self, result)

    def refresh(self) -> None:
        stats = self.db.dashboard_stats()
        copies = stats["copy_count"]
        shared = stats["shared_numbers"]
        sub = f"in {copies:,} copy/copies" if copies else "waiting for a draw"
        if shared:
            sub += f" - {shared:,} number(s) held more than once"
        self.card_active.set(f"{stats['active_count']:,}", sub)
        self.card_value.set(money(stats["active_value"]),
                            f"{money(stats['total_value'])} incl. drawn bonds")
        prize = f"prizes {money(stats['prize_total'])}" if stats["prize_total"] else "approved wins"
        self.card_wins.set(f"{stats['win_count']:,}", prize)
        pending = stats["pending_count"]
        self.card_pending.set(f"{pending:,}", "open Pending Wins to review" if pending
                              else "nothing to review")
        self.banner.setVisible(bool(pending))
        self.banner_text.setText(f"{pending:,} possible win(s) found by the agent - nothing is "
                                 "moved until you approve them.")

        rows = [{"price": money(d["denomination"]), "active": d["active"], "won": d["won"],
                 "value": d["value"]} for d in stats["by_denomination"]]
        if rows:
            rows.append({"price": "Total", "active": stats["active_count"],
                         "won": sum(r["won"] for r in rows), "value": stats["active_value"],
                         "is_total": True})
        self.holdings.set_rows(rows)
        self.recent.set_rows([
            {**w, "copy": reports.copy_text(w) if w["copy_name"] else "-",
             "where": reports.position_text(w) or "-"} for w in self.db.recent_wins(10)])
