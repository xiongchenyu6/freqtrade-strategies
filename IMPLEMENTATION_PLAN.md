# Migration Plan — Add US Equities via NautilusTrader

**Decision (2026-06-07):** Adopt NautilusTrader as the engine for **active US-equity
trend trading**. Crypto reverts to **pure accumulation** (keep the existing Event/Smart
DCA daemon — do NOT port it). The HonestTrend trend logic, which Kelly flags as
negative-edge on crypto, moves to trending equity markets (semiconductors) where it
has a better home. Unify everything at the TimescaleDB + Svelte dashboard layer.

**Reuse unchanged:** `strategies/kelly_sizer.py` (pure Python), TimescaleDB schema
`quant`, the Svelte dashboard. **Rewrite:** strategy indicators (vectorized pandas →
event-driven incremental) and entry/exit logic. **Leave alone:** crypto DCA daemon.

---

## Stage 1: Spike — prove the engine + data link
**Goal:** A NautilusTrader BacktestEngine runs one trivial EMA-cross on one semiconductor
ticker (e.g. NVDA), reading bars downloaded from IB into a ParquetDataCatalog.
**Success Criteria:** Backtest completes deterministically; trades + equity curve printed.
**Tests:** Smoke test that the catalog has bars and `engine.run()` produces ≥1 trade.
**Status:** In Progress — synthetic-data spike DONE (`nautilus_equity/backtest_spike.py`
runs: 400 bars, EMA cross, kelly_stake reused, +2.03% on synthetic NVDA, 12 fills).
nautilus-trader 1.227.0 + ib extra installed in isolated `nautilus_equity/.venv`.
REMAINING: run `download_ib.py` against a live IB Gateway/TWS to replace synthetic data
with real adjusted bars (blocked on IB Gateway running — ports currently closed).

## Stage 2: Port one HonestTrend strategy to event-driven
**Goal:** Reimplement the HonestTrend trend logic as a Nautilus `Strategy` with
incremental indicators. Wire `kelly_stake()` into the sizing path (reuse module as-is).
**Success Criteria:** Same-window backtest profit is in the same ballpark as the
freqtrade backtest for the equivalent logic on equity data (not identical — different
asset — but directionally sane).
**Tests:** Unit tests for the incremental indicator(s) vs a pandas reference;
`test_kelly_sizer.py` still green (no changes expected there).
**Status:** In Progress — port DONE (`nautilus_equity/honest_trend_equity.py`). Runs on
synthetic data (`run_honest_equity.py`): 4 entries / 6 pyramids / 4 exits / 14 fills,
exercising every path. Migration-cost finding: only ADX (Wilder-smoothed DX), volume-SMA,
crossover-edge, min-hold and pyramid bookkeeping needed hand-porting; EMA + DirectionalMovement
(+DI/-DI) and kelly_sizer carried over for free. FNG filter is crypto-only → stubbed,
needs a VIX/put-call equity replacement. REMAINING: feed real KellyStats; validate
indicator values vs talib on real bars (needs catalog/IB).

## Stage 3: Equity realities — sessions, gaps, brackets, corporate actions
**Goal:** Restrict decisions to RTH; replace soft stops with exchange-side bracket
orders (gap-safe); confirm IB historical bars are split/dividend adjusted in the catalog.
**Success Criteria:** No overnight soft-stop assumption anywhere; a known split (e.g.
NVDA 10:1, 2024-06) does not produce a phantom gap in the backtest.
**Tests:** Regression test asserting bracket SL is placed on entry; data-integrity test
on the split date.
**Status:** Mostly done (logic) — `honest_trend_equity.py` now places exchange-side
STOP_MARKET protective stops (re-placed on each pyramid at the new avg, cancelled on
EMA-cross exit), RTH gating (`rth_only`), and a pluggable `regime_gate.py` replacing the
crypto FNG filter (VIX/put-call, disabled by default — operator picks the signal).
Bracket() rejected (it forces a TP); standalone STOP_MARKET used instead. Tests
(`test_honest_trend_equity.py`, `test_regime_gate.py`): 9 pass incl. a crafted gap-down
that fires the exchange stop (stop_exits>=1, loss capped at ~-1.4% vs the -39% crash) and
a regime CSV that vetoes all entries. NOTE: pytest needs `bypass_logging=True` (Rust
logger inits once/process; a 2nd BacktestEngine aborts otherwise). REMAINING: the NVDA
2024 split data-integrity check needs real IB bars (blocked on IB).

## Stage 4: Persistence + dashboard unification
**Goal:** Write Nautilus fills/positions to TimescaleDB via `on_order_filled` /
`on_position_closed`. Add `asset_class` ('crypto'|'equity') to the relevant tables/views.
Dashboard shows crypto-accumulation + equity-trend side by side.
**Success Criteria:** `quant.panda.qzz.io` renders both asset classes; backtest_runs
distinguishes them; Kelly popover works for equity strategies too.
**Tests:** SSR smoke check (page renders 200, not just build success); a row round-trips
engine → DB → dashboard.
**Status:** Not Started

## Stage 5: IB paper account live (dry-run equivalent)
**Goal:** TradingNode against IB paper (TWS port 7497 / Gateway 4001). Run the ported
strategy live-paper on the semiconductor pool. No real money.
**Success Criteria:** Node connects, receives live RTH bars, places + fills paper orders,
writes to DB. Runs unattended for a full session without crashing.
**Tests:** Connection/health check; an end-of-session reconciliation (Nautilus Cache vs
DB) shows no drift.
**Status:** Not Started

---

## Crypto accumulation engine (done 2026-06-07, parallel track)
While IB equities were pending activation, built `nautilus_crypto/` — the crypto half on
the same Nautilus engine, using REAL local Binance data (no account needed). Per the
"crypto = pure accumulation" philosophy: a fear-driven buy-the-dip DCA (`accumulator.py`)
that buys harder when Fear&Greed is low / price is in a drawdown, and never sells.
Backtested on BTC 2017-2026: smart fear+dip DCA beats naive fixed DCA by 9.73% lower cost
basis and +57.5 pts ROI. 8 tests on real data, all green. Does NOT replace the live
Event/Smart DCA daemon yet — that's a later decision. This proved the Nautilus engine on
REAL data (equities were stuck on synthetic until IB activates).

## Joint Kelly (deferred but flagged)
Semiconductors are highly correlated internally and with BTC (risk-on/off). The current
per-instrument Half-Kelly will over-allocate. Once Stage 2-4 are stable, replace the
scalar Kelly with the covariance form f* = Σ⁻¹μ across the equity pool, using Nautilus's
unified Portfolio. Tracked separately; not a blocker for first paper-live.

## Hard guardrails
- Keep `DCA_LIVE_ENABLED=false` and IB on **paper** until explicitly promoted.
- Marketing/positioning: tools/signals/dashboard only — never 代客理财/资金池.
- Never commit secrets; IB creds go through sops, not the repo.
