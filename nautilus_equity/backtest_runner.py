"""Self-service backtest runner (playground Phase 1) — game-box service.

Polls quant.backtest_jobs for queued user-submitted backtests, runs the PREDEFINED
strategy with the user's params over the stored catalogs, and writes quant.backtest_results.
Cloudflare Workers can't run Python/Nautilus, so this is the compute backend.

SECURITY: users pick a predefined strategy + params via a form (validated here); they never
submit code. One job at a time, FOR UPDATE SKIP LOCKED so multiple runners are safe.

Run:  TIMESCALE_URL=postgres://… nautilus_equity/.venv/bin/python nautilus_equity/backtest_runner.py
Env:  TIMESCALE_URL (required), POLL_SEC (default 5), JOB_TIMEOUT_SEC (default 120)

STATUS: honest_trend (equity) + accumulator/donchian (crypto) are wired. The crypto paths reuse
the proven engines in nautilus_crypto/backtest_stats.py (run_accumulator / run_donchian_portfolio,
honest EquityRecorder drawdown). NOT YET DEPLOYED — pending owner sign-off (see PLAYGROUND_PLAN.md).
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import traceback
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
# The crypto engines live in ../nautilus_crypto and import their siblings flat.
sys.path.insert(0, str(_HERE.parent / "nautilus_crypto"))
sys.path.insert(0, str(_HERE.parent / "strategies"))  # findata (any-US-stock daily data)

# --------------------------------------------------------------------------- param validation
# Predefined strategies + the param domains a user may choose. Anything outside → reject.
EQUITY_ASSETS = {"NVDA": "NASDAQ", "AMD": "NASDAQ", "QQQ": "NASDAQ"}
TF_TO_BARS = {"1h": ("1-HOUR-LAST-EXTERNAL", 252 * 7), "1d": ("1-DAY-LAST-EXTERNAL", 252)}
EMA_MIN, EMA_MAX = 5, 400

# Crypto bases the playground may backtest. Must be a subset of backtest_stats._ASSETS AND have
# the feathers the path needs (donchian → *-1h, accumulator → *-1d). Keep in lockstep with
# backtests.ts STRATEGIES.
CRYPTO_ASSETS = ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "LINK")


def _validate_honest_trend(params: dict) -> dict:
    asset = str(params.get("asset", "")).upper()
    tf = str(params.get("tf", "1h")).lower()
    if tf not in TF_TO_BARS:
        raise ValueError("tf must be '1h' or '1d'")
    if asset not in EQUITY_ASSETS:
        # Any-US-stock path (financialdata.net daily bars): validate the ticker and
        # force daily — hourly history only exists for the IB-catalog trio.
        import findata
        if not findata.is_us_symbol(asset):
            raise ValueError(f"unknown US symbol {asset!r} (catalog assets: {sorted(EQUITY_ASSETS)})")
        if tf != "1d":
            raise ValueError(f"{asset}: only '1d' supported (hourly data exists only for {sorted(EQUITY_ASSETS)})")
    fast = int(params.get("ema_fast", 50))
    slow = int(params.get("ema_slow", 100))
    if not (EMA_MIN <= fast < slow <= EMA_MAX):
        raise ValueError(f"need {EMA_MIN} <= ema_fast < ema_slow <= {EMA_MAX}")
    return {"asset": asset, "venue": EQUITY_ASSETS.get(asset, "NASDAQ"), "tf": tf,
            "ema_fast": fast, "ema_slow": slow}


def _validate_accumulator(params: dict) -> dict:
    asset = str(params.get("asset", "")).upper()
    if asset not in CRYPTO_ASSETS:
        raise ValueError(f"asset must be one of {list(CRYPTO_ASSETS)}")
    mode = str(params.get("mode", "smart")).lower()
    if mode not in ("smart", "naive"):
        raise ValueError("mode must be 'smart' or 'naive'")
    base_buy_usd = float(params.get("base_buy_usd", 500.0))
    if not (10.0 <= base_buy_usd <= 100_000.0):
        raise ValueError("base_buy_usd must be in [10, 100000]")
    interval_bars = int(params.get("interval_bars", 7))  # bars between buys (daily bars)
    if not (1 <= interval_bars <= 90):
        raise ValueError("interval_bars must be in [1, 90]")
    return {"asset": asset, "mode": mode, "base_buy_usd": base_buy_usd,
            "interval_bars": interval_bars}


def _validate_donchian(params: dict) -> dict:
    asset = str(params.get("asset", "")).upper()
    if asset not in CRYPTO_ASSETS:
        raise ValueError(f"asset must be one of {list(CRYPTO_ASSETS)}")
    entry_lb = int(params.get("entry_lb", 168))  # breakout lookback (1h bars)
    exit_lb = int(params.get("exit_lb", 72))     # trailing-low exit lookback (1h bars)
    if not (12 <= entry_lb <= 1000):
        raise ValueError("entry_lb must be in [12, 1000]")
    if not (6 <= exit_lb <= entry_lb):
        raise ValueError("exit_lb must be in [6, entry_lb]")
    risk_frac = float(params.get("risk_frac", 0.20))  # fraction of equity deployed on entry
    if not (0.01 <= risk_frac <= 1.0):
        raise ValueError("risk_frac must be in [0.01, 1.0]")
    return {"asset": asset, "entry_lb": entry_lb, "exit_lb": exit_lb, "risk_frac": risk_frac}


# --------------------------------------------------------------------------- strategy dispatch
_CATALOG = None  # lazy ParquetDataCatalog


def _catalog():
    global _CATALOG
    if _CATALOG is None:
        from nautilus_trader.persistence.catalog import ParquetDataCatalog
        _CATALOG = ParquetDataCatalog(str(_HERE / "catalog"))
    return _CATALOG


def _downsample(curve: list, n: int = 80) -> list:
    """Reduce an equity series to ~n evenly-spaced points for a compact sparkline."""
    if not curve:
        return []
    if len(curve) <= n:
        return [round(float(v), 2) for v in curve]
    step = len(curve) / n
    return [round(float(curve[min(int(i * step), len(curve) - 1)]), 2) for i in range(n)]


def run_honest_trend(params: dict) -> dict:
    p = _validate_honest_trend(params)
    if p["asset"] in EQUITY_ASSETS:
        from grid_honest_equity_real import run_one  # IB-catalog path (1h + 1d)
        bar_suffix, ppy = TF_TO_BARS[p["tf"]]
        r = run_one(_catalog(), p["asset"], p["venue"], p["ema_fast"], p["ema_slow"],
                    bar_suffix, ppy)
    else:
        from anystock_backtest import run_any  # any US ticker, findata daily bars
        r = run_any(p["asset"], p["ema_fast"], p["ema_slow"])
    return {
        "return_pct": round(r["ret_pct"], 2),
        "max_dd_pct": round(r["mdd_pct"], 2),
        "sharpe": round(r["sharpe"], 2),
        "calmar": (None if r["calmar"] in (float("inf"), float("-inf")) else round(r["calmar"], 2)),
        "trades": r["fills"],
        "entries": r["entries"],
        "bars": r["bars"],
        "config": p,
        "equity_curve": _downsample(r.get("curve", [])),  # popped out + stored in its own column
    }


def run_accumulator(params: dict) -> dict:
    """Fear-driven smart DCA on real Binance daily bars. Never sells, so round-trip metrics
    (Sharpe/Calmar/maxDD) don't apply — the honest headline is ROI on invested capital, which
    we surface as `return_pct`. `trades` = number of DCA buys."""
    p = _validate_accumulator(params)
    from backtest_stats import run_accumulator as _run  # proven engine (EquityRecorder-free DCA)
    r = _run(p["asset"], base_buy_usd=p["base_buy_usd"], interval_bars=p["interval_bars"],
             mode=p["mode"])
    pr = r.get("params", {})
    return {
        "return_pct": r["total_profit_pct"],   # ROI on invested capital
        "max_dd_pct": None,                     # never-sell DCA: trade-level DD undefined
        "sharpe": None,
        "calmar": None,
        "trades": r["total_trades"],            # = number of buys
        # strategy-specific (DCA): how much was deployed and what was accumulated.
        "invested_usd": pr.get("invested_usd"),
        "coin_qty": pr.get("coin_qty"),
        "period_start": str(r.get("period_start")) if r.get("period_start") else None,
        "period_end": str(r.get("period_end")) if r.get("period_end") else None,
        "config": p,
        "equity_curve": _downsample(r.get("curve", [])),  # DCA accumulation curve (cash + coin×close)
    }


def run_donchian(params: dict) -> dict:
    """Single-asset Donchian breakout on real Binance 1h bars. Honest equity-curve maxDD via
    EquityRecorder; Sharpe/Calmar from the portfolio analyzer + equity curve."""
    p = _validate_donchian(params)
    from backtest_stats import run_donchian_portfolio as _run  # proven engine
    r = _run([p["asset"]], entry_lb=p["entry_lb"], exit_lb=p["exit_lb"],
             risk_frac=p["risk_frac"])
    return {
        "return_pct": r["total_profit_pct"],
        "max_dd_pct": (None if r["max_drawdown_pct"] is None else abs(r["max_drawdown_pct"])),
        "sharpe": r["sharpe"],
        "calmar": r["calmar"],
        "trades": r["total_trades"],
        "win_rate_pct": r.get("win_rate_pct"),
        "period_start": str(r.get("period_start")) if r.get("period_start") else None,
        "period_end": str(r.get("period_end")) if r.get("period_end") else None,
        "config": p,
        "equity_curve": _downsample(r.get("curve", [])),
    }


DISPATCH = {
    "honest_trend": run_honest_trend,
    "accumulator": run_accumulator,
    "donchian": run_donchian,
}


# --------------------------------------------------------------------------- job timeout
class JobTimeout(Exception):
    """Raised when a single backtest job exceeds JOB_TIMEOUT_SEC."""


def _job_timeout_sec() -> int:
    try:
        return max(1, int(os.environ.get("JOB_TIMEOUT_SEC", "120")))
    except ValueError:
        return 120


def _run_with_timeout(fn, params: dict, seconds: int) -> dict:
    """Run fn(params) under a hard SIGALRM deadline. The runner is single-threaded and runs on
    the main thread, so SIGALRM is safe here. On expiry, raise JobTimeout (caught by the job
    error handler); a fast job clears the alarm before it ever fires."""

    def _on_alarm(signum, frame):
        raise JobTimeout(f"job exceeded JOB_TIMEOUT_SEC={seconds}s")

    prev = signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(seconds)
    try:
        return fn(params)
    finally:
        signal.alarm(0)  # clear the alarm whether fn returned or raised
        signal.signal(signal.SIGALRM, prev)  # restore prior handler


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
    timeout = _job_timeout_sec()
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
            metrics = _run_with_timeout(fn, params, timeout)
            equity_curve = metrics.pop("equity_curve", None)  # charted separately from metrics
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO quant.backtest_results (job_id, user_id, metrics, equity_curve)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (job_id) DO UPDATE
                         SET metrics=EXCLUDED.metrics, equity_curve=EXCLUDED.equity_curve""",
                    (job_id, user_id, json.dumps(metrics), json.dumps(equity_curve) if equity_curve else None),
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
    # Recover jobs left 'running' by a previous crashed run (single runner → safe to requeue).
    with conn.cursor() as cur:
        cur.execute("UPDATE quant.backtest_jobs SET status='queued' WHERE status='running'")
        recovered = cur.rowcount
        conn.commit()
    if recovered:
        print(f"backtest_runner: recovered {recovered} stale running job(s) -> queued")
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
