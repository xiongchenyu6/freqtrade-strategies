---
title: "Phase 3 optimization (archived)"
description: "OPTIMIZATION_PLAN"
---

# Strategy Optimization Plan — Phase 3 (COMPLETED)

## Final Results

| Step | Change | PF | Win% | DD | Status |
|---|---|---|---|---|---|
| Baseline | defaults | 2.47 | 37% | 25% | — |
| Step 1 | Remove LTC/ATOM/UNI/NEAR | 2.61 | 43% | 18% | Kept |
| Step 2 | Faster exit | 1.81 | — | 39% | Rejected (worse) |
| Step 3 | BTC reference pair | 2.68 | 46% | 18% | Kept |
| Step 4 | Hyperopt EMA 30/61 ADX 16 | **3.19** | **53%** | **17%** | Kept |

**Final optimized: PF 3.19, Win 53%, DD 17% — all significantly better than baseline.**

## Current Baseline (V1)
- 43 trades, +221%, PF 2.47, Max DD 25%, Win Rate 37%
- Winners avg +88%, Losers avg -13%
- Winners hold 109 days, Losers hold 36 days

## Problem Diagnosis

```
Loss source analysis:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Toxic pairs (~40% of total losses):
   LTC:  -52% (0/3 wins) ← never profits
   ATOM: -30% (0/3 wins) ← never profits
   UNI:  -24% (0/2 wins) ← never profits
   XRP:  -31% (1/4 wins) ← rarely profits

2. Exit too slow (~35% of total losses):
   7 trades lost -20% to -30%
   4 trades lost -15% to -20%
   → EMA 21/55 death cross is too slow, price already dropped a lot before exit

3. Parameters not optimized (potential upside):
   EMA 21/55 is the default, never ran hyperopt
   ADX 20 is the default
   → Could have better parameter combinations

4. Altcoin counter-trend entries (~25% of total losses):
   Altcoins still trigger entry signals while BTC is dropping
   → Need a BTC direction filter
```

## Optimization Steps

### Step 1: Remove Toxic Pairs — 5 min
**Goal**: Remove pairs that historically never profit
**Action**: Blacklist LTC, ATOM, UNI, NEAR from config
**Expected**: DD down 5-10%, PF up 0.2-0.3
**Risk**: May miss some future big move, but history shows these coins don't profit under our strategy

### Step 2: Faster Exit Signal — 30 min
**Goal**: Cut losers faster, keep winners running
**Action**: Add `custom_exit` with:
  - Time-based: if trade unprofitable after 30 days → exit
  - EMA slope: if EMA 21 slope turns negative while in trade → exit
  - Faster cross: use EMA 13/34 for exit (faster than 21/55)
**Expected**: Avg loser from -13% to -8%, DD down 5%
**Risk**: May exit early on trades that would have eventually profited

### Step 3: BTC Reference Pair — 30 min
**Goal**: Only enter altcoins when BTC trend agrees
**Action**: Add BTC/USDT as informative pair, require BTC EMA uptrend for altcoin entries
**Expected**: Fewer counter-trend altcoin entries, win rate up 3-5%
**Risk**: May miss independent altcoin moves

### Step 4: Hyperopt Parameter Tuning — 1 hour
**Goal**: Find optimal EMA periods, ADX threshold
**Action**: Run hyperopt with SharpeHyperOptLoss, 300 epochs
**Optimize**: ema_fast (10-30), ema_slow (40-80), adx_threshold (15-30)
**Expected**: PF could improve 20-30%
**Risk**: Overfitting. Validate with walk-forward.

### Validation
After each step, run full backtest + walk-forward to confirm improvement.
Only keep changes that improve BOTH total profit AND profit factor.
