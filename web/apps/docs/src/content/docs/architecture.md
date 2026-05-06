---
title: 架构总览
description: 如何组合 Timescale / PostgREST / Supabase / Cloudflare Workers
---

## 数据层

```
Local 机器 (bots + DCA + pipelines)
  ├─ feather 文件          — freqtrade 原生 OHLC
  ├─ SQLite                — bot 交易状态
  ├─ JSON 文件              — event_dca_state / walk_forward_history
  └─ sync 脚本每 5 分钟推 →  VPS TimescaleDB

VPS oracle-arm-002 (NixOS)
  ├─ PostgreSQL 18 + TimescaleDB + pg_cron
  ├─ PostgREST   → https://api.panda.qzz.io
  ├─ GoTrue      → https://auth.panda.qzz.io
  ├─ Realtime    → wss://*.realtime.panda.qzz.io
  └─ nginx + ACME (自动 SSL)

Supabase 云 (免费)
  └─ kol_events / dca_log / sentiment / deribit (应用事件)

Cloudflare Workers (免费)
  └─ quant.panda.qzz.io  统一 Worker (SvelteKit Dashboard + /docs Starlight)
```

## 为什么这样切？

| 资源 | 用在哪 | 原因 |
|------|-------|------|
| VPS Timescale | OHLC (24M 行) + 回测 (万级 trade) | 重数据，Supabase 放不下 |
| Supabase | 小 JSONB 事件表 | 已在用，有 Realtime / Auth UI 等未来能力 |
| Cloudflare | 前端 + Worker | 全球 CDN + 0 egress |

## 认证

`auth.panda.qzz.io` 签发的 JWT 用共享 `JWT_SECRET` 直接过 PostgREST RLS —— 登录后访问 `api.panda.qzz.io` 时自带身份。未登录默认 `anon` 角色，看公开 view。
