-- 017: user-facing Telegram alert subscriptions (the retention loop).
--
-- A logged-in user links their Telegram via a deep-link token (t.me/<bot>?start=<token>);
-- the alert dispatcher (game box) binds chat_id on /start and fans out new signal events
-- (DCA triggers, equity paper trades) to subscribed chats. One row per user.
--
-- topics: which event streams the user wants. Valid values today:
--   'dca_events'    — quant.event_dca_triggers rows (FLASH/FAST/SUSTAIN/CAPITUL)
--   'equity_trades' — quant.nautilus_trades asset_class='equity' open/close
--
-- Apply as the api-schema owner (postgres) on oracle-arm-002:
--   ssh oracle-arm-002 sudo runuser -u postgres -- psql -d api -f - < migrations/017_alert_subscriptions.sql

BEGIN;

CREATE TABLE IF NOT EXISTS quant.telegram_links (
  user_id    uuid PRIMARY KEY,
  -- Deep-link binding token; the dispatcher matches /start <token> to this row.
  link_token text NOT NULL UNIQUE DEFAULT replace(gen_random_uuid()::text, '-', ''),
  chat_id    bigint,                       -- null until the user taps /start in Telegram
  topics     text[] NOT NULL DEFAULT '{dca_events}',
  created_at timestamptz NOT NULL DEFAULT now(),
  bound_at   timestamptz
);

ALTER TABLE quant.telegram_links ENABLE ROW LEVEL SECURITY;

-- Owner-only for app users (same pattern as backtest_jobs).
DROP POLICY IF EXISTS telegram_links_owner ON quant.telegram_links;
CREATE POLICY telegram_links_owner ON quant.telegram_links
  FOR ALL TO authenticated
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- The dispatcher (quant role) binds chat_ids and reads fan-out targets.
DROP POLICY IF EXISTS telegram_links_quant ON quant.telegram_links;
CREATE POLICY telegram_links_quant ON quant.telegram_links
  FOR ALL TO quant
  USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE, DELETE ON quant.telegram_links TO quant;
GRANT SELECT, INSERT, UPDATE, DELETE ON quant.telegram_links TO authenticated;

-- API view (PostgREST). chat_id is the user's own — fine to show bound status.
CREATE OR REPLACE VIEW api.telegram_links AS
  SELECT user_id, link_token, chat_id IS NOT NULL AS bound, topics, created_at, bound_at
  FROM quant.telegram_links;
ALTER VIEW api.telegram_links SET (security_invoker = true);
GRANT SELECT ON api.telegram_links TO authenticated;

-- Writes go through PostgREST on the view: make it auto-updatable-ish via rules is messy;
-- instead expose the base table columns users may write through a writable view.
CREATE OR REPLACE VIEW api.telegram_links_rw AS
  SELECT user_id, link_token, topics FROM quant.telegram_links;
ALTER VIEW api.telegram_links_rw SET (security_invoker = true);
GRANT SELECT, INSERT, UPDATE ON api.telegram_links_rw TO authenticated;

COMMIT;
