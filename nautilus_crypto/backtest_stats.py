"""Re-run the DEPLOYED strategies on Nautilus and emit honest backtest stats to
`quant.nautilus_backtests` — the dashboard's Stage-9 source of truth, replacing the
misleading freqtrade `backtest_runs` aggregates (which came from now-deleted strategies).

Covers the live crypto config: Donchian breakout portfolio (ETH+BTC+SOL 1h, 168/72, 6.67%
each) over full history AND the recent out-of-sample half (the regime that justified deploying
it), plus the smart accumulator. Stats are computed the same way the strategy research did:
true max-drawdown via EquityRecorder, Sharpe/Sortino via the portfolio analyzer.

Run (prints, no DB write):   nautilus_equity/.venv/bin/python nautilus_crypto/backtest_stats.py
Load to DB (needs TIMESCALE_URL): ... backtest_stats.py --load
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, CurrencyType, OmsType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Currency, Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from accumulator import Accumulator, AccumulatorConfig
from crypto_data import load_bars
from donchian import DonchianBreakout, DonchianBreakoutConfig
from equity_recorder import EquityRecorder

VENUE = Venue("BINANCE")
START_CASH = 100_000


def _mkpair(base: str) -> CurrencyPair:
    sym = f"{base}USDT"
    return CurrencyPair(
        InstrumentId(Symbol(sym), VENUE), Symbol(sym),
        Currency(base, 8, 0, base, CurrencyType.CRYPTO), USDT, 2, 6,
        Price.from_str("0.01"), Quantity.from_str("0.000001"),
        margin_init=Decimal("0"), margin_maint=Decimal("0"),
        maker_fee=Decimal("0.001"), taker_fee=Decimal("0.001"), ts_event=0, ts_init=0,
    )


# (label, instrument-factory, feather-prefix). BTC/ETH use TestInstrumentProvider; everything
# else is built with _mkpair. The feather file is "<prefix>-<tf>" so the same entry serves the
# Donchian (1h) and Accumulator (1d) paths. Keep ASSET_BASES in lockstep with the runner's
# allowed set (only bases with both *-1h and *-1d feathers belong here).
_ASSETS = {
    "BTC": (TestInstrumentProvider.btcusdt_binance, "BTC_USDT"),
    "ETH": (TestInstrumentProvider.ethusdt_binance, "ETH_USDT"),
    "SOL": (lambda: _mkpair("SOL"), "SOL_USDT"),
    "BNB": (lambda: _mkpair("BNB"), "BNB_USDT"),
    "XRP": (lambda: _mkpair("XRP"), "XRP_USDT"),
    "ADA": (lambda: _mkpair("ADA"), "ADA_USDT"),
    "DOGE": (lambda: _mkpair("DOGE"), "DOGE_USDT"),
    "LINK": (lambda: _mkpair("LINK"), "LINK_USDT"),
}


def _bars_for(inst, pair_file, bar_type, recent_half: bool):
    bars = load_bars(inst, pair_file, bar_type)
    if recent_half and bars:
        mid = bars[len(bars) // 2].ts_event  # split at the median timestamp
        bars = [b for b in bars if b.ts_event >= mid]
    return bars


def _period(bars) -> tuple:
    if not bars:
        return (None, None)
    d = lambda b: datetime.fromtimestamp(b.ts_event / 1e9, tz=timezone.utc).date()
    return (d(bars[0]), d(bars[-1]))


def _new_engine(start_cash: int = START_CASH) -> BacktestEngine:
    eng = BacktestEngine(config=BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True)))
    eng.add_venue(venue=VENUE, oms_type=OmsType.NETTING, account_type=AccountType.CASH,
                  starting_balances=[Money(start_cash, USDT)], base_currency=None)
    return eng


def _extract_stats(engine: BacktestEngine, rec: EquityRecorder) -> dict:
    perf = engine.portfolio.analyzer.get_performance_stats_returns()
    ret = rec.total_return()
    dd = rec.max_drawdown()  # negative fraction
    calmar = (ret / abs(dd)) if dd else None

    pos = engine.trader.generate_positions_report()
    trades = int(len(pos))
    wins = losses = 0
    if trades:
        col = "realized_pnl" if "realized_pnl" in pos.columns else (
            "realized_return" if "realized_return" in pos.columns else None)
        if col:
            vals = [float(str(v).replace(",", "").split(" ")[0]) for v in pos[col]]
            wins = sum(1 for v in vals if v > 0)
            losses = sum(1 for v in vals if v <= 0)
    win_rate = round(100.0 * wins / trades, 2) if trades else None

    def _r(x, n=4):
        return round(float(x), n) if x is not None else None

    return {
        "total_trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": win_rate,
        "total_profit_pct": _r(ret * 100, 2),
        "max_drawdown_pct": _r(dd * 100, 2),
        "calmar": _r(calmar, 2),
        "sharpe": _r(perf.get("Sharpe Ratio (252 days)"), 2),
        "sortino": _r(perf.get("Sortino Ratio (252 days)"), 2),
    }


def run_donchian_portfolio(bases, *, entry_lb=168, exit_lb=72, risk_frac=0.0667,
                           recent_half=False) -> dict:
    eng = _new_engine()
    insts = []
    period = (None, None)
    for base in bases:
        factory, prefix = _ASSETS[base]
        inst = factory()
        bt = BarType.from_str(f"{inst.id}-1-HOUR-LAST-EXTERNAL")
        bars = _bars_for(inst, f"{prefix}-1h", bt, recent_half)
        eng.add_instrument(inst)
        eng.add_data(bars)
        eng.add_strategy(DonchianBreakout(DonchianBreakoutConfig(
            instrument_id=str(inst.id), bar_type=bt,
            entry_lb=entry_lb, exit_lb=exit_lb, risk_frac=risk_frac,
        )))
        insts.append(inst)
        if base == bases[0]:
            period = _period(bars)
    rec = EquityRecorder(insts, VENUE, USDT)
    eng.add_actor(rec)
    eng.run()
    stats = _extract_stats(eng, rec)
    stats["curve"] = list(rec.curve)  # honest per-bar equity series (for playground charting)
    eng.dispose()
    stats["params"] = {"entry_lb": entry_lb, "exit_lb": exit_lb, "risk_frac": risk_frac}
    stats["instruments"] = [f"{b}USDT.BINANCE" for b in bases]
    stats["period_start"], stats["period_end"] = period
    return stats


def run_accumulator(base="BTC", *, base_buy_usd=500.0, interval_bars=7, mode="smart") -> dict:
    # Large starting balance so the DCA never hits a cash wall (it invests ~$0.5M over the
    # full history; a small float would truncate accumulation and distort ROI).
    eng = _new_engine(start_cash=5_000_000)
    factory, _ = _ASSETS[base]
    inst = factory()
    bt = BarType.from_str(f"{inst.id}-1-DAY-LAST-EXTERNAL")
    bars = load_bars(inst, f"{base}_USDT-1d", bt)
    eng.add_instrument(inst)
    eng.add_data(bars)
    strat = Accumulator(AccumulatorConfig(
        instrument_id=str(inst.id), bar_type=bt,
        base_buy_usd=base_buy_usd, interval_bars=interval_bars, mode=mode,
    ))
    eng.add_strategy(strat)
    # Record true equity (cash + coin×close) per daily bar → the DCA accumulation curve.
    rec = EquityRecorder([inst], VENUE, USDT, bar_spec="1-DAY-LAST-EXTERNAL")
    eng.add_actor(rec)
    eng.run()
    # Accumulator is a never-sell DCA — trade-round-trip metrics (Sharpe/win-rate/DD) don't
    # apply; the honest headline is ROI on invested capital. total_trades = number of buys.
    roi = strat.roi()
    curve = list(rec.curve)
    eng.dispose()
    stats = {
        "total_trades": int(strat.buys),
        "wins": None, "losses": None, "win_rate_pct": None,
        "total_profit_pct": round(float(roi) * 100, 2),
        "max_drawdown_pct": None, "calmar": None, "sharpe": None, "sortino": None,
        "params": {"base_buy_usd": base_buy_usd, "interval_bars": interval_bars, "mode": mode,
                   "invested_usd": round(float(strat.invested_usd), 0),
                   "coin_qty": round(float(strat.coin_qty), 6)},
        "instruments": [f"{base}USDT.BINANCE"],
        "curve": curve,  # per-bar equity (cash + coin×close) — the DCA accumulation series
    }
    stats["period_start"], stats["period_end"] = _period(bars)
    return stats


# Rows the dashboard shows. Each entry: (asset_class, strategy, label, timeframe, env, builder).
def build_rows() -> list[dict]:
    rows = []

    def add(asset_class, strategy, label, timeframe, env, stats):
        rows.append({
            "asset_class": asset_class, "strategy": strategy, "label": label,
            "timeframe": timeframe, "environment": env, **stats,
        })

    # Deployed Donchian trend — full history + recent out-of-sample half (the deploy thesis).
    add("crypto", "DonchianBreakout", "ETH+BTC+SOL 1h portfolio (full history)", "1h",
        "backtest", run_donchian_portfolio(["ETH", "BTC", "SOL"]))
    add("crypto", "DonchianBreakout", "ETH+BTC+SOL 1h portfolio (recent OOS)", "1h",
        "backtest-validated", run_donchian_portfolio(["ETH", "BTC", "SOL"], recent_half=True))
    # Smart accumulator (deployed).
    add("crypto", "Accumulator", "BTC smart DCA (fear+dip boosted)", "1d",
        "backtest", run_accumulator("BTC"))
    return rows


def load_rows(rows: list[dict]) -> int:
    import psycopg2
    url = os.environ.get("TIMESCALE_URL")
    if not url:
        sys.exit("TIMESCALE_URL not set (run via: sops exec-env secrets.env '... --load')")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    n = 0
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO quant.nautilus_backtests
                  (asset_class, strategy, label, instruments, timeframe, period_start, period_end,
                   environment, total_trades, wins, losses, win_rate_pct, total_profit_pct,
                   max_drawdown_pct, calmar, sharpe, sortino, params, run_at)
                VALUES (%(asset_class)s, %(strategy)s, %(label)s, %(instruments)s, %(timeframe)s,
                        %(period_start)s, %(period_end)s,
                        %(environment)s, %(total_trades)s, %(wins)s, %(losses)s, %(win_rate_pct)s,
                        %(total_profit_pct)s, %(max_drawdown_pct)s, %(calmar)s, %(sharpe)s,
                        %(sortino)s, %(params)s, now())
                ON CONFLICT (strategy, label, period_start, period_end) DO UPDATE SET
                  total_trades=EXCLUDED.total_trades, wins=EXCLUDED.wins, losses=EXCLUDED.losses,
                  win_rate_pct=EXCLUDED.win_rate_pct, total_profit_pct=EXCLUDED.total_profit_pct,
                  max_drawdown_pct=EXCLUDED.max_drawdown_pct, calmar=EXCLUDED.calmar,
                  sharpe=EXCLUDED.sharpe, sortino=EXCLUDED.sortino, params=EXCLUDED.params,
                  run_at=now()
                """,
                {**r, "instruments": r["instruments"],
                 "params": __import__("json").dumps(r["params"])},
            )
            n += 1
    conn.close()
    return n


def main() -> int:
    rows = build_rows()
    print("=" * 78)
    print(f"  {'strategy / label':<46} {'ret%':>7} {'DD%':>7} {'Shrp':>5} {'WR%':>5} {'N':>4}")
    print("-" * 78)
    def _f(v):
        return "—" if v is None else str(v)
    for r in rows:
        print(f"  {r['label']:<46} {_f(r['total_profit_pct']):>7} {_f(r['max_drawdown_pct']):>7} "
              f"{_f(r['sharpe']):>5} {_f(r['win_rate_pct']):>5} {r['total_trades']:>4}")
    print("=" * 78)
    if "--load" in sys.argv:
        n = load_rows(rows)
        print(f"  loaded {n} rows → quant.nautilus_backtests")
    else:
        print("  (dry run — pass --load with TIMESCALE_URL to write to DB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
