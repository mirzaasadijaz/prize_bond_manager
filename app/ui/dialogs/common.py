"""Small input widgets used by several dialogs."""
from __future__ import annotations

import re

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QDateEdit, QHBoxLayout, QLineEdit,
                             QWidget)

from ...config import DEFAULT_DENOMINATIONS
from ..widgets import _settings


class DenominationBox(QComboBox):
    """Editable drop-down of prize-bond prices.

    ``value()`` is the price as an int, or None when the text is not a price.
    With ``allow_any`` an extra "Any denomination" entry is offered
    (``is_any`` is then True); with ``allow_blank`` the first entry is empty.
    """

    ANY_TEXT = "Any denomination"

    def __init__(self, extra=(), allow_any: bool = False, allow_blank: bool = False,
                 parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.allow_any = allow_any
        if allow_blank:
            self.addItem("")
        if allow_any:
            self.addItem(self.ANY_TEXT)
        for price in sorted(set(DEFAULT_DENOMINATIONS) | set(extra)):
            self.addItem(str(price))

    @property
    def is_any(self) -> bool:
        return self.allow_any and self.currentText().strip().lower().startswith("any")

    def value(self) -> int | None:
        if self.is_any:
            return None
        digits = re.sub(r"[^0-9]", "", self.currentText())
        return int(digits) if digits and int(digits) > 0 else None

    def set_value(self, price: int | None) -> None:
        if price is None:
            index = self.findText(self.ANY_TEXT) if self.allow_any else 0
        else:
            index = self.findText(str(price))
        if index >= 0:
            self.setCurrentIndex(index)
        else:
            self.setEditText(str(price))

    # remembered between runs so repeated entry of the same price is quick
    def remember(self) -> None:
        value = self.value()
        if value:
            try:
                _settings().setValue("last_denomination", value)
            except Exception:
                pass

    @staticmethod
    def remembered(default: int = 750) -> int:
        try:
            return int(_settings().value("last_denomination", default))
        except Exception:
            return default


class DateField(QWidget):
    """Date picker with an optional 'Unknown' tick (value() is then None)."""

    def __init__(self, allow_unknown: bool = True, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QDateEdit(QDate.currentDate())
        self.edit.setCalendarPopup(True)
        self.edit.setDisplayFormat("yyyy-MM-dd")
        layout.addWidget(self.edit)
        self.unknown = QCheckBox("Unknown") if allow_unknown else None
        if self.unknown:
            self.unknown.toggled.connect(lambda on: self.edit.setEnabled(not on))
            layout.addWidget(self.unknown)
        layout.addStretch(1)

    def value(self) -> str | None:
        if self.unknown and self.unknown.isChecked():
            return None
        return self.edit.date().toString("yyyy-MM-dd")

    def set_value(self, iso: str | None) -> None:
        parsed = QDate.fromString(iso or "", "yyyy-MM-dd")
        if not iso or not parsed.isValid():
            if self.unknown:
                self.unknown.setChecked(True)
            return
        if self.unknown:
            self.unknown.setChecked(False)
        self.edit.setDate(parsed)


class LocationField(QLineEdit):
    """Optional 'where is it' text; suggests places already used anywhere in the data file.

    ``value()`` is the trimmed text, or None when it was left empty.
    """

    HINT = "optional - e.g. home safe, bank locker, Lahore office"

    def __init__(self, db=None, placeholder: str | None = None, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder or self.HINT)
        self.setClearButtonEnabled(True)
        known = db.known_locations() if db is not None else []
        if known:
            completer = QCompleter(known, self)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self.setCompleter(completer)

    def value(self) -> str | None:
        return self.text().strip() or None

    def set_value(self, text: str | None) -> None:
        self.setText(text or "")
