"""Optional location on bonds and copies, and where a draw's numbers came from."""
from app.db.core import KEEP
from tests.conftest import numbers


def test_location_is_optional_everywhere(db):
    db.add_loose_bonds(numbers("100001-100003"), 750)
    db.add_copy("Copy 1", numbers("200001-200003"), 750)
    assert all(b["location"] is None for b in db.list_bonds())
    assert db.list_copies()[0]["location"] is None


def test_loose_bonds_take_the_location_you_give(db):
    db.add_loose_bonds(numbers("100001-100003"), 750, location="  Home safe ")
    assert {b["location"] for b in db.list_bonds()} == {"Home safe"}


def test_a_copy_and_its_bonds_share_the_location(db):
    db.add_copy("Copy 1", numbers("100001-100005"), 750, location="Lahore office")
    (copy,) = db.list_copies()
    assert copy["location"] == "Lahore office"
    assert {b["location"] for b in db.copy_bonds(copy["id"])} == {"Lahore office"}
    assert db.copy_bonds(copy["id"])[0]["copy_location"] == "Lahore office"


def test_each_bond_can_have_its_own_place_and_the_copy_shows_a_shared_one_only(db):
    nums = numbers("100001-100004")
    db.add_copy("Mixed", nums, 750, locations=["Lahore", "Lahore", "Karachi", None])
    db.add_copy("Same", numbers("300001-300002"), 750, location="Multan",
                locations=["Multan", None])
    mixed, same = db.list_copies()
    assert mixed["location"] is None                      # the bonds are in different places
    assert same["location"] == "Multan"
    assert [b["location"] for b in db.copy_bonds(mixed["id"])] == ["Lahore", "Lahore", "Karachi", None]
    assert [b["location"] for b in db.copy_bonds(same["id"])] == ["Multan", "Multan"]  # default


def test_bonds_added_to_a_copy_get_their_own_location(db):
    db.add_copy("Copy 1", numbers("100001-100002"), 750, location="Lahore")
    (copy,) = db.list_copies()
    db.append_to_copy(copy["id"], numbers("100003-100004"), 750, location="Karachi")
    assert [b["location"] for b in db.copy_bonds(copy["id"])] == [
        "Lahore", "Lahore", "Karachi", "Karachi"]


def test_editing_a_bond_changes_or_keeps_or_clears_its_location(db):
    db.add_copy("Copy 1", numbers("100001"), 750, location="Lahore")
    bond = db.list_bonds()[0]
    args = (bond["id"], bond["number"], 750, None, bond["copy_id"], bond["position"])
    db.update_bond(*args)                                  # location not mentioned: kept
    assert db.get_bond(bond["id"])["location"] == "Lahore"
    db.update_bond(*args, location="Karachi")
    assert db.get_bond(bond["id"])["location"] == "Karachi"
    db.update_bond(*args, location="  ")
    assert db.get_bond(bond["id"])["location"] is None
    db.update_bond(*args, location=KEEP)


def test_changing_a_copys_location_can_move_all_its_bonds(db):
    db.add_copy("Copy 1", numbers("100001-100003"), 750, location="Lahore")
    (copy,) = db.list_copies()
    db.rename_copy(copy["id"], "Copy 1", None, location="Karachi")          # copy only
    assert db.get_copy(copy["id"])["location"] == "Karachi"
    assert {b["location"] for b in db.copy_bonds(copy["id"])} == {"Lahore"}
    db.rename_copy(copy["id"], "Copy 1", None, location="Multan", apply_to_bonds=True)
    assert {b["location"] for b in db.copy_bonds(copy["id"])} == {"Multan"}
    db.rename_copy(copy["id"], "Copy One", "note")                          # location untouched
    assert db.get_copy(copy["id"])["location"] == "Multan"


def test_known_locations_gathers_every_place_used(db):
    db.add_copy("Copy 1", numbers("100001"), 750, location="Lahore office")
    db.add_loose_bonds(numbers("200001"), 750, location="Home safe")
    db.add_draw("2026-10-01", 750, "", "Karachi")
    db.record_sale([db.list_bonds()[0]["id"]], "2026-10-14", location="Multan")
    assert {"Lahore office", "Home safe", "Karachi", "Multan"} <= set(db.known_locations())


def test_the_place_a_bond_is_kept_is_saved_with_its_win(db, agent):
    db.add_copy("Copy 1", numbers("100001-100003"), 750, location="Lahore office")
    draw = db.add_draw("2026-10-01", 750, "", "Karachi")
    db.add_winning_numbers(draw, [(*numbers("100002")[0], "1st Prize", 1_500_000)])
    agent.scan(draw)
    agent.approve_all()
    (win,) = db.list_wins()
    assert win["location"] == "Karachi"                    # where the draw / claim happened
    assert win["bond_location"] == "Lahore office"         # where the bond itself is
    db.update_bond(db.list_bonds()[0]["id"], "100001", 750, None, None, None,
                   location="Elsewhere")
    assert db.list_wins()[0]["bond_location"] == "Lahore office"      # a snapshot


# --------------------------------------------------------------- where a draw came from
def test_a_draw_remembers_how_its_numbers_got_here(db):
    manual = db.add_draw("2026-10-01", 750, "Draw 1", "Lahore")
    auto = db.add_draw("2026-10-02", 200, "Draw 107", "Muzaffarabad", source="savings.gov.pk",
                       source_url="https://savings.gov.pk/x.txt", draw_no=107)
    draws = {d["id"]: d for d in db.list_draws()}
    assert draws[manual]["source"] == "Manual"
    assert (draws[auto]["source"], draws[auto]["draw_no"]) == ("savings.gov.pk", 107)
    assert draws[auto]["source_url"].endswith("x.txt")


def test_find_draw_matches_on_date_and_price(db):
    one = db.add_draw("2026-10-01", 750)
    db.add_draw("2026-10-01", 200)
    any_price = db.add_draw("2026-10-01", None)
    assert db.find_draw("2026-10-01", 750)["id"] == one
    assert db.find_draw("2026-10-01", None)["id"] == any_price
    assert db.find_draw("2026-10-02", 750) is None
