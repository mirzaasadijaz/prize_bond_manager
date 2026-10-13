"""Shared state for the interface: the database, the agent and a few signals."""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from ..db import Database
from ..models import AddResult, ScanResult
from ..processing.agent import WinAgent


class AppContext(QObject):
    """Passed to every page and dialog.

    ``data_changed``  - something was written; pages should refresh.
    ``navigate``      - ask the main window to show a page ('pending', 'bonds', ...).
    ``status``        - short message for the status bar.
    """

    data_changed = pyqtSignal()
    navigate = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, db: Database, agent: WinAgent | None = None, parent=None):
        super().__init__(parent)
        self.db = db
        self.agent = agent or WinAgent(db)

    def changed(self) -> None:
        self.data_changed.emit()

    # -- agent ---------------------------------------------------------------
    def run_agent(self, trigger: str, draw_id: int | None = None,
                  force: bool = False) -> ScanResult | None:
        """Run the win-checking agent (``force`` ignores the automatic on/off switch)."""
        result = (self.agent.scan(draw_id, trigger) if force
                  else self.agent.run_if_enabled(trigger, draw_id))
        if result is not None:
            self.changed()
            self.status.emit(result.summary())
        return result

    def offer_review(self, parent, result: ScanResult | None,
                     heading: str = "Possible win found", lead: str = "") -> None:
        """Tell the user about new pending wins and offer to open the approval page."""
        if result is None or not result.new_pending:
            return
        text = (f"{lead}\n\n" if lead else "") + (
            f"The win-checking agent found {result.new_pending:,} bond(s) "
            "that match winning numbers.")
        box = QMessageBox(QMessageBox.Icon.Information, heading, text,
                          QMessageBox.StandardButton.NoButton, parent)
        box.setInformativeText(
            "They are listed under Pending Wins. Nothing has been moved yet - review the "
            "list and approve it when you are happy with it.")
        review = box.addButton("Review now", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is review:
            self.navigate.emit("pending")

    # -- after adding bonds ------------------------------------------------------
    def after_bonds_added(self, parent, result: AddResult, title: str = "Bonds added") -> None:
        """Summarise an add/import, let the agent check the new bonds, offer review."""
        self.changed()
        self.show_add_summary(parent, result, title)
        self.offer_review(parent, self.run_agent("bonds"))

    @staticmethod
    def show_add_summary(parent, result: AddResult, title: str) -> None:
        icon = QMessageBox.Icon.Information if result.added else QMessageBox.Icon.Warning
        box = QMessageBox(icon, title, result.summary() + ".",
                          QMessageBox.StandardButton.Ok, parent)
        details = []
        if result.shared:
            box.setInformativeText(
                f"{result.shared:,} of the new bond(s) have the same number as another bond in your list. "
                "That is fine: when such a number is drawn, every bond holding it wins and the "
                "report lists each one with its own copy and position.")
        if result.renamed_copies:
            details.append("Renamed because the name was already used:\n" + "\n".join(
                f"  {old}  ->  {new}" for old, new in result.renamed_copies))
        if result.skipped_duplicates:
            shown = result.skipped_duplicates[:300]
            more = " ..." if len(result.skipped_duplicates) > len(shown) else ""
            details.append("Left out because the copy already holds the number (or you chose to "
                           "skip numbers you already have):\n  " + ", ".join(shown) + more)
        if details:
            box.setDetailedText("\n\n".join(details))
        box.exec()
