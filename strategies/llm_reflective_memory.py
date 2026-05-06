"""
LLM Reflective Memory — Learn from Past Trades

After each trade completes, the LLM reviews:
  - What was the sentiment when we entered?
  - What happened during the trade?
  - Why did we win or lose?
  - What lesson should we remember?

These lessons are stored and injected into future LLM analysis prompts,
creating a feedback loop where the system gets smarter over time.

Inspired by CryptoTrade (EMNLP 2024) reflective reasoning approach.

Usage:
    memory = ReflectiveMemory()

    # After a trade completes
    memory.reflect_on_trade(trade_data)

    # When generating new LLM signal
    lessons = memory.get_lessons(n=5)
    # → inject into LLM prompt
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("reflective_memory")

ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MEMORY_DIR = Path(__file__).parent.parent / "sentiment_data" / "trade_memory"


class ReflectiveMemory:
    """LLM-powered trade reflection and memory system."""

    def __init__(self, max_lessons: int = 20):
        self.max_lessons = max_lessons
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self.lessons_file = MEMORY_DIR / "lessons.json"
        self.trades_file = MEMORY_DIR / "reflected_trades.json"

    def _load_lessons(self) -> list[dict]:
        try:
            if self.lessons_file.exists():
                with open(self.lessons_file) as f:
                    return json.loads(f.read())
        except (json.JSONDecodeError, IOError):
            pass
        return []

    def _save_lessons(self, lessons: list[dict]):
        with open(self.lessons_file, "w") as f:
            json.dump(lessons[-self.max_lessons:], f, indent=2)

    def _load_reflected(self) -> set:
        try:
            if self.trades_file.exists():
                with open(self.trades_file) as f:
                    return set(json.loads(f.read()))
        except (json.JSONDecodeError, IOError):
            pass
        return set()

    def _save_reflected(self, trade_ids: set):
        with open(self.trades_file, "w") as f:
            json.dump(list(trade_ids), f)

    def _call_claude(self, prompt: str) -> Optional[str]:
        if not ANTHROPIC_API_KEY:
            return None
        try:
            resp = requests.post(
                f"{ANTHROPIC_BASE_URL}/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-5-20241022",
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]
        except Exception as e:
            logger.warning(f"Claude reflection failed: {e}")
            return None

    def reflect_on_trade(self, trade: dict) -> Optional[dict]:
        """
        Ask Claude to reflect on a completed trade and extract a lesson.

        trade dict should contain:
          pair, entry_date, exit_date, profit_pct, entry_tag,
          exit_reason, duration_days, fng_at_entry, llm_signal_at_entry,
          regime_at_entry, btc_price_entry, btc_price_exit
        """
        # Check if already reflected
        trade_id = f"{trade.get('pair', '')}_{trade.get('entry_date', '')}"
        reflected = self._load_reflected()
        if trade_id in reflected:
            return None

        profit = trade.get("profit_pct", 0)
        outcome = "profitable" if profit > 0 else "loss"

        prompt = f"""You are reviewing a completed crypto trade to extract a lesson for future trading.

Trade details:
- Pair: {trade.get('pair', '?')}
- Entry: {trade.get('entry_date', '?')} at ${trade.get('btc_price_entry', '?')}
- Exit: {trade.get('exit_date', '?')} at ${trade.get('btc_price_exit', '?')}
- Result: {profit:+.1f}% ({outcome})
- Duration: {trade.get('duration_days', '?')} days
- Entry signal: {trade.get('entry_tag', '?')}
- Exit reason: {trade.get('exit_reason', '?')}
- Fear & Greed at entry: {trade.get('fng_at_entry', '?')}
- LLM signal at entry: {trade.get('llm_signal_at_entry', '?')}
- Regime at entry: {trade.get('regime_at_entry', '?')}

Analyze this trade and extract ONE concise lesson (max 2 sentences) that would help avoid this mistake or repeat this success in the future.

Format: {{"lesson": "...", "category": "entry" or "exit" or "sizing" or "timing", "applies_when": "condition when this lesson is relevant"}}"""

        raw = self._call_claude(prompt)
        if not raw:
            return None

        try:
            import re
            match = re.search(r'\{[^}]+\}', raw, re.DOTALL)
            if match:
                lesson = json.loads(match.group())
                lesson["trade_id"] = trade_id
                lesson["profit_pct"] = profit
                lesson["timestamp"] = datetime.now(timezone.utc).isoformat()

                # Save
                lessons = self._load_lessons()
                lessons.append(lesson)
                self._save_lessons(lessons)

                reflected.add(trade_id)
                self._save_reflected(reflected)

                logger.info(
                    f"Reflected on {trade.get('pair')} ({profit:+.1f}%): "
                    f"{lesson.get('lesson', '')[:80]}"
                )
                return lesson
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse reflection: {e}")

        return None

    def get_lessons(self, n: int = 5, category: str = None) -> list[dict]:
        """Get the N most recent lessons, optionally filtered by category."""
        lessons = self._load_lessons()
        if category:
            lessons = [l for l in lessons if l.get("category") == category]
        return lessons[-n:]

    def get_lessons_prompt(self, n: int = 5) -> str:
        """
        Format lessons as a string to inject into LLM prompts.
        This is the key integration point — future analyses benefit
        from past trade reflections.
        """
        lessons = self.get_lessons(n)
        if not lessons:
            return ""

        lines = ["LESSONS FROM PAST TRADES (do NOT repeat past mistakes):"]
        for l in lessons:
            profit_icon = "✅" if l.get("profit_pct", 0) > 0 else "❌"
            lines.append(
                f"  {profit_icon} [{l.get('category', '?')}] "
                f"{l.get('lesson', '?')} "
                f"(applies when: {l.get('applies_when', '?')})"
            )
        return "\n".join(lines)

    def batch_reflect(self, trades: list[dict]) -> int:
        """Reflect on multiple trades. Returns count of new lessons."""
        count = 0
        for trade in trades:
            result = self.reflect_on_trade(trade)
            if result:
                count += 1
                time.sleep(1)  # rate limit
        return count


# Integration with existing LLM signal engine
def inject_memory_into_prompt(original_prompt: str, memory: ReflectiveMemory) -> str:
    """Inject past trade lessons into an LLM analysis prompt."""
    lessons_text = memory.get_lessons_prompt(n=5)
    if not lessons_text:
        return original_prompt

    # Insert lessons before the JSON response instruction
    if "Respond with ONLY" in original_prompt:
        parts = original_prompt.split("Respond with ONLY")
        return parts[0] + "\n\n" + lessons_text + "\n\nRespond with ONLY" + parts[1]

    return original_prompt + "\n\n" + lessons_text


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    memory = ReflectiveMemory()

    # Test with sample trades
    sample_trades = [
        {
            "pair": "BTC/USDT",
            "entry_date": "2024-10-15",
            "exit_date": "2024-12-20",
            "profit_pct": 45.2,
            "entry_tag": "buy_tf_up",
            "exit_reason": "tf_exit_greed",
            "duration_days": 66,
            "fng_at_entry": 28,
            "llm_signal_at_entry": "long",
            "regime_at_entry": "buy",
            "btc_price_entry": 65000,
            "btc_price_exit": 94000,
        },
        {
            "pair": "ETH/USDT",
            "entry_date": "2025-03-10",
            "exit_date": "2025-04-05",
            "profit_pct": -12.3,
            "entry_tag": "neutral_tf_up",
            "exit_reason": "ema_cross_exit",
            "duration_days": 26,
            "fng_at_entry": 55,
            "llm_signal_at_entry": "long",
            "regime_at_entry": "neutral",
            "btc_price_entry": 85000,
            "btc_price_exit": 74000,
        },
    ]

    print("=== Reflecting on sample trades ===\n")
    count = memory.batch_reflect(sample_trades)
    print(f"\n{count} new lessons learned\n")

    print("=== Lessons for future prompts ===\n")
    print(memory.get_lessons_prompt())
