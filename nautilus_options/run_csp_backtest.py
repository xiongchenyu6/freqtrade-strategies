"""Backtest BTC put-selling on FREE Tardis Deribit chains + real BTC spot, comparing:
  - naked  : cash-secured put (collateral = strike)
  - spread : bull put spread (sell OTM put, buy a further-OTM put as tail hedge;
             collateral = width = defined risk)
  - fng    : naked CSP but skip selling when Fear&Greed >= 80 (don't sell into euphoria
             right before crashes)

Settlement vs real BTC spot at expiry. Return is on collateral, compounded monthly.

Run: nautilus_equity/.venv/bin/python nautilus_options/run_csp_backtest.py
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_CHAINS = _ROOT / "data" / "deribit_chains"
_BTC = _ROOT / "user_data" / "data" / "binance" / "BTC_USDT-1d.feather"
_FNG = _ROOT / "data" / "fng_history.csv"

MIN_DAYS, MAX_DAYS = 5, 30
MIN_OTM, MAX_OTM = 0.10, 0.25
HEDGE_BELOW = 0.15  # long put ~15% below the short strike
FNG_GREED = 80


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _btc_spot():
    df = pd.read_feather(_BTC)
    return {d.strftime("%Y-%m-%d"): float(c) for d, c in zip(df["date"], df["close"])}


def _fng():
    d = {}
    if _FNG.exists():
        for r in csv.DictReader(open(_FNG)):
            try:
                d[r["date"]] = int(r["value"])
            except (KeyError, ValueError):
                pass
    return d


def _spot_on_or_before(spot, day):
    for back in range(7):
        k = (day - dt.timedelta(days=back)).strftime("%Y-%m-%d")
        if k in spot:
            return spot[k]
    return None


def _select_short(rows, snap_dt, spot):
    best = None
    for r in rows:
        bid = _f(r.get("bid_price"))
        strike = _f(r.get("strike_price"))
        exp_us = _f(r.get("expiration"))
        if not bid or bid <= 0 or not strike or not exp_us:
            continue
        exp = dt.datetime.fromtimestamp(exp_us / 1e6, tz=dt.timezone.utc)
        days = (exp - snap_dt).total_seconds() / 86400
        if days < MIN_DAYS or days > MAX_DAYS:
            continue
        otm = (spot - strike) / spot
        if otm < MIN_OTM or otm > MAX_OTM:
            continue
        prem = bid * spot
        ann = (prem / strike) * (365 / days) * 100
        oi = _f(r.get("open_interest")) or 0
        iv = (_f(r.get("mark_iv")) or 0) / 100
        score = ann * (1 + min(oi / 100, 1.0)) - iv * 20
        c = {"strike": strike, "days": days, "prem": prem, "ann": ann,
             "exp": exp, "exp_us": exp_us, "score": score}
        if best is None or score > best["score"]:
            best = c
    return best


def _hedge_put(rows, short, spot):
    """Cheapest-suitable long put: same expiry, strike closest to short*(1-HEDGE_BELOW)."""
    target = short["strike"] * (1 - HEDGE_BELOW)
    best = None
    for r in rows:
        strike = _f(r.get("strike_price"))
        exp_us = _f(r.get("expiration"))
        if not strike or exp_us != short["exp_us"] or strike >= short["strike"]:
            continue
        ask = _f(r.get("ask_price")) or _f(r.get("mark_price"))
        if not ask or ask <= 0:
            continue
        cost = ask * spot
        if best is None or abs(strike - target) < abs(best["strike"] - target):
            best = {"strike": strike, "cost": cost}
    return best


def _run(mode, files, spot, fng):
    cap = 100_000.0
    eq = [cap]
    trades = []
    for fp in files:
        rows = list(csv.DictReader(open(fp)))
        if not rows:
            continue
        snap_us = _f(rows[0].get("timestamp"))
        snap_spot = _f(rows[0].get("underlying_price"))
        if not snap_us or not snap_spot:
            continue
        snap_dt = dt.datetime.fromtimestamp(snap_us / 1e6, tz=dt.timezone.utc)

        if mode == "fng" and fng.get(snap_dt.strftime("%Y-%m-%d"), 50) >= FNG_GREED:
            continue  # skip selling into euphoria

        short = _select_short(rows, snap_dt, snap_spot)
        if not short:
            continue
        spot_exp = _spot_on_or_before(spot, short["exp"].date())
        if spot_exp is None:
            continue

        if mode == "spread":
            hedge = _hedge_put(rows, short, snap_spot)
            if not hedge:
                continue
            width = short["strike"] - hedge["strike"]
            net = short["prem"] - hedge["cost"]
            if width <= 0 or net <= 0:
                continue
            if spot_exp >= short["strike"]:
                pnl = net
            elif spot_exp >= hedge["strike"]:
                pnl = net - (short["strike"] - spot_exp)
            else:
                pnl = net - width
            # Cash-secure the SHORT strike (same capital basis as naked); the long put is a
            # cheap tail hedge that caps the crash loss. Apples-to-apples with naked CSP.
            ret = pnl / short["strike"]
        else:  # naked / fng
            assigned = spot_exp < short["strike"]
            pnl = short["prem"] - (short["strike"] - spot_exp) if assigned else short["prem"]
            ret = pnl / short["strike"]

        cap *= (1 + ret)
        eq.append(cap)
        trades.append({"month": fp.stem, "ret": ret * 100,
                       "assigned": spot_exp < short["strike"]})

    if not trades:
        return None
    n = len(trades)
    wins = sum(1 for t in trades if t["ret"] > 0)
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak)
    yrs = n / 12.0
    cagr = (cap / 100_000) ** (1 / yrs) - 1 if yrs else 0
    worst = min(trades, key=lambda t: t["ret"])
    return {"mode": mode, "n": n, "win": wins / n * 100, "total": cap / 100_000 - 1,
            "cagr": cagr, "mdd": mdd, "final": cap, "worst": worst,
            "calmar": (cagr / mdd) if mdd else float("inf")}


def main() -> int:
    files = sorted(_CHAINS.glob("*.csv"))
    if not files:
        print("no chain data — run fetch_deribit_chains.py first")
        return 1
    spot, fng = _btc_spot(), _fng()
    print("=" * 78)
    print(f"  BTC put-selling backtest — free Tardis Deribit chains ({files[0].stem}→{files[-1].stem})")
    print("=" * 78)
    print(f"  {'mode':8} {'n':>3} {'win%':>5} {'CAGR':>7} {'maxDD':>7} {'Calmar':>7} {'total':>8}  worst month")
    print("  " + "-" * 74)
    for mode in ("naked", "spread", "fng"):
        r = _run(mode, files, spot, fng)
        if not r:
            continue
        w = r["worst"]
        print(f"  {r['mode']:8} {r['n']:>3} {r['win']:>4.0f}% {r['cagr']*100:>6.1f}% "
              f"{r['mdd']*100:>6.1f}% {r['calmar']:>7.2f} {r['total']*100:>+7.1f}%  "
              f"{w['month']} {w['ret']:+.1f}%")
    print("=" * 78)
    print("  naked = cash-secured put | spread = bull put spread (tail-hedged) | fng = skip greed≥80")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
