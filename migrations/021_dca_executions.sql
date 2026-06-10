-- 021: personal DCA execution ledger — the "discipline coach" real-value loop.
--
-- The /dca PersonalPlan simulates a hypothetical plan; this table records what the
-- user ACTUALLY bought ("我买了" one-tap log). From it the UI computes the numbers
-- that matter to the user's wallet: real invested, real average cost per coin,
-- vs current price, vs lump-sum-at-start, and the discipline streak. The alert
-- dispatcher sends monthly plan reminders (the user's OWN plan — tool, not advice).
--
-- breakdown jsonb: {"BTC": {"amount": 120, "price": 61500}, "ETH": {...}} — amounts
-- in USDT, price snapshot at log time (client-fetched from Binance public ticker;
-- it is the user's own ledger, self-reported by design).
--
-- Apply as postgres on oracle-arm-002:
--   ssh oracle-arm-002 sudo runuser -u postgres -- psql -d api -f - < migrations/021_dca_executions.sql

BEGIN;

CREATE TABLE IF NOT EXISTS quant.dca_executions (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    uuid NOT NULL,
  ts         timestamptz NOT NULL DEFAULT now(),
  total_usdt numeric NOT NULL CHECK (total_usdt > 0 AND total_usdt <= 1000000),
  breakdown  jsonb NOT NULL DEFAULT '{}',
  note       text
);

CREATE INDEX IF NOT EXISTS dca_executions_user_idx ON quant.dca_executions (user_id, ts DESC);

ALTER TABLE quant.dca_executions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS dca_executions_owner ON quant.dca_executions;
CREATE POLICY dca_executions_owner ON quant.dca_executions
  FOR ALL TO authenticated
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS dca_executions_quant ON quant.dca_executions;
CREATE POLICY dca_executions_quant ON quant.dca_executions
  FOR ALL TO quant USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, DELETE ON quant.dca_executions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON quant.dca_executions TO quant;

CREATE OR REPLACE VIEW api.dca_executions AS
  SELECT id, user_id, ts, total_usdt, breakdown, note FROM quant.dca_executions;
ALTER VIEW api.dca_executions SET (security_invoker = true);
GRANT SELECT, INSERT, DELETE ON api.dca_executions TO authenticated;

COMMIT;

-- Addendum (applied separately): the alert dispatcher (quant role) reads saved plans
-- for the monthly reminder.
GRANT SELECT ON quant.user_preferences TO quant;
DROP POLICY IF EXISTS user_preferences_quant ON quant.user_preferences;
CREATE POLICY user_preferences_quant ON quant.user_preferences
  FOR SELECT TO quant USING (true);
