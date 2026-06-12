-- 026: 市场压力指数 — an EXPLAINABLE composite from data we already collect.
--
-- One row per hourly run (time series, so the web can chart it later). The score is
-- never a black box: `components` stores every input's raw value, its 0-100 subscore,
-- and the mapping note. Composite = plain mean of available subscores (≥2 required).
--
-- Components (all our own collectors / public endpoints, nothing fabricated):
--   fng      — alternative.me Fear&Greed       → stress = 100 - fng
--   vix      — Yahoo ^VIX daily close          → stress = clamp((vix-12)/28*100)
--   funding  — Binance BTCUSDT 8h funding rate → 50 at +0.01% (neutral), deeper
--              negative = shorts pay = fear → higher stress
--   breadth  — % of quant.semi_universe with ret_1m > 0 → stress = 100 - breadth
--
-- Apply as postgres on oracle-arm-002:
--   ssh oracle-arm-002 sudo runuser -u postgres -- psql -d api -f - < migrations/026_market_stress.sql

BEGIN;

CREATE TABLE IF NOT EXISTS quant.market_stress (
  ts           timestamptz PRIMARY KEY DEFAULT now(),
  stress_score numeric(5,1) NOT NULL CHECK (stress_score >= 0 AND stress_score <= 100),
  label        text NOT NULL,             -- 平静 | 正常 | 紧张 | 高压
  components   jsonb NOT NULL             -- {fng:{raw,score,note}, vix:{...}, ...}
);

GRANT SELECT, INSERT, DELETE ON quant.market_stress TO quant;

CREATE OR REPLACE VIEW api.market_stress AS
  SELECT ts, stress_score, label, components
  FROM quant.market_stress
  WHERE ts > now() - interval '90 days'
  ORDER BY ts DESC;
GRANT SELECT ON api.market_stress TO anon, authenticated;

COMMIT;
