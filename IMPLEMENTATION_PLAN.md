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

## Stage 7 — Decommission freqtrade — CORE DONE (PATH A executed 2026-06-08)
**Done:** freqtrade core repo deleted (~11G freed); daemons repointed to `.venv-bots`;
`download-data` replaced by `nautilus_crypto/download_binance.py` (ccxt); repo renamed
`freqtrade-strategies`→`quant`, services `crypto-*`→`quant-*`. Dead freqtrade strategies/
scripts/news-cluster git-rm'd. Stale freqtrade refs scrubbed from kept live code
(telegram_alerts health-check + daily-report P&L → `quant.nautilus_trades`; ts-sync dead
sqlite stage removed).

## Stage 8 — True single-stack crypto: port signal layer onto Nautilus, retire daemons
**Why:** the only remaining parallelism — `quant-event-dca` (dry-run dip/FNG) + `quant-reactor`
(spike) are the *signal/alert layer* (Telegram + dashboard feed); Nautilus is *execution* (no
alerting). Decision 2026-06-08: **port alerts into Nautilus, then retire the daemons** (single
process). Key constraint: signal detection needs REAL (mainnet) public prices even while
execution stays testnet → the alerter runs on a mainnet **data-only** feed.

**Goal**: Nautilus emits the spike (PUMP/DUMP) + accumulation-dip (FLASH/FAST) Telegram alerts;
then stop event-dca/reactor/dca.
**P1 (code+test, no deploy)** — `telegram_notifier.py` (sink), `signal_detect.py` (pure
Spike/Dip detectors ported from the daemons), `signal_alerter.py` (Nautilus Actor wiring
bars→detectors→notifier) + tests.  **Status: COMPLETE 2026-06-08** — 9 pure unit tests pass;
integration test drives the actor through a real BacktestEngine (synthetic spike+dip path) and
confirms both Telegram alerts fire via the subscribe→on_bar wiring. Fixed a latent cooldown bug
(epoch-0 init suppressed the first alert) the original daemons had.
**P2 (deploy)** — data-only mainnet signal node + nur module; deploy to oracle-arm-002.
**Status: DEPLOYED 2026-06-08** — `run_signal_alerter.py` (data-only, no exec client, no keys →
loads 3591 instruments anonymously via public exchangeInfo; first attempts failed on a
placeholder key that forced an authed fee-tier call). `nautilus-signal` nur module + dotfiles
`services.nautilus-signal` (BTC/ETH/SOL, 1-min, mainnet). Telegram creds added to host sops
(`oracle-arm-002/telegram-{bot-token,chat-id}`, same bot/chat as legacy daemons). Service
`active`, SignalAlerter RUNNING, startup heartbeat sent (no telegram errors). **Remaining: soak
+ confirm a real spike/dip alert lands before P3.**
**P3 (retire)** — **DONE 2026-06-08**: stopped+disabled `quant-event-dca`/`quant-reactor`/
`quant-dca.timer`; trimmed ts-sync to the `wf` stage only (event_dca state frozen; historical
event_dca_triggers rows remain in the DB for the dashboard). Crypto is now single-stack: all
execution + signal runs on Nautilus@oracle-arm-002 (accumulator + trend + signal). Kept on the
game box: ts-sync(wf), alerts, deribit, risk-monitor, daily-report (monitoring/reporting only).
**Out of scope / later**: `md_http_server` :3001 (retire or own venv); CLAUDE.md for /quant;
the dashboard's event_dca_triggers panel is now historical-only (live execution = /nautilus).

**STAGE 8 COMPLETE** — crypto runs on one stack (NautilusTrader); the freqtrade-era parallel
daemons are gone.

---

## Joint Kelly (deferred but flagged)
Semis are highly correlated with each other and with BTC. Replace scalar Half-Kelly with
the covariance form f* = Σ⁻¹μ across the pool once Stages 2-3 are stable.

## Hard guardrails
- Everything paper/dry-run/testnet first; real money only after sustained clean operation.
- `DCA_LIVE_ENABLED=false` until crypto live on Nautilus is proven.
- Secrets stay sops-encrypted (already verified: secrets.env/secrets.yaml are sops, safe).
- Never commit plaintext secrets, venvs, or generated data/catalogs.
