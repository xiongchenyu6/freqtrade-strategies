"""
Smart DCA Executor — weekly BTC accumulation with dynamic sizing.

Combines three signal sources for the DCA multiplier:
  1. Fear & Greed Index (sentiment) — base multiplier
  2. BTC cycle factors (Ahr999, Mayer, Power Law, etc.) — composite score
  3. News/KOL sentiment — recent catalysts

Supports two modes:
  --dry-run:  log recommendation, push to Telegram, store in Supabase (default)
  --live:     also execute Binance spot market buy (requires BINANCE_API_KEY/SECRET)

Run weekly via systemd timer (Mondays 00:00 UTC):
  python dca_executor.py --base 500 --dry-run

Environment variables:
  DCA_BASE_USDT          base weekly amount (default 500)
  DCA_LIVE_ENABLED       set to 'true' to enable live trading
  BINANCE_API_KEY        required for --live
  BINANCE_API_SECRET     required for --live
  SUPABASE_URL, SUPABASE_KEY  for logging
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  for alerts
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("dca")

# Local imports
PROJECT_DIR = Path(__file__).parent.parent
SENTIMENT_FILE = PROJECT_DIR / "sentiment_data" / "latest_sentiment.json"

# Config defaults
DEFAULT_BASE_USDT = float(os.environ.get("DCA_BASE_USDT", "500"))
LIVE_ENABLED = os.environ.get("DCA_LIVE_ENABLED", "").lower() == "true"


class DCAExecutor:

    def __init__(self, base_usdt: float = DEFAULT_BASE_USDT):
        self.base_usdt = base_usdt

    # ---- Signal fetchers ----

    def fetch_sentiment(self) -> dict:
        """Load latest sentiment from pipeline JSON."""
        try:
            with open(SENTIMENT_FILE) as f:
                data = json.load(f)
            return {
                "fng": data.get("fng_value", 50),
                "fng_classification": data.get("fng_classification", "Neutral"),
                "combined_score": data.get("combined_score", 0.0),
                "kol_score": data.get("kol_score", 0.0),
                "kol_alert": data.get("kol_alert", "none"),
                "source": "pipeline",
            }
        except FileNotFoundError:
            logger.warning("No sentiment data, fetching FnG directly")

        # Fallback: FnG only
        try:
            r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
            fng_val = int(r.json()["data"][0]["value"])
            return {
                "fng": fng_val,
                "fng_classification": r.json()["data"][0]["value_classification"],
                "combined_score": (fng_val - 50) / 50,
                "kol_score": 0,
                "kol_alert": "none",
                "source": "fng_api",
            }
        except Exception as e:
            logger.error(f"FnG fetch failed: {e}")
            return {"fng": 50, "combined_score": 0, "kol_score": 0, "kol_alert": "none", "source": "default"}

    def fetch_cycle_factors(self) -> dict:
        """Run btc_cycle_factors computation."""
        try:
            sys.path.insert(0, str(PROJECT_DIR / "strategies"))
            from btc_cycle_factors import BTCCycleFactors

            # Get BTC price data
            closes_d = []
            end_ms = None
            for _ in range(2):
                params = {"symbol": "BTCUSDT", "interval": "1d", "limit": 1000}
                if end_ms:
                    params["endTime"] = end_ms
                r = requests.get("https://api.binance.com/api/v3/klines", params=params, timeout=15)
                batch = r.json()
                if not batch:
                    break
                closes_d = [float(k[4]) for k in batch] + closes_d
                end_ms = batch[0][0] - 1
                if len(closes_d) >= 1500:
                    break
            r2 = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1w", "limit": 250},
                timeout=15,
            )
            closes_w = [float(k[4]) for k in r2.json()]
            current = closes_d[-1] if closes_d else 0

            bf = BTCCycleFactors()
            return bf.fetch_all(closes_d, closes_w, current)
        except Exception as e:
            logger.warning(f"Cycle factors failed: {e}")
            return {"combined_score": 0, "signal": "neutral", "factors": {}}

    # ---- Multiplier logic ----

    def compute_multiplier(self, sent: dict, cycle: dict) -> tuple[float, dict]:
        """
        Combine signals into DCA multiplier (0.0 to 3.0x).

        Weights:
          Cycle factors: 50%  (long-term valuation, most reliable)
          FnG:           30%  (medium-term sentiment)
          News combined: 20%  (short-term catalysts)
        """
        # Fear & Greed contribution
        fng = sent["fng"]
        if fng < 10:
            fng_mult = 3.0      # Capitulation (2018-12, 2020-03, 2022-11 territory)
        elif fng < 20:
            fng_mult = 2.2      # Extreme Fear
        elif fng < 40:
            fng_mult = 1.5      # Fear
        elif fng < 60:
            fng_mult = 1.0      # Neutral
        elif fng < 80:
            fng_mult = 0.6      # Greed
        else:
            fng_mult = 0.2      # Extreme Greed (not quite zero — still accumulate)

        # Cycle factor contribution
        # cycle composite: +1 (deep undervalued) to -1 (top)
        cycle_score = cycle.get("combined_score", 0)
        if cycle_score > 0.7:
            cycle_mult = 2.8    # deep capitulation
        elif cycle_score > 0.5:
            cycle_mult = 2.2    # deep accumulation
        elif cycle_score > 0.2:
            cycle_mult = 1.5
        elif cycle_score > -0.2:
            cycle_mult = 1.0
        elif cycle_score > -0.5:
            cycle_mult = 0.5
        else:
            cycle_mult = 0.1    # top territory, minimal buy

        # News/KOL contribution
        combined = sent["combined_score"]
        if combined > 0.3:
            news_mult = 1.3
        elif combined < -0.3:
            news_mult = 0.7
        else:
            news_mult = 1.0

        # KOL urgent bonus — Trump/Musk positive statement amplifies buy
        kol_bonus = 1.0
        if sent["kol_alert"] == "urgent" and sent["kol_score"] > 0.3:
            kol_bonus = 1.2
        elif sent["kol_alert"] == "urgent" and sent["kol_score"] < -0.3:
            kol_bonus = 0.8

        # Weighted combination
        multiplier = (
            0.50 * cycle_mult
            + 0.30 * fng_mult
            + 0.20 * news_mult
        ) * kol_bonus

        # Clamp to [0.0, 3.0]
        multiplier = max(0.0, min(3.0, multiplier))

        explain = {
            "fng": fng,
            "fng_mult": round(fng_mult, 2),
            "cycle_score": round(cycle_score, 2),
            "cycle_mult": round(cycle_mult, 2),
            "news_score": round(combined, 2),
            "news_mult": round(news_mult, 2),
            "kol_bonus": round(kol_bonus, 2),
            "final_mult": round(multiplier, 2),
        }
        return multiplier, explain

    # ---- Order placement ----

    def place_market_buy(self, usdt_amount: float) -> dict:
        """Execute Binance spot market buy. Returns order info."""
        key = os.environ.get("BINANCE_API_KEY", "")
        secret = os.environ.get("BINANCE_API_SECRET", "")
        if not key or not secret:
            return {"error": "no BINANCE API keys"}

        try:
            from binance.client import Client
            client = Client(key, secret)

            # Market buy with quoteOrderQty (spend exact USDT amount)
            order = client.order_market_buy(
                symbol="BTCUSDT",
                quoteOrderQty=round(usdt_amount, 2),
            )
            return {
                "success": True,
                "order_id": order["orderId"],
                "executed_qty": float(order["executedQty"]),
                "cumulative_quote": float(order["cummulativeQuoteQty"]),
                "avg_price": float(order["cummulativeQuoteQty"]) / float(order["executedQty"]) if float(order["executedQty"]) > 0 else 0,
                "status": order["status"],
            }
        except Exception as e:
            logger.error(f"Order failed: {e}")
            return {"error": str(e)}

    # ---- Logging ----

    def log_to_supabase(self, record: dict):
        """Store DCA execution record."""
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")
        if not url or not key:
            return
        try:
            resp = requests.post(
                f"{url}/rest/v1/dca_log",
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json=record,
                timeout=10,
            )
            resp.raise_for_status()
            logger.info("Logged to Supabase")
        except Exception as e:
            logger.warning(f"Supabase log failed: {e}")

    def send_telegram(self, message: str):
        """Send Telegram alert."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat,
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
        except Exception:
            pass

    # ---- Main ----

    def run(self, live: bool = False, trigger: str = "weekly") -> dict:
        logger.info(f"=== DCA Run @ {datetime.now(timezone.utc).isoformat()} ===")
        logger.info(f"Base amount: {self.base_usdt} USDT")

        # Gather signals
        sent = self.fetch_sentiment()
        cycle = self.fetch_cycle_factors()

        # Compute multiplier
        mult, explain = self.compute_multiplier(sent, cycle)
        amount = self.base_usdt * mult

        logger.info(f"Multiplier: {mult:.2f}x -> {amount:.0f} USDT")
        logger.info(f"  FnG: {sent['fng']} ({explain['fng_mult']}x)")
        logger.info(f"  Cycle: {cycle.get('signal', '?')} {explain['cycle_score']:+.2f} ({explain['cycle_mult']}x)")
        logger.info(f"  News: {explain['news_score']:+.2f} ({explain['news_mult']}x)")
        logger.info(f"  KOL bonus: {explain['kol_bonus']}x")

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trigger": trigger,
            "base_usdt": self.base_usdt,
            "multiplier": mult,
            "amount_usdt": round(amount, 2),
            "mode": "live" if live else "dry_run",
            "fng_value": sent["fng"],
            "cycle_score": cycle.get("combined_score", 0),
            "news_score": sent["combined_score"],
            "kol_score": sent["kol_score"],
            "explain": explain,
            "cycle_signal": cycle.get("signal", "neutral"),
        }

        # Place order if live
        if live and amount > 0:
            if not LIVE_ENABLED:
                logger.warning("DCA_LIVE_ENABLED is not 'true' — refusing live trade")
                record["order_result"] = {"error": "DCA_LIVE_ENABLED not set"}
            else:
                result = self.place_market_buy(amount)
                record["order_result"] = result
                if result.get("success"):
                    logger.info(f"BUY filled: {result['executed_qty']} BTC @ ${result['avg_price']:,.0f}")

        # Build Telegram message
        top_factors = []
        for name, data in cycle.get("factors", {}).items():
            if isinstance(data, dict):
                score = data.get("score", 0)
                if abs(score) > 0.3:
                    icon = "🟢" if score > 0 else "🔴"
                    val = data.get("value") or data.get("band") or data.get("phase") or ""
                    top_factors.append(f"{icon} {name}: {val} ({score:+.2f})")

        mode_emoji = "💰" if live else "📊"
        tg_msg = (
            f"{mode_emoji} *Weekly DCA* {'LIVE' if live else 'DRY-RUN'}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Amount: *{amount:.0f} USDT* ({mult:.2f}x base {self.base_usdt:.0f})\n\n"
            f"*Signals:*\n"
            f"  FnG: {sent['fng']} ({sent['fng_classification']})\n"
            f"  Cycle: {cycle.get('signal', '?')} ({explain['cycle_score']:+.2f})\n"
            f"  News: {explain['news_score']:+.2f}\n"
            f"  KOL: {explain['kol_bonus']}x bonus\n\n"
            f"*Top factors:*\n" + "\n".join(top_factors[:5])
        )

        if live and record.get("order_result", {}).get("success"):
            r = record["order_result"]
            tg_msg += (
                f"\n\n*Order filled:*\n"
                f"  {r['executed_qty']:.6f} BTC @ ${r['avg_price']:,.0f}"
            )

        self.send_telegram(tg_msg)
        self.log_to_supabase(record)

        logger.info(f"=== DCA Complete. Amount: {amount:.0f} USDT ===")
        return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=float, default=DEFAULT_BASE_USDT, help="Base weekly USDT")
    ap.add_argument("--live", action="store_true", help="Execute real Binance buy (requires keys)")
    ap.add_argument("--trigger", default="weekly",
                    help="Trigger source tag for logging/Supabase (e.g. 'weekly', 'event:FLASH')")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    executor = DCAExecutor(base_usdt=args.base)
    record = executor.run(live=args.live, trigger=args.trigger)
    print("\n" + json.dumps(record, default=str, indent=2))


if __name__ == "__main__":
    main()
