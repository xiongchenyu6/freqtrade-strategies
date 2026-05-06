---
title: Architecture overview
description: How Timescale / PostgREST / Supabase / Cloudflare Workers compose
---

## Data layer

```
Local machine (bots + DCA + pipelines)
  ├─ feather files         — freqtrade-native OHLC
  ├─ SQLite                — bot trade state
  ├─ JSON files            — event_dca_state / walk_forward_history
  └─ sync script every 5 min →  VPS TimescaleDB

VPS oracle-arm-002 (NixOS)
  ├─ PostgreSQL 18 + TimescaleDB + pg_cron
  ├─ PostgREST   → https://api.panda.qzz.io
  ├─ GoTrue      → https://auth.panda.qzz.io
  ├─ Realtime    → wss://*.realtime.panda.qzz.io
  └─ nginx + ACME (auto SSL)

Supabase cloud (free tier)
  └─ kol_events / dca_log / sentiment / deribit (app events)

Cloudflare Workers (free tier)
  └─ quant.panda.qzz.io  unified worker (SvelteKit dashboard + /docs Starlight)
```

## Why this split?

| Resource | Used for | Reason |
|------|-------|------|
| VPS Timescale | OHLC (24M rows) + backtests (10K+ trades) | Heavy data, Supabase can't hold it |
| Supabase | Small JSONB event tables | Already in use; gives us Realtime / Auth UI room to grow |
| Cloudflare | Frontend + Worker | Global CDN + 0 egress |

## Authentication

JWTs issued by `auth.panda.qzz.io` pass PostgREST RLS directly via the shared `JWT_SECRET` — once logged in, requests to `api.panda.qzz.io` carry identity automatically. Unauthenticated users hit the `anon` role and see public views only.
