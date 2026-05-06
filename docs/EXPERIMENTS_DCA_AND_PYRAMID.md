# 实验报告：DCA 加激进 + 趋势策略 Pyramid Winners

两个独立的改进实验，均为"暴跌/盈利时加仓"的正确姿势。

---

## 实验 A：DCA 加激进（FnG < 10 → 3× 乘数）

**假设**：当前 DCA 在 FnG < 20 时已用 2× 乘数。再激进一点（FnG < 10 → 3×, cap 3.0）能不能用更低的平均成本累积更多 BTC？

### 方法

- 时间范围：2018-02-01 → 2026-04-17（FnG 数据起点到当前）
- 基础金额：**$500/周**，每周一买入
- 周期因子代理：**Mayer Multiple**（价格 / 200 日 MA）映射到 [-1, +1]
- 脚本：`scripts/backtest_dca.py`

### 4 种方案对比结果

| 方案 | 总花费 (USDT) | 买到的 BTC | 平均成本 ($/BTC) | 组合估值 (USDT) | PnL % | vs 平坦 多赚 % |
|------|------------:|----------:|----------------:|---------------:|------:|---------------:|
| **A. 平坦 $500/wk**（基线） | 214,000 | 13.75 | **$15,569** | $1,022,877 | +378% | 0% |
| **B. 当前公式**（cycle 50% + FnG 30%）| 328,200 | 22.00 | $14,918 | $1,637,210 | +399% | **+60.1%** |
| **C. 激进**（FnG<10→3x, cap 3x）| 356,812 | 24.52 | **$14,549** | **$1,825,060** | +412% | **+78.4%** |
| **D. FnG-only** 线性 | 250,461 | 17.48 | $14,332 | $1,300,496 | **+419%** | +27.1% |

### 结论

1. **激进方案 (C) 绝对收益最优**：$1.82M，比基线多赚 **+78%**
2. **FnG-only (D) 效率最高**：每美元收益 +419%，但绝对金额少因为投得少
3. **当前公式 (B) 已经不错**：vs 平坦 +60%。升级到 (C) 再 +18%
4. **激进方案的"代价"**：多花 $142,812（vs 基线），但多赚 $802,183 → **增量 ROI = 5.6×**

### 为什么激进有效？

- **FnG < 10 极度罕见**（8 年里只出现了 ~30 周），不会长期超额投入
- 这些时点大概率是**周期底部**（2018-12、2020-03 COVID、2022-11 FTX）
- 买在极度恐惧 = 买在接近局部底 → 平均成本更低

### 建议

✅ **采纳方案 C**。修改 `strategies/dca_executor.py` 的 `compute_multiplier`：

```python
if fng < 10:
    fng_mult = 3.0          # NEW
elif fng < 20:
    fng_mult = 2.2          # was 2.0
# ...
multiplier = ... * kol_bonus
multiplier = max(0.0, min(3.0, multiplier))  # cap raised from 2.5 to 3.0
```

### 可视化
- `reports/dca_backtest/dca_comparison.html` — 4 方案 portfolio 对比 + 累计投入 + 平均成本
- `reports/dca_backtest/multiplier_distribution.html` — 每种方案的乘数频率分布

---

## 实验 B：HonestTrend Pyramid Winners

**假设**：趋势策略当前每笔只进 1 次。如果在**盈利确认**后加仓（pyramid winners，不是 martingale losers），能不能提高总收益？

### 方法

**新策略**：`strategies/HonestTrend15mPyramid.py`

```
初始进场：EMA 94/139 金叉 + ADX > 18 + FnG < 80  （同 HonestTrend15mDry）
Pyramid 1：持仓盈利 ≥ +5%  → 加 0.6× 初始仓
Pyramid 2：持仓盈利 ≥ +12% → 加 0.4× 初始仓
最大总仓位：2.0× 初始（第一次 1.0 + 0.6 + 0.4）
出场：EMA 死叉（同基线）
关键规则：亏损时 NEVER 加仓（不是 martingale）
```

两次都用相同 config（`configs/backtest/config_backtest_15m_pyramid.json`）：
- `stake_amount: 3000`（固定，给 pyramid 留空间）
- `max_open_trades: 3`
- `position_adjustment_enable: true`（pyramid 版启用）

### 对比结果（2017-08-17 → 2026-04-20，BTC+ETH）

| 指标 | Baseline 15mDry | Pyramid 15mPyramid | 差异 |
|------|--------------:|------------------:|-------:|
| Trades | 570 | 570 | 0 |
| Win Rate | 38.2% | **33.2%** | **−5.0 ppt** |
| Total Profit (USDT) | $26,823 | **$37,782** | **+$10,959 (+41%)** |
| Total Profit % | +268% | **+378%** | **+110 ppt** |
| Avg Profit / trade | 1.20% | 0.15% | −1.05 ppt (因为仓更大) |
| Max Drawdown | 25.50% | **24.03%** | **−1.5 ppt** |

### 为什么 Pyramid 有效？

- **赢家变得更大**：原本平均 $1,439 的赢家，被放大到有效 $2,000+（初始 $3K + 0.6× $3K 加仓在盈利 5%，再 +0.4× 在盈利 12%）
- **输家没有变大**（规则：盈利才加仓）
- **Win rate 反而下降** (−5 ppt)：有些盈利 5-12% 之间进了 pyramid 后回落到 0 以下，被计入亏损
- **但平均赢利 × 赢的次数 > 平均亏损 × 亏的次数** 成立 → 净收益上升

### 为什么 Max DD 变小了？

违反直觉但有数据支持：
- Pyramid 是"盈利为前提"的加仓，大多出现在牛市/上升段
- 牛市段拉高 equity peak，之后的熊市回撤从"更高起点"往下跌，百分比上反而**小一点**
- 而且没有在输家上加仓，所以最糟糕情形的下行不会被放大

### ✅ 已采纳（2026-04-21）— 方式 2 激进集成

`adjust_trade_position` 和 `position_adjustment_enable = True` 已直接加入 `HonestTrendGeneric` 基类。**所有子类自动继承**：
- `HonestTrend15mDry` — 生效
- `HonestTrend1mLive` — 生效
- `HonestTrend1mMTF` — 生效

3 个生效 config 已更新：
- `configs/config_dryrun_honest15m.json`
- `configs/config_dryrun_honest1mmtf.json`
- `configs/config_live_honest1m.json`

每个 config 新增：
```json
"position_adjustment_enable": true,
"max_entry_position_adjustment": 2,
"stake_amount": 1500   // was "unlimited"
```

⚠️ **stake_amount 从 "unlimited" 改为固定 1500**，原因：
- 原来 unlimited 会把整个 wallet 填满（3 单 × 3333 = 9999），pyramid 没余量
- 新值 1500 给 pyramid 留空间（单笔可长到 1500 + 900 + 600 = 3000，3 笔并行最多用 9000，余 1000 buffer）
- **实盘前务必按你实际分配给 HonestTrend 的资金比例调整**（stake = dedicated_capital × 0.15）

实验版文件已删除：
- ~~`strategies/HonestTrend15mPyramid.py`~~（已合并到基类）
- ~~`configs/backtest/config_backtest_15m_pyramid.json`~~（已与 btceth 等价）

### 可视化
- `reports/pyramid/index.html` — 完整 7 图仪表盘
- 对比 `reports/full_history_btceth/index.html`（baseline）

---

## 两个实验的"哲学"区分

| | DCA 激进 | Pyramid Winners |
|--|---------|----------------|
| 何时加仓 | 暴跌恐慌时 | 盈利确认时 |
| 触发条件 | FnG / cycle 低估信号 | 当前持仓 > +5% / +12% |
| 本质 | **反向交易**（越跌越买）| **顺势加仓**（越涨越买）|
| 适合 | 长期累积（spot holdings）| 活跃趋势策略 |
| 实现位置 | `dca_executor.py` weekly timer | `HonestTrend15mPyramid.adjust_trade_position` |

两者**可以同时存在且不冲突**，因为它们作用在**不同市场阶段**：
- DCA 在明确的熊市底部加仓 → 买入长期累积
- Pyramid 在明确的牛市趋势中加仓 → 放大当下交易

**千万不要混合成"亏损加仓"（Martingale）**—— 那会把两边的优点全毁掉。

---

## 复现命令

```bash
# DCA 实验
python scripts/backtest_dca.py
# → reports/dca_backtest/summary.csv + *.html

# Pyramid 实验
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
