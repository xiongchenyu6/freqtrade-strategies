"""Unit tests for strategies.kelly_sizer."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Strategy modules live in strategies/ at the repo root and have no __init__.py;
# add to path so we can import directly.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "strategies"))

import kelly_sizer  # noqa: E402
from kelly_sizer import (  # noqa: E402
    KellyStats,
    kelly_stake,
    stats_from_trades,
    wilson_lower_bound,
)


class TestKellyStats:
    def test_classic_kelly_formula_point_estimate(self):
        # use_lower_bound=False reproduces the textbook formula:
        # p=0.60, b=2.0 → f* = (0.6*2 - 0.4)/2 = 0.40
        s = KellyStats(win_rate=0.60, payoff_ratio=2.0, n_trades=100)
        assert s.kelly_fraction(use_lower_bound=False) == pytest.approx(0.40, abs=1e-9)

    def test_wilson_shrinks_kelly_for_moderate_n(self):
        # Same (p, b) as above but n=100. Wilson p_lower ≈ 0.502, so
        # f* = (0.502·2 - 0.498)/2 ≈ 0.253, materially less than 0.40.
        s = KellyStats(win_rate=0.60, payoff_ratio=2.0, n_trades=100)
        shrunk = s.kelly_fraction(use_lower_bound=True)
        point = s.kelly_fraction(use_lower_bound=False)
        assert shrunk < point
        assert shrunk == pytest.approx(0.253, abs=0.01)

    def test_wilson_disappears_with_large_n(self):
        # n=10_000 → Wilson p_lower ≈ 0.5919, very close to point estimate.
        # Demonstrates the asymptotic property: shrinkage vanishes as n → ∞.
        s = KellyStats(win_rate=0.60, payoff_ratio=2.0, n_trades=10_000)
        shrunk = s.kelly_fraction(use_lower_bound=True)
        point = s.kelly_fraction(use_lower_bound=False)
        # Within 5% of the point estimate
        assert shrunk == pytest.approx(point, rel=0.05)

    def test_wilson_kills_marginal_edge(self):
        # p̂=0.55 with n=100 looks like a real edge in classical Kelly
        # (f* = 0.10) — but Wilson lower bound (~0.45) flips it to negative.
        # This is the whole point of shrinkage.
        s = KellyStats(win_rate=0.55, payoff_ratio=1.0, n_trades=100)
        assert s.kelly_fraction(use_lower_bound=False) == pytest.approx(0.10, abs=1e-9)
        assert s.kelly_fraction(use_lower_bound=True) == 0.0

    def test_negative_edge_clamps_to_zero(self):
        # p=0.40, b=1.0 — clearly negative under either path.
        s = KellyStats(win_rate=0.40, payoff_ratio=1.0, n_trades=100)
        assert s.kelly_fraction(use_lower_bound=False) == 0.0
        assert s.kelly_fraction(use_lower_bound=True) == 0.0

    def test_half_kelly_hits_cap_under_aggressive_stats(self):
        s = KellyStats(win_rate=0.60, payoff_ratio=2.0, n_trades=100)
        # Both paths produce f* > 0.10; halved still > cap → returns the cap.
        assert s.half_kelly_clamped() == pytest.approx(0.05, abs=1e-9)
        assert s.half_kelly_clamped(use_lower_bound=False) == pytest.approx(0.05, abs=1e-9)

    def test_cap_clamps_aggressive_kelly(self):
        # Even p=0.9 b=5.0 (which would suggest f* = 0.88) gets pulled to 0.05
        # cap. Wilson on n=100 only shrinks p to ~0.83, so cap still binds.
        s = KellyStats(win_rate=0.90, payoff_ratio=5.0, n_trades=100)
        assert s.half_kelly_clamped(cap=0.05) == pytest.approx(0.05, abs=1e-9)

    def test_zero_payoff_returns_zero(self):
        s = KellyStats(win_rate=0.60, payoff_ratio=0.0, n_trades=100)
        assert s.kelly_fraction() == 0.0


class TestWilsonLowerBound:
    def test_zero_n_returns_zero(self):
        assert wilson_lower_bound(0, 0) == 0.0

    def test_all_wins_does_not_return_one(self):
        # The naive Wald interval at p̂=1 gives [1, 1]; Wilson correctly says
        # "with finite n, we can't be sure p really is 1". Should be < 1.
        assert wilson_lower_bound(10, 10) < 1.0
        assert wilson_lower_bound(10, 10) > 0.5  # but still pretty high

    def test_all_losses_returns_zero(self):
        assert wilson_lower_bound(0, 10) == 0.0

    def test_shrinks_toward_centre(self):
        # 50/100 has lower bound below 0.5; 100/200 below 0.5 by less.
        # i.e. the shrinkage is monotone in n at fixed p̂.
        lb_100 = wilson_lower_bound(50, 100)
        lb_1000 = wilson_lower_bound(500, 1000)
        assert lb_100 < lb_1000 < 0.5

    def test_higher_z_more_conservative(self):
        # z=2.58 (≈99% one-sided) shrinks more than z=1.96 (≈97.5%).
        less_conservative = wilson_lower_bound(60, 100, z=1.96)
        more_conservative = wilson_lower_bound(60, 100, z=2.58)
        assert more_conservative < less_conservative


class TestStatsFromTrades:
    def test_empty_list(self):
        assert stats_from_trades([]) is None

    def test_all_wins_returns_none(self):
        # No losses → can't compute payoff ratio
        trades = [{"profit_ratio": 0.05}] * 5
        assert stats_from_trades(trades) is None

    def test_all_losses_returns_none(self):
        trades = [{"profit_ratio": -0.02}] * 5
        assert stats_from_trades(trades) is None

    def test_mixed_wins_and_losses(self):
        # 3 wins of +10%, 2 losses of -5% → p=0.6, b = 0.10/0.05 = 2.0
        trades = (
            [{"profit_ratio": 0.10}] * 3 + [{"profit_ratio": -0.05}] * 2
        )
        s = stats_from_trades(trades)
        assert s is not None
        assert s.n_trades == 5
        assert s.win_rate == pytest.approx(0.60, abs=1e-9)
        assert s.payoff_ratio == pytest.approx(2.0, abs=1e-9)

    def test_falls_back_to_profit_percentage(self):
        # Older backtest format uses profit_percentage (out of 100)
        trades = [{"profit_percentage": 10.0}, {"profit_percentage": -5.0}]
        s = stats_from_trades(trades)
        assert s is not None
        assert s.payoff_ratio == pytest.approx(2.0, abs=1e-9)


class TestKellyStake:
    def test_uses_proposed_when_no_stats(self):
        out = kelly_stake(equity=10_000, stats=None, proposed_stake=1500, max_stake=5000)
        assert out == 1500

    def test_uses_proposed_when_under_min_trades(self):
        s = KellyStats(win_rate=0.7, payoff_ratio=2.0, n_trades=10)
        out = kelly_stake(equity=10_000, stats=s, proposed_stake=1500, max_stake=5000)
        assert out == 1500

    def test_applies_half_kelly_with_enough_samples(self):
        # p=0.55, b=1.5, n=1000 — large enough that Wilson barely shrinks p
        # (~0.519). f* ≈ 0.198, f*/2 ≈ 0.099 → capped at 0.05.
        # stake = 10_000 * 0.05 = 500.
        s = KellyStats(win_rate=0.55, payoff_ratio=1.5, n_trades=1000)
        out = kelly_stake(equity=10_000, stats=s, proposed_stake=1500, max_stake=5000)
        assert out == pytest.approx(500.0, abs=1e-9)

    def test_respects_max_stake(self):
        s = KellyStats(win_rate=0.55, payoff_ratio=1.5, n_trades=1000)
        # Equity would suggest 500 but exchange caps at 100
        out = kelly_stake(equity=10_000, stats=s, proposed_stake=1500, max_stake=100)
        assert out == 100

    def test_marginal_edge_with_small_n_becomes_negative_under_wilson(self):
        # p̂=0.55 looks profitable but Wilson at n=100 says no edge.
        # kelly_stake should fall into the "negative edge" branch and shrink
        # to half the proposed stake.
        s = KellyStats(win_rate=0.55, payoff_ratio=1.0, n_trades=100)
        out = kelly_stake(equity=10_000, stats=s, proposed_stake=1500, max_stake=5000)
        assert out == 750  # 1500 * 0.5

    def test_negative_edge_shrinks_to_half_proposed(self):
        s = KellyStats(win_rate=0.40, payoff_ratio=1.0, n_trades=100)
        out = kelly_stake(equity=10_000, stats=s, proposed_stake=1500, max_stake=5000)
        assert out == 750  # 1500 * 0.5

    def test_zero_equity_falls_back_to_proposed(self):
        s = KellyStats(win_rate=0.60, payoff_ratio=2.0, n_trades=100)
        out = kelly_stake(equity=0, stats=s, proposed_stake=1500, max_stake=5000)
        assert out == 1500


class TestLatestStrategyStats:
    def test_missing_dir_returns_none(self, tmp_path):
        out = kelly_sizer.latest_strategy_stats("Whatever", backtest_dir=tmp_path / "nope")
        assert out is None

    def test_empty_dir_returns_none(self, tmp_path):
        out = kelly_sizer.latest_strategy_stats("Whatever", backtest_dir=tmp_path)
        assert out is None
