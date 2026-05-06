"""
Deribit BTC Options Monitor — Phase 1 (read-only)

Purpose: Find the best Cash-Secured Put (CSP) candidates every day.
Sells OTM puts to collect premium; if assigned, buys BTC at a discount.

Key ideas:
  1. Filter BTC put options by:
     - Days to expiry: 5-30 days (theta decay sweet spot)
     - Strike distance from spot: 10-25% OTM (safe buffer)
     - Bid price > 0 (has liquidity)
  2. Compute for each:
     - Annualized yield = (premium / strike_collateral) * (365 / days) * 100
     - Assignment probability ≈ |delta|
     - Max loss if BTC crashes to 0: strike - premium
  3. Rank by (yield - risk_penalty)
  4. Push top candidates to Telegram daily

No orders placed in Phase 1. Run manually or via daily systemd timer to build intuition.

Deribit API: https://docs.deribit.com — public endpoints, no auth needed.
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger("deribit")

PROJECT_DIR = Path(__file__).parent.parent
DERIBIT_URL = "https://www.deribit.com/api/v2"


class DeribitMonitor:

    def __init__(self):
        self.session = requests.Session()

    # ---- Data fetchers ----

    def get_spot_price(self) -> float:
        """Get BTC index price from Deribit."""
        r = self.session.get(f"{DERIBIT_URL}/public/get_index_price",
                             params={"index_name": "btc_usd"}, timeout=10)
        return float(r.json()["result"]["index_price"])

    def get_option_chain(self, currency: str = "BTC") -> list[dict]:
        """Get summary for all options (bid/ask/iv)."""
        r = self.session.get(
            f"{DERIBIT_URL}/public/get_book_summary_by_currency",
            params={"currency": currency, "kind": "option"},
            timeout=15,
        )
        return r.json()["result"]

    def get_instrument_ticker(self, name: str) -> dict:
        """Get full ticker for a specific instrument (includes Greeks)."""
        r = self.session.get(
            f"{DERIBIT_URL}/public/ticker",
            params={"instrument_name": name},
            timeout=10,
        )
        return r.json().get("result", {})

    # ---- Parsing ----

    @staticmethod
    def parse_instrument(name: str) -> dict | None:
        """
        Parse Deribit instrument name like 'BTC-26APR26-90000-P' into parts.
        Returns: {underlying, expiry_date, strike, option_type}
        """
        match = re.match(r"^([A-Z]+)-(\d{1,2}[A-Z]{3}\d{2})-(\d+)-([PC])$", name)
        if not match:
            return None
        underlying, expiry_str, strike, opt_type = match.groups()
        try:
            expiry = datetime.strptime(expiry_str, "%d%b%y").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        return {
            "underlying": underlying,
            "expiry": expiry,
            "strike": int(strike),
            "type": "put" if opt_type == "P" else "call",
        }

    # ---- CSP filter and ranking ----

    def find_csp_candidates(
        self,
        spot: float,
        chain: list[dict],
        min_days: int = 5,
        max_days: int = 30,
        min_otm_pct: float = 0.10,
        max_otm_pct: float = 0.30,
    ) -> list[dict]:
        """
        Filter and rank CSP (sell-put) candidates.
        """
        now = datetime.now(timezone.utc)
        candidates = []

        for entry in chain:
            name = entry["instrument_name"]
            parsed = self.parse_instrument(name)
            if not parsed or parsed["type"] != "put":
                continue

            # Days to expiry
            days = (parsed["expiry"] - now).total_seconds() / 86400
            if days < min_days or days > max_days:
                continue

            strike = parsed["strike"]
            otm_pct = (spot - strike) / spot
            if otm_pct < min_otm_pct or otm_pct > max_otm_pct:
                continue

            bid = float(entry.get("bid_price") or 0)
            ask = float(entry.get("ask_price") or 0)
            if bid <= 0:
                continue  # no liquidity

            mark_iv = float(entry.get("mark_iv") or 0)
            volume = float(entry.get("volume") or 0)
            open_interest = float(entry.get("open_interest") or 0)

            # Deribit quotes puts in BTC, so USD premium = bid * spot
            premium_usd = bid * spot
            # Collateral for CSP = strike (need to buy BTC at strike)
            annual_yield_pct = (premium_usd / strike) * (365 / days) * 100
            # Max loss if BTC goes to 0 (unlikely but): strike - premium_usd
            max_loss = strike - premium_usd

            candidates.append({
                "instrument": name,
                "strike": strike,
                "days_to_expiry": round(days, 1),
                "otm_pct": round(otm_pct * 100, 1),
                "bid_btc": bid,
                "ask_btc": ask,
                "premium_usd": round(premium_usd, 2),
                "mark_iv": round(mark_iv, 1),
                "volume": volume,
                "open_interest": open_interest,
                "annual_yield_pct": round(annual_yield_pct, 2),
                "max_loss_usd": round(max_loss, 2),
                "expiry": parsed["expiry"].strftime("%Y-%m-%d"),
            })

        # Rank by yield-adjusted score
        # Higher yield is better, but also prefer higher liquidity and lower IV (safer)
        for c in candidates:
            liquidity_score = min(c["open_interest"] / 100, 1.0)  # normalize
            iv_penalty = max(0, (c["mark_iv"] - 60) / 100)  # penalize IV > 60
            c["rank_score"] = c["annual_yield_pct"] * (1 + liquidity_score) - iv_penalty * 20

        candidates.sort(key=lambda c: c["rank_score"], reverse=True)
        return candidates

    def enrich_with_greeks(self, candidate: dict) -> dict:
        """Fetch Greeks (delta, theta, vega) for a single instrument."""
        try:
            ticker = self.get_instrument_ticker(candidate["instrument"])
            greeks = ticker.get("greeks", {})
            candidate["delta"] = round(greeks.get("delta", 0), 3)
            candidate["theta"] = round(greeks.get("theta", 0), 2)
            candidate["gamma"] = round(greeks.get("gamma", 0), 5)
            candidate["vega"] = round(greeks.get("vega", 0), 2)
            # Assignment probability approximation: |delta|
            candidate["assignment_prob_pct"] = round(abs(candidate["delta"]) * 100, 1)
        except Exception as e:
            logger.debug(f"Greeks fetch failed for {candidate['instrument']}: {e}")
        return candidate

    # ---- Reporting ----

    def run(self, top_n: int = 5) -> dict:
        """Main entry: fetch, filter, rank, report."""
        logger.info("=== Deribit BTC Options Monitor ===")

        spot = self.get_spot_price()
        chain = self.get_option_chain("BTC")
        logger.info(f"Spot: ${spot:,.0f} | Total options: {len(chain)}")

        candidates = self.find_csp_candidates(spot, chain)
        logger.info(f"CSP candidates (5-30d, 10-30% OTM, has bid): {len(candidates)}")

        # Enrich top N with Greeks
        top = candidates[:top_n]
        for c in top:
            self.enrich_with_greeks(c)

        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "spot_price": spot,
            "total_candidates": len(candidates),
            "top_candidates": top,
        }

        # Print table
        print(f"\n{'='*95}")
        print(f"  Top {top_n} BTC CSP candidates @ spot ${spot:,.0f}")
        print(f"{'='*95}")
        print(f"  {'Instrument':28s} {'Strike':>7s} {'Days':>5s} {'OTM%':>6s} {'Prem$':>8s} {'Yield%':>7s} {'Δ':>6s} {'Assign%':>7s}")
        print(f"  {'-'*95}")
        for c in top:
            delta = c.get("delta", "?")
            delta_str = f"{delta:+.2f}" if isinstance(delta, (int, float)) else str(delta)
            ap = c.get("assignment_prob_pct", "?")
            print(
                f"  {c['instrument']:28s} "
                f"{c['strike']:>7d} "
                f"{c['days_to_expiry']:>5.1f} "
                f"{c['otm_pct']:>5.1f}% "
                f"{c['premium_usd']:>8.0f} "
                f"{c['annual_yield_pct']:>6.2f}% "
                f"{delta_str:>6s} "
                f"{ap if isinstance(ap, (int, float)) else '?':>6}%"
            )
        print(f"{'='*95}")

        return snapshot

    def send_telegram(self, snapshot: dict):
        """Push top 3 candidates to Telegram."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat:
            logger.info("Telegram not configured")
            return

        spot = snapshot["spot_price"]
        top = snapshot["top_candidates"][:3]
        if not top:
            return

        lines = [
            f"📊 *Deribit BTC CSP Candidates*",
            f"Spot: ${spot:,.0f} | {snapshot['total_candidates']} candidates",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]
        for i, c in enumerate(top, 1):
            delta = c.get("delta", 0)
            ap = c.get("assignment_prob_pct", "?")
            lines.append(
                f"\n*#{i} {c['instrument']}*\n"
                f"  Strike: \\${c['strike']:,} ({c['otm_pct']:.1f}% OTM)\n"
                f"  Premium: \\${c['premium_usd']:.0f} "
                f"({c['bid_btc']} BTC)\n"
                f"  Days: {c['days_to_expiry']:.0f} | "
                f"IV: {c['mark_iv']:.0f}%\n"
                f"  *Annual yield: {c['annual_yield_pct']:.1f}%*\n"
                f"  Δ={delta} Assign prob: {ap}%\n"
                f"  OI: {c['open_interest']:.0f}"
            )

        lines.append(
            "\n━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Monitoring only. Review on Deribit before selling._"
        )

        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat,
                    "text": "\n".join(lines),
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            logger.info(f"Pushed {len(top)} candidates to Telegram")
        except Exception as e:
            logger.warning(f"Telegram failed: {e}")

    def log_to_supabase(self, snapshot: dict):
        """Store snapshot in Supabase for history."""
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")
        if not url or not key:
            return
        try:
            record = {
                "timestamp": snapshot["timestamp"],
                "spot_price": snapshot["spot_price"],
                "total_candidates": snapshot["total_candidates"],
                "top_candidates": snapshot["top_candidates"],
            }
            resp = requests.post(
                f"{url}/rest/v1/deribit_snapshots",
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json=record,
                timeout=10,
            )
            if resp.status_code < 300:
                logger.info("Snapshot logged to Supabase")
            else:
                logger.debug(f"Supabase: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"Supabase log failed: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5, help="Top N candidates to show")
    ap.add_argument("--telegram", action="store_true", help="Push top 3 to Telegram")
    ap.add_argument("--quiet", action="store_true", help="No console output, just log")
    args = ap.parse_args()

    level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")

    monitor = DeribitMonitor()
    snapshot = monitor.run(top_n=args.top)

    if args.telegram:
        monitor.send_telegram(snapshot)

    monitor.log_to_supabase(snapshot)


if __name__ == "__main__":
    main()
