"""市场压力指数 collector → quant.market_stress (hourly).

An EXPLAINABLE composite, not a black box: every component stores its raw value,
its 0-100 subscore and the mapping note; the composite is the plain mean of the
subscores that were available this run (≥2 required, else we store nothing).

Components — all from data we already collect or public endpoints we already use
elsewhere (market_collector / signal_evaluator). Nothing fabricated:
  fng      alternative.me Fear&Greed (0=极恐 100=极贪) → stress = 100 - fng
  vix      Yahoo ^VIX latest daily close → linear 12→0, 40→100 (clamped)
  funding  Binance BTCUSDT latest 8h funding rate → 50 at +0.01% (long-term
           neutral); -0.05% → 100 (shorts pay = fear), +0.07% → 0 (euphoria)
  breadth  % of quant.semi_universe tickers with ret_1m > 0 → stress = 100 - breadth

Runs via quant-stress-index.timer (hourly). Env: TIMESCALE_URL.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import psycopg2
import requests

_HDRS = {"User-Agent": "Mozilla/5.0 (quant stress index; +https://quant.panda.qzz.io)"}
_YF = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
KEEP_DAYS = 365


def log(m: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {m}", flush=True)


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def comp_fng() -> dict:
    r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=15, headers=_HDRS)
    r.raise_for_status()
    raw = int(r.json()["data"][0]["value"])
    return {"raw": raw, "score": clamp(100 - raw), "note": "stress = 100 - FNG"}


def comp_vix() -> dict:
    r = requests.get(_YF.format(sym="^VIX"), timeout=15, headers=_HDRS)
    r.raise_for_status()
    closes = r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    raw = next(c for c in reversed(closes) if c is not None)
    return {"raw": round(raw, 2), "score": clamp((raw - 12) / 28 * 100),
            "note": "VIX 12→0, 40→100 线性"}


def comp_funding() -> dict:
    r = requests.get(
        "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1",
        timeout=15, headers=_HDRS)
    r.raise_for_status()
    pct = float(r.json()[-1]["fundingRate"]) * 100  # 8h rate in percent
    score = clamp(50 - (pct - 0.01) / 0.06 * 50)
    return {"raw": round(pct, 4), "score": score,
            "note": "BTC 8h funding%: +0.01→50, -0.05→100(空头付费=恐慌), +0.07→0"}


def comp_breadth(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FILTER (WHERE ret_1m > 0), count(*)
               FROM quant.semi_universe
               WHERE ret_1m IS NOT NULL AND updated_at > now() - interval '7 days'""")
        up, total = cur.fetchone()
    if not total or total < 10:
        raise RuntimeError(f"semi_universe stale/empty (n={total})")
    breadth = up / total * 100
    return {"raw": round(breadth, 1), "score": clamp(100 - breadth),
            "note": f"美股半导体宇宙 {up}/{total} 只近1月上涨; stress = 100 - 宽度%"}


def label_for(score: float) -> str:
    if score < 25:
        return "平静"
    if score < 50:
        return "正常"
    if score < 75:
        return "紧张"
    return "高压"


def main() -> int:
    dsn = os.environ.get("TIMESCALE_URL", "")
    if not dsn:
        print("TIMESCALE_URL required", file=sys.stderr)
        return 2
    conn = psycopg2.connect(dsn)
    conn.autocommit = True

    components: dict[str, dict] = {}
    for name, fn in (("fng", comp_fng), ("vix", comp_vix), ("funding", comp_funding),
                     ("breadth", lambda: comp_breadth(conn))):
        try:
            components[name] = fn()
        except Exception as e:
            log(f"{name} unavailable: {e!r}")
    if len(components) < 2:
        log("fewer than 2 components — storing nothing (honesty over coverage)")
        return 1

    score = round(sum(c["score"] for c in components.values()) / len(components), 1)
    label = label_for(score)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO quant.market_stress (stress_score, label, components)
               VALUES (%s, %s, %s)""",
            (score, label, json.dumps(components, ensure_ascii=False)))
        cur.execute(
            "DELETE FROM quant.market_stress WHERE ts < now() - interval '%s days'"
            % KEEP_DAYS)
    conn.close()
    parts = ", ".join(f"{k}={v['raw']}→{v['score']:.0f}" for k, v in components.items())
    log(f"stress={score} ({label}) from {len(components)} components: {parts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
