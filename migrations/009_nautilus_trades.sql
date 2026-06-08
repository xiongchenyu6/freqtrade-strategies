-- 009: NautilusTrader trade ledger — isolated from the freqtrade quant.trades / api.live_trades.
-- The Nautilus execution engine (accumulator + Donchian trend) writes here via a
-- TimescaleWriter Actor on position open/close. `environment` distinguishes testnet vs live
-- so testnet activity never masquerades as real money on the public dashboard.

CREATE TABLE IF NOT EXISTS quant.nautilus_trades (
    trader_id    text        NOT NULL,   -- e.g. 'TREND-001', 'ACCUMULATOR-001'
    position_id  text        NOT NULL,   -- Nautilus position id (stable per round-trip)
    strategy     text        NOT NULL,   -- DonchianBreakout / Accumulator
    instrument   text        NOT NULL,   -- BTCUSDT.BINANCE
    venue        text        NOT NULL,   -- BINANCE
    environment  text        NOT NULL,   -- 'testnet' | 'live'
    is_short     boolean     NOT NULL DEFAULT false,
    open_date    timestamptz NOT NULL,
    close_date   timestamptz,
    open_rate    numeric,
    close_rate   numeric,
    quantity     numeric,
    realized_pnl numeric,
    profit_pct   numeric,
    exit_reason  text,
    synced_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trader_id, position_id, open_date)
);

SELECT create_hypertable('quant.nautilus_trades', 'open_date',
                         chunk_time_interval => INTERVAL '90 days',
                         if_not_exists       => TRUE);

CREATE INDEX IF NOT EXISTS nautilus_trades_env_idx ON quant.nautilus_trades (environment, open_date DESC);
CREATE INDEX IF NOT EXISTS nautilus_trades_strat_idx ON quant.nautilus_trades (strategy, open_date DESC);

-- Public API view (mirrors the api.live_trades pattern). Exposes environment so the
-- dashboard can label/segregate testnet vs live.
CREATE OR REPLACE VIEW api.nautilus_trades AS
SELECT trader_id, strategy, instrument, venue, environment, is_short,
       open_date, close_date, open_rate, close_rate, quantity,
       realized_pnl, profit_pct, exit_reason, synced_at
FROM quant.nautilus_trades;

GRANT SELECT ON api.nautilus_trades TO anon, authenticated, service_role;

-- The execution engine connects as the `quant` role and writes here.
GRANT SELECT, INSERT, UPDATE ON quant.nautilus_trades TO quant;
