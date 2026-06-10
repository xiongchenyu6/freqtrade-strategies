-- 018: user-defined signals — backtest a config, then subscribe to it firing LIVE.
--
-- The product loop: a user validates a strategy config in the backtest playground, then
-- one-click converts it into a live signal. The evaluator (game box) recomputes each
-- distinct (kind, asset, timeframe, params) group on fresh PUBLIC market data and inserts
-- a row into signal_fires when a condition triggers; the alert dispatcher pushes the fire
-- to the owner's bound Telegram chat. Compliance: these are the USER'S OWN rules firing —
-- messages say "你的信号触发了", never "we recommend buying".
--
-- kinds (mirror the backtest strategies):
--   'ema_cross'         params {ema_fast, ema_slow, direction: 'golden'|'death'|'both'}
--   'donchian_breakout' params {entry_lb, exit_lb, side: 'entry'|'exit'|'both'}
--   'fng_threshold'     params {below: int}  (fires when Fear&Greed <= below)
--
-- Apply as postgres on oracle-arm-002:
--   ssh oracle-arm-002 sudo runuser -u postgres -- psql -d api -f - < migrations/018_user_signals.sql

BEGIN;

CREATE TABLE IF NOT EXISTS quant.user_signals (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     uuid NOT NULL,
  name        text NOT NULL,
  kind        text NOT NULL CHECK (kind IN ('ema_cross', 'donchian_breakout', 'fng_threshold')),
  asset       text NOT NULL,            -- 'BTC','ETH',... or 'NVDA','AMD','QQQ' (or '*' for fng)
  timeframe   text NOT NULL DEFAULT '1h',  -- '1h' | '1d'
  params      jsonb NOT NULL DEFAULT '{}',
  status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
  -- evaluator bookkeeping (written by the quant role only):
  eval_state  jsonb,                    -- prev indicator values / last bar ts for crossing detection
  last_fired_at timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS user_signals_active_idx ON quant.user_signals (status, kind, asset, timeframe);

ALTER TABLE quant.user_signals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_signals_owner ON quant.user_signals;
CREATE POLICY user_signals_owner ON quant.user_signals
  FOR ALL TO authenticated
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS user_signals_quant ON quant.user_signals;
CREATE POLICY user_signals_quant ON quant.user_signals
  FOR ALL TO quant USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE, DELETE ON quant.user_signals TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON quant.user_signals TO quant;

-- Cap active signals per user (same anti-abuse pattern as backtest_jobs_limit).
CREATE OR REPLACE FUNCTION quant.user_signals_limit() RETURNS trigger AS $$
DECLARE n integer;
BEGIN
  SELECT count(*) INTO n FROM quant.user_signals
   WHERE user_id = NEW.user_id AND status = 'active';
  IF n >= 10 THEN
    RAISE EXCEPTION 'too many active signals (max 10) — pause or delete some first';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS user_signals_limit ON quant.user_signals;
CREATE TRIGGER user_signals_limit
  BEFORE INSERT ON quant.user_signals
  FOR EACH ROW EXECUTE FUNCTION quant.user_signals_limit();

-- Fires: one row per (signal, bar) trigger. Dispatcher pushes them to the owner's chat.
CREATE TABLE IF NOT EXISTS quant.signal_fires (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  signal_id  bigint NOT NULL REFERENCES quant.user_signals(id) ON DELETE CASCADE,
  user_id    uuid NOT NULL,
  fired_at   timestamptz NOT NULL DEFAULT now(),
  bar_ts     timestamptz,               -- the bar close that triggered (dedupe key)
  details    jsonb NOT NULL DEFAULT '{}',  -- {price, value, threshold, direction, message}
  notified_at timestamptz               -- set by the dispatcher after the Telegram send
);

CREATE UNIQUE INDEX IF NOT EXISTS signal_fires_dedupe ON quant.signal_fires (signal_id, bar_ts);
CREATE INDEX IF NOT EXISTS signal_fires_pending ON quant.signal_fires (notified_at) WHERE notified_at IS NULL;

ALTER TABLE quant.signal_fires ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS signal_fires_owner ON quant.signal_fires;
CREATE POLICY signal_fires_owner ON quant.signal_fires
  FOR SELECT TO authenticated USING (user_id = auth.uid());

DROP POLICY IF EXISTS signal_fires_quant ON quant.signal_fires;
CREATE POLICY signal_fires_quant ON quant.signal_fires
  FOR ALL TO quant USING (true) WITH CHECK (true);

GRANT SELECT ON quant.signal_fires TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON quant.signal_fires TO quant;

-- PostgREST views. Users write user_signals through the rw view; eval_state stays internal.
CREATE OR REPLACE VIEW api.user_signals AS
  SELECT id, user_id, name, kind, asset, timeframe, params, status, last_fired_at, created_at
  FROM quant.user_signals;
ALTER VIEW api.user_signals SET (security_invoker = true);
GRANT SELECT ON api.user_signals TO authenticated;

CREATE OR REPLACE VIEW api.user_signals_rw AS
  SELECT id, user_id, name, kind, asset, timeframe, params, status FROM quant.user_signals;
ALTER VIEW api.user_signals_rw SET (security_invoker = true);
GRANT SELECT, INSERT, UPDATE, DELETE ON api.user_signals_rw TO authenticated;

CREATE OR REPLACE VIEW api.signal_fires AS
  SELECT f.id, f.signal_id, f.user_id, f.fired_at, f.bar_ts, f.details, s.name AS signal_name
  FROM quant.signal_fires f JOIN quant.user_signals s ON s.id = f.signal_id;
ALTER VIEW api.signal_fires SET (security_invoker = true);
GRANT SELECT ON api.signal_fires TO authenticated;

COMMIT;
