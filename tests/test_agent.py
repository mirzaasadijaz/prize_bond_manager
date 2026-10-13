import pytest

from .conftest import numbers


def add_draw(db, items, date="2026-10-01", denomination=750, label="Draw #98"):
    draw_id = db.add_draw(date, denomination, label)
    db.add_winning_numbers(draw_id, [(d, k, tier, amount) for (d, k), tier, amount in items])
    return draw_id


def win(pattern, tier="1st Prize", amount=None):
    (item,) = numbers(pattern)
    return item, tier, amount


def test_scan_queues_matches_without_touching_the_waiting_list(seeded, agent):
    draw_id = add_draw(seeded, [win("100056", amount=1500000), win("777777", "2nd Prize")])
    before = seeded.dashboard_stats()["active_count"]
    result = agent.scan(draw_id, trigger="draw")
    assert (result.total_matches, result.new_pending) == (2, 2)
    assert seeded.dashboard_stats()["active_count"] == before        # nothing moved yet
    pending = {p["bond_number"]: p for p in agent.pending()}
    assert set(pending) == {"100056", "777777"}
    assert all(p["bond_status"] == "active" for p in pending.values())


def test_pending_rows_already_carry_the_copy_details(seeded, agent):
    add_draw(seeded, [win("100056"), win("900007", "3rd Prize")])
    agent.scan()
    pending = {p["bond_number"]: p for p in agent.pending()}
    p = pending["100056"]
    assert (p["copy_name"], p["copy_first_number"], p["position"], p["copy_size"]) == (
        "Copy 1", "100001", 56, 100)
    p = pending["900007"]
    assert (p["copy_name"], p["copy_first_number"], p["position"], p["copy_size"]) == (
        "Copy 2", "555001", 24, 25)


def test_approval_moves_bonds_and_snapshots_details(seeded, agent):
    add_draw(seeded, [win("100056", amount=1500000), win("777777", "2nd Prize")])
    agent.scan()
    result = agent.approve_all()
    assert result.approved == 2 and not result.rejected
    assert seeded.pending_count() == 0
    wins = {w["bond_number"]: w for w in seeded.list_wins()}
    w = wins["777777"]
    assert (w["copy_name"], w["copy_first_number"], w["position"], w["copy_size"]) == (
        "Copy 2", "555001", 21, 25)
    assert wins["100056"]["prize_amount"] == 1500000 and wins["100056"]["draw_date"] == "2026-10-01"
    won = {b["number"] for b in seeded.list_bonds(status="won")}
    assert won == {"100056", "777777"}
    assert seeded.dashboard_stats()["active_count"] == 225 - 2


def test_rescan_is_idempotent_and_rejection_sticks(seeded, agent):
    add_draw(seeded, [win("100056"), win("777777")])
    assert agent.scan().new_pending == 2
    again = agent.scan()
    assert (again.total_matches, again.new_pending) == (2, 0)
    first = agent.pending()[0]["pending_id"]
    agent.reject([first])
    assert agent.scan().new_pending == 0 and seeded.pending_count() == 1
    assert len(agent.pending("rejected")) == 1
    agent.restore([first])
    assert seeded.pending_count() == 2


def test_denomination_must_match_unless_draw_is_for_all(seeded, agent):
    add_draw(seeded, [win("400050")], denomination=750)           # bond is a Rs 1500 one
    assert agent.scan().total_matches == 0
    add_draw(seeded, [win("400050")], denomination=None, label="any")
    assert agent.scan().new_pending == 1
    assert agent.pending()[0]["denomination"] == 1500


def test_bonds_added_after_the_draw_are_found_by_a_later_scan(db, agent):
    add_draw(db, [win("123456")])
    assert agent.scan().total_matches == 0
    db.add_copy("Late", numbers("123450-123460"), 750)
    result = agent.run_if_enabled("bonds")
    assert result.new_pending == 1 and agent.pending()[0]["position"] == 7


def test_auto_switch_disables_automatic_runs_only(db, agent):
    add_draw(db, [win("123456")])
    db.add_copy("A", numbers("123450-123460"), 750)
    agent.auto_enabled = False
    assert agent.run_if_enabled("startup") is None and db.pending_count() == 0
    assert agent.scan().new_pending == 1                          # manual still works


def test_warning_when_bond_was_bought_after_the_draw(db, agent):
    db.add_copy("New", numbers("100001-100010"), 750, "2026-12-01")
    add_draw(db, [win("100005")], date="2026-10-01")
    agent.scan()
    assert agent.pending()[0]["warning"]


def test_approval_refuses_when_bond_was_edited_after_the_scan(seeded, agent):
    add_draw(seeded, [win("100056")])
    agent.scan()
    bond = next(b for b in seeded.list_bonds() if b["number"] == "100056")
    seeded.update_bond(bond["id"], "999999", 750, bond["purchase_date"], bond["copy_id"],
                       bond["position"])
    result = agent.approve_all()
    assert result.approved == 0 and "edited" in result.rejected[0][1]
    assert seeded.get_bond(bond["id"])["status"] == "active"


def test_revert_returns_bond_to_waiting_list(seeded, agent):
    add_draw(seeded, [win("100056")])
    agent.scan()
    agent.approve_all()
    win_id = seeded.list_wins()[0]["id"]
    assert seeded.revert_wins([win_id]) == 1
    assert seeded.list_wins() == []
    assert seeded.dashboard_stats()["active_count"] == 225
    assert agent.scan().new_pending == 0                          # reverted = decided, not re-queued


def test_win_report_survives_deleting_the_bond_and_copy(seeded, agent):
    add_draw(seeded, [win("100056")])
    agent.scan()
    agent.approve_all()
    cid = next(c["id"] for c in seeded.list_copies() if c["name"] == "Copy 1")
    seeded.delete_copy(cid, delete_bonds=True)
    w = seeded.list_wins()[0]
    assert (w["copy_name"], w["copy_first_number"], w["position"]) == ("Copy 1", "100001", 56)
    assert w["bond_id"] is None and w["copy_id"] is None


def test_revert_recreates_a_deleted_bond_from_the_snapshot(seeded, agent):
    add_draw(seeded, [win("100056")])
    agent.scan()
    agent.approve_all()
    bond = next(b for b in seeded.list_bonds() if b["number"] == "100056")
    seeded.delete_bonds([bond["id"]])
    seeded.revert_wins([seeded.list_wins()[0]["id"]])
    back = next(b for b in seeded.list_bonds() if b["number"] == "100056")
    assert back["status"] == "active" and back["position"] == 56


def test_deleting_a_draw_clears_its_pending_but_keeps_approved_wins(seeded, agent):
    d1 = add_draw(seeded, [win("100056")])
    d2 = add_draw(seeded, [win("777777")], date="2026-10-15", label="Draw #99")
    agent.scan()
    agent.approve([p["pending_id"] for p in agent.pending() if p["bond_number"] == "100056"])
    seeded.delete_draw(d1)
    seeded.delete_draw(d2)
    assert seeded.pending_count() == 0
    assert [w["bond_number"] for w in seeded.list_wins()] == ["100056"]


def test_deleting_a_bond_removes_its_pending_match(seeded, agent):
    add_draw(seeded, [win("100056")])
    agent.scan()
    bond = next(b for b in seeded.list_bonds() if b["number"] == "100056")
    seeded.delete_bonds([bond["id"]])
    assert seeded.pending_count() == 0


# ---- the same number held in several copies: when it wins, every bond holding it wins ----
@pytest.fixture
def shared(seeded):
    """Copy 4 repeats 100050-100060 of Copy 1; Copy 5 holds 100056 (and 100001) once more."""
    seeded.add_copy("Copy 4", numbers("100050-100060"), 750, "2025-03-01")
    seeded.add_copy("Copy 5", numbers("100056, 100001"), 750, "2025-04-01")
    return seeded


def where(rows):
    return sorted((r["copy_name"], r["copy_first_number"], r["position"]) for r in rows)


def test_every_bond_holding_a_winning_number_is_queued(shared, agent):
    add_draw(shared, [win("100056", amount=1500000)])
    result = agent.scan()
    assert result.new_pending == 3
    pending = agent.pending()
    assert where(pending) == [("Copy 1", "100001", 56), ("Copy 4", "100050", 7),
                              ("Copy 5", "100056", 1)]
    assert {p["same_number_count"] for p in pending} == {3}


def test_approving_one_bond_approves_every_bond_with_that_number(shared, agent):
    add_draw(shared, [win("100056", amount=1500000), win("777777", "2nd Prize")])
    agent.scan()
    row = next(p for p in agent.pending() if p["copy_name"] == "Copy 4")
    result = agent.approve([row["pending_id"]])
    assert result.approved == 3 and result.with_siblings == 2 and not result.rejected
    wins = [w for w in shared.list_wins() if w["bond_number"] == "100056"]
    assert where(wins) == [("Copy 1", "100001", 56), ("Copy 4", "100050", 7), ("Copy 5", "100056", 1)]
    assert {w["same_number_count"] for w in wins} == {3}
    assert all(w["prize_amount"] == 1500000 for w in wins)        # the full prize for every bond
    assert [p["bond_number"] for p in agent.pending()] == ["777777"]  # a different number stays
    assert {b["status"] for b in shared.list_bonds() if b["number"] == "100056"} == {"won"}
    assert shared.dashboard_stats()["prize_total"] == 3 * 1500000


def test_only_pending_siblings_are_pulled_in_and_rejected_ones_stay_out(shared, agent):
    add_draw(shared, [win("100056")])
    agent.scan()
    by_copy = {p["copy_name"]: p["pending_id"] for p in agent.pending()}
    agent.reject([by_copy["Copy 4"]])
    result = agent.approve([by_copy["Copy 1"]])
    assert result.approved == 2 and result.with_siblings == 1
    stay = next(b for b in shared.list_bonds() if b["copy_name"] == "Copy 4" and b["number"] == "100056")
    assert stay["status"] == "active"
    assert shared.pending_siblings([by_copy["Copy 4"]]) == []     # not pending any more


def test_approving_without_siblings_keeps_the_others_pending(shared, agent):
    add_draw(shared, [win("100056")])
    agent.scan()
    first = agent.pending()[0]["pending_id"]
    result = shared.approve_pending([first], include_siblings=False)
    assert result.approved == 1 and result.with_siblings == 0 and shared.pending_count() == 2


def test_reverting_one_win_leaves_the_other_bonds_won(shared, agent):
    add_draw(shared, [win("100056")])
    agent.scan()
    agent.approve_all()
    target = next(w for w in shared.list_wins() if w["copy_name"] == "Copy 4")
    assert shared.revert_wins([target["id"]]) == 1
    left = shared.list_wins()
    assert where(left) == [("Copy 1", "100001", 56), ("Copy 5", "100056", 1)]
    assert {w["same_number_count"] for w in left} == {2}
    assert next(b for b in shared.list_bonds() if b["id"] == target["bond_id"])["status"] == "active"
    assert agent.scan().new_pending == 0                          # reverted = decided


def test_a_bond_added_after_the_win_wins_with_the_others(shared, agent):
    add_draw(shared, [win("100056")])
    agent.scan()
    agent.approve_all()
    shared.add_copy("Copy 6", numbers("100056, 100057"), 750, "2026-01-01")
    assert agent.run_if_enabled("bonds").new_pending == 1
    result = agent.approve_all()
    assert result.approved == 1
    wins = [w for w in shared.list_wins() if w["bond_number"] == "100056"]
    assert len(wins) == 4 and {w["same_number_count"] for w in wins} == {4}


def test_bonds_of_the_same_number_but_other_price_do_not_win(shared, agent):
    shared.add_copy("Rs 1500 book", numbers("100056"), 1500)
    add_draw(shared, [win("100056")], denomination=750)
    agent.scan()
    assert {p["denomination"] for p in agent.pending()} == {750}
    assert len(agent.pending()) == 3


def test_deleting_one_of_the_bonds_keeps_the_rest_of_the_group(shared, agent):
    add_draw(shared, [win("100056")])
    agent.scan()
    victim = next(b for b in shared.list_bonds() if b["copy_name"] == "Copy 5" and b["number"] == "100056")
    shared.delete_bonds([victim["id"]])
    assert shared.pending_count() == 2
    assert {p["same_number_count"] for p in agent.pending()} == {2}
