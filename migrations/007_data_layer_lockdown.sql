-- Commercial lockdown — data-layer enforcement of what the UX gate already
-- blocked. Two-layer split:
--
--   Public preview views (anon + authenticated + service_role SELECT):
--     api.public_stats              — single-row aggregate KPIs
--     api.public_ohlc_1d            — daily OHLC, BTC/ETH/BNB/SOL only
--     api.public_event_triggers     — ts/kind/severity/fng (NO amount, NO price)
--
--   Detail views (authenticated + service_role only; anon REVOKED):
--     api.backtest_runs, api.backtest_trades,
--     api.ohlc_1d, api.ohlc_1h_recent, api.ohlc_15m_recent,
--     api.wf_results, api.live_trades, api.event_dca_triggers
--
-- Also revokes anon on the underlying quant.* tables so Realtime CDC filters
-- anon subscribers to 0 rows (api.* views are SECURITY DEFINER so they still
-- work for authenticated clients — the view owner retains grants).
--
-- Apply from VPS:
--   ssh oracle-arm-002 sudo -u postgres psql -d api -f - < migrations/007_data_layer_lockdown.sql

BEGIN;

-- ============================================================================
-- Public preview views
-- ============================================================================

-- 1-row aggregate across all backtest_runs. Enough to tell a visitor
-- "this system has X runs, best Calmar Y, best Sharpe Z" without leaking
-- a single row.
CREATE OR REPLACE VIEW api.public_stats AS
SELECT
  count(*)::int                             AS total_runs,
  COALESCE(sum(total_trades), 0)::bigint    AS total_trades,
  count(DISTINCT strategy)::int             AS distinct_strategies,
  round(max(total_profit_pct)::numeric, 2)  AS best_profit_pct,
  round(max(calmar)::numeric, 2)            AS best_calmar,
  round(max(sharpe)::numeric, 2)            AS best_sharpe,
  round(max(sortino)::numeric, 2)           AS best_sortino,
  round(max(win_rate_pct)::numeric, 2)      AS best_win_rate,
  round(min(max_drawdown_pct)::numeric, 2)  AS min_max_dd,
  max(imported_at)                          AS last_updated
FROM quant.backtest_runs;

-- Daily OHLC limited to the 4 pairs that power the public DCA simulator.
-- Other pairs (for /chart) stay behind auth on api.ohlc_1d.
CREATE OR REPLACE VIEW api.public_ohlc_1d AS
SELECT pair, bucket, open, high, low, close, volume
FROM quant.ohlc_1d
WHERE pair IN ('BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT');

-- Event triggers with the proprietary fields stripped. Enough for the
-- public simulator's event layer (needs severity only); hides how much
-- we actually buy and at what price.
CREATE OR REPLACE VIEW api.public_event_triggers AS
SELECT ts, kind, severity, fng
FROM quant.event_dca_triggers;

GRANT SELECT ON
  api.public_stats,
  api.public_ohlc_1d,
  api.public_event_triggers
TO anon, authenticated, service_role;

-- ============================================================================
-- Revoke anon on detail views
-- ============================================================================
REVOKE SELECT ON
  api.backtest_runs,
  api.backtest_trades,
  api.ohlc_1d,
  api.ohlc_1h_recent,
  api.ohlc_15m_recent,
  api.wf_results,
  api.live_trades,
  api.event_dca_triggers
FROM anon;

-- ============================================================================
-- Revoke anon on underlying quant.* tables so Supabase Realtime's per-role
-- CDC filtering zero-rows anon subscribers. api.* views are SECURITY DEFINER
-- (owner: freeman.xiong), so authenticated clients still see everything
-- through the views.
-- ============================================================================
REVOKE SELECT ON
  quant.backtest_runs,
  quant.backtest_trades,
  quant.ohlc_1d,
  quant.ohlc_1h,
  quant.ohlc_15m,
  quant.wf_results,
  quant.trades,
  quant.event_dca_triggers
FROM anon;

-- Undo the default-privileges inheritance set in migration 002 so new tables
-- in quant.* aren't auto-granted to anon going forward.
ALTER DEFAULT PRIVILEGES IN SCHEMA quant REVOKE SELECT ON TABLES FROM anon;

NOTIFY pgrst, 'reload schema';
COMMIT;

\echo
\echo === verification plan ===
\echo Anon probes:
\echo   curl -sI https://api.panda.qzz.io/backtest_runs       # expect 401
\echo   curl -s  https://api.panda.qzz.io/public_stats        # expect JSON 1 row
\echo   curl -s  https://api.panda.qzz.io/public_ohlc_1d?limit=3
\echo Authenticated probes (replace JWT):
\echo   curl -H "Authorization: Bearer $JWT" https://api.panda.qzz.io/backtest_runs?limit=1
