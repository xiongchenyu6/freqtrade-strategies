# Terminal State — single-stack NautilusTrader, retire freqtrade

**Decision (2026-06-07):** Consolidate onto **one engine: NautilusTrader**. freqtrade is
retired entirely. Driven by: (a) not wanting to maintain two stacks long-term, and
(b) freqtrade cannot trade US equities (CCXT-only), so the surviving single stack must be
the one that does both crypto and equities → Nautilus.

This is feasible because the **actual freqtrade footprint is thin** (recon 2026-06-07):
FreqAI unused (overfitting — dropped), hyperopt not a live dependency, pairlists is just
StaticPairList (BTC/ETH/BNB), no protections configured, the factor library is not imported
by any live strategy, and monitoring (telegram_alerts.py) + dashboard + TimescaleDB are
already custom and stack-agnostic.

## Terminal architecture
- **One engine (Nautilus)** runs all three: crypto accumulation, US-equity trend, and
  (later) crypto live execution.
- **Crypto = pure accumulation.** The fear-driven accumulator replaces the crypto trend
  strategies. `HonestTrend1mLive` (current crypto-trend live bot) is RETIRED with
  freqtrade, NOT ported — its trend edge moves to US equities. *(Confirm this assumption.)*
- **US equities = trend.** HonestTrend ported to event-driven (done).
- **Hyperopt** = Optuna/vectorbt wrapping Nautilus `BacktestNode`. Built only when
  optimizing; never a runtime dependency.
- **FreqAI = dropped.** Not migrated.

## Keep (stack-agnostic, untouched)
`strategies/telegram_alerts.py`, the Svelte dashboard, TimescaleDB, `strategies/kelly_sizer.py`,
the standalone Event/Smart DCA daemon (0 freqtrade imports — independent until folded in).

## Retire / archive
The `freqtrade` package + all `configs/config_*.json`, the crypto-trend strategies
(`HonestTrend*` except as reference), the unused factor library and `freqaimodels/`
(archive, don't migrate).

---

## Stage 1 — Nautilus engine foundation — DONE
Equity trend port (`nautilus_equity/honest_trend_equity.py`) + crypto accumulator
(`nautilus_crypto/accumulator.py`). kelly_sizer reused. Exchange-side stops, RTH gate,
VIX regime gate (real VIX 2011-2026). 48 tests green. Crypto accumulator validated on real
Binance data through the 2026-06 dip (smart DCA: -9.56% cost basis, +44 pts ROI vs naive).

## Stage 2 — Equity real data + validation — BLOCKED on IB (paper active ~Mon 6/8)
`download_ib.py` (NVDA/AMD/QQQ adjusted bars → ParquetDataCatalog); feed real KellyStats;
validate ADX/indicators vs talib; NVDA 2024 10:1 split data-integrity check.

## Stage 3 — Persistence + dashboard unification
Write Nautilus fills/positions to TimescaleDB via `on_order_filled`/`on_position_closed`;
add `asset_class` ('crypto'|'equity') dimension; dashboard shows both side by side.
Do this with REAL data only (don't pollute prod DB with synthetic trades).

## Stage 4 — Crypto live execution on Nautilus — THE careful one
`TradingNode` + native Binance adapter running the accumulator. Replaces freqtrade's live
loop AND folds in the standalone DCA daemon. freqtrade gives reliability for free
(reconnect, order timeout, reconciliation) — all of that must be re-proven on Nautilus.
Path: Binance testnet/sandbox → long dry-run → real money. Keep `DCA_LIVE_ENABLED=false`
until the dry-run has run unattended for weeks without drift.

## Stage 5 — Equity live (IB paper → real)
`TradingNode` against IB paper, semiconductor pool, full sessions unattended; reconcile
Cache vs DB. Promote to real only after sustained clean paper operation.

## Stage 6 — Hyperopt via Optuna (build when needed)
Optuna study wrapping a Nautilus `BacktestNode` run; objective = Calmar/Sharpe with DD
penalty (mirror the old HonestHyperOptLoss). Not a blocker for going live.

## Stage 7 — Decommission freqtrade
Remove the freqtrade dependency; archive freqtrade strategies/configs/factor-lib/freqaimodels;
update CLAUDE.md and docs to describe the single Nautilus stack. Delete the freqtrade `.venv`.

---

## Joint Kelly (deferred but flagged)
Semis are highly correlated with each other and with BTC. Replace scalar Half-Kelly with
the covariance form f* = Σ⁻¹μ across the pool once Stages 2-3 are stable.

## Hard guardrails
- Everything paper/dry-run/testnet first; real money only after sustained clean operation.
- `DCA_LIVE_ENABLED=false` until crypto live on Nautilus is proven.
- Secrets stay sops-encrypted (already verified: secrets.env/secrets.yaml are sops, safe).
- Never commit plaintext secrets, venvs, or generated data/catalogs.
