-- Public API views — exposes selected quant tables via PostgREST on api.panda.qzz.io
--
-- Runs on the VPS, as superuser (freeman.xiong) since api schema is owned by
-- freeman.xiong and quant schema is owned by quant.
--
-- Apply from VPS:
--   ssh oracle-arm-002 sudo -u postgres psql -d api -f - < migrations/002_public_api_views.sql
-- Or locally if connected as freeman.xiong:
--   psql -U freeman.xiong -h db.panda.qzz.io -d api -f migrations/002_public_api_views.sql

BEGIN;

-- ============================================================================
-- Grant quant SELECT permission to anon (the PostgREST anon role)
-- ============================================================================
GRANT USAGE ON SCHEMA quant TO anon, authenticated, service_role;

-- ============================================================================
-- Views in `api` schema — PostgREST auto-exposes these at /<view_name>
-- ============================================================================

-- 1. Backtest runs (main list)
CREATE OR REPLACE VIEW api.backtest_runs AS
SELECT id, job_id, strategy, timeframe, timerange,
       started_at, finished_at, duration_sec,
       total_trades, wins, losses, win_rate_pct,
       total_profit_pct, total_profit_abs,
       max_drawdown_pct, calmar, sharpe, sortino, profit_factor,
       pairs, imported_at
FROM quant.backtest_runs;

-- 2. Backtest trades (for equity curves + overlays)
CREATE OR REPLACE VIEW api.backtest_trades AS
SELECT run_id, trade_id, pair, is_short,
       open_date, close_date, open_rate, close_rate,
       stake_amount, profit_abs, profit_pct,
       exit_reason, enter_tag, trade_duration_min
FROM quant.backtest_trades;

-- 3. OHLC daily aggregate (full history, cheap to serve)
CREATE OR REPLACE VIEW api.ohlc_1d AS
SELECT pair, bucket, open, high, low, close, volume
FROM quant.ohlc_1d;

-- 4. OHLC 1h aggregate (last 90 days only, prevent huge transfers)
CREATE OR REPLACE VIEW api.ohlc_1h_recent AS
SELECT pair, bucket, open, high, low, close, volume
FROM quant.ohlc_1h
WHERE bucket >= now() - INTERVAL '90 days';

-- 5. OHLC 15m aggregate (last 30 days)
CREATE OR REPLACE VIEW api.ohlc_15m_recent AS
SELECT pair, bucket, open, high, low, close, volume
FROM quant.ohlc_15m
WHERE bucket >= now() - INTERVAL '30 days';

-- 6. Walk-forward results
CREATE OR REPLACE VIEW api.wf_results AS
SELECT id, run_date, strategy, timeframe, window_label,
       window_start, window_end, status,
       trades, avg_profit_pct, tot_profit_usdt, tot_profit_pct
FROM quant.wf_results;

-- 7. Live bot trades (drop bot_name IF you want per-bot privacy)
CREATE OR REPLACE VIEW api.live_trades AS
SELECT bot_name, pair, is_short, strategy,
       open_date, close_date, open_rate, close_rate,
       stake_amount, profit_abs, profit_pct,
       exit_reason, synced_at
FROM quant.trades;

-- 8. Event DCA triggers
CREATE OR REPLACE VIEW api.event_dca_triggers AS
SELECT ts, kind, price, severity, fng, amount_usdt, mode
FROM quant.event_dca_triggers;

-- ============================================================================
-- Grants: allow anon to SELECT
-- ============================================================================
GRANT SELECT ON api.backtest_runs,
                api.backtest_trades,
                api.ohlc_1d,
                api.ohlc_1h_recent,
                api.ohlc_15m_recent,
                api.wf_results,
                api.live_trades,
                api.event_dca_triggers
         TO anon, authenticated, service_role;

-- Critical: PostgREST executes views as the connecting role (anon), so
-- that role ALSO needs SELECT on the underlying quant.* tables.
GRANT SELECT ON quant.backtest_runs,
                quant.backtest_trades,
                quant.ohlc_1d,
                quant.ohlc_1h,
                quant.ohlc_15m,
                quant.wf_results,
                quant.trades,
                quant.event_dca_triggers
         TO anon, authenticated, service_role;

-- Set default privileges for future tables created by `quant` role
ALTER DEFAULT PRIVILEGES IN SCHEMA quant
  GRANT SELECT ON TABLES TO anon, authenticated, service_role;

-- ============================================================================
-- Rate limits + request tagging (optional; PostgREST supports via config)
-- ============================================================================
-- If you want per-IP rate limiting, nginx limit_req_zone is the right place.
-- If you want row-count limits, set `max-rows` in PostgREST config.

-- Reload PostgREST schema cache (so new views are visible without restart):
NOTIFY pgrst, 'reload schema';

COMMIT;
\echo
\echo === verification ===
\echo Run:  curl https://api.panda.qzz.io/backtest_runs?limit=3
\echo Or:   curl https://api.panda.qzz.io/ohlc_1d?pair=eq.BTC/USDT^&limit=5^&order=bucket.desc
