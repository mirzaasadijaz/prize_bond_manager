"""The files in sample_data/ import cleanly and show the same-number-wins-together rule."""
from pathlib import Path

import pytest

from app.processing.agent import WinAgent
from app.processing.importer import ImportOptions, import_file, load_records

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"

pytestmark = pytest.mark.skipif(not SAMPLES.exists(), reason="sample_data/ not present")


def load_all(db):
    import_file(db, SAMPLES / "bonds_with_copies.csv")
    import_file(db, SAMPLES / "copies_workbook.xlsx")
    import_file(db, SAMPLES / "copies_list.docx", ImportOptions(default_denomination=100))


def test_sample_files_import_as_copies(db):
    load_all(db)
    copies = {c["name"]: c for c in db.list_copies()}
    assert set(copies) == {"Book A", "Book B", "Book C", "copies_workbook - Copy 1",
                           "copies_workbook - Copy 2", "Copy 1", "Copy 2", "Copy 3"}
    assert copies["Book C"]["first_number"] == "250020" and copies["Book C"]["size"] == 10
    assert copies["Book B"]["first_number"] == "100011" and copies["Book B"]["size"] == 20
    assert db.dashboard_stats()["shared_numbers"] == 10 + 5 + 5       # A/B, workbook, Word copies


def test_winning_numbers_file_wins_in_both_copies_holding_each_number(db):
    load_all(db)
    draw = db.add_draw("2026-10-01", None, "Sample draw")
    parsed = load_records(SAMPLES / "winning_numbers.csv")
    db.add_winning_numbers(draw, [(r.display, r.key, "1st Prize", 1_000_000) for r in parsed.records])
    agent = WinAgent(db)
    assert agent.scan(draw).new_pending == 7           # 100016 x2, 250015 x1, 300007 x2, 400008 x2
    pending = agent.pending()
    by_number = {}
    for row in pending:
        by_number.setdefault(row["bond_number"], []).append(
            (row["copy_name"], row["copy_first_number"], row["position"]))
    assert sorted(by_number["100016"]) == [("Book A", "100001", 16), ("Book B", "100011", 6)]
    assert by_number["250015"] == [("Book C", "250020", 6)]
    assert sorted(by_number["300007"]) == [("copies_workbook - Copy 1", "300001", 7),
                                           ("copies_workbook - Copy 2", "300006", 2)]
    assert sorted(by_number["400008"]) == [("Copy 1", "400001", 8), ("Copy 2", "400006", 3)]
    result = agent.approve([pending[0]["pending_id"]])
    assert result.approved >= 2 and result.with_siblings >= 1


def test_numbers_listed_under_a_word_heading_join_that_copy(db):
    load_all(db)
    copy = next(c for c in db.list_copies() if c["name"] == "Copy 3")
    assert [(b["number"], b["position"]) for b in db.copy_bonds(copy["id"])] == [
        ("123456", 1), ("234567", 2), ("345678", 3)]
