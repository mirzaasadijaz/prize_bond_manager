"""Small dataclasses shared between the database, processing and UI layers."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AddResult:
    """Outcome of adding bonds (manual entry, copies dialog or file import)."""

    added: int = 0
    skipped_duplicates: list[str] = field(default_factory=list)  # left out on purpose
    shared: int = 0          # added bonds whose number another bond already holds
    copy_ids: list[int] = field(default_factory=list)
    copy_names: list[str] = field(default_factory=list)
    renamed_copies: list[tuple[str, str]] = field(default_factory=list)

    def merge(self, other: "AddResult") -> None:
        self.added += other.added
        self.skipped_duplicates += other.skipped_duplicates
        self.shared += other.shared
        self.copy_ids += other.copy_ids
        self.copy_names += other.copy_names
        self.renamed_copies += other.renamed_copies

    def summary(self) -> str:
        parts = [f"{self.added:,} bond(s) added"]
        if self.copy_names:
            parts.append(f"{len(self.copy_names):,} copy/copies created")
        if self.shared:
            parts.append(f"{self.shared:,} share a number with another bond")
        if self.skipped_duplicates:
            parts.append(f"{len(self.skipped_duplicates):,} left out (number already held)")
        return ", ".join(parts)


@dataclass
class ScanResult:
    """What one run of the win-checking agent found."""

    trigger: str = "manual"
    ran_at: str = ""
    draw_id: int | None = None
    draws_checked: int = 0
    bonds_checked: int = 0
    total_matches: int = 0
    new_pending: int = 0

    @property
    def already_known(self) -> int:
        return self.total_matches - self.new_pending

    def summary(self) -> str:
        if self.new_pending:
            return (f"Agent found {self.new_pending:,} new possible win(s) - "
                    "waiting for your approval.")
        if self.total_matches:
            return (f"No new matches ({self.already_known:,} already listed "
                    "or decided earlier).")
        return "No matching bonds found."


@dataclass
class ApprovalResult:
    """Outcome of approving pending wins."""

    win_ids: list[int] = field(default_factory=list)
    rejected: list[tuple[int, str]] = field(default_factory=list)  # (pending id, reason)
    with_siblings: int = 0   # bonds added to the approval because they hold the same winning number

    @property
    def approved(self) -> int:
        return len(self.win_ids)
