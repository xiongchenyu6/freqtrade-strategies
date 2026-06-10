# Self-service backtest playground — plan

**Problem (2026-06-10):** a visitor opened the dashboard and didn't know how to "create
backtests under his own account / play with it." Root cause, after reading the app:

The SvelteKit app (`web/apps/app`) ALREADY has — GoTrue (Supabase Auth) JWT sessions
(`lib/auth.ts`, `qt_jwt`/`qt_authed` cookies), a `/login` route + topbar login button, an
anon→authed funnel (anon sees public-preview aggregates, authed sees richer tables), and
many rich **read-only** views (`/strategies`, `/strategies/[name]`, `/nautilus`, `/hyperopt`,
`/portfolio`, `/signals`, `/factors`, `/dca`, `/semis`, …).

What it LACKS: **self-service backtest *creation*.** Every "backtest" surface shows the
OWNER's runs (`backtest_runs` / `nautilus_backtests`). There is no form/action for a
logged-in visitor to run *their own* backtest. That's the gap.

## Hard constraint
A backtest = a Nautilus `BacktestNode` run = **Python compute**. Cloudflare Workers (where
the app runs) **cannot run Python**. So self-service backtests REQUIRE a backend job runner.

## Architecture
```
SvelteKit (CF Worker)  --POST /backtest-->  api.backtest_jobs (PostgREST insert, RLS by user)
                                                   │  status=queued
                                  ┌────────────────┘ poll
   runner service (Python, on the game box — 16c/27GB, has the venv + catalogs)
     picks a queued job → runs Nautilus BacktestNode with a PREDEFINED strategy + the
     user's params over stored bars → writes api.backtest_results (user_id, metrics,
     equity curve) → status=done
                                                   │
SvelteKit polls/realtime  <--------- results scoped to the user (RLS via the GoTrue JWT)
```

## Key decisions (locked unless owner overrides)
- **No arbitrary code.** Expose PREDEFINED strategies (HonestTrend, Accumulator/DCA,
  Donchian) with **parameter forms** (asset, timeframe, EMA/risk params, date range). Users
  "play" via forms/sliders, never code. Eliminates RCE/abuse surface.
- **Compute = the game box** (already has `nautilus_equity/.venv` + the parquet catalogs).
  A small systemd runner polling `backtest_jobs`. The oracle boxes (956MB) are too small.
- **Multi-tenancy = PostgREST RLS** keyed on the GoTrue JWT `sub`. Users see only their own
  jobs/results; the owner's curated runs stay public (a `public` flag).
- **Limits**: per-user rate cap (e.g. N/day), bounded date range + asset universe, job
  timeout, queue-depth cap. Backtests are CPU-heavy — protect the runner.
- **Guardrail-aligned**: this is TOOLS for users to run their OWN backtests and see their
  OWN results — no pooled funds, no 代客理财. Per-user LIVE trading is explicitly OUT (IB
  single-session, KYC, real money — different and much harder; "play" = backtests only).

## Phasing
- **Phase 0 — onboarding clarity (½ day, frontend-only, direction-agnostic):** make it
  obvious what a visitor can do. A hero/empty-state on the backtest surfaces: "These are the
  owner's runs — sign in to run your own (coming)." Ensure the `/login` CTA is prominent.
  Low risk; ships value immediately.
- **Phase 1 — backtest MVP:** `backtest_jobs`/`backtest_results` schema (additive migration);
  the game-box runner service (predefined strategies + param validation); a "New backtest"
  form route + a "My backtests" view; RLS scoping. The real feature.
- **Phase 2 — richer:** compare runs, public share links, a community leaderboard, parameter
  sweeps.

## Open question for the owner
Confirm the target is **(A) login → run/save your own backtests** (this plan), not
**(B) users connecting their own live brokerage accounts** (out of scope per guardrails).
Then: Phase 0 now, Phase 1 next.
