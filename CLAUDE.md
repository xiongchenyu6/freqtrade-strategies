# CLAUDE.md — quant

Crypto + (planned) US-equity quant trading on **NautilusTrader**. Formerly `freqtrade-strategies`;
freqtrade is fully removed (single-stack migration done 2026-06-08). See `IMPLEMENTATION_PLAN.md`
for stage status and `STRATEGY_LEADERBOARD.md` for the strategy research log.

## Layout
- `nautilus_crypto/` — crypto engine (Nautilus). `accumulator.py` (FNG smart-DCA), `donchian.py`
  (trend), `signal_detect.py`/`signal_alerter.py`/`telegram_notifier.py` (signal layer),
  `trade_ledger.py` (writes `quant.nautilus_trades`), `live_*.py`/`run_*.py` (live nodes + backtests).
- `nautilus_equity/` — US-equity engine via IB (own `.venv`, has `nautilus_trader[ib]`). Built,
  not yet live (blocked on IB Gateway + paper account).
- `nautilus_options/` — Deribit CSP backtests (verdict: not deployed).
- `strategies/` — standalone bots/helpers (NOT freqtrade strategies anymore): `telegram_alerts.py`,
  `kelly_sizer.py`, `risk_manager.py`, `dca_executor.py`, `deribit_monitor.py`.
- `scripts/` — `sync_local_state_to_timescale.py` (wf → TimescaleDB), `download_binance.py` (ccxt
  data refresh, replaced freqtrade download-data), `md_http_server.py` (localhost :3001 dashboard).
- `web/apps/app/` — SvelteKit dashboard on Cloudflare Workers. Deploy: `pnpm run deploy` (NOT
  `pnpm deploy`). The `/nautilus` route shows live execution from `quant.nautilus_trades`.
- `migrations/` — TimescaleDB schema (db `api`, schema `quant`, served via PostgREST `api.*`).

## venvs (uv; symlink to external python so they survive dir moves)
- `.venv-bots` — the standalone bots' interpreter (ccxt/websockets/psycopg2/pandas/requests). NO
  nautilus_trader.
- `nautilus_equity/.venv` — has nautilus_trader 1.227.0 (+ ib). Used to run crypto AND equity
  Nautilus backtests/tests (`sys.path.insert(0, <module dir>)` is how tests import siblings).
- pytest is NOT installed; tests are pytest-style but run via the venv directly. Pure modules can be
  exercised with a small stdlib harness if needed.

## Commands
Python (no Makefile/pytest — invoke the venv interpreter directly; `P=nautilus_equity/.venv/bin/python`):
- Run a Nautilus backtest: `$P nautilus_crypto/run_accumulation.py` (or `run_trend_crypto.py`,
  `run_portfolio_trend.py`; equity: `$P nautilus_equity/run_honest_equity.py`).
- Refresh market data: `$P nautilus_crypto/download_binance.py` (ccxt → feather under `user_data/data/`).
- Run one test module (no pytest collector — drive the `test_*` funcs with a one-liner):
  `$P -c "import sys; sys.path.insert(0,'nautilus_crypto'); import test_signal_detect as t; [getattr(t,n)() for n in dir(t) if n.startswith('test_')]; print('ok')"`
  (swap the dir/module to target another file; run a single test by naming just that one function).
- `tests/test_kelly_sizer.py` imports from `strategies/` via `sys.path`; same harness pattern.

Web dashboard (`cd web/apps/app`, pnpm):
- `pnpm run dev` — local dev server.   `pnpm run check` — svelte-check typecheck.
- `pnpm run lint` — prettier --check + eslint.   `pnpm run format` — prettier --write.
- `pnpm run deploy` — `vite build && wrangler deploy` (NOT `pnpm deploy`, which is a different pnpm builtin).

## Deploy (oracle-arm-002, NixOS)
- Live crypto runs as **system services on oracle-arm-002**: `nautilus-accumulator`, `nautilus-trend`,
  `nautilus-signal` (all testnet/data-only). Packaged in `github:xiongchenyu6/nur-packages`
  (`modules/nautilus-*`, `pkgs/nautilus-trader`), wired in `dotfiles/nixos-configurations/oracle-arm-002/nautilus.nix`.
- Also on arm-002: `quant-news-collector` + `quant-stress-index` timers (nur `modules/quant-collectors`,
  vendored copies of `strategies/news_collector.py`/`stress_index.py` — keep both copies in sync when
  editing). Moved off the game box 2026-06-12 so 快讯/压力指数 run 7×24 next to the DB.
- Module changes need: commit+push nur-packages → `nix flake update xiongchenyu6` in dotfiles →
  `NIXPKGS_ALLOW_INSECURE=1 nixos-rebuild switch --flake .#oracle-arm-002 --build-host root@oracle-arm-002 --target-host root@oracle-arm-002 --impure`.
- The nur overlay is NOT global on hosts → reference packages as
  `inputs.xiongchenyu6.packages.${system}.nautilus-trader`.
- Secrets: sops. Host secrets in `dotfiles/secrets/common.yaml` under `oracle-arm-002/*`
  (binance-api-key/secret, telegram-bot-token/chat-id, quant-password). Repo secrets in
  `secrets.env`/`secrets.yaml` (sops-encrypted; safe to commit). DB-touching services wrap the
  command in `sops exec-env secrets.env "<single quoted cmd>"` (quoting avoids a flag-eating bug).
- **Equity IB Gateway sidecar (oracle-amd-002, x86_64):** Gateway is x86-only + unpackaged in
  nixpkgs, so it runs as a `gnzsnz/ib-gateway` podman container (paper) on the AMD box, API bound
  to the wg mesh IP `172.22.240.97:4002` (wg0 is trusted; never public). The equity node connects
  over WireGuard (`IB_HOST=172.22.240.97 IB_PORT=4002`). Config:
  `dotfiles/nixos-configurations/oracle-amd-002/ib-gateway.nix`; runbook + 2FA/sops steps:
  `nautilus_equity/deploy/ib-gateway-headless.md`. Disable 2FA on the paper login first.
- **Equity EXECUTION runs on the game box, NOT amd-002** (decided 2026-06-10). The amd-002 nix
  node `services.nautilus-equity-trend` traded but didn't persist (stale nur copy) + under-sized;
  it is **RETIRED** (`enable = false`). amd-002 hosts ONLY the IB Gateway now. The single equity
  node is `quant-equity.service` on the game box (see Local services). They must never both run —
  they share IB client id 8 on the one paper account.

## Local services (game box, `~/.config/systemd/user/quant-*`)
Monitoring/reporting on `.venv-bots`: `quant-ts-sync` (wf sync), `quant-alerts` (telegram),
`quant-deribit`, `quant-risk-monitor`, `quant-daily-report`, `quant-dashboard` (md_http :3001).
On `nautilus_equity/.venv` (needs nautilus_trader): `quant-backtest-runner` (playground compute)
and **`quant-equity`** — the US-equity LIVE node (`live_honest_equity.py`, IB paper, persists to
`quant.nautilus_trades` asset_class='equity' via in-node TradeLedger). Env in
`~/.config/quant/equity.env` (IB_* + EQ_QUOTE_PER_BASE_FX=0.74 for the SGD-base account + TIMESCALE_URL).
The crypto bots `quant-event-dca`/`quant-reactor`/`quant-dca` were **retired** (moved to Nautilus@oracle-arm-002).

## Guardrails (hard)
- All crypto stays **testnet/dry-run**; IB stays **paper**. `DCA_LIVE_ENABLED` empty/false.
- Binance EXECUTION on Nautilus requires an **Ed25519** key (HMAC/RSA fail at session.logon).
- Data-only mainnet nodes must pass **no** Binance key (a placeholder → -2008 → 0 instruments).
- Never commit plaintext secrets, venvs, or generated data/catalogs/reports. Commit/push only when asked.
- Marketing = tools/signals/dashboard only — never 代客理财 / pooled funds.
- NixOS user services need `/run/current-system/sw/bin` on PATH (sops/pgrep/systemctl).
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
