"""Row colours of the bond and copy lists, and the 'Highlight' button that sets them.

From the strongest to the weakest:  sold (grey)  >  a colour you chose  >  a win waiting for
approval (amber)  >  has already won (green).
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtGui import QAction, QColor, QIcon, QPixmap
from PyQt6.QtWidgets import QColorDialog, QMenu

from . import theme
from .widgets import button

SWATCHES = [("Yellow", "#FDE68A"), ("Orange", "#FDBA74"), ("Pink", "#FBCFE8"),
            ("Blue", "#BFDBFE"), ("Purple", "#DDD6FE"), ("Grey", "#CBD5E1")]


def bond_row_style(row: dict):
    """(text colour, background) of a row of the bond list."""
    if row.get("sale_id") is not None:
        return theme.MUTED, None
    colour = row.get("highlight") or row.get("copy_highlight")
    if colour:
        return theme.readable_on(colour), colour
    if row.get("pending_count"):
        return theme.WARNING_TEXT, theme.WARNING_BG
    if row.get("times_won"):
        return theme.WON_ROW_TEXT, theme.WON_ROW_BG
    return None


def copy_row_style(row: dict):
    """(text colour, background) of a row of the copy list."""
    colour = row.get("highlight")
    if colour:
        return theme.readable_on(colour), colour
    if row.get("won"):
        return theme.WON_ROW_TEXT, theme.WON_ROW_BG
    return None


def _swatch(colour: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(colour))
    return QIcon(pixmap)


def highlight_button(parent, on_pick: Callable[[str | None], None]):
    """A 'Highlight' button with a menu: some ready colours, 'Choose a colour...' and
    'Remove colour'.  ``on_pick`` gets ``'#RRGGBB'`` or ``None`` (remove)."""
    widget = button("Highlight", tooltip="Give the selected rows a colour of your choice")
    menu = QMenu(widget)
    for name, colour in SWATCHES:
        action = QAction(_swatch(colour), name, menu)
        action.triggered.connect(lambda _checked=False, c=colour: on_pick(c))
        menu.addAction(action)
    other = QAction("Choose a colour...", menu)
    other.triggered.connect(lambda _checked=False: _choose(parent, on_pick))
    menu.addAction(other)
    menu.addSeparator()
    remove = QAction("Remove colour", menu)
    remove.triggered.connect(lambda _checked=False: on_pick(None))
    menu.addAction(remove)
    widget.setMenu(menu)
    widget.menu_actions = menu.actions()
    return widget


def _choose(parent, on_pick) -> None:
    colour = QColorDialog.getColor(QColor("#FDE68A"), parent, "Choose a highlight colour")
    if colour.isValid():
        on_pick(colour.name())
