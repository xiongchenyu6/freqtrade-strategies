"""
BTC Cycle & On-Chain Factors — Bitcoin-specific signals

Calculable from OHLCV (backtestable):
  1. Halving Cycle Position — where are we in the 4-year cycle
  2. Pi Cycle Top — 111d MA vs 350d MA x2 crossover (called every top)
  3. 200-Week MA — ultimate support, never closed below
  4. Hash Ribbons — 30d vs 60d hashrate MA crossover
  5. Power Law Corridor — logarithmic regression support/resistance

From Santiment API:
  6. MVRV Ratio — >3.5 top, <1 bottom
  7. Realized Price — avg cost basis of all BTC, key support
  8. NVT Ratio — network valuation metric
  9. Network Profit/Loss — are holders in profit or loss
  10. Age Consumed — old coins moving = distribution
"""

import logging
import math
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import requests

logger = logging.getLogger("btc_cycle")

SANTIMENT_API_KEY = os.environ.get("SANTIMENT_API_KEY", "")

# BTC Genesis date
GENESIS = datetime(2009, 1, 3, tzinfo=timezone.utc)

# Power Law coefficients: log10(price) = POWER_A * log10(days_since_genesis) + POWER_B
# Fitted from cycle peaks: 2011, 2013, 2017, 2021
POWER_A = 4.67
POWER_B = -12.19

# Cycle peak multiplier decay: each peak is a smaller multiple of previous
# 37x → 17x → 3.5x → expected ~2-3x for cycle 5
PEAK_DECAY_RATE = 0.45  # each cycle peak mult ≈ prev * decay_rate

# Historical cycle data for diminishing returns model
CYCLE_PEAKS = [
    {"date": datetime(2011, 6, 8, tzinfo=timezone.utc), "price": 31},
    {"date": datetime(2013, 12, 4, tzinfo=timezone.utc), "price": 1150},
    {"date": datetime(2017, 12, 17, tzinfo=timezone.utc), "price": 19800},
    {"date": datetime(2021, 11, 10, tzinfo=timezone.utc), "price": 69000},
]

CYCLE_BOTTOMS = [
    {"date": datetime(2011, 11, 18, tzinfo=timezone.utc), "price": 2},
    {"date": datetime(2015, 1, 14, tzinfo=timezone.utc), "price": 170},
    {"date": datetime(2018, 12, 15, tzinfo=timezone.utc), "price": 3200},
    {"date": datetime(2022, 11, 21, tzinfo=timezone.utc), "price": 15500},
]

# BTC Halving dates
HALVINGS = [
    datetime(2012, 11, 28, tzinfo=timezone.utc),  # 50 → 25
    datetime(2016, 7, 9, tzinfo=timezone.utc),     # 25 → 12.5
    datetime(2020, 5, 11, tzinfo=timezone.utc),    # 12.5 → 6.25
    datetime(2024, 4, 20, tzinfo=timezone.utc),    # 6.25 → 3.125
    datetime(2028, 4, 1, tzinfo=timezone.utc),     # 3.125 → 1.5625 (estimated)
]


class BTCCycleFactors:
    """BTC-specific cycle and on-chain analysis."""

    def __init__(self):
        self._cache = {}
        self._cache_ts = 0
        self._CACHE_TTL = 3600

    # ------------------------------------------------------------------
    # 1. Halving Cycle Position
    # ------------------------------------------------------------------
    def halving_cycle_position(self, current_date: datetime = None) -> dict:
        """
        Where in the ~4-year halving cycle are we?
        0.0 = just halved, 1.0 = next halving imminent

        Historical pattern:
        - 0.0 to 0.3 (0-15 months post-halving): accumulation, gradual rise
        - 0.3 to 0.5 (15-24 months): parabolic run-up, bull market peak
        - 0.5 to 0.7 (24-33 months): distribution, decline begins
        - 0.7 to 1.0 (33-48 months): bear market bottom, pre-halving accumulation
        """
        if current_date is None:
            current_date = datetime.now(timezone.utc)

        # Find current cycle
        prev_halving = None
        next_halving = None
        for i, h in enumerate(HALVINGS):
            if h > current_date:
                next_halving = h
                prev_halving = HALVINGS[i-1] if i > 0 else HALVINGS[0]
                break

        if not prev_halving or not next_halving:
            return {"score": 0, "position": 0.5, "signal": "neutral", "phase": "unknown"}

        cycle_length = (next_halving - prev_halving).days
        days_since = (current_date - prev_halving).days
        position = days_since / cycle_length  # 0 to 1

        # Score based on historical cycle pattern
        if position < 0.3:
            score = 0.5   # early post-halving = strong accumulation zone
            phase = "accumulation"
        elif position < 0.45:
            score = 0.3   # mid-cycle = bull run forming
            phase = "bull_forming"
        elif position < 0.55:
            score = -0.2  # cycle peak zone = caution
            phase = "peak_zone"
        elif position < 0.75:
            score = -0.5  # distribution/decline
            phase = "distribution"
        else:
            score = 0.2   # pre-halving accumulation
            phase = "pre_halving_accumulation"

        days_to_next = (next_halving - current_date).days

        logger.info(
            f"Halving Cycle: position={position:.2f}, phase={phase}, "
            f"days_since={days_since}, days_to_next={days_to_next}"
        )

        return {
            "score": score,
            "position": round(position, 3),
            "phase": phase,
            "days_since_halving": days_since,
            "days_to_next_halving": days_to_next,
            "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral",
        }

    # ------------------------------------------------------------------
    # 1b. Power Law Corridor — logarithmic fair value
    # ------------------------------------------------------------------
    @staticmethod
    def power_law_position(current_price: float, current_date: datetime = None) -> dict:
        """
        BTC Power Law: price follows a power law over time.
        log10(price) = 4.67 * log10(days_since_genesis) - 12.19

        Returns position relative to the power law trend:
        - ratio < 0.3 = deeply undervalued (strong buy)
        - ratio 0.3-0.7 = undervalued (buy)
        - ratio 0.7-1.5 = fair value
        - ratio 1.5-3.0 = overvalued (caution)
        - ratio > 3.0 = extremely overvalued (sell zone)

        The key insight: "this time is different" is always wrong.
        BTC reverts to the power law trend.
        """
        if current_date is None:
            current_date = datetime.now(timezone.utc)

        days = (current_date - GENESIS).days
        if days <= 0 or current_price <= 0:
            return {"score": 0, "signal": "neutral"}

        fair_value = 10 ** (POWER_A * math.log10(days) + POWER_B)
        ratio = current_price / fair_value

        # Support line (roughly 0.15x of fair value historically)
        support = fair_value * 0.15
        # Resistance (roughly 3x of fair value at peaks, but diminishing)
        resistance = fair_value * 2.5

        if ratio < 0.3:
            score = 0.8   # deeply undervalued
        elif ratio < 0.7:
            score = 0.5   # undervalued
        elif ratio < 1.5:
            score = 0.1   # fair value zone
        elif ratio < 2.5:
            score = -0.4  # overvalued
        else:
            score = -0.8  # extremely overvalued (cycle top zone)

        logger.info(
            f"Power Law: fair=${fair_value:,.0f}, current=${current_price:,.0f}, "
            f"ratio={ratio:.2f}x, support=${support:,.0f}, resistance=${resistance:,.0f}, score={score:+.1f}"
        )

        return {
            "score": score,
            "fair_value": round(fair_value, 2),
            "ratio": round(ratio, 3),
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "signal": "bullish" if score > 0.3 else "bearish" if score < -0.3 else "neutral",
        }

    # ------------------------------------------------------------------
    # 1c. Diminishing Returns Model — expected cycle peak/bottom
    # ------------------------------------------------------------------
    @staticmethod
    def diminishing_returns_model(current_price: float) -> dict:
        """
        Each cycle peak multiplier decays: 37x → 17x → 3.5x → ~2x

        Predicts:
        - Expected cycle 5 peak: ~$140K-$200K (2x-3x from $69K)
        - Expected cycle 5 bottom: ~$45K-$60K (based on shallowing drawdowns)
        - Bull longer, bear shorter pattern

        Current price position relative to expected range tells us
        how much upside/downside remains.
        """
        last_peak = CYCLE_PEAKS[-1]["price"]  # $69K
        last_bottom = CYCLE_BOTTOMS[-1]["price"]  # $15.5K

        # Projected next peak (diminishing returns: ~2-3x of prev peak)
        expected_peak_low = last_peak * 2.0   # conservative: $138K
        expected_peak_high = last_peak * 3.0  # optimistic: $207K
        expected_peak_mid = last_peak * 2.5   # $172K

        # Projected next bottom (shallowing drawdowns: -65% to -75%)
        expected_bottom = expected_peak_mid * 0.30  # ~$52K (70% drawdown from peak)

        # Where is current price in the expected range?
        if current_price < last_bottom:
            position = "below_prev_bottom"
            score = 0.9   # below previous cycle bottom = once in a lifetime
        elif current_price < expected_bottom:
            position = "below_expected_bottom"
            score = 0.6   # below expected next bottom = strong value
        elif current_price < last_peak:
            position = "below_prev_peak"
            upside = (expected_peak_mid - current_price) / current_price
            score = min(0.4, upside * 0.5)  # proportional to upside
        elif current_price < expected_peak_low:
            position = "approaching_peak"
            score = 0.0   # near expected peak range
        elif current_price < expected_peak_high:
            position = "in_peak_zone"
            score = -0.5  # in expected peak range
        else:
            position = "above_expected_peak"
            score = -0.8  # above expected peak = extreme caution

        logger.info(
            f"Diminishing Returns: current=${current_price:,.0f}, "
            f"expected_peak=${expected_peak_low:,.0f}-${expected_peak_high:,.0f}, "
            f"expected_bottom=${expected_bottom:,.0f}, position={position}, score={score:+.1f}"
        )

        return {
            "score": round(score, 3),
            "position": position,
            "expected_peak_low": round(expected_peak_low),
            "expected_peak_high": round(expected_peak_high),
            "expected_bottom": round(expected_bottom),
            "upside_to_peak_pct": round((expected_peak_mid - current_price) / current_price * 100, 1),
            "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral",
        }

    # ------------------------------------------------------------------
    # 2. Pi Cycle Top Indicator (calculable from price)
    # ------------------------------------------------------------------
    @staticmethod
    def pi_cycle_check(closes: list[float]) -> dict:
        """
        Pi Cycle Top: 111-day MA crosses above 350-day MA * 2.
        Has called every BTC cycle top within 3 days.
        Needs 350+ days of data.
        """
        if len(closes) < 350:
            return {"score": 0, "signal": "neutral", "triggered": False}

        closes_arr = np.array(closes)
        ma_111 = np.mean(closes_arr[-111:])
        ma_350x2 = np.mean(closes_arr[-350:]) * 2

        # Distance between the two MAs
        distance = (ma_111 - ma_350x2) / ma_350x2

        if distance > 0:
            # MA111 above MA350x2 = TOP signal!
            score = -0.8
            triggered = True
        elif distance > -0.05:
            # Very close to crossing = warning
            score = -0.4
            triggered = False
        else:
            score = 0.0
            triggered = False

        logger.info(f"Pi Cycle: MA111={ma_111:.0f}, MA350x2={ma_350x2:.0f}, dist={distance:+.1%}, triggered={triggered}")

        return {
            "score": score,
            "ma_111": round(ma_111, 2),
            "ma_350x2": round(ma_350x2, 2),
            "distance_pct": round(distance * 100, 2),
            "triggered": triggered,
            "signal": "bearish" if triggered else "neutral",
        }

    # ------------------------------------------------------------------
    # 3. 200-Week MA — ultimate support
    # ------------------------------------------------------------------
    @staticmethod
    def two_hundred_week_ma(closes_weekly: list[float], current_price: float) -> dict:
        """
        200-week MA: BTC has never closed a week below this.
        Price near or below = generational buying opportunity.
        """
        if len(closes_weekly) < 200:
            return {"score": 0, "signal": "neutral"}

        ma_200w = np.mean(closes_weekly[-200:])
        distance = (current_price - ma_200w) / ma_200w

        if distance < 0:
            score = 0.9   # below 200W MA = historic buy signal
        elif distance < 0.2:
            score = 0.6   # within 20% = very attractive
        elif distance < 0.5:
            score = 0.2   # within 50% = reasonable
        elif distance > 3.0:
            score = -0.5  # 3x+ above = extended
        elif distance > 2.0:
            score = -0.3  # 2x above = getting frothy
        else:
            score = 0.0

        logger.info(f"200W MA: {ma_200w:.0f}, price={current_price:.0f}, dist={distance:+.0%}, score={score:+.1f}")

        return {
            "score": score,
            "ma_200w": round(ma_200w, 2),
            "distance_pct": round(distance * 100, 1),
            "signal": "bullish" if score > 0.3 else "bearish" if score < -0.2 else "neutral",
        }

    # ------------------------------------------------------------------
    # Santiment Metrics (6-10)
    # ------------------------------------------------------------------
    def _san_query(self, metric: str, days_back: int = 14) -> Optional[list]:
        if not SANTIMENT_API_KEY:
            return None
        to_dt = datetime.now(timezone.utc) - timedelta(days=30)
        from_dt = to_dt - timedelta(days=days_back)
        query = '{getMetric(metric: "%s") {timeseriesData(slug: "bitcoin" from: "%s" to: "%s" interval: "1d") {datetime value}}}' % (
            metric, from_dt.strftime("%Y-%m-%dT00:00:00Z"), to_dt.strftime("%Y-%m-%dT00:00:00Z"))
        try:
            resp = requests.post("https://api.santiment.net/graphql",
                headers={"Authorization": f"Apikey {SANTIMENT_API_KEY}"},
                json={"query": query}, timeout=15)
            gm = resp.json().get("data", {}).get("getMetric")
            return gm.get("timeseriesData") if gm else None
        except Exception as e:
            logger.debug(f"Santiment {metric}: {e}")
            return None

    def fetch_mvrv(self) -> dict:
        """Factor 6: MVRV — Market Value to Realized Value."""
        data = self._san_query("mvrv_usd", 14)
        if not data:
            return {"score": 0, "value": None, "signal": "neutral"}

        mvrv = data[-1]["value"]

        if mvrv > 3.5:
            score = -0.8  # extremely overvalued = cycle top
        elif mvrv > 2.5:
            score = -0.4  # overvalued
        elif mvrv < 1.0:
            score = 0.8   # undervalued = strong buy
        elif mvrv < 1.5:
            score = 0.4   # slightly undervalued
        else:
            score = 0.0

        logger.info(f"MVRV: {mvrv:.2f}, score={score:+.1f}")
        return {"score": score, "value": round(mvrv, 3), "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral"}

    def fetch_realized_price(self) -> dict:
        """Factor 7: Realized Price — avg cost basis of all BTC."""
        data = self._san_query("mean_realized_price_usd", 7)
        if not data:
            return {"score": 0, "value": None, "signal": "neutral"}

        realized = data[-1]["value"]

        # Get current BTC price
        try:
            resp = requests.get("https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "bitcoin", "vs_currencies": "usd"}, timeout=10)
            current = resp.json()["bitcoin"]["usd"]
        except Exception:
            return {"score": 0, "value": round(realized), "signal": "neutral"}

        ratio = current / realized if realized > 0 else 1

        if ratio < 0.9:
            score = 0.8   # below realized = historically rare buy
        elif ratio < 1.1:
            score = 0.5   # near realized = strong value
        elif ratio > 3.0:
            score = -0.4  # 3x above = extended
        else:
            score = 0.0

        logger.info(f"Realized Price: ${realized:.0f}, current=${current:.0f}, ratio={ratio:.2f}, score={score:+.1f}")
        return {"score": score, "value": round(realized), "current": round(current), "ratio": round(ratio, 2), "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral"}

    def fetch_nvt(self) -> dict:
        """Factor 8: NVT — Network Value to Transactions. High = overvalued."""
        data = self._san_query("nvt", 14)
        if not data:
            return {"score": 0, "signal": "neutral"}

        nvt = data[-1]["value"]
        avg = sum(d["value"] for d in data) / len(data)

        if nvt > 150:
            score = -0.3  # overvalued relative to usage
        elif nvt < 50:
            score = 0.3   # undervalued, lots of usage
        else:
            score = 0.0

        logger.info(f"NVT: {nvt:.0f} (avg {avg:.0f}), score={score:+.1f}")
        return {"score": score, "value": round(nvt, 1), "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral"}

    def fetch_age_consumed(self) -> dict:
        """Factor 10: Age Consumed — old coins moving = distribution."""
        data = self._san_query("age_consumed", 14)
        if not data or len(data) < 7:
            return {"score": 0, "signal": "neutral"}

        recent = sum(d["value"] for d in data[-3:]) / 3
        older = sum(d["value"] for d in data[:7]) / 7

        if older == 0:
            return {"score": 0, "signal": "neutral"}

        spike = recent / older

        if spike > 5:
            score = -0.5  # massive old coin movement = distribution/top
        elif spike > 2:
            score = -0.2
        else:
            score = 0.0

        logger.info(f"Age Consumed: spike={spike:.1f}x, score={score:+.1f}")
        return {"score": score, "spike_ratio": round(spike, 1), "signal": "bearish" if score < -0.2 else "neutral"}

    # ------------------------------------------------------------------
    # Combined
    # ------------------------------------------------------------------
    # ---- Extra valuation indicators (added from user request) ----

    @staticmethod
    def mayer_multiple(current_price: float, closes_daily: list[float]) -> dict:
        """Price / 200D MA. <1 undervalued, >2.4 overvalued."""
        if len(closes_daily) < 200 or current_price <= 0:
            return {"value": None, "signal": "neutral", "score": 0.0}
        ma200 = sum(closes_daily[-200:]) / 200
        mm = current_price / ma200
        if mm < 0.6:
            score = 1.0
        elif mm < 1.0:
            score = 0.6 + (1.0 - mm) * 1.0
        elif mm < 1.5:
            score = (1.5 - mm) * 1.2
        elif mm < 2.4:
            score = -(mm - 1.5) * 0.66
        else:
            score = -0.6 - min((mm - 2.4) * 0.5, 0.4)
        return {
            "value": round(mm, 3),
            "ma200": round(ma200, 0),
            "signal": "buy" if mm < 1.0 else "sell" if mm > 2.4 else "hold",
            "score": round(max(-1.0, min(1.0, score)), 3),
        }

    @staticmethod
    def ahr999_index(current_price: float, closes_daily: list[float]) -> dict:
        """Ahr999 = (price/200D geomean) × (price/fitted). <0.45=hard_buy, >1.2=sell."""
        if len(closes_daily) < 200 or current_price <= 0:
            return {"value": None, "signal": "neutral", "score": 0.0}
        sub = closes_daily[-200:]
        geo_mean = math.exp(sum(math.log(p) for p in sub if p > 0) / 200)
        days = (datetime.now(timezone.utc) - GENESIS).days
        fitted = 10 ** (5.84 * math.log10(days) - 17.01)
        ratio_ma = current_price / geo_mean
        ratio_fit = current_price / fitted
        ahr = ratio_ma * ratio_fit
        if ahr < 0.45:
            score = 1.0
        elif ahr < 0.75:
            score = 0.6 + (0.75 - ahr) / 0.3 * 0.4
        elif ahr < 1.2:
            score = (1.2 - ahr) / 0.45 * 0.6
        elif ahr < 2.0:
            score = -(ahr - 1.2) / 0.8 * 0.6
        else:
            score = -0.6 - min((ahr - 2.0) * 0.3, 0.4)
        return {
            "value": round(ahr, 3),
            "ratio_ma": round(ratio_ma, 3),
            "ratio_fit": round(ratio_fit, 3),
            "fitted_price": round(fitted, 0),
            "signal": "strong_buy" if ahr < 0.45 else "buy" if ahr < 1.2 else "sell",
            "score": round(max(-1.0, min(1.0, score)), 3),
        }

    @staticmethod
    def ahr999x_top_escape(current_price: float, closes_daily: list[float]) -> dict:
        """Ahr999x inverse — high = near top. >10 = escape top."""
        if len(closes_daily) < 200 or current_price <= 0:
            return {"value": None, "signal": "neutral", "score": 0.0}
        sub = closes_daily[-200:]
        geo_mean = math.exp(sum(math.log(p) for p in sub if p > 0) / 200)
        days = (datetime.now(timezone.utc) - GENESIS).days
        fitted = 10 ** (5.84 * math.log10(days) - 17.01)
        x = (fitted / current_price) * (current_price / geo_mean)
        if x > 20:
            score = -1.0
        elif x > 10:
            score = -0.5 - (x - 10) / 10 * 0.5
        elif x > 5:
            score = -(x - 5) / 5 * 0.5
        else:
            score = 0.0
        return {
            "value": round(x, 3),
            "signal": "escape_top" if x > 10 else "warn" if x > 5 else "safe",
            "score": round(max(-1.0, min(1.0, score)), 3),
        }

    @staticmethod
    def four_year_ma(current_price: float, closes_daily: list[float]) -> dict:
        """Price vs 4Y (1460d) MA. Below = historic bottom buy zone."""
        need = 365 * 4
        if len(closes_daily) < need or current_price <= 0:
            return {"value": None, "signal": "neutral", "score": 0.0}
        ma = sum(closes_daily[-need:]) / need
        ratio = current_price / ma
        if ratio < 1.0:
            score = 1.0
        elif ratio < 1.5:
            score = 1.0 - (ratio - 1.0) / 0.5 * 0.5
        elif ratio < 3.0:
            score = 0.5 - (ratio - 1.5) / 1.5 * 0.8
        else:
            score = -0.3 - min((ratio - 3.0) * 0.2, 0.5)
        return {
            "value": round(ratio, 2),
            "ma_4y": round(ma, 0),
            "signal": "deep_buy" if ratio < 1.0 else "buy" if ratio < 1.5 else "hold",
            "score": round(max(-1.0, min(1.0, score)), 3),
        }

    @staticmethod
    def stock_to_flow(current_price: float) -> dict:
        """PlanB S2F model: model_price = exp(3.3*ln(stock/flow) - 1.84)."""
        now = datetime.now(timezone.utc)
        block_height = int((now - GENESIS).total_seconds() / 600)
        halving_blocks = 210000
        stock = 0
        remaining = block_height
        reward = 50
        for _ in range(10):
            be = min(remaining, halving_blocks)
            stock += be * reward
            remaining -= be
            reward /= 2
            if remaining <= 0:
                break
        halvings_done = sum(1 for _ in range(10) if block_height > _ * halving_blocks and _ > 0)
        current_reward = 50 / (2 ** min(halvings_done, 5))
        flow = current_reward * (365 * 24 * 6)
        if flow <= 0 or stock <= 0:
            return {"value": None, "signal": "neutral", "score": 0.0}
        sf = stock / flow
        model_price = math.exp(3.3 * math.log(sf) - 1.84)
        deviation = (current_price - model_price) / model_price
        if deviation < -0.5:
            score = 1.0
        elif deviation < 0:
            score = -deviation * 1.5
        elif deviation < 1.0:
            score = -deviation * 0.5
        else:
            score = -0.5 - min((deviation - 1.0) * 0.3, 0.5)
        return {
            "sf_ratio": round(sf, 1),
            "model_price": round(model_price, 0),
            "deviation_pct": round(deviation * 100, 1),
            "signal": "buy" if deviation < -0.2 else "sell" if deviation > 0.5 else "hold",
            "score": round(max(-1.0, min(1.0, score)), 3),
        }

    @staticmethod
    def rainbow_band(current_price: float) -> dict:
        """Rainbow log regression: 9 bands from Fire Sale to Max Bubble."""
        days = (datetime.now(timezone.utc) - GENESIS).days
        center = 10 ** (1.95 * math.log10(days) - 2.8)
        if center <= 0 or current_price <= 0:
            return {"band": "unknown", "score": 0.0}
        ratio = current_price / center
        if ratio < 0.45:
            band, score = "Fire Sale", 1.0
        elif ratio < 0.7:
            band, score = "Buy", 0.7
        elif ratio < 0.95:
            band, score = "Accumulate", 0.4
        elif ratio < 1.35:
            band, score = "Cheap", 0.2
        elif ratio < 1.9:
            band, score = "HODL", 0.0
        elif ratio < 2.7:
            band, score = "Is This FOMO", -0.3
        elif ratio < 3.85:
            band, score = "Sell", -0.6
        elif ratio < 5.5:
            band, score = "Bubble Territory", -0.8
        else:
            band, score = "Maximum Bubble", -1.0
        return {
            "band": band,
            "center_price": round(center, 0),
            "price_ratio": round(ratio, 2),
            "signal": "buy" if score > 0.3 else "sell" if score < -0.3 else "hold",
            "score": round(score, 3),
        }

    @staticmethod
    def bubble_index(current_price: float, closes_daily: list[float]) -> dict:
        """Price vs 2Y MA. >2.5 = bubble territory."""
        if len(closes_daily) < 730 or current_price <= 0:
            return {"value": None, "signal": "neutral", "score": 0.0}
        ma_2y = sum(closes_daily[-730:]) / 730
        ratio = current_price / ma_2y
        if ratio < 1.0:
            score = 0.7
        elif ratio < 1.5:
            score = 0.3
        elif ratio < 2.5:
            score = -0.3
        elif ratio < 4.0:
            score = -0.7
        else:
            score = -1.0
        return {
            "value": round(ratio, 2),
            "ma_2y": round(ma_2y, 0),
            "signal": "buy" if ratio < 1.0 else "sell" if ratio > 2.5 else "hold",
            "score": round(score, 3),
        }

    def fetch_all(self, btc_closes_daily: list[float] = None, btc_closes_weekly: list[float] = None, current_price: float = 0) -> dict:
        now = time.time()
        if now - self._cache_ts < self._CACHE_TTL and self._cache:
            return self._cache

        results = {}
        scores = []

        # 1. Halving cycle (always available)
        halving = self.halving_cycle_position()
        results["halving"] = halving
        scores.append((halving["score"], 0.20))

        # 1b-1c. Power law + diminishing returns (need current price)
        if current_price > 0:
            power = self.power_law_position(current_price)
            results["power_law"] = power
            scores.append((power["score"], 0.15))

            diminish = self.diminishing_returns_model(current_price)
            results["diminishing_returns"] = diminish
            scores.append((diminish["score"], 0.10))

        # 2-3. Technical (need price data)
        if btc_closes_daily and len(btc_closes_daily) >= 350:
            pi = self.pi_cycle_check(btc_closes_daily)
            results["pi_cycle"] = pi
            scores.append((pi["score"], 0.12))

        if btc_closes_weekly and len(btc_closes_weekly) >= 200 and current_price > 0:
            w200 = self.two_hundred_week_ma(btc_closes_weekly, current_price)
            results["200w_ma"] = w200
            scores.append((w200["score"], 0.08))

        # 2a. Extra valuation indicators (Mayer, Ahr999, etc.)
        if btc_closes_daily and current_price > 0:
            mayer = self.mayer_multiple(current_price, btc_closes_daily)
            results["mayer_multiple"] = mayer
            if mayer["score"] != 0:
                scores.append((mayer["score"], 0.10))

            ahr = self.ahr999_index(current_price, btc_closes_daily)
            results["ahr999"] = ahr
            if ahr["score"] != 0:
                scores.append((ahr["score"], 0.12))

            ahrx = self.ahr999x_top_escape(current_price, btc_closes_daily)
            results["ahr999x"] = ahrx
            if ahrx["score"] != 0:
                scores.append((ahrx["score"], 0.06))

            s2f = self.stock_to_flow(current_price)
            results["stock_to_flow"] = s2f
            if s2f["score"] != 0:
                scores.append((s2f["score"], 0.06))

            rainbow = self.rainbow_band(current_price)
            results["rainbow"] = rainbow
            if rainbow["score"] != 0:
                scores.append((rainbow["score"], 0.08))

            if len(btc_closes_daily) >= 730:
                bubble = self.bubble_index(current_price, btc_closes_daily)
                results["bubble_index"] = bubble
                if bubble["score"] != 0:
                    scores.append((bubble["score"], 0.06))

            if len(btc_closes_daily) >= 365 * 4:
                m4y = self.four_year_ma(current_price, btc_closes_daily)
                results["ma_4year"] = m4y
                if m4y["score"] != 0:
                    scores.append((m4y["score"], 0.08))

        # 6-10. Santiment metrics
        if SANTIMENT_API_KEY:
            mvrv = self.fetch_mvrv()
            results["mvrv"] = mvrv
            scores.append((mvrv["score"], 0.20))
            time.sleep(0.5)

            realized = self.fetch_realized_price()
            results["realized_price"] = realized
            scores.append((realized["score"], 0.15))
            time.sleep(0.5)

            nvt = self.fetch_nvt()
            results["nvt"] = nvt
            scores.append((nvt["score"], 0.10))
            time.sleep(0.5)

            age = self.fetch_age_consumed()
            results["age_consumed"] = age
            scores.append((age["score"], 0.10))

        # Weighted average
        if scores:
            total_w = sum(w for _, w in scores)
            combined = sum(s * w for s, w in scores) / total_w
        else:
            combined = 0

        combined = max(-1.0, min(1.0, combined))

        result = {
            "combined_score": round(combined, 3),
            "signal": "bullish" if combined > 0.15 else "bearish" if combined < -0.15 else "neutral",
            "factors": results,
        }

        self._cache = result
        self._cache_ts = now

        logger.info(
            f"BTC Cycle Combined: {combined:+.2f} | "
            f"halving={halving['phase']}({halving['score']:+.1f}) "
            f"mvrv={results.get('mvrv', {}).get('value', '?')}"
        )

        return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Get BTC price data for technical indicators
    closes_d = []
    closes_w = []
    current = 0
    try:
        # Paginate to get more than 1000 daily candles (need ~1500 for 4Y MA)
        closes_d = []
        end_ms = None
        for _ in range(3):
            params = {"symbol": "BTCUSDT", "interval": "1d", "limit": 1000}
            if end_ms:
                params["endTime"] = end_ms
            resp = requests.get("https://api.binance.com/api/v3/klines", params=params, timeout=15)
            batch = resp.json()
            if not batch:
                break
            closes_d = [float(k[4]) for k in batch] + closes_d
            end_ms = batch[0][0] - 1
            if len(closes_d) >= 1500:
                break
        current = closes_d[-1]
        resp2 = requests.get("https://api.binance.com/api/v3/klines",
            params={"symbol": "BTCUSDT", "interval": "1w", "limit": 250}, timeout=15)
        closes_w = [float(k[4]) for k in resp2.json()]
        print(f"Loaded {len(closes_d)} daily, {len(closes_w)} weekly candles")
    except Exception as e:
        print(f"Price data failed: {e}")

    bf = BTCCycleFactors()
    r = bf.fetch_all(closes_d, closes_w, current)

    print(f"\n{'='*55}")
    print(f"  BTC Cycle Analysis: {r['signal'].upper()} ({r['combined_score']:+.2f})")
    print(f"{'='*55}")
    for name, data in r["factors"].items():
        score = data.get("score", 0)
        icon = "🟢" if score > 0.2 else "🔴" if score < -0.2 else "⚪"
        extra = ""
        if "phase" in data: extra = f"phase={data['phase']}"
        elif "value" in data: extra = f"value={data['value']}"
        elif "triggered" in data: extra = f"triggered={data['triggered']}"
        elif "distance_pct" in data: extra = f"dist={data['distance_pct']}%"
        print(f"  {icon} {name:20s} {score:+.2f}  {extra}")
