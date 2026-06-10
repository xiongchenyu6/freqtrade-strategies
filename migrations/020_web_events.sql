-- 020: lightweight first-party analytics — the validation plan's "eyes".
--
-- Minimal funnel events, no third party, no PII beyond an opaque visitor id
-- (random localStorage uuid) and the optional auth user_id. Writes go through an
-- INSERT-ONLY view exposed to anon+authenticated; nothing is readable via the API
-- (reads happen via the quant role: daily Telegram growth report / psql).
--
-- Allowed events (CHECK keeps the table from becoming a junk drawer):
--   page_view, signup, backtest_submit, signal_create, telegram_bound
--
-- Apply as postgres on oracle-arm-002:
--   ssh oracle-arm-002 sudo runuser -u postgres -- psql -d api -f - < migrations/020_web_events.sql

BEGIN;

CREATE TABLE IF NOT EXISTS quant.web_events (
  id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ts       timestamptz NOT NULL DEFAULT now(),
  event    text NOT NULL CHECK (event IN
           ('page_view', 'signup', 'backtest_submit', 'signal_create', 'telegram_bound')),
  path     text,
  visitor  text NOT NULL,         -- opaque random id from localStorage
  user_id  uuid,                  -- set when logged in
  lang     text,
  ref      text                   -- document.referrer host, first touch only
);

CREATE INDEX IF NOT EXISTS web_events_ts_idx ON quant.web_events (ts DESC);
CREATE INDEX IF NOT EXISTS web_events_visitor_idx ON quant.web_events (visitor, ts DESC);

ALTER TABLE quant.web_events ENABLE ROW LEVEL SECURITY;

-- Insert-only for web clients (anon + authenticated); no SELECT policy for them.
DROP POLICY IF EXISTS web_events_insert ON quant.web_events;
CREATE POLICY web_events_insert ON quant.web_events
  FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS web_events_quant ON quant.web_events;
CREATE POLICY web_events_quant ON quant.web_events
  FOR ALL TO quant USING (true) WITH CHECK (true);

GRANT INSERT ON quant.web_events TO anon, authenticated;
GRANT SELECT, INSERT, DELETE ON quant.web_events TO quant;

CREATE OR REPLACE VIEW api.web_events_in AS
  SELECT event, path, visitor, user_id, lang, ref FROM quant.web_events;
ALTER VIEW api.web_events_in SET (security_invoker = true);
GRANT INSERT ON api.web_events_in TO anon, authenticated;

COMMIT;
