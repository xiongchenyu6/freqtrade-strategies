"""Tests for the crypto fear-driven accumulator, on REAL Binance BTC daily data."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crypto_data import FngSeries  # noqa: E402
from run_accumulation import run  # noqa: E402


@pytest.fixture(scope="module")
def smart():
    return run("smart")


@pytest.fixture(scope="module")
def naive():
    return run("naive")


def test_naive_has_no_boosts(naive):
    assert naive.buys > 0
    assert naive.fear_buys == 0
    assert naive.dip_buys == 0


def test_smart_and_naive_same_scheduled_count(smart, naive):
    # Both buy on every interval boundary; smart just buys *more* per fear/dip event,
    # not more often. Same number of scheduled buys.
    assert smart.buys == naive.buys


def test_smart_buys_harder_in_fear_and_dips(smart):
    assert smart.fear_buys > 0
    assert smart.dip_buys > 0
    assert smart.invested_usd > 0
    assert smart.coin_qty > 0


def test_smart_invests_more_than_naive(smart, naive):
    # Fear/dip boosts deploy extra capital → smart invests strictly more.
    assert smart.invested_usd > naive.invested_usd


def test_smart_achieves_lower_cost_basis(smart, naive):
    # The whole point: buying harder in fear lowers the average cost per BTC.
    assert smart.avg_cost() < naive.avg_cost()


def test_accumulation_is_profitable_over_full_history(smart):
    # Long-term BTC bull thesis — DCA should be well in the green over 2017-2026.
    assert smart.roi() > 0


class TestFngSeries:
    def test_known_date(self):
        import datetime as dt

        fng = FngSeries()
        assert len(fng) > 0
        # 2026-04-17 is the last row in data/fng_history.csv (value 21, Extreme Fear)
        assert fng.value_on(dt.date(2026, 4, 17)) == 21

    def test_missing_date_defaults_neutral(self):
        import datetime as dt

        fng = FngSeries(default=50)
        assert fng.value_on(dt.date(1990, 1, 1)) == 50
