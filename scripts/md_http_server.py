#!/usr/bin/env python3
"""
HTTP server that serves static files AND renders .md as HTML on the fly.

Used by crypto-dashboard.service to replace `python -m http.server 3001`.
Keeps URLs clean — `/docs/X.md` returns rendered HTML with dark theme.

Features:
  - Markdown → HTML with tables, fenced code, TOC
  - Pygments-free syntax highlighting via highlight.js CDN
  - Dark GitHub-ish theme matching dashboard/index.html
  - UTF-8 charset headers (fixes mojibake for .md served as text)
  - Everything else falls through to SimpleHTTPRequestHandler
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, parse_qs

import markdown

try:
    import psycopg2
    import psycopg2.pool
except ImportError:  # let the rest of the server work without psycopg2
    psycopg2 = None


SERVE_ROOT = Path.cwd()

MD_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/styles/github-dark.min.css">
<style>
  * {{ box-sizing: border-box; }}
  body {{
    background: #0d1117;
    color: #c9d1d9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    line-height: 1.6;
    margin: 0;
    padding: 0;
  }}
  .topbar {{
    background: #161b22;
    border-bottom: 1px solid #30363d;
    padding: 10px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 13px;
    position: sticky;
    top: 0;
    z-index: 10;
  }}
  .topbar a {{ color: #58a6ff; text-decoration: none; margin-right: 18px; }}
  .topbar a:hover {{ text-decoration: underline; }}
  .topbar .path {{ color: #8b949e; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  .container {{ max-width: 920px; margin: 0 auto; padding: 32px 24px 80px; }}
  h1, h2, h3, h4, h5, h6 {{ color: #f0f6fc; margin: 1.5em 0 0.6em; line-height: 1.25; }}
  h1 {{ font-size: 28px; border-bottom: 1px solid #30363d; padding-bottom: 10px; }}
  h2 {{ font-size: 22px; border-bottom: 1px solid #21262d; padding-bottom: 6px; }}
  h3 {{ font-size: 18px; }}
  p, li {{ font-size: 15px; }}
  a {{ color: #58a6ff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  code {{
    background: #161b22;
    color: #79c0ff;
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 0.88em;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }}
  pre {{
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 14px 16px;
    overflow-x: auto;
    margin: 14px 0;
  }}
  pre code {{
    background: transparent;
    padding: 0;
    color: #c9d1d9;
    font-size: 13px;
  }}
  table {{
    border-collapse: collapse;
    margin: 14px 0;
    font-size: 14px;
    display: block;
    overflow-x: auto;
    max-width: 100%;
  }}
  th, td {{
    border: 1px solid #30363d;
    padding: 8px 12px;
    text-align: left;
  }}
  th {{ background: #161b22; color: #f0f6fc; }}
  tr:nth-child(even) {{ background: #0d1117; }}
  tr:nth-child(odd)  {{ background: #11161d; }}
  blockquote {{
    border-left: 4px solid #30363d;
    margin: 14px 0;
    padding: 8px 16px;
    color: #8b949e;
    background: #0f141a;
  }}
  hr {{ border: none; border-top: 1px solid #30363d; margin: 28px 0; }}
  ul, ol {{ padding-left: 28px; }}
  li {{ margin: 3px 0; }}
  img {{ max-width: 100%; border-radius: 6px; }}
  .toc {{
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 14px 20px;
    margin: 20px 0;
    font-size: 13px;
  }}
  .toc ul {{ padding-left: 20px; }}
  .toc li {{ margin: 2px 0; }}
  details summary {{ cursor: pointer; color: #58a6ff; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/lib/core.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/lib/languages/python.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/lib/languages/bash.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/lib/languages/json.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/lib/languages/yaml.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/lib/languages/javascript.min.js"></script>
</head>
<body>
<div class="topbar">
  <div>
    <a href="/">🏠 主页</a>
    <a href="/docs/">📚 docs/</a>
    <a href="/reports/">📈 reports/</a>
  </div>
  <span class="path">{path}</span>
</div>
<div class="container">
{content}
</div>
<script>
  document.querySelectorAll('pre code').forEach((el) => {{
    try {{ hljs.highlightElement(el); }} catch(e) {{}}
  }});
</script>
</body>
</html>
"""


def render_markdown(md_path: Path, url_path: str) -> str:
    text = md_path.read_text(encoding="utf-8")

    md = markdown.Markdown(
        extensions=[
            "fenced_code",
            "tables",
            "toc",
            "sane_lists",
            "attr_list",
            "md_in_html",
        ],
        extension_configs={
            "toc": {"title": "目录", "toc_depth": "2-4"},
        },
    )
    content_html = md.convert(text)

    # Derive title from first H1 or filename
    title = md_path.stem
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            break

    return MD_TEMPLATE.format(
        title=html_lib.escape(title),
        path=html_lib.escape(url_path),
        content=content_html,
    )


BOT_DBS = [
    {"name": "15m spot long", "port": 8082,
     "db": "user_data/tradesv3_honest15m_dryrun.sqlite",
     "strategy": "HonestTrend15mDry"},
    {"name": "1m MTF spot",   "port": 8083,
     "db": "user_data/tradesv3_honest1mmtf_dryrun.sqlite",
     "strategy": "HonestTrend1mMTF"},
    {"name": "Futures L+S",   "port": 8084,
     "db": "user_data/tradesv3_honestfutures15m_dryrun.sqlite",
     "strategy": "HonestTrendFutures"},
]


def _db_stats(db_path: Path) -> dict:
    """Read trade stats from a freqtrade sqlite DB."""
    if not db_path.exists():
        return {"exists": False}
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT pair, is_open, is_short, open_rate, close_rate, amount,
                   stake_amount, close_profit, close_profit_abs, realized_profit,
                   open_date, close_date, exit_reason, enter_tag, funding_fees, leverage
            FROM trades
            ORDER BY open_date DESC
        """).fetchall()
        con.close()
    except Exception as e:
        return {"exists": True, "error": str(e)}

    trades = [dict(r) for r in rows]
    closed = [t for t in trades if not t["is_open"]]
    open_ = [t for t in trades if t["is_open"]]
    total_profit = sum((t.get("close_profit_abs") or 0.0) for t in closed)
    wins = sum(1 for t in closed if (t.get("close_profit") or 0) > 0)
    losses = sum(1 for t in closed if (t.get("close_profit") or 0) <= 0)
    return {
        "exists": True,
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "open_trades": len(open_),
        "wins": wins, "losses": losses,
        "win_rate": round(wins / len(closed) * 100, 1) if closed else None,
        "total_profit_abs": round(total_profit, 2),
        "recent_trades": trades[:10],
    }


def api_bots_summary() -> bytes:
    project = Path.cwd()
    bots = []
    for b in BOT_DBS:
        stats = _db_stats(project / b["db"])
        bots.append({**b, **stats})
    grand = {
        "total_closed":   sum(b.get("closed_trades", 0) or 0 for b in bots),
        "total_open":     sum(b.get("open_trades", 0) or 0   for b in bots),
        "total_profit":   round(sum(b.get("total_profit_abs", 0) or 0 for b in bots), 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload = {"bots": bots, "grand": grand}
    return json.dumps(payload, default=str).encode("utf-8")


def api_event_dca_state() -> bytes:
    """Passthrough wrapper around event_dca_state.json, with default if missing."""
    p = Path.cwd() / "event_dca_state.json"
    if p.exists():
        try:
            return p.read_bytes()
        except Exception:
            pass
    return json.dumps({
        "last_trigger_ts": 0,
        "month_key": datetime.now(timezone.utc).strftime("%Y-%m"),
        "month_spend": 0.0,
        "month_count": 0,
        "history": [],
        "no_state_file": True,
    }).encode("utf-8")


def api_strategy_params() -> bytes:
    """List all strategy .json files with their current params."""
    strat_dir = Path.cwd() / "strategies"
    files = []
    for p in sorted(strat_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            files.append({
                "file": p.name,
                "strategy_name": data.get("strategy_name", p.stem),
                "export_time": data.get("export_time"),
                "params": data.get("params", {}),
            })
        except Exception as e:
            files.append({"file": p.name, "error": str(e)})
    return json.dumps({"strategies": files}).encode("utf-8")


WRITE_ROUTES: dict = {}


def api_save_strategy_params(body: bytes) -> tuple[int, bytes]:
    try:
        payload = json.loads(body)
    except Exception as e:
        return 400, json.dumps({"error": f"invalid json: {e}"}).encode()

    fname = payload.get("file", "")
    new_params = payload.get("params")
    if not fname or not fname.endswith(".json") or "/" in fname or ".." in fname:
        return 400, json.dumps({"error": "invalid filename"}).encode()
    if not isinstance(new_params, dict):
        return 400, json.dumps({"error": "params must be dict"}).encode()

    strat_dir = Path.cwd() / "strategies"
    p = strat_dir / fname
    if not p.exists():
        return 404, json.dumps({"error": "not found"}).encode()

    # Read current, update params, write back atomically
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data["params"] = new_params
        data["export_time"] = datetime.now(timezone.utc).isoformat()
        # Also take a backup copy next to it
        backup = p.with_suffix(".json.bak")
        backup.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=4, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
        return 200, json.dumps({"ok": True, "file": fname,
                                "backup": backup.name}).encode()
    except Exception as e:
        return 500, json.dumps({"error": str(e)}).encode()


_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_JOBS_DIR = Path.cwd() / "logs" / "backtest_jobs"

# --- TimescaleDB pool (optional; falls back to 503 if URL missing) ---
_TS_POOL = None
_TS_SCHEMA = os.environ.get("TIMESCALE_SCHEMA", "quant")


def _ts_pool():
    global _TS_POOL
    if _TS_POOL is not None:
        return _TS_POOL
    url = os.environ.get("TIMESCALE_URL")
    if not url or psycopg2 is None:
        return None
    try:
        _TS_POOL = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=5, dsn=url, connect_timeout=5)
        return _TS_POOL
    except Exception as e:
        sys.stderr.write(f"[timescale] pool init failed: {e}\n")
        return None


def _ts_query(sql: str, params: tuple = ()) -> list[dict]:
    pool = _ts_pool()
    if pool is None:
        raise RuntimeError("TIMESCALE_URL not configured or psycopg2 unavailable")
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        pool.putconn(conn)


def _pick_granularity(span_minutes: float, max_points: int) -> tuple[str, str]:
    """Return (view_or_table, bucket_col_name)."""
    target_min = max(1, span_minutes / max_points)
    if   target_min <= 5:    return f"{_TS_SCHEMA}.ohlc",     "ts"       # 1m raw
    elif target_min <= 30:   return f"{_TS_SCHEMA}.ohlc_15m", "bucket"
    elif target_min <= 300:  return f"{_TS_SCHEMA}.ohlc_1h",  "bucket"
    else:                    return f"{_TS_SCHEMA}.ohlc_1d",  "bucket"


def api_ts_ohlc(query: str) -> tuple[int, bytes]:
    """GET /api/ts/ohlc?pair=BTC/USDT&from=...&to=...&max_points=2000"""
    q = {k: v[0] for k, v in parse_qs(query).items()}
    pair = q.get("pair", "BTC/USDT")
    try:
        t_from = datetime.fromisoformat(q.get("from", "").replace("Z", "+00:00"))
        t_to   = datetime.fromisoformat(q.get("to", "").replace("Z", "+00:00"))
    except Exception:
        # Default: last 30 days
        t_to   = datetime.now(timezone.utc)
        t_from = t_to - timedelta(days=30)
    max_points = int(q.get("max_points", "2000"))
    max_points = min(max_points, 10000)  # hard cap to protect DB

    span_min = (t_to - t_from).total_seconds() / 60
    if span_min <= 0:
        return 400, json.dumps({"error": "invalid range"}).encode()
    source, bucket_col = _pick_granularity(span_min, max_points)

    if source.endswith("ohlc"):
        # raw 1m table: `tf='1m'` filter + column name is `ts`
        sql = (
            f"SELECT ts AS bucket, open, high, low, close, volume "
            f"FROM {source} "
            f"WHERE pair=%s AND tf='1m' AND ts >= %s AND ts < %s "
            f"ORDER BY ts"
        )
    else:
        sql = (
            f"SELECT bucket, open, high, low, close, volume "
            f"FROM {source} "
            f"WHERE pair=%s AND bucket >= %s AND bucket < %s "
            f"ORDER BY bucket"
        )
    try:
        rows = _ts_query(sql, (pair, t_from, t_to))
    except Exception as e:
        return 503, json.dumps({"error": str(e)}).encode()
    # Convert datetimes to ISO strings
    for r in rows:
        r["bucket"] = r["bucket"].isoformat() if r.get("bucket") else None
        for k in ("open", "high", "low", "close", "volume"):
            if r.get(k) is not None:
                r[k] = float(r[k])
    payload = {
        "pair": pair,
        "from": t_from.isoformat(),
        "to":   t_to.isoformat(),
        "source": source,
        "granularity_minutes": (span_min / max(1, len(rows))),
        "rows": rows,
    }
    return 200, json.dumps(payload).encode()


def api_ts_pairs() -> bytes:
    try:
        rows = _ts_query(f"SELECT DISTINCT pair FROM {_TS_SCHEMA}.ohlc ORDER BY pair")
    except Exception as e:
        return json.dumps({"error": str(e)}).encode()
    return json.dumps({"pairs": [r["pair"] for r in rows]}).encode()


def api_backtest_runs(query: str) -> tuple[int, bytes]:
    """GET /api/backtest-runs?strategy=X&limit=100"""
    q = {k: v[0] for k, v in parse_qs(query).items()}
    strategy = q.get("strategy")
    limit = min(int(q.get("limit", "100")), 500)

    where = "WHERE 1=1"
    params: list = []
    if strategy:
        where += " AND strategy = %s"
        params.append(strategy)

    sql = f"""
        SELECT id, job_id, strategy, timeframe, timerange,
               started_at, finished_at, duration_sec,
               total_trades, wins, losses, win_rate_pct,
               total_profit_pct, total_profit_abs,
               max_drawdown_pct, calmar, sharpe, sortino, profit_factor,
               pairs, imported_at
        FROM {_TS_SCHEMA}.backtest_runs
        {where}
        ORDER BY COALESCE(started_at, imported_at) DESC
        LIMIT %s
    """
    params.append(limit)
    try:
        rows = _ts_query(sql, tuple(params))
    except Exception as e:
        return 503, json.dumps({"error": str(e)}).encode()
    for r in rows:
        for k in ("started_at", "finished_at", "imported_at"):
            if r.get(k):
                r[k] = r[k].isoformat()
        for k in ("total_profit_pct", "total_profit_abs", "max_drawdown_pct",
                  "calmar", "sharpe", "sortino", "profit_factor",
                  "duration_sec", "win_rate_pct"):
            if r.get(k) is not None:
                r[k] = float(r[k])
    return 200, json.dumps({"runs": rows}).encode()


def api_backtest_run_trades(query: str) -> tuple[int, bytes]:
    """GET /api/backtest-run-trades?id=N&limit=5000"""
    q = {k: v[0] for k, v in parse_qs(query).items()}
    run_id = q.get("id")
    if not run_id or not run_id.isdigit():
        return 400, json.dumps({"error": "id required"}).encode()
    limit = min(int(q.get("limit", "5000")), 10000)
    sql = f"""
        SELECT trade_id, pair, is_short, open_date, close_date,
               open_rate, close_rate, stake_amount, profit_abs, profit_pct,
               exit_reason, enter_tag, trade_duration_min
        FROM {_TS_SCHEMA}.backtest_trades
        WHERE run_id = %s
        ORDER BY open_date
        LIMIT %s
    """
    try:
        rows = _ts_query(sql, (int(run_id), limit))
    except Exception as e:
        return 503, json.dumps({"error": str(e)}).encode()
    for r in rows:
        for k in ("open_date", "close_date"):
            if r.get(k):
                r[k] = r[k].isoformat()
        for k in ("open_rate", "close_rate", "stake_amount",
                  "profit_abs", "profit_pct"):
            if r.get(k) is not None:
                r[k] = float(r[k])
    return 200, json.dumps({"run_id": int(run_id), "trades": rows}).encode()


def api_ts_status() -> bytes:
    if _ts_pool() is None:
        return json.dumps({"ok": False, "reason": "TIMESCALE_URL not set"}).encode()
    try:
        rows = _ts_query(f"""
          SELECT pair, tf, count(*) AS rows, min(ts) AS first_ts, max(ts) AS last_ts
          FROM {_TS_SCHEMA}.ohlc GROUP BY pair, tf ORDER BY pair""")
        for r in rows:
            r["first_ts"] = r["first_ts"].isoformat() if r.get("first_ts") else None
            r["last_ts"]  = r["last_ts"].isoformat()  if r.get("last_ts")  else None
        return json.dumps({"ok": True, "pairs": rows}).encode()
    except Exception as e:
        return json.dumps({"ok": False, "reason": str(e)}).encode()

ALLOWED_STRATEGIES = {
    "HonestTrend15mDry", "HonestTrend1mMTF",
    "HonestTrend1mLive", "HonestTrendFutures",
}
ALLOWED_CONFIGS = {
    "config_backtest_15m_alts_a5.json",
    "config_backtest_15m_futures_a5.json",
    "config_backtest_15m_btceth.json",
    "config_backtest_15m.json",
    "config_backtest_1m.json",
    "config_backtest_1m_btceth.json",
    "config_backtest_honest.json",
}
TIMERANGE_RE = re.compile(r"^\d{8}-\d{8}$|^\d{8}-$|^-\d{8}$|^$")


def api_backtest_list_options() -> bytes:
    return json.dumps({
        "strategies": sorted(ALLOWED_STRATEGIES),
        "configs":    sorted(ALLOWED_CONFIGS),
    }).encode("utf-8")


def api_backtest_jobs() -> bytes:
    with _JOBS_LOCK:
        jobs = [
            {k: v for k, v in j.items() if k != "_proc"}
            for j in sorted(_JOBS.values(), key=lambda j: j["started_at"], reverse=True)
        ]
    return json.dumps({"jobs": jobs}).encode("utf-8")


def api_backtest_job_log(job_id: str) -> tuple[int, bytes]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        return 404, json.dumps({"error": "job not found"}).encode()
    log_path = Path(job["log_path"])
    if not log_path.exists():
        return 200, json.dumps({"job": {k: v for k, v in job.items() if k != "_proc"},
                                "log": ""}).encode()
    log = log_path.read_text(encoding="utf-8", errors="replace")
    # Trim excessive logs to last 200KB
    if len(log) > 200_000:
        log = "…(head truncated)\n" + log[-200_000:]
    return 200, json.dumps({"job": {k: v for k, v in job.items() if k != "_proc"},
                            "log": log}).encode()


def _run_backtest(job: dict):
    """Subprocess runner — writes log file, updates job state, auto-imports to DB."""
    cmd = job["cmd"]
    log_path = Path(job["log_path"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("w", encoding="utf-8") as lf:
            lf.write(f"$ {' '.join(cmd)}\n\n")
            lf.flush()
            proc = subprocess.Popen(
                cmd, stdout=lf, stderr=subprocess.STDOUT,
                cwd=str(Path.cwd()),
                env={**os.environ,
                     "PYTHONPATH": str(Path.cwd().parent / "freqtrade")},
            )
            with _JOBS_LOCK:
                job["_proc"] = proc
                job["pid"] = proc.pid
            rc = proc.wait()
            with _JOBS_LOCK:
                job["return_code"] = rc
                job["status"] = "ok" if rc == 0 else "failed"
                job["finished_at"] = datetime.now(timezone.utc).isoformat()

        # Auto-import into Timescale if success
        if rc == 0 and os.environ.get("TIMESCALE_URL"):
            try:
                latest = _find_latest_zip_after(
                    datetime.fromisoformat(job["started_at"]))
                if latest:
                    import_rc = subprocess.run(
                        [sys.executable,
                         str(Path.cwd() / "scripts" / "import_backtest_zip.py"),
                         "--zip", str(latest),
                         "--job-id", job["job_id"]],
                        cwd=str(Path.cwd()),
                        env={**os.environ,
                             "PYTHONPATH": str(Path.cwd().parent / "freqtrade")},
                        capture_output=True, text=True, timeout=60,
                    )
                    with log_path.open("a", encoding="utf-8") as lf:
                        lf.write("\n\n=== auto-import ===\n")
                        lf.write(import_rc.stdout)
                        if import_rc.stderr:
                            lf.write(import_rc.stderr)
                    with _JOBS_LOCK:
                        job["imported"] = import_rc.returncode == 0
                        job["zip_path"] = str(latest)
                else:
                    with log_path.open("a", encoding="utf-8") as lf:
                        lf.write("\n\n[auto-import] no new zip found\n")
            except Exception as e:
                with log_path.open("a", encoding="utf-8") as lf:
                    lf.write(f"\n\n[auto-import] error: {e}\n")
    except Exception as e:
        with _JOBS_LOCK:
            job["status"] = "error"
            job["error"] = str(e)
            job["finished_at"] = datetime.now(timezone.utc).isoformat()


def _find_latest_zip_after(started_at: datetime) -> Path | None:
    backtest_dir = Path.cwd() / "user_data" / "backtest_results"
    if not backtest_dir.exists():
        return None
    zips = sorted(backtest_dir.glob("*.zip"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for z in zips:
        mt = datetime.fromtimestamp(z.stat().st_mtime, tz=timezone.utc)
        if mt >= started_at:
            return z
    return None


def api_backtest_start(body: bytes) -> tuple[int, bytes]:
    try:
        req = json.loads(body)
    except Exception:
        return 400, json.dumps({"error": "invalid json"}).encode()

    strategy  = req.get("strategy", "")
    config    = req.get("config", "")
    timerange = req.get("timerange", "")
    if strategy not in ALLOWED_STRATEGIES:
        return 400, json.dumps({"error": f"strategy not allowed: {strategy}"}).encode()
    if config not in ALLOWED_CONFIGS:
        return 400, json.dumps({"error": f"config not allowed: {config}"}).encode()
    if not TIMERANGE_RE.match(timerange):
        return 400, json.dumps({"error": "timerange must match YYYYMMDD-YYYYMMDD"}).encode()

    # Enforce concurrent job limit (resource management)
    with _JOBS_LOCK:
        active = [j for j in _JOBS.values() if j["status"] == "running"]
    if len(active) >= 2:
        return 429, json.dumps({"error": "2 jobs already running; wait"}).encode()

    job_id = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc).isoformat()
    python_bin = sys.executable
    cmd = [
        python_bin, "-m", "freqtrade", "backtesting",
        "--strategy", strategy,
        "--config", f"configs/backtest/{config}",
        "--datadir", "user_data/data/binance",
        "--user-data-dir", "user_data",
        "--strategy-path", "strategies",
        "--cache", "none",
    ]
    if timerange:
        cmd += ["--timerange", timerange]

    log_path = _JOBS_DIR / f"{job_id}.log"
    job = {
        "job_id": job_id,
        "strategy": strategy, "config": config, "timerange": timerange,
        "cmd": cmd, "log_path": str(log_path),
        "started_at": now, "status": "running",
        "pid": None,
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = job
    threading.Thread(target=_run_backtest, args=(job,), daemon=True).start()
    return 200, json.dumps({"ok": True, "job_id": job_id}).encode()


def api_backtest_job(query: str) -> bytes:
    """GET /api/backtest-job?id=xxx"""
    job_id = ""
    for p in query.split("&"):
        if p.startswith("id="):
            job_id = p[3:]
    status, body = api_backtest_job_log(job_id)
    return body  # status always 200 here from our code; errors encoded as json


def _api_backtest_job_wrapper() -> bytes:
    # Placeholder; real handler is dispatched below with query parsing
    return b"{}"


API_ROUTES = {
    "/api/bots-summary":            api_bots_summary,
    "/api/event-dca-state":         api_event_dca_state,
    "/api/strategy-params":         api_strategy_params,
    "/api/backtest-options":        api_backtest_list_options,
    "/api/backtest-jobs":           api_backtest_jobs,
    "/api/ts/pairs":                api_ts_pairs,
    "/api/ts/status":               api_ts_status,
    # /api/backtest-job, /api/ts/ohlc handled specially (need query string)
}
WRITE_ROUTES = {
    "/api/strategy-params":         api_save_strategy_params,
    "/api/backtest-start":          api_backtest_start,
}


class MDRequestHandler(SimpleHTTPRequestHandler):
    """Serve static files; render .md as HTML; expose small read-only JSON API."""

    def do_POST(self):
        route = self.path.split("?", 1)[0]
        handler = WRITE_ROUTES.get(route)
        if not handler:
            self.send_error(404, "Not Found")
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(n) if n else b""
            status, resp = handler(body)
        except Exception as e:
            self.send_error(500, f"{e}")
            return
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(resp)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(resp)

    def send_head(self):
        # API endpoints — JSON responses
        route = self.path.split("?", 1)[0]
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        if route in API_ROUTES:
            try:
                body = API_ROUTES[route]()
            except Exception as e:
                self.send_error(500, f"API error: {e}")
                return None
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return BytesIO(body)
        if route == "/api/backtest-job":
            body = api_backtest_job(query)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return BytesIO(body)
        if route == "/api/backtest-runs":
            status, body = api_backtest_runs(query)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=10")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return BytesIO(body)
        if route == "/api/backtest-run-trades":
            status, body = api_backtest_run_trades(query)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return BytesIO(body)
        if route == "/api/ts/ohlc":
            status, body = api_ts_ohlc(query)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=30")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return BytesIO(body)

        path = self.translate_path(self.path)
        # SimpleHTTPRequestHandler adds trailing slash logic etc. — mimic it only for md
        if path.endswith(".md"):
            md_path = Path(path)
            if not md_path.exists():
                self.send_error(404, "Not Found")
                return None
            try:
                body = render_markdown(md_path, unquote(self.path)).encode("utf-8")
            except Exception as e:
                self.send_error(500, f"Markdown render failed: {e}")
                return None
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            # Write body directly; parent's do_GET expects a file-like object from send_head
            return BytesIO(body)
        return super().send_head()

    def guess_type(self, path):
        # Ensure UTF-8 for any .md that slips through (e.g., via directory listing)
        mimetype = super().guess_type(path)
        if path.endswith(".md"):
            return "text/html; charset=utf-8"
        return mimetype

    def log_message(self, format, *args):
        # Quieter logs
        sys.stderr.write(f"{self.address_string()} - {format % args}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=3001)
    ap.add_argument("--directory", default=".", help="serve root (default cwd)")
    args = ap.parse_args()

    import os
    os.chdir(args.directory)

    addr = (args.bind, args.port)
    httpd = HTTPServer(addr, MDRequestHandler)
    print(f"Serving {Path(args.directory).resolve()} on http://{args.bind}:{args.port}/ (md → html)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
