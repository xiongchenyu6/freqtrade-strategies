# nautilus_equity — US-equity trend engine (NautilusTrader)

Isolated subsystem for **active US-equity trend trading**, separate from the crypto
freqtrade stack. See `../IMPLEMENTATION_PLAN.md` for the full 5-stage migration plan.

- **Why separate:** Nautilus is a heavy Rust-core engine; it gets its own venv so it
  never touches the freqtrade editable install.
- **What's reused:** `../strategies/kelly_sizer.py` (imported verbatim — pure Python).
- **Unify at:** TimescaleDB + the Svelte dashboard (Stage 4 adds an `asset_class` dim).

## Environment

Dedicated venv (NOT the freqtrade `.venv`), latest packages:

```bash
# already created:
uv venv nautilus_equity/.venv --python 3.13
VIRTUAL_ENV=nautilus_equity/.venv uv pip install "nautilus_trader[ib]"
# nautilus-trader 1.227.0, nautilus-ibapi 10.45.1
```

## What works now (Stages 1–3, synthetic data, no IB)

```bash
P=nautilus_equity/.venv/bin/python

# Stage 1 — engine smoke test:
$P nautilus_equity/backtest_spike.py          # EMA cross, kelly_stake() wired in

# Stage 2/3 — full HonestTrend port (event-driven indicators, pyramids, protective
# stops, RTH gate, regime gate):
$P nautilus_equity/run_honest_equity.py

# Tests (40 green: 9 equity-engine + 31 portable kelly_sizer):
$P -m pytest nautilus_equity/test_honest_trend_equity.py nautilus_equity/test_regime_gate.py -q
$P -m pytest tests/test_kelly_sizer.py -q     # same module, runs under either venv

# Download real adjusted bars from IB (needs TWS/Gateway running):
$P nautilus_equity/download_ib.py             # → ParquetDataCatalog at nautilus_equity/catalog/
```

### Files
| File | Role |
|---|---|
| `backtest_spike.py` | Stage 1 engine smoke test (synthetic) |
| `honest_trend_equity.py` | Event-driven HonestTrend port (Stages 2–3) |
| `regime_gate.py` | Pluggable sentiment gate (FNG→VIX replacement) |
| `run_honest_equity.py` | Backtest runner |
| `download_ib.py` | IB historical → ParquetDataCatalog |
| `test_*.py` | 9 engine/gate tests |

### Stage 3 equity-reality notes
- **Gap-safe stops:** exchange-side `STOP_MARKET` (not soft next-bar exits). Re-placed at
  the new average on every pyramid; cancelled on EMA-cross exit. `bracket()` was rejected
  because it forces a take-profit leg.
- **RTH gating:** `rth_only=True` restricts entries to 09:30–16:00 ET (intraday bars).
- **Regime gate:** `regime_csv`/`regime_threshold`/`regime_mode`; disabled by default.
- **pytest gotcha:** use `LoggingConfig(bypass_logging=True)` — the Rust logger inits once
  per process and a second `BacktestEngine` aborts otherwise.

## IB setup (you have an account)

1. Run **IB Gateway** (lighter, headless-friendly) or **TWS**, log into the **paper**
   account.
2. Enable API: TWS/Gateway → Settings → API → *Enable ActiveX and Socket Clients*.
3. Ports: TWS paper `7497`, TWS live `7496`, Gateway paper `4002`, Gateway live `4001`.
   `download_ib.py` defaults to `7497`; override with `IB_PORT`.
4. On NixOS, run the Gateway as a user service — remember `/run/current-system/sw/bin`
   must be in the service PATH (same gotcha as the existing bot services).

## Concept mapping (freqtrade → Nautilus), proven in `backtest_spike.py`

| freqtrade | Nautilus |
|---|---|
| `populate_indicators` (vectorized pandas) | incremental indicator, `register_indicator_for_bars` + `on_bar` |
| `populate_entry_trend` / `_exit_trend` | logic inside `on_bar` |
| `custom_stake_amount` (Kelly) | `kelly_stake(...)` in the entry path — **reused unchanged** |
| `Backtesting` class | `BacktestEngine` |
| feather datahandler | `ParquetDataCatalog` |

## Guardrails

- IB stays on **paper** until explicitly promoted; mirrors `DCA_LIVE_ENABLED=false`.
- IB credentials via sops, never committed.
- The `catalog/` dir is generated data — keep it out of git.
