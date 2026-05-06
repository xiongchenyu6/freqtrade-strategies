---
title: "Phase 3 优化（归档）"
description: "OPTIMIZATION_PLAN"
---

# Strategy Optimization Plan — Phase 3 (COMPLETED)

## Final Results

| Step | Change | PF | Win% | DD | Status |
|---|---|---|---|---|---|
| Baseline | defaults | 2.47 | 37% | 25% | — |
| Step 1 | Remove LTC/ATOM/UNI/NEAR | 2.61 | 43% | 18% | ✅ Kept |
| Step 2 | Faster exit | 1.81 | — | 39% | ❌ Rejected (worse) |
| Step 3 | BTC reference pair | 2.68 | 46% | 18% | ✅ Kept |
| Step 4 | Hyperopt EMA 30/61 ADX 16 | **3.19** | **53%** | **17%** | ✅ Kept |

**Final optimized: PF 3.19, Win 53%, DD 17% — all significantly better than baseline.**

## Current Baseline (V1)
- 43 trades, +221%, PF 2.47, Max DD 25%, Win Rate 37%
- Winners avg +88%, Losers avg -13%
- Winners hold 109 days, Losers hold 36 days

## Problem Diagnosis

```
亏损来源分析:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 垃圾币对 (占总亏损 ~40%):
   LTC:  -52% (0/3 wins) ← 从不赚钱
   ATOM: -30% (0/3 wins) ← 从不赚钱
   UNI:  -24% (0/2 wins) ← 从不赚钱
   XRP:  -31% (1/4 wins) ← 极少赚钱

2. 出场太慢 (占总亏损 ~35%):
   7 笔交易亏 -20% 到 -30%
   4 笔交易亏 -15% 到 -20%
   → EMA 21/55 死叉太慢，价格已跌很多才出场

3. 参数未优化 (潜在收益):
   EMA 21/55 是默认值，从没跑过 hyperopt
   ADX 20 是默认值
   → 可能有更好的参数组合

4. Altcoin 逆势入场 (占总亏损 ~25%):
   BTC 下跌时 altcoin 仍在触发入场信号
   → 需要 BTC 方向过滤器
```

## Optimization Steps

### Step 1: Remove Toxic Pairs ⏱️ 5 min
**Goal**: Remove pairs that historically never profit
**Action**: Blacklist LTC, ATOM, UNI, NEAR from config
**Expected**: DD减少5-10%, PF提升0.2-0.3
**Risk**: 可能错过未来某次大行情，但历史证明这些币在我们策略下不赚钱

### Step 2: Faster Exit Signal ⏱️ 30 min
**Goal**: Cut losers faster, keep winners running
**Action**: Add `custom_exit` with:
  - Time-based: if trade unprofitable after 30 days → exit
  - EMA slope: if EMA 21 slope turns negative while in trade → exit
  - Faster cross: use EMA 13/34 for exit (faster than 21/55)
**Expected**: Avg loser from -13% to -8%, DD减少5%
**Risk**: 可能过早退出最终会盈利的交易

### Step 3: BTC Reference Pair ⏱️ 30 min
**Goal**: Only enter altcoins when BTC trend agrees
**Action**: Add BTC/USDT as informative pair, require BTC EMA uptrend for altcoin entries
**Expected**: 减少逆势 altcoin 入场，win rate提升3-5%
**Risk**: 可能错过 altcoin 独立行情

### Step 4: Hyperopt Parameter Tuning ⏱️ 1 hour
**Goal**: Find optimal EMA periods, ADX threshold
**Action**: Run hyperopt with SharpeHyperOptLoss, 300 epochs
**Optimize**: ema_fast (10-30), ema_slow (40-80), adx_threshold (15-30)
**Expected**: PF可能提升20-30%
**Risk**: 过拟合。用 walk-forward 验证。

### Validation
After each step, run full backtest + walk-forward to confirm improvement.
Only keep changes that improve BOTH total profit AND profit factor.
