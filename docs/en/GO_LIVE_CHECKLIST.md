# Go-Live Checklist

> **2026-04-22 architecture update**: This checklist covers all components of Phase A (spot alts trend) + Phase B (futures L+S) + Smart DCA dual-channel. Each component goes live independently and can be rolled out in batches at your own pace.

## Architecture Quick Reference

| Component | Config | Market | Key Requirement | Live flag |
|------|--------|------|---------|-----------|
| HonestTrend15mDry | `config_dryrun_honest15m.json` | Binance spot | spot trading only | — |
| HonestTrend1mMTF | `config_dryrun_honest1mmtf.json` | Binance spot | spot trading only | — |
| **HonestTrendFutures** | `config_dryrun_honestfutures15m.json` | **Binance USDT-M futures** | **futures trading only** | — |
| Weekly DCA | `crypto-dca.timer` → `dca_executor.py` | Binance spot | spot buy only | `DCA_LIVE_ENABLED=true` |
| **Event DCA** | `crypto-event-dca.service` → `event_dca_bot.py` | Binance spot | spot buy only | `DCA_LIVE_ENABLED=true` |

---

## Phase 1: Dry-Run Validation (each component independent, minimum 2-4 weeks)

All components must first pass the following thresholds in dry-run:

### HonestTrend15mDry / HonestTrend1mMTF (spot long-only)
- [ ] Cumulative ≥ 20 trades (statistical significance)
- [ ] Rolling PF ≥ 1.2
- [ ] Max DD < 12% (A5 backtest 14.77%, dry-run should be similar or better)
- [ ] 0 RETIRED events
- [ ] Walk-forward monthly check at least 4/8 windows positive

### HonestTrendFutures (futures long+short)
- [ ] Cumulative ≥ 30 trades (L+S has higher frequency)
- [ ] Long / Short ratio between 30-50% (proves short signals actually fired)
- [ ] Funding rate actual cost ≤ 6% annualized (backtest ~4%, leave margin)
- [ ] Max DD < 10% (backtest 7.84%)
- [ ] Stoploss -8% trigger frequency ≤ 5%/month
- [ ] Walk-forward 5/6 windows positive (validated W5 LUNA-type scenario)

### Smart DCA (both channels)
- [ ] At least 1 Monday trigger (next Monday `journalctl --user -u crypto-dca.service`)
- [ ] Telegram push works, FnG/cycle multipliers look reasonable
- [ ] Event channel fires at least 1-2 times (or skip this item if the market is quiet for 1 month)
- [ ] Supabase `dca_log` table has records

---

## Phase 2: Prepare Live Keys

### 2.1 Spot strategies + DCA (share one set of spot API keys)

Binance API key setup: https://www.binance.com/en/my/settings/api-management

- [ ] Permissions: **only** enable Spot Trading
- [ ] Permissions: **disable** Withdrawals / Margin / Lending
- [ ] IP allowlist: server public IP
- [ ] Add to SOPS:
  ```bash
  sops edit secrets.env
  # Add:
  # BINANCE_API_KEY=<key>
  # BINANCE_API_SECRET=<secret>
  ```

### 2.2 Futures strategy (**separate** API key)

**You must create a separate API key — do not reuse the spot one** (security isolation + Binance permission separation):

- [ ] Create a new Binance API key, **only** enable Futures Trading
- [ ] **Disable** Spot / Withdrawals / Margin
- [ ] IP allowlist same as above
- [ ] Add to SOPS:
  ```bash
  sops edit secrets.env
  # Add:
  # BINANCE_FUTURES_API_KEY=<key>
  # BINANCE_FUTURES_API_SECRET=<secret>
  ```
- [ ] Copy `config_dryrun_honestfutures15m.json` to `config_live_honestfutures15m.json`, `dry_run: false`
- [ ] Update `start_honest_trend.sh`'s `start_futures` function to inject futures keys

### 2.3 DCA live flag

- [ ] Add `DCA_LIVE_ENABLED=true` to SOPS `secrets.env` (**both DCA channels share this flag**)

---

## Phase 3: Capital Allocation

```
Total capital: 100,000 USDT

Allocation (Phase A/B architecture):
  Spot wallet (ETH/BNB/SOL trend + DCA accumulate BTC):  60,000 USDT
    ├─ Trend bots shared: 10,000 USDT (3 bots × 3,500 USDT avg)
    ├─ DCA accumulation (weekly + event):  50,000 USDT (accumulating)
    │
  Futures wallet (isolated, small-sized trial):  5,000 USDT
    └─ HonestTrendFutures L+S

  Stablecoin yield:                              25,000 USDT
  Reserve (do not touch):                        10,000 USDT
```

**Principles**:
- Futures starts at 5,000 USDT (backtest DD 7.84% → worst-case loss ~$400); add only after proving stable for 2 months
- Trend starts at 10,000 USDT (original allocated amount)
- DCA weekly DCA $500 base × 3.0 max = $1500/week max → ~$26K/year budget (leaves the 50K pool to accumulate slowly over 1.9 years)

---

## Phase 4: Go-Live Order (**roll out in batches; do not turn on all at once**)

### Batch 1 (Week 1-2): Spot trend bots
```bash
# 1. Start 15m spot live
./scripts/start_honest_trend.sh live    # old 1m live path, or write a new 15m live launcher
```
- Observe for 2 weeks, check Telegram daily
- Confirm live vs dry-run P&L differs < 1% / week

### Batch 2 (Week 3): Weekly DCA go-live
```bash
sops edit secrets.env
# Add DCA_LIVE_ENABLED=true
# Restart crypto-dca.timer (auto-fires next Monday)
```
- On first trigger, manually monitor once; verify Binance actual fills vs Telegram preview

### Batch 3 (Week 5): Event DCA go-live
```bash
# DCA_LIVE_ENABLED already set, just restart event daemon
systemctl --user restart crypto-event-dca.service
```
- Wait for an actual crash trigger (may take several weeks)
- After first trigger, check: were cooldown / monthly budget really deducted?

### Batch 4 (Week 7 or later): Futures L+S go-live

**This is the most dangerous step.** The following must be met first:
- [ ] All of batches 1-3 stable ≥ 2 weeks
- [ ] Futures API key tested (read-only)
- [ ] You know the liquidation price (1x leverage will not liquidate, but stoploss -8% will eat it)
- [ ] Transferred 5,000 USDT into the Binance futures wallet

```bash
# Start (assuming config_live_honestfutures15m.json is prepared)
./scripts/start_honest_trend.sh futures-live    # need to add this mode first
```

---

## Phase 5: Continuous Monitoring (Forever)

### Daily (Telegram is enough)
- [ ] Heartbeat present for all 3 bots
- [ ] No RETIRED alerts
- [ ] Funding rate notifications (if any)
- [ ] Event DCA trigger notifications (if any)

### Weekly
- [ ] Check DD and PF with `risk_monitor.py status`
- [ ] Compare this week's dry-run vs live actual fills (slippage / latency)
- [ ] Check `event_dca_state.json` monthly budget usage for Event DCA

### Monthly
- [ ] Walk-forward monthly validation (runs automatically via `crypto-walkforward.timer`)
- [ ] Futures funding cumulative cost (actual vs backtest expected 4%)
- [ ] Equity curve vs market comparison (Phase B should outperform in bear markets)

---

## Emergency Procedures

### Global Emergency Stop
```bash
./emergency_stop.sh
```
Kills all `freqtrade trade` processes + stops timers + Telegram alert. **Note**: event_dca daemon must be stopped separately:
```bash
systemctl --user stop crypto-event-dca.service
```

### Stop a Specific Bot Only
```bash
# Stop only futures (keep spot)
pkill -TERM -f "config_dryrun_honestfutures15m"

# Stop only event DCA (keep weekly DCA)
systemctl --user stop crypto-event-dca.service
```

### Block New Entries, Keep Existing
```bash
# Via API (each bot independent)
curl -X POST http://127.0.0.1:8082/api/v1/stopentry  # spot 15m
curl -X POST http://127.0.0.1:8084/api/v1/stopentry  # futures

# Or Telegram /stopentry (will be sent to all bots with the token)
```

### Force-Close All Futures Positions
```bash
# Telegram to HonestTrendFutures:
# /forceexit all
# Or go directly to the Binance futures UI and market-close everything
```

---

## Risk Rules (Hard Rules, No Bypass)

| Rule | Limit | Enforced By |
|------|------|---------|
| Max open trades per bot | 3 | config `max_open_trades` |
| Max per-position | 1,500 USDT × pyramid 2.6 = 3,900 USDT | config `stake_amount` + pyramid |
| Account max DD | 15% → PAUSE, 20% → RETIRE | `risk_manager.py` |
| **Futures leverage** | **1x (never exceed 2x)** | `HonestTrendFutures.leverage() → 1.0` |
| Futures stoploss | **−8%** (hard stop) | `HonestTrendFutures.stoploss = -0.08` |
| Short FnG filter | FnG > 70 blocks shorts | `HonestTrendFutures.FNG_SHORT_BLOCK` |
| DCA monthly budget | Weekly $500 × 3x max / Event $2000/month | env vars + executor clamp |
| DCA cooldown | Event 72h, max 3 times per month | `event_dca_state.json` |
| Spot stoploss | None (`-0.99`), signal-driven exits | IStrategy `stoploss = -0.99` |

---

## What NOT to Do

- ❌ **Do not go live with all 4 components on the same day** — batch it, observe each batch ≥ 2 weeks
- ❌ **Do not give the futures API key spot permissions** — isolation is the first line of defense
- ❌ **Do not skip the `DCA_LIVE_ENABLED` lock** — it was added to the code specifically to prevent accidental triggers
- ❌ **Do not manually edit strategy parameters while live** — if you want to tune, go back to dry-run first
- ❌ **Do not raise futures leverage to 2x+** — backtest DD 7.84%, 2x means 15.7%, leaving only 4 ppt margin to the 20% kill-switch
- ❌ **Do not override the FnG short filter** — shorting FOMO tops like 2021 Q4 will get you flattened
- ❌ **Do not manually close positions and restart the bot** — the bot will re-enter, you just waste fees
- ❌ **Do not run multiple live spot bots on the same Binance account** (futures is OK because positions are isolated)

---

## Next Steps After Transition

- **Phase B+1**: Futures 2x leverage (requires re-running walk-forward to verify W5 LUNA does not blow up)
- **Phase B+2**: Funding rate filter (avoid shorting when funding is high)
- **Deribit Phase 2**: Upgrade from monitoring to auto-writing CSP options
- **V5**: Event DCA for ETH / SOL (currently BTC-only)

All of the above wait until the current 4 components have been live-stable for 3+ months.
