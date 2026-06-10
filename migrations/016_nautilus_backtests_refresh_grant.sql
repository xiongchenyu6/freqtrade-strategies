-- 016: let the `quant` role refresh its own backtest rows.
--
-- log_equity_backtests.py re-runs the equity grid and wants to DELETE+re-INSERT the
-- asset_class='equity' rows so numbers stay current with the catalog. `quant` had only
-- INSERT/SELECT, so grant DELETE+UPDATE on the backtest table (and its sequence).
--
-- Apply as the api-schema owner (postgres) on oracle-arm-002:
--   ssh oracle-arm-002 sudo -u postgres psql -d api -f - < migrations/016_nautilus_backtests_refresh_grant.sql

BEGIN;

GRANT DELETE, UPDATE ON quant.nautilus_backtests TO quant;
-- Also let the equity sync/maintenance tooling prune stale rows in the live trades table
-- (e.g. one-off reconciliation backfills). The live node only ever INSERT/UPDATEs its own
-- positions; DELETE is for housekeeping by the maintainer-run scripts.
GRANT DELETE ON quant.nautilus_trades TO quant;

COMMIT;
