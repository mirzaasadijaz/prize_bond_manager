"""Win reports.

A report states, for every winning bond:
    * which copy (book) it belongs to,
    * the 1st (starting) bond number of that copy, and
    * the exact position of the winning bond inside that copy.

The same number may be held in several copies.  When that number is drawn
*every* bond holding it wins, so reports group the bonds by winning number and
give each bond its own copy / 1st number / position.

The functions accept rows from the ``wins`` table and from the pending list
(both carry the same copy fields).
"""
from __future__ import annotations

from datetime import datetime
from html import escape

LOOSE = "Not in a copy (loose bond)"
SHOWN_COPIES = 6          # copy names listed in a "held in" line before "..."


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def money(amount) -> str:
    return f"Rs {int(amount):,}" if amount not in (None, "") else ""


def copy_text(win: dict) -> str:
    return win.get("copy_name") or LOOSE


def first_number_text(win: dict) -> str:
    return (win.get("copy_first_number") or "") if win.get("copy_name") else ""


def position_text(win: dict, long: bool = False) -> str:
    """'56 of 100' (or, with long=True, '56 of 100 - the 56th bond in the copy')."""
    position = win.get("position")
    if not win.get("copy_name") or not position:
        return ""
    size = win.get("copy_size")
    text = f"{position} of {size}" if size else str(position)
    if long:
        text += f" - the {ordinal(position)} bond in the copy"
        if position == 1:
            text += " (it is the first bond of the copy)"
    return text


def prize_text(win: dict) -> str:
    label = win.get("prize_label") or "Winner"
    amount = money(win.get("prize_amount"))
    return f"{label} - {amount}" if amount else label


def draw_text(win: dict) -> str:
    label = win.get("draw_label")
    return f"{win.get('draw_date', '')} - {label}" if label else str(win.get("draw_date", ""))


def copy_lines(win: dict) -> list[tuple[str, str]]:
    """The three facts every win report must state about one bond."""
    return [
        ("Copy (book)", copy_text(win)),
        ("1st bond number of this copy", first_number_text(win) or "-"),
        ("Position in this copy", position_text(win, long=True) or "-"),
    ]


def detail_lines(win: dict) -> list[tuple[str, str]]:
    """Ordered (label, value) pairs describing one win."""
    return [
        ("Bond number", f"{win.get('bond_number', '')} (Rs {int(win.get('denomination') or 0):,})"),
        ("Draw", draw_text(win)),
        ("Prize", prize_text(win)),
    ] + copy_lines(win)


COPY_LABEL_WIDTH = max(len(label) for label, _ in copy_lines({}))


# ------------------------------------------------------------------ grouping
def group_key(win: dict) -> tuple:
    """Wins with the same key are the same winning number held in several bonds."""
    return (win.get("draw_id"), win.get("draw_date"), win.get("denomination"),
            win.get("bond_number"))


def group_wins(wins: list[dict]) -> list[dict]:
    """Group wins (or pending matches) by draw and winning number, keeping their order."""
    groups: dict[tuple, dict] = {}
    for win in wins:
        key = group_key(win)
        group = groups.get(key)
        if group is None:
            groups[key] = group = {
                "number": str(win.get("bond_number", "")),
                "denomination": int(win.get("denomination") or 0),
                "draw": draw_text(win), "prize": prize_text(win), "bonds": []}
        group["bonds"].append(win)
    return list(groups.values())


def with_same_number(selected: list[dict], everything: list[dict]) -> list[dict]:
    """``selected`` plus every other row of ``everything`` holding the same winning number.

    A report on one win has to cover all the bonds that won with that number.
    """
    keys = {group_key(w) for w in selected}
    return [w for w in everything if group_key(w) in keys]


def total_prize(group: dict) -> int | None:
    amounts = [b.get("prize_amount") for b in group["bonds"] if b.get("prize_amount") is not None]
    return sum(int(a) for a in amounts) if amounts else None


def holders_text(bonds: list[dict]) -> str:
    """'2 bonds - Copy 1, Copy 5': where the bonds holding one number are."""
    names = [b.get("copy_name") or "no copy" for b in bonds]
    shown = ", ".join(names[:SHOWN_COPIES]) + (" ..." if len(names) > SHOWN_COPIES else "")
    return f"{len(bonds)} bonds - {shown}"


def heading_text(group: dict) -> str:
    return f"Winning number {group['number']} (Rs {group['denomination']:,})"


def sharing_note(group: dict) -> str:
    """Why several bonds are listed under one number (empty for a single bond)."""
    count = len(group["bonds"])
    if count < 2:
        return ""
    return f"{count} of your bonds hold this number, so all {count} win"


# -------------------------------------------------------------------- reports
def win_report_text(wins: list[dict], title: str = "PRIZE BOND WIN REPORT") -> str:
    groups = group_wins(wins)
    lines = [title, f"Generated: {datetime.now():%Y-%m-%d %H:%M}",
             f"Winning numbers: {len(groups)}    Winning bonds: {len(wins)}", ""]
    for number, group in enumerate(groups, start=1):
        bonds = group["bonds"]
        many = len(bonds) > 1
        counter = f"   [{number} of {len(groups)}]" if len(groups) > 1 else ""
        lines += ["=" * 64, f"{heading_text(group)}{counter}",
                  f"  Draw  : {group['draw']}",
                  f"  Prize : {group['prize']}" + (" per bond" if many and total_prize(group)
                                                    else "")]
        if many:
            lines.append(f"  Held  : {holders_text(bonds)}")
            lines.append(f"  Note  : {sharing_note(group)}")
            total = total_prize(group)
            if total is not None:
                lines.append(f"  Total : {money(total)}")
        for index, bond in enumerate(bonds, start=1):
            if many:
                lines.append(f"  Bond {index} of {len(bonds)}")
            for label, value in copy_lines(bond):
                lines.append(f"    {label.ljust(COPY_LABEL_WIDTH)} : {value}")
        lines.append("")
    return "\n".join(lines)


def _row(label: str, value: str, bold: bool = True) -> str:
    value = escape(value)
    return (f"<tr><td width='38%' style='color:#6B7280'>{escape(label)}</td>"
            f"<td>{'<b>' + value + '</b>' if bold else value}</td></tr>")


def win_report_html(wins: list[dict], title: str = "Prize Bond Win Report") -> str:
    """Self-contained HTML (works in QTextBrowser, a browser, or when printed)."""
    groups = group_wins(wins)
    parts = [
        "<html><head><meta charset='utf-8'><title>%s</title></head>"
        "<body style='font-family:Segoe UI,Arial,sans-serif;color:#1F2937'>" % escape(title),
        f"<h2 style='margin-bottom:2px'>{escape(title)}</h2>",
        f"<p style='color:#6B7280;margin-top:0'>Generated {datetime.now():%Y-%m-%d %H:%M} "
        f"&middot; {len(groups)} winning number(s) &middot; {len(wins)} winning bond(s)</p>",
    ]
    for number, group in enumerate(groups, start=1):
        bonds = group["bonds"]
        many = len(bonds) > 1
        counter = f" &mdash; {number} of {len(groups)}" if len(groups) > 1 else ""
        parts.append(
            "<table width='100%' cellspacing='0' cellpadding='6' "
            "style='border:1px solid #D1D5DB;margin-bottom:14px'>"
            f"<tr><td colspan='2' bgcolor='#ECFDF5'><b>{escape(heading_text(group))}</b>"
            f"{counter}</td></tr>")
        parts.append(_row("Draw", group["draw"]))
        parts.append(_row("Prize", group["prize"] + (" per bond" if many and total_prize(group)
                                                      else "")))
        if many:
            parts.append(_row("Held in", holders_text(bonds)))
            parts.append(f"<tr><td colspan='2' bgcolor='#FEF3C7'>{escape(sharing_note(group))}"
                         " (the same number sits in several copies).</td></tr>")
            total = total_prize(group)
            if total is not None:
                parts.append(_row("Total prize", money(total)))
        for index, bond in enumerate(bonds, start=1):
            if many:
                parts.append(f"<tr><td colspan='2' bgcolor='#F3F4F6'><b>Bond {index} of "
                             f"{len(bonds)}</b></td></tr>")
            for label, value in copy_lines(bond):
                parts.append(_row(label, value))
        parts.append("</table>")
    parts.append("</body></html>")
    return "".join(parts)


# -------------------------------------------------------------------- export
WIN_HEADERS = ["Draw date", "Draw", "Bond number", "Denomination", "Prize", "Prize amount",
               "Bonds with this number", "Copy (book)", "1st bond number of copy",
               "Position in copy", "Copy size"]


def win_table(wins: list[dict], stamp_header: str = "Approved on",
              stamp_key: str = "approved_at") -> tuple[list[str], list[list]]:
    """Headers + rows for exporting wins (or pending wins) with the copy details."""
    sizes = {group_key(g["bonds"][0]): len(g["bonds"]) for g in group_wins(wins)}
    rows = [[w.get("draw_date"), w.get("draw_label") or "", w.get("bond_number"),
             w.get("denomination"), w.get("prize_label") or "", w.get("prize_amount"),
             max(int(w.get("same_number_count") or 0), sizes[group_key(w)]),
             w.get("copy_name") or "", first_number_text(w),
             w.get("position") if w.get("copy_name") else None,
             w.get("copy_size") if w.get("copy_name") else None,
             w.get(stamp_key) or ""] for w in wins]
    return WIN_HEADERS + [stamp_header], rows
