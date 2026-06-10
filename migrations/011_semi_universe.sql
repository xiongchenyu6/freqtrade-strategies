-- 011: NVDA-centric semiconductor supply-chain universe (powers the /semis analysis page).
-- Populated by nautilus_equity/semi_analysis.py from real Yahoo daily closes — honest numbers,
-- no synthetic data. One row per ticker; re-runs upsert.

CREATE TABLE IF NOT EXISTS quant.semi_universe (
    symbol        text PRIMARY KEY,
    name          text NOT NULL,
    tier          text NOT NULL,        -- core | upstream | peer | downstream | benchmark
    role          text,
    last_price    numeric,
    ret_1w        numeric,
    ret_1m        numeric,
    ret_3m        numeric,
    ret_6m        numeric,
    ret_1y        numeric,
    ret_ytd       numeric,
    rs_vs_nvda    numeric,              -- 3m return minus NVDA's 3m return (pp)
    rs_vs_smh     numeric,              -- 3m return minus SMH's 3m return (pp)
    corr_nvda     numeric,              -- daily-return correlation to NVDA (~6m)
    beta_nvda     numeric,
    vol_annual    numeric,              -- annualised vol %
    from_52w_high numeric,              -- % below trailing 52w high (<= 0)
    mom_score     numeric,              -- cross-sectional momentum z-score
    alpha_score   numeric,              -- momentum + catch-up tilt
    alpha_note    text,                 -- generated rationale
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Public list view.
CREATE OR REPLACE VIEW api.semi_universe AS
SELECT symbol, name, tier, role, last_price,
       ret_1w, ret_1m, ret_3m, ret_6m, ret_1y, ret_ytd,
       rs_vs_nvda, rs_vs_smh, corr_nvda, beta_nvda, vol_annual, from_52w_high,
       mom_score, alpha_score, alpha_note, updated_at
FROM quant.semi_universe;

-- Tier aggregates (avg performance per supply-chain tier, ex-benchmark).
CREATE OR REPLACE VIEW api.semi_groups AS
SELECT tier,
       count(*)::int                       AS members,
       round(avg(ret_1m)::numeric, 2)      AS avg_ret_1m,
       round(avg(ret_3m)::numeric, 2)      AS avg_ret_3m,
       round(avg(ret_1y)::numeric, 2)      AS avg_ret_1y,
       round(avg(corr_nvda)::numeric, 2)   AS avg_corr_nvda,
       max(updated_at)                     AS updated_at
FROM quant.semi_universe
WHERE tier <> 'benchmark'
GROUP BY tier;

GRANT SELECT ON api.semi_universe, api.semi_groups TO anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON quant.semi_universe TO quant;
