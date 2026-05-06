#!/usr/bin/env python3
"""
Import freqtrade backtest result zips → Timescale
  quant.backtest_runs (one row per run)
  quant.backtest_trades (one row per trade in that run)

Idempotent by `run_id` (hash freqtrade assigns per backtest). Re-imports skipped.

Usage:
  sops exec-env secrets.env 'python scripts/import_backtest_zip.py'             # all zips
  sops exec-env secrets.env 'python scripts/import_backtest_zip.py --zip PATH'  # one file
  sops exec-env secrets.env 'python scripts/import_backtest_zip.py --job-id X'  # tag with job_id (for launcher)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import psycopg2


PROJECT_DIR  = Path(__file__).resolve().parent.parent
BACKTEST_DIR = PROJECT_DIR / "user_data" / "backtest_results"
SCHEMA       = os.environ.get("TIMESCALE_SCHEMA", "quant")
DB_URL       = os.environ.get("TIMESCALE_URL")

# Canonical factor tags per strategy. The UI surfaces these as badges on
# /strategies/[name] and on the home page's Recent Runs table, so unknown
# strategies get a single "unknown" placeholder rather than an empty list.
# Keep the tag vocabulary aligned with migrations/003_backtest_factors.sql.
FACTORS_BY_STRATEGY = {
    "HonestTrend15mDry":         ["EMA", "ADX", "DD-Kill", "Spot"],
    "HonestTrend15mAdvanced":    ["EMA", "ADX", "Protections", "DD-Kill", "Spot"],
    "HonestTrend15mProtections": ["EMA", "ADX", "Protections", "Trailing", "DD-Kill", "Spot"],
    "HonestTrend15mPyramid":     ["EMA", "ADX", "Pyramid", "DCA", "DD-Kill", "Spot"],
    "HonestTrend1mLive":         ["EMA", "ADX", "DD-Kill", "Spot"],
    "HonestTrend1mMTF":          ["EMA", "ADX", "HTF", "DD-Kill", "Spot"],
    "HonestTrendFutures":        ["EMA", "ADX", "FnG", "Funding", "Futures-Short", "DD-Kill"],
    "LiveProveIt":               ["EMA", "ADX", "Production-gate", "DD-Kill"],
}


def connect():
    if not DB_URL:
        sys.exit("TIMESCALE_URL not set")
    return psycopg2.connect(DB_URL)


def read_result(zip_path: Path) -> tuple[str, dict, list[dict], dict, Path]:
    """Return (run_id, strategy_summary_dict, trades_list, meta, json_member)."""
    meta_path = zip_path.with_suffix(".meta.json")
    if not meta_path.exists():
        raise RuntimeError(f"no meta.json sibling for {zip_path.name}")
    meta_all = json.loads(meta_path.read_text())
    # meta is {strategy_name: {run_id, timeframe, ...}}
    strategy_name = next(iter(meta_all.keys()))
    meta = meta_all[strategy_name]

    with zipfile.ZipFile(zip_path) as z:
        # Main results JSON = one without _config / _wallet / _market_change suffix
        main = next((n for n in z.namelist()
                     if n.endswith(".json")
                     and "_config" not in n
                     and "wallet" not in n
                     and "market_change" not in n),
                    None)
        if not main:
            raise RuntimeError(f"no main result json in {zip_path.name}")
        with z.open(main) as f:
            result = json.load(f)

    strat = result["strategy"].get(strategy_name)
    if not strat:
        raise RuntimeError(f"strategy {strategy_name} not in result")
    trades = strat.pop("trades", [])  # pop to slim raw_summary
    return meta["run_id"], strat, trades, meta, Path(main)


def already_imported(cur, run_id: str) -> bool:
    cur.execute(
        f"SELECT 1 FROM {SCHEMA}.backtest_runs WHERE raw_summary->>'run_id' = %s LIMIT 1",
        (run_id,))
    return cur.fetchone() is not None


def dt_or_none(v) -> datetime | None:
    if v is None or v == "" or v == 0:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc) if v > 1e9 else None
    try:
        return datetime.fromisoformat(str(v))
    except Exception:
        return None


def insert_run(cur, run_id: str, strategy_name: str, strat: dict,
               meta: dict, zip_path: Path, job_id: str | None) -> int:
    """Insert into backtest_runs, return inserted id."""
    pairs = strat.get("pairlist") or []
    # freqtrade stores backtest_start/end in various places
    started  = dt_or_none(strat.get("backtest_start"))
    finished = dt_or_none(strat.get("backtest_end"))
    duration = None
    if strat.get("backtest_run_start_ts") and strat.get("backtest_run_end_ts"):
        duration = strat["backtest_run_end_ts"] - strat["backtest_run_start_ts"]

    raw = {k: v for k, v in strat.items()
           if not isinstance(v, (dict, list))}  # strip nested for smaller blob
    # Keep exit_reason_summary + results_per_pair + some key structured bits
    for k in ("exit_reason_summary", "results_per_pair", "results_per_enter_tag"):
        if k in strat:
            raw[k] = strat[k]
    raw["run_id"] = run_id

    factors = FACTORS_BY_STRATEGY.get(strategy_name, ["unknown"])

    cur.execute(f"""
        INSERT INTO {SCHEMA}.backtest_runs
            (job_id, strategy, config_file, timerange, timeframe,
             max_open_trades, stake_amount, pairs,
             started_at, finished_at, duration_sec,
             total_trades, wins, losses, win_rate_pct,
             total_profit_pct, total_profit_abs, max_drawdown_pct,
             calmar, sharpe, sortino, profit_factor,
             factors, raw_summary, zip_path)
        VALUES (%s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s::jsonb, %s::jsonb, %s)
        RETURNING id
    """, (
        job_id,
        strategy_name,
        None,                                       # config_file (unknown from zip)
        f"{strat.get('backtest_start_ts')}-{strat.get('backtest_end_ts')}"
          if strat.get("backtest_start_ts") else None,
        meta.get("timeframe"),
        strat.get("max_open_trades") if isinstance(strat.get("max_open_trades"), (int, float)) else None,
        strat.get("stake_amount")     if isinstance(strat.get("stake_amount"),     (int, float)) else None,
        pairs if pairs else None,
        started, finished, duration,
        strat.get("total_trades"),
        strat.get("wins"),
        strat.get("losses"),
        round((strat.get("winrate") or 0) * 100, 2),
        round((strat.get("profit_total") or 0) * 100, 2),
        strat.get("profit_total_abs"),
        round((strat.get("max_drawdown_account") or 0) * 100, 2),
        strat.get("calmar"),
        strat.get("sharpe"),
        strat.get("sortino"),
        strat.get("profit_factor"),
        json.dumps(factors),
        json.dumps(raw, default=str),
        str(zip_path),
    ))
    return cur.fetchone()[0]


def insert_trades(cur, run_id_pk: int, trades: list[dict]):
    if not trades:
        return 0
    rows = []
    for i, t in enumerate(trades):
        rows.append((
            run_id_pk, i + 1,
            t.get("pair"),
            bool(t.get("is_short")),
            dt_or_none(t.get("open_date")),
            dt_or_none(t.get("close_date")),
            t.get("open_rate"), t.get("close_rate"),
            t.get("stake_amount"),
            t.get("profit_abs"),
            round((t.get("profit_ratio") or 0) * 100, 4),
            t.get("exit_reason"),
            t.get("enter_tag"),
            t.get("trade_duration"),
        ))
    cur.executemany(f"""
        INSERT INTO {SCHEMA}.backtest_trades
            (run_id, trade_id, pair, is_short,
             open_date, close_date, open_rate, close_rate,
             stake_amount, profit_abs, profit_pct,
             exit_reason, enter_tag, trade_duration_min)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, rows)
    return len(rows)


def import_zip(cur, zip_path: Path, job_id: str | None, force: bool) -> tuple[bool, str]:
    try:
        run_id, strat, trades, meta, _ = read_result(zip_path)
    except Exception as e:
        return False, f"parse error: {e}"

    if not force and already_imported(cur, run_id):
        return False, "already imported (skip)"

    if force:
        cur.execute(
            f"DELETE FROM {SCHEMA}.backtest_runs WHERE raw_summary->>'run_id' = %s",
            (run_id,))

    strategy_name = next(iter(json.loads(zip_path.with_suffix(".meta.json")
                                         .read_text()).keys()))
    pk = insert_run(cur, run_id, strategy_name, strat, meta, zip_path, job_id)
    n  = insert_trades(cur, pk, trades)
    return True, f"imported run_id={run_id[:8]} pk={pk} trades={n}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", help="single zip path (default: all in user_data/backtest_results/)")
    ap.add_argument("--job-id", help="tag with launcher job_id")
    ap.add_argument("--force", action="store_true", help="reimport even if run_id present")
    args = ap.parse_args()

    if args.zip:
        zips = [Path(args.zip)]
    else:
        zips = sorted(BACKTEST_DIR.glob("*.zip"))
    if not zips:
        print("no backtest zips found")
        return

    print(f"importing {len(zips)} zip(s) → {SCHEMA}.backtest_runs")
    imp = skip = err = 0
    with connect() as conn, conn.cursor() as cur:
        for z in zips:
            ok, msg = import_zip(cur, z, args.job_id, args.force)
            marker = "✓" if ok else ("·" if "skip" in msg else "✗")
            print(f"  {marker} {z.name:<60} {msg}")
            if ok: imp += 1
            elif "skip" in msg: skip += 1
            else: err += 1
        conn.commit()
    print(f"\nImported {imp}, skipped {skip}, errors {err}")


if __name__ == "__main__":
    main()
