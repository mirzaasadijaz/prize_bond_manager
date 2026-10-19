"""Sales: bonds sold to somebody leave your holdings, but keep the wins earned before the sale."""
import pytest

from app.db import SaleError
from app.processing.sales import parse_amount, prices_for, split_total
from tests.conftest import numbers


def ids(db, copy_name=None, sold=False):
    return [b["id"] for b in db.list_bonds(sold=sold)
            if copy_name is None or b["copy_name"] == copy_name]


def draw_with(db, date, winners, denomination=750, location="Lahore"):
    draw_id = db.add_draw(date, denomination, "Draw", location)
    items = []
    for n in winners:
        display, key = numbers(n)[0]
        items.append((display, key, "1st Prize", 1_500_000))
    db.add_winning_numbers(draw_id, items)
    return draw_id


# ----------------------------------------------------------------- recording
def test_a_sale_marks_the_bonds_sold_and_updates_every_count(seeded):
    seeded.add_loose_bonds(numbers("123456"), 750, "2025-01-01")
    copy1 = ids(seeded, "Copy 1")
    sale_id = seeded.record_sale(copy1[:10], "2026-10-14", "Ali", "0300-1234567", "Lahore", "cash")

    sale = seeded.get_sale(sale_id)
    assert (sale["buyer"], sale["contact"], sale["location"], sale["note"]) == (
        "Ali", "0300-1234567", "Lahore", "cash")
    assert sale["bonds"] == 10 and sale["face_value"] == 7500 and sale["total_amount"] == 7500

    held = {b["id"] for b in seeded.list_bonds(sold=False)}
    sold = {b["id"] for b in seeded.list_bonds(sold=True)}
    assert sold == set(copy1[:10]) and not held & sold
    assert len(seeded.list_bonds()) == len(held) + len(sold)           # nothing was deleted

    copy = next(c for c in seeded.list_copies() if c["name"] == "Copy 1")
    assert (copy["bonds"], copy["sold"], copy["size"]) == (90, 10, 100)  # positions are unchanged

    stats = seeded.dashboard_stats()
    assert stats["sold_count"] == 10 and stats["sale_total"] == 7500 and stats["sale_count"] == 1
    assert stats["bond_count"] == len(held)
    row = next(d for d in stats["by_denomination"] if d["denomination"] == 750)
    assert row["sold"] == 10


def test_a_sold_bond_keeps_its_copy_and_position_and_says_who_bought_it(seeded):
    first = seeded.copy_bonds(next(c["id"] for c in seeded.list_copies()
                                   if c["name"] == "Copy 1"))[4]
    seeded.record_sale([first["id"]], "2026-10-14", "Sara")
    bond = seeded.get_bond(first["id"])
    assert (bond["copy_name"], bond["position"]) == ("Copy 1", 5)
    assert (bond["sold_date"], bond["sold_to"]) == ("2026-10-14", "Sara")
    assert bond["same_count"] == 0                                    # not "held" any more
    (item,) = seeded.sale_items(bond["sale_id"])
    assert (item["copy_name"], item["position"], item["copy_first_number"]) == (
        "Copy 1", 5, "100001")


def test_prices_default_to_face_value_and_can_be_set(seeded):
    a, b = ids(seeded, "Copy 1")[:2]
    s1 = seeded.record_sale([a], "2026-10-14")
    s2 = seeded.record_sale([b], "2026-10-14", prices=[800])
    assert seeded.get_sale(s1)["total_amount"] == 750
    assert seeded.get_sale(s2)["total_amount"] == 800
    assert seeded.get_sale(s2)["difference"] == 50


def test_splitting_a_total_adds_up_exactly():
    assert split_total(3100, [750] * 4) == [775] * 4
    parts = split_total(1000, [750, 750, 1500])
    assert sum(parts) == 1000 and abs(parts[2] - 2 * parts[0]) <= 2
    assert sum(split_total(7, [100, 100, 100])) == 7
    assert prices_for("face", [750, 1500]) == [750, 1500]
    assert prices_for("each", [750, 1500], 800) == [800, 800]
    assert sum(prices_for("total", [750, 1500, 200], 2999)) == 2999
    assert parse_amount("Rs 3,100") == 3100 and parse_amount("") is None
    assert parse_amount("12.5") is None


def test_bad_sales_are_refused_and_change_nothing(seeded):
    some = ids(seeded, "Copy 1")[:3]
    with pytest.raises(SaleError):
        seeded.record_sale([], "2026-10-14")
    with pytest.raises(SaleError):
        seeded.record_sale(some, "14-10-2026")
    with pytest.raises(SaleError):
        seeded.record_sale(some, "2026-10-14", prices=[1, 2])
    with pytest.raises(SaleError):
        seeded.record_sale(some + [999999], "2026-10-14")
    seeded.record_sale(some, "2026-10-14")
    with pytest.raises(SaleError, match="Already sold"):
        seeded.record_sale(some[:1], "2026-10-15")
    assert seeded.sales_summary()["sales"] == 1


# ------------------------------------------------------------- who owns a win
def test_a_sold_bond_still_wins_draws_held_before_the_sale_but_not_after(seeded):
    bond = next(b for b in seeded.list_bonds() if b["number"] == "100010")
    early = draw_with(seeded, "2026-10-01", ["100010"])
    late = draw_with(seeded, "2026-10-20", ["100010"])
    same_day = draw_with(seeded, "2026-10-14", ["100010"])
    seeded.record_sale([bond["id"]], "2026-10-14", "Ali")

    scan = seeded.scan_for_matches()
    pending = {p["draw_id"] for p in seeded.list_pending() if p["bond_id"] == bond["id"]}
    assert pending == {early}                      # sale date itself and later = the buyer's
    assert late not in pending and same_day not in pending
    assert scan.new_pending == 1


def test_selling_removes_waiting_matches_from_draws_on_or_after_the_sale(seeded):
    bond = next(b for b in seeded.list_bonds() if b["number"] == "100010")
    early = draw_with(seeded, "2026-10-01", ["100010"])
    late = draw_with(seeded, "2026-10-20", ["100010"])
    seeded.scan_for_matches()
    assert {p["draw_id"] for p in seeded.list_pending()} == {early, late}
    seeded.record_sale([bond["id"]], "2026-10-14", "Ali")
    assert {p["draw_id"] for p in seeded.list_pending()} == {early}


def test_approved_wins_stay_yours_after_the_bond_is_sold(seeded):
    bond = next(b for b in seeded.list_bonds() if b["number"] == "100010")
    draw_with(seeded, "2026-10-01", ["100010"])
    seeded.scan_for_matches()
    seeded.approve_pending([p["pending_id"] for p in seeded.list_pending()])
    seeded.record_sale([bond["id"]], "2026-10-14", "Ali")
    (win,) = seeded.list_wins()
    assert win["bond_number"] == "100010" and win["claim_status"] == "Not claimed yet"
    assert (win["sold_date"], win["sold_to"]) == ("2026-10-14", "Ali")


def test_a_match_for_a_bond_sold_before_the_draw_cannot_be_approved(seeded):
    bond = next(b for b in seeded.list_bonds() if b["number"] == "100010")
    draw_with(seeded, "2026-10-01", ["100010"])
    seeded.scan_for_matches()
    # make the data inconsistent on purpose: sold before the draw, pending row still there
    seeded.conn.execute("INSERT INTO sales (sale_date, total_amount, created_at) "
                        "VALUES ('2026-09-01', 750, 'x')")
    sale_id = seeded.conn.execute("SELECT MAX(id) FROM sales").fetchone()[0]
    seeded.conn.execute("UPDATE bonds SET sale_id = ?, sold_date = '2026-09-01' WHERE id = ?",
                        (sale_id, bond["id"]))
    result = seeded.approve_pending([p["pending_id"] for p in seeded.list_pending()])
    assert result.approved == 0 and "sold" in result.rejected[0][1]


def test_the_agent_counts_only_bonds_you_still_hold(seeded):
    before = seeded.scan_for_matches().bonds_checked
    seeded.record_sale(ids(seeded, "Copy 1")[:10], "2026-10-14")
    assert seeded.scan_for_matches().bonds_checked == before - 10


# ------------------------------------------------------------------ undo / return
def test_undoing_a_sale_puts_the_bonds_back_in_play(seeded):
    bond = next(b for b in seeded.list_bonds() if b["number"] == "100010")
    draw_with(seeded, "2026-10-20", ["100010"])
    sale_id = seeded.record_sale([bond["id"]], "2026-10-14", "Ali")
    assert seeded.scan_for_matches().new_pending == 0
    assert seeded.undo_sale(sale_id) == 1
    assert seeded.get_sale(sale_id) is None
    back = seeded.get_bond(bond["id"])
    assert back["sale_id"] is None and back["sold_date"] is None
    assert seeded.scan_for_matches().new_pending == 1                  # it takes part again


def test_taking_some_bonds_back_keeps_the_rest_sold_and_fixes_the_total(seeded):
    a, b, c = ids(seeded, "Copy 1")[:3]
    sale_id = seeded.record_sale([a, b, c], "2026-10-14", "Ali", prices=[800, 800, 900])
    items = seeded.sale_items(sale_id)
    assert seeded.return_sale_items([items[0]["id"]]) == 1
    sale = seeded.get_sale(sale_id)
    assert sale["bonds"] == 2 and sale["total_amount"] == sum(i["price"] for i in items[1:])
    assert seeded.get_bond(a)["sale_id"] is None
    assert seeded.get_bond(b)["sale_id"] == sale_id
    seeded.return_sale_items([i["id"] for i in seeded.sale_items(sale_id)])
    assert seeded.get_sale(sale_id) is None                           # an empty sale disappears


def test_editing_a_sale_moves_the_date_of_its_bonds(seeded):
    bond = next(b for b in seeded.list_bonds() if b["number"] == "100010")
    draw_with(seeded, "2026-10-10", ["100010"])
    sale_id = seeded.record_sale([bond["id"]], "2026-10-14", "Ali")
    seeded.scan_for_matches()
    assert len(seeded.list_pending()) == 1                            # the draw was before the sale
    seeded.update_sale(sale_id, sale_date="2026-10-05", buyer="Ali Khan")
    assert seeded.get_bond(bond["id"])["sold_date"] == "2026-10-05"
    assert seeded.get_sale(sale_id)["buyer"] == "Ali Khan"
    assert seeded.list_pending() == []                                # now the buyer's draw
    with pytest.raises(SaleError):
        seeded.update_sale(sale_id, sale_date="soon")


# --------------------------------------------------------------------- guards
def test_a_sold_bond_cannot_be_edited_until_the_sale_is_undone(seeded):
    bond = seeded.list_bonds()[0]
    sale_id = seeded.record_sale([bond["id"]], "2026-10-14")
    with pytest.raises(ValueError, match="sold"):
        seeded.update_bond(bond["id"], bond["number"], bond["denomination"], None,
                           bond["copy_id"], bond["position"])
    seeded.undo_sale(sale_id)
    seeded.update_bond(bond["id"], bond["number"], bond["denomination"], None,
                       bond["copy_id"], bond["position"])


def test_deleting_a_sold_bond_keeps_the_sale_record(seeded):
    bond = seeded.list_bonds()[0]
    sale_id = seeded.record_sale([bond["id"]], "2026-10-14", "Ali")
    seeded.delete_bonds([bond["id"]])
    (item,) = seeded.sale_items(sale_id)
    assert item["bond_number"] == bond["number"] and not item["bond_exists"]
    assert seeded.return_sale_items([item["id"]]) == 0                 # nothing to give back
    assert seeded.get_sale(sale_id) is None


def test_a_number_you_sold_can_be_added_again_but_not_twice_in_the_same_copy(seeded):
    bond = next(b for b in seeded.list_bonds() if b["number"] == "100010")
    seeded.record_sale([bond["id"]], "2026-10-14")
    key = bond["num"]
    assert key not in seeded.held_keys(750, [key])                     # no longer "held"
    assert key in seeded.held_keys(750, [key], bond["copy_id"])        # still sits in its copy
    result = seeded.add_loose_bonds([(bond["number"], key)], 750, skip_existing=True)
    assert result.added == 1


def test_same_number_counts_ignore_sold_bonds(seeded):
    a = next(b for b in seeded.list_bonds() if b["number"] == "100056")
    seeded.add_copy("Copy 9", numbers("100056"), 750)
    assert seeded.get_bond(a["id"])["same_count"] == 2
    seeded.record_sale([a["id"]], "2026-10-14")
    other = next(b for b in seeded.list_bonds(sold=False) if b["number"] == "100056")
    assert other["same_count"] == 1
