# Crypto Quant — Public Frontend

Cloudflare Pages app that lets friends browse the quant system.
Talks to **3 data sources** (no single point of coupling):

```
Friends browser (quant.pages.dev)
  ├─► https://api.panda.qzz.io       (VPS PostgREST  — OHLC, backtests, trades)
  ├─► https://auth.panda.qzz.io      (VPS GoTrue     — JWT issuance)
  ├─► https://<proj>.supabase.co     (Supabase cloud — KOL, DCA log, sentiment)
  └─► /api/*                          (this site's Pages Functions — server-secret / merges)
```

## Why this split

| Layer     | What it serves             | Why there |
|-----------|----------------------------|-----------|
| VPS PostgREST | Heavy time-series (27M+ OHLC rows, 9K+ trades) | Supabase free tier = 500MB, can't fit |
| VPS GoTrue    | Auth (shared JWT_SECRET with PostgREST) | Browser JWT directly passes RLS on api.panda.qzz.io |
| Supabase      | Application events (KOL, sentiment, DCA log) | Already in use by backend pipelines; free tier fine |
| CF Pages      | Static HTML + client JS     | Global CDN, zero cost, auto-HTTPS |
| CF Pages Function | Aggregations / server-secret calls | Edge latency, keeps keys off client |

## Layout

```
web/
├── wrangler.toml        — CF Pages config + public env vars
├── package.json         — dev + deploy scripts
├── public/              — static files → Cloudflare Pages
│   ├── index.html       — hub (overview + top 10 runs)
│   ├── chart.html       — OHLC multi-granularity
│   ├── archive.html     — backtest archive (sort/filter/compare)
│   ├── login.html       — GoTrue signup/login
│   ├── css/app.css      — shared dark theme
│   └── js/
│       ├── config.js    — runtime config (API_BASE etc.)
│       ├── auth.js      — GoTrue client (JWT, refresh)
│       ├── api.js       — unified data client (vps/supabase/pages)
│       └── layout.js    — shared topbar with auth state
└── functions/
    └── api/
        └── summary.ts   — Pages Function: merged overview
```

## Local dev

```bash
cd web
npm install
npm run dev     # http://localhost:8788 (wrangler pages dev)
```

Since browser fetches hit `api.panda.qzz.io` directly (not localhost), dev
works identically to prod. You don't need the local md_http_server running.

## Deploy

```bash
# First time only: create the project
wrangler pages project create quant --production-branch=main

# Every deploy
npm run deploy          # wrangler pages deploy public --project-name=quant
```

On success you get a URL like `https://quant.pages.dev` — share with friends.
Each deploy is immutable and versioned; CF lets you rollback.

## Custom domain (optional)

Point a CNAME `quant.panda.qzz.io` → `quant.pages.dev` in your DNS,
then add the custom domain in the CF Pages dashboard.

## Auth notes

- **Friends can browse without logging in** — `api_anon` role has SELECT on all
  public views (see `migrations/002_public_api_views.sql`).
- **Logging in** via GoTrue issues a JWT with role `authenticated` —
  PostgREST's RLS would let authenticated users see extra views / data if we
  create such views. Right now we don't; all public views are free to read.
- **Sign-up is open** (GoTrue `GOTRUE_DISABLE_SIGNUP=false`). Flip it if you want
  invite-only. Alternatively add an allow-list check in a Pages Function.

## Adding new data exposures

When a new `quant.*` table should be visible to friends:

```sql
-- In migrations/00X_.sql, run on VPS
CREATE VIEW api.<thing> AS SELECT … FROM quant.<table>;
GRANT SELECT ON api.<thing> TO api_anon, authenticated, service_role;
GRANT SELECT ON quant.<table> TO api_anon, authenticated, service_role;
NOTIFY pgrst, 'reload schema';
```

Then add a helper in `public/js/api.js` under `export const vps`.

## Future optimization knobs

1. **Cache layer**: set `Cache-Control: public, max-age=60` on responses
   PostgREST returns. Cloudflare auto-caches at edge.
2. **KV for user preferences**: `wrangler kv namespace create qt_prefs`.
3. **R2 for large static blobs** (old plotly HTML, CSV dumps): zero egress cost.
4. **Durable Objects** for per-session state.
5. **Queues** for background processing triggered by user actions.
6. **Realtime**: if you want push updates, add Supabase Realtime (it works
   against the VPS Postgres if you run the realtime container alongside
   postgrest + gotrue — they all share the same DB).

## What's missing / honest TODOs

- [ ] `migrations/002_public_api_views.sql` needs to be applied on VPS
      (`ssh oracle-arm-002 sudo -u postgres psql -d api -f - < …`)
- [ ] No pair list endpoint — `chart.html` hardcodes 6 pairs. Could add
      `CREATE VIEW api.pairs AS SELECT DISTINCT pair FROM quant.ohlc;`
- [ ] Magic-link email requires GoTrue SMTP config (current setup likely
      sends via default which may not deliver reliably).
- [ ] Server-side rate limit not enforced. Cloudflare free tier includes
      some; add per-IP limit in wrangler config if abuse seen.
- [ ] No observability — add `AnalyticsEngine` to Pages Functions for free
      request metrics.
