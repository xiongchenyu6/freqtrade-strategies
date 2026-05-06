---
title: "Go-Live 清单"
description: "GO_LIVE_CHECKLIST"
---

# Go-Live Checklist

> **2026-04-22 架构更新**：本清单覆盖 Phase A (spot alts trend) + Phase B (futures L+S) + Smart DCA 双通道全部组件。每个组件独立 go-live，可按节奏分批打开。

## 架构速查

| 组件 | Config | 市场 | Key 要求 | Live flag |
|------|--------|------|---------|-----------|
| HonestTrend15mDry | `config_dryrun_honest15m.json` | Binance spot | spot trading only | — |
| HonestTrend1mMTF | `config_dryrun_honest1mmtf.json` | Binance spot | spot trading only | — |
| **HonestTrendFutures** | `config_dryrun_honestfutures15m.json` | **Binance USDT-M futures** | **futures trading only** | — |
| Weekly DCA | `crypto-dca.timer` → `dca_executor.py` | Binance spot | spot buy only | `DCA_LIVE_ENABLED=true` |
| **Event DCA** | `crypto-event-dca.service` → `event_dca_bot.py` | Binance spot | spot buy only | `DCA_LIVE_ENABLED=true` |

---

## Phase 1: Dry-Run 验证（每个组件独立，最少 2-4 周）

所有组件必须先在 dry-run 通过以下门槛：

### HonestTrend15mDry / HonestTrend1mMTF (spot long-only)
- [ ] 累计 ≥ 20 笔交易（统计意义）
- [ ] Rolling PF ≥ 1.2
- [ ] 最大 DD < 12%（A5 回测 14.77%，dry-run 应类似或更好）
- [ ] 0 次 RETIRED 事件
- [ ] Walk-forward 月度 check 至少 4/8 窗口正收益

### HonestTrendFutures (futures long+short)
- [ ] 累计 ≥ 30 笔交易（L+S 频率更高）
- [ ] Long / Short 比例介于 30-50% 之间（证明 short 信号真触发了）
- [ ] Funding rate 实际成本 ≤ 年化 6%（回测 ~4%，留余量）
- [ ] 最大 DD < 10%（回测 7.84%）
- [ ] Stoploss -8% 触发频率 ≤ 5%/月
- [ ] Walk-forward 5/6 窗口正收益（W5 LUNA 类场景验证）

### Smart DCA（两通道）
- [ ] 至少 1 次周一触发（下周一 `journalctl --user -u crypto-dca.service`）
- [ ] Telegram 推送正常，FnG/cycle 倍率看起来合理
- [ ] 事件通道至少触发 1-2 次（或市场平静 1 个月则跳过此条）
- [ ] Supabase `dca_log` 表有记录

---

## Phase 2: 准备 live 密钥

### 2.1 Spot 策略 + DCA（共用一套 spot API key）

Binance API key 设置：https://www.binance.com/en/my/settings/api-management

- [ ] 权限：**只** 启用 Spot Trading
- [ ] 权限：**禁用** Withdrawals / Margin / Lending
- [ ] IP 白名单：服务器外网 IP
- [ ] 加入 SOPS：
  ```bash
  sops edit secrets.env
  # 添加：
  # BINANCE_API_KEY=<key>
  # BINANCE_API_SECRET=<secret>
  ```

### 2.2 Futures 策略（**独立** API key）

**必须另开一套 API key，不要复用 spot 的**（安全隔离 + Binance 权限分离）：

- [ ] 新建 Binance API key，**只** 启用 Futures Trading
- [ ] **禁用** Spot / Withdrawals / Margin
- [ ] IP 白名单同上
- [ ] 加入 SOPS：
  ```bash
  sops edit secrets.env
  # 添加：
  # BINANCE_FUTURES_API_KEY=<key>
  # BINANCE_FUTURES_API_SECRET=<secret>
  ```
- [ ] 修改 `config_dryrun_honestfutures15m.json` 复制为 `config_live_honestfutures15m.json`，`dry_run: false`
- [ ] 更新 `start_honest_trend.sh` 的 `start_futures` 函数注入 futures keys

### 2.3 DCA live flag

- [ ] 在 SOPS `secrets.env` 添加 `DCA_LIVE_ENABLED=true`（**两个 DCA 通道共用这个 flag**）

---

## Phase 3: 资金分配

```
总资金: 100,000 USDT

分工（Phase A/B 架构）:
  Spot 钱包（ETH/BNB/SOL trend + DCA 累积 BTC):  60,000 USDT
    ├─ Trend bots 共享: 10,000 USDT (3 bot × 3,500 USDT avg)
    ├─ DCA 累积（周+事件）:           50,000 USDT（积累中）
    │
  Futures 钱包（隔离，小额尝试）:        5,000 USDT
    └─ HonestTrendFutures L+S
    
  稳定币收益:                          25,000 USDT
  Reserve（不动）:                     10,000 USDT
```

**原则**：
- Futures 从 5,000 USDT 起步（回测 DD 7.84% → 最坏损失 ~$400），证明 2 个月稳定再加
- Trend 从 10,000 USDT 起（原定额度）
- DCA 周定投 $500 base × 3.0 max = $1500/周最大 → 1 年预算 ~$26K（留给 50K 池子 1.9 年慢慢累积）

---

## Phase 4: Go-Live 顺序（**分批打开，不要一起上**）

### 第 1 批（第 1-2 周）：Spot trend bots
```bash
# 1. 启动 15m spot live
./scripts/start_honest_trend.sh live    # 旧 1m live 路径，或新写一个 15m live 启动器
```
- 观察 2 周，每天看 Telegram
- 确认实盘 vs dry-run 盈亏差 < 1% / 周

### 第 2 批（第 3 周）：Weekly DCA go-live
```bash
sops edit secrets.env
# 添加 DCA_LIVE_ENABLED=true
# 重启 crypto-dca.timer（下周一自动触发）
```
- 首次触发时手动盯一次，核对 Binance 实际成交 vs Telegram 预告

### 第 3 批（第 5 周）：Event DCA go-live
```bash
# DCA_LIVE_ENABLED 已设，只需重启 event daemon
systemctl --user restart crypto-event-dca.service
```
- 等一次真正的 crash 触发（可能要等几周）
- 首次触发后检查：cooldown / monthly budget 真的扣了吗？

### 第 4 批（第 7 周或更晚）：Futures L+S go-live

**这是最危险的一步**。必须先满足：
- [ ] 前 3 批全部稳定 ≥ 2 周
- [ ] Futures API key 测试过（read-only）
- [ ] 明确知道强平价（1x 杠杆不会强平，但 stoploss -8% 会吃掉）
- [ ] Binance futures 钱包转入 5,000 USDT

```bash
# 启动（假设已准备好 config_live_honestfutures15m.json）
./scripts/start_honest_trend.sh futures-live    # 需要先加这个 mode
```

---

## Phase 5: 持续监控（永远）

### 每天（Telegram 看即可）
- [ ] 3 个 bot 的 heartbeat 都在
- [ ] 无 RETIRED 告警
- [ ] Funding rate 通知（如有）
- [ ] Event DCA 触发通知（如有）

### 每周
- [ ] `risk_monitor.py status` 看 DD 和 PF
- [ ] 对比本周 dry-run vs live 实际成交（滑点 / 延迟）
- [ ] 看 Event DCA `event_dca_state.json` 的 monthly budget 使用情况

### 每月
- [ ] Walk-forward 月度验证（`crypto-walkforward.timer` 自动跑）
- [ ] Futures funding 累计成本（实际 vs 回测预期 4%）
- [ ] 资金曲线 vs 大盘对比（Phase B 应该在熊时 outperform）

---

## Emergency Procedures

### 全局紧急停机
```bash
./emergency_stop.sh
```
杀全部 `freqtrade trade` 进程 + 停 timers + Telegram 告警。**注意**：event_dca daemon 需要单独停：
```bash
systemctl --user stop crypto-event-dca.service
```

### 只停某个 bot
```bash
# 只停 futures（保留 spot）
pkill -TERM -f "config_dryrun_honestfutures15m"

# 只停 event DCA（保留周定投）
systemctl --user stop crypto-event-dca.service
```

### 禁止开新仓，保留现有
```bash
# 通过 API（每个 bot 独立）
curl -X POST http://127.0.0.1:8082/api/v1/stopentry  # spot 15m
curl -X POST http://127.0.0.1:8084/api/v1/stopentry  # futures

# 或 Telegram /stopentry（会发到所有有 token 的 bot）
```

### 强平所有 futures 仓位
```bash
# Telegram 发给 HonestTrendFutures：
# /forceexit all
# 或直接去 Binance futures UI 市价全平
```

---

## Risk Rules（硬规则，不可绕过）

| 规则 | 限制 | 谁来强制 |
|------|------|---------|
| Max open trades per bot | 3 | config `max_open_trades` |
| Max per-position | 1,500 USDT × pyramid 2.6 = 3,900 USDT | config `stake_amount` + pyramid |
| Account max DD | 15% → PAUSE, 20% → RETIRE | `risk_manager.py` |
| **Futures 杠杆** | **1x（绝不超过 2x）** | `HonestTrendFutures.leverage() → 1.0` |
| Futures stoploss | **−8%**（硬止损） | `HonestTrendFutures.stoploss = -0.08` |
| Short FnG 过滤 | FnG > 70 禁空 | `HonestTrendFutures.FNG_SHORT_BLOCK` |
| DCA 月预算 | Weekly $500 × 3x max / Event $2000/月 | env vars + executor clamp |
| DCA cooldown | 事件 72h，单月最多 3 次 | `event_dca_state.json` |
| Spot stoploss | 无（`-0.99`），信号驱动退出 | IStrategy `stoploss = -0.99` |

---

## What NOT to Do

- ❌ **不要把所有 4 个组件一天之内全部 go-live** — 分批，每批观察 ≥ 2 周
- ❌ **不要让 futures API key 也有 spot 权限** — 隔离是第一道防线
- ❌ **不要跳过 `DCA_LIVE_ENABLED` 这道锁** — 代码里专门加的，就是为了防止误触
- ❌ **不要在 live 期间手改策略参数** — 想调参请先回到 dry-run 调
- ❌ **不要把 futures 杠杆提到 2x+** — 回测 DD 7.84%，2x 就是 15.7%，距离 20% kill-switch 只剩 4 ppt 余量
- ❌ **不要覆盖 FnG short 过滤** — 2021 Q4 那种 FOMO 顶部做空会被轧到地板
- ❌ **不要手动平仓然后重启 bot** — bot 会重新进场，你只是浪费了手续费
- ❌ **不要同一 Binance 账号跑多个 live spot bot**（futures 可以，因为仓位隔离）

---

## 过渡后的下一步

- **Phase B+1**：Futures 2x 杠杆（需要重新 walk-forward 验证 W5 LUNA 不爆）
- **Phase B+2**：Funding rate filter（高 funding 时避免做空）
- **Deribit Phase 2**：从监控升级到自动写 CSP 期权
- **V5**：ETH / SOL 的 event DCA（当前只跑 BTC）

全部都等当前 4 组件 live 稳定 3+ 个月后再说。
