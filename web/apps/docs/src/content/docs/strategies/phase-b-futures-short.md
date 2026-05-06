---
title: "Phase B：期货对冲"
description: "PHASE_B_FUTURES_SHORT"
---

# Phase B：期货做空山寨对冲

**日期**：2026-04-22
**目标**：在 Phase A（BTC 交给 DCA，trend 策略只跑山寨 ETH/BNB/SOL）基础上，引入**期货做多+做空**，用空仓对冲 LUNA-级熊市风险。

## 策略设计

### `HonestTrendFutures`（继承 `HonestTrendGeneric`）

```python
can_short = True
stoploss = -0.08              # 期货必须有硬止损（spot 可以 -0.99）
FNG_SHORT_BLOCK = 70          # FnG > 70 禁做空（不空 euphoria）
leverage = 1.0                # 1x，零强平风险
```

**Short 信号**（mirror long）：
- `crossed_below(ema_fast, ema_slow)`
- `minus_di > plus_di`
- `adx > threshold`
- `volume > volume_sma`
- `fng < FNG_SHORT_BLOCK (70)` —— 关键过滤，避免牛市轧空

**Short 出场**：
- `crossed_above(ema_fast, ema_slow)`

### 参数继承（from `HonestTrendGeneric`）
EMA / ADX / min_hold / pyramid 全部继承 base class —— **同一套参数跑 long+short**（经 WF 验证足够稳健）。

## 回测结果

### 全历史（2020-09-14 → 2026-04-21，5.6 年）

| 指标 | A5 spot long-only | **Futures L+S** | Δ |
|------|------:|--------:|------:|
| Trades | 559 | **901** (508L + 393S) | +342 |
| Profit | +166% | +157% | −9 ppt |
| Long profit | — | +107% | — |
| **Short profit** | — | **+50%** 🎯 | — |
| **Max DD** | 14.77% | **7.84%** | **−6.93** ✅ |
| **Calmar** | 9.45 | **18.72** | **翻倍** ⭐ |
| Sortino | 1.66 | **2.56** | +0.9 |

### 8-Regime Walk-Forward

| Window | A5 Spot | **Futures L+S** | Δ |
|--------|--------:|--------:|------:|
| W1 2018 crash | +12.31% | n/a (无 futures) | — |
| W2 2019 accum | +10.38% | n/a | — |
| W3 2020 COVID | +14.94% | +9.91% | −5.0 |
| W4 2021 bull | +143.30% | +91.20% | −52.1 |
| **W5 2022 LUNA** | **−16.93% 🩸** | **+47.62% 🔥** | **+64.6** |
| W6 2023 recovery | +18.27% | +18.71% | +0.4 |
| W7 2024 ETF | +23.79% | +17.15% | −6.6 |
| W8 2025 present | −1.23% | −6.43% | −5.2 |

**关键发现**：在 5/6 "平凡"窗口上，shorts 略微拖累（funding 成本 + 少量失败空单）；但在 **1/6 危机窗口 (2022 LUNA/FTX)，shorts 把 −17% 变成 +48%** —— 单窗口 +65 ppt 的 tail-risk hedge。

### 保险理论解释

把 shorts 当作**"年化成本 ~4 ppt，熊市赔付 60+ ppt"的保险**。保费看起来贵，但黑天鹅出现时 10 倍回本。这正是 tail-risk hedging 该有的 payoff profile。

## 部署

### 已创建
| 文件 | 说明 |
|------|------|
| `strategies/HonestTrendFutures.py` | L+S 策略类 |
| `configs/backtest/config_backtest_15m_futures_a5.json` | 回测 config |
| `configs/config_dryrun_honestfutures15m.json` | dry-run config, port 8084 |
| `scripts/start_honest_trend.sh` | 新增 `futures` 和 `all` 模式 |

### 启动
```bash
./scripts/start_honest_trend.sh futures   # 单独启动
./scripts/start_honest_trend.sh all       # 与 dryrun + mtf 并行
```

### Port 分配
- 8082 — HonestTrend15m (spot long-only, A5 alts)
- 8083 — HonestTrend1mMTF (spot 1m long-only)
- **8084 — HonestTrendFutures (futures L+S) 🆕**
- 8081 — live bot (1m, BTC+ETH+BNB, **old — 尚未切 A5**)

### Telegram
启用（通过 `FREQTRADE__TELEGRAM__TOKEN` 环境变量注入）—— 会在同一 chat 接收来自 `HonestTrendFutures-DRYRUN` 的通知。

## 观察清单（dry-run 1-2 周）

- [ ] 资金费率（Funding rate）真实成本是否和回测一致（~4 ppt 年化）
- [ ] Short entries 是否在熊市触发（FnG 过滤是否 OK）
- [ ] Stoploss -8% 是否被 wick/gap 频繁穿破
- [ ] 1x 杠杆是否真的没有强平风险
- [ ] Pyramid 规则在 short 侧是否正确行为
- [ ] Drawdown 是否维持在回测 7.84% 数量级

## 未来：Phase B+

### B+1. Leverage 2x（待验证）
- DD 7.84% 有 10+ ppt headroom 到 20% kill-switch
- 理论上 2x 可翻倍利润
- 但强平风险进入：插针 20% 时 2x 杠杆即爆仓
- **建议**：dry-run 稳定后，先在 backtest 测 2x，walk-forward 确认 W5 LUNA 不爆

### B+2. FnG < 30 强化空
- 当前 FnG < 70 才允许空，但没有区分 30 vs 60
- 可尝试：FnG < 30 时 stake × 1.5 (恐慌底增仓空)
- 风险：V-型反转时被顶

### B+3. Funding rate filter
- 当前不检查 funding rate
- 极端高负 funding（shorts 被额外 penalize）时应避免开空
- 可在 `confirm_trade_entry` 里查最近 8h funding > 阈值则拒单

### 不做
- **不在山寨 futures 加 XRP/DOGE**（回测已验证这俩在 spot 上就是 DD 放大器）
- **不把 BTC 加进 futures 池子**（BTC 走 DCA，不混）
- **不超过 2x 杠杆**（1x→2x 已经是 risk doubling，3x+ 是赌博）

## 回滚路径

如果 dry-run 2 周表现差于回测预期（DD 超过 12% 或 short profit 为负）：
1. 停 futures bot：`pkill -f HonestTrendFutures`（emergency_stop.sh 也会带走它）
2. 继续跑 A5 spot long-only（没有 short 的保险）
3. 记录失败原因，更新本文档"失败实验"章节

## 关键教训（尚待 dry-run 验证）

1. **Shorts 不为常态赚钱，为危机保命**：5/6 窗口拖累，1/6 窗口救命
2. **1x 杠杆是期货"最安全"起点**：没有强平，纯吃方向 alpha
3. **FnG 过滤是关键**：如果在牛顶允许做空，会被轧到怀疑人生
4. **Funding 是隐性税**：年化 4-10%，盘整市最痛苦
