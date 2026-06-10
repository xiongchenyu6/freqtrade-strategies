"""Sync completed IB paper round-trips into quant.nautilus_trades (asset_class='equity').

Stop-gap until the live node's in-process trade_ledger persistence is deployed: the equity
HonestTrend node trades on IB paper, but those fills don't reach the dashboard DB yet. This
connects READ-ONLY to the Gateway, pulls recent executions, reconstructs closed round-trips
(position returns to flat) per symbol, and upserts them so /nautilus + the home equity card
show real paper activity.

Idempotent: position_id = f"ib-{symbol}-{open_epoch}" with ON CONFLICT, so re-runs refresh
rather than duplicate. NOTE: IB reqExecutions only returns ~the last 24h for this client, so
run it on a schedule to capture trades as they close. Places NO orders.

  IB_HOST (default 172.22.240.97)  IB_PORT (default 4002)  IB_CLIENT_ID (default 10)
  TIMESCALE_URL (else read from ~/.config/quant/backtest-runner.env)
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import psycopg2
from ibapi.client import EClient
from ibapi.execution import ExecutionFilter
from ibapi.wrapper import EWrapper


class Fills(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.accounts: list[str] = []
        self.fills: list[dict] = []
        self._done = threading.Event()

    def error(self, reqId, code, msg, *a):
        if code not in (2104, 2105, 2106, 2107, 2119, 2158):
            print(f"  [ib msg {code}] {msg}")

    def managedAccounts(self, accountsList: str):
        self.accounts = [a for a in accountsList.split(",") if a]

    def execDetails(self, reqId, contract, execution):
        # execution.time like "20260609 11:18:56 US/Eastern"; side BOT/SLD.
        self.fills.append({
            "symbol": contract.symbol,
            "venue": (contract.primaryExchange or contract.exchange or "NASDAQ"),
            "side": execution.side,
            "shares": float(execution.shares),
            "price": float(execution.price),
            "time": execution.time,
            "epoch": _to_epoch(execution.time),
        })

    def execDetailsEnd(self, reqId):
        self._done.set()


def _to_epoch(ib_time: str) -> int:
    # "20260609 11:18:56 US/Eastern" → epoch ns (best-effort; tz label dropped → treat as UTC-ish
    # ordering key only, which is all we use it for).
    import datetime as dt
    parts = ib_time.split(" ")
    stamp = f"{parts[0]} {parts[1]}"
    t = dt.datetime.strptime(stamp, "%Y%m%d %H:%M:%S")
    return int(t.timestamp() * 1_000_000_000)


def reconstruct(fills: list[dict]) -> list[dict]:
    """Walk fills per symbol; emit a closed round-trip each time net position returns to 0."""
    trips: list[dict] = []
    by_sym: dict[str, list[dict]] = {}
    for f in fills:
        by_sym.setdefault(f["symbol"], []).append(f)
    for sym, fs in by_sym.items():
        fs.sort(key=lambda x: x["epoch"])
        pos = 0.0
        buy_qty = buy_cost = sell_qty = sell_cost = 0.0
        open_epoch = None
        venue = fs[0]["venue"]
        for f in fs:
            signed = f["shares"] if f["side"] == "BOT" else -f["shares"]
            if pos == 0.0:
                # opening a fresh position
                open_epoch = f["epoch"]
                buy_qty = buy_cost = sell_qty = sell_cost = 0.0
            if f["side"] == "BOT":
                buy_qty += f["shares"]; buy_cost += f["shares"] * f["price"]
            else:
                sell_qty += f["shares"]; sell_cost += f["shares"] * f["price"]
            pos += signed
            if abs(pos) < 1e-9 and open_epoch is not None:
                qty = min(buy_qty, sell_qty)
                open_rate = buy_cost / buy_qty if buy_qty else 0.0
                close_rate = sell_cost / sell_qty if sell_qty else 0.0
                pnl = (close_rate - open_rate) * qty
                ret = (close_rate / open_rate - 1) if open_rate else 0.0
                trips.append({
                    "symbol": sym, "venue": venue, "is_short": False,
                    "open_epoch": open_epoch, "close_epoch": f["epoch"],
                    "open_rate": round(open_rate, 4), "close_rate": round(close_rate, 4),
                    "quantity": qty, "realized_pnl": round(pnl, 2), "profit_pct": round(ret, 6),
                })
                open_epoch = None
    return trips


def _dsn() -> str:
    url = os.environ.get("TIMESCALE_URL")
    if not url:
        env = Path.home() / ".config" / "quant" / "backtest-runner.env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("TIMESCALE_URL="):
                    url = line.split("=", 1)[1].strip()
    if not url:
        raise SystemExit("TIMESCALE_URL not set")
    return url


def main() -> int:
    host = os.environ.get("IB_HOST", "172.22.240.97")
    port = int(os.environ.get("IB_PORT", "4002"))
    cid = int(os.environ.get("IB_CLIENT_ID", "10"))

    app = Fills()
    app.connect(host, port, cid)
    threading.Thread(target=app.run, daemon=True).start()
    time.sleep(2.0)
    if not app.isConnected():
        print(f"NOT CONNECTED to {host}:{port}")
        return 1
    for _ in range(20):
        if app.accounts:
            break
        time.sleep(0.2)
    acct = app.accounts[0] if app.accounts else "?"
    if not acct.startswith("DU"):
        print(f"REFUSING: {acct} is not an IB paper account")
        app.disconnect(); return 2
    print(f"connected {host}:{port} · account {acct}")

    app.reqExecutions(1, ExecutionFilter())
    app._done.wait(timeout=10)
    time.sleep(0.5)
    app.disconnect()

    trips = reconstruct(app.fills)
    print(f"{len(app.fills)} fills → {len(trips)} closed round-trip(s)")
    if not trips:
        print("nothing to sync")
        return 0

    env = os.environ.get("NAUTILUS_ENV", "paper")
    conn = psycopg2.connect(_dsn())
    try:
        with conn.cursor() as cur:
            for t in trips:
                pid = f"ib-{t['symbol']}-{t['open_epoch']}"
                cur.execute(
                    """INSERT INTO quant.nautilus_trades
                         (trader_id, position_id, strategy, instrument, venue, environment,
                          asset_class, is_short, open_date, close_date, open_rate, close_rate,
                          quantity, realized_pnl, profit_pct, exit_reason, synced_at)
                       VALUES ('IB-PAPER', %s, 'HonestTrendEquity', %s, %s, %s, 'equity', %s,
                          to_timestamp(%s/1e9), to_timestamp(%s/1e9), %s, %s, %s, %s, %s, 'ib-sync', now())
                       ON CONFLICT (trader_id, position_id, open_date) DO UPDATE
                         SET close_date=EXCLUDED.close_date, close_rate=EXCLUDED.close_rate,
                             realized_pnl=EXCLUDED.realized_pnl, profit_pct=EXCLUDED.profit_pct,
                             synced_at=now()""",
                    (pid, f"{t['symbol']}.{t['venue']}", t["venue"], env, t["is_short"],
                     t["open_epoch"], t["close_epoch"], t["open_rate"], t["close_rate"],
                     t["quantity"], t["realized_pnl"], t["profit_pct"]),
                )
                print(f"  synced {t['symbol']}: {t['quantity']:.0f} @ {t['open_rate']} → "
                      f"{t['close_rate']}  pnl={t['realized_pnl']:+.2f}  ret={t['profit_pct']*100:+.2f}%")
        conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
