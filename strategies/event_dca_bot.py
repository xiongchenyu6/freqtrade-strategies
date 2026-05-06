"""
Event-driven DCA Bot — opportunistic BTC accumulation on crashes.

Runs alongside weekly crypto-dca.timer. Catches:
  - FLASH:   1m drop > 3%              (WebSocket, tick-level)
  - FAST:    5m drop > 5%              (WebSocket, rolling)
  - SUSTAIN: 24h drop > 10%            (polling every 5min)
  - CAPITUL: 30d drawdown > 25%        (polling every 5min)

On trigger, calls `dca_executor.py --trigger=event --usdt=<amount>` which
respects DCA_LIVE_ENABLED to decide dry-run vs real buy.

Budget controls:
  EVENT_DCA_MONTHLY_BUDGET   max $ per month for event-triggered buys (default 2000)
  EVENT_DCA_PER_TRIGGER      base per-event amount (default 700; FnG<20 → ×1.5, >60 → ×0.7)
  EVENT_DCA_COOLDOWN_HOURS   global cooldown between triggers (default 72)
  EVENT_DCA_MAX_PER_MONTH    max triggers per month (default 3)

State file: event_dca_state.json (tracks cooldown + monthly spend)

Usage:
  python event_dca_bot.py                 # run as daemon
  python event_dca_bot.py --self-test     # test detection without WebSocket
"""
import argparse
import asyncio
import json
import logging
import os
import ssl
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import certifi
import requests
import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("event_dca")

# --- Config ---
PROJECT_DIR = Path(__file__).parent.parent
STATE_FILE = PROJECT_DIR / "event_dca_state.json"
DCA_EXECUTOR = PROJECT_DIR / "strategies" / "dca_executor.py"

SYMBOL = "btcusdt"
FLASH_THRESHOLD = 0.03           # 1m drop > 3%
FLASH_WINDOW_SEC = 60
FAST_THRESHOLD = 0.05            # 5m drop > 5%
FAST_WINDOW_SEC = 300
SUSTAIN_THRESHOLD = 0.10         # 24h drop > 10%
CAPITUL_DD_THRESHOLD = 0.25      # 30d drawdown > 25%
POLL_INTERVAL_SEC = 300          # 5min polling for sustained signals

MONTHLY_BUDGET = float(os.environ.get("EVENT_DCA_MONTHLY_BUDGET", "2000"))
PER_TRIGGER_BASE = float(os.environ.get("EVENT_DCA_PER_TRIGGER", "700"))
COOLDOWN_HOURS = int(os.environ.get("EVENT_DCA_COOLDOWN_HOURS", "72"))
MAX_PER_MONTH = int(os.environ.get("EVENT_DCA_MAX_PER_MONTH", "3"))

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

WS_URL = f"wss://stream.binance.com:9443/ws/{SYMBOL}@aggTrade"
KLINES_URL = "https://api.binance.com/api/v3/klines"


class State:
    """Persisted cooldown + monthly budget tracker."""

    def __init__(self, path: Path):
        self.path = path
        self.last_trigger_ts: float = 0
        self.month_key: str = ""
        self.month_spend: float = 0.0
        self.month_count: int = 0
        self.history: list = []
        self.load()

    def load(self):
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text())
                self.last_trigger_ts = d.get("last_trigger_ts", 0)
                self.month_key = d.get("month_key", "")
                self.month_spend = d.get("month_spend", 0.0)
                self.month_count = d.get("month_count", 0)
                self.history = d.get("history", [])[-100:]  # keep last 100
            except Exception as e:
                logger.warning(f"failed to load state: {e}")

    def save(self):
        self.path.write_text(json.dumps({
            "last_trigger_ts": self.last_trigger_ts,
            "month_key": self.month_key,
            "month_spend": self.month_spend,
            "month_count": self.month_count,
            "history": self.history[-100:],
        }, indent=2))

    def _reset_if_new_month(self, now: datetime):
        key = now.strftime("%Y-%m")
        if key != self.month_key:
            self.month_key = key
            self.month_spend = 0.0
            self.month_count = 0

    def can_trigger(self, now: datetime) -> tuple[bool, str]:
        self._reset_if_new_month(now)
        cooldown_cutoff = now.timestamp() - COOLDOWN_HOURS * 3600
        if self.last_trigger_ts > cooldown_cutoff:
            remain = (self.last_trigger_ts + COOLDOWN_HOURS * 3600 - now.timestamp()) / 3600
            return False, f"cooldown {remain:.1f}h remaining"
        if self.month_count >= MAX_PER_MONTH:
            return False, f"monthly trigger cap ({MAX_PER_MONTH}) reached for {self.month_key}"
        if self.month_spend >= MONTHLY_BUDGET:
            return False, f"monthly budget $${int(MONTHLY_BUDGET)} exhausted for {self.month_key}"
        return True, "ok"

    def record_trigger(self, now: datetime, amount: float, event: dict):
        self._reset_if_new_month(now)
        self.last_trigger_ts = now.timestamp()
        self.month_spend += amount
        self.month_count += 1
        self.history.append({
            "ts": now.isoformat(),
            "kind": event["kind"],
            "price": event["price"],
            "severity": event["severity"],
            "amount_usdt": amount,
            "fng": event.get("fng"),
        })
        self.save()


def get_fng() -> int:
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
        return int(r.json()["data"][0]["value"])
    except Exception as e:
        logger.warning(f"FnG fetch failed: {e}")
        return 50


def fear_boost(fng: int) -> float:
    if fng < 20:
        return 1.5
    if fng > 60:
        return 0.7
    return 1.0


def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"telegram send failed: {e}")


def fetch_klines(interval: str, limit: int) -> list[list]:
    """Fetch Binance klines. Returns list of [open_time, open, high, low, close, volume, ...]."""
    try:
        r = requests.get(
            KLINES_URL,
            params={"symbol": SYMBOL.upper(), "interval": interval, "limit": limit},
            timeout=10,
        )
        return r.json()
    except Exception as e:
        logger.warning(f"klines {interval} fetch failed: {e}")
        return []


def check_sustained_signals() -> Optional[dict]:
    """
    Poll REST for sustained/capitulation signals.
    Returns event dict if any threshold hit, else None. Returns strongest.
    """
    events = []

    # 24h return (check 1h candles for last 24)
    candles_1h = fetch_klines("1h", 24)
    if len(candles_1h) >= 24:
        start = float(candles_1h[0][1])    # open of first candle (24h ago)
        end = float(candles_1h[-1][4])      # close of last candle (now)
        ret_24h = (end - start) / start
        if ret_24h < -SUSTAIN_THRESHOLD:
            events.append({
                "kind": "SUSTAIN",
                "severity": ret_24h,
                "price": end,
            })

    # 30d drawdown (check daily candles last 30)
    candles_1d = fetch_klines("1d", 30)
    if len(candles_1d) >= 10:
        closes = [float(c[4]) for c in candles_1d]
        recent_high = max(closes)
        curr = closes[-1]
        dd = (curr - recent_high) / recent_high
        if dd < -CAPITUL_DD_THRESHOLD:
            events.append({
                "kind": "CAPITUL",
                "severity": dd,
                "price": curr,
            })

    if not events:
        return None
    # Return strongest
    return min(events, key=lambda e: e["severity"])


def trigger_dca(event: dict, state: State, dry_run: bool = False):
    """Fire DCA with event amount; record in state."""
    now = datetime.now(timezone.utc)
    ok, why = state.can_trigger(now)
    if not ok:
        logger.info(f"event {event['kind']} detected but BLOCKED: {why}")
        send_telegram(
            f"🔕 *Event DCA skipped*\n"
            f"Kind: `{event['kind']}`\n"
            f"Price: `${event['price']:,.0f}`\n"
            f"Severity: `{event['severity']:+.2%}`\n"
            f"Reason: `{why}`"
        )
        return

    fng = get_fng()
    event["fng"] = fng
    boost = fear_boost(fng)
    amount = round(PER_TRIGGER_BASE * boost)

    # Clamp to remaining monthly budget
    remain = MONTHLY_BUDGET - state.month_spend
    if amount > remain:
        amount = round(remain)
    if amount < 50:
        logger.info(f"amount ${amount} too small; skipping")
        return

    logger.warning(
        f"TRIGGER: {event['kind']} severity {event['severity']:+.2%} @ ${event['price']:,.0f}  "
        f"FnG={fng} boost={boost:.1f}x → ${amount} USDT"
    )

    send_telegram(
        f"🎯 *Event DCA Triggered*\n"
        f"Kind: `{event['kind']}`\n"
        f"BTC price: `${event['price']:,.0f}`\n"
        f"Severity: `{event['severity']:+.2%}`\n"
        f"FnG: `{fng}` (boost `{boost:.1f}x`)\n"
        f"Amount: `${amount} USDT`\n"
        f"Monthly: `{state.month_count + 1}/{MAX_PER_MONTH}` "
        f"(`${state.month_spend + amount:.0f}/{int(MONTHLY_BUDGET)}`)"
    )

    # Fire DCA executor (subprocess) — it honors DCA_LIVE_ENABLED
    env = os.environ.copy()
    cmd = [sys.executable, str(DCA_EXECUTOR),
           "--base", str(amount),
           "--trigger", f"event:{event['kind']}"]
    if dry_run or os.environ.get("DCA_LIVE_ENABLED", "").lower() != "true":
        # explicitly dry-run even if env is set (belt-and-suspenders)
        pass
    else:
        cmd.append("--live")

    try:
        subprocess.run(cmd, env=env, timeout=120, check=False)
    except Exception as e:
        logger.error(f"dca_executor call failed: {e}")

    state.record_trigger(now, amount, event)


class PriceBuffer:
    """Ring buffer of (ts, price) — supports FLASH + FAST detection."""

    def __init__(self):
        self.ticks: deque = deque()

    def add(self, price: float, ts: float) -> Optional[dict]:
        self.ticks.append((ts, price))
        # Keep only last 5 minutes
        cutoff = ts - FAST_WINDOW_SEC
        while self.ticks and self.ticks[0][0] < cutoff:
            self.ticks.popleft()

        if len(self.ticks) < 10:
            return None

        # FLASH: highest price in last 60s → current → drop > 3%
        flash_cutoff = ts - FLASH_WINDOW_SEC
        flash_max = max(p for t, p in self.ticks if t >= flash_cutoff)
        flash_drop = (price - flash_max) / flash_max
        if flash_drop < -FLASH_THRESHOLD:
            return {"kind": "FLASH", "severity": flash_drop, "price": price}

        # FAST: highest price in last 5min → current → drop > 5%
        fast_max = max(p for t, p in self.ticks)
        fast_drop = (price - fast_max) / fast_max
        if fast_drop < -FAST_THRESHOLD:
            return {"kind": "FAST", "severity": fast_drop, "price": price}

        return None


async def websocket_loop(state: State):
    """Listen to aggTrade, detect FLASH/FAST. Reconnect on disconnect."""
    buf = PriceBuffer()
    last_flash_alert: float = 0
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())

    while True:
        try:
            logger.info(f"connecting to {WS_URL}")
            async with websockets.connect(WS_URL, ssl=ssl_ctx, ping_interval=30) as ws:
                async for msg in ws:
                    d = json.loads(msg)
                    price = float(d["p"])
                    ts = d["T"] / 1000.0
                    ev = buf.add(price, ts)
                    if ev:
                        # Per-kind sub-cooldown to avoid spam within same second
                        if ts - last_flash_alert < 60:
                            continue
                        last_flash_alert = ts
                        trigger_dca(ev, state)
        except Exception as e:
            logger.warning(f"WS error, reconnecting in 5s: {e}")
            await asyncio.sleep(5)


async def polling_loop(state: State):
    """Every POLL_INTERVAL_SEC, check SUSTAIN + CAPITUL signals."""
    while True:
        try:
            ev = check_sustained_signals()
            if ev:
                trigger_dca(ev, state)
        except Exception as e:
            logger.warning(f"polling error: {e}")
        await asyncio.sleep(POLL_INTERVAL_SEC)


async def main_async():
    state = State(STATE_FILE)
    logger.info(
        f"event_dca_bot starting | monthly_budget=${int(MONTHLY_BUDGET)} "
        f"per_trigger=${int(PER_TRIGGER_BASE)} cooldown={COOLDOWN_HOURS}h "
        f"max/month={MAX_PER_MONTH}"
    )
    live_mode = os.environ.get("DCA_LIVE_ENABLED", "").lower() == "true"
    logger.info(f"LIVE MODE: {live_mode}  (DCA_LIVE_ENABLED={'true' if live_mode else 'false'})")
    send_telegram(
        f"🚀 *Event DCA Bot started*\n"
        f"Monthly budget: `${int(MONTHLY_BUDGET)}`\n"
        f"Per trigger: `${int(PER_TRIGGER_BASE)}`\n"
        f"Cooldown: `{COOLDOWN_HOURS}h`\n"
        f"Max/month: `{MAX_PER_MONTH}`\n"
        f"Mode: `{'LIVE' if live_mode else 'DRY-RUN'}`"
    )
    await asyncio.gather(websocket_loop(state), polling_loop(state))


def self_test():
    """Run one REST poll + print state + simulate a trigger without firing DCA."""
    print("=== self-test ===")
    print(f"state file:     {STATE_FILE}")
    print(f"dca executor:   {DCA_EXECUTOR}  exists={DCA_EXECUTOR.exists()}")
    print(f"monthly budget: ${MONTHLY_BUDGET}")
    print(f"per trigger:    ${PER_TRIGGER_BASE}")
    print(f"cooldown:       {COOLDOWN_HOURS}h")
    print(f"max/month:      {MAX_PER_MONTH}")
    print()
    state = State(STATE_FILE)
    now = datetime.now(timezone.utc)
    ok, why = state.can_trigger(now)
    print(f"can_trigger:    {ok}  ({why})")
    print(f"month:          {state.month_key}  spent=${state.month_spend:.0f}  count={state.month_count}")
    print()
    print("checking sustained signals (1h + daily klines)...")
    ev = check_sustained_signals()
    print(f"  result: {ev}")
    print()
    fng = get_fng()
    print(f"current FnG: {fng}  → boost {fear_boost(fng):.1f}x")
    if ev:
        amt = round(PER_TRIGGER_BASE * fear_boost(fng))
        print(f"  → would trigger ${amt} USDT DCA")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true", help="run REST checks only, exit")
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        try:
            asyncio.run(main_async())
        except KeyboardInterrupt:
            logger.info("bye")
