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

## Stage 4 — Crypto live execution on Nautilus — DEPLOYED TO PROD (testnet) 2026-06-07
Packaged nautilus-trader (aarch64 wheel) + a nautilus-accumulator NixOS service in
nur-packages; deployed to **oracle-arm-002** via dotfiles + nixos-rebuild switch. The box
also got bumped 26.05→26.11 (fixed a stale supabase-realtime mix-deps FOD hash that blocked
it). Live on Binance **testnet**: service active, Ed25519 session.logon authenticated,
1372 instruments, stream connected; buys on hourly bar close. Dashboard/API survived
(api.panda + quant both 200). Soak running. Flip `testnet=false` only after weeks clean.

### (prior) testnet PROVEN locally 2026-06-07
`TradingNode` + native Binance adapter running the accumulator (`live_accumulation.py`).
END-TO-END VALIDATED on Binance testnet: connect → Ed25519 `session.logon` → load account
(testnet balances) + 1372 instruments → subscribe 1m bars → on first bar (FNG=12 extreme
fear → deep-fear 6× boost) the accumulator placed a live order: BUY MARKET 0.0096 BTC
@ $62,515.86, Submitted → Accepted (venue_order_id) → Filled. The smart fear logic fired
in a real exchange environment. KEY GOTCHA: execution requires an **Ed25519** API key
(HMAC/RSA deprecated — they authenticate + load account but fail at session.logon).
REMAINING before real money: long unattended dry-run/testnet soak (reconnect, order
timeout, reconciliation, daily restart), fold in the DCA daemon, then mainnet with
`DCA_LIVE_ENABLED=false` lifted only after weeks of clean operation.

## Stage 5 — Equity live (IB paper → real)
`TradingNode` against IB paper, semiconductor pool, full sessions unattended; reconcile
Cache vs DB. Promote to real only after sustained clean paper operation.

## Stage 6 — Hyperopt via Optuna (build when needed)
Optuna study wrapping a Nautilus `BacktestNode` run; objective = Calmar/Sharpe with DD
penalty (mirror the old HonestHyperOptLoss). Not a blocker for going live.

## Stage 7 — Decommission freqtrade  (PATH B chosen 2026-06-08: wait for mainnet, then delete)
**End goal:** `rm -rf ~/Documents/github/public/freqtrade` (the core repo + 8.7G .venv).
**NOT safe yet** — these still depend on it (mapped 2026-06-08). Delete only after EVERY box ticked.

What still depends on `~/Documents/github/public/freqtrade` (all on the `game` dev machine):
| dependency | what it is | migration before deletion |
|---|---|---|
| `crypto-event-dca.service` (event_dca_bot.py) | live (dry-run) Event DCA bot | → Nautilus accumulator on **mainnet** (oracle-arm-002) takes over |
| `crypto-reactor.service` (event_reactor.py) | price-spike reactor | fold into Nautilus / retire |
| `crypto-dca.timer` (dca_executor.py) | weekly DCA | → Nautilus accumulator |
| `crypto-ts-sync.timer` (sync_local_state) | freqtrade sqlite → quant.trades | obsolete once freqtrade dry-run gone (Nautilus writes quant.nautilus_trades via TradeLedger) |
| `crypto-alerts.timer` (telegram_alerts.py) | KOL + bot-health + daily report | give own venv OR repoint to Nautilus state |
| `md_http_server.py` :3001 | market-data HTTP | own venv or retire |
| `freqtrade download-data` | produces user_data/data/binance/*.feather for Nautilus backtests | replace with standalone ccxt downloader / Nautilus Binance historical |
| freqtrade CLI scripts (start_bot/start_live/backtest/visualize) | run freqtrade strategies | retire (strategies move to Nautilus) |

Note: the daemons' CODE is freqtrade-independent (0 imports) — they just borrow freqtrade's
.venv as the Python interpreter (ccxt/websockets/psycopg2). So the blocker is the interpreter
+ the live function, not code coupling.

Deletion checklist (do in order, only when each is green):
1. ☐ Nautilus crypto accumulator + trend proven on **MAINNET** (post-soak), real money on.
2. ☐ Stop + remove `crypto-event-dca`, `crypto-reactor`, `crypto-dca.timer` (function now on Nautilus).
3. ☐ Retire `crypto-ts-sync` (freqtrade sqlite no longer the source; dashboard uses quant.nautilus_trades).
4. ☐ Repoint `crypto-alerts` + `md_http_server` to their own venv (or retire) — drop freqtrade .venv.
5. ☐ Replace `download-data` with a freqtrade-free downloader for any backtest data refresh.
6. ☐ Archive freqtrade strategies/configs/factor-lib/freqaimodels in the freqtrade-strategies repo.
7. ☐ Update CLAUDE.md / docs to the single Nautilus stack.
8. ☐ THEN `rm -rf ~/Documents/github/public/freqtrade`.

---

## Joint Kelly (deferred but flagged)
Semis are highly correlated with each other and with BTC. Replace scalar Half-Kelly with
the covariance form f* = Σ⁻¹μ across the pool once Stages 2-3 are stable.

## Hard guardrails
- Everything paper/dry-run/testnet first; real money only after sustained clean operation.
- `DCA_LIVE_ENABLED=false` until crypto live on Nautilus is proven.
- Secrets stay sops-encrypted (already verified: secrets.env/secrets.yaml are sops, safe).
- Never commit plaintext secrets, venvs, or generated data/catalogs.
