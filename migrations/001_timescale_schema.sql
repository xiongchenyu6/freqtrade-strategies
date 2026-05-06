-- Timescale schema for quant public-serving layer.
-- All objects go in `quant` schema (our only writable one).
-- Apply:
--   sops exec-env secrets.env 'psql "$TIMESCALE_URL" -f migrations/001_timescale_schema.sql'

SET search_path = quant, public;

-- ===========================================================================
-- 1. OHLCV (bulk time-series, compressed + 3 continuous aggregates)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS quant.ohlc (
    pair        text         NOT NULL,
    tf          text         NOT NULL,   -- source timeframe tag, usually '1m'
    ts          timestamptz  NOT NULL,
    open        double precision NOT NULL,
    high        double precision NOT NULL,
    low         double precision NOT NULL,
    close       double precision NOT NULL,
    volume      double precision NOT NULL,
    PRIMARY KEY (pair, tf, ts)
);

SELECT create_hypertable('quant.ohlc', 'ts',
                         chunk_time_interval => INTERVAL '30 days',
                         if_not_exists       => TRUE);

CREATE INDEX IF NOT EXISTS ohlc_pair_ts_idx ON quant.ohlc (pair, ts DESC);

-- Continuous aggregate: 15m from 1m
CREATE MATERIALIZED VIEW IF NOT EXISTS quant.ohlc_15m
WITH (timescaledb.continuous) AS
SELECT pair,
       time_bucket('15 minutes', ts) AS bucket,
       first(open, ts)  AS open,
       max(high)        AS high,
       min(low)         AS low,
       last(close, ts)  AS close,
       sum(volume)      AS volume
FROM quant.ohlc
WHERE tf = '1m'
GROUP BY pair, bucket
WITH NO DATA;

-- Continuous aggregate: 1h from 1m
CREATE MATERIALIZED VIEW IF NOT EXISTS quant.ohlc_1h
WITH (timescaledb.continuous) AS
SELECT pair,
       time_bucket('1 hour', ts) AS bucket,
       first(open, ts)  AS open,
       max(high)        AS high,
       min(low)         AS low,
       last(close, ts)  AS close,
       sum(volume)      AS volume
FROM quant.ohlc
WHERE tf = '1m'
GROUP BY pair, bucket
WITH NO DATA;

-- Continuous aggregate: 1d from 1m
CREATE MATERIALIZED VIEW IF NOT EXISTS quant.ohlc_1d
WITH (timescaledb.continuous) AS
SELECT pair,
       time_bucket('1 day', ts) AS bucket,
       first(open, ts)  AS open,
       max(high)        AS high,
       min(low)         AS low,
       last(close, ts)  AS close,
       sum(volume)      AS volume
FROM quant.ohlc
WHERE tf = '1m'
GROUP BY pair, bucket
WITH NO DATA;

-- Refresh policies: keep aggregates fresh automatically
SELECT add_continuous_aggregate_policy('quant.ohlc_15m',
    start_offset      => INTERVAL '3 days',
    end_offset        => INTERVAL '15 minutes',
    schedule_interval => INTERVAL '15 minutes',
    if_not_exists     => TRUE);
SELECT add_continuous_aggregate_policy('quant.ohlc_1h',
    start_offset      => INTERVAL '14 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE);
SELECT add_continuous_aggregate_policy('quant.ohlc_1d',
    start_offset      => INTERVAL '60 days',
    end_offset        => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists     => TRUE);

-- Compress chunks older than 7 days (about 90% savings on OHLC)
ALTER TABLE quant.ohlc SET (
    timescaledb.compress,
    timescaledb.compress_orderby   = 'ts DESC',
    timescaledb.compress_segmentby = 'pair, tf'
);
SELECT add_compression_policy('quant.ohlc', INTERVAL '7 days',
                               if_not_exists => TRUE);

-- ===========================================================================
-- 2. Bot live/dry-run trades (synced from SQLite every few minutes)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS quant.trades (
    bot_name     text        NOT NULL,   -- e.g. 'HonestTrend15mDry'
    trade_id     integer     NOT NULL,
    pair         text        NOT NULL,
    is_short     boolean     NOT NULL DEFAULT false,
    strategy     text,
    open_date    timestamptz NOT NULL,
    close_date   timestamptz,
    open_rate    numeric,
    close_rate   numeric,
    stake_amount numeric,
    amount       numeric,
    profit_abs   numeric,
    profit_pct   numeric,        -- close_profit (fraction)
    exit_reason  text,
    enter_tag    text,
    leverage     numeric,
    funding_fees numeric,
    synced_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (bot_name, trade_id, open_date)   -- open_date required by hypertable
);
SELECT create_hypertable('quant.trades', 'open_date',
                         chunk_time_interval => INTERVAL '90 days',
                         if_not_exists       => TRUE);
CREATE INDEX IF NOT EXISTS trades_bot_open_idx   ON quant.trades (bot_name, open_date DESC);
CREATE INDEX IF NOT EXISTS trades_strategy_idx   ON quant.trades (strategy, open_date DESC);
CREATE INDEX IF NOT EXISTS trades_pair_idx       ON quant.trades (pair, open_date DESC);

-- ===========================================================================
-- 3. Backtest run archive (one row per `freqtrade backtesting` invocation)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS quant.backtest_runs (
    id               bigserial PRIMARY KEY,
    job_id           text,               -- from the launcher
    strategy         text NOT NULL,
    config_file      text,
    timerange        text,
    timeframe        text,
    max_open_trades  integer,
    stake_amount     numeric,
    pairs            text[],
    started_at       timestamptz NOT NULL,
    finished_at      timestamptz,
    duration_sec     numeric,
    -- Headline metrics
    total_trades     integer,
    wins             integer,
    losses           integer,
    win_rate_pct     numeric,
    total_profit_pct numeric,
    total_profit_abs numeric,
    max_drawdown_pct numeric,
    calmar           numeric,
    sharpe           numeric,
    sortino          numeric,
    profit_factor    numeric,
    -- Full backtest summary blob (what freqtrade reports)
    raw_summary      jsonb,
    -- Where to find source data
    zip_path         text,
    imported_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS backtest_runs_strategy_idx ON quant.backtest_runs (strategy, started_at DESC);
CREATE INDEX IF NOT EXISTS backtest_runs_started_idx  ON quant.backtest_runs (started_at DESC);

-- ===========================================================================
-- 4. Individual trades from backtest runs
-- ===========================================================================
CREATE TABLE IF NOT EXISTS quant.backtest_trades (
    run_id      bigint NOT NULL REFERENCES quant.backtest_runs(id) ON DELETE CASCADE,
    trade_id    integer NOT NULL,
    pair        text NOT NULL,
    is_short    boolean NOT NULL DEFAULT false,
    open_date   timestamptz NOT NULL,
    close_date  timestamptz,
    open_rate   numeric,
    close_rate  numeric,
    stake_amount numeric,
    profit_abs  numeric,
    profit_pct  numeric,
    exit_reason text,
    enter_tag   text,
    trade_duration_min integer,
    PRIMARY KEY (run_id, trade_id)
);
-- No hypertable needed — partitioned naturally by run_id
CREATE INDEX IF NOT EXISTS bt_trades_run_idx   ON quant.backtest_trades (run_id, open_date);
CREATE INDEX IF NOT EXISTS bt_trades_pair_idx  ON quant.backtest_trades (pair, open_date);

-- ===========================================================================
-- 5. Walk-forward per-window results
-- ===========================================================================
CREATE TABLE IF NOT EXISTS quant.wf_results (
    id           bigserial PRIMARY KEY,
    run_date     timestamptz NOT NULL,
    strategy     text NOT NULL,
    timeframe    text NOT NULL,
    window_label text NOT NULL,     -- 'W1_2018_crash', etc.
    window_start date NOT NULL,
    window_end   date NOT NULL,
    status       text NOT NULL,     -- 'ok' | 'failed'
    trades       integer,
    avg_profit_pct   numeric,
    tot_profit_usdt  numeric,
    tot_profit_pct   numeric,
    json_source  text                -- path to original JSON
);
CREATE INDEX IF NOT EXISTS wf_strategy_idx ON quant.wf_results (strategy, run_date DESC);
CREATE INDEX IF NOT EXISTS wf_window_idx   ON quant.wf_results (window_label, run_date DESC);

-- ===========================================================================
-- 6. Event DCA triggers (mirror of event_dca_state.json history[])
-- ===========================================================================
CREATE TABLE IF NOT EXISTS quant.event_dca_triggers (
    ts           timestamptz NOT NULL PRIMARY KEY,
    kind         text NOT NULL,     -- FLASH / FAST / SUSTAIN / CAPITUL
    price        numeric,
    severity     numeric,           -- negative fraction (e.g. -0.05 = -5%)
    fng          integer,
    amount_usdt  numeric,
    mode         text               -- 'dry_run' | 'live'
);
CREATE INDEX IF NOT EXISTS event_dca_kind_idx ON quant.event_dca_triggers (kind, ts DESC);

-- ===========================================================================
-- 7. FnG history (daily)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS quant.fng_history (
    date           date PRIMARY KEY,
    value          integer NOT NULL CHECK (value BETWEEN 0 AND 100),
    classification text
);

-- ===========================================================================
-- 8. Read-only role for public API (PostgREST / FastAPI connects as this)
-- ===========================================================================
-- Optional: create a separate low-priv role for serving. Skip if quant user
-- is used directly behind the API.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_ro') THEN
    CREATE ROLE quant_ro NOLOGIN;
  END IF;
END
$$;
GRANT USAGE ON SCHEMA quant TO quant_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA quant TO quant_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA quant GRANT SELECT ON TABLES TO quant_ro;

-- ===========================================================================
-- Done.
-- ===========================================================================
\echo
\echo === summary ===
SELECT 'hypertables' AS kind, count(*) FROM timescaledb_information.hypertables
  WHERE hypertable_schema='quant'
UNION ALL
SELECT 'continuous aggregates', count(*) FROM timescaledb_information.continuous_aggregates
  WHERE view_schema='quant'
UNION ALL
SELECT 'tables', count(*) FROM pg_tables
  WHERE schemaname='quant' AND tablename NOT LIKE '\\_%';
