---
title: "Visualization guide"
description: "VISUALIZATION_GUIDE"
---

# Strategy Visualization Guide

How to use `scripts/visualize_strategy.py` + freqtrade built-in tools to actually understand a backtest result.

Using `HonestTrend15mDry` full history (2017-08 → 2026-04, BTC+ETH) as the running example.

## Key numbers (look at these first)

| Metric | Value | Interpretation |
|------|---|------|
| Total trades | 570 | 8.6 years × 15m frequency → ~1 trade every 5.5 days on average (slow and steady) |
| Win rate | 38.2% | Typical trend strategy — **few wins, many losses, but wins are big** |
| Total profit | **+954.27%** | 10K → 104K (compound annual growth ~32%) |
| Avg per trade | +1.20% | Positive expected value |
| Avg win / Avg loss | $1,439 / −$620 = **2.32×** | Winners are 2.3× larger than losers — that's where the edge lives |
| Max drawdown | 17,544 USDT (26.06%) | Occurred in the 2018 bear, lasted ~11.5 months |
| Sharpe (daily) | — | Use plotly-profit to gauge stability |

**One sentence**: 62% of 570 trades lose money, but the 38% winners are on average 2.3× larger than the losers → systemic positive expectancy.

## 7 custom charts (by importance)

### 1. `01_equity_curve.html` — Equity curve + drawdown (the single most important chart)

Upper half: green equity curve starting at 10K, ending around ~104K over 8 years. Gray dashed line marks the rolling peak.
Lower half: red filled area shows current drawdown percentage.

**How to read it:**
- Gentle up-slope = healthy growth
- Sharp vertical drops + long time in negative territory = rough patch (e.g. 2018)
- Speed of drawdown recovery = strategy resilience
- New highs being hit continually = strategy is still earning

**HonestTrend's signature**: crawled around −26% for all of 2018 (max DD segment), only reclaimed the peak in 2019 Q3. After that, 2020 and 2024 were two strong runs.

### 2. `02_drawdown.html` — Rolling drawdown

Zoomed-in drawdown view. Automatically annotates the worst drawdown point.

**Important thresholds:**
- **DD ≤ 15%** — Normal volatility
- **DD 15-20%** — Warning (risk_manager PAUSE)
- **DD > 20%** — Strategy retirement trigger (risk_manager RETIRE)

HonestTrend hit −26% in 2018 — with the current kill-switch it would have been paused long before then. **This is exactly why you run the kill-switch instead of trusting historical data blindly.**

### 3. `03_per_pair.html` — Per-pair performance

3 panels side by side: total profit / win rate / trade count.

**Look for:**
- Which pair contributes the most profit?
- Which pair has a low win rate?
- Big gap in trade counts (concentration vs spread)?

HonestTrend full history: BTC and ETH contribute about equally (strategy is symmetric).

### 4. `04_trade_distribution.html` — 4-in-1 distribution plot

- **Top-left**: Profit distribution histogram. Is it normal? Long-tailed? Median near 0?
- **Top-right**: Holding duration distribution.
- **Bottom-left**: Profit vs holding duration scatter. **If you see a "longer hold = higher profit" trend → the "let winners run" thesis holds empirically.**
- **Bottom-right**: 20-trade rolling average profit. Staying above 0 = edge persists.

**HonestTrend's signature**: 5–10 day holds are the big winners (scatter points beyond 60h cluster in positive returns); short-duration exits are mostly stops.

### 5. `05_monthly_heatmap.html` — Monthly P&L heatmap

Rows are years, columns are months, color intensity is P&L. Green = win, red = loss.

**At a glance:**
- Which years earned the most (2020, 2024)
- Which months repeatedly turn red (historically May in crypto tends to drop — "sell in May")
- Consecutive green/red months = clear regime

### 6. `06_exit_reasons.html` — Exit reason analysis

Two bar charts:
- Left: trade count per exit reason
- Right: total profit per exit reason

**For HonestTrend**: almost every trade is `trend_exit` (EMA death cross). Because the strategy **has no hard stoploss and no ROI take-profit**, it only exits on signal reversal.

If one exit_reason is responsible for a lot of losses → that rule may need tuning.

### 7. `07_rolling_winrate.html` — Rolling win rate

3 lines: 10 / 30 / 60-trade window win rate. 50% baseline.

**How to read it:**
- Consistently 40–50% = normal trend strategy
- Long-term < 40% = edge decay
- Sudden spike or drop = precursor to a regime shift

HonestTrend's win rate oscillates between 35–45% long-term, **consistent with theoretical expectations**.

## Freqtrade built-in charts (auto-generated)

### 8. `08_freqtrade_profit_plot.html` — Official profit plot

Output of Freqtrade's `plot-profit` command. Includes:
- Per-pair price curve
- Cumulative profit curve
- Per-pair average profit
- Open trades count over time

Use: verify the equity curve conclusions from chart 1.

### 9. `09_btc_candles_with_trades.html` — Candles + trade markers

Output of Freqtrade's `plot-dataframe`. Draws directly on the BTC candles:
- Green triangle = buy entry
- Red triangle = sell exit
- Overlaid EMA / ADX indicators

**This is the most intuitive "what is the strategy actually doing" view.** You can see first-hand:
- Under what price patterns does the strategy enter
- Where it exits
- Whether there are obvious "chase highs / panic sells" mistakes

## Tabular analysis (CSV output)

`freqtrade backtesting-analysis --analysis-groups 0 2 5` produces:

- `group_0.csv` — Enter tag summary
- `group_2.csv` — Enter × Exit tag matrix
- `group_5.csv` — Exit reason summary
- `indicators.csv` — Entry/exit indicator values for each trade

Open in pandas / Excel and filter, e.g.:
```python
import pandas as pd
df = pd.read_csv('reports/full_history_btceth/indicators.csv')
# How did entries with FnG > 70 perform?
print(df[df['enter_FnG'] > 70][['pair', 'enter_date', 'profit_ratio']])
```

## Cross-window comparison (regime analysis)

Want to compare 2018 vs 2024 strategy behavior? Run 2 backtests separately and store them in different reports subdirectories:

```bash
# 2018 crash
freqtrade backtesting --strategy HonestTrend15mDry ... --timerange 20180101-20181231 --export signals
python scripts/visualize_strategy.py --out reports/2018_crash

# 2024 bull
freqtrade backtesting --strategy HonestTrend15mDry ... --timerange 20240101-20241231 --export signals
python scripts/visualize_strategy.py --out reports/2024_bull
```

Compare `05_monthly_heatmap.html` or `07_rolling_winrate.html` to visually see regime differences.

## References

- [freqtrade · Strategy Analysis Example](https://www.freqtrade.io/en/develop/strategy_analysis_example/)
- [freqtrade · Advanced Backtesting](https://www.freqtrade.io/en/develop/advanced-backtesting/)
- [WALK_FORWARD_FULL_HISTORY.md](WALK_FORWARD_FULL_HISTORY.md) — full case study using these charts to diagnose the 2018 loss
