"""Readers for the pages and files that publish prize-bond draw results.

Everything here works on text that has already been downloaded (no network), so each reader can
be tested with a saved copy of a real page.

    official .txt / PDF text   "First Prize of Rs. 3,000,000/-", then the numbers
    prizebond.net result page  "1 Prize(s) of Rs.750,000", "5 2nd Prize(s) of Rs.250,000" ...
    list pages                 which draws exist, with their dates and links
"""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin

from .http import FetchError
from .model import (OFFICIAL, PRIZEBOND_NET, DrawRef, OnlineDraw, PrizeGroup, tier_label)

BOND_NUMBER = re.compile(r"(?<![\d,])\d{6}(?![\d,])")        # a standalone 6-digit number
_ORDINAL_WORDS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
                  "fourth": 4, "4th": 4, "fifth": 5, "5th": 5}

# Spelling variants of cities the sites write in different ways.
_CITIES = {"muzzaffarabad": "Muzaffarabad", "muzafarabad": "Muzaffarabad",
           "muzaffarabad": "Muzaffarabad", "sialkoat": "Sialkot", "sialkot": "Sialkot"}


def normalize_city(text: str) -> str:
    text = " ".join((text or "").replace("-", " ").split())
    return _CITIES.get(text.lower(), text.title())


def amount_of(text: str) -> int | None:
    """'18, 500' / '1,250' / '750000' -> int (None if there are no digits)."""
    digits = re.sub(r"\D", "", text or "")
    return int(digits) if digits else None


# --------------------------------------------------------------------- html -> text
class _Lines(HTMLParser):
    """Turn HTML into text lines: every tag boundary starts a new line; scripts are skipped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buffer: list[str] = []
        self._skip = 0

    def _flush(self) -> None:
        text = " ".join("".join(self._buffer).split())
        if text:
            self.lines.append(text)
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        self._flush()

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._buffer.append(data)

    def close(self):
        super().close()
        self._flush()


def html_lines(html: str) -> list[str]:
    parser = _Lines()
    parser.feed(html)
    parser.close()
    return parser.lines


def strip_tags(html: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html or "")).split())


# ------------------------------------------------------------- official text / PDF
_OFFICIAL_TIER = re.compile(
    r"\b(First|Second|Third|Fourth|Fifth|1st|2nd|3rd|4th|5th)\s+Prizes?\b[^\n/]*?"
    r"R[sS]\.?\s*([\d][\d, ]*)", re.IGNORECASE)
_HEADER_PRICE = re.compile(r"R[sS]\.?\s*([\d][\d,]*)")
_HEADER_DRAW = re.compile(r"(\d+)\s*(?:ST|ND|RD|TH)\s+DRAW", re.IGNORECASE)


def parse_official_text(text: str) -> OnlineDraw:
    """Read the text of an official result file (the .txt, or the text taken out of the PDF).

    The date and the place are not in the file - the list page that links to it has the date.
    Raises ``FetchError`` when no prize section is found.
    """
    text = (text or "").replace("\r", "")
    tiers = list(_OFFICIAL_TIER.finditer(text))
    if not tiers:
        raise FetchError("this file does not look like a prize-bond result "
                         "(no 'First Prize' / 'Second Prize' sections)")
    header = text[:tiers[0].start()]
    price = _HEADER_PRICE.search(header)
    draw_no = _HEADER_DRAW.search(header)
    draw = OnlineDraw(denomination=amount_of(price.group(1)) if price else None, draw_date=None,
                      draw_no=int(draw_no.group(1)) if draw_no else None, location="",
                      source=OFFICIAL, url="")
    seen_tiers: set[int] = set()
    for index, match in enumerate(tiers):
        end = tiers[index + 1].start() if index + 1 < len(tiers) else len(text)
        position = _ORDINAL_WORDS[match.group(1).lower()]
        numbers = list(dict.fromkeys(BOND_NUMBER.findall(text[match.end():end])))
        if position in seen_tiers:
            draw.warnings.append(f"{tier_label(position)} appears twice in the file")
        seen_tiers.add(position)
        draw.prizes.append(PrizeGroup(tier_label(position), amount_of(match.group(2)), numbers))
    if not draw.number_count:
        raise FetchError("the file has prize sections but no bond numbers")
    return draw


def pdf_text(data: bytes) -> str:
    """The text of a PDF (needs the optional ``pypdf`` package)."""
    try:
        from io import BytesIO

        from pypdf import PdfReader
    except ImportError as exc:
        raise FetchError("reading a PDF needs the 'pypdf' package (pip install pypdf)") from exc
    try:
        reader = PdfReader(BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # noqa: BLE001 - a damaged or scanned PDF
        raise FetchError(f"the PDF could not be read ({exc})") from exc


# ----------------------------------------------------------------- prizebond.net
_PBN_TITLE = re.compile(
    r"^Draw\s+(\d+)\s+of\s+(\d[\d,]*)\b.*?\bon\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})"
    r"(?:\s+held\s+in\s+(.+?))?\s*\.?$", re.IGNORECASE)
_PBN_PRIZE = re.compile(
    r"^(\d[\d,]*)\s+(?:(\d+)(?:st|nd|rd|th)\s+)?Prize\(s\)\s+of\s+R[sS]\.?\s*([\d,]+)",
    re.IGNORECASE)


def _long_date(day: str, month: str, year: str) -> str | None:
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(f"{day} {month} {year}", fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_prizebond_net_result(html: str) -> OnlineDraw:
    """Read one prizebond.net draw page ("Draw 107 of 200 on 15 September 2026 held in ...")."""
    lines = html_lines(html)
    title = next((m for m in map(_PBN_TITLE.match, lines) if m), None)
    if title is None:
        raise FetchError("the page has no draw title ('Draw 107 of 200 on 15 September ...')")
    draw = OnlineDraw(
        denomination=amount_of(title.group(2)), draw_date=_long_date(*title.group(3, 4, 5)),
        draw_no=int(title.group(1)), location=normalize_city(title.group(6) or ""),
        source=PRIZEBOND_NET, url="")
    group: PrizeGroup | None = None
    for line in lines:
        prize = _PBN_PRIZE.match(line)
        if prize:
            position = int(prize.group(2)) if prize.group(2) else len(draw.prizes) + 1
            group = PrizeGroup(tier_label(position), amount_of(prize.group(3)), [],
                               declared=amount_of(prize.group(1)))
            draw.prizes.append(group)
            continue
        if group is None:
            continue
        tokens = line.split()
        if tokens and all(BOND_NUMBER.fullmatch(t) for t in tokens):
            group.numbers += [t for t in tokens if t not in group.numbers]
        else:
            group = None                                  # text again: the numbers have ended
    if not draw.number_count:
        raise FetchError("the page lists no winning numbers")
    for prize in draw.prizes:
        if prize.declared is not None and prize.declared != len(prize.numbers):
            draw.warnings.append(f"{prize.label}: the page says {prize.declared:,} numbers but "
                                 f"{len(prize.numbers):,} were found")
    return draw


# -------------------------------------------------------------------- list pages
_ANCHOR = re.compile(r"<a\b[^>]*?\bhref\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                     re.IGNORECASE | re.DOTALL)
_DMY = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})")
_DMY_COMPACT = re.compile(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)")


def _iso_dmy(day: str, month: str, year: str) -> str | None:
    try:
        return datetime(int(year), int(month), int(day)).date().isoformat()
    except ValueError:
        return None


def parse_official_list(html: str, base_url: str, denomination: int) -> list[DrawRef]:
    """The draws an official list page links to: one entry per date (newest first).

    A date may link to a .txt and a .pdf; the .txt is preferred (the PDF is kept as a
    fallback in ``alternatives``).
    """
    by_date: dict[str, dict[str, str]] = {}
    for href, inner in _ANCHOR.findall(html or ""):
        url = urljoin(base_url, unescape(href.strip()))
        extension = url.lower().split("?")[0].rsplit(".", 1)[-1]
        if extension not in ("txt", "pdf"):
            continue
        label = strip_tags(inner)
        found = _DMY.search(label)
        when = _iso_dmy(*found.groups()) if found else None
        if when is None:
            compact = _DMY_COMPACT.search(url.rsplit("/", 1)[-1])
            when = _iso_dmy(*compact.groups()) if compact else None
        if when is None:
            continue
        by_date.setdefault(when, {}).setdefault(extension, url)
    refs = []
    for when in sorted(by_date, reverse=True):
        files = by_date[when]
        order = [kind for kind in ("txt", "pdf") if kind in files]
        refs.append(DrawRef(denomination, when, None, "", files[order[0]], order[0], OFFICIAL,
                            [(kind, files[kind]) for kind in order[1:]]))
    return refs


_PBN_LINK = re.compile(r"/results/Draw-(\d+)-of-", re.IGNORECASE)


def parse_prizebond_net_list(html: str, denomination: int, base_url: str = "") -> list[DrawRef]:
    """The draws on a prizebond.net denomination page (rows that have a 'List' link)."""
    refs = []
    for row in re.findall(r"<tr\b.*?</tr>", html or "", re.IGNORECASE | re.DOTALL):
        link = _ANCHOR.search(row)
        if not link or not _PBN_LINK.search(link.group(1)):
            continue
        cells = [strip_tags(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", row,
                                                   re.IGNORECASE | re.DOTALL)]
        draw_no = int(_PBN_LINK.search(link.group(1)).group(1))
        when = None
        for cell in cells:
            found = _DMY.fullmatch(cell)
            if found:
                when = _iso_dmy(*found.groups())
                break
        city = cells[4] if len(cells) > 4 else ""
        refs.append(DrawRef(denomination, when, draw_no, normalize_city(city),
                            urljoin(base_url, unescape(link.group(1))), "html", PRIZEBOND_NET))
    return sorted(refs, key=lambda r: r.draw_date or "", reverse=True)


def read_result_file(path) -> OnlineDraw | None:
    """A result saved on disk - the official list (.txt or .pdf) or a saved prizebond.net page
    (.html) - read as a whole draw; ``None`` when the file is not one of those (then it is just
    a list of numbers for the ordinary importer)."""
    from pathlib import Path

    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in (".txt", ".pdf", ".html", ".htm"):
        return None
    try:
        data = path.read_bytes()
        if suffix == ".pdf":
            return parse_official_text(pdf_text(data))
        text = data.decode("utf-8-sig", errors="replace")
        if suffix in (".html", ".htm"):
            return parse_prizebond_net_result(text)
        return parse_official_text(text)
    except (FetchError, OSError):
        return None
