#!/usr/bin/env python3
"""
Generate backtest_data.js for dashboard/backtest.html

Reads the latest Freqtrade backtest result JSON, replays the indicator state
at each trade's entry and exit, and emits a JS file with per-trade condition
breakdowns: which of the 6 entry rules were satisfied with what values.

Output: dashboard/backtest_data.js  (window.BACKTEST_DATA = {...})

Usage:
  python scripts/generate_backtest_viz.py [--strategy NAME] [--config PATH]
"""

import argparse
import csv
import json
import logging
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import talib.abstract as ta

PROJECT_DIR = Path(__file__).resolve().parent.parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backtest_viz")

# Default strategy params (matches HonestTrend1mLive / HonestTrend15mDry conventions)
DEFAULT_PARAMS = {
    "ema_fast": 1410,
    "ema_slow": 2085,
    "adx_threshold": 18,
    "fng_block": 80,
    "min_hold_minutes": 1440,
}


def load_fng() -> dict[str, int]:
    fng_file = PROJECT_DIR / "data" / "fng_history.csv"
    fng = {}
    if not fng_file.exists():
        logger.warning(f"No FnG file at {fng_file}")
        return fng
    with open(fng_file) as f:
        for row in csv.DictReader(f):
            fng[row["date"]] = int(row["value"])
    return fng


def latest_backtest_zip() -> Path | None:
    # Override via FREQTRADE_BACKTEST_DIR env; default to ../freqtrade/user_data/backtest_results
    default = Path(__file__).resolve().parent.parent.parent / "freqtrade" / "user_data" / "backtest_results"
    bt_dir = Path(os.environ.get("FREQTRADE_BACKTEST_DIR", default))
    if not bt_dir.exists():
        return None
    zips = sorted(bt_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    return zips[0] if zips else None


def load_backtest(zip_path: Path) -> tuple[str, list[dict], dict]:
    """Returns (strategy_name, trades, summary_metrics)."""
    with zipfile.ZipFile(zip_path) as z:
        json_name = next(
            n for n in z.namelist()
            if n.endswith(".json") and "_config" not in n
            and not n.endswith(".meta.json")
        )
        data = json.loads(z.read(json_name))
    strategy_key = next(iter(data.get("strategy", {})))
    s = data["strategy"][strategy_key]
    return strategy_key, s["trades"], {
        "profit_total_pct": s.get("profit_total_pct", 0),
        "profit_total_abs": s.get("profit_total_abs", 0),
        "max_drawdown_account": s.get("max_drawdown_account", 0),
        "trades_count": len(s["trades"]),
        "winrate": (sum(1 for t in s["trades"] if t["profit_ratio"] > 0)
                    / max(1, len(s["trades"]))) * 100,
        "profit_factor": s.get("profit_factor", 0),
        "timerange": f"{s.get('backtest_run_start_ts', '')} → {s.get('backtest_run_end_ts', '')}",
    }


def load_ohlcv(pair: str, timeframe: str) -> pd.DataFrame | None:
    """Load feather data for a pair/timeframe."""
    data_dir = PROJECT_DIR / "user_data" / "data"
    ft_pair = pair.replace("/", "_")
    candidates = [
        data_dir / f"{ft_pair}-{timeframe}.feather",
    ]
    for p in candidates:
        if p.exists():
            df = pd.read_feather(p)
            df["date"] = pd.to_datetime(df["date"], utc=True)
            return df
    logger.warning(f"No OHLCV data for {pair} {timeframe}")
    return None


def compute_indicators(df: pd.DataFrame, params: dict, timeframe: str) -> pd.DataFrame:
    """Add EMAs, ADX, +DI, -DI, volume_sma, FnG to dataframe."""
    df = df.copy()
    df[f"ema_{params['ema_fast']}"] = ta.EMA(df, timeperiod=params["ema_fast"])
    df[f"ema_{params['ema_slow']}"] = ta.EMA(df, timeperiod=params["ema_slow"])
    df["adx"] = ta.ADX(df)
    df["plus_di"] = ta.PLUS_DI(df)
    df["minus_di"] = ta.MINUS_DI(df)

    tf_min = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}.get(timeframe, 15)
    vol_window = max(1, 1440 // tf_min)
    df["volume_sma"] = ta.SMA(df["volume"], timeperiod=vol_window)
    return df


def attach_fng(df: pd.DataFrame, fng_lookup: dict) -> pd.DataFrame:
    df["fng"] = df["date"].dt.strftime("%Y-%m-%d").map(lambda d: fng_lookup.get(d, 50))
    return df


def trade_conditions(
    df: pd.DataFrame, dt: pd.Timestamp, params: dict, side: str
) -> dict:
    """Snapshot indicator state at a given timestamp. Returns conditions dict."""
    # Find the candle whose close matches dt (or just before)
    idx = df["date"].searchsorted(dt) - 1
    if idx < 0 or idx >= len(df):
        return {}
    row = df.iloc[idx]
    prev = df.iloc[idx - 1] if idx > 0 else row

    ef = params["ema_fast"]
    es = params["ema_slow"]
    fast_now, slow_now = float(row[f"ema_{ef}"]), float(row[f"ema_{es}"])
    fast_prev, slow_prev = float(prev[f"ema_{ef}"]), float(prev[f"ema_{es}"])
    adx = float(row["adx"])
    plus_di = float(row["plus_di"])
    minus_di = float(row["minus_di"])
    vol = float(row["volume"])
    vol_sma = float(row["volume_sma"]) if not pd.isna(row["volume_sma"]) else 0
    fng = int(row["fng"])

    if side == "entry":
        crossed = (fast_prev <= slow_prev) and (fast_now > slow_now)
        return {
            "candle_time": row["date"].isoformat(),
            "price": float(row["close"]),
            "checks": [
                {
                    "name": f"EMA {ef} crossed above EMA {es}",
                    "pass": crossed,
                    "detail": f"fast {fast_now:.2f} vs slow {slow_now:.2f} "
                              f"(prev fast {fast_prev:.2f}, slow {slow_prev:.2f})",
                },
                {
                    "name": "+DI > -DI (uptrend)",
                    "pass": plus_di > minus_di,
                    "detail": f"+DI {plus_di:.2f}, -DI {minus_di:.2f}",
                },
                {
                    "name": f"ADX > {params['adx_threshold']}",
                    "pass": adx > params["adx_threshold"],
                    "detail": f"ADX {adx:.2f}",
                },
                {
                    "name": "Volume > 1d SMA",
                    "pass": vol > vol_sma,
                    "detail": f"vol {vol:.2f}, sma {vol_sma:.2f} "
                              f"(ratio {vol / vol_sma:.2f}x)" if vol_sma > 0 else f"vol {vol:.2f}, sma 0",
                },
                {
                    "name": f"Fear&Greed < {params['fng_block']}",
                    "pass": fng < params["fng_block"],
                    "detail": f"FnG {fng}",
                },
                {
                    "name": "Volume > 0",
                    "pass": vol > 0,
                    "detail": f"vol {vol:.2f}",
                },
            ],
        }
    else:  # exit
        crossed_down = (fast_prev >= slow_prev) and (fast_now < slow_now)
        return {
            "candle_time": row["date"].isoformat(),
            "price": float(row["close"]),
            "checks": [
                {
                    "name": f"EMA {ef} crossed below EMA {es}",
                    "pass": crossed_down,
                    "detail": f"fast {fast_now:.2f} vs slow {slow_now:.2f}",
                },
                {
                    "name": "Volume > 0",
                    "pass": vol > 0,
                    "detail": f"vol {vol:.2f}",
                },
            ],
        }


def trade_price_window(df: pd.DataFrame, entry_dt, exit_dt, target_points=120) -> list[dict]:
    """
    Return downsampled close prices around the trade for sparkline plotting.
    Aim for ~target_points samples regardless of timeframe; trades on 1m can be 4000+ candles.
    Pad: 10% of trade duration on each side.
    """
    ei_raw = df["date"].searchsorted(entry_dt)
    xi_raw = df["date"].searchsorted(exit_dt)
    span = max(1, xi_raw - ei_raw)
    pad = max(5, span // 10)
    ei = max(0, ei_raw - pad)
    xi = min(len(df) - 1, xi_raw + pad)
    sub = df.iloc[ei:xi + 1]
    if len(sub) > target_points:
        # Stride sampling
        step = max(1, len(sub) // target_points)
        sub = sub.iloc[::step]
    return [
        {
            "t": r["date"].isoformat(),
            "c": float(r["close"]),
            "in_trade": entry_dt <= r["date"] <= exit_dt,
        }
        for _, r in sub.iterrows()
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", help="path to backtest zip (default: latest)")
    ap.add_argument("--timeframe", default="1m",
                    help="OHLCV timeframe to load (default: 1m matches HonestTrend1mLive)")
    ap.add_argument("--ema-fast", type=int, default=DEFAULT_PARAMS["ema_fast"])
    ap.add_argument("--ema-slow", type=int, default=DEFAULT_PARAMS["ema_slow"])
    ap.add_argument("--adx-threshold", type=int, default=DEFAULT_PARAMS["adx_threshold"])
    ap.add_argument("--max-trades", type=int, default=200,
                    help="cap trades emitted (default 200, full set can be heavy)")
    ap.add_argument("--out", default=str(PROJECT_DIR / "dashboard" / "backtest_data.js"))
    args = ap.parse_args()

    bt_zip = Path(args.zip) if args.zip else latest_backtest_zip()
    if not bt_zip or not bt_zip.exists():
        logger.error("No backtest zip found")
        return 1

    logger.info(f"Reading: {bt_zip.name}")
    strat, trades, summary = load_backtest(bt_zip)
    logger.info(f"Strategy: {strat}, trades: {len(trades)}")

    params = {
        "ema_fast": args.ema_fast,
        "ema_slow": args.ema_slow,
        "adx_threshold": args.adx_threshold,
        "fng_block": DEFAULT_PARAMS["fng_block"],
        "min_hold_minutes": DEFAULT_PARAMS["min_hold_minutes"],
    }

    fng = load_fng()
    pair_dfs: dict[str, pd.DataFrame] = {}
    pairs = sorted({t["pair"] for t in trades})
    for pair in pairs:
        df = load_ohlcv(pair, args.timeframe)
        if df is None:
            continue
        df = compute_indicators(df, params, args.timeframe)
        df = attach_fng(df, fng)
        pair_dfs[pair] = df
        logger.info(f"Indicators ready for {pair} ({len(df)} candles)")

    enriched_trades = []
    sliced = trades[:args.max_trades] if args.max_trades > 0 else trades
    for i, t in enumerate(sliced):
        pair = t["pair"]
        df = pair_dfs.get(pair)
        if df is None:
            continue
        entry_dt = pd.to_datetime(t["open_date"], utc=True)
        exit_dt = pd.to_datetime(t["close_date"], utc=True)

        entry_cond = trade_conditions(df, entry_dt, params, "entry")
        exit_cond = trade_conditions(df, exit_dt, params, "exit")
        price_window = trade_price_window(df, entry_dt, exit_dt)

        enriched_trades.append({
            "id": i + 1,
            "pair": pair,
            "open_date": t["open_date"],
            "close_date": t["close_date"],
            "open_rate": t["open_rate"],
            "close_rate": t["close_rate"],
            "amount": t["amount"],
            "stake": t.get("stake_amount", 0),
            "profit_ratio": t["profit_ratio"],
            "profit_abs": t["profit_abs"],
            "duration_min": t["trade_duration"],
            "exit_reason": t.get("exit_reason", ""),
            "enter_tag": t.get("enter_tag", ""),
            "entry": entry_cond,
            "exit": exit_cond,
            "price_window": price_window,
        })

    out_data = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source_zip": bt_zip.name,
        "strategy": strat,
        "params": params,
        "timeframe": args.timeframe,
        "summary": summary,
        "pairs": pairs,
        "trades": enriched_trades,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    js = "// Auto-generated by scripts/generate_backtest_viz.py — do not edit\n"
    js += "window.BACKTEST_DATA = " + json.dumps(out_data, default=str, indent=2) + ";\n"
    out_path.write_text(js)
    logger.info(f"Wrote {len(enriched_trades)} trades → {out_path} ({out_path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
