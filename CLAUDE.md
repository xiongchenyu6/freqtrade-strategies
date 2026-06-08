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

## Deploy (oracle-arm-002, NixOS)
- Live crypto runs as **system services on oracle-arm-002**: `nautilus-accumulator`, `nautilus-trend`,
  `nautilus-signal` (all testnet/data-only). Packaged in `github:xiongchenyu6/nur-packages`
  (`modules/nautilus-*`, `pkgs/nautilus-trader`), wired in `dotfiles/nixos-configurations/oracle-arm-002/nautilus.nix`.
- Module changes need: commit+push nur-packages → `nix flake update xiongchenyu6` in dotfiles →
  `NIXPKGS_ALLOW_INSECURE=1 nixos-rebuild switch --flake .#oracle-arm-002 --build-host root@oracle-arm-002 --target-host root@oracle-arm-002 --impure`.
- The nur overlay is NOT global on hosts → reference packages as
  `inputs.xiongchenyu6.packages.${system}.nautilus-trader`.
- Secrets: sops. Host secrets in `dotfiles/secrets/common.yaml` under `oracle-arm-002/*`
  (binance-api-key/secret, telegram-bot-token/chat-id, quant-password). Repo secrets in
  `secrets.env`/`secrets.yaml` (sops-encrypted; safe to commit). DB-touching services wrap the
  command in `sops exec-env secrets.env "<single quoted cmd>"` (quoting avoids a flag-eating bug).

## Local services (game box, `~/.config/systemd/user/quant-*`, on `.venv-bots`)
Monitoring/reporting only after the single-stack migration: `quant-ts-sync` (wf sync),
`quant-alerts` (telegram), `quant-deribit`, `quant-risk-monitor`, `quant-daily-report`,
`quant-dashboard` (md_http :3001). The crypto bots `quant-event-dca`/`quant-reactor`/`quant-dca`
were **retired** (function moved to Nautilus@oracle-arm-002).

## Guardrails (hard)
- All crypto stays **testnet/dry-run**; IB stays **paper**. `DCA_LIVE_ENABLED` empty/false.
- Binance EXECUTION on Nautilus requires an **Ed25519** key (HMAC/RSA fail at session.logon).
- Data-only mainnet nodes must pass **no** Binance key (a placeholder → -2008 → 0 instruments).
- Never commit plaintext secrets, venvs, or generated data/catalogs/reports. Commit/push only when asked.
- Marketing = tools/signals/dashboard only — never 代客理财 / pooled funds.
- NixOS user services need `/run/current-system/sw/bin` on PATH (sops/pgrep/systemctl).
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
