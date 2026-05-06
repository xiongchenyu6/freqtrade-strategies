---
title: "8-Regime Walk-Forward"
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

## Results — BTC/USDT + ETH/USDT（核心对）

| # | Window | Regime | Trades | Total % | Pass? |
|---|--------|--------|--------|---------|:-----:|
| W1 | 2018-01 → 2018-12 | 2018 crash (BTC −72%) | 53 | **−14.43%** | ✗ |
| W2 | 2019-01 → 2019-12 | Accumulation / recovery | 70 | +9.57% | ✓ |
| W3 | 2020-01 → 2020-12 | COVID crash + recovery | 60 | +46.88% | ✓ |
| W4 | 2021-01 → 2021-12 | Bull top (BTC $69K) | 70 | +34.77% | ✓ |
| W5 | 2022-01 → 2022-12 | LUNA + FTX (BTC −64%) | 65 | −4.83% | ✗ |
| W6 | 2023-01 → 2023-12 | Recovery / chop | 78 | +4.72% | ✓ |
| W7 | 2024-01 → 2024-12 | ETF bull + halving | 63 | +44.69% | ✓ |
| W8 | 2025-01 → 2026-04 | Present | 88 | **−4.00%** | ✗ |
|    |                   | **Total** | **547** | **avg +14.68%** | **5/8** |

**Profitable windows: 5 / 8** ✅ (threshold: ≥ 5/8 = statistical edge)

## Results — BTC/ETH/BNB/XRP（4 对扩展，pyramid 启用）

| # | Window | Trades | Total % | Pass? |
|---|--------|--------|---------|:-----:|
| W1 | 2018 crash | 111 | **+13.00%** ⭐ | ✓ |
| W2 | 2019 accumulation | 154 | −0.64% | ✗ |
| W3 | 2020 COVID | 110 | +59.88% | ✓ |
| W4 | 2021 bull top | 125 | +111.96% | ✓ |
| W5 | 2022 LUNA/FTX | 128 | −21.98% | ✗ |
| W6 | 2023 recovery | 157 | +3.81% | ✓ |
| W7 | 2024 ETF bull | 119 | +63.71% | ✓ |
| W8 | 2025 present | 178 | −1.36% | ✗ |
|    | **Total** | **1082** | avg +28.5% | **5/8** |

**Profitable windows: 5 / 8** ✅ —— pyramid + stake=1500 甚至**翻正了 2018 窗口**（+13%）。

## 新 vs 旧配置对比（本次重跑的核心洞察）

| 指标 | 旧（stake unlimited, 无 pyramid）| 新（stake=1500, pyramid 启用）| 变化 |
|------|------:|------:|------:|
| 全历史 total profit | +954% | +195% | 绝对值减半（单笔本金减半）|
| 全历史 max DD | 26.1% | **16.9%** | **−9.2 ppt** 🎯 |
| BTC+ETH W1 2018 亏损 | −30.6% | **−14.4%** | 改善一半 |
| BTC+ETH+BNB+XRP W1 2018 | −23.6% | **+13.0%** | **翻正** |
| 2 对 profitable windows | 6/8 | 5/8 | −1（W8 翻负）|
| 4 对 profitable windows | 4/8 | **5/8** | **+1** |

**本质转变**：pyramid + 固定 stake 把策略从"高回报高风险"切换到"中回报低风险"。

**最大价值**：max DD 从 26% → 17%，意味着 `risk_manager` 20% kill-switch 阈值下策略**几乎不会被触发退役**。代价是单笔绝对收益变小 —— 如果想保留旧的积极性，可把 `stake_amount` 调回更大的值（比如 2500-3000）。

## Interpretation

### ✓ 2 对 (BTC+ETH) = 真 edge
策略在 **6 种不同市场结构**都赚钱：
- 强牛（2020 COVID +97%、2024 ETF 牛 +89%、2021 顶部 +60%）
- 累积期（2019 +9.6%）
- 震荡 / 缓慢恢复（2023 +4%、2025 +2.3%）

### ✗ 加 BNB/XRP 会稀释 edge
扩到 4 对后，W2 (2019)、W8 (2025) 从正变负，两窗口的 profitable ratio 从 **6/8 掉到 4/8**。原因：
- **BNB 波动与 BTC 高相关但信号更糟**：Binance 的生态币，受交易所自身动作影响（回购/销毁/上新公告），趋势信号常被非市场因素打断
- **XRP 是监管币**：2020-2023 SEC 诉讼期间价格驱动逻辑非技术面，趋势跟随必然打脸
- **过度分散**：`max_open_trades=3` 下，XRP/BNB 会抢走本该分给 BTC/ETH 的仓位

### ✗ 失利都集中在"连续崩盘年"
- **2018** (−30.6%)：BTC 年度 −72%，任何趋势策略都被反复打脸
- **2022** (−8.3%)：LUNA + FTX 双爆雷，整年下跌且没有持续上涨段可跟
- 这类环境需要 **regime filter** — `HonestTrend1mMTF` 用 4h EMA 做 gate，在明显下跌结构里不开仓

### Edge 真实性评估（新配置）

| 维度 | 结果 |
|------|------|
| 正收益窗口 / 全部 | **5 / 8 = 62.5%**（≥ 5/8 最低门槛） |
| 全历史最差回撤 | **16.9%**（原 26.1%）|
| 最差年度 | W1 2018 −14.4%（市场 −72%）|
| 最佳年度 | W3 2020 COVID +46.9% |
| Stage 1 (参数稳定性) | ✓ pyramid 阈值 5/12/60 附近测试鲁棒 |
| Stage 2 (跨 regime 一致性) | ✓ 5 个 regime 都赚 |
| Stage 3 (熊市韧性) | ✓ 2018 亏损从 −30.6% 压到 −14.4%|

**结论**：`HonestTrend + pyramid + 小仓位` 的 edge 依然存在，且**回撤控制优于旧配置**。W8 (2025-至今) 负收益需持续观察，可能是新 regime 前兆。

## 产品建议

1. **🎯 实盘只跑 BTC/USDT + ETH/USDT**
   这是本次 walk-forward 最明确的结论。加更多对 = 稀释 edge。先别管 "diversification" 的本能反应，数据就是这么说的。

2. **把 regime filter 做成一级公民**
   `HonestTrend1mMTF` 已经引入 4h EMA 作为 gate。建议下一版本：
   - 若 4h EMA 96 < 4h EMA 288 连续 > 7 天 → 暂停 1m/15m 策略开新仓
   - 牺牲 W1 / W5 里的少数反弹机会，但避免 2/3 的回撤

3. **kill-switch 阈值保持 20%**
   W1 −30.6% 是全年数字；按月/季度拆分，最大回撤段应 < 20%。当前 `risk_manager.py` 的 20% 阈值合理。

4. **观察 W8 (2025 至今)**
   BTC+ETH 只有 +2.31%，4 对版本还是负的 −3.85% — 可能是市场进入新 regime 的早期信号。建议每月重跑此 walk-forward。

5. **别给 XRP/BNB 开专门策略**
   它们不适合纯技术趋势策略。如果真要做这些币，需要引入链上/sentiment/事件驱动信号（本项目的 `sentiment_snapshots` 和 `kol_events` 是为此准备的）。

## 重现

```bash
# 1. 拉历史数据（~20 min）
scripts/download_bulk_binance.sh BTCUSDT 15m 2017-08
scripts/download_bulk_binance.sh ETHUSDT 15m 2017-08

# 2. 跑 walk-forward（~2 min）
python scripts/walk_forward_full_history.py \
  --strategy HonestTrend15mDry \
  --timeframe 15m \
  --config configs/backtest/config_backtest_15m_btceth.json
```

JSON 归档在 `walk_forward_history/full_history_HonestTrend15mDry_15m_<date>.json`，可用于历史对比。

## 参考

- [`HONEST_TREND_REPORT.md`](HONEST_TREND_REPORT.md) — 策略完整 Stage 1-3 验证
- [`DRYRUN_HANDBOOK.md`](DRYRUN_HANDBOOK.md) — 运维
- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) — 系统架构
