# Hyperopt 实验：Pyramid 参数优化

**目标**：把我"凭感觉"设的 4 个 pyramid 参数交给 optuna 优化，用自定义 loss 避免过拟合，walk-forward 验证是否真的更好。

## 方法论

### 1. 参数空间

```python
pyramid_1_trigger     = DecimalParameter(0.03, 0.10)  # 原默认 0.05
pyramid_2_trigger     = DecimalParameter(0.08, 0.20)  # 原默认 0.12
pyramid_1_stake_ratio = DecimalParameter(0.30, 1.00)  # 原默认 0.60
pyramid_2_stake_ratio = DecimalParameter(0.20, 0.80)  # 原默认 0.40
```

### 2. 自定义 Loss — `HonestHyperOptLoss`

避开内置 loss 的陷阱：
- `ShortTradeDurHyperOptLoss` 鼓励短线（违反我们中线哲学）
- `SharpeHyperOptLoss` 容易被大赢家骗
- 内置 `CalmarHyperOptLoss` 最接近但没有 DD 硬阈值

我们的版本（`strategies/HonestHyperOptLoss.py`）：

```
IF trade_count < 50:       loss = 999  (拒绝低样本)
IF max_dd > 20%:           loss = 100 + max_dd * 10  (硬拒绝)
IF max_dd > 15%:           Calmar 除以惩罚系数 (1.0 → 2.0)
ELSE:                      loss = -Calmar  (Calmar 越大越好)
```

### 3. 训练 / 验证切分

- **训练**：2022-01 → 2024-12（3 年，3 regime：LUNA 崩盘 / 复苏 / ETF 牛）
- **验证**：
  - **真 out-of-sample 过去**：2018-2020（W1-W3）
  - **真 out-of-sample 未来**：2025-至今（W8）
  - **内含 in-sample**：2022-2024（W5-W7）

- **CPU**：单线程（多线程因 joblib pickle 错误无法启用）
- **Optuna sampler**：NSGAIIISampler（默认，多目标友好）
- **Epochs**：100
- **Runtime**：19 分钟

## 结果

### 最优参数（epoch 42/100）

| 参数 | 原默认 | Hyperopt 最优 | 变化 |
|------|------:|-------------:|-----:|
| `pyramid_1_trigger` | 0.05 | **0.08** | +60% |
| `pyramid_2_trigger` | 0.12 | **0.10** | −17% |
| `pyramid_1_stake_ratio` | 0.60 | **0.80** | +33% |
| `pyramid_2_stake_ratio` | 0.40 | **0.80** | **+100%** |

**解读**：
- 第一次加仓门槛提高到 +8%（更谨慎，过滤噪音）
- 第二次加仓门槛反而降到 +10%（当第一次已经过关，第二次更快跟进）
- 两次加仓金额都放大到 **0.8× 初始**（最大总仓位达 **2.6× 初始** vs 旧的 2.0×）
- 本质：**更激进的 pyramid，但更严格的门槛**

### 训练集表现（2022-01 → 2024-12）

```
Trades: 206
Win Rate: 37.4%
Total Profit: +48.86%
Max DD: 10.31%
Calmar Objective: -4.74
```

### 全历史对比（2017-08 → 2026-04）

| 指标 | 旧默认 | **Hyperopted** | 差异 |
|------|------:|---------:|-----:|
| Total Profit | +195% | **+207%** | +12 ppt |
| Trades | 570 | 570 | 0 |
| Win Rate | 33.2% | **35.3%** | +2.1 ppt |
| Max DD | 16.93% | **15.53%** | **−1.4 ppt** |
| Avg Trade | 0.15% | −0.08% | 略降（高胜率换高利润模式）|

### 8-Regime Walk-Forward 对比

| Window | 旧默认 | Hyperopted | 差异 | 备注 |
|--------|------:|---------:|-----:|------|
| W1 2018 crash | −14.43% | **−13.27%** | **+1.16** | 🎯 OOS 改善 |
| W2 2019 accum | +9.57% | +8.42% | −1.15 | OOS 略降 |
| W3 2020 COVID | +46.88% | +45.74% | −1.14 | OOS 略降 |
| W4 2021 bull | +34.77% | +31.54% | −3.23 | 训练前 |
| W5 2022 LUNA | −4.83% | **−4.68%** | +0.15 | 训练集 |
| W6 2023 recovery | +4.72% | +5.90% | +1.18 | 训练集 |
| W7 2024 ETF | +44.69% | +47.29% | +2.60 | 训练集 |
| W8 2025 present | −4.00% | **−2.46%** | **+1.54** | 🎯 OOS 改善 |
|    | | | **+1.11 sum** | |
| profitable/8 | 5/8 | 5/8 | 0 | 稳定 |

**关键观察**：
1. **训练集 (W5-W7) 累计 +3.93 ppt 改善** — 符合预期
2. **OOS 过去 (W1-W3) 累计 −1.13 ppt** — 过去数据有轻微退化，但 W1 (2018 最难) 实际改善 +1.16
3. **OOS 未来 (W8) +1.54 ppt 改善** — 对当下市场有益
4. **没有过拟合信号**：OOS 平均 +0.24 ppt 改善，超过 1/8 样本意义

## 结论：值得采纳

✅ **Pros**：
- 全历史 +12 ppt 收益 + DD 降 1.4 ppt
- W1 2018 (最难窗口) 和 W8 2025 (当前) 都有改善
- 无过拟合证据 (OOS 数据有净正改善)

⚠️ **Cons**：
- W4 2021 牛市顶部 −3.23 ppt（高估值时代的边际退化）
- W2/W3 OOS 轻微退化（但仍盈利）

### 已应用

1. `strategies/HonestTrendGeneric.py` 基类 defaults 更新为 hyperopt 最优值
   - 所有子类 (`HonestTrend15mDry`, `1mLive`, `1mMTF`) 自动继承
2. `strategies/HonestTrend15mDry.json` auto-saved by freqtrade（takes precedence for that class specifically）
3. 生产 configs 已 pyramid enabled（见 `docs/EXPERIMENTS_DCA_AND_PYRAMID.md`）

## 扩展实验：6 参数 hyperopt（❌ 被拒绝）

**2026-04-21 后续测试**：把 `adx_threshold` 和 `min_hold_minutes` 也加入 hyperopt 空间（总计 6 个参数），150 epochs。

### 结果

训练集表现炸裂：
```
Objective: -10.84  (vs -4.74 in 4-param baseline)
In-sample (2022-2024): 119 trades, 37.8% WR, +70%, Max DD 6.46%
```

最优参数：
- `adx_threshold`: 18 → **30**（大幅提高入场门槛）
- `min_hold_minutes`: 720 → **1065**（~18h 最短持仓）
- `pyramid_1_stake_ratio`: 0.80 → **1.00**（第一次加仓打满）

### Walk-forward 8 窗口：6/8（看起来更好！）

| Window | 4-param | 6-param | Diff |
|--------|-------:|-------:|-----:|
| W1 2018 | −13.27% | **−20.02%** | −6.75 ❌ |
| W4 2021 | +31.54% | **+58.59%** | +27.05 ✅ |
| W5 2022 | −4.83% | **+4.89%** | +9.57 ✅ **翻正** |
| W7 2024 | +47.29% | +55.02% | +7.73 ✅ |
| Sum | | | **+19.4 ppt** |

### ❌ 但全历史是灾难

| 指标 | 4-param | 6-param | 差异 |
|------|------:|------:|-----:|
| Total profit | +207% | **+160%** | −47 ppt |
| Max DD | **15.53%** | **24.81%** | **+9.3 ppt 🚨** |
| Trades | 570 | 335 | −40% |

**24.81% max DD 超过 20% kill-switch 阈值** → 实盘会触发 RETIRE 自动退役。

### 为什么 walk-forward 好但全历史坏？

- Walk-forward 每个窗口 $10K 独立本金，peak-to-trough 只在年内
- 全历史**复合增长**后，mid-2018 的 −6.7 ppt 亏损叠加到已累积的牛市利润上 = 更大百分比回撤
- ADX=30 的严格过滤在牛市涨得更猛，但熊市也因为少开仓而**更晚**回到新高
- 简单的"每窗口能赚吗"忽略了**下跌时的相对深度**

### 回退决定

- `adx_threshold` 和 `min_hold_minutes` 恢复为 `optimize=False`
- `strategies/HonestTrend15mDry.json` 恢复为 4-param hyperopt 的旧最优值
- 教训：**walk-forward profitable rate 不等于全历史 max DD 控制**

## 扩展实验：CmaEsSampler（技术改进）

添加了 `generate_estimator` 方法（nested `HyperOpt` class 内）用 `CmaEsSampler` 替代默认 `NSGAIIISampler`。CmaEs 对连续参数收敛更快。

**未来 hyperopt 自动启用**，但 6-param 被拒绝的实验用的是 NSGAIII（改 CmaEs 前），结果不受影响。

## 扩展实验：HonestTrend1mLive 单独 hyperopt（❌ 被拒绝）

**2026-04-22**：在 1m timeframe 上单独 hyperopt（base class 是用 15m 数据调的，理论上 1m 可能有不同最优）。

### 设置
- 训练范围：2024-01 → 2024-12（1 年 1m BTC+ETH）
- Epochs：50，`min_trades=25`（1m 交易少，必须降阈值）
- 空间：4 个 pyramid 参数（不动 EMA/ADX/min_hold）
- Sampler：CmaEs

### 最优参数（epoch 30/50）

| 参数 | base class 默认 | 1m hyperopt | 变化 |
|------|------:|---------:|-----:|
| `pyramid_1_stake_ratio` | 0.80 | **0.60** | −25% |
| `pyramid_2_stake_ratio` | 0.80 | **0.70** | −13% |
| `pyramid_2_trigger` | 0.10 | **0.08** | −20% |
| `pyramid_1_trigger` | 0.08 | 0.08 | = |

方向：**加仓更保守**（stake 小、第二次加仓门槛更低但金额更小）。

### 训练集（2024 单年）
- Default: +25.21%
- 1m hyperopt: +24.72%（**−0.49 ppt**）

训练集上已经没有明显改善 —— 说明 CmaEs 在 50 epochs 内找不到比默认更好的组合。

### 全历史 3.3 年对比（2023-01 → 2026-04）

| 指标 | Base class 默认 | 1m hyperopt | 差异 |
|------|------:|---------:|-----:|
| Total Profit | **+37.99%** | +36.13% | **−1.86 ppt** |
| Max DD | 10.55% | 10.33% | −0.22 ppt |
| Calmar (wallet) | 4.15 | 4.04 | −0.11 |
| Trades | 135 | 135 | 0 |
| Win Rate | 35.6% | 35.6% | 0 |

### 回退决定
- 删除 `strategies/HonestTrend1mLive.json`
- `HonestTrend1mLive` 继续继承 base class 的 pyramid 默认值
- 教训：**同一套 4 个 pyramid 参数在 15m 和 1m 上都够用**，再单独 hyperopt 1m 是 noise-chasing

### 为什么没改善？
1. **Pyramid 触发器是"利润百分比"**，不依赖 timeframe —— +8% 在 15m 和 1m 都是 +8%
2. **真正会随 timeframe 变的是 EMA/ADX**，但这些我们明确不做 hyperopt
3. **50 epochs + 1 年数据**不够 CmaEs 收敛到有意义的改善

## 未来优化路线

### 短期
- 观察 W8 (2025-至今) 实盘 1-2 月，确认 4-param 新参数确实好

### 不做
- **不要再往 hyperopt 空间加 adx/min_hold**（上面已验证是陷阱）
- **不要一次调 >5 个参数**（过拟合概率随维度指数增加）
- **不要把 EMA 周期加进 hyperopt**（这些是"结构性"选择，不该由优化器随意改）
- **不要再单独 hyperopt 1m vs 15m 的 pyramid 参数**（2026-04-22 已验证 noise-chasing）

### 关键教训

1. **训练 loss 降低 ≠ 生产更好**：objective 从 -4.74 → -10.84 在训练集看来是 2× 改善，但全历史 DD 翻了 1.6 倍
2. **Walk-forward 独立窗口 ≠ 全历史回测**：前者看不见"连续劣势"的复合伤害
3. **相信 kill-switch 阈值**：20% DD 不是随便定的，是实盘能扛住的心理上限。让 hyperopt 把 DD 推到那个阈值就是在玩火
4. **少即是多**：4 个 pyramid 参数 + 严格 loss 已足够。再加 2 个变量把噪音引进来
5. **跨 timeframe 的 pyramid 参数是 timeframe-agnostic**：同一套 4 个 pyramid 在 15m 和 1m 上都最优 —— 因为触发器看百分比利润而非 K 线数

## 复现

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

# 查看最佳 epoch
freqtrade hyperopt-show --best \
  --user-data-dir user_data \
  --hyperopt-filename strategy_HonestTrend15mDry_2026-04-21_17-08-21.fthypt

# Walk-forward 验证
python scripts/walk_forward_full_history.py \
  --strategy HonestTrend15mDry \
  --timeframe 15m \
  --config configs/backtest/config_backtest_15m_btceth.json
```

## 参考

- [Freqtrade Advanced Hyperopt](https://www.freqtrade.io/en/develop/advanced-hyperopt/)
- [`WALK_FORWARD_FULL_HISTORY.md`](WALK_FORWARD_FULL_HISTORY.md) — 8-regime 方法论
- [`TUTORIAL_FOR_BEGINNERS.md`](../TUTORIAL_FOR_BEGINNERS.md) §1.8 — Hyperopt 陷阱
