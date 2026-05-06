---
title: "Phase B: futures hedge"
description: "PHASE_B_FUTURES_SHORT"
---

# Phase B: Futures Short Altcoin Hedge

**Date**: 2026-04-22
**Goal**: Building on Phase A (BTC handled by DCA, trend strategy only runs altcoins ETH/BNB/SOL), introduce **futures long+short** to hedge LUNA-grade bear risk with short positions.

## Strategy design

### `HonestTrendFutures` (extends `HonestTrendGeneric`)

```python
can_short = True
stoploss = -0.08              # Futures must have hard stoploss (spot can use -0.99)
FNG_SHORT_BLOCK = 70          # Block shorts when FnG > 70 (never short euphoria)
leverage = 1.0                # 1x, zero liquidation risk
```

**Short signals** (mirror long):
- `crossed_below(ema_fast, ema_slow)`
- `minus_di > plus_di`
- `adx > threshold`
- `volume > volume_sma`
- `fng < FNG_SHORT_BLOCK (70)` — critical filter, avoids short squeezes in bull markets

**Short exit**:
- `crossed_above(ema_fast, ema_slow)`

### Parameter inheritance (from `HonestTrendGeneric`)
EMA / ADX / min_hold / pyramid all inherited from the base class — **same parameter set runs long+short** (proven robust enough via WF validation).

## Backtest results

### Full history (2020-09-14 → 2026-04-21, 5.6 years)

| Metric | A5 spot long-only | **Futures L+S** | Δ |
|------|------:|--------:|------:|
| Trades | 559 | **901** (508L + 393S) | +342 |
| Profit | +166% | +157% | −9 ppt |
| Long profit | — | +107% | — |
| **Short profit** | — | **+50%** | — |
| **Max DD** | 14.77% | **7.84%** | **−6.93** |
| **Calmar** | 9.45 | **18.72** | **doubled** |
| Sortino | 1.66 | **2.56** | +0.9 |

### 8-Regime Walk-Forward

| Window | A5 Spot | **Futures L+S** | Δ |
|--------|--------:|--------:|------:|
| W1 2018 crash | +12.31% | n/a (no futures) | — |
| W2 2019 accum | +10.38% | n/a | — |
| W3 2020 COVID | +14.94% | +9.91% | −5.0 |
| W4 2021 bull | +143.30% | +91.20% | −52.1 |
| **W5 2022 LUNA** | **−16.93%** | **+47.62%** | **+64.6** |
| W6 2023 recovery | +18.27% | +18.71% | +0.4 |
| W7 2024 ETF | +23.79% | +17.15% | −6.6 |
| W8 2025 present | −1.23% | −6.43% | −5.2 |

**Key finding**: in 5/6 "normal" windows, shorts are a slight drag (funding cost + a few losing shorts); but in the **1/6 crisis window (2022 LUNA/FTX), shorts turned −17% into +48%** — a +65 ppt single-window tail-risk hedge.

### Insurance theory explanation

Treat shorts as **insurance with "~4 ppt annualized cost, 60+ ppt payout in bear markets"**. The premium looks expensive, but black-swan events repay it 10× over. This is exactly the payoff profile tail-risk hedging should have.

## Deployment

### Created
| File | Description |
|------|------|
| `strategies/HonestTrendFutures.py` | L+S strategy class |
| `configs/backtest/config_backtest_15m_futures_a5.json` | Backtest config |
| `configs/config_dryrun_honestfutures15m.json` | dry-run config, port 8084 |
| `scripts/start_honest_trend.sh` | Added `futures` and `all` modes |

### Startup
```bash
./scripts/start_honest_trend.sh futures   # start alone
./scripts/start_honest_trend.sh all       # run alongside dryrun + mtf
```

### Port allocation
- 8082 — HonestTrend15m (spot long-only, A5 alts)
- 8083 — HonestTrend1mMTF (spot 1m long-only)
- **8084 — HonestTrendFutures (futures L+S)**
- 8081 — live bot (1m, BTC+ETH+BNB, **old — not yet switched to A5**)

### Telegram
Enabled (injected via `FREQTRADE__TELEGRAM__TOKEN` env var) — will receive notifications from `HonestTrendFutures-DRYRUN` in the same chat.

## Observation checklist (dry-run 1-2 weeks)

- [ ] Funding rate real cost matches backtest (~4 ppt annualized)
- [ ] Short entries trigger in bear markets (FnG filter works correctly)
- [ ] Stoploss -8% is not frequently pierced by wicks/gaps
- [ ] 1x leverage truly has no liquidation risk
- [ ] Pyramid rules behave correctly on the short side
- [ ] Drawdown stays in the backtest 7.84% ballpark

## Future: Phase B+

### B+1. Leverage 2x (pending validation)
- DD 7.84% leaves 10+ ppt headroom to 20% kill-switch
- Theoretically 2x doubles profit
- But liquidation risk enters: a 20% wick with 2x leverage = liquidation
- **Recommendation**: after dry-run stable, backtest 2x first, walk-forward confirm W5 LUNA doesn't liquidate

### B+2. Strengthen shorts when FnG < 30
- Currently shorts allowed when FnG < 70, no distinction between 30 vs 60
- Could try: stake × 1.5 when FnG < 30 (panic-bottom short size-up)
- Risk: getting crushed on V-shaped reversals

### B+3. Funding rate filter
- Currently doesn't check funding rate
- Extremely high negative funding (shorts get extra penalized) should avoid opening shorts
- Could query last 8h funding in `confirm_trade_entry` and reject order if > threshold

### Not doing
- **No XRP/DOGE in altcoin futures pool** (backtests already showed these amplify DD in spot)
- **No BTC in futures pool** (BTC uses DCA, keep them separate)
- **No leverage above 2x** (1x→2x already doubles risk, 3x+ is gambling)

## Rollback path

If dry-run 2 weeks performs worse than backtest expectations (DD > 12% or short profit negative):
1. Stop futures bot: `pkill -f HonestTrendFutures` (emergency_stop.sh also takes it down)
2. Keep running A5 spot long-only (no short insurance)
3. Record failure reason, update the "failed experiments" section of this doc

## Key lessons (pending dry-run validation)

1. **Shorts don't earn in normal times, they save lives in crises**: drag in 5/6 windows, lifesaver in 1/6
2. **1x leverage is the "safest" futures starting point**: no liquidation, pure directional alpha
3. **FnG filter is critical**: allowing shorts at bull-top will get you squeezed beyond belief
4. **Funding is a hidden tax**: 4-10% annualized, most painful in ranging markets
