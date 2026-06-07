"""Backtest a monthly Cash-Secured Put (CSP) wheel on BTC using FREE Tardis Deribit
option-chain snapshots (data/deribit_chains/*.csv) + real BTC spot for settlement.

Strategy (mirrors strategies/deribit_monitor.py):
  - Each month: from the opening chain, pick OTM puts with DTE 5-30, strike 10-25% OTM,
    bid>0. Rank by annual_yield x liquidity - IV penalty. Sell the top candidate.
  - Hold to expiry. Settle vs real BTC spot:
      assigned (spot_exp < strike): pnl = premium - (strike - spot_exp)
      expires worthless:            pnl = premium  (full premium kept)
  - Collateral = strike (cash-secured). Compound return-on-collateral month to month.

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

MIN_DAYS, MAX_DAYS = 5, 30
MIN_OTM, MAX_OTM = 0.10, 0.25


def _btc_spot_by_date() -> dict[str, float]:
    df = pd.read_feather(_BTC)
    return {d.strftime("%Y-%m-%d"): float(c) for d, c in zip(df["date"], df["close"])}


def _spot_on_or_before(spot: dict[str, float], day: dt.date) -> float | None:
    for back in range(0, 7):
        k = (day - dt.timedelta(days=back)).strftime("%Y-%m-%d")
        if k in spot:
            return spot[k]
    return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def select_csp(rows, snap_dt, spot):
    best = None
    for r in rows:
        bid = _f(r.get("bid_price"))
        if not bid or bid <= 0:
            continue
        strike = _f(r.get("strike_price"))
        exp_us = _f(r.get("expiration"))
        if not strike or not exp_us:
            continue
        exp = dt.datetime.fromtimestamp(exp_us / 1e6, tz=dt.timezone.utc)
        days = (exp - snap_dt).total_seconds() / 86400
        if days < MIN_DAYS or days > MAX_DAYS:
            continue
        otm = (spot - strike) / spot
        if otm < MIN_OTM or otm > MAX_OTM:
            continue
        premium_usd = bid * spot
        annual_yield = (premium_usd / strike) * (365 / days) * 100
        oi = _f(r.get("open_interest")) or 0
        iv = (_f(r.get("mark_iv")) or 0) / 100.0
        liq = min(oi / 100, 1.0)
        score = annual_yield * (1 + liq) - iv * 20
        cand = {
            "strike": strike, "days": days, "otm": otm * 100,
            "premium_usd": premium_usd, "annual_yield": annual_yield,
            "expiry": exp.date(), "score": score,
            "delta": _f(r.get("delta")),
        }
        if best is None or score > best["score"]:
            best = cand
    return best


def main() -> int:
    spot = _btc_spot_by_date()
    files = sorted(_CHAINS.glob("*.csv"))
    if not files:
        print("no chain data — run fetch_deribit_chains.py first")
        return 1

    capital = 100_000.0
    eq = [capital]
    trades = []
    for fp in files:
        rows = list(csv.DictReader(open(fp)))
        if not rows:
            continue
        snap_us = _f(rows[0].get("timestamp"))
        if not snap_us:
            continue
        snap_dt = dt.datetime.fromtimestamp(snap_us / 1e6, tz=dt.timezone.utc)
        snap_spot = _f(rows[0].get("underlying_price"))
        if not snap_spot:
            continue
        pick = select_csp(rows, snap_dt, snap_spot)
        if pick is None:
            continue
        spot_exp = _spot_on_or_before(spot, pick["expiry"])
        if spot_exp is None:
            continue
        assigned = spot_exp < pick["strike"]
        pnl = pick["premium_usd"] - (pick["strike"] - spot_exp) if assigned else pick["premium_usd"]
        ret = pnl / pick["strike"]  # return on collateral
        capital *= (1 + ret)
        eq.append(capital)
        trades.append({
            "month": fp.stem, "strike": pick["strike"], "dte": round(pick["days"], 1),
            "otm": round(pick["otm"], 1), "ann_yield": round(pick["annual_yield"], 1),
            "assigned": assigned, "ret_pct": round(ret * 100, 2),
        })

    if not trades:
        print("no qualifying CSP trades")
        return 1

    n = len(trades)
    wins = sum(1 for t in trades if t["ret_pct"] > 0)
    assigns = sum(1 for t in trades if t["assigned"])
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak)
    total_ret = capital / 100_000 - 1
    span_years = n / 12.0
    cagr = (capital / 100_000) ** (1 / span_years) - 1 if span_years > 0 else 0

    print("=" * 60)
    print("  BTC Cash-Secured Put backtest — free Tardis Deribit chains")
    print("=" * 60)
    print(f"  months traded   : {n}  ({files[0].stem} → {files[-1].stem})")
    print(f"  win rate        : {wins}/{n} ({wins/n*100:.0f}%)")
    print(f"  assignment rate : {assigns}/{n} ({assigns/n*100:.0f}%)")
    print(f"  avg ann. yield* : {sum(t['ann_yield'] for t in trades)/n:.1f}%  (*of selected puts)")
    print(f"  total return    : {total_ret*100:+.1f}%  over ~{span_years:.1f}y")
    print(f"  CAGR            : {cagr*100:+.1f}%")
    print(f"  max drawdown    : {mdd*100:.1f}%")
    print(f"  final capital   : ${capital:,.0f}")
    print("-" * 60)
    print("  worst 5 months by return:")
    for t in sorted(trades, key=lambda x: x["ret_pct"])[:5]:
        print(f"    {t['month']}  strike {t['strike']:.0f}  {t['otm']}% OTM  "
              f"DTE {t['dte']}  {'ASSIGNED' if t['assigned'] else 'expired'}  {t['ret_pct']:+.2f}%")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
