# Strategy Visualization Guide

如何用 `scripts/visualize_strategy.py` + freqtrade 内置工具把一个回测结果"看明白"。

以 `HonestTrend15mDry` 全历史 (2017-08 → 2026-04, BTC+ETH) 为例。

## 关键数字（先看这个）

| 指标 | 值 | 解读 |
|------|---|------|
| 总交易数 | 570 | 8.6 年 × 15m 频率 → 平均每 5.5 天 1 笔（慢而稳）|
| 胜率 | 38.2% | 典型趋势策略 — **赢少输多但赢大**|
| 总利润 | **+954.27%** | 10K → 104K（复合增长率 ~32% 年化）|
| 平均单笔 | +1.20% | 正期望值 |
| 平均赢 / 平均输 | $1,439 / −$620 = **2.32×** | 赢家是输家的 2.3 倍大 — 这就是 edge 所在 |
| 最大回撤 | 17,544 USDT (26.06%) | 发生在 2018 熊市，持续约 11.5 个月 |
| Sharpe（日）| — | 用 plotly-profit 看稳定性 |

**一句话**：570 笔里 62% 亏钱，但 38% 的赢家平均是亏家的 2.3 倍 → 系统级正期望。

## 7 张自定义图表（按重要度）

### 1️⃣ `01_equity_curve.html` — 资金曲线 + 回撤（最关键的图）

上半部分：绿色资金曲线从 10K 起，走 8 年到 ~104K。灰色虚线是历史最高点（peak）。
下半部分：红色填充区域是当前回撤百分比。

**怎么读：**
- 平缓向上 = 健康增长
- 大幅垂直下跌 + 长期在负值区 = 糟糕阶段（比如 2018）
- 回撤回到 0 的速度 = 策略恢复能力
- 如果新高不断刷新 = 策略仍在赚钱

**HonestTrend 的特征**：2018 一整年在 −26% 左右爬行（最大 DD 段），2019 Q3 才回到 peak。之后 2020、2024 是两次强劲阶段。

### 2️⃣ `02_drawdown.html` — 滚动回撤

放大的回撤视图。自动标注最差回撤点。

**重要阈值：**
- **DD ≤ 15%** — 正常震荡
- **DD 15-20%** — 警告（risk_manager PAUSE）
- **DD > 20%** — 策略退役触发（risk_manager RETIRE）

HonestTrend 在 2018 触及 −26%，按现在的 kill-switch 早就被 pause 了。**这也是为什么要跑 kill-switch 而不是盲信历史数据。**

### 3️⃣ `03_per_pair.html` — 每个币的表现

3 个小图横向排列：总利润 / 胜率 / 交易数。

**看点：**
- 哪个币贡献最多利润？
- 哪个币胜率低？
- 交易数差距大吗（集中 vs 分散）？

HonestTrend 全历史：BTC 和 ETH 贡献差不多（策略是对称的）。

### 4️⃣ `04_trade_distribution.html` — 4 合 1 分布图

- **左上**：利润分布直方图。正态吗？长尾吗？中位数在 0 左右？
- **右上**：持仓时长分布。
- **左下**：利润 vs 持仓时长散点图。**如果看到"持仓越久利润越好"的趋势 → 证明"让赢家跑"的理论成立**。
- **右下**：20-trade 滚动平均利润。稳定在 0 以上 = edge 持续。

**HonestTrend 的特征**：持仓 5-10 天的是大赢家（60 小时以上的散点集中在正收益区）；短时间出场的多为止损。

### 5️⃣ `05_monthly_heatmap.html` — 月度 P&L 热力图

行是年份，列是月份，颜色深浅表示盈亏。绿色 = 赚，红色 = 亏。

**一眼看出**：
- 哪些年份最赚钱（2020、2024）
- 哪些月份反复出现红色（历史上加密圈 5 月容易跌 — "sell in May"）
- 连续多月绿/红 = 明确 regime

### 6️⃣ `06_exit_reasons.html` — 出场原因分析

两个柱状图：
- 左：每种出场原因的交易数
- 右：每种出场原因的总利润

**对 HonestTrend**：几乎所有交易都是 `trend_exit`（EMA 死叉）。因为策略**没有硬止损、没有 ROI 止盈**，信号反转才出场。

如果看到某种 exit_reason 大量亏钱 → 那个规则可能要调。

### 7️⃣ `07_rolling_winrate.html` — 滚动胜率

3 条线：10 / 30 / 60-trade 窗口胜率。基准线 50%。

**怎么读：**
- 持续在 40-50% 之间徘徊 = 正常趋势策略
- 长期 < 40% = edge 退化
- 突然飙升或下跌 = regime shift 前兆

HonestTrend 的胜率长期在 35-45% 之间波动，**符合理论预期**。

## Freqtrade 内置图表（自动生成）

### 8️⃣ `08_freqtrade_profit_plot.html` — 官方 profit plot

Freqtrade 的 `plot-profit` 命令输出。包含：
- 每个币的价格曲线
- 累计利润曲线
- 每个币的平均利润
- Open trades 数量随时间变化

用途：验证 1 的资金曲线结论。

### 9️⃣ `09_btc_candles_with_trades.html` — 蜡烛图 + 交易标记

Freqtrade 的 `plot-dataframe` 输出。在 BTC K 线上直接画出：
- 绿三角 = 买入点
- 红三角 = 卖出点
- 覆盖的 EMA / ADX 指标

**这是最直观的"策略在干嘛"视图**。你能真实看到：
- 策略在什么样的价格模式下进场
- 在哪里出场
- 有没有明显的"追高/杀跌"错误

## Tabular 分析（CSV 输出）

`freqtrade backtesting-analysis --analysis-groups 0 2 5` 生成：

- `group_0.csv` — Enter tag 汇总
- `group_2.csv` — Enter × Exit 标签矩阵
- `group_5.csv` — Exit reason 汇总
- `indicators.csv` — 每笔交易的入场/出场指标值

用 pandas / Excel 打开筛选，比如：
```python
import pandas as pd
df = pd.read_csv('reports/full_history_btceth/indicators.csv')
# 看看 FnG > 70 的进场都怎么样
print(df[df['enter_FnG'] > 70][['pair', 'enter_date', 'profit_ratio']])
```

## 跨窗口对比（regime analysis）

想对比 2018 和 2024 的策略行为？分别跑 2 个 backtest，存到不同 reports 子目录：

```bash
# 2018 crash
freqtrade backtesting --strategy HonestTrend15mDry ... --timerange 20180101-20181231 --export signals
python scripts/visualize_strategy.py --out reports/2018_crash

# 2024 bull
freqtrade backtesting --strategy HonestTrend15mDry ... --timerange 20240101-20241231 --export signals
python scripts/visualize_strategy.py --out reports/2024_bull
```

对比 `05_monthly_heatmap.html` 或 `07_rolling_winrate.html` 就能直观看出 regime 差异。

## 参考

- [freqtrade · Strategy Analysis Example](https://www.freqtrade.io/en/develop/strategy_analysis_example/)
- [freqtrade · Advanced Backtesting](https://www.freqtrade.io/en/develop/advanced-backtesting/)
- [WALK_FORWARD_FULL_HISTORY.md](WALK_FORWARD_FULL_HISTORY.md) — 用这些图诊断 2018 亏损的完整案例
