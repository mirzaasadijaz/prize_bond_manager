"""Edit the location, status and feedback of one or more wins."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QCompleter, QDialog, QFormLayout, QHBoxLayout, QLineEdit,
                             QPlainTextEdit, QVBoxLayout)

from ...config import WIN_STATUSES
from ...processing import reports
from ..context import AppContext
from ..widgets import button, label, warn

DIFFERENT = "(different - leave empty to keep each as it is)"
KEEP_EACH = "(keep each as it is)"


def _common(rows: list[dict], key: str) -> str | None:
    """The value all rows share (empty text counts as a value), or None when they differ."""
    values = {(r.get(key) or "").strip() for r in rows}
    return values.pop() if len(values) == 1 else None


class EditWinDetailsDialog(QDialog):
    """Location / status / feedback for the selected wins.

    With several wins selected, a field that differs between them starts empty and is only
    changed if you type something in it - the others keep their own values.
    """

    def __init__(self, ctx: AppContext, wins: list[dict], parent=None):
        super().__init__(parent)
        self.ctx, self.db, self.wins = ctx, ctx.db, wins
        self.changes: dict = {}
        many = len(wins) > 1
        self.setWindowTitle("Win details" if many else f"Win details - bond {wins[0]['bond_number']}")
        self.setMinimumWidth(520)

        who = ", ".join(f"{w['bond_number']} ({reports.copy_text(w)})" for w in wins[:4])
        who += f" ... (+{len(wins) - 4} more)" if len(wins) > 4 else ""
        intro = label(f"{len(wins)} win(s): {who}", "muted", wrap=True)

        status = _common(wins, "claim_status")
        self.status = QComboBox()
        if status is None:
            self.status.addItem(KEEP_EACH, None)
        for text in WIN_STATUSES:
            self.status.addItem(text, text)
        if status is not None:
            self.status.setCurrentIndex(max(self.status.findData(status), 0))

        location = _common(wins, "location")
        self.location = QLineEdit(location or "")
        self.location.setPlaceholderText(DIFFERENT if location is None else
                                         "where the prize is claimed / the draw was held, e.g. Lahore")
        known = self.db.known_locations()
        if known:
            completer = QCompleter(known, self.location)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self.location.setCompleter(completer)
        self._location_touched = False
        self.location.textEdited.connect(lambda *_: setattr(self, "_location_touched", True))

        feedback = _common(wins, "feedback")
        self.feedback = QPlainTextEdit(feedback or "")
        self.feedback.setPlaceholderText(DIFFERENT if feedback is None else
                                         "what the bank / office said, a reference number, "
                                         "the date you handed the bond in ...")
        self.feedback.setFixedHeight(110)
        self._feedback_touched = False
        self.feedback.textChanged.connect(lambda: setattr(self, "_feedback_touched", True))

        form = QFormLayout()
        form.addRow("Status", self.status)
        form.addRow("Location", self.location)
        form.addRow("Feedback", self.feedback)

        save = button("Save", "primary")
        save.clicked.connect(self._save)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(save)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addLayout(footer)

    def _collect(self) -> dict:
        """Only what you actually changed (so a shared note is not rewritten for nothing)."""
        changes: dict = {}
        status = self.status.currentData()
        if status is not None and status != _common(self.wins, "claim_status"):
            changes["claim_status"] = status
        if self._location_touched:
            changes["location"] = self.location.text()
        if self._feedback_touched:
            changes["feedback"] = self.feedback.toPlainText()
        return changes

    def _save(self) -> None:
        changes = self._collect()
        try:
            if changes:
                self.db.update_win_details([w["id"] for w in self.wins], **changes)
        except ValueError as exc:
            warn(self, "Cannot save", str(exc))
            return
        self.changes = changes
        self.accept()
