#!/usr/bin/env python3
"""
Backtest event-driven DCA vs time-based DCA vs hybrid on full BTC history.

Strategies:
  A: Weekly DCA — FnG-weighted base amount each Monday (current crypto-dca.timer)
  B: Pure Event DCA — only trigger on detected crashes (flash + sustained)
  C: Hybrid — weekly base + monthly event-reserve for crashes

Event detection (approximated on 1m OHLC; real daemon will use tick data):
  - FLASH:    1m return < -3%             (2020-03-12 style; ~minute-scale)
  - FAST:     rolling 15m return < -5%
  - SUSTAIN:  rolling 24h return < -10%
  - CAPITUL:  30d drawdown > 25%          (deep bear territory)

Usage:
  python scripts/backtest_event_dca.py
  python scripts/backtest_event_dca.py --weekly-base 500 --event-per-month 3
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent.parent
BTC_DATA = PROJECT_DIR / "user_data" / "data" / "binance" / "BTC_USDT-1m.feather"
FNG_DATA = PROJECT_DIR / "data" / "fng_history.csv"


def fng_to_mult(fng: int) -> float:
    if fng < 10:
        return 3.0
    if fng < 20:
        return 2.2
    if fng < 40:
        return 1.5
    if fng < 60:
        return 1.0
    if fng < 80:
        return 0.6
    return 0.2


@dataclass
class Buy:
    ts: pd.Timestamp
    price: float
    usdt: float
    reason: str
    fng: int

    @property
    def btc(self) -> float:
        return self.usdt / self.price


@dataclass
class Strategy:
    name: str
    buys: list[Buy] = field(default_factory=list)

    def add(self, ts, price, usdt, reason, fng):
        if usdt > 0:
            self.buys.append(Buy(ts, float(price), float(usdt), reason, int(fng)))

    def summary(self, final_price: float) -> dict:
        total_usdt = sum(b.usdt for b in self.buys)
        total_btc = sum(b.btc for b in self.buys)
        if total_btc == 0:
            return {"name": self.name, "buys": 0, "usdt": 0, "btc": 0}
        avg_cost = total_usdt / total_btc
        final_value = total_btc * final_price
        return {
            "name": self.name,
            "buys": len(self.buys),
            "usdt": round(total_usdt, 0),
            "btc": round(total_btc, 4),
            "avg_cost": round(avg_cost, 0),
            "final_value": round(final_value, 0),
            "unrealized_pnl": round(final_value - total_usdt, 0),
            "roi_pct": round((final_value / total_usdt - 1) * 100, 1),
        }


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    print("loading BTC 1m data...")
    btc = pd.read_feather(BTC_DATA)[["date", "open", "high", "low", "close", "volume"]]
    btc["date"] = pd.to_datetime(btc["date"], utc=True)

    print("loading FnG daily...")
    fng = pd.read_csv(FNG_DATA)
    fng["date"] = pd.to_datetime(fng["date"], utc=True)
    fng = fng.sort_values("date").reset_index(drop=True)
    return btc, fng


def fng_at(fng_df: pd.DataFrame, ts: pd.Timestamp) -> int:
    """Pick FnG value on or before ts."""
    day = ts.normalize()
    row = fng_df[fng_df["date"] <= day].tail(1)
    if len(row) == 0:
        return 50
    return int(row["value"].iloc[0])


def detect_events(btc: pd.DataFrame) -> pd.DataFrame:
    """
    Scan 1m data, return DataFrame of event rows with kind + severity.
    Only keeps the strongest event per 72h cooldown window per kind.
    """
    print("computing event signals (can take 20-60s)...")
    df = btc.copy()
    df["ret_1m"] = df["close"].pct_change(1)
    df["ret_15m"] = df["close"].pct_change(15)
    df["ret_24h"] = df["close"].pct_change(24 * 60)
    df["roll_30d_high"] = df["close"].rolling(30 * 24 * 60, min_periods=60).max()
    df["dd_30d"] = (df["close"] / df["roll_30d_high"]) - 1

    events = []
    for kind, col, threshold in [
        ("FLASH", "ret_1m", -0.03),
        ("FAST", "ret_15m", -0.05),
        ("SUSTAIN", "ret_24h", -0.10),
        ("CAPITUL", "dd_30d", -0.25),
    ]:
        mask = df[col] < threshold
        hits = df[mask][["date", "close", col]].copy()
        if len(hits) == 0:
            continue
        hits = hits.rename(columns={col: "severity"})
        hits["kind"] = kind
        events.append(hits)

    if not events:
        return pd.DataFrame()

    ev = pd.concat(events, ignore_index=True).sort_values("date").reset_index(drop=True)
    return ev


def dedupe_events(ev: pd.DataFrame, cooldown_hours: int = 72) -> pd.DataFrame:
    """Apply cooldown: keep only first event in each 72h window (any kind)."""
    if len(ev) == 0:
        return ev
    cooldown = pd.Timedelta(hours=cooldown_hours)
    keep_rows = []
    last_ts = None
    for _, r in ev.iterrows():
        if last_ts is None or r["date"] - last_ts >= cooldown:
            keep_rows.append(r)
            last_ts = r["date"]
    return pd.DataFrame(keep_rows).reset_index(drop=True)


def simulate_weekly(btc: pd.DataFrame, fng: pd.DataFrame,
                    start: pd.Timestamp, end: pd.Timestamp,
                    base_usdt: float) -> Strategy:
    """Strategy A: every Monday 00:00 UTC buy base × fng_mult."""
    strat = Strategy(name=f"A_weekly_${int(base_usdt)}")
    mondays = pd.date_range(start=start, end=end, freq="W-MON", tz="UTC")
    btc_sorted = btc.set_index("date")
    for mon in mondays:
        row = btc_sorted.iloc[btc_sorted.index.searchsorted(mon)]
        price = row["close"]
        f = fng_at(fng, mon)
        mult = fng_to_mult(f)
        strat.add(mon, price, base_usdt * mult, "weekly", f)
    return strat


def simulate_event(btc: pd.DataFrame, fng: pd.DataFrame, events: pd.DataFrame,
                   start: pd.Timestamp, end: pd.Timestamp,
                   per_trigger_usdt: float, max_per_month: int = 3) -> Strategy:
    """Strategy B: buy per_trigger_usdt each dedupe'd event, capped per month."""
    strat = Strategy(name=f"B_event_${int(per_trigger_usdt)}x{max_per_month}mo")
    ev_in = events[(events["date"] >= start) & (events["date"] <= end)]

    from collections import Counter
    month_count: Counter = Counter()
    for _, e in ev_in.iterrows():
        month_key = e["date"].strftime("%Y-%m")
        if month_count[month_key] >= max_per_month:
            continue
        month_count[month_key] += 1
        f = fng_at(fng, e["date"])
        # Fear boost: FnG < 20 → 1.5x, FnG > 60 → 0.5x (dampen event buys in euphoria)
        fear_boost = 1.5 if f < 20 else (0.7 if f > 60 else 1.0)
        usdt = per_trigger_usdt * fear_boost
        strat.add(e["date"], e["close"], usdt, f"event:{e['kind']}:{e['severity']:.2%}", f)
    return strat


def simulate_hybrid(btc: pd.DataFrame, fng: pd.DataFrame, events: pd.DataFrame,
                    start: pd.Timestamp, end: pd.Timestamp,
                    weekly_base: float, event_per_trigger: float,
                    max_per_month: int = 3) -> Strategy:
    """Strategy C: weekly base + event reserve."""
    strat = Strategy(name=f"C_hybrid_w${int(weekly_base)}+e${int(event_per_trigger)}")

    # Weekly leg
    mondays = pd.date_range(start=start, end=end, freq="W-MON", tz="UTC")
    btc_sorted = btc.set_index("date")
    for mon in mondays:
        row = btc_sorted.iloc[btc_sorted.index.searchsorted(mon)]
        price = row["close"]
        f = fng_at(fng, mon)
        mult = fng_to_mult(f)
        strat.add(mon, price, weekly_base * mult, "weekly", f)

    # Event leg
    from collections import Counter
    month_count: Counter = Counter()
    ev_in = events[(events["date"] >= start) & (events["date"] <= end)]
    for _, e in ev_in.iterrows():
        month_key = e["date"].strftime("%Y-%m")
        if month_count[month_key] >= max_per_month:
            continue
        month_count[month_key] += 1
        f = fng_at(fng, e["date"])
        fear_boost = 1.5 if f < 20 else (0.7 if f > 60 else 1.0)
        usdt = event_per_trigger * fear_boost
        strat.add(e["date"], e["close"], usdt, f"event:{e['kind']}:{e['severity']:.2%}", f)
    return strat


def print_summary(strats: list[Strategy], final_price: float):
    rows = [s.summary(final_price) for s in strats]
    print("\n" + "=" * 80)
    print("  BACKTEST SUMMARY")
    print("=" * 80)
    header = f"{'Strategy':<36} {'Buys':>5} {'USDT':>10} {'BTC':>8} {'Cost':>8} {'Value':>10} {'ROI%':>7}"
    print(header)
    print("-" * 80)
    for r in rows:
        print(f"{r['name']:<36} {r['buys']:>5} {r['usdt']:>10,.0f} {r['btc']:>8.4f} "
              f"{r['avg_cost']:>8,.0f} {r['final_value']:>10,.0f} {r['roi_pct']:>6.1f}%")


def print_event_stats(events: pd.DataFrame):
    if len(events) == 0:
        print("no events detected")
        return
    print("\n" + "=" * 80)
    print("  EVENTS DETECTED (after 72h cooldown)")
    print("=" * 80)
    print(f"Total events: {len(events)}")
    print(f"Kind distribution:")
    print(events["kind"].value_counts().to_string())
    print(f"\nSample (strongest 10 by severity):")
    top = events.nsmallest(10, "severity")[["date", "kind", "close", "severity"]]
    for _, r in top.iterrows():
        print(f"  {r['date'].strftime('%Y-%m-%d %H:%M')}  {r['kind']:<8} "
              f"${r['close']:>10,.0f}  {r['severity']:>+6.2%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weekly-base", type=float, default=500,
                    help="weekly DCA base (default 500)")
    ap.add_argument("--event-per-trigger", type=float, default=1000,
                    help="per-event amount (default 1000)")
    ap.add_argument("--max-per-month", type=int, default=3,
                    help="max event triggers per month (default 3)")
    ap.add_argument("--start", default="2018-02-01",
                    help="backtest start (FnG data starts 2018-02)")
    ap.add_argument("--end", default="2026-04-22",
                    help="backtest end")
    args = ap.parse_args()

    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")

    btc, fng = load_data()
    btc = btc[(btc["date"] >= start) & (btc["date"] <= end)].reset_index(drop=True)
    print(f"BTC data: {btc['date'].min()} → {btc['date'].max()}  ({len(btc):,} rows)")
    print(f"FnG data: {fng['date'].min()} → {fng['date'].max()}  ({len(fng):,} rows)")

    final_price = btc["close"].iloc[-1]
    print(f"Final BTC price at {btc['date'].iloc[-1]}: ${final_price:,.0f}")

    # Detect events
    events = detect_events(btc)
    events_dedup = dedupe_events(events, cooldown_hours=72)
    print(f"\nRaw events: {len(events):,}  →  after 72h cooldown: {len(events_dedup):,}")

    # Run 3 strategies
    strat_a = simulate_weekly(btc, fng, start, end, args.weekly_base)
    strat_b = simulate_event(btc, fng, events_dedup, start, end,
                             args.event_per_trigger, args.max_per_month)
    strat_c = simulate_hybrid(btc, fng, events_dedup, start, end,
                              args.weekly_base * 0.7,                # smaller weekly leg
                              args.event_per_trigger * 0.7,          # smaller event leg
                              args.max_per_month)

    # Also: a "lump sum" baseline for reference
    lump = Strategy(name="X_lump_sum_at_start")
    lump.add(btc["date"].iloc[0], btc["close"].iloc[0],
             args.weekly_base * 52 * 8, "lump", fng_at(fng, btc["date"].iloc[0]))

    print_event_stats(events_dedup)
    print_summary([strat_a, strat_b, strat_c, lump], final_price)


if __name__ == "__main__":
    main()
