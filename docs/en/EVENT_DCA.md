# Event-Driven DCA (Crash-Buy Bot)

**Date**: 2026-04-22
**Goal**: On top of weekly DCA, catch flash crashes / sharp drops to auto-add BTC and improve BTC acquisition rate.

## Why

Pure weekly DCA (`crypto-dca.timer`) misses mid-week flash crashes. Backtests (below) show the hybrid strategy (weekly + event) acquires **+6.4% more BTC** than pure weekly, which compounds to +2.24 BTC over 8 years.

**Design principle**: event triggers do NOT replace weekly DCA, they **stack on top**. Weekly DCA guarantees "never miss a year"; event triggers optimize "average cost".

## Signal hierarchy (by importance)

| Signal | Threshold | Detection | 8-year historical count |
|------|------|---------|:---------:|
| CAPITUL | 30d drawdown > 25% | REST poll 5min | 109 |
| SUSTAIN | 24h drop > 10% | REST poll 5min | 47 |
| FAST    | 5m drop > 5%  | WebSocket realtime | 18 |
| FLASH   | 1m drop > 3%  | WebSocket realtime | 8 |

**alpha distribution**: CAPITUL + SUSTAIN contribute 80%+ of the value. FLASH is rare but each occurrence is high value (e.g. 2020-3-12).

## Backtest results (2018-02 → 2026-04, BTC spot price $75,841)

| Strategy | Buys | USDT | BTC | Avg cost | Current value | ROI |
|------|-----:|----:|-----:|------:|------:|---:|
| A pure weekly $500 base | 429 | $247K | 17.75 | $13,918 | $1.35M | +445% |
| B pure event $1000x3/month | 119 | $127K | 10.81 | $11,731 | $820K | +547% |
| **C hybrid $350w+$700e** | **548** | **$262K** | **19.99** | **$13,090** | **$1.52M** | **+479%** |
| X lump sum $208K | 1 | $208K | 20.19 | $10,300 | $1.53M | +636% |

**BTC acquired per $1M**:
- Pure weekly A: 71.8 BTC
- Hybrid C: **76.4 BTC** (+6.4%)
- Pure event B: 85.2 BTC (highest, but budget is underutilized)

## Implementation architecture

```
                    ┌──────────────────┐
                    │  event_dca_bot   │  always-on daemon
                    │                  │
   Binance WS  ──►  │  PriceBuffer     │  ring 5min tick
   aggTrade         │  ↓ detect        │
                    │  FLASH / FAST    │
                    │                  │
   Binance REST ──► │  poll 5min       │
   klines           │  SUSTAIN / CAPITUL│
                    │                  │
                    │  ↓               │
                    │  State (cooldown │  JSON file
                    │  + budget tracker)│
                    │  ↓ if OK          │
                    │  spawn subprocess│
                    └─────┬────────────┘
                          │
                          ▼
              python dca_executor.py
                --base $amount
                --trigger event:FLASH
                [--live if DCA_LIVE_ENABLED]
                          │
                          ▼
                Supabase + Telegram
                (possibly Binance buy)
```

## Key files

| File | Purpose |
|------|------|
| `strategies/event_dca_bot.py` | Main daemon (WebSocket + REST polling) |
| `scripts/backtest_event_dca.py` | Backtest script (reproducible validation) |
| `start_event_dca_bot.sh` | sops launch wrapper |
| `~/.config/systemd/user/crypto-event-dca.service` | systemd always-on unit |
| `event_dca_state.json` | Runtime state (cooldown + monthly budget) |

## Configuration (env vars)

```bash
EVENT_DCA_MONTHLY_BUDGET=2000    # monthly event budget (default $2000)
EVENT_DCA_PER_TRIGGER=700        # base amount per trigger (FnG<20 ×1.5 / >60 ×0.7)
EVENT_DCA_COOLDOWN_HOURS=72      # cooldown after trigger (prevents re-buying same crash)
EVENT_DCA_MAX_PER_MONTH=3        # max triggers per month
DCA_LIVE_ENABLED=true            # only when set does it actually place orders (else log + Telegram only)
```

By default it **does NOT actually buy** (`DCA_LIVE_ENABLED` unset = dry-run).

## Ops

```bash
# Status
systemctl --user status crypto-event-dca.service
journalctl --user -u crypto-event-dca.service -f

# Manual test
python strategies/event_dca_bot.py --self-test

# View recent trigger history
cat event_dca_state.json | jq

# Restart
systemctl --user restart crypto-event-dca.service

# Stop
systemctl --user stop crypto-event-dca.service
```

## Steps to enable live

1. Confirm `crypto-dca.service` (weekly DCA) has been live-soaked for 2+ weeks (dry-run log looks normal)
2. Add `DCA_LIVE_ENABLED=true` to SOPS secrets.env
3. Confirm in SOPS that `BINANCE_API_KEY` / `BINANCE_API_SECRET` exist (spot buy permission is enough)
4. Restart: `systemctl --user restart crypto-event-dca.service`
5. First week: **manually observe each trigger**, ensure Telegram alert + Binance actual fill match

## Boundary conditions

```python
# Hard rules, do not modify
MAX_PER_MONTH = 3               # prevent frenzy buying within a month
COOLDOWN_HOURS = 72             # only buy once per crash
MONTHLY_BUDGET = $2000          # annual cap $24K
MIN_AMOUNT_USDT = $50           # no trigger if budget < $50
WEBSOCKET_RECONNECT_DELAY = 5s  # auto-reconnect on drop

# Soft rules (tunable)
FLASH triggers at most once per 60s in cooldown (avoid same-minute duplicates)
FnG < 20 → amount × 1.5 (panic-bottom size-up)
FnG > 60 → amount × 0.7 (halve in greed zone)
```

## Failure modes + recovery

| Symptom | Likely cause | Fix |
|------|---------|------|
| No triggers for 1 month | Mild market / no crash | Normal, weekly DCA keeps running |
| Frequent WS disconnects | Network/firewall | `systemctl --user restart` |
| No Telegram push | Token wrong | Check SOPS secrets.env |
| Trigger fires but no order | `DCA_LIVE_ENABLED` not set | Expected (dry-run) |
| Binance order fails | API key/balance | Check Binance API logs |
| State file corrupted | Unexpected exit | Delete `event_dca_state.json` to rebuild |

## Future evolution

- **V2. Add liquidation-stream signal**: subscribe to `!forceOrder@arr`, weighted trigger when 1h liquidations > $300M
- **V3. Supabase UI**: visualize trigger history in dashboard port 3001
- **V4. Reverse detection**: detect pumps, reduce on FnG > 90 (skipping for now, violates long-only BTC philosophy)
- **V5. Multi-asset**: event DCA for ETH / SOL (same framework, only change SYMBOL)

## Known limitations

1. **FLASH/FAST during WebSocket disconnects are missed** (auto-reconnect but data has gaps)
2. **REST poll runs every 5min**, theoretically a 30d DD could exceed threshold within 5min and already be missed (but signals of this magnitude almost never last <5min)
3. **Binance REST rate limit**: 5min polling is far below 1200req/min cap, no risk of hitting limit
4. **FnG API free tier**: alternative.me has no explicit rate limit, but recommended to stay under 1 request/min
