-- 012: add market cap to the semiconductor universe (the /semis page renders it as the
-- "version" in a package-dependency-tree view). Real caps from Yahoo's crumb-gated quote API.

ALTER TABLE quant.semi_universe ADD COLUMN IF NOT EXISTS market_cap numeric;

-- Append market_cap at the END (CREATE OR REPLACE VIEW cannot reorder existing columns).
DROP VIEW IF EXISTS api.semi_universe;
CREATE VIEW api.semi_universe AS
SELECT symbol, name, tier, role, last_price,
       ret_1w, ret_1m, ret_3m, ret_6m, ret_1y, ret_ytd,
       rs_vs_nvda, rs_vs_smh, corr_nvda, beta_nvda, vol_annual, from_52w_high,
       mom_score, alpha_score, alpha_note, updated_at, market_cap
FROM quant.semi_universe;

GRANT SELECT ON api.semi_universe TO anon, authenticated, service_role;
