"""Backtest the best trend follower (HonestTrend15mProtections params) on REAL Binance
BTC 15m data, via the SAME event-driven port used for equities — proving one strategy
class runs both asset classes on Nautilus.

Run: nautilus_equity/.venv/bin/python nautilus_crypto/run_trend_crypto.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.test_kit.providers import TestInstrumentProvider

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "nautilus_equity"))
from crypto_data import load_bars  # noqa: E402
from honest_trend_equity import HonestTrendEquity, HonestTrendEquityConfig  # noqa: E402

PAIR_FILE = "BTC_USDT-15m"
_FNG = _HERE.parent / "data" / "fng_history.csv"


def main() -> int:
    engine = BacktestEngine(config=BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True)))
    instrument = TestInstrumentProvider.btcusdt_binance()
    venue = Venue("BINANCE")
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=[Money(100_000, USDT)],
        base_currency=None,  # multi-currency spot account
    )
    engine.add_instrument(instrument)
    bar_type = BarType.from_str(f"{instrument.id}-15-MINUTE-LAST-EXTERNAL")
    engine.add_data(load_bars(instrument, PAIR_FILE, bar_type))

    # HonestTrend15mProtections params (the best raw-profit backtest).
    strat = HonestTrendEquity(HonestTrendEquityConfig(
        instrument_id=str(instrument.id),
        bar_type=bar_type,
        ema_fast=72,
        ema_slow=144,
        adx_period=14,
        adx_threshold=18.0,
        vol_window=96,        # 1 day of 15m bars
        min_hold_bars=48,     # ~12h (orig min_hold 720 min)
        risk_frac=0.10,
        stop_loss_pct=0.0,    # no hard stop — exit on EMA cross (matches the spot philosophy)
        rth_only=False,       # crypto is 24/7
        regime_csv=str(_FNG) if _FNG.exists() else None,
        regime_threshold=80.0,
        regime_mode="block_above",  # don't enter in extreme greed (FNG>=80) — original logic
    ))
    engine.add_strategy(strat)
    engine.run()

    final = float(engine.portfolio.account(venue).balance_total(USDT))
    fills = engine.trader.generate_order_fills_report()
    bars = len(load_bars(instrument, PAIR_FILE, bar_type))
    print("=" * 60)
    print(f"  HonestTrend (15mProtections params) — REAL BTC 15m on Nautilus")
    print("=" * 60)
    print(f"  bars            : {bars}")
    print(f"  entries         : {strat.entries}")
    print(f"  pyramids        : {strat.pyramids}")
    print(f"  ema-cross exits : {strat.exits}")
    print(f"  order fills     : {len(fills)}")
    print(f"  start equity    : 100,000 USDT")
    print(f"  final equity    : {final:,.0f} USDT  ({(final/100_000 - 1)*100:+.1f}%)")
    print("=" * 60)
    engine.dispose()
    return 0 if len(fills) >= 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
