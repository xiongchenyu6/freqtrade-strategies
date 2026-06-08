"""Nautilus Actor: the single-stack signal layer.

Subscribes to minute bars and emits Telegram spike (PUMP/DUMP) + accumulation-dip
(FLASH/FAST) alerts — replacing the retired standalone ``event_reactor.py`` /
``event_dca_bot.py`` daemons. Detection lives in ``signal_detect.py`` (pure, unit-tested);
this actor only wires Nautilus bar closes into the detectors and the ``TelegramNotifier``
sink, so it stays thin and trivial to reason about.

Add it to a TradingNode subscribed to REAL (mainnet) public market data — spike/dip
signals must reflect live prices even while execution runs on testnet.
"""

from __future__ import annotations

from nautilus_trader.common.actor import Actor
from nautilus_trader.model.data import Bar, BarType

from signal_detect import DipDetector, SpikeDetector
from telegram_notifier import TelegramNotifier


class SignalAlerter(Actor):
    def __init__(
        self,
        instrument_ids,
        bar_spec: str = "1-MINUTE-LAST-EXTERNAL",
        notifier: TelegramNotifier | None = None,
    ):
        super().__init__()
        # Accept instrument objects (backtest) or id strings (live, where instruments load
        # async and aren't available at construction) — normalise to "SYMBOL.VENUE" strings.
        self._iids = [str(getattr(i, "id", i)) for i in instrument_ids]
        self._bar_spec = bar_spec
        self._notifier = notifier or TelegramNotifier()
        self._spike: dict = {}
        self._dip: dict = {}

    def on_start(self):
        for iid in self._iids:
            bt = BarType.from_str(f"{iid}-{self._bar_spec}")
            self.subscribe_bars(bt)
            self._spike[iid] = SpikeDetector()
            self._dip[iid] = DipDetector()
        if self._notifier.enabled:
            syms = ", ".join(iid.split(".")[0] for iid in self._iids)
            # One-time heartbeat: confirms the live creds→Telegram path and tells the
            # operator the node is watching. Only re-fires on restart/redeploy.
            self._notifier.send(
                f"🟢 *Signal node online*\nWatching {syms} for spike + accumulation-dip alerts."
            )
        else:
            self.log.warning(
                "SignalAlerter: TelegramNotifier disabled (no creds) — detecting but not sending"
            )

    def on_bar(self, bar: Bar):
        iid = str(bar.bar_type.instrument_id)
        ts = bar.ts_event / 1e9
        price = float(bar.close)
        sym = iid.split(".")[0]

        sp = self._spike[iid].update(ts, price)
        if sp:
            self.log.info(f"spike {sym} {sp['kind']} {sp['change_pct']:+.2%}")
            self._notifier.send(self._fmt_spike(sym, sp))

        dp = self._dip[iid].update(ts, price)
        if dp:
            self.log.info(f"dip {sym} {dp['kind']} {dp['change_pct']:+.2%}")
            self._notifier.send(self._fmt_dip(sym, dp))

    # ----- formatting (mirrors the retired daemons' Telegram messages) -----
    @staticmethod
    def _fmt_spike(sym: str, e: dict) -> str:
        arrow = "📈" if e["kind"] == "PUMP" else "📉"
        mins = int(e["window_sec"] / 60)
        return (
            f"{arrow} *{e['kind']}* `{sym}`\n"
            f"Move: `{e['change_pct']:+.2%}` in {mins}m\n"
            f"Price: `${e['price']:,.2f}` (from `${e['from_price']:,.2f}`)"
        )

    @staticmethod
    def _fmt_dip(sym: str, e: dict) -> str:
        mins = int(e["window_sec"] / 60)
        return (
            f"🎯 *Accumulation dip* `{sym}` ({e['kind']})\n"
            f"Drop: `{e['change_pct']:+.2%}` in {mins}m\n"
            f"Price: `${e['price']:,.2f}` (from `${e['from_price']:,.2f}`)\n"
            f"_Nautilus accumulator handles execution._"
        )
