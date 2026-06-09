"""Self-service backtest runner (playground Phase 1) — game-box service.

Polls quant.backtest_jobs for queued user-submitted backtests, runs the PREDEFINED
strategy with the user's params over the stored catalogs, and writes quant.backtest_results.
Cloudflare Workers can't run Python/Nautilus, so this is the compute backend.

SECURITY: users pick a predefined strategy + params via a form (validated here); they never
submit code. One job at a time, FOR UPDATE SKIP LOCKED so multiple runners are safe.

Run:  TIMESCALE_URL=postgres://… nautilus_equity/.venv/bin/python nautilus_equity/backtest_runner.py
Env:  TIMESCALE_URL (required), POLL_SEC (default 5), JOB_TIMEOUT_SEC (default 120)

STATUS: skeleton. honest_trend is wired (reuses grid_honest_equity_real.run_one); accumulator
and donchian are stubbed. NOT YET DEPLOYED — pending owner sign-off (see PLAYGROUND_PLAN.md).
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

# --------------------------------------------------------------------------- param validation
# Predefined strategies + the param domains a user may choose. Anything outside → reject.
EQUITY_ASSETS = {"NVDA": "NASDAQ", "AMD": "NASDAQ", "QQQ": "NASDAQ"}
TF_TO_BARS = {"1h": ("1-HOUR-LAST-EXTERNAL", 252 * 7), "1d": ("1-DAY-LAST-EXTERNAL", 252)}
EMA_MIN, EMA_MAX = 5, 400


def _validate_honest_trend(params: dict) -> dict:
    asset = str(params.get("asset", "")).upper()
    if asset not in EQUITY_ASSETS:
        raise ValueError(f"asset must be one of {sorted(EQUITY_ASSETS)}")
    tf = str(params.get("tf", "1h")).lower()
    if tf not in TF_TO_BARS:
        raise ValueError("tf must be '1h' or '1d'")
    fast = int(params.get("ema_fast", 50))
    slow = int(params.get("ema_slow", 100))
    if not (EMA_MIN <= fast < slow <= EMA_MAX):
        raise ValueError(f"need {EMA_MIN} <= ema_fast < ema_slow <= {EMA_MAX}")
    return {"asset": asset, "venue": EQUITY_ASSETS[asset], "tf": tf,
            "ema_fast": fast, "ema_slow": slow}


# --------------------------------------------------------------------------- strategy dispatch
_CATALOG = None  # lazy ParquetDataCatalog


def _catalog():
    global _CATALOG
    if _CATALOG is None:
        from nautilus_trader.persistence.catalog import ParquetDataCatalog
        _CATALOG = ParquetDataCatalog(str(_HERE / "catalog"))
    return _CATALOG


def run_honest_trend(params: dict) -> dict:
    p = _validate_honest_trend(params)
    from grid_honest_equity_real import run_one  # reuse the validated backtest path
    bar_suffix, ppy = TF_TO_BARS[p["tf"]]
    r = run_one(_catalog(), p["asset"], p["venue"], p["ema_fast"], p["ema_slow"],
                bar_suffix, ppy)
    return {
        "return_pct": round(r["ret_pct"], 2),
        "max_dd_pct": round(r["mdd_pct"], 2),
        "sharpe": round(r["sharpe"], 2),
        "calmar": (None if r["calmar"] in (float("inf"), float("-inf")) else round(r["calmar"], 2)),
        "trades": r["fills"],
        "entries": r["entries"],
        "bars": r["bars"],
        "config": p,
    }


DISPATCH = {
    "honest_trend": run_honest_trend,
    # TODO(playground Phase 1): wire crypto strategies over the crypto catalogs.
    "accumulator": lambda p: (_ for _ in ()).throw(NotImplementedError("accumulator: TODO")),
    "donchian": lambda p: (_ for _ in ()).throw(NotImplementedError("donchian: TODO")),
}


# --------------------------------------------------------------------------- job loop
def _claim_job(cur):
    """Atomically grab one queued job and mark it running. Returns (id, strategy, params) | None."""
    cur.execute(
        """
        UPDATE quant.backtest_jobs SET status='running'
        WHERE id = (SELECT id FROM quant.backtest_jobs WHERE status='queued'
                    ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
        RETURNING id, strategy, params, user_id
        """
    )
    return cur.fetchone()


def _run_loop(conn):
    poll = float(os.environ.get("POLL_SEC", "5"))
    while True:
        with conn.cursor() as cur:
            job = _claim_job(cur)
            conn.commit()
        if job is None:
            time.sleep(poll)
            continue
        job_id, strategy, params, user_id = job
        params = params if isinstance(params, dict) else json.loads(params or "{}")
        try:
            fn = DISPATCH.get(strategy)
            if fn is None:
                raise ValueError(f"unknown strategy {strategy!r}")
            metrics = fn(params)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO quant.backtest_results (job_id, user_id, metrics)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (job_id) DO UPDATE SET metrics=EXCLUDED.metrics""",
                    (job_id, user_id, json.dumps(metrics)),
                )
                cur.execute("UPDATE quant.backtest_jobs SET status='done' WHERE id=%s", (job_id,))
                conn.commit()
            print(f"[done] {job_id} {strategy} -> {metrics.get('return_pct')}%")
        except Exception as e:  # noqa: BLE001 — surface to the user, keep the runner alive
            traceback.print_exc()
            with conn.cursor() as cur:
                cur.execute("UPDATE quant.backtest_jobs SET status='error', error=%s WHERE id=%s",
                            (str(e)[:500], job_id))
                conn.commit()
            print(f"[error] {job_id} {strategy}: {e}")


def main() -> int:
    url = os.environ.get("TIMESCALE_URL")
    if not url:
        print("TIMESCALE_URL not set", file=sys.stderr)
        return 2
    import psycopg2
    conn = psycopg2.connect(url)
    conn.autocommit = False
    print("backtest_runner: polling quant.backtest_jobs …")
    try:
        _run_loop(conn)
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
