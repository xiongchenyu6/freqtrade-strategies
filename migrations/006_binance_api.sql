-- Portfolio-sync — store a user's read-only Binance API credentials so the
-- Cloudflare Worker can call GET /api/v3/account on their behalf.
--
-- SECURITY NOTES (v1, pragmatic):
--   * Stored plaintext but RLS-gated: only the owner (authenticated role) can
--     read their own row; service_role bypasses RLS for ops.
--   * The UI MUST instruct the user to create a read-only, IP-allowlisted API
--     key with ONLY "Enable Reading" permission (no trade, no withdraw).
--   * Upgrade path: encrypt with a KEK held in Worker secrets + column
--     binance_api_secret_enc bytea. Done later; not blocking for friend-scale use.
--
-- Apply from VPS:
--   ssh oracle-arm-002 sudo -u postgres psql -d api -f - < migrations/006_binance_api.sql

BEGIN;

ALTER TABLE quant.user_preferences
  ADD COLUMN IF NOT EXISTS binance_api_key    text,
  ADD COLUMN IF NOT EXISTS binance_api_secret text,
  ADD COLUMN IF NOT EXISTS binance_connected_at timestamptz;

-- Recreate the api view so the new columns are visible via PostgREST. The
-- SELECT policy on the underlying table already restricts to auth.uid() = user_id,
-- so exposing the columns is safe — nobody else can read them.
DROP VIEW IF EXISTS api.user_preferences;
CREATE VIEW api.user_preferences
  WITH (security_invoker = true)
AS SELECT
     user_id,
     dca_plan,
     email_digest,
     display_name,
     binance_api_key,
     binance_api_secret,
     binance_connected_at,
     updated_at
   FROM quant.user_preferences;

GRANT SELECT, INSERT, UPDATE ON api.user_preferences TO authenticated, service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;
