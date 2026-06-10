"""Reusable Actor that records true account equity (USDT + Σ balance×close) every bar, so
backtests get an honest max-drawdown — Nautilus's built-in returns stats expose Sharpe/Sortino
but NOT drawdown, and reconstructing equity from `analyzer.returns()` is wrong (proved in the
strategy-leaderboard iter11→13: it gave −60% where the true DD is −13%).

Usage:
    rec = EquityRecorder(instruments, venue, USDT)
    engine.add_actor(rec)
    engine.run()
    rec.max_drawdown(), rec.total_return(), rec.curve
"""

from __future__ import annotations

from nautilus_trader.common.actor import Actor
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.objects import Currency


class EquityRecorder(Actor):
    def __init__(self, instruments, venue, quote: Currency, bar_spec: str = "1-HOUR-LAST-EXTERNAL"):
        super().__init__()
        self._insts = list(instruments)
        self._venue = venue
        self._quote = quote
        self._bar_spec = bar_spec  # e.g. "1-HOUR-LAST-EXTERNAL" (donchian) | "1-DAY-LAST-EXTERNAL" (accumulator)
        self._bar_types = [
            BarType.from_str(f"{i.id}-{bar_spec}") for i in self._insts
        ]
        self._last: dict = {}
        self.curve: list[float] = []

    def on_start(self):
        for bt in self._bar_types:
            self.subscribe_bars(bt)

    def on_bar(self, bar: Bar):
        self._last[bar.bar_type.instrument_id] = float(bar.close)
        acct = self.portfolio.account(self._venue)
        if acct is None:
            return
        eq = float(acct.balance_total(self._quote))
        for inst in self._insts:
            px = self._last.get(inst.id)
            if px:
                bal = acct.balance_total(inst.base_currency)
                if bal:
                    eq += float(bal) * px
        self.curve.append(eq)

    # ----- metrics -----
    def total_return(self) -> float:
        return self.curve[-1] / self.curve[0] - 1 if len(self.curve) > 1 else 0.0

    def max_drawdown(self) -> float:
        if not self.curve:
            return 0.0
        peak, mdd = self.curve[0], 0.0
        for x in self.curve:
            peak = max(peak, x)
            mdd = min(mdd, x / peak - 1)
        return mdd

    def bar_type_for(self, instrument):
        return BarType.from_str(f"{instrument.id}-{self._bar_spec}")
