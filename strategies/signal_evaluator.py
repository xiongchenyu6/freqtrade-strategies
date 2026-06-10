"""Evaluates user-defined signals (quant.user_signals) on fresh PUBLIC market data and
records fires into quant.signal_fires — the live half of "backtest it, then subscribe to it".

Signal kinds (mirror the backtest playground strategies):
  ema_cross          {ema_fast, ema_slow, direction: 'golden'|'death'|'both'}
  donchian_breakout  {entry_lb, exit_lb, side: 'entry'|'exit'|'both'}
  fng_threshold      {below: int}   — Fear & Greed <= below (evaluated on the daily FNG value)

Data sources (all public, no keys): Binance klines REST for crypto (BTC→BTCUSDT etc.),
Yahoo chart API for equities (NVDA/AMD/QQQ, daily), alternative.me for FNG.

Efficiency: signals are grouped by (kind, asset, timeframe, params-hash) so 100 users on the
same config cost ONE fetch + ONE computation. Fires dedupe per (signal_id, bar_ts) via a
unique index — re-evaluating the same closed bar can't double-notify. Only CLOSED bars are
evaluated (the last, still-forming kline is dropped) so a signal can't flip-flop intrabar.

The alert dispatcher (alert_dispatcher.py) picks up fires with notified_at IS NULL and
pushes them to the owner's bound Telegram chat. Wording stays "你的信号触发了" — the user's
own rule, never advice.

Env: TIMESCALE_URL (sops). EVAL_INTERVAL seconds between sweeps (default 300).
Run: .venv-bots/bin/python strategies/signal_evaluator.py [--once]
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import requests

DSN = os.environ.get("TIMESCALE_URL", "")
INTERVAL = int(os.environ.get("EVAL_INTERVAL", "300"))

CRYPTO = {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "LINK"}
# Core equity set; extended at sweep time with quant.semi_universe symbols (38-ticker
# NVDA supply chain incl. SPY/MSFT/META/GOOGL/AMZN) so the allowed list tracks the DB.
EQUITY_CORE = {"NVDA", "AMD", "QQQ"}
_YF = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=2y&interval=1d"
_HDRS = {"User-Agent": "Mozilla/5.0 (quant signal evaluator)"}


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}", flush=True)


# ---------- market data (closed bars only) ----------

def crypto_closes(asset: str, timeframe: str, limit: int = 1100) -> list[tuple[int, float]]:
    """[(close_time_ms, close), ...] for CLOSED bars, oldest→newest."""
    interval = {"1h": "1h", "1d": "1d"}[timeframe]
    r = requests.get(
        "https://api.binance.com/api/v3/klines",
        params={"symbol": f"{asset}USDT", "interval": interval, "limit": min(limit, 1000)},
        timeout=15,
    )
    r.raise_for_status()
    rows = r.json()
    out = [(int(k[6]), float(k[4])) for k in rows]
    # Drop the still-forming last bar (close_time in the future).
    now_ms = int(time.time() * 1000)
    return [x for x in out if x[0] <= now_ms]


def equity_closes(asset: str) -> list[tuple[int, float]]:
    """Daily closes from Yahoo (same source as semi_analysis). Last bar dropped if today
    (US session may still be open)."""
    r = requests.get(_YF.format(sym=asset), headers=_HDRS, timeout=15)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts, close = res["timestamp"], res["indicators"]["quote"][0]["close"]
    out = [(int(t) * 1000, float(c)) for t, c in zip(ts, close) if c is not None]
    today = datetime.now(timezone.utc).date()
    return [x for x in out if datetime.fromtimestamp(x[0] / 1000, timezone.utc).date() < today]


def fng_now() -> tuple[int, int]:
    """(unix_ms_of_value, fng_value)"""
    r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
    r.raise_for_status()
    d = r.json()["data"][0]
    return int(d["timestamp"]) * 1000, int(d["value"])


def vix_now() -> tuple[int, float]:
    """(unix_ms_of_bar, vix_close) — latest daily VIX close from Yahoo (^VIX). Unlike the
    bar feeds we DO use the most recent value even if today's session is open: VIX alerts
    are about the fear level right now, and the (signal_id, bar_ts) dedupe still caps one
    fire per VIX bar."""
    r = requests.get(_YF.format(sym="^VIX"), headers=_HDRS, timeout=15)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts, close = res["timestamp"], res["indicators"]["quote"][0]["close"]
    pairs = [(int(t) * 1000, float(c)) for t, c in zip(ts, close) if c is not None]
    return pairs[-1]


# ---------- indicators (plain python — small series, no pandas needed) ----------

def ema_series(closes: list[float], period: int) -> list[float]:
    k = 2.0 / (period + 1)
    out = [closes[0]]
    for c in closes[1:]:
        out.append(c * k + out[-1] * (1 - k))
    return out


# ---------- evaluation per kind ----------

def eval_ema_cross(bars: list[tuple[int, float]], p: dict) -> dict | None:
    fast_n, slow_n = int(p.get("ema_fast", 20)), int(p.get("ema_slow", 50))
    direction = p.get("direction", "golden")
    if len(bars) < slow_n + 2:
        return None
    closes = [c for _, c in bars]
    f, s = ema_series(closes, fast_n), ema_series(closes, slow_n)
    prev_diff, cur_diff = f[-2] - s[-2], f[-1] - s[-1]
    golden = prev_diff <= 0 < cur_diff
    death = prev_diff >= 0 > cur_diff
    if (golden and direction in ("golden", "both")) or (death and direction in ("death", "both")):
        kind = "golden" if golden else "death"
        return {
            "bar_ts": bars[-1][0],
            "price": closes[-1],
            "direction": kind,
            "message": (f"EMA{fast_n} {'上穿' if golden else '下穿'} EMA{slow_n}"
                        f"({'金叉' if golden else '死叉'}),收盘 {closes[-1]:,.2f}"),
        }
    return None


def eval_donchian(bars: list[tuple[int, float]], p: dict) -> dict | None:
    entry_lb, exit_lb = int(p.get("entry_lb", 168)), int(p.get("exit_lb", 72))
    side = p.get("side", "entry")
    need = max(entry_lb, exit_lb) + 2
    if len(bars) < need:
        return None
    closes = [c for _, c in bars]
    last = closes[-1]
    hi = max(closes[-(entry_lb + 1):-1])  # prior N bars, excluding current
    lo = min(closes[-(exit_lb + 1):-1])
    if last > hi and side in ("entry", "both"):
        return {"bar_ts": bars[-1][0], "price": last, "direction": "entry",
                "message": f"收盘 {last:,.2f} 突破 {entry_lb} 根K线高点 {hi:,.2f}(入场条件)"}
    if last < lo and side in ("exit", "both"):
        return {"bar_ts": bars[-1][0], "price": last, "direction": "exit",
                "message": f"收盘 {last:,.2f} 跌破 {exit_lb} 根K线低点 {lo:,.2f}(离场条件)"}
    return None


def eval_fng(p: dict) -> dict | None:
    below = int(p.get("below", 25))
    ts_ms, val = fng_now()
    if val <= below:
        return {"bar_ts": ts_ms, "price": None, "direction": "fear",
                "value": val,
                "message": f"恐惧贪婪指数 {val} ≤ 你设定的 {below}(市场恐慌区)"}
    return None


def eval_vix(p: dict) -> dict | None:
    above = float(p.get("above", 25))
    ts_ms, val = vix_now()
    if val >= above:
        return {"bar_ts": ts_ms, "price": None, "direction": "fear",
                "value": val,
                "message": f"VIX 恐慌指数 {val:.1f} ≥ 你设定的 {above:g}(美股波动/恐慌升高)"}
    return None


# ---------- sweep ----------

def equity_allowed(conn) -> set[str]:
    """Core equities + the semi-universe tickers (tracks the DB; cheap query)."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol FROM quant.semi_universe")
            return EQUITY_CORE | {r[0] for r in cur.fetchall()}
    except Exception as e:
        log(f"semi_universe fetch failed (using core set): {e!r}")
        return set(EQUITY_CORE)


def sweep(conn) -> int:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, user_id, name, kind, asset, timeframe, params "
                    "FROM quant.user_signals WHERE status='active'")
        signals = cur.fetchall()
    if not signals:
        return 0
    equities = equity_allowed(conn)

    # Group identical configs → one evaluation each.
    groups: dict[str, dict] = {}
    for s in signals:
        key = json.dumps([s["kind"], s["asset"], s["timeframe"], s["params"]], sort_keys=True)
        groups.setdefault(key, {"spec": s, "members": []})["members"].append(s)

    fired = 0
    cache: dict[str, list[tuple[int, float]]] = {}
    for key, g in groups.items():
        s = g["spec"]
        kind, asset, tf, params = s["kind"], s["asset"], s["timeframe"], s["params"] or {}
        try:
            if kind == "fng_threshold":
                hit = eval_fng(params)
            elif kind == "vix_threshold":
                hit = eval_vix(params)
            else:
                ck = f"{asset}:{tf}"
                if ck not in cache:
                    if asset in CRYPTO:
                        cache[ck] = crypto_closes(asset, tf)
                    elif asset in equities:
                        cache[ck] = equity_closes(asset)
                    else:
                        log(f"unknown asset {asset!r} (signal {s['id']}) — skipping")
                        cache[ck] = []
                bars = cache[ck]
                if not bars:
                    continue
                hit = eval_ema_cross(bars, params) if kind == "ema_cross" else eval_donchian(bars, params)
        except Exception as e:
            log(f"eval {kind}/{asset}/{tf} failed: {e!r}")
            continue
        if not hit:
            continue

        bar_dt = datetime.fromtimestamp(hit["bar_ts"] / 1000, timezone.utc)
        details = {k: v for k, v in hit.items() if k != "bar_ts"}
        for member in g["members"]:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO quant.signal_fires (signal_id, user_id, bar_ts, details)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT (signal_id, bar_ts) DO NOTHING
                           RETURNING id""",
                        (member["id"], member["user_id"], bar_dt, json.dumps(details)),
                    )
                    if cur.fetchone():
                        cur.execute("UPDATE quant.user_signals SET last_fired_at=now() WHERE id=%s",
                                    (member["id"],))
                        fired += 1
                        log(f"FIRE signal {member['id']} ({member['name']!r}): {details['message']}")
            except Exception as e:
                log(f"fire insert for signal {member['id']} failed: {e!r}")
    return fired


def main() -> int:
    if not DSN:
        print("TIMESCALE_URL required", file=sys.stderr)
        return 2
    once = "--once" in sys.argv
    log(f"signal evaluator up (interval={INTERVAL}s, once={once})")
    while True:
        try:
            conn = psycopg2.connect(DSN)
            conn.autocommit = True
            n = sweep(conn)
            conn.close()
            if n:
                log(f"sweep complete: {n} fire(s)")
        except Exception as e:
            log(f"sweep error (continuing): {e!r}")
        if once:
            return 0
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
