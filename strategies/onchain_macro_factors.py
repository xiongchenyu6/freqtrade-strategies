"""
On-Chain + Cross-Market Factors — ALL FREE

Factor 11: BTC exchange flows (Blockchain.com)
Factor 12: Miner capitulation (Mempool.space hashrate trend)
Factor 13: Cross-market correlation (Yahoo Finance: Nasdaq, Gold, DXY)
Factor 14: Network activity (Blockchain.com transaction count)
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import requests

logger = logging.getLogger("onchain_macro")


class OnChainFactors:
    """Bitcoin on-chain health metrics."""

    def __init__(self):
        self._cache = {}
        self._cache_ts = 0

    def fetch_miner_health(self) -> dict:
        """Factor 12: Miner capitulation — hashrate trend from mempool.space."""
        try:
            resp = requests.get(
                "https://mempool.space/api/v1/mining/hashrate/3m", timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            hashrates = data.get("hashrates", [])

            if len(hashrates) < 14:
                return {"score": 0, "signal": "neutral"}

            # Compare last 2 weeks vs previous 2 weeks
            recent = [h["avgHashrate"] for h in hashrates[-14:]]
            older = [h["avgHashrate"] for h in hashrates[-28:-14]]

            recent_avg = np.mean(recent)
            older_avg = np.mean(older)
            change = (recent_avg - older_avg) / older_avg

            # Hashrate drop > 10% = miners capitulating = potential bottom
            if change < -0.10:
                score = 0.6  # miner capitulation = strong bottom signal
            elif change < -0.05:
                score = 0.3  # miners under stress
            elif change > 0.10:
                score = 0.2  # hashrate surging = miners confident
            else:
                score = 0.0

            logger.info(f"Miner Health: HR change 2w={change:+.1%}, score={score:+.1f}")

            return {
                "score": score,
                "hashrate_change_2w": round(change, 4),
                "signal": "bullish" if score > 0.2 else "neutral",
            }
        except Exception as e:
            logger.warning(f"Miner health failed: {e}")
            return {"score": 0, "signal": "neutral"}

    def fetch_network_activity(self) -> dict:
        """Factor 14: BTC transaction count — network usage."""
        try:
            resp = requests.get("https://blockchain.info/q/24hrtransactioncount", timeout=10)
            resp.raise_for_status()
            tx_count = int(resp.text.strip())

            # Normal range: 300K-500K/day
            if tx_count > 500000:
                score = 0.2  # high usage = healthy network
            elif tx_count < 200000:
                score = -0.2  # low usage = quiet
            else:
                score = 0.0

            logger.info(f"Network: {tx_count:,} tx/24h, score={score:+.1f}")

            return {
                "score": score,
                "tx_24h": tx_count,
                "signal": "bullish" if score > 0 else "neutral",
            }
        except Exception as e:
            logger.warning(f"Network activity failed: {e}")
            return {"score": 0, "signal": "neutral", "tx_24h": 0}

    def fetch_all(self) -> dict:
        now = time.time()
        if now - self._cache_ts < 3600 and self._cache:
            return self._cache

        miner = self.fetch_miner_health()
        time.sleep(0.3)
        network = self.fetch_network_activity()

        combined = miner["score"] * 0.6 + network["score"] * 0.4
        result = {
            "combined_score": round(combined, 3),
            "signal": "bullish" if combined > 0.15 else "bearish" if combined < -0.15 else "neutral",
            "miner": miner,
            "network": network,
        }
        self._cache = result
        self._cache_ts = now
        return result


class CrossMarketFactors:
    """Factor 13: BTC vs traditional markets — correlation and divergence."""

    SYMBOLS = {
        "nasdaq": "^IXIC",
        "gold": "GC=F",
        "dxy": "DX-Y.NYB",
    }

    def _fetch_yahoo(self, symbol: str, days: int = 30) -> list[float]:
        try:
            resp = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                params={"interval": "1d", "range": f"{days}d"},
                headers={"User-Agent": "CryptoBot/1.0"},
                timeout=15,
            )
            resp.raise_for_status()
            closes = resp.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            return [c for c in closes if c is not None]
        except Exception as e:
            logger.debug(f"Yahoo {symbol} failed: {e}")
            return []

    def fetch(self) -> dict:
        btc_prices = self._fetch_yahoo("BTC-USD")
        time.sleep(0.5)

        if len(btc_prices) < 10:
            return {"score": 0, "signal": "neutral", "correlations": {}}

        scores = []
        correlations = {}

        for name, symbol in self.SYMBOLS.items():
            prices = self._fetch_yahoo(symbol)
            time.sleep(0.3)

            if len(prices) < 10:
                continue

            # Align lengths
            min_len = min(len(btc_prices), len(prices))
            btc_returns = np.diff(btc_prices[-min_len:]) / btc_prices[-min_len:-1]
            mkt_returns = np.diff(prices[-min_len:]) / prices[-min_len:-1]

            min_ret_len = min(len(btc_returns), len(mkt_returns))
            corr = np.corrcoef(btc_returns[-min_ret_len:], mkt_returns[-min_ret_len:])[0, 1]
            correlations[name] = round(float(corr), 3) if not np.isnan(corr) else 0

            # DXY: inverse relationship — DXY down = crypto up
            if name == "dxy":
                mkt_trend = (prices[-1] - prices[-5]) / prices[-5]
                if mkt_trend < -0.01:
                    scores.append(0.3)  # DXY falling = bullish crypto
                elif mkt_trend > 0.01:
                    scores.append(-0.3)  # DXY rising = bearish crypto

            # Gold: safe haven correlation
            elif name == "gold":
                mkt_trend = (prices[-1] - prices[-5]) / prices[-5]
                if mkt_trend > 0.02:
                    scores.append(0.1)  # gold up = safe haven demand = slight crypto positive

        combined = sum(scores) / len(scores) if scores else 0
        combined = max(-1.0, min(1.0, combined))

        logger.info(f"Cross-Market: {correlations}, score={combined:+.2f}")

        return {
            "score": round(combined, 3),
            "signal": "bullish" if combined > 0.15 else "bearish" if combined < -0.15 else "neutral",
            "correlations": correlations,
        }


def fetch_all_onchain_macro() -> dict:
    """Fetch all on-chain + cross-market factors."""
    onchain = OnChainFactors().fetch_all()
    time.sleep(0.5)
    cross = CrossMarketFactors().fetch()

    combined = onchain["combined_score"] * 0.5 + cross["score"] * 0.5
    combined = max(-1.0, min(1.0, combined))

    logger.info(
        f"OnChain+Macro Combined: {combined:+.2f} | "
        f"OnChain={onchain['combined_score']:+.2f} Cross={cross['score']:+.2f}"
    )

    return {
        "combined_score": round(combined, 3),
        "signal": "bullish" if combined > 0.15 else "bearish" if combined < -0.15 else "neutral",
        "onchain": onchain,
        "cross_market": cross,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = fetch_all_onchain_macro()
    print(f"\nOnChain+Macro: {r['signal'].upper()} ({r['combined_score']:+.2f})")
    print(f"  Miner: {r['onchain']['miner']['signal']} (HR 2w chg: {r['onchain']['miner'].get('hashrate_change_2w', 0):+.1%})")
    print(f"  Network: {r['onchain']['network'].get('tx_24h', 0):,} tx/24h")
    print(f"  Correlations: {r['cross_market'].get('correlations', {})}")
