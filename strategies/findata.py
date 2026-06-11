"""financialdata.net client — daily US-equity OHLCV for ANY ticker, with caching + budget.

Free tier: 300 requests/day. This module makes that safe to build on:
  - On-disk daily cache: user_data/data/findata/{SYM}_1d.json — bars change once per
    trading day, so each symbol costs AT MOST a few requests per day no matter how
    often the evaluator sweeps or users backtest it.
  - Budget guard: a daily counter file stops us at SOFT_LIMIT (280) — callers fall
    back to Yahoo (signals) or fail with a clear message (backtests).
  - Pagination: /stock-prices returns 300 rows (newest first) per call; closes_us()
    pages with offset until min_bars or history exhausted (10+ years available).

Env: FINANCIALDATA_KEY (sops secrets.env / ~/.config/quant/backtest-runner.env).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

_BASE = "https://financialdata.net/api/v1"
_CACHE_DIR = Path(__file__).resolve().parent.parent / "user_data" / "data" / "findata"
_BUDGET_FILE = _CACHE_DIR / "_budget.json"
SOFT_LIMIT = 280  # keep headroom under the 300/day cap


def _key() -> str:
    return os.environ.get("FINANCIALDATA_KEY", "")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _budget_spend(n: int = 1) -> bool:
    """Reserve n requests from today's budget. False = over limit, don't call."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        b = json.loads(_BUDGET_FILE.read_text())
    except Exception:
        b = {}
    if b.get("date") != _today():
        b = {"date": _today(), "used": 0}
    if b["used"] + n > SOFT_LIMIT:
        return False
    b["used"] += n
    _BUDGET_FILE.write_text(json.dumps(b))
    return True


def budget_used() -> int:
    try:
        b = json.loads(_BUDGET_FILE.read_text())
        return b["used"] if b.get("date") == _today() else 0
    except Exception:
        return 0


def _get(path: str, **params) -> list | None:
    if not _key() or not _budget_spend():
        return None
    params["key"] = _key()
    try:
        r = requests.get(f"{_BASE}/{path}", params=params, timeout=20)
        if r.status_code != 200:
            return None
        d = r.json()
        return d if isinstance(d, list) else None
    except Exception:
        return None


# COMEX/NYMEX/CME/CBOT continuous futures available on the free tier (verified 2026-06-11).
# zh labels live in the web layer; this set gates evaluator/runner symbol routing.
COMMODITIES = {"GC", "SI", "CL", "BZ", "HG", "NG", "HO", "RB", "PL", "PA", "KT", "CJ", "CT",
               "ZC", "ZW", "ZS", "ZL", "ZM", "ZO", "ZR", "LE", "GF", "HE", "DC", "KE", "LBR", "YO"}


def closes_us(symbol: str, min_bars: int = 600, max_pages: int = 10) -> list[tuple[int, float]]:
    """[(unix_ms, close), ...] oldest→newest for a US stock/ETF, today's session excluded
    if still open (rows are end-of-day; the API only lists completed sessions, but we
    also drop a today-dated row before 21:00 UTC to be safe). Cached per UTC day.
    Returns [] when the symbol is unknown, the budget is exhausted and no cache exists,
    or the key is missing."""
    symbol = symbol.upper().strip()
    if not symbol.isalnum():
        return []
    return _closes(symbol, "stock-prices", f"{symbol}_1d.json", min_bars, max_pages)


def closes_commodity(symbol: str, min_bars: int = 600, max_pages: int = 10) -> list[tuple[int, float]]:
    """Daily closes for a continuous commodity future (GC gold, CL crude, ...)."""
    symbol = symbol.upper().strip()
    if symbol not in COMMODITIES:
        return []
    return _closes(symbol, "commodity-prices", f"CMD_{symbol}_1d.json", min_bars, max_pages)


def _closes(symbol: str, endpoint: str, cache_name: str, min_bars: int, max_pages: int) -> list[tuple[int, float]]:
    cache = _CACHE_DIR / cache_name
    try:
        c = json.loads(cache.read_text())
        if c.get("date") == _today() and len(c.get("bars", [])) >= min(min_bars, len(c.get("bars", []))):
            bars = c["bars"]
            if len(bars) >= min_bars or c.get("complete"):
                return [tuple(x) for x in bars]
    except Exception:
        pass

    rows: list[dict] = []
    complete = False
    for page in range(max_pages):
        batch = _get(endpoint, identifier=symbol, offset=page * 300)
        if batch is None:  # budget/key/network — serve stale cache if any
            try:
                c = json.loads(cache.read_text())
                return [tuple(x) for x in c.get("bars", [])]
            except Exception:
                return []
        rows.extend(batch)
        if len(batch) < 300:
            complete = True
            break
        if len(rows) >= min_bars:
            break

    out: list[tuple[int, float]] = []
    for r in rows:
        try:
            ts = int(datetime.strptime(r["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
            out.append((ts, float(r["close"])))
        except Exception:
            continue
    out.sort(key=lambda x: x[0])
    # Drop a today-dated bar while the US session could still be open (~13:30-21:00 UTC).
    now = datetime.now(timezone.utc)
    if out and out[-1][0] >= int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000) \
       and now.hour < 21:
        out = out[:-1]

    if out:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"date": _today(), "complete": complete, "bars": out}))
    return out


def ohlcv_us(symbol: str, min_bars: int = 2600, max_pages: int = 10) -> list[dict]:
    """Full OHLCV rows oldest→newest (for backtests). Cached per UTC day."""
    symbol = symbol.upper().strip()
    if not symbol.isalnum():
        return []
    return _ohlcv(symbol, "stock-prices", f"{symbol}_ohlcv.json", min_bars, max_pages)


def ohlcv_commodity(symbol: str, min_bars: int = 2600, max_pages: int = 10) -> list[dict]:
    """Full OHLCV for a continuous commodity future (for backtests)."""
    symbol = symbol.upper().strip()
    if symbol not in COMMODITIES:
        return []
    return _ohlcv(symbol, "commodity-prices", f"CMD_{symbol}_ohlcv.json", min_bars, max_pages)


def _ohlcv(symbol: str, endpoint: str, cache_name: str, min_bars: int, max_pages: int) -> list[dict]:
    cache = _CACHE_DIR / cache_name
    try:
        c = json.loads(cache.read_text())
        if c.get("date") == _today():
            return c.get("rows", [])
    except Exception:
        pass
    rows: list[dict] = []
    for page in range(max_pages):
        batch = _get(endpoint, identifier=symbol, offset=page * 300)
        if batch is None:
            try:
                c = json.loads(cache.read_text())
                return c.get("rows", [])
            except Exception:
                return []
        rows.extend(batch)
        if len(batch) < 300 or len(rows) >= min_bars:
            break
    rows = [r for r in rows if all(r.get(k) is not None for k in ("date", "open", "high", "low", "close", "volume"))]
    rows.sort(key=lambda r: r["date"])
    now = datetime.now(timezone.utc)
    if rows and rows[-1]["date"] == _today() and now.hour < 21:
        rows = rows[:-1]
    if rows:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"date": _today(), "rows": rows}))
    return rows


def is_us_symbol(symbol: str) -> bool:
    """Cheap validity check: cached weekly symbol list; on cache miss, a 1-row price
    probe (cached as the symbol's bars, so it's not wasted)."""
    symbol = symbol.upper().strip()
    if not symbol.isalnum() or len(symbol) > 6:
        return False
    syms = _symbol_set()
    if syms is not None:
        return symbol in syms
    return bool(closes_us(symbol, min_bars=1, max_pages=1))


_SYMBOLS_CACHE = _CACHE_DIR / "_symbols.json"


def _symbol_set() -> set[str] | None:
    try:
        c = json.loads(_SYMBOLS_CACHE.read_text())
        if time.time() - c.get("ts", 0) < 7 * 86400:
            return set(c["symbols"])
    except Exception:
        pass
    syms: list[str] = []
    for page in range(40):  # ~11k US symbols / 500 per call
        batch = _get("stock-symbols", offset=page * 500)
        if batch is None:
            return None  # budget gone — caller falls back to the probe path
        syms.extend(r["trading_symbol"] for r in batch if r.get("trading_symbol"))
        if len(batch) < 500:
            break
    if syms:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _SYMBOLS_CACHE.write_text(json.dumps({"ts": time.time(), "symbols": syms}))
        return set(syms)
    return None


# ---------- Yahoo fallback channel (ETFs: findata's free tier has no /etf-prices) ----------
_YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=15y&interval=1d"
_YHDRS = {"User-Agent": "Mozilla/5.0 (quant portfolio engine)"}


def closes_yahoo(symbol: str) -> list[tuple[int, float]]:
    """[(unix_ms, close)] oldest→newest from Yahoo (15y daily) — used for ETFs (SPY/TLT/...)
    which the findata free tier doesn't serve. Daily disk cache, same shape as closes_us."""
    symbol = symbol.upper().strip()
    if not symbol.isalnum():
        return []
    cache = _CACHE_DIR / f"YF_{symbol}_1d.json"
    try:
        c = json.loads(cache.read_text())
        if c.get("date") == _today():
            return [tuple(x) for x in c["bars"]]
    except Exception:
        pass
    try:
        r = requests.get(_YAHOO.format(sym=symbol), headers=_YHDRS, timeout=20)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        ts, close = res["timestamp"], res["indicators"]["quote"][0]["close"]
        out = sorted((int(t) * 1000, float(c)) for t, c in zip(ts, close) if c is not None)
    except Exception:
        try:
            c = json.loads(cache.read_text())
            return [tuple(x) for x in c.get("bars", [])]
        except Exception:
            return []
    now = datetime.now(timezone.utc)
    if out and out[-1][0] >= int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000) and now.hour < 21:
        out = out[:-1]
    if out:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"date": _today(), "bars": out}))
    return out


def closes_any(symbol: str, min_bars: int = 600) -> list[tuple[int, float]]:
    """Best-source daily closes: findata stocks → findata commodities → Yahoo (ETFs)."""
    symbol = symbol.upper().strip()
    if symbol in COMMODITIES:
        return closes_commodity(symbol, min_bars=min_bars)
    bars = closes_us(symbol, min_bars=min_bars)
    if bars:
        return bars
    return closes_yahoo(symbol)
