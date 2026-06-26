"""Focused tests for dependency-light Quant Lab models."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "strategies"))

import quant_models as qm  # noqa: E402
from quant_lab import run_quant_lab  # noqa: E402


def _prices(n: int = 420, seed: int = 1) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = 0.0004 + rng.normal(0, 0.01, n)
    px = 100 * np.exp(np.cumsum(rets))
    return pd.Series(px, index=pd.date_range("2020-01-01", periods=n, tz="UTC"))


def _frame(n: int = 420) -> pd.DataFrame:
    base = qm.log_returns(_prices(n + 1, 2)).to_numpy()
    rng = np.random.default_rng(3)
    data = {
        "SPY": base,
        "QQQ": base * 1.25 + rng.normal(0, 0.004, len(base)),
        "TLT": -base * 0.35 + rng.normal(0, 0.005, len(base)),
        "GLD": rng.normal(0.0002, 0.008, len(base)),
    }
    return pd.DataFrame(data, index=pd.date_range("2020-01-02", periods=len(base), tz="UTC"))


def test_bsm_put_call_parity():
    call = qm.bsm_price(100, 100, 0.05, 0.2, 365, "call")["price"]
    put = qm.bsm_price(100, 100, 0.05, 0.2, 365, "put")["price"]
    lhs = call - put
    rhs = 100 - 100 * math.exp(-0.05 * 365 / 365.25)
    assert abs(lhs - rhs) < 0.02


def test_gbm_seeded_positive_and_deterministic():
    prices = _prices()
    a = qm.gbm_simulation(prices, horizon_days=20, paths=500, seed=42)
    b = qm.gbm_simulation(prices, horizon_days=20, paths=500, seed=42)
    assert a["terminal"]["p50"] == b["terminal"]["p50"]
    assert a["terminal"]["p5"] > 0


def test_markowitz_weights_sum_and_cap():
    out = qm.markowitz_random_search(_frame(), max_weight=0.6, samples=1500, seed=4)
    weights = [r["weight_pct"] / 100 for r in out["max_sharpe"]["weights"]]
    assert abs(sum(weights) - 1.0) < 0.002
    assert max(weights) <= 0.602


def test_garch_volatility_is_nonnegative_and_cluster_sensitive():
    rng = np.random.default_rng(5)
    low = rng.normal(0, 0.004, 150)
    high = rng.normal(0, 0.035, 80)
    r = pd.Series(np.r_[low, high])
    out = qm.garch_11(r, horizon_days=5)
    assert out["next_daily_vol_pct"] > 0
    assert out["next_annual_vol_pct"] > out["last_daily_vol_pct"]


def test_cointegration_detects_synthetic_pair():
    rng = np.random.default_rng(6)
    x = np.cumsum(rng.normal(0, 0.01, 360)) + 5
    y = 0.7 + 1.4 * x + rng.normal(0, 0.02, 360)
    idx = pd.date_range("2021-01-01", periods=360, tz="UTC")
    out = qm.cointegration_pair(pd.Series(np.exp(y), idx), pd.Series(np.exp(x), idx))
    assert abs(out["hedge_ratio"] - 1.4) < 0.08
    assert out["adf_t_stat"] < -3


def test_hmm_splits_low_and_high_volatility_states():
    rng = np.random.default_rng(7)
    r = pd.Series(np.r_[rng.normal(0, 0.003, 140), rng.normal(0, 0.03, 140)])
    out = qm.hmm_gaussian(r, n_states=2, max_iter=30)
    vols = [s["annual_vol_pct"] for s in out["states"]]
    assert vols[1] > vols[0] * 3
    assert out["current_label"] == "high_vol"


def test_pca_recovers_dominant_factor():
    out = qm.pca_factors(_frame(), n_components=2)
    assert out["components"][0]["explained_variance_pct"] > out["components"][1]["explained_variance_pct"]
    assert out["components"][0]["explained_variance_pct"] > 40


def test_copula_tail_dependence_is_higher_for_correlated_pair():
    data = _frame()
    out = qm.copula_tail_dependence(data[["SPY", "QQQ", "GLD"]], q=0.1)
    rows = {r["pair"]: r for r in out["pairs"]}
    assert rows["SPY/QQQ"]["upper_tail"] > rows["SPY/GLD"]["upper_tail"]


def test_kelly_wrapper_matches_existing_contract():
    out = qm.kelly_from_stats(0.55, 1.5, 1000, cap=0.05)
    assert out["kelly_point_pct"] > out["kelly_wilson_pct"]
    assert out["half_kelly_capped_pct"] == 5.0


def test_quant_lab_runs_every_model_with_injected_prices():
    base = pd.Timestamp("2020-01-01", tz="UTC")
    symbols = ["SPY", "QQQ", "TLT", "GLD", "BIL"]

    def loader(sym: str, min_bars: int):
        i = symbols.index(sym)
        out = []
        px = 100.0 + i * 10
        for n in range(820):
            px *= math.exp(0.0002 * (i + 1) + 0.001 * math.sin(n / 11 + i))
            out.append((int((base + pd.Timedelta(days=n)).timestamp() * 1000), px))
        return out

    for model in ("gbm", "bsm", "markowitz", "garch", "cointegration", "hmm", "pca", "copula"):
        out = run_quant_lab(
            {"model": model, "asset": "SPY", "universe": ",".join(symbols), "lookback_days": 420},
            price_loader=loader,
        )
        assert out["model"] == model
        assert out["summary"]
        assert out["tables"]
    kelly = run_quant_lab({"model": "kelly", "win_rate": 0.55, "payoff_ratio": 1.5, "n_trades": 1000})
    assert kelly["summary"]
