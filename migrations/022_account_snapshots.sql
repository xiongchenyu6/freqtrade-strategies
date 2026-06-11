-- 022: daily account NetLiq snapshots — the verifiable real-account equity curve.
--
-- Screenshots can be faked; a platform-computed daily NetLiq series of OUR OWN accounts
-- (IB paper DUQ654554, Binance testnet) cannot. One row per account per day, written by
-- scripts on the game box (read-only API connections). Public read via api view — this
-- IS the transparency artifact ("公开账本" with a curve instead of a table).
--
-- Apply as postgres on oracle-arm-002:
--   ssh oracle-arm-002 sudo runuser -u postgres -- psql -d api -f - < migrations/022_account_snapshots.sql

BEGIN;

CREATE TABLE IF NOT EXISTS quant.account_snapshots (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ts          timestamptz NOT NULL DEFAULT now(),
  snap_date   date NOT NULL DEFAULT (now() AT TIME ZONE 'utc')::date,
  account     text NOT NULL,             -- 'IB-DUQ654554' | 'BINANCE-TESTNET'
  asset_class text NOT NULL,             -- 'equity' | 'crypto'
  environment text NOT NULL,             -- 'paper' | 'testnet'
  net_liq     numeric NOT NULL,
  currency    text NOT NULL,
  detail      jsonb NOT NULL DEFAULT '{}'  -- balances breakdown / positions value
);

CREATE UNIQUE INDEX IF NOT EXISTS account_snapshots_daily ON quant.account_snapshots (account, snap_date);

GRANT SELECT, INSERT, UPDATE ON quant.account_snapshots TO quant;

CREATE OR REPLACE VIEW api.account_snapshots AS
  SELECT snap_date, account, asset_class, environment, net_liq, currency, ts
  FROM quant.account_snapshots ORDER BY snap_date;
GRANT SELECT ON api.account_snapshots TO anon, authenticated;

COMMIT;
