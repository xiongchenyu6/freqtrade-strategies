-- 015: cap concurrent backtest jobs per user (anti-abuse for the public playground).
--
-- A logged-in user may have at most 5 active (queued|running) jobs at once. Server-side
-- (a BEFORE INSERT trigger), so it can't be bypassed from the client. Done jobs don't count,
-- so there's no lifetime cap — just back-pressure on the runner.
--
-- Apply as the api-schema owner (postgres) on oracle-arm-002:
--   ssh oracle-arm-002 sudo -u postgres psql -d api -f - < migrations/015_backtest_jobs_limit.sql

BEGIN;

CREATE OR REPLACE FUNCTION quant.backtest_jobs_limit() RETURNS trigger AS $$
DECLARE
  active_count integer;
BEGIN
  SELECT count(*) INTO active_count
  FROM quant.backtest_jobs
  WHERE user_id = NEW.user_id AND status IN ('queued', 'running');
  IF active_count >= 5 THEN
    RAISE EXCEPTION 'too many active backtests (max 5 queued/running) — wait for some to finish';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS backtest_jobs_limit ON quant.backtest_jobs;
CREATE TRIGGER backtest_jobs_limit
  BEFORE INSERT ON quant.backtest_jobs
  FOR EACH ROW EXECUTE FUNCTION quant.backtest_jobs_limit();

COMMIT;
