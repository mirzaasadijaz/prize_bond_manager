"""The win-checking agent and the approval workflow around it.

The agent never takes a bond out of the waiting list on its own.  It only
*queues* possible wins in the temporary pending list.  A bond reaches the final
win list when -- and only when -- the user approves it.

When it runs (``trigger`` in the activity log):
    startup   - when the app opens
    bonds     - after bonds are added or imported (new bonds may match old draws)
    draw      - after winning numbers are saved
    manual    - the "Run agent now" button
The automatic triggers can be switched off in the Pending Wins page.
"""
from __future__ import annotations

from ..db import Database
from ..models import ApprovalResult, ScanResult

AUTO_SETTING = "agent_auto"
LAST_RUN_SETTING = "agent_last_run"
LAST_SUMMARY_SETTING = "agent_last_summary"


class WinAgent:
    def __init__(self, db: Database):
        self.db = db

    # -- settings --------------------------------------------------------
    @property
    def auto_enabled(self) -> bool:
        return self.db.get_setting(AUTO_SETTING, "1") == "1"

    @auto_enabled.setter
    def auto_enabled(self, enabled: bool) -> None:
        self.db.set_setting(AUTO_SETTING, "1" if enabled else "0")

    def last_run_text(self) -> str:
        when = self.db.get_setting(LAST_RUN_SETTING)
        if not when:
            return "The agent has not run yet."
        return f"Last run {when}: {self.db.get_setting(LAST_SUMMARY_SETTING, '')}"

    # -- scanning --------------------------------------------------------
    def scan(self, draw_id: int | None = None, trigger: str = "manual") -> ScanResult:
        """Check the waiting list against winning numbers (all draws, or one)."""
        result = self.db.scan_for_matches(draw_id)
        result.trigger = trigger
        self.db.set_setting(LAST_RUN_SETTING, result.ran_at)
        self.db.set_setting(LAST_SUMMARY_SETTING, result.summary())
        if result.new_pending or trigger == "manual":
            self.db.log("Agent scan", f"{trigger}: {result.summary()}")
        return result

    def run_if_enabled(self, trigger: str, draw_id: int | None = None) -> ScanResult | None:
        """Automatic trigger: runs only when the user left the agent switched on."""
        return self.scan(draw_id, trigger) if self.auto_enabled else None

    # -- the temporary list and its approval ------------------------------
    def pending(self, status: str = "pending") -> list[dict]:
        return self.db.list_pending(status)

    def approve(self, pending_ids) -> ApprovalResult:
        return self.db.approve_pending(list(pending_ids))

    def approve_all(self) -> ApprovalResult:
        return self.approve(p["pending_id"] for p in self.pending())

    def reject(self, pending_ids) -> int:
        return self.db.reject_pending(list(pending_ids))

    def restore(self, pending_ids) -> int:
        return self.db.restore_pending(list(pending_ids))
