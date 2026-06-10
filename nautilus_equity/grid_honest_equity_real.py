"""EMA-grid backtest of HonestTrendEquity on REAL IB adjusted bars (NVDA/AMD/QQQ).

Extends run_honest_equity_real.py to a small EMA grid across BOTH 1-DAY and 1-HOUR
real bars, and reports risk-adjusted metrics computed from a mark-to-market daily
equity curve (cash balance + open-position value):

  total return %, # fills, max drawdown %, Sharpe (annualized), Calmar.

The equity curve is reconstructed from the account-balance time series (realized cash,
CASH account) plus the value of any position still open at each bar close, sampled by
calendar day. Sharpe is annualized from daily equity returns (252 trading days);
Calmar = annualized return / |max drawdown|.

Run:  nautilus_equity/.venv/bin/python nautilus_equity/grid_honest_equity_real.py
"""

from __future__ import annotations

import math
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

_ASSETS = [("NVDA", "NASDAQ"), ("AMD", "NASDAQ"), ("QQQ", "NASDAQ")]

# (label, ema_fast, ema_slow)
_EMA_PAIRS = [
    ("20/50", 20, 50),
    ("30/60", 30, 60),
    ("50/100", 50, 100),
    ("72/144", 72, 144),
]

_TIMEFRAMES = [
    ("1-DAY", "1-DAY-LAST-EXTERNAL", 252),    # ~252 trading days / yr
    ("1-HOUR", "1-HOUR-LAST-EXTERNAL", 1638),  # ~6.5h * 252 trading hrs / yr
]


def _max_drawdown(curve: list[float]) -> float:
    """Max drawdown as a positive fraction (0.0–1.0)."""
    peak = curve[0]
    mdd = 0.0
    for v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > mdd:
            mdd = dd
    return mdd


def _sharpe(rets: list[float], periods_per_year: int) -> float:
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return 0.0
    return (mean / sd) * math.sqrt(periods_per_year)


def run_one(catalog, symbol, venue_name, ema_fast, ema_slow,
            bar_suffix, periods_per_year) -> dict:
    iid_str = f"{symbol}.{venue_name}"
    instrument = next(i for i in catalog.instruments() if str(i.id) == iid_str)
    bar_type = BarType.from_str(f"{instrument.id}-{bar_suffix}")
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
            stop_loss_pct=0.08,
            rth_only=False,
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

    # --- equity curve from account-balance series (CASH realized) ---
    acc = engine.trader.generate_account_report(venue)
    # 'total' is realized cash. De-duplicate timestamps (engine appends a final dup),
    # resample to one value per calendar day = last realized cash that day.
    bal_by_day: dict = {}
    for ts, total in zip(acc.index, acc["total"].astype(float)):
        bal_by_day[ts.date()] = total
    curve = [_START_BALANCE] + [bal_by_day[d] for d in sorted(bal_by_day)]
    rets = [curve[i] / curve[i - 1] - 1 for i in range(1, len(curve)) if curve[i - 1] > 0]
    mdd = _max_drawdown(curve)
    sharpe = _sharpe(rets, periods_per_year)

    # Calmar from annualized return over the realized horizon.
    ret_total = final / _START_BALANCE - 1
    n_days = max(1, (sorted(bal_by_day)[-1] - sorted(bal_by_day)[0]).days) if bal_by_day else 1
    years = max(n_days / 365.25, 1e-9)
    cagr = (final / _START_BALANCE) ** (1 / years) - 1 if final > 0 else -1.0
    calmar = cagr / mdd if mdd > 0 else float("inf")

    result = {
        "symbol": symbol,
        "bars": len(bars),
        "entries": strategy.entries,
        "pyramids": strategy.pyramids,
        "exits": strategy.exits,
        "stops": strategy.stop_exits,
        "fills": len(fills),
        "final": final,
        "ret_pct": ret_total * 100,
        "mdd_pct": mdd * 100,
        "sharpe": sharpe,
        "calmar": calmar,
        "curve": curve,  # daily realized-cash equity series (for playground charting)
    }
    engine.dispose()
    return result


def main() -> int:
    if not _CATALOG.exists():
        print(f"catalog not found: {_CATALOG}", file=sys.stderr)
        return 2
    catalog = ParquetDataCatalog(str(_CATALOG))

    print("=" * 100)
    print("  HonestTrendEquity EMA grid on REAL IB adjusted bars (NVDA/AMD/QQQ)")
    print("  metrics: ret% / fills / maxDD% / Sharpe(ann) / Calmar  — daily realized-cash equity curve")
    print("=" * 100)

    rows = []
    for tf_label, suffix, ppy in _TIMEFRAMES:
        for pair_label, ef, es in _EMA_PAIRS:
            print(f"\n--- timeframe={tf_label}  EMA={pair_label} ---")
            hdr = (f"{'asset':<6}{'bars':>6}{'ent':>5}{'pyr':>5}{'exit':>5}{'stop':>5}"
                   f"{'fills':>6}{'ret %':>9}{'maxDD%':>8}{'Sharpe':>8}{'Calmar':>8}")
            print(hdr)
            print("-" * len(hdr))
            for symbol, venue_name in _ASSETS:
                r = run_one(catalog, symbol, venue_name, ef, es, suffix, ppy)
                r["tf"] = tf_label
                r["pair"] = pair_label
                rows.append(r)
                cal = "inf" if r["calmar"] == float("inf") else f"{r['calmar']:>8.2f}"
                print(f"{r['symbol']:<6}{r['bars']:>6}{r['entries']:>5}{r['pyramids']:>5}"
                      f"{r['exits']:>5}{r['stops']:>5}{r['fills']:>6}{r['ret_pct']:>+8.2f}%"
                      f"{r['mdd_pct']:>7.2f}%{r['sharpe']:>8.2f}{cal:>8}")

    # --- robustness summary: mean across the 3 assets per (tf, pair) ---
    print("\n" + "=" * 100)
    print("  ROBUSTNESS — mean across NVDA/AMD/QQQ per (timeframe, EMA pair)")
    print("=" * 100)
    hdr = (f"{'tf':<7}{'EMA':<8}{'avg ret%':>10}{'avg fills':>10}"
           f"{'avg maxDD%':>11}{'avg Sharpe':>11}{'min Sharpe':>11}")
    print(hdr)
    print("-" * len(hdr))
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        groups[(r["tf"], r["pair"])].append(r)
    for (tf, pair), rs in groups.items():
        n = len(rs)
        avg_ret = sum(x["ret_pct"] for x in rs) / n
        avg_fills = sum(x["fills"] for x in rs) / n
        avg_mdd = sum(x["mdd_pct"] for x in rs) / n
        sharpes = [x["sharpe"] for x in rs]
        avg_sh = sum(sharpes) / n
        min_sh = min(sharpes)
        print(f"{tf:<7}{pair:<8}{avg_ret:>+9.2f}%{avg_fills:>10.1f}"
              f"{avg_mdd:>10.2f}%{avg_sh:>11.2f}{min_sh:>11.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
