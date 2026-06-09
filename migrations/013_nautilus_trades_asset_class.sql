-- 013: add an asset_class dimension to quant.nautilus_trades.
-- The single-stack migration runs two Nautilus execution engines that both write here:
--   * crypto (Accumulator + Donchian trend, Binance) on oracle-arm-002
--   * US-equity (HonestTrend via Interactive Brokers, PAPER) on oracle-amd-002
-- Mirrors quant.nautilus_backtests.asset_class (migration 010). Additive + non-breaking:
-- existing rows are crypto, so backfill the default to 'crypto'.

ALTER TABLE quant.nautilus_trades
    ADD COLUMN IF NOT EXISTS asset_class text NOT NULL DEFAULT 'crypto';

CREATE INDEX IF NOT EXISTS nautilus_trades_asset_idx
    ON quant.nautilus_trades (asset_class, open_date DESC);

-- Re-create the public API view to expose asset_class so the dashboard can split
-- crypto vs equity live execution (mirrors api.nautilus_backtests). DROP+CREATE (not
-- CREATE OR REPLACE) because asset_class is appended at the END — CREATE OR REPLACE
-- cannot insert a column mid-list against the existing view.
DROP VIEW IF EXISTS api.nautilus_trades;
CREATE VIEW api.nautilus_trades AS
SELECT trader_id, strategy, instrument, venue, environment, is_short,
       open_date, close_date, open_rate, close_rate, quantity,
       realized_pnl, profit_pct, exit_reason, synced_at, asset_class
FROM quant.nautilus_trades;

GRANT SELECT ON api.nautilus_trades TO anon, authenticated, service_role;
