"""Turn file contents into bonds and copies.

Pipeline (the import dialog uses the same three steps):

    parsed = load_records(path)                 # read + understand the file
    groups = plan_groups(parsed, options)       # decide which bonds form which copy
    result = commit(db, groups, options, ...)   # write to the database (all or nothing)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..models import AddResult
from .numbers import parse_pattern
from .parsers import RawTable, read_file

# Column header names (lower-case, letters/digits only) understood in tables.
ALIASES: dict[str, set[str]] = {
    "number": {"bondnumber", "bondno", "bondnum", "bondnumbers", "number", "numbers", "no",
               "num", "bond", "bonds", "serial", "serialnumber", "prizebond",
               "prizebondnumber", "prizebondno"},
    "denomination": {"denomination", "denom", "price", "value", "amount", "rs", "rupees",
                     "bondprice", "bondvalue", "facevalue", "face"},
    "date": {"date", "purchasedate", "dateofpurchase", "purchased", "purchasedon", "bought",
             "boughton", "buydate", "dop"},
    "copy": {"copy", "book", "batch", "set", "booklet", "bookno", "copyno", "copynumber",
             "copyname", "bookname", "batchno", "batchname"},
    "position": {"position", "pos", "place", "index", "seq", "sequence"},
}

# "Copy 3" / "Book 2:" headings inside Word paragraphs or text files.
_LABEL = re.compile(r"^\s*((?:copy|book|batch|booklet|set)\b[^:]*?)\s*(?::(.*))?$", re.IGNORECASE)
_LONG_DIGITS = re.compile(r"\d{5,}")
_NUMBERISH = re.compile(r"^\d{4,}(?:\.0+)?(?:\s*(?:-|–|to)\s*\d{4,})?", re.IGNORECASE)
_DIGITS = re.compile(r"^\d+(?:\.0+)?")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_AMOUNT = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass
class ImportRecord:
    display: str
    key: int
    denomination: int | None = None
    purchase_date: str | None = None
    copy_name: str | None = None
    position: int | None = None
    source: str = ""


@dataclass
class ParsedFile:
    path: str
    stem: str
    records: list[ImportRecord] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    # Numbers repeated inside one cell/pattern ("100001-100005, 100003").  The same number
    # in different rows or copies is NOT a duplicate: copies may hold the same number.
    duplicates: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)       # sheets / tables that held bonds
    has_copy_column: bool = False
    has_position_column: bool = False
    has_denomination_column: bool = False
    has_date_column: bool = False

    @property
    def missing_denomination(self) -> bool:
        return any(r.denomination is None for r in self.records)

    @property
    def copy_labels(self) -> list[str]:
        return list(dict.fromkeys(r.copy_name for r in self.records if r.copy_name))

    def summary(self) -> str:
        text = f"{len(self.records):,} bond number(s) found"
        if len(self.sources) > 1:
            text += f" in {len(self.sources)} sheets/tables"
        if self.duplicates:
            text += f", {len(self.duplicates):,} repeated within one entry (ignored)"
        if self.problems:
            text += f", {len(self.problems):,} problem(s)"
        return text


@dataclass
class ImportOptions:
    mode: str = "auto"            # auto | single | chunks | none
    copy_name: str = ""           # base name for the copy / copies (default: file name)
    chunk_size: int = 100
    default_denomination: int | None = None
    default_date: str | None = None
    # Leave out numbers that are already in the database.  Off by default: the same
    # number may be held in several copies, and then all those bonds win together.
    skip_existing: bool = False


@dataclass
class Group:
    """Bonds that will become one copy (name=None -> loose bonds)."""

    name: str | None
    items: list[ImportRecord]
    positions: list[int] | None = None
    repeated: list[str] = field(default_factory=list)   # same number twice in this copy (dropped)


# --------------------------------------------------------------------- cells
def parse_date(text: str) -> str | None:
    """ISO date from the common spreadsheet/text forms (day-first for 01/02/2025)."""
    text = (text or "").strip()
    if not text:
        return None
    match = _ISO_DATE.match(text)
    try:
        if match:
            return datetime(int(match[1]), int(match[2]), int(match[3])).date().isoformat()
        if text.isdigit():
            raise ValueError("number, not a date")
        from dateutil import parser as date_parser
        return date_parser.parse(text, dayfirst=True).date().isoformat()
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"unreadable date '{text}'") from exc


def parse_denomination(text: str) -> int:
    match = _AMOUNT.search(text or "")
    if not match:
        raise ValueError(f"unreadable denomination '{text}'")
    value = float(match.group(0).replace(",", ""))
    if value <= 0 or not value.is_integer():
        raise ValueError(f"unreadable denomination '{text}'")
    return int(value)


# -------------------------------------------------------------------- tables
def _header_key(cell: str) -> str:
    return re.sub(r"[^a-z0-9]", "", cell.lower())


def _find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    for index, row in enumerate(rows[:10]):
        mapping: dict[str, int] = {}
        for col, cell in enumerate(row):
            key = _header_key(cell)
            for name, aliases in ALIASES.items():
                if key in aliases and name not in mapping:
                    mapping[name] = col
                    break
        if "number" in mapping:
            return index, mapping
    return None


def _guess_number_column(rows: list[list[str]]) -> int:
    width = max(len(r) for r in rows)
    sample = rows[:50]
    for pattern in (_NUMBERISH, _DIGITS):
        scores = [sum(1 for r in sample if col < len(r) and pattern.match(r[col]))
                  for col in range(width)]
        if max(scores) > 0:
            return scores.index(max(scores))
    return 0


def _cell(row: list[str], col: int | None) -> str:
    return row[col].strip() if col is not None and col < len(row) else ""


def _read_table(table: RawTable, parsed: ParsedFile) -> list[ImportRecord]:
    rows = table.rows
    found = _find_header(rows)
    if found:
        start, mapping = found[0] + 1, found[1]
    else:
        start, mapping = 0, {"number": _guess_number_column(rows)}
    parsed.has_copy_column |= "copy" in mapping
    parsed.has_position_column |= "position" in mapping
    parsed.has_denomination_column |= "denomination" in mapping
    parsed.has_date_column |= "date" in mapping
    records: list[ImportRecord] = []
    for row in rows[start:]:
        text = _cell(row, mapping["number"])
        if not text:
            continue
        pattern = parse_pattern(text)
        for message in pattern.errors:
            parsed.problems.append(f"{table.name}: {message}")
        parsed.duplicates += pattern.duplicates
        if not pattern.numbers:
            continue
        try:
            denomination = (parse_denomination(_cell(row, mapping.get("denomination")))
                            if _cell(row, mapping.get("denomination")) else None)
        except ValueError as exc:
            parsed.problems.append(f"{table.name}: {text} skipped - {exc}")
            continue
        try:
            when = parse_date(_cell(row, mapping.get("date")))
        except ValueError as exc:
            parsed.problems.append(f"{table.name}: {text} imported without a date - {exc}")
            when = None
        position = None
        raw_position = _cell(row, mapping.get("position"))
        if raw_position:
            if raw_position.isdigit() and int(raw_position) > 0 and len(pattern.numbers) == 1:
                position = int(raw_position)
            else:
                parsed.problems.append(f"{table.name}: position '{raw_position}' for {text} ignored")
        copy_name = _cell(row, mapping.get("copy")) or None
        for display, key in pattern.numbers:
            records.append(ImportRecord(display, key, denomination, when, copy_name,
                                        position, table.name))
    return records


def _read_text_block(table: RawTable, parsed: ParsedFile) -> list[ImportRecord]:
    """Free text: numbers/ranges anywhere; 'Copy 2' style lines name the copy."""
    records: list[ImportRecord] = []
    current: str | None = None
    for (line,) in table.rows:
        label = _LABEL.match(line)
        numbers_text = line
        if label and (label.group(2) is not None or not _LONG_DIGITS.search(line)):
            current = label.group(1).strip()
            numbers_text = label.group(2) or ""
        pattern = parse_pattern(numbers_text, lenient=True)
        parsed.duplicates += pattern.duplicates
        for display, key in pattern.numbers:
            records.append(ImportRecord(display, key, None, None, current, None, table.name))
    if any(r.copy_name for r in records):
        parsed.has_copy_column = True
    return records


# --------------------------------------------------------------------- steps
def load_records(path: str | Path) -> ParsedFile:
    """Step 1: read the file and extract bond records (no database access)."""
    path = Path(path)
    parsed = ParsedFile(str(path), path.stem)
    for table in read_file(path):
        reader = _read_text_block if table.kind == "text" else _read_table
        found = reader(table, parsed)
        if found:
            parsed.sources.append(table.name)
            parsed.records += found
    return parsed


def _unique(records: list[ImportRecord], group: Group, default_denomination: int | None) -> None:
    """Fill ``group`` with ``records``; a number repeated inside one copy is kept once."""
    seen: set[tuple[int | None, int]] = set()
    for rec in records:
        ident = (rec.denomination or default_denomination, rec.key)
        if ident in seen:
            group.repeated.append(rec.display)
        else:
            seen.add(ident)
            group.items.append(rec)


def plan_groups(parsed: ParsedFile, options: ImportOptions) -> list[Group]:
    """Step 2: decide which bonds form which copy.

    The same number in two different copies is normal (every one of those bonds wins when
    it is drawn).  Only a number repeated *inside one copy* is dropped: a copy holds each
    number once.
    """
    records = parsed.records
    if not records:
        return []
    base = options.copy_name.strip() or parsed.stem
    default = options.default_denomination
    if options.mode in ("none", "single"):
        group = Group(None if options.mode == "none" else base, [])
        _unique(records, group, default)
        return [group]
    if options.mode == "chunks":
        size = max(1, int(options.chunk_size))
        groups = []
        for i in range(0, len(records), size):
            group = Group(f"{base} - {i // size + 1}", [])
            _unique(records[i:i + size], group, default)
            groups.append(group)
        return groups
    named: dict[str, list[ImportRecord]] = {}
    several_sources = len(parsed.sources) > 1
    for rec in records:
        name = rec.copy_name or (f"{base} - {rec.source}" if several_sources else base)
        named.setdefault(name, []).append(rec)
    groups = []
    for name, members in named.items():
        group = Group(name, [])
        _unique(members, group, default)
        spots = [r.position for r in group.items]
        if all(spots) and len(set(spots)) == len(spots):
            group.positions = spots
        groups.append(group)
    return groups


def _denomination_of(rec: ImportRecord, options: ImportOptions) -> int:
    denomination = rec.denomination or options.default_denomination
    if not denomination:
        raise ValueError(f"Bond {rec.display} has no denomination - "
                         "choose a default denomination.")
    return denomination


def held_in_database(db, records: list[ImportRecord],
                     default_denomination: int | None = None) -> tuple[int, list[str]]:
    """How many distinct numbers of ``records`` are already held by bonds in the database.

    Returns ``(count, a few examples)``; records without a denomination (and no default yet)
    are ignored.  Holding a number already is allowed - it only means the new bonds share
    their number with the old ones, so they win together.
    """
    wanted: dict[int, dict[int, str]] = {}
    for rec in records:
        denomination = rec.denomination or default_denomination
        if denomination:
            wanted.setdefault(denomination, {})[rec.key] = rec.display
    count, examples = 0, []
    for denomination, keys in wanted.items():
        held = db.held_keys(denomination, list(keys))
        count += len(held)
        examples += [keys[k] for k in sorted(held)[:5]]
    return count, examples[:8]


def commit(db, groups: list[Group], options: ImportOptions, source_name: str = "") -> AddResult:
    """Step 3: write the groups to the database, all or nothing.

    With ``options.skip_existing`` numbers that were in the database *before* the import are
    left out; copies imported together may still share numbers with each other.
    """
    result = AddResult()
    with db.tx():
        plan = []
        for group in groups:
            by_denomination: dict[int, list[int]] = {}
            for index, rec in enumerate(group.items):
                by_denomination.setdefault(_denomination_of(rec, options), []).append(index)
            plan.append((group, by_denomination))
        skip: dict[int, set[int]] = {}
        if options.skip_existing:
            wanted: dict[int, set[int]] = {}
            for group, by_denomination in plan:
                for denomination, indexes in by_denomination.items():
                    wanted.setdefault(denomination, set()).update(
                        group.items[i].key for i in indexes)
            skip = {d: db.held_keys(d, sorted(keys)) for d, keys in wanted.items()}
        for group, by_denomination in plan:
            for denomination, indexes in by_denomination.items():
                items = [group.items[i] for i in indexes]
                numbers = [(r.display, r.key) for r in items]
                dates = [r.purchase_date or options.default_date for r in items]
                skip_keys = skip.get(denomination)
                if group.name is None:
                    result.merge(db.add_loose_bonds(numbers, denomination, dates=dates,
                                                    skip_keys=skip_keys))
                    continue
                name = group.name if len(by_denomination) == 1 else f"{group.name} (Rs {denomination})"
                positions = [group.positions[i] for i in indexes] if group.positions else None
                result.merge(db.add_copy(name, numbers, denomination, dates=dates,
                                         positions=positions, skip_keys=skip_keys))
        db.log("File imported", f"{source_name or 'file'}: {result.summary()}")
    return result


def import_file(db, path: str | Path, options: ImportOptions | None = None) -> AddResult:
    """Convenience wrapper: read, plan and import in one call."""
    options = options or ImportOptions()
    parsed = load_records(path)
    return commit(db, plan_groups(parsed, options), options, Path(path).name)
