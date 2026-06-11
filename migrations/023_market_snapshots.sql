-- 023: server-side market data snapshots — /market was dead on Cloudflare.
--
-- Binance blocks Cloudflare Workers egress (and mainland-CN browsers), so neither SSR
-- nor client-side fetch can load the market dashboard for many users. The game box CAN
-- reach Binance: strategies/market_collector.py fetches the raw upstream payloads every
-- 30 min and stores them here; the web app reads OUR API instead (PostgREST, public).
--
-- payload: raw upstream responses keyed by source, e.g.
--   {"klines_1w": [...], "funding": [...], "open_interest": {...}, "fng": {...},
--    "long_short": [...], "taker_ratio": [...], "top_long_short": [...]}
--
-- Apply as postgres on oracle-arm-002:
--   ssh oracle-arm-002 sudo runuser -u postgres -- psql -d api -f - < migrations/023_market_snapshots.sql

BEGIN;

CREATE TABLE IF NOT EXISTS quant.market_snapshots (
  asset      text PRIMARY KEY,            -- 'BTC' | 'ETH'
  ts         timestamptz NOT NULL DEFAULT now(),
  payload    jsonb NOT NULL
);

GRANT SELECT, INSERT, UPDATE ON quant.market_snapshots TO quant;

CREATE OR REPLACE VIEW api.market_snapshots AS
  SELECT asset, ts, payload FROM quant.market_snapshots;
GRANT SELECT ON api.market_snapshots TO anon, authenticated;

COMMIT;
