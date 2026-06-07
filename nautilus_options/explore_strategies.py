"""Explore put-selling variants on the free Deribit chains vs a buy-and-hold BTC benchmark.
The bar to beat: just holding BTC. Run after fetch_deribit_chains.py.

Variants (all cash-secured, collateral = strike, compounded monthly):
  base      : 10-25% OTM, DTE 5-30   (the original)
  deepOTM   : 18-40% OTM             (fewer assignments, less premium)
  lowdelta  : |delta| <= 0.12        (~10-delta, tail-safe selection)
  shortDTE  : DTE 5-12               (faster theta, less gamma exposure)
  fearOnly  : sell only when FNG<=25 (buy-the-dip via puts, near bottoms)
  fear+deep : fearOnly + 18-40% OTM
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


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _btc():
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


def _spot_before(spot, day):
    for b in range(7):
        k = (day - dt.timedelta(days=b)).strftime("%Y-%m-%d")
        if k in spot:
            return spot[k]
    return None


def _pick(rows, snap_dt, spot, otm_lo, otm_hi, dte_lo, dte_hi, delta_cap):
    best = None
    for r in rows:
        bid = _f(r.get("bid_price"))
        strike = _f(r.get("strike_price"))
        exp_us = _f(r.get("expiration"))
        if not bid or bid <= 0 or not strike or not exp_us:
            continue
        exp = dt.datetime.fromtimestamp(exp_us / 1e6, tz=dt.timezone.utc)
        days = (exp - snap_dt).total_seconds() / 86400
        if days < dte_lo or days > dte_hi:
            continue
        otm = (spot - strike) / spot
        if otm < otm_lo or otm > otm_hi:
            continue
        delta = _f(r.get("delta"))
        if delta_cap is not None and (delta is None or abs(delta) > delta_cap):
            continue
        prem = bid * spot
        ann = (prem / strike) * (365 / days) * 100
        oi = _f(r.get("open_interest")) or 0
        iv = (_f(r.get("mark_iv")) or 0) / 100
        score = ann * (1 + min(oi / 100, 1.0)) - iv * 20
        c = {"strike": strike, "prem": prem, "ann": ann, "exp": exp, "score": score}
        if best is None or score > best["score"]:
            best = c
    return best


def _run(name, files, spot, fng, otm=(0.10, 0.25), dte=(5, 30), delta_cap=None, fng_max=None):
    cap, eq, trades = 100_000.0, [100_000.0], []
    for fp in files:
        rows = list(csv.DictReader(open(fp)))
        if not rows:
            continue
        snap_us = _f(rows[0].get("timestamp"))
        snap_spot = _f(rows[0].get("underlying_price"))
        if not snap_us or not snap_spot:
            continue
        snap_dt = dt.datetime.fromtimestamp(snap_us / 1e6, tz=dt.timezone.utc)
        if fng_max is not None and fng.get(snap_dt.strftime("%Y-%m-%d"), 50) > fng_max:
            continue
        p = _pick(rows, snap_dt, snap_spot, otm[0], otm[1], dte[0], dte[1], delta_cap)
        if not p:
            continue
        se = _spot_before(spot, p["exp"].date())
        if se is None:
            continue
        pnl = p["prem"] - (p["strike"] - se) if se < p["strike"] else p["prem"]
        ret = pnl / p["strike"]
        cap *= (1 + ret)
        eq.append(cap)
        trades.append(ret * 100)
    if not trades:
        return None
    n = len(trades)
    peak = mdd = 0
    peak = eq[0]
    for v in eq:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak)
    yrs = n / 12.0
    cagr = (cap / 100_000) ** (1 / yrs) - 1 if yrs else 0
    return (name, n, sum(1 for t in trades if t > 0) / n * 100, cagr * 100, mdd * 100,
            (cagr / mdd if mdd else 0), min(trades))


def _btc_benchmark(files, spot):
    # Buy-hold BTC over the same span (first snapshot month → last expiry-ish).
    months = [fp.stem for fp in files]
    s0 = None
    for m in months:
        k = f"{m}-01"
        if k in spot:
            s0 = spot[k]
            break
    last = files[-1].stem
    sN = None
    for b in range(40):
        k = (dt.date(int(last[:4]), int(last[5:7]), 1) + dt.timedelta(days=30 - b)).strftime("%Y-%m-%d")
        if k in spot:
            sN = spot[k]
            break
    if not s0 or not sN:
        return None
    yrs = len(files) / 12.0
    total = sN / s0 - 1
    cagr = (sN / s0) ** (1 / yrs) - 1
    # rough max DD of BTC over span
    ks = sorted(k for k in spot if files[0].stem <= k[:7] <= last)
    peak = mdd = 0
    peak = spot[ks[0]]
    for k in ks:
        peak = max(peak, spot[k]); mdd = max(mdd, (peak - spot[k]) / peak)
    return ("BTC buy&hold", len(files), 0, cagr * 100, mdd * 100, (cagr / mdd if mdd else 0), 0)


def main() -> int:
    files = sorted(_CHAINS.glob("*.csv"))
    if not files:
        print("no data"); return 1
    spot, fng = _btc(), _fng()
    rows = [
        _run("base", files, spot, fng),
        _run("deepOTM", files, spot, fng, otm=(0.18, 0.40)),
        _run("lowdelta", files, spot, fng, delta_cap=0.12),
        _run("shortDTE", files, spot, fng, dte=(5, 12)),
        _run("fearOnly", files, spot, fng, fng_max=25),
        _run("fear+deep", files, spot, fng, otm=(0.18, 0.40), fng_max=25),
        _btc_benchmark(files, spot),
    ]
    print("=" * 76)
    print(f"  Put-selling exploration vs BTC buy&hold ({files[0].stem}→{files[-1].stem})")
    print("=" * 76)
    print(f"  {'variant':12} {'n':>3} {'win%':>5} {'CAGR':>7} {'maxDD':>7} {'Calmar':>7} {'worst':>8}")
    print("  " + "-" * 72)
    for r in rows:
        if not r:
            continue
        name, n, win, cagr, mdd, calmar, worst = r
        print(f"  {name:12} {n:>3} {win:>4.0f}% {cagr:>6.1f}% {mdd:>6.1f}% {calmar:>7.2f} {worst:>+7.1f}%")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
