"""
Real-Time Event Reactor

Monitors BTC price via Binance WebSocket. When a sudden spike/dump is
detected (>1.5% in 5 minutes), immediately:
  1. Checks Google News for KOL cause (Trump/Musk/BlackRock?)
  2. Sends Telegram alert with context
  3. Optionally places a trade via Binance API

This runs ALONGSIDE Freqtrade (not replacing it):
  - Freqtrade handles daily trend following
  - Event Reactor handles breaking news trades

Usage:
    # Run as daemon
    python event_reactor.py

    # Or via sops
    sops exec-env secrets.env 'python event_reactor.py'
"""

import asyncio
import json
import logging
import os
import ssl
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import certifi
import requests
import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("reactor")

# --- Config ---
SYMBOLS = ["btcusdt", "ethusdt", "solusdt"]
SPIKE_THRESHOLD = 0.015      # 1.5% move in window
SPIKE_WINDOW_SEC = 300       # 5 minute window
COOLDOWN_SEC = 600           # 10 min cooldown after alert (avoid spam)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


class PriceTracker:
    """Track price history for one symbol, detect spikes."""

    def __init__(self, symbol: str, window_sec: int = SPIKE_WINDOW_SEC):
        self.symbol = symbol.upper().replace("USDT", "/USDT")
        self.window_sec = window_sec
        self.prices: deque = deque()  # (timestamp, price)
        self.last_alert_ts: float = 0

    def add_price(self, price: float, ts: float) -> Optional[dict]:
        """Add a price tick. Returns spike info if detected, else None."""
        self.prices.append((ts, price))

        # Remove old prices outside window
        cutoff = ts - self.window_sec
        while self.prices and self.prices[0][0] < cutoff:
            self.prices.popleft()

        if len(self.prices) < 2:
            return None

        # Check for spike
        oldest_price = self.prices[0][1]
        change_pct = (price - oldest_price) / oldest_price

        if abs(change_pct) >= SPIKE_THRESHOLD:
            # Cooldown check
            if ts - self.last_alert_ts < COOLDOWN_SEC:
                return None

            self.last_alert_ts = ts
            return {
                "symbol": self.symbol,
                "change_pct": change_pct,
                "price": price,
                "from_price": oldest_price,
                "window_sec": self.window_sec,
                "direction": "PUMP" if change_pct > 0 else "DUMP",
            }

        return None


def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")
        return False


def check_kol_cause() -> list[dict]:
    """Quick KOL check — what caused the spike?"""
    try:
        from kol_tracker import KOLTracker
        tracker = KOLTracker()
        tracker._CACHE_TTL = 0  # force fresh fetch
        result = tracker.run()
        return [
            m for m in result.get("kol_mentions", [])
            if abs(m.get("score", 0)) > 0.2
        ][:5]
    except Exception as e:
        logger.warning(f"KOL check failed: {e}")
        return []


def push_to_supabase(event: dict):
    """Log spike event to Supabase."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        return
    try:
        requests.post(
            f"{url}/rest/v1/kol_events",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json={
                "kol": "price_spike",
                "sentiment": "bullish" if event["change_pct"] > 0 else "bearish",
                "score": round(event["change_pct"], 4),
                "title": f"{event['symbol']} {event['direction']} {event['change_pct']:+.1%} in {event['window_sec']}s (${event['price']:,.0f})",
                "source": "event_reactor",
            },
            timeout=10,
        )
    except Exception:
        pass


async def handle_spike(event: dict):
    """Handle a detected price spike."""
    logger.warning(
        f"SPIKE DETECTED: {event['symbol']} {event['direction']} "
        f"{event['change_pct']:+.1%} in {event['window_sec']}s "
        f"(${event['from_price']:,.0f} → ${event['price']:,.0f})"
    )

    # 1. Quick KOL check
    kol_mentions = check_kol_cause()
    kol_text = ""
    if kol_mentions:
        kol_lines = []
        for m in kol_mentions:
            icon = "🟢" if m["score"] > 0 else "🔴"
            kol_lines.append(f"  {icon} *{m['kol']}*: {m['title'][:80]}")
        kol_text = "\n\n*Possible cause:*\n" + "\n".join(kol_lines)

    # 1b. LLM analysis — what should we do?
    llm_text = ""
    try:
        from llm_signal import LLMSignalEngine
        engine = LLMSignalEngine()
        llm_signal = engine.analyze(
            headlines=[m.get("title", "") for m in kol_mentions] if kol_mentions else [],
            spike_event=event,
            market_data={"btc_price": event["price"]},
        )
        action = llm_signal.get("action", "wait")
        conf = llm_signal.get("confidence", 0)
        reasoning = llm_signal.get("reasoning", "")[:150]
        signal_emoji = {"buy": "🟢", "strong_buy": "🟢🟢", "sell": "🔴", "reduce": "🟡"}.get(action, "⚪")
        llm_text = (
            f"\n\n*AI Signal:* {signal_emoji} *{action.upper()}* ({conf:.0%} confidence)\n"
            f"_{reasoning}_"
        )
        logger.info(f"LLM: {action} ({conf:.0%}) — {reasoning[:80]}")
    except Exception as e:
        logger.warning(f"LLM analysis failed: {e}")

    # 2. Telegram alert
    direction_emoji = "🚀" if event["change_pct"] > 0 else "💥"
    message = (
        f"{direction_emoji} *PRICE SPIKE: {event['symbol']}*\n"
        f"{'─' * 30}\n"
        f"{event['direction']} *{event['change_pct']:+.1%}* in {event['window_sec']//60} min\n"
        f"${event['from_price']:,.0f} → *${event['price']:,.0f}*\n"
        f"Time: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
        f"{kol_text}"
        f"{llm_text}"
    )
    send_telegram(message)

    # 3. Log to Supabase
    push_to_supabase(event)


async def price_monitor():
    """Main WebSocket price monitor loop."""
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())

    # Track multiple symbols
    trackers = {s: PriceTracker(s) for s in SYMBOLS}

    # Combined stream
    streams = "/".join(f"{s}@aggTrade" for s in SYMBOLS)
    uri = f"wss://stream.binance.com:9443/stream?streams={streams}"

    while True:
        try:
            logger.info(f"Connecting to Binance WebSocket ({len(SYMBOLS)} symbols)...")
            async with websockets.connect(uri, ssl=ssl_ctx, ping_interval=30) as ws:
                logger.info("Connected! Monitoring for price spikes...")

                last_log = 0
                msg_count = 0

                async for raw in ws:
                    msg = json.loads(raw)
                    data = msg.get("data", {})

                    symbol = data.get("s", "").lower()
                    price = float(data.get("p", 0))
                    ts = data.get("T", 0) / 1000  # ms to sec

                    if symbol not in trackers or price <= 0:
                        continue

                    spike = trackers[symbol].add_price(price, ts)
                    if spike:
                        await handle_spike(spike)

                    # Periodic heartbeat log
                    msg_count += 1
                    now = time.time()
                    if now - last_log > 300:  # every 5 min
                        prices = {s: t.prices[-1][1] if t.prices else 0 for s, t in trackers.items()}
                        price_str = " ".join(f"{s.upper()}=${p:,.0f}" for s, p in prices.items())
                        logger.info(f"Heartbeat: {msg_count} ticks | {price_str}")
                        msg_count = 0
                        last_log = now

        except (websockets.ConnectionClosed, ConnectionError) as e:
            logger.warning(f"WebSocket disconnected: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error: {e}. Reconnecting in 10s...")
            await asyncio.sleep(10)


if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════╗
║     Real-Time Event Reactor                  ║
║     Monitoring: {', '.join(s.upper() for s in SYMBOLS):30s}  ║
║     Spike threshold: {SPIKE_THRESHOLD:.1%} in {SPIKE_WINDOW_SEC//60} min           ║
║     Cooldown: {COOLDOWN_SEC//60} min                          ║
╚══════════════════════════════════════════════╝
""")
    asyncio.run(price_monitor())
