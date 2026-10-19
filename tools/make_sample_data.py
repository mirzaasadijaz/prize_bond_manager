"""Create the example files in ``sample_data/`` (run:  python tools/make_sample_data.py).

The files share some bond numbers between copies on purpose: the same number may sit in
several copies, and when it is drawn every bond holding it wins.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
from docx import Document

OUT = Path(__file__).resolve().parent.parent / "sample_data"


def csv_with_copies() -> None:
    """Book A and Book B (Rs 750) overlap on 100011-100020; Book C (Rs 1500) runs backwards."""
    rows = []
    for name, numbers, price, date in (
            ("Book A", range(100001, 100021), 750, "2025-01-10"),
            ("Book B", range(100011, 100031), 750, "2025-03-05"),
            ("Book C", range(250020, 250010, -1), 1500, "2025-06-20")):
        for position, number in enumerate(numbers, start=1):
            rows.append([number, price, date, name, position])
    with open(OUT / "bonds_with_copies.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Bond Number", "Denomination", "Date of Purchase", "Copy", "Position"])
        writer.writerows(rows)


def excel_two_sheets() -> None:
    """Each sheet is one copy; 300006-300010 appear in both (Rs 200)."""
    with pd.ExcelWriter(OUT / "copies_workbook.xlsx") as writer:
        for sheet, start in (("Copy 1", 300001), ("Copy 2", 300006)):
            frame = pd.DataFrame({"Bond No": range(start, start + 10), "Price": 200,
                                  "Purchase Date": "2026-02-14"})
            frame.to_excel(writer, sheet_name=sheet, index=False)


def word_list() -> None:
    """'Copy N:' lines name the copies; the price is chosen in the import dialog."""
    document = Document()
    document.add_heading("My prize bonds", level=1)
    document.add_paragraph("Copy 1: 400001-400010")
    document.add_paragraph("Copy 2: 400006-400015")
    document.add_paragraph("Copy 3")                    # a heading line; its numbers follow
    document.add_paragraph("123456, 234567, 345678")
    document.save(OUT / "copies_list.docx")


def csv_with_location() -> None:
    """The optional Location column: two copies kept in different places, and one single bond
    that is kept somewhere else than the rest of its copy (a bond without a place is allowed)."""
    rows = []
    for name, numbers, price, date, place in (
            ("Safe Book 1", range(500001, 500011), 750, "2026-01-05", "Home safe"),
            ("Locker Book 1", range(510001, 510011), 1500, "2026-02-10", "Bank locker")):
        for position, number in enumerate(numbers, start=1):
            rows.append([number, price, date, name, position,
                         "Office drawer" if number == 500003 else place])
    rows.append([520001, 200, "2026-03-01", "", "", ""])             # loose, no place given
    with open(OUT / "bonds_with_location.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Bond Number", "Denomination", "Date of Purchase", "Copy", "Position",
                         "Location"])
        writer.writerows(rows)


def winning_numbers() -> None:
    """Four winning numbers; each one is held by two bonds in the sample copies."""
    with open(OUT / "winning_numbers.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Winning Number"])
        for number in (100016, 250015, 300007, 400008):
            writer.writerow([number])


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    csv_with_copies()
    excel_two_sheets()
    word_list()
    csv_with_location()
    winning_numbers()
    print("Sample files written to", OUT)
