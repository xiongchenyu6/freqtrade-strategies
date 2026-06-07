"""Backtest the fear-driven accumulator on REAL Binance BTC daily history and compare
'smart' (fear+dip boosted DCA) vs 'naive' (plain fixed-interval DCA).

Run:  nautilus_crypto/.venv-link/python ... — or:
      ../nautilus_equity/.venv/bin/python nautilus_crypto/run_accumulation.py
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from accumulator import Accumulator, AccumulatorConfig  # noqa: E402
from crypto_data import load_bars  # noqa: E402

PAIR_FILE = "BTC_USDT-1d"


def run(mode: str):
    # bypass_logging: Rust logger inits once/process; both engines in one run need this.
    engine = BacktestEngine(config=BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True)))
    instrument = TestInstrumentProvider.btcusdt_binance()
    venue = Venue("BINANCE")
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=[Money(5_000_000, USDT)],
        base_currency=None,  # multi-currency cash account (holds USDT + BTC) for spot
    )
    engine.add_instrument(instrument)
    bar_type = BarType.from_str(f"{instrument.id}-1-DAY-LAST-EXTERNAL")
    engine.add_data(load_bars(instrument, PAIR_FILE, bar_type))

    strat = Accumulator(AccumulatorConfig(
        instrument_id=str(instrument.id),
        bar_type=bar_type,
        base_buy_usd=500.0,
        interval_bars=7,  # ~weekly
        mode=mode,
    ))
    engine.add_strategy(strat)
    engine.run()
    engine.dispose()
    return strat


def main() -> int:
    smart = run("smart")
    naive = run("naive")

    def block(name, s):
        print(f"  {name}")
        print(f"    buys            : {s.buys}  (fear {s.fear_buys}, dip {s.dip_buys})")
        print(f"    invested        : ${s.invested_usd:,.0f}")
        print(f"    BTC accumulated : {s.coin_qty:.4f}")
        print(f"    avg cost / BTC  : ${s.avg_cost():,.0f}")
        print(f"    final value     : ${s.final_value():,.0f}  (last px ${s.last_price:,.0f})")
        print(f"    ROI on invested : {s.roi()*100:+.1f}%")

    print("=" * 60)
    print(f"  Accumulation backtest — {PAIR_FILE}, real Binance data")
    print("=" * 60)
    block("SMART (fear + dip boosted DCA)", smart)
    print("-" * 60)
    block("NAIVE (plain fixed-interval DCA)", naive)
    print("-" * 60)
    if naive.avg_cost() > 0:
        edge = (1 - smart.avg_cost() / naive.avg_cost()) * 100
        print(f"  Smart avg-cost advantage : {edge:+.2f}%  (lower cost basis = better)")
        print(f"  Smart ROI − Naive ROI    : {(smart.roi()-naive.roi())*100:+.2f} pts")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
