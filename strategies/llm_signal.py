"""
LLM-Powered Trading Signal Engine

Uses Claude to analyze news headlines, KOL events, and market context
to generate actionable trading signals with reasoning.

Output:
    {
        "signal": "long" / "short" / "neutral",
        "confidence": 0.0 - 1.0,
        "reasoning": "one paragraph explanation",
        "key_factors": ["factor1", "factor2"],
        "time_horizon": "immediate" / "short_term" / "medium_term",
    }

Usage:
    from llm_signal import LLMSignalEngine
    engine = LLMSignalEngine()
    signal = engine.analyze(headlines, kol_mentions, market_data)
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger("llm_signal")

ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


class LLMSignalEngine:
    """Generate trading signals using Claude."""

    def __init__(
        self,
        api_key: str = ANTHROPIC_API_KEY,
        base_url: str = ANTHROPIC_BASE_URL,
        model: str = "claude-sonnet-4-5-20241022",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._cache: dict = {}
        self._cache_ts: float = 0
        self._CACHE_TTL = 300  # 5 min cache

    def _call_claude(self, prompt: str, max_tokens: int = 500) -> Optional[str]:
        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set")
            return None

        try:
            resp = requests.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]
        except Exception as e:
            logger.warning(f"Claude API call failed: {e}")
            return None

    def analyze(
        self,
        headlines: list[str] = None,
        kol_mentions: list[dict] = None,
        market_data: dict = None,
        spike_event: dict = None,
    ) -> dict:
        """
        Full LLM analysis of current market conditions.

        Args:
            headlines: recent news headlines
            kol_mentions: KOL tracker results
            market_data: BTC price, FnG, TVL etc
            spike_event: price spike event (if triggered by reactor)

        Returns:
            Signal dict with direction, confidence, reasoning
        """
        now = time.time()
        cache_key = f"{len(headlines or [])}_{len(kol_mentions or [])}"
        if now - self._cache_ts < self._CACHE_TTL and self._cache.get("_key") == cache_key:
            return self._cache

        # Build context for Claude
        context_parts = []

        if spike_event:
            context_parts.append(
                f"ALERT: {spike_event['symbol']} just moved {spike_event['change_pct']:+.1%} "
                f"in {spike_event.get('window_sec', 300)//60} minutes "
                f"(${spike_event.get('from_price', 0):,.0f} → ${spike_event.get('price', 0):,.0f})"
            )

        if market_data:
            md = market_data
            context_parts.append(
                f"Market: BTC ${md.get('btc_price', 'N/A'):,.0f} ({md.get('btc_24h', 0):+.1f}% 24h), "
                f"Fear & Greed: {md.get('fng_value', 'N/A')} ({md.get('fng_classification', 'N/A')}), "
                f"DeFi TVL week change: {md.get('tvl_week_chg', 'N/A')}%"
            )

        if kol_mentions:
            kol_lines = []
            for m in kol_mentions[:10]:
                kol_lines.append(f"- [{m.get('kol', '?')}] {m.get('title', '')[:120]}")
            context_parts.append("Key Opinion Leader mentions:\n" + "\n".join(kol_lines))

        if headlines:
            hl_text = "\n".join(f"- {h[:120]}" for h in headlines[:20])
            context_parts.append(f"Recent crypto news headlines:\n{hl_text}")

        if not context_parts:
            return {"signal": "neutral", "confidence": 0, "reasoning": "No data available"}

        # Unanimity detection: if headlines are too one-sided, flag it
        if headlines:
            bull_kw = ["surge", "rally", "bull", "soar", "breakout", "ath", "record", "buy"]
            bear_kw = ["crash", "plunge", "dump", "bear", "fear", "sell", "ban", "fraud"]
            bull_count = sum(1 for h in headlines for k in bull_kw if k in h.lower())
            bear_count = sum(1 for h in headlines for k in bear_kw if k in h.lower())
            total_sentiment = bull_count + bear_count
            if total_sentiment > 0:
                unanimity = abs(bull_count - bear_count) / total_sentiment
                dominant = "bullish" if bull_count > bear_count else "bearish"
                context_parts.append(
                    f"SENTIMENT UNANIMITY WARNING: {unanimity:.0%} of sentiment keywords are {dominant}. "
                    f"({bull_count} bullish vs {bear_count} bearish keywords). "
                    f"High unanimity (>70%) historically signals a contrarian opportunity."
                )

        # Add structural data if available (MVRV, power law, cycle position)
        if market_data:
            structural = []
            if market_data.get("mvrv"):
                structural.append(f"MVRV ratio: {market_data['mvrv']:.2f} (>3.5=cycle top, <1=cycle bottom)")
            if market_data.get("power_law_ratio"):
                structural.append(f"Power Law ratio: {market_data['power_law_ratio']:.2f}x fair value")
            if market_data.get("halving_phase"):
                structural.append(f"Halving cycle: {market_data['halving_phase']} (position {market_data.get('halving_position', 0):.2f})")
            if market_data.get("futures_funding"):
                structural.append(f"Funding rate: {market_data['futures_funding']:.6f}")
            if market_data.get("futures_ls_ratio"):
                structural.append(f"Retail Long/Short: {market_data['futures_ls_ratio']:.2f}")
            if structural:
                context_parts.append("Structural/on-chain data:\n" + "\n".join(f"- {s}" for s in structural))

        context = "\n\n".join(context_parts)

        prompt = f"""You are an elite contrarian crypto trader, NOT a news summarizer.

Your edge: you think OPPOSITE to the crowd at extremes. When everyone is euphoric, you see risk. When everyone is panicking, you see opportunity. You've survived 3 bear markets by being early, not by following the herd.

{context}

WHEN TO BE CONTRARIAN (only at extremes, NOT always):
1. Fear & Greed > 80 → MUST say "sell" or "hold". Euphoria = top. No exceptions.
2. Fear & Greed 70-80 → be cautious, reduce confidence, prefer "hold" over "buy".
3. Fear & Greed 30-70 → NORMAL ZONE. Follow the trend. If news and structure are bullish, say "buy". Don't overthink.
4. Fear & Greed 20-30 → be optimistic, look for buy opportunities despite scary news.
5. Fear & Greed < 20 → MUST say "buy" or "strong_buy". Maximum panic = maximum opportunity. No exceptions.
6. If >80% of sentiment is one-sided AND FnG is extreme (>75 or <25) → strong contrarian signal.
7. If sentiment is 50-70% one-sided → this is NORMAL market, follow the direction.

KEY: Only be contrarian at EXTREMES. In the middle zone (FnG 30-70), follow the trend like a normal trader.

STRUCTURAL CONTEXT (these override news sentiment):
- MVRV > 3.0 = historically ALWAYS preceded a major crash. Do not be long.
- MVRV < 1.0 = historically ALWAYS preceded a major rally. Do not be short.
- Pi Cycle Top triggered = cycle top confirmed. Sell everything.
- Funding rate deeply negative = short squeeze imminent (bullish).
- Retail heavily long (L/S > 2.0) = dumb money is wrong (bearish).

Give TWO assessments:
1. What the CROWD thinks (from news sentiment)
2. What a CONTRARIAN should do (your actual recommendation)

Respond with ONLY this JSON:
{{
    "crowd_sentiment": "bullish" or "bearish" or "neutral",
    "unanimity_pct": 0 to 100,
    "signal": "long" or "short" or "neutral",
    "confidence": 0.0 to 1.0,
    "reasoning": "one paragraph: what crowd thinks vs what contrarian does and why",
    "key_factors": ["most important structural factor", "contrarian insight"],
    "time_horizon": "immediate" or "short_term" or "medium_term",
    "action": "strong_buy" or "buy" or "hold" or "reduce" or "sell",
    "contrarian_flag": true if your signal opposes the crowd
}}"""

        # Inject reflective memory lessons into prompt
        try:
            from llm_reflective_memory import ReflectiveMemory, inject_memory_into_prompt
            memory = ReflectiveMemory()
            prompt = inject_memory_into_prompt(prompt, memory)
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Reflective memory injection failed: {e}")

        raw = self._call_claude(prompt)
        if not raw:
            return {"signal": "neutral", "confidence": 0, "reasoning": "LLM unavailable"}

        try:
            # Extract JSON from response
            import re
            match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw, re.DOTALL)
            if match:
                result = json.loads(match.group())
                result["model"] = self.model
                result["timestamp"] = datetime.now(timezone.utc).isoformat()

                logger.info(
                    f"LLM Signal: {result['signal']} (confidence={result['confidence']:.0%}) "
                    f"action={result.get('action', '?')} | {result['reasoning'][:100]}"
                )

                result["_key"] = cache_key
                self._cache = result
                self._cache_ts = now
                return result
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse LLM response: {e}\nRaw: {raw[:200]}")

        return {"signal": "neutral", "confidence": 0, "reasoning": f"Parse error: {raw[:100]}"}

    def analyze_spike(self, spike_event: dict) -> dict:
        """
        Quick analysis specifically for price spike events.
        Optimized for speed — uses shorter prompt.
        """
        prompt = f"""A crypto price spike just occurred:
{spike_event['symbol']} moved {spike_event['change_pct']:+.1%} in {spike_event.get('window_sec', 300)//60} minutes.
Price: ${spike_event.get('from_price', 0):,.0f} → ${spike_event.get('price', 0):,.0f}

Based on this price action alone, should a trend follower:
1. Buy into the momentum (if pump)?
2. Buy the dip (if dump)?
3. Wait for confirmation?

Respond with ONLY this JSON:
{{
    "signal": "long" or "short" or "neutral",
    "confidence": 0.0 to 1.0,
    "action": "buy_momentum" or "buy_dip" or "wait" or "sell",
    "reasoning": "one sentence"
}}"""

        raw = self._call_claude(prompt, max_tokens=200)
        if not raw:
            return {"signal": "neutral", "confidence": 0, "action": "wait", "reasoning": "LLM unavailable"}

        try:
            import re
            match = re.search(r'\{[^}]+\}', raw)
            if match:
                return json.loads(match.group())
        except Exception:
            pass

        return {"signal": "neutral", "confidence": 0, "action": "wait", "reasoning": "parse error"}

    def daily_briefing(self, all_data: dict) -> str:
        """Generate a daily market briefing for Telegram."""
        prompt = f"""You are a crypto market analyst writing a daily briefing for a trader.

Data:
- BTC: ${all_data.get('btc_price', 'N/A')}
- Fear & Greed: {all_data.get('fng_value', 'N/A')} ({all_data.get('fng_classification', 'N/A')})
- Combined sentiment score: {all_data.get('combined_score', 'N/A')}
- KOL activity: {all_data.get('kol_mentions', 0)} mentions, score {all_data.get('kol_score', 0):+.2f}
- News sentiment: {all_data.get('keyword_sentiment', 'N/A')}

Write a 3-4 sentence briefing covering:
1. Current market state
2. Key risk/opportunity
3. Recommended stance (aggressive/neutral/defensive)

Keep it concise and actionable. No disclaimers."""

        raw = self._call_claude(prompt, max_tokens=300)
        return raw or "Briefing unavailable."


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    engine = LLMSignalEngine()

    # Test with sample data
    signal = engine.analyze(
        headlines=[
            "Bitcoin holds near $75,000 as short-term holders look for profit",
            "BlackRock pulls $505M into Bitcoin ETF in 48H",
            "Elon Musk Posts About Bitcoin For First Time In Months",
            "Trump's Crypto Agenda Is Struggling",
            "Federal Reserve holds rates steady, signals caution",
        ],
        market_data={
            "btc_price": 75800,
            "btc_24h": -0.3,
            "fng_value": 21,
            "fng_classification": "Extreme Fear",
            "tvl_week_chg": 3.2,
        },
    )

    print(f"\n{'='*50}")
    print(f"  Signal: {signal['signal'].upper()}")
    print(f"  Confidence: {signal.get('confidence', 0):.0%}")
    print(f"  Action: {signal.get('action', '?')}")
    print(f"  Time horizon: {signal.get('time_horizon', '?')}")
    print(f"{'='*50}")
    print(f"  Reasoning: {signal.get('reasoning', 'N/A')}")
    print(f"  Key factors: {signal.get('key_factors', [])}")
