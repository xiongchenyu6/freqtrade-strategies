-- 019: add the 'vix_threshold' signal kind — the US-equity counterpart of fng_threshold.
-- params {above: number} — fires when the VIX daily close >= above (fear spike).
-- Asset is '*' (market-wide), timeframe '1d', mirroring fng_threshold.
--
-- Apply as postgres on oracle-arm-002:
--   ssh oracle-arm-002 sudo runuser -u postgres -- psql -d api -f - < migrations/019_vix_signal_kind.sql

BEGIN;

ALTER TABLE quant.user_signals DROP CONSTRAINT IF EXISTS user_signals_kind_check;
ALTER TABLE quant.user_signals ADD CONSTRAINT user_signals_kind_check
  CHECK (kind IN ('ema_cross', 'donchian_breakout', 'fng_threshold', 'vix_threshold'));

COMMIT;
