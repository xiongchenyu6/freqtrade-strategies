# Event-Driven DCA（暴跌加仓机器人）

**日期**：2026-04-22
**目标**：在周定投基础上，捕捉闪崩/暴跌自动加仓 BTC，提升 BTC 获取率。

## 为什么做

纯周定投（`crypto-dca.timer`）错过周中闪崩。回测（见下）显示混合策略（周 + 事件）相对纯周能多获得 **+6.4% 的 BTC**，相当于复利 8 年 +2.24 BTC。

**设计原则**：事件触发不替代周定投，而是**加码**。周定投保证"不漏年"，事件触发优化"均成本"。

## 信号层次（按重要性）

| 信号 | 阈值 | 检测方式 | 8 年历史次数 |
|------|------|---------|:---------:|
| CAPITUL | 30d 回撤 > 25% | REST 轮询 5min | 109 |
| SUSTAIN | 24h 跌幅 > 10% | REST 轮询 5min | 47 |
| FAST    | 5m 跌幅 > 5%  | WebSocket 实时 | 18 |
| FLASH   | 1m 跌幅 > 3%  | WebSocket 实时 | 8 |

**alpha 分布**：CAPITUL + SUSTAIN 贡献 80%+ 的价值。FLASH 虽然罕见但单次价值大（如 2020-3-12）。

## 回测结果（2018-02 → 2026-04，$75,841 BTC 现价）

| 策略 | Buys | USDT | BTC | 均成本 | 当前市值 | ROI |
|------|-----:|----:|-----:|------:|------:|---:|
| A 纯周 $500 base | 429 | $247K | 17.75 | $13,918 | $1.35M | +445% |
| B 纯事件 $1000x3/月 | 119 | $127K | 10.81 | $11,731 | $820K | +547% |
| **C 混合 $350w+$700e** | **548** | **$262K** | **19.99** | **$13,090** | **$1.52M** | **+479%** |
| X 一次性 $208K | 1 | $208K | 20.19 | $10,300 | $1.53M | +636% |

**每 $1M 获得 BTC 数**：
- 纯周 A: 71.8 BTC
- 混合 C: **76.4 BTC** (+6.4%)
- 纯事件 B: 85.2 BTC (最高，但预算用不完)

## 实现架构

```
                    ┌──────────────────┐
                    │  event_dca_bot   │  always-on daemon
                    │                  │
   Binance WS  ──►  │  PriceBuffer     │  ring 5min tick
   aggTrade         │  ↓ detect        │
                    │  FLASH / FAST    │
                    │                  │
   Binance REST ──► │  poll 5min       │
   klines           │  SUSTAIN / CAPITUL│
                    │                  │
                    │  ↓               │
                    │  State (cooldown │  JSON file
                    │  + budget tracker)│
                    │  ↓ if OK          │
                    │  spawn subprocess│
                    └─────┬────────────┘
                          │
                          ▼
              python dca_executor.py
                --base $amount
                --trigger event:FLASH
                [--live if DCA_LIVE_ENABLED]
                          │
                          ▼
                Supabase + Telegram
                (possibly Binance buy)
```

## 关键文件

| 文件 | 用途 |
|------|------|
| `strategies/event_dca_bot.py` | 主 daemon（WebSocket + REST polling） |
| `scripts/backtest_event_dca.py` | 回测脚本（可复现验证） |
| `start_event_dca_bot.sh` | sops 启动包装 |
| `~/.config/systemd/user/crypto-event-dca.service` | systemd always-on unit |
| `event_dca_state.json` | 运行状态（cooldown + monthly budget） |

## 配置（环境变量）

```bash
EVENT_DCA_MONTHLY_BUDGET=2000    # 每月 event 预算（默认 $2000）
EVENT_DCA_PER_TRIGGER=700        # 每次基础金额（FnG<20 ×1.5 / >60 ×0.7）
EVENT_DCA_COOLDOWN_HOURS=72      # 触发后冷却（防止同一暴跌重复买）
EVENT_DCA_MAX_PER_MONTH=3        # 每月最多触发次数
DCA_LIVE_ENABLED=true            # 打开后才真下单（否则仅 log + Telegram）
```

默认**不会真买**（`DCA_LIVE_ENABLED` 未设置 = dry-run）。

## 运维

```bash
# 状态
systemctl --user status crypto-event-dca.service
journalctl --user -u crypto-event-dca.service -f

# 手动测试
python strategies/event_dca_bot.py --self-test

# 查看最近触发历史
cat event_dca_state.json | jq

# 重启
systemctl --user restart crypto-event-dca.service

# 停止
systemctl --user stop crypto-event-dca.service
```

## 开启 live 的步骤

1. 确保 `crypto-dca.service`（周定投）的 live 已经 soak 过 2+ 周（dry-run 记录正常）
2. 在 SOPS secrets.env 加 `DCA_LIVE_ENABLED=true`
3. 在 SOPS 确认 `BINANCE_API_KEY` / `BINANCE_API_SECRET` 存在（spot 买入权限即可）
4. 重启：`systemctl --user restart crypto-event-dca.service`
5. 第一周：**手动观察每次触发**，Telegram 预警 + Binance 实际成交匹配

## 边界条件

```python
# 硬规则，不可改
MAX_PER_MONTH = 3               # 避免一个月内狂买
COOLDOWN_HOURS = 72             # 同一暴跌只买一次
MONTHLY_BUDGET = $2000          # 全年上限 $24K
MIN_AMOUNT_USDT = $50           # 预算剩 < $50 时不触发
WEBSOCKET_RECONNECT_DELAY = 5s  # 断线自动重连

# 软规则（可调）
FLASH 仅触发 cooldown 内 60s 一次（避免同分钟重复）
FnG < 20 → amount × 1.5 (恐慌底加仓)
FnG > 60 → amount × 0.7 (greed 区减半)
```

## 失败模式 + 恢复

| 症状 | 可能原因 | 处理 |
|------|---------|------|
| 1 个月没触发 | 市场温和/无暴跌 | 正常，周定投继续跑就行 |
| WS 断线频繁 | 网络/防火墙 | `systemctl --user restart` |
| Telegram 无推送 | token 错误 | 检查 SOPS secrets.env |
| 触发但没下单 | `DCA_LIVE_ENABLED` 未设 | 符合预期（dry-run） |
| Binance 下单失败 | API key/余额 | 查 Binance API 日志 |
| 状态文件损坏 | 意外退出 | 删除 `event_dca_state.json` 重建 |

## 未来演进

- **V2. 爆仓流加入信号**：订阅 `!forceOrder@arr`，当 1h 爆仓 > $300M 时加权触发
- **V3. Supabase UI**：把触发历史可视化到 dashboard port 3001
- **V4. 反向检测**：检测暴涨（泵），在 FnG > 90 时减仓（暂不做，违反 long-only BTC 哲学）
- **V5. 多币支持**：ETH / SOL 的事件 DCA（用当前框架，仅换 SYMBOL）

## 已知限制

1. **WebSocket 断线期间的 FLASH/FAST 会漏**（自动重连但数据有缺口）
2. **REST 轮询 5min 间隔**，理论上 30d DD 可能在 5min 内超阈值但已错过（但这种级别的信号几乎不可能只持续 <5min）
3. **Binance REST 限频**：5min 一次轮询远低于 1200req/min 上限，不会触限
4. **FnG API 免费额度**：alternative.me 无明确 rate limit，但建议不超过 1 次/min
