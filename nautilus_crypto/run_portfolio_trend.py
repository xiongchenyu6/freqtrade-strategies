"""Validated winner: multi-asset 1h trend portfolio on Nautilus, real Binance data, with an
honest equity-curve max-drawdown (via EquityRecorder).

Result (ETH+BTC @10% each, full 1h history): +211% / Sharpe 2.41 / maxDD -13.2%.
See ../STRATEGY_LEADERBOARD.md for the full exploration that led here.

Run: nautilus_equity/.venv/bin/python nautilus_crypto/run_portfolio_trend.py
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "nautilus_equity"))

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, CurrencyType, OmsType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Currency, Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from crypto_data import load_bars
from equity_recorder import EquityRecorder
from honest_trend_equity import HonestTrendEquity, HonestTrendEquityConfig

# Portfolio: (instrument, feather-file). ETH+BTC is the validated best (Sharpe). Add
# ("SOL", "SOL_USDT-1h") / ("BNB", ...) via mkpair to widen (more return, Sharpe plateaus).
RISK_PER_ASSET = 0.10


def mkpair(base: str) -> CurrencyPair:
    sym = f"{base}USDT"
    return CurrencyPair(
        InstrumentId(Symbol(sym), Venue("BINANCE")), Symbol(sym),
        Currency(base, 8, 0, base, CurrencyType.CRYPTO), USDT, 2, 6,
        Price.from_str("0.01"), Quantity.from_str("0.000001"),
        margin_init=Decimal("0"), margin_maint=Decimal("0"),
        maker_fee=Decimal("0.001"), taker_fee=Decimal("0.001"), ts_event=0, ts_init=0,
    )


def main() -> int:
    assets = [
        (TestInstrumentProvider.ethusdt_binance(), "ETH_USDT-1h"),
        (TestInstrumentProvider.btcusdt_binance(), "BTC_USDT-1h"),
    ]
    engine = BacktestEngine(config=BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True)))
    venue = Venue("BINANCE")
    engine.add_venue(venue=venue, oms_type=OmsType.NETTING, account_type=AccountType.CASH,
                     starting_balances=[Money(100_000, USDT)], base_currency=None)
    insts = []
    for inst, pf in assets:
        bt = BarType.from_str(f"{inst.id}-1-HOUR-LAST-EXTERNAL")
        engine.add_instrument(inst)
        engine.add_data(load_bars(inst, pf, bt))
        engine.add_strategy(HonestTrendEquity(HonestTrendEquityConfig(
            instrument_id=str(inst.id), bar_type=bt, ema_fast=72, ema_slow=144,
            adx_period=14, adx_threshold=25.0, vol_window=24, min_hold_bars=12,
            risk_frac=RISK_PER_ASSET, stop_loss_pct=0.0, rth_only=False,
            regime_csv="data/fng_history.csv", regime_threshold=80.0, regime_mode="block_above",
        )))
        insts.append(inst)

    rec = EquityRecorder(insts, venue, USDT)
    engine.add_actor(rec)
    engine.run()

    sharpe = engine.portfolio.analyzer.get_performance_stats_returns().get("Sharpe Ratio (252 days)")
    print("=" * 60)
    print("  Multi-asset 1h trend portfolio (validated winner)")
    print("=" * 60)
    print(f"  assets          : {', '.join(str(i.id) for i in insts)}  @ {RISK_PER_ASSET:.0%} each")
    print(f"  total return    : {rec.total_return()*100:+.1f}%")
    print(f"  Sharpe (252d)   : {sharpe:.2f}")
    print(f"  TRUE max DD     : {rec.max_drawdown()*100:.1f}%")
    print("=" * 60)
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
