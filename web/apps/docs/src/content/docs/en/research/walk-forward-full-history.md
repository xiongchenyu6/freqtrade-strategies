---
title: "8-regime Walk-Forward"
description: "WALK_FORWARD_FULL_HISTORY"
---

# Full-History Walk-Forward Validation

Cross-regime walk-forward test of `HonestTrend15mDry` on BTC/USDT + ETH/USDT (15m timeframe) across 8 fundamentally distinct market regimes, using data pulled from `data.binance.vision` going back to **2017-08-17** (Binance USDT first day).

**Last run:** 2026-04-21 (post pyramid adoption)
**Strategy:** `HonestTrend15mDry` (EMA 94/139 + ADX 18 + FnG gate + pyramid winners)
**Pairs:** BTC/USDT, ETH/USDT
**Timeframe:** 15m
**Capital:** 10,000 USDT simulated, stake_amount=1500, max_open_trades=3
**Fees:** 0.1% (realistic worst case)

## Results — BTC/USDT + ETH/USDT (core pair)

| # | Window | Regime | Trades | Total % | Pass? |
|---|--------|--------|--------|---------|:-----:|
| W1 | 2018-01 → 2018-12 | 2018 crash (BTC −72%) | 53 | **−14.43%** | No |
| W2 | 2019-01 → 2019-12 | Accumulation / recovery | 70 | +9.57% | Yes |
| W3 | 2020-01 → 2020-12 | COVID crash + recovery | 60 | +46.88% | Yes |
| W4 | 2021-01 → 2021-12 | Bull top (BTC $69K) | 70 | +34.77% | Yes |
| W5 | 2022-01 → 2022-12 | LUNA + FTX (BTC −64%) | 65 | −4.83% | No |
| W6 | 2023-01 → 2023-12 | Recovery / chop | 78 | +4.72% | Yes |
| W7 | 2024-01 → 2024-12 | ETF bull + halving | 63 | +44.69% | Yes |
| W8 | 2025-01 → 2026-04 | Present | 88 | **−4.00%** | No |
|    |                   | **Total** | **547** | **avg +14.68%** | **5/8** |

**Profitable windows: 5 / 8** (threshold: ≥ 5/8 = statistical edge)

## Results — BTC/ETH/BNB/XRP (4-pair extension, pyramid enabled)

| # | Window | Trades | Total % | Pass? |
|---|--------|--------|---------|:-----:|
| W1 | 2018 crash | 111 | **+13.00%** | Yes |
| W2 | 2019 accumulation | 154 | −0.64% | No |
| W3 | 2020 COVID | 110 | +59.88% | Yes |
| W4 | 2021 bull top | 125 | +111.96% | Yes |
| W5 | 2022 LUNA/FTX | 128 | −21.98% | No |
| W6 | 2023 recovery | 157 | +3.81% | Yes |
| W7 | 2024 ETF bull | 119 | +63.71% | Yes |
| W8 | 2025 present | 178 | −1.36% | No |
|    | **Total** | **1082** | avg +28.5% | **5/8** |

**Profitable windows: 5 / 8** — pyramid + stake=1500 even **flipped the 2018 window to positive** (+13%).

## New vs old config comparison (core insight of this rerun)

| Metric | Old (stake unlimited, no pyramid) | New (stake=1500, pyramid enabled) | Change |
|------|------:|------:|------:|
| Full-history total profit | +954% | +195% | halved in absolute (per-trade capital halved) |
| Full-history max DD | 26.1% | **16.9%** | **−9.2 ppt** |
| BTC+ETH W1 2018 loss | −30.6% | **−14.4%** | halved |
| BTC+ETH+BNB+XRP W1 2018 | −23.6% | **+13.0%** | **flipped positive** |
| 2-pair profitable windows | 6/8 | 5/8 | −1 (W8 flipped negative) |
| 4-pair profitable windows | 4/8 | **5/8** | **+1** |

**Fundamental shift**: pyramid + fixed stake converts the strategy from "high return high risk" to "medium return low risk".

**Biggest value**: max DD dropped from 26% → 17%, meaning under the `risk_manager` 20% kill-switch threshold the strategy **will almost never be retired**. The cost is smaller absolute per-trade return — if you want the old aggressiveness back, raise `stake_amount` to a larger value (e.g. 2500-3000).

## Interpretation

### Yes — 2 pairs (BTC+ETH) = real edge
Strategy is profitable in **6 different market structures**:
- Strong bull (2020 COVID +97%, 2024 ETF bull +89%, 2021 top +60%)
- Accumulation (2019 +9.6%)
- Chop / slow recovery (2023 +4%, 2025 +2.3%)

### No — adding BNB/XRP dilutes the edge
After expanding to 4 pairs, W2 (2019) and W8 (2025) flipped from positive to negative, dragging the profitable ratio from **6/8 down to 4/8**. Reasons:
- **BNB is highly correlated with BTC but has worse signal quality**: Binance's ecosystem token, price is influenced by exchange actions (buyback/burn/new listing announcements), trend signals get repeatedly interrupted by non-market factors
- **XRP is the regulatory coin**: during the 2020-2023 SEC lawsuit, price drivers were non-technical, trend-following was guaranteed to get hit
- **Over-diversification**: with `max_open_trades=3`, XRP/BNB steal slots that should have gone to BTC/ETH

### No — losses concentrated in "back-to-back crash years"
- **2018** (−30.6%): BTC annual −72%, any trend strategy gets whipsawed repeatedly
- **2022** (−8.3%): LUNA + FTX double blow-up, whole year down without sustained up-legs
- This environment needs a **regime filter** — `HonestTrend1mMTF` uses 4h EMA as a gate, does not open positions in clearly downtrending structures

### Edge realness assessment (new config)

| Dimension | Result |
|------|------|
| Profitable windows / total | **5 / 8 = 62.5%** (≥ 5/8 minimum threshold) |
| Full-history worst drawdown | **16.9%** (was 26.1%) |
| Worst year | W1 2018 −14.4% (market −72%) |
| Best year | W3 2020 COVID +46.9% |
| Stage 1 (parameter stability) | Robust near pyramid thresholds 5/12/60 |
| Stage 2 (cross-regime consistency) | 5 regimes profitable |
| Stage 3 (bear resilience) | 2018 loss compressed from −30.6% to −14.4% |

**Conclusion**: `HonestTrend + pyramid + small position` edge still exists, and **drawdown control is better than the old config**. W8 (2025-present) negative return needs continued observation — could be a new regime precursor.

## Product recommendations

1. **Live trade only BTC/USDT + ETH/USDT**
   This is the clearest conclusion of this walk-forward. Adding more pairs = diluting edge. Set aside the "diversification" instinct, the data says what it says.

2. **Make regime filter a first-class citizen**
   `HonestTrend1mMTF` already introduced 4h EMA as a gate. Suggested next version:
   - If 4h EMA 96 < 4h EMA 288 for > 7 consecutive days → pause new 1m/15m entries
   - Sacrifice a few rebound opportunities in W1 / W5, but avoid 2/3 of the drawdowns

3. **Keep kill-switch threshold at 20%**
   W1 −30.6% is an annual number; broken down by month/quarter, the worst drawdown segment should be < 20%. The current `risk_manager.py` 20% threshold is reasonable.

4. **Watch W8 (2025-present)**
   BTC+ETH only +2.31%, 4-pair version is still negative −3.85% — could be an early signal of market entering a new regime. Recommend rerunning this walk-forward monthly.

5. **Don't build dedicated strategies for XRP/BNB**
   These coins don't fit pure technical trend strategies. If you want to trade them, you need to introduce on-chain/sentiment/event-driven signals (this project's `sentiment_snapshots` and `kol_events` are built for that).

## Reproduce

```bash
# 1. Pull historical data (~20 min)
scripts/download_bulk_binance.sh BTCUSDT 15m 2017-08
scripts/download_bulk_binance.sh ETHUSDT 15m 2017-08

# 2. Run walk-forward (~2 min)
python scripts/walk_forward_full_history.py \
  --strategy HonestTrend15mDry \
  --timeframe 15m \
  --config configs/backtest/config_backtest_15m_btceth.json
```

JSON archived at `walk_forward_history/full_history_HonestTrend15mDry_15m_<date>.json`, usable for historical comparisons.

## References

- [`HONEST_TREND_REPORT.md`](HONEST_TREND_REPORT.md) — Full Stage 1-3 strategy validation
- [`DRYRUN_HANDBOOK.md`](DRYRUN_HANDBOOK.md) — Operations
- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) — System architecture
