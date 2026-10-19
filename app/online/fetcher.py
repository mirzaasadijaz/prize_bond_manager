"""The fetcher: look up draws on the web and read their winning numbers.

Order of attempts (``mode='auto'``), per price:
    1. the official site's JSON API              (closed at the moment - tried, then skipped)
    2. the official list page  ->  the .txt file  ->  the .pdf file
    3. prizebond.net: list page -> result page
Whatever fails is noted in a ``Trace`` that the screen can show.  Nothing is guessed: if no source
can give a draw, the fetcher says so and you can type the numbers in by hand.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import urlparse

from .http import FetchError, HttpClient
from .model import DrawRef, Listed, OnlineDraw, Trace
from .parse import parse_official_text, parse_prizebond_net_result, pdf_text
from .sources import OfficialSource, PrizeBondNetSource

MODES = {
    "auto": "Official site first, then prizebond.net",
    "official": "Official site only (savings.gov.pk)",
    "prizebond.net": "prizebond.net only",
}


def compare_draws(a: OnlineDraw, b: OnlineDraw) -> list[str]:
    """Differences between two readings of the same draw (only prize tiers both have)."""
    problems = []
    tiers_b = {p.label: p for p in b.prizes}
    for tier in a.prizes:
        other = tiers_b.get(tier.label)
        if other is None:
            continue
        mine, theirs = set(tier.numbers), set(other.numbers)
        if mine != theirs:
            problems.append(f"{tier.label}: {a.source} has {len(mine):,} numbers, {b.source} has "
                            f"{len(theirs):,} ({len(mine ^ theirs):,} differ)")
    return problems


class ResultFetcher:
    def __init__(self, client: HttpClient | None = None, mode: str = "auto"):
        if mode not in MODES:
            raise ValueError(f"Unknown source mode '{mode}'.")
        self.client = client or HttpClient()
        self.mode = mode
        official, other = OfficialSource(), PrizeBondNetSource()
        self.sources = {"auto": [official, other], "official": [official],
                        "prizebond.net": [other]}[mode]
        self._by_name = {s.name: s for s in (official, other)}

    # ------------------------------------------------------------------ listing
    def list_draws(self, denominations, trace: Trace | None = None) -> list[Listed]:
        """Every draw the sources list for these prices, newest first, one entry per draw."""
        trace = trace if trace is not None else Trace()
        found: dict[tuple, Listed] = {}
        for denomination in sorted(set(denominations)):
            supported = [s for s in self.sources if s.supports(denomination)]
            if not supported:
                trace.add("-", "list page", False, f"no source knows Rs {denomination} bonds")
            for source in supported:
                try:
                    refs = source.list_draws(self.client, denomination, trace)
                except FetchError:
                    continue                                  # already in the trace
                for ref in refs:
                    entry = self._same_draw(found, denomination, ref)
                    if entry is None:
                        entry = found[(denomination, ref.draw_date or ref.url, ref.source)] = \
                            Listed(denomination, ref.draw_date, ref.draw_no, ref.location)
                    entry.refs.append(ref)
                    entry.draw_no = entry.draw_no or ref.draw_no
                    entry.location = entry.location or ref.location
        for entry in found.values():
            entry.refs.sort(key=lambda r: [s.name for s in self.sources].index(r.source))
        return sorted(found.values(), key=lambda e: (e.draw_date or "", e.denomination),
                      reverse=True)

    @staticmethod
    def _same_draw(found: dict, denomination: int, ref: DrawRef) -> Listed | None:
        """The entry ``ref`` belongs to: same price and the same date - or, when two sites
        disagree by a day or two (a holiday moved the draw), a date within 3 days."""
        for entry in found.values():
            if entry.denomination != denomination or any(r.source == ref.source
                                                         for r in entry.refs):
                continue
            if entry.draw_date == ref.draw_date:
                return entry
            if entry.draw_date and ref.draw_date:
                gap = abs((date.fromisoformat(entry.draw_date)
                           - date.fromisoformat(ref.draw_date)).days)
                if gap <= 3:
                    return entry
        return None

    # ------------------------------------------------------------------ reading
    def fetch(self, listed: Listed, trace: Trace | None = None, verify: bool = False) -> OnlineDraw:
        """Read one listed draw from the best source that works.

        With ``verify`` the draw is read from a second source as well; ``verified_by`` is set
        when both agree, and a warning lists the differences when they do not.
        """
        trace = trace if trace is not None else Trace()
        readings: list[OnlineDraw] = []
        for ref in listed.refs:
            try:
                readings.append(self._by_name[ref.source].fetch(self.client, ref, trace))
            except FetchError:
                continue
            if not verify:
                break
        if not readings:
            raise FetchError(trace.last_failure() or "none of the sources could give this draw")
        draw = readings[0]
        draw.draw_date = draw.draw_date or listed.draw_date
        draw.draw_no = draw.draw_no or listed.draw_no
        draw.location = draw.location or listed.location
        if len(readings) > 1:
            problems = compare_draws(draw, readings[1])
            if problems:
                draw.warnings += [f"the two sites disagree - {p}" for p in problems]
            else:
                draw.verified_by = readings[1].source
        elif verify:
            draw.warnings.append("only one site could be read, so the numbers could not be "
                                 "cross-checked")
        return draw

    def fetch_link(self, url: str, trace: Trace | None = None) -> OnlineDraw:
        """Read a result straight from a link: an official .txt / .pdf or a prizebond.net page."""
        trace = trace if trace is not None else Trace()
        url = url.strip()
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if not url.lower().startswith(("http://", "https://")):
            raise FetchError("Paste a web address that starts with https://")
        lower = url.lower().split("?")[0]
        try:
            if lower.endswith(".pdf"):
                draw = parse_official_text(pdf_text(self.client.bytes(url)))
            elif lower.endswith(".txt"):
                draw = parse_official_text(self.client.text(url))
            else:
                text = self.client.text(url)
                draw = (parse_prizebond_net_result(text) if "<" in text[:2000]
                        else parse_official_text(text))
        except FetchError as exc:
            trace.add(host or "link", "link", False, str(exc))
            raise
        draw.source, draw.url = host or "link", url
        trace.add(draw.source, "link", True, f"{draw.number_count:,} winning numbers read")
        return draw


def listed_from_ref(ref: DrawRef) -> Listed:
    return Listed(ref.denomination, ref.draw_date, ref.draw_no, ref.location, [ref])
