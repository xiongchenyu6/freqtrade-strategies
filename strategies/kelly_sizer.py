"""
Half-Kelly position sizing helper for HonestTrend-family strategies.

Why Half-Kelly and not full Kelly:
  Full Kelly maximises log-growth of equity but is only optimal if (p, b) are
  known exactly. Empirically, a 5% overestimate of win rate already drives
  expected log-growth negative — i.e. ruin-prone. Halving the fraction
  preserves ~75% of the growth rate with dramatically lower variance, which
  is the standard practitioner choice (Thorp 1997).

Parameter-uncertainty shrinkage (Wilson lower bound on p):
  Backtest p̂ is a point estimate with sampling variance. Plugging it into
  Kelly as if it were the true p systematically over-bets — the more so the
  smaller n is. We replace p̂ with its Wilson score lower bound at a
  configurable confidence level (default z=1.96, i.e. one-sided 97.5%).
  This is equivalent to a small-sample shrinkage toward 0.5 and disappears
  asymptotically as n → ∞.

  Concretely: a strategy with p̂=0.55 on n=100 trades has a Wilson lower
  bound of ~0.46 — Kelly says do *not* bet. The same p̂=0.55 on n=10_000
  trades has a lower bound of ~0.54 — bet close to the point estimate.

Sample-size guard:
  We refuse Kelly when the backtest has fewer than MIN_TRADES_FOR_KELLY
  trades. Below that threshold even the lower bound is too unstable; fall
  back to whatever stake freqtrade proposed from the config.

Hard cap:
  Even with a clean Kelly answer we never bet more than KELLY_CAP_FRAC of
  equity per trade. Belt-and-suspenders against parameter drift —
  the strategy that hit p=0.9 on the past 6 months might be at p=0.5 next
  month, and Kelly answers there differ by 4×.

Known limitations (not addressed here, see project_kelly_findings.md):
  - Multi-strategy correlation is not modelled. We rely on KELLY_CAP_FRAC
    to bound the joint exposure. The principled fix is f* = Σ⁻¹ μ.
  - No vol-targeting overlay; sizing assumes stationary return distribution.
"""

from __future__ import annotations

import json
import logging
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

KELLY_HALF_DIVISOR = 2.0
KELLY_CAP_FRAC = 0.05
MIN_TRADES_FOR_KELLY = 30
# z=1.96 → one-sided 97.5% lower bound on p (standard for finance risk work).
# Higher z = more conservative shrinkage = smaller positions.
WILSON_Z = 1.96
DEFAULT_BACKTEST_DIR = Path("user_data/backtest_results")


def wilson_lower_bound(successes: int, n: int, z: float = WILSON_Z) -> float:
    """One-sided Wilson score lower bound on a binomial proportion.

    The Wilson interval is well-defined for small n and at extremes (0, 1),
    where the naive Wald interval (p ± z·√(p(1-p)/n)) collapses. The closed
    form for the lower bound:

        p̂ + z²/(2n)        z·√(p̂(1-p̂)/n + z²/(4n²))
        ───────────────  −  ───────────────────────────
          1 + z²/n                  1 + z²/n

    Equivalent to a Bayesian posterior under a uniform-ish prior, with the
    shrinkage strength controlled by z.
    """
    if n <= 0:
        return 0.0
    p_hat = successes / n
    denom = 1.0 + (z * z) / n
    centre = p_hat + (z * z) / (2.0 * n)
    margin = z * math.sqrt(p_hat * (1.0 - p_hat) / n + (z * z) / (4.0 * n * n))
    lower = (centre - margin) / denom
    return max(0.0, min(1.0, lower))


@dataclass
class KellyStats:
    """Aggregate win/payoff stats for a single strategy across all pairs."""

    win_rate: float
    payoff_ratio: float
    n_trades: int

    def conservative_win_rate(self, z: float = WILSON_Z) -> float:
        """Wilson lower bound on the win rate. Falls back to point estimate
        if we somehow lost track of the trade count."""
        if self.n_trades <= 0:
            return self.win_rate
        wins = int(round(self.win_rate * self.n_trades))
        return wilson_lower_bound(wins, self.n_trades, z=z)

    def kelly_fraction(self, use_lower_bound: bool = True, z: float = WILSON_Z) -> float:
        """Raw Kelly fraction f* = (p·b − q) / b, clamped at 0 for negative edge.

        :param use_lower_bound: if True, shrink p toward 0.5 via the Wilson
            lower bound before solving (recommended; matches the "parameter
            uncertainty" practice in [[project-kelly-findings]]).
        :param z: critical value for the Wilson interval. 1.96 ≈ 97.5%.
        """
        if self.payoff_ratio <= 0:
            return 0.0
        p = self.conservative_win_rate(z=z) if use_lower_bound else self.win_rate
        b = self.payoff_ratio
        f = (p * b - (1 - p)) / b
        return max(f, 0.0)

    def half_kelly_clamped(
        self,
        cap: float = KELLY_CAP_FRAC,
        use_lower_bound: bool = True,
        z: float = WILSON_Z,
    ) -> float:
        f = self.kelly_fraction(use_lower_bound=use_lower_bound, z=z)
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
