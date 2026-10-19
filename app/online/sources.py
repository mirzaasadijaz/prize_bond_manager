"""The web sites results are read from.  Each source can list its draws and read one draw.

    OfficialSource      savings.gov.pk (National Savings): a list page per price, each draw a
                        .txt file (and a .pdf).  Its JSON API is tried first, but the site keeps
                        it closed ("only authenticated users"), so the pages are used.
    PrizeBondNetSource  prizebond.net: no API; plain HTML pages for each price and draw.
"""
from __future__ import annotations

import json

from .http import FetchError, HttpClient
from .model import OFFICIAL, PRIZEBOND_NET, DrawRef, OnlineDraw, Trace
from .parse import (parse_official_list, parse_official_text, parse_prizebond_net_list,
                    parse_prizebond_net_result, pdf_text)


class OfficialSource:
    name = OFFICIAL
    BASE = "https://savings.gov.pk"
    PAGES = {100: "rs-100-prize-bond-draw", 200: "rs-200-prize-bond-draw",
             750: "rs-750-prize-bond-draw", 1500: "rs-1500-prize-bond-draw",
             25000: "premium-prize-bond-rs-25000", 40000: "premium-prize-bond-rs-40000"}

    def supports(self, denomination: int) -> bool:
        return denomination in self.PAGES

    def list_draws(self, client: HttpClient, denomination: int, trace: Trace) -> list[DrawRef]:
        slug = self.PAGES[denomination]
        page_url = f"{self.BASE}/{slug}/"
        # 1. the site's JSON API (WordPress), if it is open
        try:
            data = json.loads(client.text(f"{self.BASE}/wp-json/wp/v2/pages?slug={slug}"
                                          "&_fields=content"))
            refs = parse_official_list(data[0]["content"]["rendered"], page_url, denomination)
            if refs:
                trace.add(self.name, "API", True, f"Rs {denomination}: {len(refs)} draw(s) listed")
                return refs
            trace.add(self.name, "API", False, "answered, but listed no result files")
        except FetchError as exc:
            trace.add(self.name, "API", False, str(exc))
        except (ValueError, KeyError, IndexError, TypeError):
            trace.add(self.name, "API", False, "answered with something unexpected")
        # 2. the public page
        try:
            refs = parse_official_list(client.text(page_url), page_url, denomination)
        except FetchError as exc:
            trace.add(self.name, "list page", False, str(exc))
            raise
        if not refs:
            message = "no result files found on the page (its layout may have changed)"
            trace.add(self.name, "list page", False, message)
            raise FetchError(message)
        trace.add(self.name, "list page", True, f"Rs {denomination}: {len(refs)} draw(s) listed")
        return refs

    def fetch(self, client: HttpClient, ref: DrawRef, trace: Trace) -> OnlineDraw:
        """Read the .txt file; if that fails (or there is none) the PDF."""
        problems: list[str] = []
        for kind, url in [(ref.kind, ref.url), *ref.alternatives]:
            stage = "txt file" if kind == "txt" else "PDF file"
            try:
                text = client.text(url) if kind == "txt" else pdf_text(client.bytes(url))
                draw = parse_official_text(text)
            except FetchError as exc:
                trace.add(self.name, stage, False, f"{url.rsplit('/', 1)[-1]}: {exc}")
                problems.append(str(exc))
                continue
            draw.url = url
            draw.draw_date = ref.draw_date
            if draw.denomination and draw.denomination != ref.denomination:
                draw.warnings.append(f"the file says Rs {draw.denomination:,} but it was listed "
                                     f"under Rs {ref.denomination:,}")
            draw.denomination = ref.denomination
            trace.add(self.name, stage, True, f"{draw.number_count:,} winning numbers read")
            return draw
        raise FetchError("; ".join(dict.fromkeys(problems)) or "no result file to read")


class PrizeBondNetSource:
    name = PRIZEBOND_NET
    BASE = "https://prizebond.net"

    def supports(self, denomination: int) -> bool:
        return denomination in (100, 200, 750, 1500, 7500, 15000, 25000, 40000)

    def list_draws(self, client: HttpClient, denomination: int, trace: Trace) -> list[DrawRef]:
        url = f"{self.BASE}/prizebond-draw-schedule/prizebond-{denomination}-draw-result"
        try:
            refs = parse_prizebond_net_list(client.text(url), denomination, url)
        except FetchError as exc:
            trace.add(self.name, "list page", False, str(exc))
            raise
        if not refs:
            message = "no draws found on the page (its layout may have changed)"
            trace.add(self.name, "list page", False, message)
            raise FetchError(message)
        trace.add(self.name, "list page", True, f"Rs {denomination}: {len(refs)} draw(s) listed")
        return refs

    def fetch(self, client: HttpClient, ref: DrawRef, trace: Trace) -> OnlineDraw:
        try:
            draw = parse_prizebond_net_result(client.text(ref.url))
        except FetchError as exc:
            trace.add(self.name, "result page", False, f"{ref.url.rsplit('/', 1)[-1]}: {exc}")
            raise
        draw.url = ref.url
        draw.draw_date = draw.draw_date or ref.draw_date
        if ref.draw_date and draw.draw_date != ref.draw_date:
            draw.warnings.append(f"the page is dated {draw.draw_date} but the list says "
                                 f"{ref.draw_date}")
        if draw.denomination and draw.denomination != ref.denomination:
            draw.warnings.append(f"the page is for Rs {draw.denomination:,} but it was listed "
                                 f"under Rs {ref.denomination:,}")
        draw.denomination = ref.denomination
        trace.add(self.name, "result page", True, f"{draw.number_count:,} winning numbers read")
        return draw


ALL_SOURCES = (OfficialSource, PrizeBondNetSource)
