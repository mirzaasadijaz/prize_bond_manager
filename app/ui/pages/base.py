"""Common frame for every page."""
from __future__ import annotations

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ..context import AppContext


class BasePage(QWidget):
    """A page has a context (database, agent, signals) and a ``refresh`` hook."""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.ctx = ctx
        self.db = ctx.db
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(28, 24, 28, 20)
        self.root.setSpacing(14)

    def refresh(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError
