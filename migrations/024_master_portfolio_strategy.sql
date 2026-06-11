-- 024: allow the new 'master_portfolio' strategy in the playground job queue.
-- Apply as postgres on oracle-arm-002:
--   ssh oracle-arm-002 sudo runuser -u postgres -- psql -d api -f - < migrations/024_master_portfolio_strategy.sql
BEGIN;
ALTER TABLE quant.backtest_jobs DROP CONSTRAINT IF EXISTS backtest_jobs_strategy_check;
ALTER TABLE quant.backtest_jobs ADD CONSTRAINT backtest_jobs_strategy_check
  CHECK (strategy IN ('honest_trend', 'accumulator', 'donchian', 'master_portfolio'));
COMMIT;
