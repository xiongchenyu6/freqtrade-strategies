#!/usr/bin/env python3
"""
Incremental sync of local state files → TimescaleDB.
Runs quickly (seconds) so safe to invoke every few minutes via systemd timer.

Three sources:
  1. Bot SQLite DBs → quant.trades           (live/dry-run per-trade snapshots)
  2. event_dca_state.json → quant.event_dca_triggers
  3. walk_forward_history/*.json → quant.wf_results

All upserts are idempotent by natural key.

Usage:
  sops exec-env secrets.env 'python scripts/sync_local_state_to_timescale.py'
  sops exec-env secrets.env 'python scripts/sync_local_state_to_timescale.py --only trades'
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras


PROJECT_DIR = Path(__file__).resolve().parent.parent
SCHEMA      = os.environ.get("TIMESCALE_SCHEMA", "quant")
DB_URL      = os.environ.get("TIMESCALE_URL")


# Bot SQLite DB paths and their bot_name (for tagging in DB)
BOT_DBS = [
    ("HonestTrend15mDry",   PROJECT_DIR / "user_data" / "tradesv3_honest15m_dryrun.sqlite"),
    ("HonestTrend1mMTF",    PROJECT_DIR / "user_data" / "tradesv3_honest1mmtf_dryrun.sqlite"),
    ("HonestTrendFutures",  PROJECT_DIR / "user_data" / "tradesv3_honestfutures15m_dryrun.sqlite"),
    # 1mLive would go here if/when enabled
]


def connect():
    if not DB_URL:
        sys.exit("TIMESCALE_URL not set")
    return psycopg2.connect(DB_URL)


# ---------------------------------------------------------------------------
# 1. SQLite trades → quant.trades
# ---------------------------------------------------------------------------
def sync_bot_trades(conn) -> dict:
    """For each bot DB, import NEW trades since last synced open_date."""
    total = 0
    per_bot = {}
    with conn.cursor() as cur:
        for bot_name, db_path in BOT_DBS:
            if not db_path.exists():
                per_bot[bot_name] = "no DB file"
                continue

            cur.execute(
                f"SELECT max(open_date) FROM {SCHEMA}.trades WHERE bot_name=%s",
                (bot_name,))
            last = cur.fetchone()[0]

            sq = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3)
            sq.row_factory = sqlite3.Row
            try:
                rows = sq.execute("""
                    SELECT id AS trade_id, pair, is_short, strategy,
                           open_date, close_date, open_rate, close_rate,
                           stake_amount, amount, close_profit_abs AS profit_abs,
                           close_profit AS profit_pct, exit_reason, enter_tag,
                           leverage, funding_fees
                    FROM trades
                    ORDER BY open_date
                """).fetchall()
            finally:
                sq.close()

            if last:
                # SQLite open_date strings are like '2026-04-20 19:30:01.397687'
                last_iso = last.isoformat(" ").replace("+00:00", "")
                rows = [r for r in rows if (r["open_date"] or "") > last_iso]

            if not rows:
                per_bot[bot_name] = "up to date (0)"
                continue

            # Upsert (trade_id can be updated as close_date / profit_abs arrive)
            values = [(
                bot_name, r["trade_id"], r["pair"], bool(r["is_short"]),
                r["strategy"],
                _sqlite_dt(r["open_date"]),
                _sqlite_dt(r["close_date"]),
                r["open_rate"], r["close_rate"],
                r["stake_amount"], r["amount"],
                r["profit_abs"], r["profit_pct"],
                r["exit_reason"], r["enter_tag"],
                r["leverage"], r["funding_fees"],
            ) for r in rows]

            psycopg2.extras.execute_values(cur, f"""
                INSERT INTO {SCHEMA}.trades
                  (bot_name, trade_id, pair, is_short, strategy,
                   open_date, close_date, open_rate, close_rate,
                   stake_amount, amount, profit_abs, profit_pct,
                   exit_reason, enter_tag, leverage, funding_fees)
                VALUES %s
                ON CONFLICT (bot_name, trade_id, open_date) DO UPDATE SET
                  close_date   = EXCLUDED.close_date,
                  close_rate   = EXCLUDED.close_rate,
                  profit_abs   = EXCLUDED.profit_abs,
                  profit_pct   = EXCLUDED.profit_pct,
                  exit_reason  = EXCLUDED.exit_reason,
                  funding_fees = EXCLUDED.funding_fees,
                  synced_at    = now()
            """, values)
            total += len(values)
            per_bot[bot_name] = f"+{len(values)} new/updated"
        conn.commit()
    return {"total": total, "per_bot": per_bot}


def _sqlite_dt(s):
    if not s:
        return None
    # SQLite stores without tz; freqtrade uses UTC
    try:
        return datetime.fromisoformat(str(s).replace(" ", "T")).replace(
            tzinfo=timezone.utc) if "+" not in str(s) else datetime.fromisoformat(str(s))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 2. event_dca_state.json → quant.event_dca_triggers
# ---------------------------------------------------------------------------
def sync_event_dca(conn) -> dict:
    f = PROJECT_DIR / "event_dca_state.json"
    if not f.exists():
        return {"total": 0, "note": "no state file"}
    data = json.loads(f.read_text())
    history = data.get("history", [])
    if not history:
        return {"total": 0, "note": "empty history"}

    rows = []
    for h in history:
        ts = h.get("ts")
        if not ts:
            continue
        rows.append((
            datetime.fromisoformat(str(ts).replace("Z", "+00:00")),
            h.get("kind"),
            h.get("price"),
            h.get("severity"),
            h.get("fng"),
            h.get("amount_usdt"),
            h.get("mode", "dry_run"),
        ))
    if not rows:
        return {"total": 0}

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, f"""
            INSERT INTO {SCHEMA}.event_dca_triggers
              (ts, kind, price, severity, fng, amount_usdt, mode)
            VALUES %s
            ON CONFLICT (ts) DO UPDATE SET
              price = EXCLUDED.price,
              severity = EXCLUDED.severity,
              fng = EXCLUDED.fng,
              amount_usdt = EXCLUDED.amount_usdt,
              mode = EXCLUDED.mode
        """, rows)
        conn.commit()
    return {"total": len(rows)}


# ---------------------------------------------------------------------------
# 3. walk_forward_history/*.json → quant.wf_results
# ---------------------------------------------------------------------------
def sync_wf(conn) -> dict:
    wf_dir = PROJECT_DIR / "walk_forward_history"
    if not wf_dir.exists():
        return {"total": 0, "note": "no dir"}

    rows = []
    skipped = 0
    for f in sorted(wf_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        # Older WF JSONs (pre-2026-04) didn't include `strategy`/`timeframe` at
        # the top level; skip those rather than crashing the whole sync.
        if not all(k in data for k in ("run_date", "strategy", "timeframe")):
            skipped += 1
            continue
        run_date = datetime.fromisoformat(
            str(data["run_date"]).replace("Z", "+00:00"))
        strategy = data["strategy"]
        timeframe = data["timeframe"]
        for r in data.get("results", []):
            rows.append((
                run_date, strategy, timeframe, r["label"],
                datetime.strptime(r["start"], "%Y%m%d").date(),
                datetime.strptime(r["end"],   "%Y%m%d").date(),
                r.get("status", "ok"),
                r.get("trades"),
                r.get("avg_profit_pct"),
                r.get("tot_profit_usdt"),
                r.get("tot_profit_pct"),
                str(f),
            ))

    if not rows:
        return {"total": 0}
    with conn.cursor() as cur:
        # wf_results has no natural unique key in schema, so we DELETE+INSERT per source file
        # to keep idempotent without duplicates.
        # For efficiency we just insert; later we can dedupe.
        # Dedup: keep last one per (run_date, strategy, timeframe, window_label)
        cur.execute(f"""
          DELETE FROM {SCHEMA}.wf_results
          WHERE json_source = ANY(%s)
        """, ([r[11] for r in rows],))
        psycopg2.extras.execute_values(cur, f"""
            INSERT INTO {SCHEMA}.wf_results
              (run_date, strategy, timeframe, window_label,
               window_start, window_end, status,
               trades, avg_profit_pct, tot_profit_usdt, tot_profit_pct,
               json_source)
            VALUES %s
        """, rows)
        conn.commit()
    return {"total": len(rows)}


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["trades", "event_dca", "wf"],
                    help="Run only one stage.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    started = datetime.now(timezone.utc)
    out = {"started_at": started.isoformat(), "stages": {}}
    with connect() as conn:
        if not args.only or args.only == "trades":
            out["stages"]["trades"] = sync_bot_trades(conn)
        if not args.only or args.only == "event_dca":
            out["stages"]["event_dca"] = sync_event_dca(conn)
        if not args.only or args.only == "wf":
            out["stages"]["wf"] = sync_wf(conn)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    out["elapsed_sec"] = round(elapsed, 2)

    if args.quiet:
        print(json.dumps(out))
    else:
        print(f"sync complete in {elapsed:.2f}s")
        for stage, r in out["stages"].items():
            print(f"  {stage}: {r}")


if __name__ == "__main__":
    main()
