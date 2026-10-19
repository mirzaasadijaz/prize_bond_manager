import pytest

from .conftest import numbers


def add_draw(db, items, date="2026-10-01", denomination=750, label="Draw #98", location=""):
    draw_id = db.add_draw(date, denomination, label, location)
    db.add_winning_numbers(draw_id, [(d, k, tier, amount) for (d, k), tier, amount in items])
    return draw_id


def win(pattern, tier="1st Prize", amount=None):
    (item,) = numbers(pattern)
    return item, tier, amount


def test_scan_queues_matches_without_recording_anything(seeded, agent):
    draw_id = add_draw(seeded, [win("100056", amount=1500000), win("777777", "2nd Prize")])
    before = seeded.dashboard_stats()["bond_count"]
    result = agent.scan(draw_id, trigger="draw")
    assert (result.total_matches, result.new_pending) == (2, 2)
    assert result.bonds_checked == before == 225
    assert seeded.list_wins() == []                                  # nothing recorded yet
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


def test_approval_adds_wins_and_snapshots_details(seeded, agent):
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
    won = {b["number"] for b in seeded.list_bonds(won=True)}
    assert won == {"100056", "777777"}
    assert seeded.dashboard_stats()["bond_count"] == 225             # bonds stay in play
    assert len(seeded.list_bonds(won=False)) == 223
    assert {w["claim_status"] for w in wins.values()} == {"Not claimed yet"}


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


def test_a_bond_bought_after_the_draw_is_skipped(db, agent):
    db.add_copy("New", numbers("100001-100010"), 750, "2026-12-01")
    add_draw(db, [win("100005")], date="2026-10-01")
    assert agent.scan().new_pending == 0 and agent.pending() == []


def test_approval_refuses_when_bond_was_edited_after_the_scan(seeded, agent):
    add_draw(seeded, [win("100056")])
    agent.scan()
    bond = next(b for b in seeded.list_bonds() if b["number"] == "100056")
    seeded.update_bond(bond["id"], "999999", 750, bond["purchase_date"], bond["copy_id"],
                       bond["position"])
    result = agent.approve_all()
    assert result.approved == 0 and "edited" in result.rejected[0][1]
    assert seeded.get_bond(bond["id"])["times_won"] == 0


def test_undoing_an_approval_removes_the_win_and_keeps_the_bond(seeded, agent):
    add_draw(seeded, [win("100056")])
    agent.scan()
    agent.approve_all()
    win_id = seeded.list_wins()[0]["id"]
    assert seeded.revert_wins([win_id]) == 1
    assert seeded.list_wins() == []
    assert seeded.dashboard_stats()["bond_count"] == 225
    assert seeded.list_bonds(won=True) == []
    assert agent.scan().new_pending == 0                          # reverted = decided, not re-queued
    assert [p["note"] for p in agent.pending("rejected")] == ["Win reverted"]


def test_win_report_survives_deleting_the_bond_and_copy(seeded, agent):
    add_draw(seeded, [win("100056")])
    agent.scan()
    agent.approve_all()
    cid = next(c["id"] for c in seeded.list_copies() if c["name"] == "Copy 1")
    seeded.delete_copy(cid, delete_bonds=True)
    w = seeded.list_wins()[0]
    assert (w["copy_name"], w["copy_first_number"], w["position"]) == ("Copy 1", "100001", 56)
    assert w["bond_id"] is None and w["copy_id"] is None


def test_undoing_the_win_of_a_deleted_bond_does_not_bring_the_bond_back(seeded, agent):
    add_draw(seeded, [win("100056")])
    agent.scan()
    agent.approve_all()
    bond = next(b for b in seeded.list_bonds() if b["number"] == "100056")
    seeded.delete_bonds([bond["id"]])                  # e.g. you cashed the bond in
    assert seeded.revert_wins([seeded.list_wins()[0]["id"]]) == 1
    assert seeded.list_wins() == []
    assert not [b for b in seeded.list_bonds() if b["number"] == "100056"]


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
    assert {b["times_won"] for b in shared.list_bonds() if b["number"] == "100056"} == {1}
    assert shared.dashboard_stats()["prize_total"] == 3 * 1500000


def test_only_pending_siblings_are_pulled_in_and_rejected_ones_stay_out(shared, agent):
    add_draw(shared, [win("100056")])
    agent.scan()
    by_copy = {p["copy_name"]: p["pending_id"] for p in agent.pending()}
    agent.reject([by_copy["Copy 4"]])
    result = agent.approve([by_copy["Copy 1"]])
    assert result.approved == 2 and result.with_siblings == 1
    stay = next(b for b in shared.list_bonds() if b["copy_name"] == "Copy 4" and b["number"] == "100056")
    assert stay["times_won"] == 0
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
    assert next(b for b in shared.list_bonds() if b["id"] == target["bond_id"])["times_won"] == 0
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


# ---- a bond keeps playing after it wins: it can win again, in another draw / place / time ----
def test_a_bond_that_won_takes_part_in_the_next_draw(seeded, agent):
    add_draw(seeded, [win("100056", amount=1500000)], date="2026-10-01", label="Draw #98",
             location="Lahore")
    agent.scan()
    agent.approve_all()
    add_draw(seeded, [win("100056", "2nd Prize", 500000)], date="2026-11-01", label="Draw #99",
             location="Karachi")
    result = agent.scan()
    assert result.new_pending == 1
    (again,) = agent.pending()
    assert again["times_won"] == 1 and again["draw_location"] == "Karachi"      # a repeat winner
    agent.approve_all()
    first, second = sorted(seeded.list_wins(), key=lambda w: w["draw_date"])
    assert first["bond_id"] == second["bond_id"]                                # the same bond
    assert (first["draw_date"], first["location"], first["win_no"], first["times_won"]) == (
        "2026-10-01", "Lahore", 1, 2)
    assert (second["draw_date"], second["location"], second["win_no"], second["times_won"]) == (
        "2026-11-01", "Karachi", 2, 2)
    assert next(b for b in seeded.list_bonds() if b["number"] == "100056")["times_won"] == 2
    stats = seeded.dashboard_stats()
    assert stats["win_count"] == 2 and stats["repeat_winners"] == 1
    assert stats["prize_total"] == 2_000_000


def test_a_bond_cannot_win_twice_in_the_same_draw(seeded, agent):
    draw = add_draw(seeded, [win("100056")])
    agent.scan()
    agent.approve_all()
    assert agent.scan(draw).new_pending == 0
    assert len(seeded.list_wins()) == 1


def test_a_win_starts_with_the_location_of_its_draw(seeded, agent):
    add_draw(seeded, [win("100056"), win("777777")], location="  Lahore ")
    add_draw(seeded, [win("900007")], date="2026-11-01", label="Draw #99")        # no location
    agent.scan()
    agent.approve_all()
    where_ = {w["bond_number"]: w["location"] for w in seeded.list_wins()}
    assert where_ == {"100056": "Lahore", "777777": "Lahore", "900007": None}
    assert seeded.known_locations() == ["Lahore"]


def test_win_details_can_be_set_for_one_win_or_many(shared, agent):
    add_draw(shared, [win("100056", amount=1500000)], location="Lahore")
    agent.scan()
    agent.approve_all()
    wins = shared.list_wins()
    assert {w["claim_status"] for w in wins} == {"Not claimed yet"}
    one, *rest = wins
    assert shared.update_win_details([one["id"]], claim_status="Claim submitted",
                                     feedback="  handed in at the bank, ref 4411 ") == 1
    got = shared.get_win(one["id"])
    assert (got["claim_status"], got["feedback"], got["location"]) == (
        "Claim submitted", "handed in at the bank, ref 4411", "Lahore")      # location untouched
    assert got["updated_at"]
    assert shared.update_win_details([w["id"] for w in rest], location="Karachi branch") == 2
    assert {w["location"] for w in shared.list_wins() if w["id"] != one["id"]} == {"Karachi branch"}
    assert shared.get_win(one["id"])["location"] == "Lahore"
    shared.update_win_details([one["id"]], feedback="")                         # empty clears
    assert shared.get_win(one["id"])["feedback"] is None
    assert shared.update_win_details([one["id"]]) == 0                          # nothing to change
    with pytest.raises(ValueError, match="not a win status"):
        shared.update_win_details([one["id"]], claim_status="Whatever")
    assert any(e["action"] == "Win details updated" for e in shared.list_activity())


def test_dashboard_counts_wins_that_are_not_paid_yet(seeded, agent):
    add_draw(seeded, [win("100056", amount=1000), win("777777", amount=500)])
    agent.scan()
    agent.approve_all()
    assert seeded.dashboard_stats()["unpaid_count"] == 2
    paid = next(w for w in seeded.list_wins() if w["bond_number"] == "100056")
    seeded.update_win_details([paid["id"]], claim_status="Paid")
    stats = seeded.dashboard_stats()
    assert (stats["unpaid_count"], stats["unpaid_total"]) == (1, 500)


def test_win_details_survive_deleting_the_bond(seeded, agent):
    add_draw(seeded, [win("100056")], location="Lahore")
    agent.scan()
    agent.approve_all()
    (w,) = seeded.list_wins()
    seeded.update_win_details([w["id"]], claim_status="Paid", feedback="cash received")
    seeded.delete_bonds([w["bond_id"]])
    (w,) = seeded.list_wins()
    assert (w["claim_status"], w["feedback"], w["location"], w["times_won"]) == (
        "Paid", "cash received", "Lahore", 1)
