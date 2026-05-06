-- Factor tags per backtest run — populated at ingest time.
--
-- Lets the UI surface "what this strategy relies on" without parsing
-- config_file or introspecting strategy source. Canonical tags (kept small so
-- badges stay readable):
--   Signal:    EMA, ADX, MACD, RSI
--   Context:   FnG, Funding, HTF
--   Execution: Pyramid, DCA, Trailing, Protections
--   Risk:      DD-Kill, Cooldown
--   Mode:      Spot, Futures-Short, Futures-L+S, Production-gate
--
-- Apply from VPS (as superuser, owner of api schema):
--   ssh oracle-arm-002 sudo -u postgres psql -d api -f - < migrations/003_backtest_factors.sql

BEGIN;

ALTER TABLE quant.backtest_runs
  ADD COLUMN IF NOT EXISTS factors jsonb;

-- Rewrite the api view to expose factors. CREATE OR REPLACE can't change the
-- column list, so drop+recreate.
DROP VIEW IF EXISTS api.backtest_runs;
CREATE VIEW api.backtest_runs AS
SELECT id, job_id, strategy, timeframe, timerange,
       started_at, finished_at, duration_sec,
       total_trades, wins, losses, win_rate_pct,
       total_profit_pct, total_profit_abs,
       max_drawdown_pct, calmar, sharpe, sortino, profit_factor,
       pairs, factors, imported_at
FROM quant.backtest_runs;

GRANT SELECT ON api.backtest_runs TO anon, authenticated, service_role;

-- Backfill existing runs with best-guess factor tags based on strategy name.
-- These match scripts/import_backtest_zip.py:FACTORS_BY_STRATEGY, so new
-- imports keep the mapping consistent.
UPDATE quant.backtest_runs SET factors = '["EMA","ADX","DD-Kill","Spot"]'::jsonb
  WHERE strategy = 'HonestTrend15mDry' AND factors IS NULL;
UPDATE quant.backtest_runs SET factors = '["EMA","ADX","Protections","DD-Kill","Spot"]'::jsonb
  WHERE strategy = 'HonestTrend15mAdvanced' AND factors IS NULL;
UPDATE quant.backtest_runs SET factors = '["EMA","ADX","Protections","Trailing","DD-Kill","Spot"]'::jsonb
  WHERE strategy = 'HonestTrend15mProtections' AND factors IS NULL;
UPDATE quant.backtest_runs SET factors = '["EMA","ADX","Pyramid","DCA","DD-Kill","Spot"]'::jsonb
  WHERE strategy = 'HonestTrend15mPyramid' AND factors IS NULL;
UPDATE quant.backtest_runs SET factors = '["EMA","ADX","DD-Kill","Spot"]'::jsonb
  WHERE strategy = 'HonestTrend1mLive' AND factors IS NULL;
UPDATE quant.backtest_runs SET factors = '["EMA","ADX","HTF","DD-Kill","Spot"]'::jsonb
  WHERE strategy = 'HonestTrend1mMTF' AND factors IS NULL;
UPDATE quant.backtest_runs SET factors = '["EMA","ADX","FnG","Funding","Futures-Short","DD-Kill"]'::jsonb
  WHERE strategy = 'HonestTrendFutures' AND factors IS NULL;
UPDATE quant.backtest_runs SET factors = '["EMA","ADX","Production-gate","DD-Kill"]'::jsonb
  WHERE strategy = 'LiveProveIt' AND factors IS NULL;

-- Reload PostgREST schema cache so the new column is visible without restart.
NOTIFY pgrst, 'reload schema';

COMMIT;
\echo
\echo === verification ===
\echo Run:  curl https://api.panda.qzz.io/backtest_runs?select=strategy,factors^&limit=3
