-- 028: allow Quant Lab research jobs in the self-service job queue.
-- Apply as postgres on oracle-arm-002:
--   ssh oracle-arm-002 sudo runuser -u postgres -- psql -d api -f - < migrations/028_quant_lab_strategy.sql
BEGIN;

ALTER TABLE quant.backtest_jobs DROP CONSTRAINT IF EXISTS backtest_jobs_strategy_check;
ALTER TABLE quant.backtest_jobs ADD CONSTRAINT backtest_jobs_strategy_check
  CHECK (strategy IN ('honest_trend', 'accumulator', 'donchian', 'master_portfolio', 'quant_lab'));

COMMIT;
