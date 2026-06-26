"""Small dependency-light quant models for the dashboard Quant Lab.

The production venv intentionally does not carry scipy/statsmodels/sklearn/arch.
These implementations favor transparent, bounded computations over heavyweight
estimators. They are research diagnostics, not trading signals.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _finite(a: np.ndarray) -> np.ndarray:
    return np.asarray(a, dtype=float)[np.isfinite(a)]


def _r(x: float | np.floating | None, ndigits: int = 6) -> float | None:
    if x is None:
        return None
    y = float(x)
    if not math.isfinite(y):
        return None
    return round(y, ndigits)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def log_returns(prices: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Log returns with non-positive prices dropped before differencing."""
    clean = prices.replace([np.inf, -np.inf], np.nan).dropna()
    clean = clean[clean > 0] if isinstance(clean, pd.Series) else clean.where(clean > 0).dropna()
    return np.log(clean / clean.shift(1)).dropna()


def gbm_simulation(
    prices: pd.Series,
    horizon_days: int = 30,
    paths: int = 1000,
    seed: int = 7,
) -> dict:
    rets = _finite(log_returns(prices).to_numpy())
    if len(rets) < 30:
        raise ValueError("GBM needs at least 30 returns")
    horizon_days = int(max(1, min(horizon_days, 365)))
    paths = int(max(100, min(paths, 5000)))
    last = float(prices.dropna().iloc[-1])
    mu = float(np.mean(rets) * TRADING_DAYS)
    sigma = float(np.std(rets, ddof=1) * math.sqrt(TRADING_DAYS))
    rng = np.random.default_rng(seed)
    dt = 1.0 / TRADING_DAYS
    z = rng.standard_normal((horizon_days, paths))
    increments = (mu - 0.5 * sigma * sigma) * dt + sigma * math.sqrt(dt) * z
    terminal = last * np.exp(np.cumsum(increments, axis=0))[-1]
    pct = np.percentile(terminal, [5, 25, 50, 75, 95])
    return {
        "spot": _r(last, 4),
        "annual_drift": _r(mu, 6),
        "annual_vol": _r(sigma, 6),
        "horizon_days": horizon_days,
        "paths": paths,
        "seed": seed,
        "terminal": {
            "p5": _r(pct[0], 4),
            "p25": _r(pct[1], 4),
            "p50": _r(pct[2], 4),
            "p75": _r(pct[3], 4),
            "p95": _r(pct[4], 4),
        },
        "median_return_pct": _r((pct[2] / last - 1.0) * 100, 4),
    }


def bsm_price(
    spot: float,
    strike: float,
    rate: float,
    vol: float,
    days: int,
    option_type: str = "call",
    dividend_yield: float = 0.0,
) -> dict:
    option_type = option_type.lower()
    if option_type not in ("call", "put"):
        raise ValueError("option_type must be call or put")
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    t = max(float(days), 0.0) / 365.25
    vol = max(float(vol), 0.0)
    rate = float(rate)
    q = float(dividend_yield)
    if t <= 0 or vol <= 0:
        intrinsic = max(spot - strike, 0.0) if option_type == "call" else max(strike - spot, 0.0)
        return {"price": _r(intrinsic, 4), "delta": 1.0 if intrinsic > 0 and option_type == "call" else 0.0,
                "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
    sqrt_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + (rate - q + 0.5 * vol * vol) * t) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    df_r = math.exp(-rate * t)
    df_q = math.exp(-q * t)
    if option_type == "call":
        price = spot * df_q * _norm_cdf(d1) - strike * df_r * _norm_cdf(d2)
        delta = df_q * _norm_cdf(d1)
        theta = (-(spot * df_q * _norm_pdf(d1) * vol) / (2 * sqrt_t)
                 - rate * strike * df_r * _norm_cdf(d2)
                 + q * spot * df_q * _norm_cdf(d1))
        rho = strike * t * df_r * _norm_cdf(d2)
    else:
        price = strike * df_r * _norm_cdf(-d2) - spot * df_q * _norm_cdf(-d1)
        delta = -df_q * _norm_cdf(-d1)
        theta = (-(spot * df_q * _norm_pdf(d1) * vol) / (2 * sqrt_t)
                 + rate * strike * df_r * _norm_cdf(-d2)
                 - q * spot * df_q * _norm_cdf(-d1))
        rho = -strike * t * df_r * _norm_cdf(-d2)
    gamma = df_q * _norm_pdf(d1) / (spot * vol * sqrt_t)
    vega = spot * df_q * _norm_pdf(d1) * sqrt_t
    return {
        "price": _r(price, 4),
        "delta": _r(delta, 6),
        "gamma": _r(gamma, 6),
        "vega": _r(vega / 100.0, 6),  # per 1 vol point
        "theta": _r(theta / 365.25, 6),  # per calendar day
        "rho": _r(rho / 100.0, 6),  # per 1 rate point
        "d1": _r(d1, 6),
        "d2": _r(d2, 6),
    }


def _portfolio_stats(weights: np.ndarray, mu: np.ndarray, cov: np.ndarray, rf: float) -> dict:
    ret = float(weights @ mu)
    vol = float(math.sqrt(max(weights @ cov @ weights, 0.0)))
    sharpe = (ret - rf) / vol if vol > 0 else 0.0
    return {"return": ret, "vol": vol, "sharpe": sharpe}


def markowitz_random_search(
    returns: pd.DataFrame,
    risk_free_rate: float = 0.0,
    max_weight: float = 0.35,
    samples: int = 8000,
    seed: int = 11,
) -> dict:
    data = returns.dropna()
    if data.shape[0] < 60 or data.shape[1] < 2:
        raise ValueError("Markowitz needs at least 60 rows and 2 assets")
    assets = list(data.columns)
    n = len(assets)
    max_weight = float(max(max_weight, 1.0 / n))
    max_weight = float(min(max_weight, 1.0))
    samples = int(max(1000, min(samples, 50_000)))
    mu = data.mean().to_numpy() * TRADING_DAYS
    cov = data.cov().to_numpy() * TRADING_DAYS
    rng = np.random.default_rng(seed)

    best_sharpe: tuple[float, np.ndarray, dict] | None = None
    best_vol: tuple[float, np.ndarray, dict] | None = None
    tries = 0
    accepted = 0
    target = samples
    while accepted < target and tries < target * 20:
        tries += 1
        w = rng.dirichlet(np.ones(n))
        if np.max(w) > max_weight:
            continue
        st = _portfolio_stats(w, mu, cov, risk_free_rate)
        accepted += 1
        if best_sharpe is None or st["sharpe"] > best_sharpe[0]:
            best_sharpe = (st["sharpe"], w, st)
        if best_vol is None or st["vol"] < best_vol[0]:
            best_vol = (st["vol"], w, st)
    if best_sharpe is None or best_vol is None:
        w = np.full(n, 1.0 / n)
        st = _portfolio_stats(w, mu, cov, risk_free_rate)
        best_sharpe = (st["sharpe"], w, st)
        best_vol = (st["vol"], w, st)
    return {
        "assets": assets,
        "accepted_samples": accepted,
        "risk_free_rate": _r(risk_free_rate, 6),
        "max_weight": _r(max_weight, 4),
        "max_sharpe": _portfolio_payload(assets, best_sharpe[1], best_sharpe[2]),
        "min_vol": _portfolio_payload(assets, best_vol[1], best_vol[2]),
    }


def _portfolio_payload(assets: list[str], weights: np.ndarray, stats: dict) -> dict:
    return {
        "annual_return_pct": _r(stats["return"] * 100, 4),
        "annual_vol_pct": _r(stats["vol"] * 100, 4),
        "sharpe": _r(stats["sharpe"], 4),
        "weights": [{"asset": a, "weight_pct": _r(float(w) * 100, 3)} for a, w in zip(assets, weights)],
    }


def garch_11(returns: pd.Series, horizon_days: int = 10) -> dict:
    r = _finite(returns.to_numpy())
    if len(r) < 80:
        raise ValueError("GARCH needs at least 80 returns")
    eps = r - float(np.mean(r))
    var = float(np.var(eps, ddof=1))
    if var <= 0:
        raise ValueError("GARCH needs non-constant returns")

    def fit_score(alpha: float, beta: float) -> tuple[float, float, np.ndarray]:
        if alpha <= 0 or beta < 0 or alpha + beta >= 0.995:
            return (float("inf"), 0.0, np.array([]))
        omega = max(var * (1.0 - alpha - beta), 1e-12)
        h = np.empty_like(eps)
        h[0] = var
        for i in range(1, len(eps)):
            h[i] = omega + alpha * eps[i - 1] ** 2 + beta * h[i - 1]
            if h[i] <= 0 or not math.isfinite(float(h[i])):
                return (float("inf"), omega, h)
        nll = 0.5 * float(np.sum(np.log(h) + eps * eps / h))
        return (nll, omega, h)

    best = (float("inf"), 0.08, 0.88, var * 0.04, np.full_like(eps, var))
    for alpha in np.linspace(0.02, 0.24, 12):
        for beta in np.linspace(0.50, 0.97, 16):
            nll, omega, h = fit_score(float(alpha), float(beta))
            if nll < best[0]:
                best = (nll, float(alpha), float(beta), omega, h)
    ba, bb = best[1], best[2]
    for alpha in np.linspace(max(0.005, ba - 0.04), min(0.35, ba + 0.04), 17):
        for beta in np.linspace(max(0.0, bb - 0.08), min(0.99, bb + 0.08), 25):
            nll, omega, h = fit_score(float(alpha), float(beta))
            if nll < best[0]:
                best = (nll, float(alpha), float(beta), omega, h)

    _, alpha, beta, omega, h = best
    next_var = omega + alpha * eps[-1] ** 2 + beta * h[-1]
    horizon_days = int(max(1, min(horizon_days, 252)))
    forecasts = []
    v = next_var
    for _ in range(horizon_days):
        forecasts.append(v)
        v = omega + (alpha + beta) * v
    return {
        "omega": _r(omega, 12),
        "alpha": _r(alpha, 6),
        "beta": _r(beta, 6),
        "persistence": _r(alpha + beta, 6),
        "last_daily_vol_pct": _r(math.sqrt(float(h[-1])) * 100, 4),
        "next_daily_vol_pct": _r(math.sqrt(float(next_var)) * 100, 4),
        "next_annual_vol_pct": _r(math.sqrt(float(next_var) * TRADING_DAYS) * 100, 4),
        "horizon_avg_annual_vol_pct": _r(math.sqrt(float(np.mean(forecasts)) * TRADING_DAYS) * 100, 4),
    }


def cointegration_pair(y: pd.Series, x: pd.Series) -> dict:
    df = pd.concat([y, x], axis=1).dropna()
    if len(df) < 80:
        raise ValueError("cointegration needs at least 80 overlapping prices")
    yy = np.log(df.iloc[:, 0].to_numpy(dtype=float))
    xx = np.log(df.iloc[:, 1].to_numpy(dtype=float))
    X = np.column_stack([np.ones(len(xx)), xx])
    intercept, beta = np.linalg.lstsq(X, yy, rcond=None)[0]
    spread = yy - (intercept + beta * xx)
    sd = float(np.std(spread, ddof=1))
    z = (float(spread[-1]) - float(np.mean(spread))) / sd if sd > 0 else 0.0

    ds = np.diff(spread)
    lag = spread[:-1]
    A = np.column_stack([np.ones(len(lag)), lag])
    coef = np.linalg.lstsq(A, ds, rcond=None)[0]
    resid = ds - A @ coef
    dof = max(len(ds) - 2, 1)
    s2 = float(np.sum(resid ** 2) / dof)
    inv = np.linalg.pinv(A.T @ A)
    se_phi = math.sqrt(max(s2 * inv[1, 1], 1e-18))
    phi = float(coef[1])
    adf_t = phi / se_phi
    half_life = -math.log(2.0) / phi if phi < 0 else None
    return {
        "hedge_ratio": _r(float(beta), 6),
        "intercept": _r(float(intercept), 6),
        "spread_z": _r(z, 4),
        "adf_t_stat": _r(adf_t, 4),
        "half_life_days": _r(half_life, 2),
        "spread_mean": _r(float(np.mean(spread)), 6),
        "spread_std": _r(sd, 6),
    }


def hmm_gaussian(returns: pd.Series, n_states: int = 2, max_iter: int = 40, seed: int = 13) -> dict:
    x = _finite(returns.to_numpy()) * 100.0
    if len(x) < 80:
        raise ValueError("HMM needs at least 80 returns")
    n_states = int(max(2, min(n_states, 3)))
    n = len(x)
    qs = np.linspace(0.15, 0.85, n_states)
    means = np.quantile(x, qs)
    vars_ = np.full(n_states, max(float(np.var(x)), 1e-6))
    trans = np.full((n_states, n_states), 0.08 / max(n_states - 1, 1))
    np.fill_diagonal(trans, 0.92)
    start = np.full(n_states, 1.0 / n_states)

    def logsumexp(a: np.ndarray, axis: int | None = None) -> np.ndarray:
        m = np.max(a, axis=axis, keepdims=True)
        return np.squeeze(m + np.log(np.sum(np.exp(a - m), axis=axis, keepdims=True)), axis=axis)

    last_ll = -float("inf")
    for _ in range(max_iter):
        log_emit = np.column_stack([
            -0.5 * (np.log(2 * math.pi * vars_[k]) + (x - means[k]) ** 2 / vars_[k])
            for k in range(n_states)
        ])
        log_trans = np.log(np.maximum(trans, 1e-12))
        la = np.empty((n, n_states))
        la[0] = np.log(start) + log_emit[0]
        for t in range(1, n):
            la[t] = log_emit[t] + logsumexp(la[t - 1][:, None] + log_trans, axis=0)
        lb = np.zeros((n, n_states))
        for t in range(n - 2, -1, -1):
            lb[t] = logsumexp(log_trans + log_emit[t + 1] + lb[t + 1], axis=1)
        ll = float(logsumexp(la[-1], axis=0))
        gamma = np.exp(la + lb - ll)
        xi_sum = np.zeros((n_states, n_states))
        for t in range(n - 1):
            xi = la[t][:, None] + log_trans + log_emit[t + 1] + lb[t + 1] - ll
            xi_sum += np.exp(xi)
        start = gamma[0] / max(float(np.sum(gamma[0])), 1e-12)
        trans = xi_sum / np.maximum(xi_sum.sum(axis=1, keepdims=True), 1e-12)
        weights = np.maximum(gamma.sum(axis=0), 1e-12)
        means = (gamma * x[:, None]).sum(axis=0) / weights
        vars_ = (gamma * (x[:, None] - means) ** 2).sum(axis=0) / weights
        vars_ = np.maximum(vars_, 1e-6)
        if abs(ll - last_ll) < 1e-5:
            break
        last_ll = ll

    order = np.argsort(vars_)
    gamma = gamma[:, order]
    means = means[order]
    vars_ = vars_[order]
    trans = trans[order][:, order]
    current_idx = int(np.argmax(gamma[-1]))
    states = []
    for i in range(n_states):
        states.append({
            "state": int(i),
            "label": ["low_vol", "mid_vol", "high_vol"][i if n_states == 3 else (0 if i == 0 else 2)],
            "mean_daily_return_pct": _r(float(means[i]), 4),
            "annual_vol_pct": _r(math.sqrt(float(vars_[i])) / 100.0 * math.sqrt(TRADING_DAYS) * 100, 4),
            "current_probability_pct": _r(float(gamma[-1, i]) * 100, 2),
        })
    return {
        "states": states,
        "current_state": current_idx,
        "current_label": states[current_idx]["label"],
        "transition": [[_r(v, 4) for v in row] for row in trans],
        "log_likelihood": _r(last_ll, 4),
    }


def pca_factors(returns: pd.DataFrame, n_components: int = 3) -> dict:
    data = returns.dropna()
    if data.shape[0] < 60 or data.shape[1] < 2:
        raise ValueError("PCA needs at least 60 rows and 2 assets")
    assets = list(data.columns)
    z = (data - data.mean()) / data.std(ddof=1).replace(0, np.nan)
    z = z.dropna(axis=1).dropna()
    x = z.to_numpy(dtype=float)
    _, s, vt = np.linalg.svd(x, full_matrices=False)
    eig = (s ** 2) / max(len(x) - 1, 1)
    ratio = eig / np.sum(eig)
    n_components = int(max(1, min(n_components, len(ratio), len(assets))))
    comps = []
    for i in range(n_components):
        comps.append({
            "component": i + 1,
            "explained_variance_pct": _r(float(ratio[i]) * 100, 3),
            "loadings": [{"asset": a, "loading": _r(float(vt[i, j]), 4)}
                         for j, a in enumerate(list(z.columns))],
        })
    return {"components": comps}


def copula_tail_dependence(returns: pd.DataFrame, q: float = 0.05) -> dict:
    data = returns.dropna()
    if data.shape[0] < 80 or data.shape[1] < 2:
        raise ValueError("copula needs at least 80 rows and 2 assets")
    q = float(min(max(q, 0.01), 0.20))
    ranks = data.rank(method="average") / (len(data) + 1.0)
    assets = list(ranks.columns)
    rows = []
    for i, a in enumerate(assets):
        for b in assets[i + 1:]:
            ua = ranks[a].to_numpy()
            ub = ranks[b].to_numpy()
            lower = float(np.mean((ua <= q) & (ub <= q)) / q)
            upper = float(np.mean((ua >= 1 - q) & (ub >= 1 - q)) / q)
            spear = float(np.corrcoef(ua, ub)[0, 1])
            rows.append({
                "pair": f"{a}/{b}",
                "lower_tail": _r(lower, 4),
                "upper_tail": _r(upper, 4),
                "spearman": _r(spear, 4),
            })
    return {"tail_q": q, "pairs": rows}


def kelly_from_stats(win_rate: float, payoff_ratio: float, n_trades: int, cap: float = 0.05) -> dict:
    from kelly_sizer import KellyStats

    s = KellyStats(win_rate=float(win_rate), payoff_ratio=float(payoff_ratio), n_trades=int(n_trades))
    point = s.kelly_fraction(use_lower_bound=False)
    shrunk = s.kelly_fraction(use_lower_bound=True)
    half = s.half_kelly_clamped(cap=float(cap))
    return {
        "win_rate": _r(float(win_rate), 4),
        "payoff_ratio": _r(float(payoff_ratio), 4),
        "n_trades": int(n_trades),
        "kelly_point_pct": _r(point * 100, 4),
        "kelly_wilson_pct": _r(shrunk * 100, 4),
        "half_kelly_capped_pct": _r(half * 100, 4),
        "cap_pct": _r(float(cap) * 100, 4),
    }


def weights_table(payload: dict, key: str = "max_sharpe") -> list[dict]:
    return list(payload[key]["weights"])


def pair_symbols(universe: Iterable[str]) -> tuple[str, str]:
    vals = [str(x).upper().strip() for x in universe if str(x).strip()]
    if len(vals) < 2:
        raise ValueError("need at least two symbols")
    return vals[0], vals[1]
