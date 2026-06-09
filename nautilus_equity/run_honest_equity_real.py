"""Stage 1+ validation runner — backtest HonestTrendEquity on REAL IB data.

Mirrors run_honest_equity.py but loads split/dividend-adjusted daily bars for
NVDA/AMD/QQQ from the ParquetDataCatalog (built by download_ib.py) instead of the
synthetic series. Runs one BacktestEngine per instrument and prints final balance,
fills, and return %.

Two EMA pairs are run per asset:
  - production 72/144 (the tuned HonestTrendEquityConfig defaults)
  - faster 20/50 (so we can SEE the strategy actually trade on ~750 daily bars,
    in case 72/144 is too slow to cross over a 3-year window)

LoggingConfig(bypass_logging=True): the Rust logger inits once per process; a second
BacktestEngine in the same process aborts otherwise (see README Stage 3 note).

Run:  nautilus_equity/.venv/bin/python nautilus_equity/run_honest_equity_real.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog import ParquetDataCatalog

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from honest_trend_equity import HonestTrendEquity, HonestTrendEquityConfig  # noqa: E402

_CATALOG = _HERE / "catalog"
_VIX_CSV = _HERE.parent / "data" / "vix_history.csv"
_START_BALANCE = 100_000

# (symbol, primary_venue) — must match what download_ib.py wrote.
_ASSETS = [
    ("NVDA", "NASDAQ"),
    ("AMD", "NASDAQ"),
    ("QQQ", "NASDAQ"),
]

# (label, ema_fast, ema_slow)
_EMA_PAIRS = [
    ("72/144 (production)", 72, 144),
    ("20/50 (fast)", 20, 50),
]


def run_one(catalog: ParquetDataCatalog, symbol: str, venue_name: str,
            ema_fast: int, ema_slow: int) -> dict:
    iid_str = f"{symbol}.{venue_name}"
    instrument = next(i for i in catalog.instruments() if str(i.id) == iid_str)
    bar_type = BarType.from_str(f"{instrument.id}-1-DAY-LAST-EXTERNAL")
    bars = catalog.bars(bar_types=[str(bar_type)])

    engine = BacktestEngine(
        config=BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True)),
    )
    venue = Venue(venue_name)
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=[Money(_START_BALANCE, USD)],
        base_currency=USD,
    )
    engine.add_instrument(instrument)
    engine.add_data(bars)

    strategy = HonestTrendEquity(
        HonestTrendEquityConfig(
            instrument_id=str(instrument.id),
            bar_type=bar_type,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            adx_period=14,
            adx_threshold=18.0,
            vol_window=20,
            min_hold_bars=1,
            stop_loss_pct=0.08,  # exchange-side protective stop at -8% from avg
            rth_only=False,  # daily bars: no intraday clock
            regime_csv=str(_VIX_CSV) if _VIX_CSV.exists() else None,
            regime_threshold=30.0,
            regime_mode="block_above",
        )
    )
    engine.add_strategy(strategy)
    engine.run()

    account = engine.portfolio.account(venue)
    final = float(account.balance_total(USD))
    fills = engine.trader.generate_order_fills_report()
    result = {
        "symbol": symbol,
        "bars": len(bars),
        "entries": strategy.entries,
        "pyramids": strategy.pyramids,
        "exits": strategy.exits,
        "stop_exits": strategy.stop_exits,
        "fills": len(fills),
        "final": final,
        "ret_pct": (final / _START_BALANCE - 1) * 100,
    }
    engine.dispose()
    return result


def main() -> int:
    if not _CATALOG.exists():
        print(f"catalog not found: {_CATALOG}", file=sys.stderr)
        return 2
    catalog = ParquetDataCatalog(str(_CATALOG))

    print("=" * 72)
    print("  HonestTrendEquity on REAL IB adjusted daily bars (NVDA/AMD/QQQ)")
    print(f"  catalog: {_CATALOG}")
    print("=" * 72)

    any_fills = False
    for label, ef, es in _EMA_PAIRS:
        print(f"\n--- EMA pair: {label} ---")
        header = (f"{'asset':<6} {'bars':>5} {'entries':>7} {'pyr':>4} "
                  f"{'exits':>6} {'stops':>6} {'fills':>6} {'final $':>14} {'ret %':>9}")
        print(header)
        print("-" * len(header))
        for symbol, venue_name in _ASSETS:
            r = run_one(catalog, symbol, venue_name, ef, es)
            any_fills = any_fills or r["fills"] > 0
            print(f"{r['symbol']:<6} {r['bars']:>5} {r['entries']:>7} "
                  f"{r['pyramids']:>4} {r['exits']:>6} {r['stop_exits']:>6} "
                  f"{r['fills']:>6} {r['final']:>14,.2f} {r['ret_pct']:>+8.2f}%")

    print("\n" + "=" * 72)
    return 0 if any_fills else 1


if __name__ == "__main__":
    raise SystemExit(main())
