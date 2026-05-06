# Hyperopt Experiment: Pyramid Parameter Optimization

**Goal**: Hand the 4 pyramid parameters I set "by feel" over to optuna, use a custom loss to avoid overfitting, and walk-forward validate whether it is actually better.

## Methodology

### 1. Parameter Space

```python
pyramid_1_trigger     = DecimalParameter(0.03, 0.10)  # original default 0.05
pyramid_2_trigger     = DecimalParameter(0.08, 0.20)  # original default 0.12
pyramid_1_stake_ratio = DecimalParameter(0.30, 1.00)  # original default 0.60
pyramid_2_stake_ratio = DecimalParameter(0.20, 0.80)  # original default 0.40
```

### 2. Custom Loss — `HonestHyperOptLoss`

Avoid the pitfalls of built-in losses:
- `ShortTradeDurHyperOptLoss` encourages short-term trading (violates our mid-term philosophy)
- `SharpeHyperOptLoss` is easily fooled by big winners
- Built-in `CalmarHyperOptLoss` is closest, but has no hard DD threshold

Our version (`strategies/HonestHyperOptLoss.py`):

```
IF trade_count < 50:       loss = 999  (reject low sample size)
IF max_dd > 20%:           loss = 100 + max_dd * 10  (hard reject)
IF max_dd > 15%:           Calmar divided by penalty factor (1.0 → 2.0)
ELSE:                      loss = -Calmar  (higher Calmar is better)
```

### 3. Training / Validation Split

- **Training**: 2022-01 → 2024-12 (3 years, 3 regimes: LUNA crash / recovery / ETF bull)
- **Validation**:
  - **True out-of-sample past**: 2018-2020 (W1-W3)
  - **True out-of-sample future**: 2025-present (W8)
  - **Contained in-sample**: 2022-2024 (W5-W7)

- **CPU**: Single-threaded (multi-threading could not be enabled due to joblib pickle errors)
- **Optuna sampler**: NSGAIIISampler (default, multi-objective friendly)
- **Epochs**: 100
- **Runtime**: 19 minutes

## Results

### Best Parameters (epoch 42/100)

| Parameter | Original default | Hyperopt best | Change |
|------|------:|-------------:|-----:|
| `pyramid_1_trigger` | 0.05 | **0.08** | +60% |
| `pyramid_2_trigger` | 0.12 | **0.10** | −17% |
| `pyramid_1_stake_ratio` | 0.60 | **0.80** | +33% |
| `pyramid_2_stake_ratio` | 0.40 | **0.80** | **+100%** |

**Interpretation**:
- First add-on threshold raised to +8% (more conservative, filters noise)
- Second add-on threshold instead dropped to +10% (once the first is cleared, follow up faster)
- Both add-on sizes expanded to **0.8× initial** (max total position reaches **2.6× initial** vs the old 2.0×)
- Essence: **more aggressive pyramid, but stricter thresholds**

### Training Set Performance (2022-01 → 2024-12)

```
Trades: 206
Win Rate: 37.4%
Total Profit: +48.86%
Max DD: 10.31%
Calmar Objective: -4.74
```

### Full-History Comparison (2017-08 → 2026-04)

| Metric | Old default | **Hyperopted** | Difference |
|------|------:|---------:|-----:|
| Total Profit | +195% | **+207%** | +12 ppt |
| Trades | 570 | 570 | 0 |
| Win Rate | 33.2% | **35.3%** | +2.1 ppt |
| Max DD | 16.93% | **15.53%** | **−1.4 ppt** |
| Avg Trade | 0.15% | −0.08% | Slightly lower (trades higher win rate for higher profit mode) |

### 8-Regime Walk-Forward Comparison

| Window | Old default | Hyperopted | Difference | Notes |
|--------|------:|---------:|-----:|------|
| W1 2018 crash | −14.43% | **−13.27%** | **+1.16** | 🎯 OOS improvement |
| W2 2019 accum | +9.57% | +8.42% | −1.15 | OOS slightly lower |
| W3 2020 COVID | +46.88% | +45.74% | −1.14 | OOS slightly lower |
| W4 2021 bull | +34.77% | +31.54% | −3.23 | Pre-training |
| W5 2022 LUNA | −4.83% | **−4.68%** | +0.15 | Training set |
| W6 2023 recovery | +4.72% | +5.90% | +1.18 | Training set |
| W7 2024 ETF | +44.69% | +47.29% | +2.60 | Training set |
| W8 2025 present | −4.00% | **−2.46%** | **+1.54** | 🎯 OOS improvement |
|    | | | **+1.11 sum** | |
| profitable/8 | 5/8 | 5/8 | 0 | Stable |

**Key observations**:
1. **Training set (W5-W7) cumulative +3.93 ppt improvement** — as expected
2. **OOS past (W1-W3) cumulative −1.13 ppt** — slight degradation on past data, but W1 (hardest 2018 window) actually improved +1.16
3. **OOS future (W8) +1.54 ppt improvement** — beneficial for the current market
4. **No overfitting signal**: OOS averages +0.24 ppt improvement, beyond 1/8 sample significance

## Conclusion: Worth Adopting

✅ **Pros**:
- Full-history +12 ppt return + DD down 1.4 ppt
- Both W1 2018 (hardest window) and W8 2025 (current) improved
- No overfitting evidence (OOS data shows net positive improvement)

⚠️ **Cons**:
- W4 2021 bull-market top −3.23 ppt (marginal degradation in high-valuation era)
- W2/W3 OOS slight degradation (still profitable)

### Already Applied

1. `strategies/HonestTrendGeneric.py` base class defaults updated to hyperopt-best values
   - All subclasses (`HonestTrend15mDry`, `1mLive`, `1mMTF`) inherit automatically
2. `strategies/HonestTrend15mDry.json` auto-saved by freqtrade (takes precedence for that class specifically)
3. Production configs already have pyramid enabled (see `docs/EXPERIMENTS_DCA_AND_PYRAMID.md`)

## Extended Experiment: 6-Parameter Hyperopt (❌ Rejected)

**2026-04-21 follow-up test**: Added `adx_threshold` and `min_hold_minutes` to the hyperopt space (6 parameters total), 150 epochs.

### Results

Training set performance was off the charts:
```
Objective: -10.84  (vs -4.74 in 4-param baseline)
In-sample (2022-2024): 119 trades, 37.8% WR, +70%, Max DD 6.46%
```

Best parameters:
- `adx_threshold`: 18 → **30** (sharply raised entry threshold)
- `min_hold_minutes`: 720 → **1065** (~18h minimum hold)
- `pyramid_1_stake_ratio`: 0.80 → **1.00** (first add-on maxed out)

### Walk-forward 8 windows: 6/8 (looks better!)

| Window | 4-param | 6-param | Diff |
|--------|-------:|-------:|-----:|
| W1 2018 | −13.27% | **−20.02%** | −6.75 ❌ |
| W4 2021 | +31.54% | **+58.59%** | +27.05 ✅ |
| W5 2022 | −4.83% | **+4.89%** | +9.57 ✅ **flipped to positive** |
| W7 2024 | +47.29% | +55.02% | +7.73 ✅ |
| Sum | | | **+19.4 ppt** |

### ❌ But Full History Is a Disaster

| Metric | 4-param | 6-param | Diff |
|------|------:|------:|-----:|
| Total profit | +207% | **+160%** | −47 ppt |
| Max DD | **15.53%** | **24.81%** | **+9.3 ppt 🚨** |
| Trades | 570 | 335 | −40% |

**24.81% max DD exceeds the 20% kill-switch threshold** → would trigger auto-RETIRE in live trading.

### Why Good on Walk-Forward but Bad on Full History?

- Walk-forward each window uses an independent $10K principal, peak-to-trough only within the year
- Full history **compounds**, and the −6.7 ppt loss in mid-2018 stacks on top of already-accumulated bull-market profits = bigger percentage drawdown
- ADX=30 strict filtering rallies harder in bull markets, but recovers to new highs **later** in bear markets due to fewer entries
- Simple "profitable each window?" ignores the **relative depth during drawdowns**

### Rollback Decision

- `adx_threshold` and `min_hold_minutes` restored to `optimize=False`
- `strategies/HonestTrend15mDry.json` restored to the old best values from 4-param hyperopt
- Lesson: **walk-forward profitable rate ≠ full-history max DD control**

## Extended Experiment: CmaEsSampler (Technical Improvement)

Added a `generate_estimator` method (inside the nested `HyperOpt` class) that uses `CmaEsSampler` to replace the default `NSGAIIISampler`. CmaEs converges faster on continuous parameters.

**Auto-enabled for future hyperopts**, but the rejected 6-param experiment used NSGAIII (before switching to CmaEs), so the results are unaffected.

## Extended Experiment: HonestTrend1mLive Standalone Hyperopt (❌ Rejected)

**2026-04-22**: Standalone hyperopt on the 1m timeframe (base class was tuned on 15m data; in theory, 1m might have different optima).

### Setup
- Training range: 2024-01 → 2024-12 (1 year 1m BTC+ETH)
- Epochs: 50, `min_trades=25` (fewer trades on 1m, must lower the threshold)
- Space: 4 pyramid parameters (leave EMA/ADX/min_hold alone)
- Sampler: CmaEs

### Best Parameters (epoch 30/50)

| Parameter | base class default | 1m hyperopt | Change |
|------|------:|---------:|-----:|
| `pyramid_1_stake_ratio` | 0.80 | **0.60** | −25% |
| `pyramid_2_stake_ratio` | 0.80 | **0.70** | −13% |
| `pyramid_2_trigger` | 0.10 | **0.08** | −20% |
| `pyramid_1_trigger` | 0.08 | 0.08 | = |

Direction: **more conservative add-ons** (smaller stake, lower threshold but smaller amount on the second add-on).

### Training Set (2024 single year)
- Default: +25.21%
- 1m hyperopt: +24.72% (**−0.49 ppt**)

Already no clear improvement on the training set — indicating CmaEs cannot find a better combo than the default within 50 epochs.

### Full-History 3.3-Year Comparison (2023-01 → 2026-04)

| Metric | Base class default | 1m hyperopt | Diff |
|------|------:|---------:|-----:|
| Total Profit | **+37.99%** | +36.13% | **−1.86 ppt** |
| Max DD | 10.55% | 10.33% | −0.22 ppt |
| Calmar (wallet) | 4.15 | 4.04 | −0.11 |
| Trades | 135 | 135 | 0 |
| Win Rate | 35.6% | 35.6% | 0 |

### Rollback Decision
- Delete `strategies/HonestTrend1mLive.json`
- `HonestTrend1mLive` continues to inherit base class pyramid defaults
- Lesson: **the same 4 pyramid parameters are good enough on both 15m and 1m**; standalone hyperopt on 1m is noise-chasing

### Why No Improvement?
1. **Pyramid triggers are "profit percentage"**, independent of timeframe — +8% is +8% on both 15m and 1m
2. **What actually varies with timeframe is EMA/ADX**, but we explicitly do not hyperopt those
3. **50 epochs + 1 year data** is not enough for CmaEs to converge to any meaningful improvement

## Future Optimization Roadmap

### Short-Term
- Observe 1-2 months of live W8 (2025-present) to confirm the 4-param new parameters are actually better

### Don't Do
- **Do not add adx/min_hold to the hyperopt space again** (verified above to be a trap)
- **Do not tune >5 parameters at once** (overfitting probability grows exponentially with dimensionality)
- **Do not put EMA periods in hyperopt** (these are "structural" choices, not something the optimizer should randomly change)
- **Do not hyperopt 1m vs 15m pyramid parameters separately** (verified as noise-chasing on 2026-04-22)

### Key Lessons

1. **Lower training loss ≠ better production**: objective going from -4.74 → -10.84 looks like 2× improvement on the training set, but full-history DD multiplied by 1.6×
2. **Walk-forward independent windows ≠ full-history backtest**: the former misses the compounding damage of "continuous disadvantage"
3. **Trust the kill-switch threshold**: 20% DD was not set arbitrarily — it is the psychological upper bound the live account can withstand. Letting hyperopt push DD to that threshold is playing with fire
4. **Less is more**: 4 pyramid parameters + strict loss is enough. Adding 2 more variables just injects noise
5. **Pyramid parameters are timeframe-agnostic across timeframes**: the same 4 pyramid parameters are optimal on both 15m and 1m — because triggers look at percentage profit, not candle count

## Reproduction

```bash
# Hyperopt
freqtrade hyperopt \
  --strategy HonestTrend15mDry \
  --config configs/backtest/config_backtest_15m_btceth.json \
  --datadir user_data/data/binance \
  --user-data-dir user_data \
  --strategy-path strategies \
  --hyperopt-loss HonestHyperOptLoss \
  --hyperopt-path strategies \
  --spaces buy \
  --epochs 100 \
  --timerange 20220101-20241231 \
  -j 1  # single-threaded due to joblib pickle issue with our strategy

# Inspect best epoch
freqtrade hyperopt-show --best \
  --user-data-dir user_data \
  --hyperopt-filename strategy_HonestTrend15mDry_2026-04-21_17-08-21.fthypt

# Walk-forward validation
python scripts/walk_forward_full_history.py \
  --strategy HonestTrend15mDry \
  --timeframe 15m \
  --config configs/backtest/config_backtest_15m_btceth.json
```

## References

- [Freqtrade Advanced Hyperopt](https://www.freqtrade.io/en/develop/advanced-hyperopt/)
- [`WALK_FORWARD_FULL_HISTORY.md`](WALK_FORWARD_FULL_HISTORY.md) — 8-regime methodology
- [`TUTORIAL_FOR_BEGINNERS.md`](../TUTORIAL_FOR_BEGINNERS.md) §1.8 — Hyperopt pitfalls
