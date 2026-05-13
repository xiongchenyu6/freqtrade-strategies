"""
Half-Kelly position sizing helper for HonestTrend-family strategies.

Why Half-Kelly and not full Kelly:
  Full Kelly maximises log-growth of equity but is only optimal if (p, b) are
  known exactly. Empirically, a 5% overestimate of win rate already drives
  expected log-growth negative — i.e. ruin-prone. Halving the fraction
  preserves ~75% of the growth rate with dramatically lower variance, which
  is the standard practitioner choice (Thorp 1997).

Sample-size guard:
  We refuse Kelly when the backtest has fewer than MIN_TRADES_FOR_KELLY
  trades. Below that threshold the (p, b) estimate is dominated by sampling
  noise; we fall back to whatever stake freqtrade proposed from the config.

Hard cap:
  Even with a clean Kelly answer we never bet more than KELLY_CAP_FRAC of
  equity per trade. This is belt-and-suspenders against parameter drift —
  the strategy that hit p=0.9 on the past 6 months might be at p=0.5 next
  month, and Kelly answers there differ by 4×.
"""

from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

KELLY_HALF_DIVISOR = 2.0
KELLY_CAP_FRAC = 0.05
MIN_TRADES_FOR_KELLY = 30
DEFAULT_BACKTEST_DIR = Path("user_data/backtest_results")


@dataclass
class KellyStats:
    """Aggregate win/payoff stats for a single strategy across all pairs."""

    win_rate: float
    payoff_ratio: float
    n_trades: int

    def kelly_fraction(self) -> float:
        """Raw Kelly fraction f* = (p*b - q) / b, clamped at 0 for negative edge."""
        if self.payoff_ratio <= 0:
            return 0.0
        p, b = self.win_rate, self.payoff_ratio
        f = (p * b - (1 - p)) / b
        return max(f, 0.0)

    def half_kelly_clamped(self, cap: float = KELLY_CAP_FRAC) -> float:
        f = self.kelly_fraction()
        if f <= 0:
            return 0.0
        return min(f / KELLY_HALF_DIVISOR, cap)


def stats_from_trades(trades: list[dict]) -> Optional[KellyStats]:
    """Build (p, b, n) from a freqtrade backtest trade list.

    :param trades: list of trade dicts with ``profit_ratio`` (or ``profit_percentage``)
    :returns: KellyStats or None if the sample is degenerate (no wins, no losses,
        or no trades at all)
    """
    if not trades:
        return None
    wins: list[float] = []
    losses: list[float] = []
    for t in trades:
        pr = t.get("profit_ratio")
        if pr is None:
            pct = t.get("profit_percentage")
            if pct is None:
                continue
            pr = pct / 100.0
        if pr > 0:
            wins.append(pr)
        elif pr < 0:
            losses.append(pr)
    n = len(wins) + len(losses)
    if n == 0 or not wins or not losses:
        return None
    avg_win = sum(wins) / len(wins)
    avg_loss = abs(sum(losses) / len(losses))
    if avg_loss == 0:
        return None
    return KellyStats(
        win_rate=len(wins) / n,
        payoff_ratio=avg_win / avg_loss,
        n_trades=n,
    )


def _load_stats_from_zip(zip_path: Path, strategy_name: str) -> Optional[KellyStats]:
    """Read aggregate stats from a backtest zip.

    A freqtrade backtest zip ships two JSONs per strategy:
      - ``<stem>.json``                — top-level results, contains ``strategy[name].trades``
      - ``<stem>_<StrategyName>.json`` — params/config dump, *no* trade list

    We want the first. Detect it by looking for the unsuffixed JSON named after
    the zip stem; if absent we scan all JSONs and pick whichever exposes
    ``strategy[strategy_name].trades``.
    """
    stem = zip_path.stem
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        preferred = f"{stem}.json"
        target: Optional[str] = preferred if preferred in names else None

        candidates = [target] if target else [
            n for n in names
            if n.endswith(".json") and "_config" not in n and not n.endswith(".meta.json")
        ]
        for name in candidates:
            if name is None:
                continue
            with z.open(name) as f:
                data = json.load(f)
            sd = None
            if isinstance(data, dict) and "strategy" in data:
                sd = data["strategy"].get(strategy_name)
            if sd and "trades" in sd:
                stats = stats_from_trades(sd.get("trades", []))
                if stats is not None:
                    return stats
    return None


def latest_strategy_stats(
    strategy_name: str,
    backtest_dir: Path = DEFAULT_BACKTEST_DIR,
) -> Optional[KellyStats]:
    """Walk ``backtest_dir`` newest-first, return first parseable stats for the strategy."""
    if not backtest_dir.exists():
        return None
    candidates = sorted(
        backtest_dir.glob("backtest-result-*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for zp in candidates:
        try:
            stats = _load_stats_from_zip(zp, strategy_name)
        except (zipfile.BadZipFile, KeyError, ValueError, json.JSONDecodeError) as e:
            logger.debug("kelly: skipping %s: %s", zp.name, e)
            continue
        if stats is not None:
            return stats
    return None


def kelly_stake(
    equity: float,
    stats: Optional[KellyStats],
    proposed_stake: float,
    max_stake: float,
    cap: float = KELLY_CAP_FRAC,
    min_trades: int = MIN_TRADES_FOR_KELLY,
) -> float:
    """Half-Kelly stake with a hard cap + low-sample fallback.

    :param equity: total tradable equity in stake currency
    :param stats: backtest stats, or None to skip Kelly
    :param proposed_stake: freqtrade's default stake (used when Kelly is skipped)
    :param max_stake: exchange/balance cap
    :param cap: max fraction of equity per trade
    :param min_trades: minimum sample size to trust Kelly
    :returns: stake amount in stake currency, clamped to [0, max_stake]
    """
    if equity <= 0:
        return min(proposed_stake, max_stake)
    if stats is None or stats.n_trades < min_trades:
        return min(proposed_stake, max_stake)
    f_half = stats.half_kelly_clamped(cap=cap)
    if f_half <= 0:
        # Negative edge per Kelly. custom_stake_amount can't refuse the entry,
        # so we shrink to half the proposed stake instead of zero.
        return min(proposed_stake * 0.5, max_stake)
    return min(equity * f_half, max_stake)
