# Experiment Report: Aggressive DCA and Trend-Strategy Pyramid Winners

Two independent enhancement experiments, both representing the correct form of "add to position on crash / add to position on profit".

---

## Experiment A: Aggressive DCA (FnG < 10 → 3× multiplier)

**Hypothesis**: The current DCA already uses a 2× multiplier when FnG < 20. Would being a bit more aggressive (FnG < 10 → 3×, cap 3.0) accumulate more BTC at a lower average cost?

### Method

- Time range: 2018-02-01 → 2026-04-17 (from the start of FnG data to the present)
- Base amount: **$500/week**, buy every Monday
- Cycle factor proxy: **Mayer Multiple** (price / 200-day MA) mapped to [-1, +1]
- Script: `scripts/backtest_dca.py`

### Comparison across 4 schemes

| Scheme | Total Spent (USDT) | BTC Acquired | Avg Cost ($/BTC) | Portfolio Value (USDT) | PnL % | Extra vs Flat % |
|------|------------:|----------:|----------------:|---------------:|------:|---------------:|
| **A. Flat $500/wk** (baseline) | 214,000 | 13.75 | **$15,569** | $1,022,877 | +378% | 0% |
| **B. Current formula** (cycle 50% + FnG 30%) | 328,200 | 22.00 | $14,918 | $1,637,210 | +399% | **+60.1%** |
| **C. Aggressive** (FnG<10→3x, cap 3x) | 356,812 | 24.52 | **$14,549** | **$1,825,060** | +412% | **+78.4%** |
| **D. FnG-only** linear | 250,461 | 17.48 | $14,332 | $1,300,496 | **+419%** | +27.1% |

### Conclusions

1. **Aggressive scheme (C) wins on absolute return**: $1.82M, **+78%** over baseline
2. **FnG-only (D) is the most efficient**: +419% return per dollar, but lower absolute amount because it invests less
3. **Current formula (B) is already decent**: +60% vs flat. Upgrading to (C) adds another +18%
4. **"Cost" of the aggressive scheme**: $142,812 more spent (vs baseline), but $802,183 more earned → **incremental ROI = 5.6×**

### Why is being aggressive effective?

- **FnG < 10 is extremely rare** (only ~30 weeks across 8 years), so overcapitalization is not sustained long term
- These moments are very likely **cycle bottoms** (2018-12, 2020-03 COVID, 2022-11 FTX)
- Buying in extreme fear = buying near local bottoms → lower average cost

### Recommendation

Adopt scheme C. Update `compute_multiplier` in `strategies/dca_executor.py`:

```python
if fng < 10:
    fng_mult = 3.0          # NEW
elif fng < 20:
    fng_mult = 2.2          # was 2.0
# ...
multiplier = ... * kol_bonus
multiplier = max(0.0, min(3.0, multiplier))  # cap raised from 2.5 to 3.0
```

### Visualizations
- `reports/dca_backtest/dca_comparison.html` — 4-scheme portfolio comparison + cumulative investment + average cost
- `reports/dca_backtest/multiplier_distribution.html` — multiplier frequency distribution per scheme

---

## Experiment B: HonestTrend Pyramid Winners

**Hypothesis**: The trend strategy currently enters each position only once. If we add to the position after **profit is confirmed** (pyramid winners, not martingale losers), can total return be improved?

### Method

**New strategy**: `strategies/HonestTrend15mPyramid.py`

```
Initial entry: EMA 94/139 golden cross + ADX > 18 + FnG < 80  (same as HonestTrend15mDry)
Pyramid 1: position profit ≥ +5%  → add 0.6× of initial size
Pyramid 2: position profit ≥ +12% → add 0.4× of initial size
Max total position: 2.0× initial (first 1.0 + 0.6 + 0.4)
Exit: EMA death cross (same as baseline)
Key rule: NEVER add to position on loss (this is not martingale)
```

Both runs use the same config (`configs/backtest/config_backtest_15m_pyramid.json`):
- `stake_amount: 3000` (fixed, leaves room for pyramid)
- `max_open_trades: 3`
- `position_adjustment_enable: true` (enabled for pyramid version)

### Comparison results (2017-08-17 → 2026-04-20, BTC+ETH)

| Metric | Baseline 15mDry | Pyramid 15mPyramid | Difference |
|------|--------------:|------------------:|-------:|
| Trades | 570 | 570 | 0 |
| Win Rate | 38.2% | **33.2%** | **−5.0 ppt** |
| Total Profit (USDT) | $26,823 | **$37,782** | **+$10,959 (+41%)** |
| Total Profit % | +268% | **+378%** | **+110 ppt** |
| Avg Profit / trade | 1.20% | 0.15% | −1.05 ppt (because position is larger) |
| Max Drawdown | 25.50% | **24.03%** | **−1.5 ppt** |

### Why does Pyramid work?

- **Winners get bigger**: an average $1,439 winner gets scaled to an effective $2,000+ (initial $3K + 0.6× $3K added at +5% profit, then +0.4× at +12%)
- **Losers do not get bigger** (rule: only add on profit)
- **Win rate actually drops** (−5 ppt): some trades that were at +5–12% entered pyramid and then fell back below 0, counted as losers
- **But average win × number of wins > average loss × number of losses** still holds → net return increases

### Why does Max DD shrink?

Counter-intuitive but supported by the data:
- Pyramid is a "profit-contingent" add-on, mostly occurring during bull/rising phases
- Bull phases push the equity peak higher, so subsequent bear drawdowns start from a "higher base" — in percentage terms they are **smaller**
- And because we never add on losers, the worst-case downside is not amplified

### Adopted (2026-04-21) — Mode 2 aggressive integration

`adjust_trade_position` and `position_adjustment_enable = True` have been added directly to the `HonestTrendGeneric` base class. **All subclasses inherit automatically**:
- `HonestTrend15mDry` — active
- `HonestTrend1mLive` — active
- `HonestTrend1mMTF` — active

The 3 active configs have been updated:
- `configs/config_dryrun_honest15m.json`
- `configs/config_dryrun_honest1mmtf.json`
- `configs/config_live_honest1m.json`

Each config adds:
```json
"position_adjustment_enable": true,
"max_entry_position_adjustment": 2,
"stake_amount": 1500   // was "unlimited"
```

**stake_amount changed from "unlimited" to a fixed 1500** because:
- The original unlimited value would fill the entire wallet (3 trades × 3333 = 9999), leaving no room for pyramid
- The new value of 1500 leaves room for pyramid (a single trade can grow to 1500 + 900 + 600 = 3000; 3 parallel trades use at most 9000, with a 1000 buffer)
- **Before going live, be sure to scale this to your actual capital allocation for HonestTrend** (stake = dedicated_capital × 0.15)

The experimental files have been deleted:
- ~~`strategies/HonestTrend15mPyramid.py`~~ (merged into the base class)
- ~~`configs/backtest/config_backtest_15m_pyramid.json`~~ (equivalent to btceth)

### Visualizations
- `reports/pyramid/index.html` — full 7-panel dashboard
- Compare with `reports/full_history_btceth/index.html` (baseline)

---

## "Philosophical" distinction between the two experiments

| | Aggressive DCA | Pyramid Winners |
|--|---------|----------------|
| When to add | On crash / panic | On confirmed profit |
| Trigger condition | FnG / cycle undervaluation signal | Current position > +5% / +12% |
| Nature | **Contrarian trading** (buy more as it drops) | **Trend-following addition** (buy more as it rises) |
| Suitable for | Long-term accumulation (spot holdings) | Active trend strategy |
| Implementation location | `dca_executor.py` weekly timer | `HonestTrend15mPyramid.adjust_trade_position` |

The two **can coexist without conflict** because they act in **different market phases**:
- DCA adds at well-defined bear bottoms → buy for long-term accumulation
- Pyramid adds within a well-defined bullish trend → amplify the current trade

**Never mix them into "add on loss" (Martingale)** — that would destroy the benefits of both.

---

## Reproduction commands

```bash
# DCA experiment
python scripts/backtest_dca.py
# → reports/dca_backtest/summary.csv + *.html

# Pyramid experiment
freqtrade backtesting --strategy HonestTrend15mDry \
  --config configs/backtest/config_backtest_15m_pyramid.json \
  --datadir user_data/data/binance \
  --user-data-dir user_data \
  --strategy-path strategies \
  --timerange 20170817- --export signals

freqtrade backtesting --strategy HonestTrend15mPyramid \
  --config configs/backtest/config_backtest_15m_pyramid.json \
  --datadir user_data/data/binance \
  --user-data-dir user_data \
  --strategy-path strategies \
  --timerange 20170817- --export signals

python scripts/visualize_strategy.py --out reports/pyramid
```
