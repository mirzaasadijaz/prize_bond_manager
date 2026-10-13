import sqlite3

import pytest

from app.db import CopyNameError, DuplicateBondError, PositionTakenError
from app.processing.numbers import NumberError

from .conftest import numbers


def positions(db, copy_name):
    return {b["number"]: b["position"] for b in db.copy_bonds(
        next(c["id"] for c in db.list_copies() if c["name"] == copy_name))}


def test_copies_need_not_share_range_size_or_sequence(seeded):
    copies = {c["name"]: c for c in seeded.list_copies()}
    assert copies["Copy 1"]["size"] == 100 and copies["Copy 1"]["first_number"] == "100001"
    assert copies["Copy 2"]["size"] == 25 and copies["Copy 2"]["first_number"] == "555001"
    assert copies["Copy 3"]["size"] == 100 and copies["Copy 3"]["first_number"] == "400100"
    # position follows the order typed, not the numeric value
    assert positions(seeded, "Copy 2")["777777"] == 21
    assert positions(seeded, "Copy 2")["900007"] == 24
    assert positions(seeded, "Copy 3")["400001"] == 100          # descending copy


def test_same_number_can_be_held_in_several_copies(db):
    db.add_loose_bonds(numbers("100050"), 750)
    result = db.add_copy("Book", numbers("100001-100100"), 750)
    assert result.added == 100 and not result.skipped_duplicates and result.shared == 1
    other = db.add_copy("Book 2", numbers("100050-100052"), 750)
    assert other.added == 3 and other.shared == 3
    held = [b for b in db.list_bonds() if b["number"] == "100050"]
    assert len(held) == 3 and {b["same_count"] for b in held} == {3}
    assert {b["same_count"] for b in db.list_bonds() if b["number"] == "100001"} == {1}
    assert db.dashboard_stats()["shared_numbers"] == 3          # 100050, 100051, 100052


def test_skip_existing_leaves_numbers_out_but_positions_stay_physical(db):
    db.add_loose_bonds(numbers("100050"), 750)
    result = db.add_copy("Book", numbers("100001-100100"), 750, skip_existing=True)
    assert result.added == 99 and result.skipped_duplicates == ["100050"] and result.shared == 0
    pos = positions(db, "Book")
    assert pos["100051"] == 51                                   # not shifted by the skipped bond
    assert db.get_copy(result.copy_ids[0])["size"] == 100
    again = db.add_loose_bonds(numbers("100099-100101"), 750, skip_existing=True)
    assert again.added == 1 and again.skipped_duplicates == ["100099", "100100"]


def test_a_copy_never_holds_the_same_number_twice(db):
    twice = [("100001", 100001), ("100002", 100002), ("100001", 100001)]
    result = db.add_copy("Book", twice, 750)
    assert result.added == 2 and result.skipped_duplicates == ["100001"]
    cid = result.copy_ids[0]
    again = db.append_to_copy(cid, numbers("100002-100004"), 750)
    assert again.added == 2 and again.skipped_duplicates == ["100002"]      # no skip flag needed
    with pytest.raises(sqlite3.IntegrityError):                              # the database agrees
        db.conn.execute("INSERT INTO bonds (number, num, denomination, status, copy_id, position, "
                        "created_at) VALUES ('100001', 100001, 750, 'active', ?, 99, 'x')", (cid,))


def test_copies_added_together_may_share_numbers_even_when_skipping_existing(db):
    db.add_loose_bonds(numbers("100002"), 750)
    snapshot = db.held_keys(750, [100001, 100002, 100003])
    assert snapshot == {100002}
    first = db.add_copy("A", numbers("100001-100003"), 750, skip_keys=snapshot)
    second = db.add_copy("B", numbers("100001-100003"), 750, skip_keys=snapshot)
    assert first.added == second.added == 2                       # 100002 left out of both
    assert {b["same_count"] for b in db.list_bonds() if b["number"] == "100001"} == {2}


def test_same_number_in_other_denomination_is_a_different_bond(db):
    db.add_loose_bonds(numbers("123456"), 750)
    result = db.add_loose_bonds(numbers("123456"), 1500)
    assert result.added == 1 and not result.skipped_duplicates and result.shared == 0
    assert [b["same_count"] for b in db.list_bonds()] == [1, 1]


def test_copy_names_are_unique_and_suggested(db):
    first = db.add_copy("Copy 1", numbers("1-3"), 100)
    second = db.add_copy("copy 1", numbers("10-12"), 100)
    assert first.copy_names == ["Copy 1"]
    assert second.copy_names == ["copy 1 (2)"] and second.renamed_copies
    assert db.suggest_copy_names(2) == ["Copy 2", "Copy 3"]


def test_append_continues_after_last_position(seeded):
    cid = next(c["id"] for c in seeded.list_copies() if c["name"] == "Copy 2")
    result = seeded.append_to_copy(cid, numbers("600001-600003"), 750)
    assert result.added == 3
    assert positions(seeded, "Copy 2")["600001"] == 26
    assert seeded.get_copy(cid)["size"] == 28


def test_update_bond_validates_and_keeps_first_number_in_sync(seeded):
    cid = next(c["id"] for c in seeded.list_copies() if c["name"] == "Copy 1")
    first = seeded.list_bonds(copy_id=cid)[0]
    assert first["position"] == 1
    seeded.update_bond(first["id"], "000042", 750, "2025-01-11", cid, 1)
    assert seeded.get_copy(cid)["first_number"] == "000042"
    other = seeded.list_bonds(copy_id=cid)[1]
    with pytest.raises(PositionTakenError):
        seeded.update_bond(other["id"], other["number"], 750, None, cid, 1)
    with pytest.raises(DuplicateBondError):
        seeded.update_bond(other["id"], "000042", 750, None, cid, other["position"])
    with pytest.raises(NumberError):
        seeded.update_bond(other["id"], "12x", 750, None, cid, other["position"])


def test_delete_copy_can_keep_bonds_as_loose(seeded):
    cid = next(c["id"] for c in seeded.list_copies() if c["name"] == "Copy 3")
    assert seeded.delete_copy(cid, delete_bonds=False) == 100
    loose = seeded.list_bonds(denomination=1500)
    assert len(loose) == 100 and all(b["copy_id"] is None and b["position"] is None for b in loose)
    cid2 = next(c["id"] for c in seeded.list_copies() if c["name"] == "Copy 2")
    assert seeded.delete_copy(cid2, delete_bonds=True) == 25
    assert seeded.list_bonds(copy_id=cid2) == []


def test_rename_copy_rejects_taken_name(seeded):
    cid = next(c["id"] for c in seeded.list_copies() if c["name"] == "Copy 1")
    with pytest.raises(CopyNameError):
        seeded.rename_copy(cid, "copy 2")
    seeded.rename_copy(cid, "Blue book", "bought in Lahore")
    assert seeded.get_copy(cid)["name"] == "Blue book"


def test_filters_and_denominations(seeded):
    assert seeded.denominations() == [750, 1500]
    assert len(seeded.list_bonds(denomination=1500)) == 100
    assert [b["number"] for b in seeded.list_bonds(number_from=100001, number_to=100003)] == [
        "100001", "100002", "100003"]
    assert len(seeded.list_bonds(date_from="2025-02-01", date_to="2025-12-31")) == 25


def test_transaction_rolls_back_on_error(db):
    with pytest.raises(RuntimeError):
        with db.tx():
            db.add_loose_bonds(numbers("1-5"), 100)
            raise RuntimeError("boom")
    assert db.list_bonds() == []


def test_leading_zero_numbers_match_regardless_of_padding(db):
    db.add_loose_bonds(numbers("123"), 100)
    assert db.list_bonds()[0]["number"] == "000123"
    assert db.held_keys(100, [123]) == {123}


def test_editing_a_number_into_another_copy_is_allowed_but_not_into_the_same_copy(seeded):
    copy1 = next(c["id"] for c in seeded.list_copies() if c["name"] == "Copy 1")
    copy2 = next(c["id"] for c in seeded.list_copies() if c["name"] == "Copy 2")
    bond = seeded.list_bonds(copy_id=copy2)[0]                  # 555001, position 1
    seeded.update_bond(bond["id"], "100056", 750, None, copy2, bond["position"])
    assert {b["same_count"] for b in seeded.list_bonds() if b["number"] == "100056"} == {2}
    with pytest.raises(DuplicateBondError):                      # Copy 1 already holds 100056
        seeded.update_bond(bond["id"], "100056", 750, None, copy1, None)
    other = seeded.list_bonds(copy_id=copy1)[1]
    with pytest.raises(DuplicateBondError):                      # same copy, another bond has it
        seeded.update_bond(other["id"], "100056", 750, None, copy1, other["position"])


def test_loose_bonds_with_the_same_number_are_allowed(db):
    db.add_loose_bonds(numbers("123456"), 100)
    db.add_loose_bonds(numbers("123456"), 100)
    assert [b["same_count"] for b in db.list_bonds()] == [2, 2]
