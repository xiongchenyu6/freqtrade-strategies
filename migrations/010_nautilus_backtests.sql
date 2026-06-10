-- 010: Nautilus backtest stats — isolated from the freqtrade quant.backtest_runs / api.public_stats.
-- The dashboard redesign (Stage 9) shows HONEST current numbers: these rows come from re-running
-- the deployed strategies on NautilusTrader, not the retired freqtrade strategies. Kept in a
-- separate table (mirrors how 009 isolated nautilus_trades from freqtrade trades) so the old
-- freqtrade backtest_runs stays untouched as legacy history.

CREATE TABLE IF NOT EXISTS quant.nautilus_backtests (
    id            bigserial PRIMARY KEY,
    engine        text        NOT NULL DEFAULT 'nautilus',
    asset_class   text        NOT NULL,             -- 'crypto' | 'equity'
    strategy      text        NOT NULL,             -- DonchianBreakout / Accumulator / HonestTrend
    label         text        NOT NULL,             -- human label, e.g. 'ETH+BTC+SOL 1h portfolio'
    instruments   text[],                           -- ['ETHUSDT.BINANCE', ...] or ['NVDA.NASDAQ', ...]
    timeframe     text,                             -- '1h' / '1d'
    period_start  date,
    period_end    date,
    environment   text        NOT NULL DEFAULT 'backtest',  -- 'backtest' (equity) | 'backtest-validated' (crypto recent-OOS)
    total_trades  integer,
    wins          integer,
    losses        integer,
    win_rate_pct  numeric,
    total_profit_pct numeric,
    max_drawdown_pct numeric,                       -- negative (true DD from EquityRecorder)
    calmar        numeric,                          -- total_return / |maxDD|
    sharpe        numeric,
    sortino       numeric,
    params        jsonb,                            -- strategy params (entry_lb, risk_frac, ...)
    run_at        timestamptz NOT NULL DEFAULT now(),
    -- one row per (strategy, label, period) — re-runs upsert
    UNIQUE (strategy, label, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS nautilus_backtests_asset_idx ON quant.nautilus_backtests (asset_class, run_at DESC);

-- Public list view (archive / strategies pages read this).
CREATE OR REPLACE VIEW api.nautilus_backtests AS
SELECT id, engine, asset_class, strategy, label, instruments, timeframe,
       period_start, period_end, environment,
       total_trades, wins, losses, win_rate_pct,
       total_profit_pct, max_drawdown_pct, calmar, sharpe, sortino,
       params, run_at
FROM quant.nautilus_backtests
ORDER BY asset_class, run_at DESC;

-- Aggregate view — same shape as api.public_stats so the homepage KPIs swap cleanly.
CREATE OR REPLACE VIEW api.nautilus_stats AS
SELECT
  count(*)::int                              AS total_runs,
  COALESCE(sum(total_trades), 0)::bigint     AS total_trades,
  count(DISTINCT strategy)::int              AS distinct_strategies,
  count(DISTINCT asset_class)::int           AS distinct_asset_classes,
  round(max(total_profit_pct)::numeric, 2)   AS best_profit_pct,
  round(max(calmar)::numeric, 2)             AS best_calmar,
  round(max(sharpe)::numeric, 2)             AS best_sharpe,
  round(max(sortino)::numeric, 2)            AS best_sortino,
  round(max(win_rate_pct)::numeric, 2)       AS best_win_rate,
  round(min(max_drawdown_pct)::numeric, 2)   AS min_max_dd,
  max(run_at)                                AS last_updated
FROM quant.nautilus_backtests;

GRANT SELECT ON api.nautilus_backtests, api.nautilus_stats TO anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON quant.nautilus_backtests TO quant;
GRANT USAGE, SELECT ON SEQUENCE quant.nautilus_backtests_id_seq TO quant;
