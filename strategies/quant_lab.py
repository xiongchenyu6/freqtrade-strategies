"""Quant Lab runner facade.

This module turns user-submitted model params into a bounded JSON payload that
fits quant.backtest_results.metrics. It deliberately does not place trades.
"""

from __future__ import annotations

from datetime import timezone
from typing import Callable

import pandas as pd

import quant_models as qm

DEFAULT_UNIVERSE = ("SPY", "QQQ", "TLT", "GLD", "BIL")
MODELS = {"gbm", "bsm", "markowitz", "garch", "cointegration", "hmm", "pca", "kelly", "copula"}


def _symbol(s: object, default: str = "SPY") -> str:
    out = str(s or default).upper().strip()
    if not out.isalnum() or len(out) > 8:
        raise ValueError(f"invalid symbol {out!r}")
    return out


def _universe(params: dict, min_len: int = 2) -> list[str]:
    raw = params.get("universe") or params.get("assets") or ",".join(DEFAULT_UNIVERSE)
    if isinstance(raw, str):
        vals = [x.strip().upper() for x in raw.split(",")]
    else:
        vals = [str(x).strip().upper() for x in raw]
    out: list[str] = []
    for v in vals:
        if not v:
            continue
        out.append(_symbol(v))
    out = list(dict.fromkeys(out))
    if len(out) < min_len:
        raise ValueError(f"need at least {min_len} symbols")
    if len(out) > 12:
        raise ValueError("universe supports at most 12 symbols")
    return out


def _int(params: dict, key: str, default: int, lo: int, hi: int) -> int:
    v = int(params.get(key, default))
    if not (lo <= v <= hi):
        raise ValueError(f"{key} must be in [{lo}, {hi}]")
    return v


def _float(params: dict, key: str, default: float, lo: float, hi: float) -> float:
    v = float(params.get(key, default))
    if not (lo <= v <= hi):
        raise ValueError(f"{key} must be in [{lo}, {hi}]")
    return v


def _price_frame(
    symbols: list[str],
    lookback_days: int,
    price_loader: Callable[[str, int], list[tuple[int, float]]] | None = None,
) -> pd.DataFrame:
    if price_loader is None:
        import findata
        price_loader = findata.closes_any
    min_bars = max(lookback_days + 5, 420)
    series = {}
    for sym in symbols:
        bars = price_loader(sym, min_bars)
        if not bars:
            raise ValueError(f"no daily data for {sym}")
        idx = pd.to_datetime([int(ts) for ts, _ in bars], unit="ms", utc=True)
        series[sym] = pd.Series([float(px) for _, px in bars], index=idx, name=sym)
    frame = pd.concat(series.values(), axis=1, join="inner").dropna()
    if len(frame) < 252:
        raise ValueError("need at least 252 overlapping daily bars")
    return frame.tail(lookback_days)


def _period(frame: pd.DataFrame) -> tuple[str, str]:
    a = frame.index[0].tz_convert(timezone.utc).date().isoformat()
    b = frame.index[-1].tz_convert(timezone.utc).date().isoformat()
    return a, b


def _summary(label: str, value: object, unit: str = "") -> dict:
    return {"label": label, "value": value, "unit": unit}


def _table(name: str, rows: list[dict]) -> dict:
    return {"name": name, "rows": rows}


def _base(model: str, assets: list[str], period_start: str | None, period_end: str | None, params: dict) -> dict:
    return {
        "kind": "quant_lab",
        "model": model,
        "assets": assets,
        "period_start": period_start,
        "period_end": period_end,
        "return_pct": 0.0,
        "max_dd_pct": None,
        "sharpe": None,
        "calmar": None,
        "trades": 0,
        "config": params,
        "summary": [],
        "tables": [],
        "notes": [
            "Research diagnostic only; it does not place trades or create live signals.",
            "Historical fit is not a forecast guarantee.",
        ],
    }


def run_quant_lab(
    params: dict,
    price_loader: Callable[[str, int], list[tuple[int, float]]] | None = None,
) -> dict:
    model = str(params.get("model", "markowitz")).lower().strip()
    if model not in MODELS:
        raise ValueError(f"model must be one of {sorted(MODELS)}")
    lookback = _int(params, "lookback_days", 756, 252, 4000)
    horizon = _int(params, "horizon_days", 30, 1, 365)
    seed = _int(params, "seed", 7, 0, 1_000_000)
    rf = _float(params, "risk_free_rate", 0.04, -0.05, 0.25)

    if model == "kelly":
        win_rate = _float(params, "win_rate", 0.55, 0.0, 1.0)
        payoff_ratio = _float(params, "payoff_ratio", 1.5, 0.0, 20.0)
        n_trades = _int(params, "n_trades", 1000, 0, 100_000)
        cap = _float(params, "cap", 0.05, 0.0, 1.0)
        payload = qm.kelly_from_stats(win_rate, payoff_ratio, n_trades, cap)
        out = _base(model, [], None, None, {**params, "model": model})
        out["return_pct"] = payload["half_kelly_capped_pct"]
        out["summary"] = [
            _summary("Half-Kelly capped", payload["half_kelly_capped_pct"], "% of equity"),
            _summary("Wilson Kelly", payload["kelly_wilson_pct"], "%"),
            _summary("Point Kelly", payload["kelly_point_pct"], "%"),
        ]
        out["tables"] = [_table("Kelly sizing", [payload])]
        return out

    if model in {"gbm", "bsm", "garch", "hmm"}:
        assets = [_symbol(params.get("asset"), "SPY")]
    elif model == "cointegration":
        assets = _universe(params, min_len=2)[:2]
    else:
        assets = _universe(params, min_len=2)

    prices = _price_frame(assets, lookback, price_loader=price_loader)
    period_start, period_end = _period(prices)
    rets = qm.log_returns(prices)
    out = _base(model, assets, period_start, period_end, {**params, "model": model, "assets": assets})

    if model == "gbm":
        paths = _int(params, "paths", 1000, 100, 5000)
        payload = qm.gbm_simulation(prices[assets[0]], horizon, paths, seed)
        out["return_pct"] = payload["median_return_pct"]
        out["summary"] = [
            _summary("Spot", payload["spot"], "USD"),
            _summary("Annual drift", round(payload["annual_drift"] * 100, 4), "%"),
            _summary("Annual volatility", round(payload["annual_vol"] * 100, 4), "%"),
            _summary("Median horizon return", payload["median_return_pct"], "%"),
        ]
        out["tables"] = [_table("Terminal price percentiles", [
            {"percentile": k.upper(), "price": v} for k, v in payload["terminal"].items()
        ])]
        return out

    if model == "bsm":
        asset = assets[0]
        spot = float(prices[asset].iloc[-1])
        hist_vol = float(rets[asset].std(ddof=1) * (252 ** 0.5))
        strike = float(params.get("strike") or round(spot, 2))
        vol = _float(params, "vol", hist_vol, 0.001, 5.0)
        days = _int(params, "days_to_expiry", horizon, 1, 1095)
        div = _float(params, "dividend_yield", 0.0, 0.0, 0.25)
        call = qm.bsm_price(spot, strike, rf, vol, days, "call", div)
        put = qm.bsm_price(spot, strike, rf, vol, days, "put", div)
        out["summary"] = [
            _summary("Spot", round(spot, 4), "USD"),
            _summary("Strike", round(strike, 4), "USD"),
            _summary("Input vol", round(vol * 100, 4), "%"),
            _summary("Call price", call["price"], "USD"),
            _summary("Put price", put["price"], "USD"),
        ]
        out["tables"] = [_table("BSM option values", [
            {"type": "call", **call},
            {"type": "put", **put},
        ])]
        return out

    if model == "markowitz":
        max_weight = _float(params, "max_weight", 0.35, 0.05, 1.0)
        samples = _int(params, "samples", 8000, 1000, 50_000)
        payload = qm.markowitz_random_search(rets, rf, max_weight, samples, seed)
        out["return_pct"] = payload["max_sharpe"]["annual_return_pct"]
        out["sharpe"] = payload["max_sharpe"]["sharpe"]
        out["summary"] = [
            _summary("Max-Sharpe return", payload["max_sharpe"]["annual_return_pct"], "% annual"),
            _summary("Max-Sharpe volatility", payload["max_sharpe"]["annual_vol_pct"], "% annual"),
            _summary("Max-Sharpe", payload["max_sharpe"]["sharpe"], ""),
            _summary("Accepted samples", payload["accepted_samples"], ""),
        ]
        out["tables"] = [
            _table("Max-Sharpe weights", payload["max_sharpe"]["weights"]),
            _table("Min-vol weights", payload["min_vol"]["weights"]),
        ]
        return out

    if model == "garch":
        payload = qm.garch_11(rets[assets[0]], horizon)
        out["summary"] = [
            _summary("Next daily vol", payload["next_daily_vol_pct"], "%"),
            _summary("Next annual vol", payload["next_annual_vol_pct"], "%"),
            _summary("Persistence", payload["persistence"], "alpha+beta"),
            _summary("Horizon avg annual vol", payload["horizon_avg_annual_vol_pct"], "%"),
        ]
        out["tables"] = [_table("GARCH(1,1)", [payload])]
        return out

    if model == "cointegration":
        payload = qm.cointegration_pair(prices[assets[0]], prices[assets[1]])
        out["summary"] = [
            _summary("Pair", f"{assets[0]}/{assets[1]}", ""),
            _summary("Hedge ratio", payload["hedge_ratio"], ""),
            _summary("Spread z-score", payload["spread_z"], ""),
            _summary("Half-life", payload["half_life_days"], "days"),
            _summary("ADF-style t-stat", payload["adf_t_stat"], ""),
        ]
        out["tables"] = [_table("Cointegration pair", [payload])]
        return out

    if model == "hmm":
        states = _int(params, "states", 2, 2, 3)
        payload = qm.hmm_gaussian(rets[assets[0]], states, seed=seed)
        out["summary"] = [
            _summary("Current regime", payload["current_label"], ""),
            _summary("Current state", payload["current_state"], ""),
            _summary("Log likelihood", payload["log_likelihood"], ""),
        ]
        out["tables"] = [
            _table("Regime states", payload["states"]),
            _table("Transition matrix", [
                {"from_state": i, **{f"to_{j}": v for j, v in enumerate(row)}}
                for i, row in enumerate(payload["transition"])
            ]),
        ]
        return out

    if model == "pca":
        comps = _int(params, "components", 3, 1, min(6, len(assets)))
        payload = qm.pca_factors(rets, comps)
        rows = []
        for comp in payload["components"]:
            for loading in comp["loadings"]:
                rows.append({
                    "component": comp["component"],
                    "explained_variance_pct": comp["explained_variance_pct"],
                    **loading,
                })
        out["summary"] = [
            _summary("PC1 explained variance", payload["components"][0]["explained_variance_pct"], "%"),
            _summary("Components", len(payload["components"]), ""),
            _summary("Assets", len(assets), ""),
        ]
        out["tables"] = [_table("PCA loadings", rows)]
        return out

    if model == "copula":
        q = _float(params, "tail_q", 0.05, 0.01, 0.20)
        payload = qm.copula_tail_dependence(rets, q)
        max_upper = max((row["upper_tail"] for row in payload["pairs"]), default=0)
        max_lower = max((row["lower_tail"] for row in payload["pairs"]), default=0)
        out["summary"] = [
            _summary("Tail quantile", payload["tail_q"], ""),
            _summary("Max lower tail", max_lower, ""),
            _summary("Max upper tail", max_upper, ""),
            _summary("Pairs", len(payload["pairs"]), ""),
        ]
        out["tables"] = [_table("Pair tail dependence", payload["pairs"])]
        return out

    raise AssertionError(f"unhandled model {model}")
