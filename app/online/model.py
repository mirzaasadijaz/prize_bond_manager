"""Plain data shared by the online result fetcher."""
from __future__ import annotations

from dataclasses import dataclass, field

OFFICIAL = "savings.gov.pk"
PRIZEBOND_NET = "prizebond.net"

TIER_LABELS = {1: "1st Prize", 2: "2nd Prize", 3: "3rd Prize"}


def tier_label(position: int) -> str:
    """'1st Prize', '2nd Prize', '3rd Prize', '4th Prize' ... (matches the Draw Results form)."""
    if position in TIER_LABELS:
        return TIER_LABELS[position]
    return f"{position}th Prize"


@dataclass
class PrizeGroup:
    """All the winning numbers of one prize tier."""

    label: str
    amount: int | None
    numbers: list[str] = field(default_factory=list)
    declared: int | None = None        # how many numbers the page says this tier has


@dataclass
class DrawRef:
    """A draw that a web site lists (its numbers have not been read yet)."""

    denomination: int
    draw_date: str | None              # ISO yyyy-mm-dd
    draw_no: int | None
    location: str
    url: str
    kind: str                          # 'txt' | 'pdf' | 'html'
    source: str
    alternatives: list[tuple[str, str]] = field(default_factory=list)   # (kind, url) of other files


@dataclass
class Listed:
    """One draw as the sites list it: the same draw may be known to several of them."""

    denomination: int
    draw_date: str | None
    draw_no: int | None
    location: str
    refs: list[DrawRef] = field(default_factory=list)       # best source first

    @property
    def sources(self) -> list[str]:
        return list(dict.fromkeys(r.source for r in self.refs))

    @property
    def label(self) -> str:
        return f"Draw #{self.draw_no}" if self.draw_no else ""


@dataclass
class OnlineDraw:
    """The winning numbers of one draw, read from a web page or file."""

    denomination: int | None
    draw_date: str | None
    draw_no: int | None
    location: str
    source: str
    url: str
    prizes: list[PrizeGroup] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    verified_by: str = ""              # a second site that agrees with these numbers

    @property
    def label(self) -> str:
        return f"Draw #{self.draw_no}" if self.draw_no else ""

    @property
    def number_count(self) -> int:
        return sum(len(p.numbers) for p in self.prizes)

    def looks_complete(self) -> bool:
        """Safe for fully automatic saving: a date, exactly one first prize, nothing odd."""
        first = next((p for p in self.prizes if p.label == "1st Prize"), None)
        return bool(self.draw_date and self.denomination and first and len(first.numbers) == 1
                    and not self.warnings)


@dataclass
class Attempt:
    """One thing the fetcher tried, kept so the user can see what happened."""

    source: str
    stage: str                         # 'API', 'list page', 'txt file', 'PDF file', 'result page'
    ok: bool
    message: str

    def __str__(self) -> str:
        return f"{'OK  ' if self.ok else 'FAIL'}  {self.source} - {self.stage}: {self.message}"


@dataclass
class Trace:
    attempts: list[Attempt] = field(default_factory=list)

    def add(self, source: str, stage: str, ok: bool, message: str) -> None:
        self.attempts.append(Attempt(source, stage, ok, message))

    def text(self) -> str:
        return "\n".join(str(a) for a in self.attempts)

    def last_failure(self) -> str:
        failed = [a for a in self.attempts if not a.ok]
        return failed[-1].message if failed else ""
