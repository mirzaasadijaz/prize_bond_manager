"""Reading results from the web.  A fake connection serves saved copies of the real pages, so the
tests never touch the network."""
import json
from datetime import date
from pathlib import Path

import pytest

from app.online import parse
from app.online.fetcher import ResultFetcher, compare_draws
from app.online.http import FetchError, HttpClient, Response
from app.online.model import OFFICIAL, PRIZEBOND_NET, Trace
from app.online.store import auto_check, save_draw
from tests.conftest import numbers

FIX = Path(__file__).parent / "fixtures"
OFFICIAL_LIST = "https://savings.gov.pk/rs-1500-prize-bond-draw/"
OFFICIAL_API = "https://savings.gov.pk/wp-json/wp/v2/pages?slug=rs-1500-prize-bond-draw&_fields=content"
TXT_0515 = "https://savings.gov.pk/wp-content/uploads/2026/05/DRAW-RESULT-OF-RS.1500-DENOMINATIO.txt"
TXT_0216 = ("https://savings.gov.pk/wp-content/uploads/2026/02/"
            "105-DRAW-RESULT-OF-RS.1500-DENOMINATIO.txt")
PDF_0817 = "https://savings.gov.pk/wp-content/uploads/2026/08/1500_17082026.pdf"
PBN_LIST_200 = "https://prizebond.net/prizebond-draw-schedule/prizebond-200-draw-result"
PBN_107 = "https://prizebond.net/results/Draw-107-of-200-on-15-September-2026-held-in-Muzafarabad-482"


def read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class FakeWeb:
    """url -> (status, body).  Unknown addresses are refused with 404."""

    def __init__(self, pages: dict[str, tuple[int, str | bytes]]):
        self.pages = pages
        self.asked: list[str] = []

    def __call__(self, url: str, timeout: float) -> Response:
        self.asked.append(url)
        status, body = self.pages.get(url, (404, b""))
        data = body.encode() if isinstance(body, str) else body
        return Response(status, data, "text/html; charset=utf-8", url)

    def client(self) -> HttpClient:
        return HttpClient(self, retries=0, pause=0)


def web(**extra) -> FakeWeb:
    pages = {
        OFFICIAL_API: (401, '{"code":"rest_cannot_access"}'),     # the real site's answer
        OFFICIAL_LIST: (200, read("savings_rs1500_list.html")),
        TXT_0515: (200, read("official_rs1500_106.txt")),
        TXT_0216: (200, read("official_rs1500_106.txt")),
        PBN_LIST_200: (200, read("prizebond_net_rs200_list.html")),
        PBN_107: (200, read("prizebond_net_rs200_draw107.html")),
    }
    pages.update(extra)
    return FakeWeb(pages)


# ------------------------------------------------------------------ the readers
def test_official_text_file_is_read_with_tiers_amounts_and_draw_number():
    draw = parse.parse_official_text(read("official_rs1500_106.txt"))
    assert (draw.denomination, draw.draw_no) == (1500, 106)
    tiers = {p.label: p for p in draw.prizes}
    assert tiers["1st Prize"].numbers == ["024132"] and tiers["1st Prize"].amount == 3_000_000
    assert tiers["2nd Prize"].numbers == ["026284", "355420", "407321"]
    assert tiers["2nd Prize"].amount == 1_000_000
    third = tiers["3rd Prize"]
    assert third.amount == 18_500                       # "Rs. 18, 500/-" has a stray space
    assert len(third.numbers) == 46 and "XXXXX" not in third.numbers
    assert third.numbers[0] == "000040" and third.numbers[-1] == "969591"


def test_a_file_that_is_not_a_result_is_refused():
    with pytest.raises(FetchError, match="does not look like"):
        parse.parse_official_text("Dear customer, this page is under maintenance.")


def test_prizebond_net_page_is_read_including_date_place_and_counts():
    draw = parse.parse_prizebond_net_result(read("prizebond_net_rs200_draw107.html"))
    assert (draw.denomination, draw.draw_no, draw.draw_date) == (200, 107, "2026-09-15")
    assert draw.location == "Muzaffarabad"
    tiers = {p.label: p for p in draw.prizes}
    assert tiers["1st Prize"].numbers == ["516806"] and tiers["1st Prize"].amount == 750_000
    assert tiers["2nd Prize"].numbers == ["381066", "425087", "796229", "799273", "844138"]
    assert tiers["3rd Prize"].declared == 2394 and tiers["3rd Prize"].amount == 1250
    # the saved copy of the page holds only 48 of the 2,394 third prizes -> the reader notices
    assert len(tiers["3rd Prize"].numbers) == 48
    assert any("2,394" in w for w in draw.warnings)


def test_prizebond_net_numbers_do_not_run_into_page_text_or_prize_amounts():
    page = ("<h3>Draw 5 of 750 on 15 July 2026 held in Lahore.</h3>"
            "<h5>1 Prize(s) of Rs.1,500,000</h5><h2>976106</h2>"
            "<p>Call us on 0300 1234567 or visit 2003-2026</p><h5>123456</h5>")
    draw = parse.parse_prizebond_net_result(page)
    assert draw.prizes[0].numbers == ["976106"]         # 123456 comes after text: not a prize
    assert draw.prizes[0].amount == 1_500_000


def test_list_pages_give_dates_links_and_prefer_the_txt_file():
    official = parse.parse_official_list(read("savings_rs1500_list.html"), OFFICIAL_LIST, 1500)
    assert [r.draw_date for r in official] == ["2026-08-17", "2026-05-15", "2026-02-16",
                                               "2025-11-17", "2025-08-15"]
    by_date = {r.draw_date: r for r in official}
    assert by_date["2026-02-16"].kind == "txt" and by_date["2026-02-16"].alternatives[0][0] == "pdf"
    assert by_date["2026-08-17"].kind == "pdf"          # only a PDF exists for the newest draw
    assert by_date["2026-08-17"].url == PDF_0817        # a relative link was made absolute
    assert all(not r.url.endswith("about/") for r in official)

    pbn = parse.parse_prizebond_net_list(read("prizebond_net_rs200_list.html"), 200, PBN_LIST_200)
    assert [(r.draw_no, r.draw_date, r.location) for r in pbn] == [
        (107, "2026-09-15", "Muzaffarabad"), (106, "2026-06-15", "Karachi"),
        (105, "2026-03-16", "Faisalabad")]              # the "Upcoming Draw" row has no link


# ------------------------------------------------------------------ the chain
def test_official_api_is_tried_first_and_when_closed_the_pages_are_used():
    trace = Trace()
    fetcher = ResultFetcher(web().client(), mode="official")
    listed = fetcher.list_draws([1500], trace)
    assert [e.draw_date for e in listed][:2] == ["2026-08-17", "2026-05-15"]
    stages = [(a.stage, a.ok) for a in trace.attempts]
    assert stages == [("API", False), ("list page", True)]
    assert "401" in trace.attempts[0].message and "signed-in" in trace.attempts[0].message


def test_an_open_api_is_used_without_touching_the_page():
    api = json.dumps([{"content": {"rendered": read("savings_rs1500_list.html")}}])
    fake = web(**{OFFICIAL_API: (200, api)})
    trace = Trace()
    listed = ResultFetcher(fake.client(), mode="official").list_draws([1500], trace)
    assert len(listed) == 5 and OFFICIAL_LIST not in fake.asked
    assert trace.attempts[0].stage == "API" and trace.attempts[0].ok


def test_a_draw_is_read_from_the_txt_file_with_the_date_from_the_list():
    fetcher = ResultFetcher(web().client(), mode="official")
    listed = next(e for e in fetcher.list_draws([1500]) if e.draw_date == "2026-05-15")
    trace = Trace()
    draw = fetcher.fetch(listed, trace)
    assert (draw.source, draw.draw_date, draw.denomination, draw.draw_no) == (
        OFFICIAL, "2026-05-15", 1500, 106)
    assert draw.number_count == 50 and draw.url == TXT_0515
    assert [a.stage for a in trace.attempts] == ["txt file"]


def test_when_the_txt_is_missing_the_pdf_is_used():
    pytest.importorskip("reportlab")
    pytest.importorskip("pypdf")
    from io import BytesIO

    from reportlab.pdfgen import canvas
    buf = BytesIO()
    pdf = canvas.Canvas(buf)
    y = 800
    for line in ["DRAW RESULT OF RS.1500/- DENOMINATION NATIONAL PRIZE BONDS - 105TH DRAW",
                 "First Prize of Rs. 3,000,000/-", "024132",
                 "Second Prize of Rs. 1,000,000/- (each)", "026284 355420 407321",
                 "Third Prize of Rs. 18, 500/-", "000040 028615 052200 091819"]:
        pdf.drawString(40, y, line)
        y -= 20
    pdf.save()
    fake = web(**{TXT_0216: (404, b""), "https://savings.gov.pk/wp-content/uploads/2026/02/Rs-1500-105-Draw.pdf":
                  (200, buf.getvalue())})
    fetcher = ResultFetcher(fake.client(), mode="official")
    listed = next(e for e in fetcher.list_draws([1500]) if e.draw_date == "2026-02-16")
    trace = Trace()
    draw = fetcher.fetch(listed, trace)
    assert draw.draw_no == 105 and draw.number_count == 8
    assert [(a.stage, a.ok) for a in trace.attempts] == [("txt file", False), ("PDF file", True)]


def test_if_the_official_file_fails_prizebond_net_is_used_for_the_same_draw():
    fake = web(**{TXT_0515: (404, b"")})
    # the official site has a Rs 200 page in real life; here only prizebond.net knows Rs 200
    fetcher = ResultFetcher(fake.client(), mode="auto")
    listed = fetcher.list_draws([200])
    assert [e.refs[0].source for e in listed] == [PRIZEBOND_NET] * 3
    trace = Trace()
    draw = fetcher.fetch(listed[0], trace)
    assert draw.source == PRIZEBOND_NET and draw.location == "Muzaffarabad"
    assert draw.prizes[0].numbers == ["516806"]


def test_both_sites_listing_one_draw_become_one_entry_and_the_place_is_filled_in():
    official_200 = "https://savings.gov.pk/rs-200-prize-bond-draw/"
    listing = ('<a href="/u/200_107.txt">16-09-2026</a>')        # a day later than prizebond.net
    txt = read("official_rs1500_106.txt").replace("RS.1500", "RS.200")
    fake = web(**{official_200: (200, listing), "https://savings.gov.pk/u/200_107.txt": (200, txt),
                  "https://savings.gov.pk/wp-json/wp/v2/pages?slug=rs-200-prize-bond-draw&_fields=content": (401, "")})
    fetcher = ResultFetcher(fake.client())
    entries = fetcher.list_draws([200])
    sept = [e for e in entries if e.draw_date and e.draw_date.startswith("2026-09")]
    assert len(sept) == 1                                         # same draw, dates a day apart
    assert sept[0].sources == [OFFICIAL, PRIZEBOND_NET] and sept[0].location == "Muzaffarabad"
    draw = fetcher.fetch(sept[0])
    assert draw.source == OFFICIAL and draw.location == "Muzaffarabad" and draw.draw_no == 106


def test_cross_checking_two_sites_marks_agreement_and_reports_differences():
    official_200 = "https://savings.gov.pk/rs-200-prize-bond-draw/"
    same = parse.parse_prizebond_net_result(read("prizebond_net_rs200_draw107.html"))
    body = ("DRAW RESULT OF RS.200/- DENOMINATION NATIONAL PRIZE BONDS - 107TH DRAW\n"
            "First Prize of Rs. 750,000/-\n516806\nSecond Prize of Rs. 250,000/- (each)\n"
            "381066 425087 796229 799273 844138\nThird Prize of Rs. 1,250/-\n"
            + " ".join(same.prizes[2].numbers))
    pages = {official_200: (200, '<a href="/u/200.txt">15-09-2026</a>'),
             "https://savings.gov.pk/u/200.txt": (200, body)}
    fetcher = ResultFetcher(web(**pages).client())
    listed = next(e for e in fetcher.list_draws([200]) if e.draw_date == "2026-09-15")
    draw = fetcher.fetch(listed, verify=True)
    assert draw.verified_by == PRIZEBOND_NET and not [w for w in draw.warnings if "disagree" in w]

    pages["https://savings.gov.pk/u/200.txt"] = (200, body.replace("516806", "516807"))
    fetcher = ResultFetcher(web(**pages).client())
    listed = next(e for e in fetcher.list_draws([200]) if e.draw_date == "2026-09-15")
    draw = fetcher.fetch(listed, verify=True)
    assert not draw.verified_by and any("disagree" in w and "1st Prize" in w for w in draw.warnings)
    assert compare_draws(draw, parse.parse_prizebond_net_result(read("prizebond_net_rs200_draw107.html")))


def test_when_nothing_works_the_error_says_what_was_tried():
    fetcher = ResultFetcher(FakeWeb({}).client())
    trace = Trace()
    assert fetcher.list_draws([1500], trace) == []
    assert not any(a.ok for a in trace.attempts)
    assert {a.source for a in trace.attempts} == {OFFICIAL, PRIZEBOND_NET}
    listed = ResultFetcher(web().client(), "official").list_draws([1500])[1]
    broken = ResultFetcher(web(**{TXT_0515: (404, b"")}).client(), "official")
    with pytest.raises(FetchError, match="404"):
        broken.fetch(listed)


def test_a_pasted_link_is_read_by_its_type():
    fetcher = ResultFetcher(web().client())
    draw = fetcher.fetch_link(TXT_0515)
    assert draw.denomination == 1500 and draw.draw_date is None and draw.source == "savings.gov.pk"
    draw = fetcher.fetch_link(PBN_107)
    assert draw.draw_date == "2026-09-15" and draw.source == "prizebond.net"
    with pytest.raises(FetchError, match="https"):
        fetcher.fetch_link("savings.gov.pk/x.txt")


def test_the_client_does_not_hammer_a_site_that_said_no():
    fake = FakeWeb({"https://x.test/a": (403, b"")})
    client = HttpClient(fake, retries=3, pause=0)
    with pytest.raises(FetchError, match="403") as caught:
        client.get("https://x.test/a")
    assert fake.asked == ["https://x.test/a"] and caught.value.status == 403   # asked once
    flaky = FakeWeb({"https://x.test/b": (503, b"")})
    with pytest.raises(FetchError):
        HttpClient(flaky, retries=2, pause=0).get("https://x.test/b")
    assert len(flaky.asked) == 3                                              # 5xx: retried


# ------------------------------------------------------------------ saving
def test_a_fetched_draw_is_saved_with_its_source_tiers_and_amounts(db):
    draw = ResultFetcher(web().client(), "official").fetch_link(TXT_0515)
    draw.draw_date = "2026-05-15"
    outcome = save_draw(db, draw)
    assert outcome.created and outcome.added == 50
    (saved,) = db.list_draws()
    assert (saved["source"], saved["draw_no"], saved["draw_date"]) == ("savings.gov.pk", 106,
                                                                      "2026-05-15")
    first = [n for n in db.draw_numbers(outcome.draw_id) if n["prize_label"] == "1st Prize"]
    assert [(n["number"], n["prize_amount"]) for n in first] == [("024132", 3_000_000)]


def test_saving_the_same_draw_twice_tops_it_up_instead_of_duplicating_it(db):
    draw = ResultFetcher(web().client(), "official").fetch_link(TXT_0515)
    draw.draw_date = "2026-05-15"
    first = save_draw(db, draw)
    again = save_draw(db, draw)
    assert not again.created and again.added == 0 and again.skipped == 50
    assert again.draw_id == first.draw_id and len(db.list_draws()) == 1
    with pytest.raises(ValueError, match="date"):
        draw.draw_date = None
        save_draw(db, draw)


def test_a_fetched_draw_flows_into_the_win_checking_agent(db, agent):
    db.add_copy("Copy 1", numbers("024130-024135"), 1500, "2025-01-01")
    draw = ResultFetcher(web().client(), "official").fetch_link(TXT_0515)
    draw.draw_date = "2026-05-15"
    outcome = save_draw(db, draw)
    scan = agent.scan(outcome.draw_id, "draw")
    assert scan.new_pending == 1
    (pending,) = db.list_pending()
    assert pending["bond_number"] == "024132" and pending["prize_amount"] == 3_000_000


# ------------------------------------------------------------------ automatic check
def test_auto_check_saves_only_new_complete_draws_for_prices_you_hold(db):
    db.add_copy("Copy 1", numbers("024130-024135"), 1500, "2026-01-01")
    fetcher = ResultFetcher(web().client(), "official")
    result = auto_check(db, fetcher, today=date(2026, 10, 15))
    # draws 2026-02-16 and 2026-05-15 can be read; 2026-08-17 is a PDF only (not served here)
    saved_dates = sorted(d.draw_date for _, d, _ in result.saved)
    assert saved_dates == ["2026-02-16", "2026-05-15"]
    assert [e.draw_date for e, _ in result.needs_review] == ["2026-08-17"]
    assert {d["source"] for d in db.list_draws()} == {"savings.gov.pk"}
    again = auto_check(db, fetcher, today=date(2026, 10, 15))
    assert not again.saved                                   # nothing is fetched twice


def test_auto_check_ignores_draws_before_you_owned_any_bond_and_dates_in_the_future(db):
    db.add_copy("Copy 1", numbers("024130-024135"), 1500, "2026-04-01")
    result = auto_check(db, ResultFetcher(web().client(), "official"), today=date(2026, 5, 1))
    assert [d.draw_date for _, d, _ in result.saved] == []   # 02-16 is before the purchase
    result = auto_check(db, ResultFetcher(web().client(), "official"), today=date(2026, 6, 1))
    assert [d.draw_date for _, d, _ in result.saved] == ["2026-05-15"]


def test_auto_check_never_saves_a_result_that_looks_wrong(db):
    db.add_copy("Copy 1", numbers("100001-100005"), 200, "2026-01-01")
    fetcher = ResultFetcher(web().client(), "prizebond.net")
    result = auto_check(db, fetcher, today=date(2026, 10, 15))
    # the saved page has 48 of 2,394 third prizes: the count check fails, so it needs review
    assert [(e.draw_no, "2,394" in why) for e, why in result.needs_review][:1] == [(107, True)]
    assert all(d.draw_date != "2026-09-15" for _, d, _ in result.saved)


def test_auto_check_with_no_bonds_or_no_connection_says_so(db):
    assert "No bonds" in auto_check(db, ResultFetcher(web().client())).summary()
    db.add_loose_bonds(numbers("100001"), 1500)
    result = auto_check(db, ResultFetcher(FakeWeb({}).client()))
    assert "could not be reached" in result.summary()
