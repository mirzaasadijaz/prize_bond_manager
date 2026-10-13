"""Bond-number normalisation and pattern parsing.

A *pattern* is the text a user types (or a file contains) to describe bonds:

    123456                      a single bond
    100001-100100               a range (also "100001 to 100100" or "100001..100100")
    100001-100100:2             every 2nd number in the range
    100001-100050, 250010, ...  any mix, separated by commas, spaces or new lines

The order of the numbers in the pattern is kept: it is the physical order of
the bonds inside a copy (book), which is what the "position" in a win report
refers to.  Copies therefore never have to share a range or a sequence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import BOND_DIGITS, MAX_DIGITS, MAX_RANGE_SIZE


class NumberError(ValueError):
    """Raised when text cannot be read as a bond number or range."""


_ASCII_DIGITS = re.compile(r"[0-9]+")
_EXCEL_FLOAT = re.compile(r"^([0-9]+)\.0+$")          # "123456.0" from spreadsheets
_RANGE = re.compile(r"^([0-9]+)-([0-9]+)(?::([0-9]+))?$")
_TOKEN_SPLIT = re.compile(r"[,;\s]+")
_WORD_RANGE = re.compile(r"\s*(?:\.\.|\bto\b)\s*", re.IGNORECASE)
_SPACED_DASH = re.compile(r"\s*-\s*")


def format_number(key: int, width: int = BOND_DIGITS) -> str:
    """Zero-padded display text for a numeric key."""
    return str(key).zfill(width)


def normalize_number(raw, digits: int = BOND_DIGITS) -> tuple[str, int]:
    """Return ``(display_text, numeric_key)`` for one bond number.

    Accepts strings, ints and whole floats (spreadsheets often hand back
    ``123456.0``).  Display text is zero-padded to ``digits``; the key is the
    integer used for matching, so padding never affects a comparison.
    """
    if raw is None or isinstance(raw, bool):
        raise NumberError("empty value")
    if isinstance(raw, float):
        if raw != raw or raw in (float("inf"), float("-inf")) or not raw.is_integer():
            raise NumberError(f"{raw!r} is not a whole number")
        raw = int(raw)
    text = str(raw).strip()
    match = _EXCEL_FLOAT.match(text)
    if match:
        text = match.group(1)
    if not text:
        raise NumberError("empty value")
    if not _ASCII_DIGITS.fullmatch(text):
        raise NumberError(f"'{text}' is not a valid bond number (digits only)")
    if len(text.lstrip("0")) > MAX_DIGITS:
        raise NumberError(f"'{text}' has too many digits")
    return text.zfill(digits), int(text)


def expand_range(start_text: str, end_text: str, step_text: str | None = None,
                 digits: int = BOND_DIGITS) -> list[tuple[str, int]]:
    """Expand ``start-end[:step]`` into ordered ``(display, key)`` pairs.

    A descending range (start > end) is allowed and yields descending numbers.
    """
    start, end = int(start_text), int(end_text)
    step = int(step_text) if step_text else 1
    if step < 1:
        raise NumberError("a range step must be at least 1")
    if len(str(max(start, end))) > MAX_DIGITS:
        raise NumberError(f"range {start_text}-{end_text} has too many digits")
    count = abs(end - start) // step + 1
    if count > MAX_RANGE_SIZE:
        raise NumberError(f"range {start_text}-{end_text} is too large "
                          f"({count:,} bonds; the limit is {MAX_RANGE_SIZE:,})")
    width = max(digits, len(start_text))
    if start <= end:
        keys = range(start, end + 1, step)
    else:
        keys = range(start, end - 1, -step)
    return [(format_number(k, width), k) for k in keys]


@dataclass
class PatternResult:
    """Parsed numbers (in order) plus anything that could not be used."""

    numbers: list[tuple[str, int]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.numbers)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.duplicates

    @property
    def first(self) -> str:
        return self.numbers[0][0] if self.numbers else ""

    @property
    def last(self) -> str:
        return self.numbers[-1][0] if self.numbers else ""

    def problems(self, limit: int = 3) -> str:
        """Short human-readable description of what is wrong."""
        msgs = list(self.errors)
        if self.duplicates:
            shown = ", ".join(self.duplicates[:limit])
            more = "..." if len(self.duplicates) > limit else ""
            msgs.append(f"duplicate number(s) in this list: {shown}{more}")
        if len(msgs) > limit:
            msgs = msgs[:limit] + [f"(+{len(msgs) - limit} more)"]
        return "; ".join(msgs)


def _tidy(text: str) -> str:
    """Normalise dashes / 'to' / '..' so that ranges survive whitespace splitting."""
    text = text.replace("–", "-").replace("—", "-")
    text = _WORD_RANGE.sub("-", text)
    return _SPACED_DASH.sub("-", text)


def parse_pattern(text, digits: int = BOND_DIGITS, lenient: bool = False,
                  min_free_digits: int = 5) -> PatternResult:
    """Parse a pattern into an ordered list of unique bond numbers.

    ``lenient`` is meant for free text (Word paragraphs): words and short
    numbers such as page numbers are ignored instead of being reported.
    Repeated numbers are dropped and listed in ``PatternResult.duplicates``.
    """
    result = PatternResult()
    if text is None:
        return result
    seen: set[int] = set()
    for token in _TOKEN_SPLIT.split(_tidy(str(text))):
        token = token.strip().rstrip(".")
        if not token:
            continue
        range_match = _RANGE.match(token)
        if lenient:
            first_part = range_match.group(1) if range_match else token
            if not _ASCII_DIGITS.fullmatch(first_part) or len(first_part) < min_free_digits:
                continue
        try:
            if range_match:
                items = expand_range(*range_match.groups(), digits=digits)
            else:
                items = [normalize_number(token, digits)]
        except NumberError as exc:
            if not lenient:
                result.errors.append(str(exc))
            continue
        for display, key in items:
            if key in seen:
                result.duplicates.append(display)
            else:
                seen.add(key)
                result.numbers.append((display, key))
    return result
