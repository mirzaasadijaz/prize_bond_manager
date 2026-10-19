"""The optional PIN: asked before anything is edited or deleted, and the dialog that sets it."""
from __future__ import annotations

import time

from PyQt6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QInputDialog, QLineEdit,
                             QVBoxLayout)

from ..db import PinError
from ..db.security_repo import MIN_PIN_LENGTH
from .widgets import button, info, label, warn

MAX_WRONG = 3                 # after this many wrong PINs in a row the program waits a little
LOCK_SECONDS = 30


def ask_pin(parent, ctx, what: str) -> bool:
    """True when the action may go on: no PIN is set, or the right one was typed.

    ``what`` finishes the sentence 'Enter your PIN to ...', e.g. 'delete bonds'.
    """
    db = ctx.db
    if not db.pin_is_set():
        return True
    wait = getattr(ctx, "pin_locked_until", 0) - time.monotonic()
    if wait > 0:
        warn(parent, "Too many wrong PINs", f"Wait {int(wait) + 1} seconds and try again.")
        return False
    pin, ok = QInputDialog.getText(parent, "PIN needed", f"Enter your PIN to {what}:",
                                   QLineEdit.EchoMode.Password)
    if not ok:
        return False
    if db.check_pin(pin):
        ctx.pin_wrong = 0
        return True
    ctx.pin_wrong = getattr(ctx, "pin_wrong", 0) + 1
    if ctx.pin_wrong >= MAX_WRONG:
        ctx.pin_wrong = 0
        ctx.pin_locked_until = time.monotonic() + LOCK_SECONDS
    warn(parent, "Wrong PIN", "That PIN is not right. Nothing was changed.")
    return False


class PinDialog(QDialog):
    """Set, change or remove the PIN."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx, self.db = ctx, ctx.db
        self.is_set = self.db.pin_is_set()
        self.setWindowTitle("PIN / password")
        self.setMinimumWidth(420)

        def field() -> QLineEdit:
            edit = QLineEdit()
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            return edit

        self.current, self.new, self.again = field(), field(), field()
        form = QFormLayout()
        if self.is_set:
            form.addRow("Current PIN", self.current)
        form.addRow("New PIN" if self.is_set else "PIN", self.new)
        form.addRow("Type it again", self.again)

        save = button("Save", "primary")
        save.clicked.connect(self._save)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        footer = QHBoxLayout()
        if self.is_set:
            remove = button("Remove PIN", "danger")
            remove.clicked.connect(self._remove)
            footer.addWidget(remove)
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(save)
        layout = QVBoxLayout(self)
        layout.addWidget(label(
            "With a PIN set, the program asks for it before anything is edited or deleted "
            f"(at least {MIN_PIN_LENGTH} characters, letters and digits are fine). It protects "
            "the program's screens; it does not encrypt the data file.", "muted", wrap=True))
        layout.addLayout(form)
        layout.addLayout(footer)

    def _save(self) -> None:
        if self.new.text() != self.again.text():
            warn(self, "PIN", "The two PINs are not the same.")
            return
        try:
            self.db.set_pin(self.new.text(), self.current.text() if self.is_set else None)
        except PinError as exc:
            warn(self, "PIN", str(exc))
            return
        info(self, "PIN", "The PIN is saved. Editing and deleting now ask for it.")
        self.accept()

    def _remove(self) -> None:
        try:
            self.db.remove_pin(self.current.text())
        except PinError as exc:
            warn(self, "PIN", str(exc))
            return
        info(self, "PIN", "The PIN is removed.")
        self.accept()
