"""The bulk checker and the POST API: thousands of bonds in one request, answered in milliseconds."""
import random
import time

import pytest

from app.api.checker import WinningIndex, check_bonds, held_bonds, open_readonly
from app.db import Database
from tests.conftest import numbers


def draw_with(db, date, winners, price=750, location="Lahore", label="Draw"):
    draw_id = db.add_draw(date, price, label, location)
    db.add_winning_numbers(draw_id, [(*numbers(n)[0], tier, amount) for n, tier, amount in winners])
    return draw_id


@pytest.fixture
def index(db):
    draw_with(db, "2026-10-01", [("100056", "1st Prize", 1_500_000), ("777777", "2nd Prize", 500_000)])
    draw_with(db, "2026-07-01", [("100056", "3rd Prize", 9_300)], label="Earlier")
    draw_with(db, "2026-10-02", [("555555", "1st Prize", 1_000)], price=None, label="Any price")
    return WinningIndex.from_connection(db.conn)


# ------------------------------------------------------------------ the checker
def test_a_bond_that_won_is_found_with_its_draw_prize_and_place(index):
    summary = check_bonds(index, [("100056", 750, None), ("100057", 750, None)])
    assert (summary.checked, summary.winners) == (2, 1)
    assert sorted(h.row.prize_label for h in summary.hits) == ["1st Prize", "3rd Prize"]
    first = next(h for h in summary.hits if h.row.prize_label == "1st Prize")
    assert (first.row.draw_date, first.row.location, first.row.prize_amount) == (
        "2026-10-01", "Lahore", 1_500_000)


def test_leading_zeros_do_not_matter_and_the_price_must_agree(index):
    assert check_bonds(index, [("100056", 750, None)]).winners == 1
    assert check_bonds(index, [(100056, 750, None)]).winners == 1             # an int works too
    assert check_bonds(index, [("0000100056", 750, None)]).winners == 1
    assert check_bonds(index, [("100056", 1500, None)]).winners == 0          # another price
    assert check_bonds(index, [("100056", None, None)]).winners == 1          # no price: any draw
    assert check_bonds(index, [("100056", None, None)], default_denomination=1500).winners == 0


def test_a_draw_for_every_price_matches_every_bond_with_that_number(index):
    assert check_bonds(index, [("555555", 750, None)]).winners == 1
    assert check_bonds(index, [("555555", 200, None)]).winners == 1


def test_unreadable_numbers_are_reported_and_the_rest_is_still_checked(index):
    summary = check_bonds(index, [("100056", 750, None), ("12x456", 750, None), ("", 750, None),
                                  (None, 750, None), ("777777", 750, "Copy 2 #21")])
    assert summary.checked == 2 and summary.winners == 2
    assert [i for i, _, _ in summary.invalid] == [1, 2, 3]
    assert next(h for h in summary.hits if h.number == "777777").ref == "Copy 2 #21"


def test_ten_thousand_bonds_take_milliseconds():
    rng = random.Random(1)
    db = Database(":memory:")
    for d in range(10):                                          # 10 draws x 600 numbers
        db.add_draw(f"2026-{d + 1:02d}-15", 750)
    draw_ids = [r["id"] for r in db.list_draws()]
    seen = set()
    for draw_id in draw_ids:
        items = []
        while len(items) < 600:
            n = rng.randrange(1, 1_000_000)
            if n not in seen:
                seen.add(n)
                items.append((str(n).zfill(6), n, "3rd Prize", 9300))
        db.add_winning_numbers(draw_id, items)
    index = WinningIndex.from_connection(db.conn)
    wins = rng.sample(sorted(seen), 25)
    bonds = [(str(n).zfill(6), 750, None) for n in wins]
    bonds += [(str(rng.randrange(1, 1_000_000)).zfill(6), 750, None) for _ in range(9_975)]
    started = time.perf_counter()
    summary = check_bonds(index, bonds)
    total_ms = (time.perf_counter() - started) * 1000
    assert summary.checked == 10_000 and summary.winners >= 25
    print(f"\n10,000 bonds against {index.count:,} winning numbers: {summary.elapsed_ms:.1f} ms")
    assert total_ms < 500                                        # generous: it takes a few ms
    db.close()


# ------------------------------------------------------------------ the HTTP API
fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from app.api.server import create_app, run  # noqa: E402


@pytest.fixture
def datafile(tmp_path):
    path = tmp_path / "bonds.db"
    db = Database(path)
    db.add_copy("Copy 1", numbers("100001-100100"), 750, "2025-01-10")
    db.add_copy("Copy 2", numbers("555001-555020, 777777"), 750, "2025-02-01")
    draw_with(db, "2026-10-01", [("100056", "1st Prize", 1_500_000), ("777777", "2nd Prize", 500_000)])
    yield path, db
    db.close()


@pytest.fixture
def client(datafile):
    return TestClient(create_app(datafile[0]))


def test_post_check_accepts_bare_numbers_objects_and_a_default_price(client):
    reply = client.post("/check", json={"denomination": 750, "bonds": [
        "100056", 777777, {"number": "100002", "ref": "Copy 1 #2"},
        {"number": "100056", "denomination": 1500}]})
    assert reply.status_code == 200
    body = reply.json()
    assert (body["checked"], body["winners"], body["hits"]) == (4, 2, 2)
    wins = {w["number"]: w for w in body["wins"]}
    assert wins["100056"]["prize_amount"] == 1_500_000 and wins["100056"]["location"] == "Lahore"
    assert wins["777777"]["prize_label"] == "2nd Prize"
    assert body["draws_searched"] == 1 and body["winning_numbers_searched"] == 2
    assert body["elapsed_ms"] >= 0


def test_ten_thousand_bonds_in_one_post_request(client):
    bonds = [{"number": str(200_000 + i).zfill(6), "ref": f"#{i}"} for i in range(9_998)]
    bonds += ["100056", "777777"]
    started = time.perf_counter()
    reply = client.post("/check", json={"denomination": 750, "bonds": bonds})
    wall_ms = (time.perf_counter() - started) * 1000
    body = reply.json()
    assert reply.status_code == 200 and body["checked"] == 10_000 and body["winners"] == 2
    print(f"\nPOST of 10,000 bonds: matching {body['elapsed_ms']:.1f} ms, "
          f"whole request {wall_ms:.0f} ms")
    assert wall_ms < 3000


def test_the_body_is_validated(client):
    assert client.post("/check", json={"bonds": []}).status_code == 422
    assert client.post("/check", json={}).status_code == 422
    assert client.post("/check", json={"bonds": [{"number": "1", "denomination": -5}]}
                       ).status_code == 422
    assert client.post("/check", json={"bonds": ["1"] * 100_001}).status_code == 422


def test_unreadable_numbers_come_back_in_a_list_not_as_an_error(client):
    body = client.post("/check", json={"denomination": 750,
                                       "bonds": ["100056", "abc", "12 34"]}).json()
    assert body["checked"] == 1 and body["winners"] == 1
    assert [(i["index"], i["number"]) for i in body["invalid"]] == [(1, "abc"), (2, "12 34")]


def test_the_check_can_be_limited_to_some_draws_or_dates(client, datafile):
    _, db = datafile
    older = draw_with(db, "2026-01-01", [("100056", "3rd Prize", 9_300)], label="Old")
    both = client.post("/check", json={"denomination": 750, "bonds": ["100056"]}).json()
    assert both["hits"] == 2                                  # new data is seen without a restart
    only_old = client.post("/check", json={"denomination": 750, "bonds": ["100056"],
                                           "draw_ids": [older]}).json()
    assert [w["draw_label"] for w in only_old["wins"]] == ["Old"]
    recent = client.post("/check", json={"denomination": 750, "bonds": ["100056"],
                                         "since": "2026-06-01"}).json()
    assert [w["prize_label"] for w in recent["wins"]] == ["1st Prize"]


def test_my_bonds_checks_the_whole_data_file_and_respects_sales(client, datafile):
    _, db = datafile
    body = client.post("/check/my-bonds").json()
    assert body["checked"] == 121 and body["winners"] == 2
    assert {w["ref"] for w in body["wins"]} == {"Copy 1 #56", "Copy 2 #21"}
    seven = next(b for b in db.list_bonds() if b["number"] == "777777")
    db.record_sale([seven["id"]], "2026-09-01")               # sold before the draw
    again = client.post("/check/my-bonds").json()
    assert [w["number"] for w in again["wins"]] == ["100056"]
    db.undo_sale(db.get_bond(seven["id"])["sale_id"])
    db.record_sale([seven["id"]], "2026-11-01")               # sold after the draw: still yours
    later = client.post("/check/my-bonds").json()
    assert sorted(w["number"] for w in later["wins"]) == ["100056", "777777"]


def test_draws_and_health_are_listed(client):
    assert client.get("/health").json() == {"status": "ok", "draws": 1, "winning_numbers": 2}
    (draw,) = client.get("/draws").json()
    assert (draw["draw_date"], draw["winning_numbers"], draw["source"]) == ("2026-10-01", 2,
                                                                          "Manual")


def test_a_token_can_protect_the_api(datafile):
    client = TestClient(create_app(datafile[0], token="s3cret"))
    body = {"bonds": ["100056"], "denomination": 750}
    assert client.post("/check", json=body).status_code == 401
    assert client.post("/check", json=body, headers={"Authorization": "Bearer nope"}
                       ).status_code == 401
    assert client.post("/check", json=body, headers={"Authorization": "Bearer s3cret"}
                       ).status_code == 200
    assert client.get("/health").status_code == 200           # only says it is running


def test_the_server_only_reads_the_file(datafile, client):
    path, _ = datafile
    before = path.read_bytes()
    client.post("/check", json={"bonds": ["100056"], "denomination": 750})
    client.post("/check/my-bonds")
    assert path.read_bytes() == before
    conn = open_readonly(path)
    with pytest.raises(Exception, match="readonly"):
        conn.execute("DELETE FROM bonds")
    conn.close()
    assert held_bonds(open_readonly(path))[0][0] == "100001"


def test_the_server_refuses_to_start_in_the_open_without_a_token(datafile):
    with pytest.raises(SystemExit, match="--token"):
        run(datafile[0], host="0.0.0.0")
    with pytest.raises(FileNotFoundError):
        open_readonly(datafile[0].with_name("missing.db"))
