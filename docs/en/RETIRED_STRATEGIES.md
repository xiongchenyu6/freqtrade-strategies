# Retired Strategies — Reasons & Lessons

> **2026-04-22 update**: Code has been deleted from `strategies/legacy/` + `configs_legacy/`.
> This document is the sole remaining retirement record — each entry explains **why it is not used** + **what the lesson is**.
> To revive anything, strictly follow the "Restoration Protocol" at the end.

The active deployed stack lives in `strategies/`. See
[`HONEST_TREND_REPORT.md`](HONEST_TREND_REPORT.md) for the full validation report.

---

## TL;DR — Patterns That Fooled Us

Every strategy here passed at least one of these "looks great" tests and
still failed in reality:

1. **In-sample PF > 3.0** → almost always overfit, 90% of the gap between IS
   and OOS is noise.
2. **Calmar > 20** → red flag, not a feature. Means the sample is too small
   to have hit a real drawdown yet.
3. **p-value < 0.0001 in-sample** → statistical significance on IS data is
   circular reasoning.
4. **Single OOS window profitable** → one lucky quarter can hide 4 losing
   quarters. **Always walk-forward.**
5. **"Contrarian at extremes" LLM prompts** → Claude sets contrarian=true 96%
   of the time regardless of prompt. Signal is random noise with extra steps.

---

## Sentiment / ML Family (overfit cluster)

### `SentimentTrend.py` — live-mode sentiment strategy with LLM signals

- **Why retired**: PF 6.86 in-sample collapsed to ~1.05 OOS.
- **What looked good**: combined hand-crafted FnG gate + LLM sentiment +
  reflective memory + BTC cycle indicators → 200+ features.
- **What actually happened**: feature importance analysis showed **LLM
  signal contributed 0%**. Redundant with FnG. Most "features" were noise
  that happened to correlate with price in 2024 bull market.
- **Lesson**: adding features ≠ adding edge. Always ablate.

### `SentimentTrendBT.py` / `SentimentTrendBT.json`

- **Why retired**: Backtestable version of `SentimentTrend.py`. Used historical
  FnG + reconstructed LLM outputs. Tested 6 variants (v1–v6), none had OOS edge.
- **Lesson**: historical sentiment reconstruction is a leaky abstraction.

### `SentimentUltimate.py`

- **Why retired**: Hand-crafted + FreqAI LightGBM classifier hybrid.
  In-sample PF 6.86 → OOS PF 1.05. Textbook overfitting.
- **Lesson**: ML on features with no a-priori economic thesis = noise-fit.

### `SentimentHybrid.py`

- **Why retired**: Earlier hybrid attempt. Never passed OOS.
- **Lesson**: you can't validate an ML model on the same data you trained it on.

### `SentimentRL.py` / `SentimentRL1h.py`

- **Why retired**: PPO/A2C reinforcement learning agents. Learned to
  "buy-and-hold with extra steps" in-sample. OOS: total loss, then gave up.
- **Lesson**: RL on small financial samples (few million ticks) overfits
  catastrophically. You'd need millions of episodes across many markets.

### `SentimentFreqAI.py` / `SentimentFreqAIClassifier.py`

- **Why retired**: FreqAI pipelines with LightGBM, XGBoost, PyTorch MLP,
  Transformer. All produced beautiful in-sample fits (Calmar > 50) that
  vanished out-of-sample.
- **Lesson**: ML models trained on n < 5000 examples with 50+ features
  will memorize, not generalize. Guaranteed.

---

## Early Iterations (superseded)

### `TrendFollowEMA.py`

- **Why retired**: Earliest trend-follower. Replaced by `HonestTrendGeneric`
  and its subclasses. Functionally similar but without FnG defense,
  risk-manager integration, or walk-forward validation.
- **Lesson**: the first version of any strategy is a prototype, not a product.

### `DonchianBreakout.py`

- **Why retired**: Breakout attempts on daily timeframe. Too few trades/year
  (~8) to validate. OOS inconclusive.
- **Lesson**: low trade frequency makes any backtest statistically useless
  regardless of apparent results.

---

## Dead Edges (looked real, weren't)

### `PairMeanReversion.py`

- **What it was**: ETH/BTC z-score mean reversion. Buy ETH when z < −2
  (ETH undervalued vs BTC), exit when z reverts to 0.
- **The seductive stat**: p < 0.0001 in-sample (n=2382, avg +0.96% per week).
- **What happened**: 2025 saw persistent ETH/BTC trend drift. The mean-
  reversion assumption broke. OOS: lost money.
- **Lesson**: statistical significance on historical data does not guarantee
  the underlying regime persists. "Every strategy dies cliff-fall" (Taleb).
  Always have a kill-switch on regime change.

---

## HonestTrend Earlier Variants (replaced by Generic + Subclasses)

These predate the `HonestTrendGeneric` + risk-manager architecture. They
were rungs on the ladder, not the ladder itself.

### `HonestTrend.py` (daily)

- **Why retired**: ~10 trades/year. Can't validate anything with n=20
  across 2 years.
- **Lesson**: daily-timeframe trend following on 3 pairs gives
  insufficient sample for significance tests.

### `HonestTrend1h.py` (1h)

- **Why retired**: OOS −14% to −25% across multiple parameter choices.
  Stage 2 cross-timeframe test later confirmed: **1h timeframe completely
  fails** for this edge, regardless of EMA choice.
- **Lesson**: "signal works at X timeframe" is often shorthand for
  "execution works at X timeframe". Latency kills.

### `HonestTrend1m.py` (1m, original)

- **Why retired**: Superseded by `HonestTrend1mLive.py` subclass. Kept
  here as the original before the risk-manager framework.
- **Lesson**: add risk-management before you deploy, not after.

### `HonestTrend15m.py` + `.json` (15m, original)

- **Why retired**: Superseded by `HonestTrend15mDry.py`. This was the
  hyperopt-fitted version (EMA 94/139, ratio 1.48x) before we understood
  whether the fit was real.
- **Lesson**: hyperopt results must be walk-forward validated before
  being treated as "the" parameters.

### `HonestTrend15m_2xRatio.py` + `.json`

- **What it was**: Stage 1 testing artifact. Fixed slow = 2×fast, varied
  fast across {24, 48, 72, 96, 128, 160}.
- **Why retired**: Served its purpose — proved the edge is real (non-
  hyperopt 2x ratios also profit OOS) but not as robust as 1.48x ratio.
- **Lesson**: keep testing scaffolding separate from production code.

### `HonestTrend4h.py` (4h)

- **Why retired**: Best PF (1.74 OOS) but only ~15 trades/year. Too few
  for meaningful validation. Not a bad strategy; just not enough data
  to trust.
- **Lesson**: a 1.74 PF over 15 trades means your 95% CI on PF is roughly
  [0.7, 4.5]. Useless.

---

## Restoration Protocol

If a future you wants to revive one of these:

1. **Read the "Why retired" entry above first.** The failure mode is
   documented. Don't rediscover it.
2. **Run the full validation stack**: Stage 1 (parameter stability) +
   Stage 2 (cross-timeframe consistency) + Stage 3 (fat-tail + bootstrap
   significance) from `HONEST_TREND_REPORT.md`.
3. **Integrate `risk_manager.py`** before any dry-run.
4. **Parallel dry-run at least 3 months** before risking real money.
5. **Do not trust in-sample metrics.** Only walk-forward.

---

## What To Read When Things Go Wrong

- `HONEST_TREND_REPORT.md` — full decision record
- `../strategies/risk_manager.py` — kill-switch rules
- `../risk_state.json` — live state
- `../walk_forward_history/` — monthly re-validation archive

---

*If you're reading this because the live strategy died, the right reaction
is not "try another strategy from legacy". The right reaction is:
is the entire class of strategy (short-term trend following) no longer
working? Or did a specific implementation break? Answer that first,
then decide whether to build new or restart from legacy.*
