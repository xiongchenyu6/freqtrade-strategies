"""Pure price-move signal detection — no Nautilus, no network, fully unit-testable.

Ports the detection logic of the retired standalone daemons so it can live on the Nautilus
stack (the ``SignalAlerter`` actor feeds these bar closes; tests feed synthetic series):

  - ``SpikeDetector``  ← event_reactor.py   (|Δ| ≥ 1.5% over 5min, 10min cooldown) → PUMP/DUMP
  - ``DipDetector``    ← event_dca_bot.py    (FLASH: 1m drop >3%; FAST: 5m drop >5%) → accumulation

Both consume a stream of ``(timestamp_seconds, price)`` per symbol and return an event dict
when a threshold trips, else ``None``. Windows are evaluated against wall-clock seconds, so
they work identically on tick streams (daemon) and bar closes (Nautilus actor).
"""

from __future__ import annotations

from collections import deque


class SpikeDetector:
    """Symmetric move detector: fires when price moves >= ``threshold`` (either direction)
    versus the oldest price still inside ``window_sec``. ``cooldown_sec`` suppresses spam."""

    def __init__(self, threshold: float = 0.015, window_sec: int = 300, cooldown_sec: int = 600):
        self.threshold = threshold
        self.window_sec = window_sec
        self.cooldown_sec = cooldown_sec
        self._prices: deque = deque()  # (ts, price)
        self._last_alert: float | None = None  # None = never alerted (don't gate the first)

    def update(self, ts: float, price: float) -> dict | None:
        self._prices.append((ts, price))
        cutoff = ts - self.window_sec
        while self._prices and self._prices[0][0] < cutoff:
            self._prices.popleft()
        if len(self._prices) < 2:
            return None
        oldest = self._prices[0][1]
        change = (price - oldest) / oldest
        if abs(change) >= self.threshold:
            if self._last_alert is not None and ts - self._last_alert < self.cooldown_sec:
                return None
            self._last_alert = ts
            return {
                "kind": "PUMP" if change > 0 else "DUMP",
                "change_pct": change,
                "price": price,
                "from_price": oldest,
                "window_sec": self.window_sec,
            }
        return None


class DipDetector:
    """Downside-only detector over two windows (FLASH short / FAST long), matching
    event_dca_bot's FLASH (1m >3%) + FAST (5m >5%) accumulation triggers. FAST takes
    priority (stronger signal). ``cooldown_sec`` suppresses repeats."""

    def __init__(
        self,
        flash_pct: float = 0.03,
        flash_sec: int = 60,
        fast_pct: float = 0.05,
        fast_sec: int = 300,
        cooldown_sec: int = 600,
    ):
        self.flash_pct = flash_pct
        self.flash_sec = flash_sec
        self.fast_pct = fast_pct
        self.fast_sec = fast_sec
        self.cooldown_sec = cooldown_sec
        self._prices: deque = deque()  # (ts, price)
        self._last_alert: float | None = None  # None = never alerted (don't gate the first)

    def update(self, ts: float, price: float) -> dict | None:
        self._prices.append((ts, price))
        cutoff = ts - max(self.flash_sec, self.fast_sec)
        while self._prices and self._prices[0][0] < cutoff:
            self._prices.popleft()
        ev = self._detect(ts, price)
        if ev and (self._last_alert is None or ts - self._last_alert >= self.cooldown_sec):
            self._last_alert = ts
            return ev
        return None

    def _ref_price(self, ts: float, window: int) -> float | None:
        """Oldest price still within ``window`` seconds of ``ts`` (the deque may hold
        prices older than ``window`` because it is sized to the larger FAST window)."""
        for t, p in self._prices:
            if t >= ts - window:
                return p
        return None

    def _detect(self, ts: float, price: float) -> dict | None:
        fast_ref = self._ref_price(ts, self.fast_sec)
        if fast_ref:
            chg = (price - fast_ref) / fast_ref
            if chg <= -self.fast_pct:
                return {
                    "kind": "FAST",
                    "change_pct": chg,
                    "price": price,
                    "from_price": fast_ref,
                    "window_sec": self.fast_sec,
                }
        flash_ref = self._ref_price(ts, self.flash_sec)
        if flash_ref:
            chg = (price - flash_ref) / flash_ref
            if chg <= -self.flash_pct:
                return {
                    "kind": "FLASH",
                    "change_pct": chg,
                    "price": price,
                    "from_price": flash_ref,
                    "window_sec": self.flash_sec,
                }
        return None
