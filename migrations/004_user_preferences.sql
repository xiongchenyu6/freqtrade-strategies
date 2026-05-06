-- Per-user preferences — first auth-scoped table in the stack.
--
-- Each authenticated user owns exactly one row keyed on auth.uid(). RLS blocks
-- all cross-user reads/writes; PostgREST upserts land via the api.* view.
--
-- dca_plan jsonb shape (client-decoded, not constrained at the DB level):
--   {
--     "start_date":   "2022-01-01",
--     "monthly_usdt": 500,
--     "include_event": true
--   }
--
-- Apply from VPS (as superuser, the api schema owner):
--   ssh oracle-arm-002 sudo -u postgres psql -d api -f - < migrations/004_user_preferences.sql

BEGIN;

CREATE TABLE IF NOT EXISTS quant.user_preferences (
  user_id       uuid        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  dca_plan      jsonb,
  email_digest  boolean     NOT NULL DEFAULT false,
  display_name  text,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Keep updated_at fresh on every write so the client can cache-bust reliably.
CREATE OR REPLACE FUNCTION quant.user_preferences_touch()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS user_preferences_touch ON quant.user_preferences;
CREATE TRIGGER user_preferences_touch
  BEFORE UPDATE ON quant.user_preferences
  FOR EACH ROW EXECUTE FUNCTION quant.user_preferences_touch();

-- RLS: only the owner can touch their own row.
ALTER TABLE quant.user_preferences ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_preferences_select_own ON quant.user_preferences;
CREATE POLICY user_preferences_select_own ON quant.user_preferences
  FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS user_preferences_insert_own ON quant.user_preferences;
CREATE POLICY user_preferences_insert_own ON quant.user_preferences
  FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS user_preferences_update_own ON quant.user_preferences;
CREATE POLICY user_preferences_update_own ON quant.user_preferences
  FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- Authenticated role can CRUD its own row (RLS enforces the "own" part).
GRANT SELECT, INSERT, UPDATE ON quant.user_preferences TO authenticated, service_role;

-- Expose via the api schema for PostgREST auto-routing. The view is a
-- trivial passthrough; RLS runs on the underlying table under the caller's
-- role (PostgREST sets role=authenticated from the JWT).
DROP VIEW IF EXISTS api.user_preferences;
CREATE VIEW api.user_preferences
  WITH (security_invoker = true)
AS SELECT user_id, dca_plan, email_digest, display_name, updated_at
   FROM quant.user_preferences;

GRANT SELECT, INSERT, UPDATE ON api.user_preferences TO authenticated, service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;
\echo
\echo === verification ===
\echo Expect: auth'd user sees only their own row; anon sees empty.
\echo   curl -H "Authorization: Bearer $JWT" https://api.panda.qzz.io/user_preferences
