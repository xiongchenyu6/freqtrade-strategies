-- Expose quant.hyperopt_epochs to PostgREST via the api schema.
-- Pattern matches migrations/002_public_api_views.sql.

CREATE OR REPLACE VIEW api.hyperopt_epochs AS
SELECT id, strategy, file_ts, epoch,
       is_best, is_initial_point, is_random,
       loss, params,
       sharpe, calmar, sortino, sqn,
       profit_total, winrate, total_trades,
       max_drawdown, holding_avg_hours,
       results_explanation, synced_at
FROM quant.hyperopt_epochs;

-- Match the access pattern of other detail views: authenticated only.
-- (The /hyperopt page guards with qt_jwt cookie via vps.hyperoptEpochs auth.)
GRANT SELECT ON api.hyperopt_epochs TO authenticated, service_role;

-- View is owned by the migration runner; let it bypass the underlying RLS
-- by ensuring the view inherits the caller's role at runtime. PostgREST
-- defaults to security_invoker so the connecting role is what counts.
ALTER VIEW api.hyperopt_epochs SET (security_invoker = true);

-- Grant SELECT on the underlying quant.hyperopt_epochs to authenticated so
-- the security_invoker view actually returns rows.
GRANT USAGE ON SCHEMA quant TO authenticated;
GRANT SELECT ON quant.hyperopt_epochs TO authenticated;

-- Tell PostgREST to rebuild its schema cache so the new path becomes live.
NOTIFY pgrst, 'reload schema';
