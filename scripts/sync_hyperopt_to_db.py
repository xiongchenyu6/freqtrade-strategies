#!/usr/bin/env python3
"""
Parse all .fthypt (NDJSON) files in user_data/hyperopt_results/ and upsert
epoch summaries to quant.hyperopt_epochs in TimescaleDB.

-- DDL (run once before first sync) ------------------------------------
CREATE TABLE IF NOT EXISTS quant.hyperopt_epochs (
  id TEXT PRIMARY KEY,  -- strategy_name + ':' + file_ts + ':' + epoch
  strategy TEXT NOT NULL,
  file_ts TEXT NOT NULL,  -- timestamp from filename e.g. "2026-04-21_17-44-31"
  epoch INTEGER NOT NULL,
  is_best BOOLEAN,
  is_initial_point BOOLEAN,
  is_random BOOLEAN,
  loss DOUBLE PRECISION,
  -- params
  params JSONB,  -- full params_dict
  -- key metrics
  sharpe DOUBLE PRECISION,
  calmar DOUBLE PRECISION,
  sortino DOUBLE PRECISION,
  sqn DOUBLE PRECISION,
  profit_total DOUBLE PRECISION,
  winrate DOUBLE PRECISION,
  total_trades INTEGER,
  max_drawdown DOUBLE PRECISION,
  holding_avg_hours DOUBLE PRECISION,
  results_explanation TEXT,
  synced_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS hyperopt_epochs_strategy_idx ON quant.hyperopt_epochs(strategy, file_ts);
-- -----------------------------------------------------------------------

Usage:
  sops exec-env secrets.env 'python scripts/sync_hyperopt_to_db.py'
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras


PROJECT_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_DIR / "user_data" / "hyperopt_results"
SCHEMA = os.environ.get("TIMESCALE_SCHEMA", "quant")
DB_URL = os.environ.get("TIMESCALE_URL")

# Filename pattern: strategy_<StrategyName>_<YYYY-MM-DD_HH-MM-SS>.fthypt
_FILENAME_RE = re.compile(r"^strategy_(.+?)_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.fthypt$")


def connect():
    if not DB_URL:
        sys.exit("TIMESCALE_URL not set")
    return psycopg2.connect(DB_URL)


def parse_file(path: Path) -> tuple[str, str, list[dict]]:
    """Return (strategy_name, file_ts, list_of_parsed_rows)."""
    m = _FILENAME_RE.match(path.name)
    if not m:
        return "", "", []
    strategy = m.group(1)
    file_ts = m.group(2)

    rows = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue

        rm = d.get("results_metrics")
        if not rm or not isinstance(rm, dict):
            continue

        epoch = d.get("current_epoch")
        if epoch is None:
            continue

        # holding_avg_s is in seconds; convert to hours
        holding_s = rm.get("holding_avg_s")
        holding_hours = (holding_s / 3600.0) if isinstance(holding_s, (int, float)) else None

        row_id = f"{strategy}:{file_ts}:{epoch}"
        rows.append({
            "id": row_id,
            "strategy": strategy,
            "file_ts": file_ts,
            "epoch": int(epoch),
            "is_best": bool(d.get("is_best", False)),
            "is_initial_point": bool(d.get("is_initial_point", False)),
            "is_random": bool(d.get("is_random", False)),
            "loss": d.get("loss"),
            "params": json.dumps(d.get("params_dict") or {}),
            "sharpe": rm.get("sharpe"),
            "calmar": rm.get("calmar"),
            "sortino": rm.get("sortino"),
            "sqn": rm.get("sqn"),
            "profit_total": rm.get("profit_total"),
            "winrate": rm.get("winrate"),
            "total_trades": rm.get("total_trades"),
            "max_drawdown": rm.get("max_drawdown_account"),
            "holding_avg_hours": holding_hours,
            "results_explanation": d.get("results_explanation"),
        })
    return strategy, file_ts, rows


def sync_hyperopt(conn) -> dict:
    files = sorted(RESULTS_DIR.glob("*.fthypt"))
    if not files:
        return {"files": 0, "epochs": 0, "note": f"no .fthypt files in {RESULTS_DIR}"}

    total_epochs = 0
    files_processed = 0
    per_file: dict[str, str] = {}

    with conn.cursor() as cur:
        for path in files:
            strategy, file_ts, rows = parse_file(path)
            if not rows:
                per_file[path.name] = "skipped (parse error or no valid epochs)"
                continue

            values = [
                (
                    r["id"], r["strategy"], r["file_ts"], r["epoch"],
                    r["is_best"], r["is_initial_point"], r["is_random"],
                    r["loss"], r["params"],
                    r["sharpe"], r["calmar"], r["sortino"], r["sqn"],
                    r["profit_total"], r["winrate"], r["total_trades"],
                    r["max_drawdown"], r["holding_avg_hours"],
                    r["results_explanation"],
                )
                for r in rows
            ]

            psycopg2.extras.execute_values(cur, f"""
                INSERT INTO {SCHEMA}.hyperopt_epochs
                  (id, strategy, file_ts, epoch,
                   is_best, is_initial_point, is_random,
                   loss, params,
                   sharpe, calmar, sortino, sqn,
                   profit_total, winrate, total_trades,
                   max_drawdown, holding_avg_hours,
                   results_explanation)
                VALUES %s
                ON CONFLICT (id) DO UPDATE SET
                  is_best             = EXCLUDED.is_best,
                  is_initial_point    = EXCLUDED.is_initial_point,
                  is_random           = EXCLUDED.is_random,
                  loss                = EXCLUDED.loss,
                  params              = EXCLUDED.params,
                  sharpe              = EXCLUDED.sharpe,
                  calmar              = EXCLUDED.calmar,
                  sortino             = EXCLUDED.sortino,
                  sqn                 = EXCLUDED.sqn,
                  profit_total        = EXCLUDED.profit_total,
                  winrate             = EXCLUDED.winrate,
                  total_trades        = EXCLUDED.total_trades,
                  max_drawdown        = EXCLUDED.max_drawdown,
                  holding_avg_hours   = EXCLUDED.holding_avg_hours,
                  results_explanation = EXCLUDED.results_explanation,
                  synced_at           = now()
            """, values)

            files_processed += 1
            total_epochs += len(rows)
            per_file[path.name] = f"+{len(rows)} epochs"

        conn.commit()

    return {
        "files": files_processed,
        "epochs": total_epochs,
        "per_file": per_file,
    }


def main():
    started = datetime.now(timezone.utc)
    print(f"syncing hyperopt results from {RESULTS_DIR}")
    conn = connect()
    try:
        result = sync_hyperopt(conn)
    finally:
        conn.close()

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    print(f"done in {elapsed:.2f}s — {result['files']} files, {result['epochs']} epochs")
    for fname, note in result.get("per_file", {}).items():
        print(f"  {fname}: {note}")


if __name__ == "__main__":
    main()
