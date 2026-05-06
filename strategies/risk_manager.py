"""
Risk Manager — Taleb-inspired strategy kill switch

Enforces anti-fragile deployment rules:
  1. Hard drawdown stop: 15% → PAUSE, 20% → RETIRE
  2. Time-based edge check: after 6 months, if rolling PF < 1.2 → RETIRE
  3. Manual override via CLI (pause/resume/retire/reset)
  4. All state persisted to JSON, readable by strategy + monitor scripts

State machine:
  ACTIVE ──(DD>15%)──→ PAUSED ──(DD recovers to <10%)──→ ACTIVE
  ACTIVE ──(DD>20%)──→ RETIRED (manual reset only)
  ACTIVE ──(6mo + PF<1.2)──→ RETIRED

Key principle (Taleb): strategies die cliff-fall, not slowly.
Never add on losses. Only manual resume after RETIRE.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Thresholds (percent as 0-1 fractions)
DD_PAUSE_THRESHOLD = 0.15
DD_RESUME_THRESHOLD = 0.10  # must recover below this to auto-resume
DD_RETIRE_THRESHOLD = 0.20
MIN_LIVE_DAYS_BEFORE_PF_CHECK = 180  # 6 months
PF_RETIRE_THRESHOLD = 1.20
MIN_TRADES_FOR_PF_CHECK = 50


@dataclass
class RiskState:
    status: str = "ACTIVE"  # ACTIVE | PAUSED | RETIRED
    status_reason: str = "initial"
    status_since: str = ""
    start_date: str = ""
    peak_equity: float = 0.0
    current_equity: float = 0.0
    current_dd_pct: float = 0.0
    total_trades: int = 0
    live_days: int = 0
    rolling_pf: float = 0.0  # PF over last N trades
    notes: str = ""


class RiskManager:
    """
    Reads/writes a JSON state file. Strategy consults `status` on each entry.
    The monitor script updates equity/DD/PF from live trade DB.
    """

    def __init__(self, state_file: Path):
        self.state_file = Path(state_file)
        initial = not self.state_file.exists()
        self.state = self._load()
        if initial:
            self.save()  # persist initial state

    def _load(self) -> RiskState:
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    data = json.load(f)
                return RiskState(**data)
            except Exception as e:
                logger.error(f"Failed to load risk state: {e}. Using defaults.")
        # First-time init
        now = datetime.now(timezone.utc).isoformat()
        return RiskState(
            status="ACTIVE",
            status_reason="initial",
            status_since=now,
            start_date=now,
        )

    def save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(asdict(self.state), f, indent=2)

    # --- Public API for strategies ---

    def can_enter(self) -> tuple[bool, str]:
        """Returns (allowed, reason). Strategy calls this before each entry."""
        if self.state.status == "ACTIVE":
            return True, "ok"
        return False, f"{self.state.status}: {self.state.status_reason}"

    # --- Public API for monitor ---

    def update_equity(self, equity: float) -> Optional[str]:
        """
        Update equity, recompute DD, transition state if thresholds hit.
        Returns a status-change message if state changed, else None.
        """
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity

        if self.state.peak_equity > 0:
            self.state.current_equity = equity
            self.state.current_dd_pct = max(
                0.0, (self.state.peak_equity - equity) / self.state.peak_equity
            )

        return self._evaluate_transitions()

    def update_metrics(
        self, total_trades: int, rolling_pf: float, live_days: int
    ) -> Optional[str]:
        """Update trade stats, check time-based PF rule."""
        self.state.total_trades = total_trades
        self.state.rolling_pf = rolling_pf
        self.state.live_days = live_days
        return self._evaluate_transitions()

    def _transition(self, new_status: str, reason: str) -> str:
        old = self.state.status
        self.state.status = new_status
        self.state.status_reason = reason
        self.state.status_since = datetime.now(timezone.utc).isoformat()
        msg = f"Risk state: {old} → {new_status}. Reason: {reason}"
        logger.warning(msg)
        return msg

    def _evaluate_transitions(self) -> Optional[str]:
        s = self.state

        # RETIRED is terminal (manual reset only)
        if s.status == "RETIRED":
            return None

        dd = s.current_dd_pct

        # Hard stop: retirement threshold
        if dd >= DD_RETIRE_THRESHOLD:
            return self._transition(
                "RETIRED",
                f"Drawdown {dd*100:.1f}% >= {DD_RETIRE_THRESHOLD*100:.0f}%. "
                "Strategy retired. Manual reset required.",
            )

        # Time-based PF check (after 6 months live)
        if (
            s.live_days >= MIN_LIVE_DAYS_BEFORE_PF_CHECK
            and s.total_trades >= MIN_TRADES_FOR_PF_CHECK
            and 0 < s.rolling_pf < PF_RETIRE_THRESHOLD
        ):
            return self._transition(
                "RETIRED",
                f"After {s.live_days}d live, rolling PF {s.rolling_pf:.2f} "
                f"< {PF_RETIRE_THRESHOLD}. Edge gone. Strategy retired.",
            )

        # Pause threshold
        if s.status == "ACTIVE" and dd >= DD_PAUSE_THRESHOLD:
            return self._transition(
                "PAUSED",
                f"Drawdown {dd*100:.1f}% >= {DD_PAUSE_THRESHOLD*100:.0f}%. "
                "Auto-resume when DD recovers below "
                f"{DD_RESUME_THRESHOLD*100:.0f}%.",
            )

        # Auto-resume from PAUSE
        if s.status == "PAUSED" and dd < DD_RESUME_THRESHOLD:
            return self._transition(
                "ACTIVE",
                f"Drawdown recovered to {dd*100:.1f}% < "
                f"{DD_RESUME_THRESHOLD*100:.0f}%. Resuming.",
            )

        return None

    # --- Manual CLI operations ---

    def manual_pause(self, note: str = "") -> str:
        return self._transition("PAUSED", f"manual: {note or 'user requested'}")

    def manual_retire(self, note: str = "") -> str:
        return self._transition("RETIRED", f"manual: {note or 'user requested'}")

    def manual_reset(self, note: str = "") -> str:
        self.state.peak_equity = self.state.current_equity
        self.state.current_dd_pct = 0.0
        return self._transition("ACTIVE", f"manual reset: {note or 'user'}")
