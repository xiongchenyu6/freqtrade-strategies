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
)


class TestKellyStats:
    def test_classic_kelly_formula(self):
        # p=0.60, b=2.0 → f* = (0.6*2 - 0.4)/2 = 0.40
        s = KellyStats(win_rate=0.60, payoff_ratio=2.0, n_trades=100)
        assert s.kelly_fraction() == pytest.approx(0.40, abs=1e-9)

    def test_negative_edge_clamps_to_zero(self):
        # p=0.40, b=1.0 → f* = (0.4 - 0.6)/1 = -0.20  → clamp to 0
        s = KellyStats(win_rate=0.40, payoff_ratio=1.0, n_trades=100)
        assert s.kelly_fraction() == 0.0

    def test_half_kelly_is_half(self):
        s = KellyStats(win_rate=0.60, payoff_ratio=2.0, n_trades=100)
        # f*/2 = 0.20, well under default 5% cap → expect 0.05 (the cap wins)
        assert s.half_kelly_clamped() == pytest.approx(0.05, abs=1e-9)

    def test_half_kelly_under_cap_returns_raw_half(self):
        # p=0.55, b=1.0 → f* = 0.10; f*/2 = 0.05; cap=0.05 — exactly at cap
        s = KellyStats(win_rate=0.55, payoff_ratio=1.0, n_trades=100)
        assert s.half_kelly_clamped(cap=0.10) == pytest.approx(0.05, abs=1e-9)

    def test_cap_clamps_aggressive_kelly(self):
        # Suspiciously bullish stats: p=0.9, b=5.0 → f* = (4.5-0.1)/5 = 0.88
        # Half-Kelly would be 0.44 — cap pulls back to 0.05
        s = KellyStats(win_rate=0.90, payoff_ratio=5.0, n_trades=100)
        assert s.half_kelly_clamped(cap=0.05) == pytest.approx(0.05, abs=1e-9)

    def test_zero_payoff_returns_zero(self):
        s = KellyStats(win_rate=0.60, payoff_ratio=0.0, n_trades=100)
        assert s.kelly_fraction() == 0.0


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
        # p=0.55, b=1.5 → f* = (0.55*1.5 - 0.45)/1.5 = 0.25
        # f*/2 = 0.125, capped at 0.05 → stake = 10_000 * 0.05 = 500
        s = KellyStats(win_rate=0.55, payoff_ratio=1.5, n_trades=100)
        out = kelly_stake(equity=10_000, stats=s, proposed_stake=1500, max_stake=5000)
        assert out == pytest.approx(500.0, abs=1e-9)

    def test_respects_max_stake(self):
        s = KellyStats(win_rate=0.55, payoff_ratio=1.5, n_trades=100)
        # Equity would suggest 500 but exchange caps at 100
        out = kelly_stake(equity=10_000, stats=s, proposed_stake=1500, max_stake=100)
        assert out == 100

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
