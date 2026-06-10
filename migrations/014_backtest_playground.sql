-- 014: self-service backtest playground (jobs + results), user-scoped.
--
-- Lets a logged-in visitor queue their OWN backtest of a PREDEFINED strategy with their
-- own params; a backend runner (game box) executes it and writes results scoped to them.
-- Mirrors the user-scoping + RLS + api-view pattern from 004_user_preferences.sql.
--
-- NOT YET APPLIED — held pending owner sign-off on the playground direction
-- (see PLAYGROUND_PLAN.md). Apply from the VPS as the api-schema owner:
--   ssh oracle-arm-002 sudo -u postgres psql -d api -f - < migrations/014_backtest_playground.sql
--
-- The runner connects directly (service_role / a privileged role, bypassing RLS) to poll
-- queued jobs and write results. Per-user rate limits are enforced in the app/runner, not here.

BEGIN;

-- ---------------------------------------------------------------- jobs (user-submitted)
CREATE TABLE IF NOT EXISTS quant.backtest_jobs (
  id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  -- PREDEFINED strategies only — never arbitrary code.
  strategy     text        NOT NULL CHECK (strategy IN ('honest_trend', 'accumulator', 'donchian')),
  -- Param form values (asset, timeframe, ema fast/slow, risk frac, date range, …).
  -- Shape validated by the runner, not constrained at the DB level.
  params       jsonb       NOT NULL DEFAULT '{}'::jsonb,
  status       text        NOT NULL DEFAULT 'queued'
                           CHECK (status IN ('queued', 'running', 'done', 'error')),
  error        text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS backtest_jobs_user_idx   ON quant.backtest_jobs (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS backtest_jobs_status_idx ON quant.backtest_jobs (status) WHERE status = 'queued';

CREATE OR REPLACE FUNCTION quant.backtest_jobs_touch() RETURNS trigger AS $$
BEGIN NEW.updated_at := now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS backtest_jobs_touch ON quant.backtest_jobs;
CREATE TRIGGER backtest_jobs_touch BEFORE UPDATE ON quant.backtest_jobs
  FOR EACH ROW EXECUTE FUNCTION quant.backtest_jobs_touch();

-- ---------------------------------------------------------------- results (runner-written)
CREATE TABLE IF NOT EXISTS quant.backtest_results (
  job_id        uuid        PRIMARY KEY REFERENCES quant.backtest_jobs(id) ON DELETE CASCADE,
  user_id       uuid        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,  -- denormalized for RLS
  metrics       jsonb       NOT NULL,   -- { return_pct, sharpe, max_dd_pct, trades, win_rate, … }
  equity_curve  jsonb,                  -- [[ts, equity], …] for charting (MVP: inline jsonb)
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS backtest_results_user_idx ON quant.backtest_results (user_id, created_at DESC);

-- ---------------------------------------------------------------- RLS (owner-only reads)
ALTER TABLE quant.backtest_jobs    ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant.backtest_results ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS backtest_jobs_select_own ON quant.backtest_jobs;
CREATE POLICY backtest_jobs_select_own ON quant.backtest_jobs
  FOR SELECT USING (auth.uid() = user_id);
-- Users may only enqueue their OWN job, and only in the 'queued' state (no smuggling a
-- pre-'done' row). Status transitions queued→running→done are the runner's (service_role).
DROP POLICY IF EXISTS backtest_jobs_insert_own ON quant.backtest_jobs;
CREATE POLICY backtest_jobs_insert_own ON quant.backtest_jobs
  FOR INSERT WITH CHECK (auth.uid() = user_id AND status = 'queued');

DROP POLICY IF EXISTS backtest_results_select_own ON quant.backtest_results;
CREATE POLICY backtest_results_select_own ON quant.backtest_results
  FOR SELECT USING (auth.uid() = user_id);

-- authenticated: insert/select own jobs, read own results. service_role (runner) bypasses RLS.
GRANT SELECT, INSERT          ON quant.backtest_jobs    TO authenticated;
GRANT SELECT, UPDATE          ON quant.backtest_jobs    TO service_role;
GRANT SELECT                  ON quant.backtest_results TO authenticated;
GRANT SELECT, INSERT, UPDATE  ON quant.backtest_results TO service_role;

-- The backtest runner (game box) connects as the existing `quant` role — already allowed
-- remotely in pg_hba and already in sops — so give it scoped FULL access to just these two
-- tables via explicit policies (not global BYPASSRLS). Hardening TODO: a dedicated
-- backtest_runner login role + pg_hba entry.
GRANT SELECT, UPDATE         ON quant.backtest_jobs    TO quant;
GRANT SELECT, INSERT, UPDATE ON quant.backtest_results TO quant;
DROP POLICY IF EXISTS backtest_jobs_runner ON quant.backtest_jobs;
CREATE POLICY backtest_jobs_runner ON quant.backtest_jobs
  FOR ALL TO quant USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS backtest_results_runner ON quant.backtest_results;
CREATE POLICY backtest_results_runner ON quant.backtest_results
  FOR ALL TO quant USING (true) WITH CHECK (true);

-- ---------------------------------------------------------------- api views (PostgREST)
DROP VIEW IF EXISTS api.backtest_jobs;
CREATE VIEW api.backtest_jobs WITH (security_invoker = true) AS
  SELECT id, user_id, strategy, params, status, error, created_at, updated_at
  FROM quant.backtest_jobs;
GRANT SELECT, INSERT ON api.backtest_jobs TO authenticated;
GRANT SELECT, UPDATE ON api.backtest_jobs TO service_role;

DROP VIEW IF EXISTS api.backtest_results;
CREATE VIEW api.backtest_results WITH (security_invoker = true) AS
  SELECT job_id, user_id, metrics, equity_curve, created_at
  FROM quant.backtest_results;
GRANT SELECT ON api.backtest_results TO authenticated;
GRANT SELECT, INSERT ON api.backtest_results TO service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;

\echo
\echo === verification ===
\echo Authed user enqueues a job:
\echo   curl -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
\echo        -d '{"strategy":"honest_trend","params":{"asset":"NVDA","tf":"1h","ema_fast":50,"ema_slow":100}}' \
\echo        https://api.panda.qzz.io/backtest_jobs
\echo Then sees only their own jobs/results; anon sees empty.
