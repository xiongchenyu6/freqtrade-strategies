-- 031_auth0_migration.sql
--
-- Stage 2 of the GoTrue → Auth0 migration (forward-compatible, applied while
-- GoTrue is still live). After this migration BOTH token shapes work:
--   * legacy GoTrue tokens:  sub = <uuid>, role = authenticated
--   * Auth0 tokens:          https://panda.qzz.io/uid|role|email custom claims
--
-- What it does:
--   1. quant.users shadow table (replaces auth.users as the FK target).
--   2. Re-point the 4 business FKs from auth.users → quant.users.
--   3. Rewrite auth.uid()/role()/email() as dual-read (namespaced claim first,
--      legacy claim fallback). auth.jwt() unchanged in behaviour.
--   4. quant.enqueue_weekly_digests(): JOIN quant.users instead of auth.users.
--   5. quant.ensure_user(): PostgREST db-pre-request hook that upserts the
--      current user into quant.users (new Auth0 signups have no GoTrue row).
--
-- Apply (as usual, runs as postgres superuser — required here for the
-- ALTER FUNCTION ... OWNER of the supabase_auth_admin-owned auth.* functions):
--   ssh oracle-arm-002 "sudo runuser -u postgres -- psql -d api -v ON_ERROR_STOP=1" < migrations/031_auth0_migration.sql
--   ssh oracle-arm-002 "sudo runuser -u postgres -- psql -d api -c \"NOTIFY pgrst, 'reload schema'\""
--
-- Rollback (pre-cutover only): re-point the 4 FKs back to auth.users(id),
-- restore the original function bodies (preserved in comments below), and
-- DROP TABLE quant.users, DROP FUNCTION quant.ensure_user().

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Shadow user table. auth.users stays untouched (it is the rollback safety
--    net until 032 retires GoTrue for good).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quant.users (
  id         uuid PRIMARY KEY,
  email      text,
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE quant.users OWNER TO quant;
GRANT SELECT ON quant.users TO service_role;

INSERT INTO quant.users (id, email, created_at)
SELECT id, email, created_at FROM auth.users
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. Re-point business FKs (constraint names verified in prod 2026-07-28).
-- ---------------------------------------------------------------------------
ALTER TABLE quant.user_preferences
  DROP CONSTRAINT user_preferences_user_id_fkey,
  ADD CONSTRAINT user_preferences_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES quant.users(id) ON DELETE CASCADE;

ALTER TABLE quant.email_queue
  DROP CONSTRAINT email_queue_user_id_fkey,
  ADD CONSTRAINT email_queue_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES quant.users(id) ON DELETE CASCADE;

ALTER TABLE quant.backtest_jobs
  DROP CONSTRAINT backtest_jobs_user_id_fkey,
  ADD CONSTRAINT backtest_jobs_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES quant.users(id) ON DELETE CASCADE;

ALTER TABLE quant.backtest_results
  DROP CONSTRAINT backtest_results_user_id_fkey,
  ADD CONSTRAINT backtest_results_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES quant.users(id) ON DELETE CASCADE;

-- ---------------------------------------------------------------------------
-- 3. Dual-read auth helper functions.
--
-- Owner moves supabase_auth_admin → postgres so 032 can drop the role, and so
-- future replaces don't need the GoTrue role. Function NAMES stay the same so
-- every RLS policy (9 tables) keeps working unmodified.
--
-- Original GoTrue bodies (for rollback):
--   auth.uid():   coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''),
--                          (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'))::uuid
--   auth.role():  same shape, claim 'role'
--   auth.email(): same shape, claim 'email'
--   auth.jwt():   coalesce(nullif(current_setting('request.jwt.claim', true), ''),
--                          nullif(current_setting('request.jwt.claims', true), ''))::jsonb
-- ---------------------------------------------------------------------------
ALTER FUNCTION auth.uid()   OWNER TO postgres;
ALTER FUNCTION auth.role()  OWNER TO postgres;
ALTER FUNCTION auth.email() OWNER TO postgres;
ALTER FUNCTION auth.jwt()   OWNER TO postgres;

CREATE OR REPLACE FUNCTION auth.jwt() RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb
$$;

-- Namespaced keys contain '/' so they can only be read via jsonb ->>, never
-- via the request.jwt.claim.* GUC form.
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT coalesce(
    auth.jwt() ->> 'https://panda.qzz.io/uid',                    -- Auth0
    nullif(current_setting('request.jwt.claim.sub', true), ''),   -- legacy GoTrue
    auth.jwt() ->> 'sub'
  )::uuid
$$;

CREATE OR REPLACE FUNCTION auth.role() RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT coalesce(
    auth.jwt() ->> 'https://panda.qzz.io/role',
    nullif(current_setting('request.jwt.claim.role', true), ''),
    auth.jwt() ->> 'role'
  )
$$;

CREATE OR REPLACE FUNCTION auth.email() RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT coalesce(
    auth.jwt() ->> 'https://panda.qzz.io/email',
    nullif(current_setting('request.jwt.claim.email', true), ''),
    auth.jwt() ->> 'email'
  )
$$;

-- The api.* views are security_invoker=true, so RLS policies run AS the
-- requesting role — which therefore needs USAGE on schema auth to call
-- auth.uid(). This grant was missing in prod (verified 2026-07-28: a real
-- authenticated request to api.user_preferences returned 403 "permission
-- denied for schema auth"), so per-user reads were silently broken. Table
-- privileges inside auth are NOT granted — auth.users stays unreadable.
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role, api_authenticator;
GRANT EXECUTE ON FUNCTION auth.jwt(), auth.uid(), auth.role(), auth.email()
  TO anon, authenticated, service_role, api_authenticator;

-- ---------------------------------------------------------------------------
-- 4. Weekly digest: read emails from quant.users. Body identical to 005
--    except the JOIN target.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION quant.enqueue_weekly_digests()
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = quant, public
AS $$
DECLARE
  v_count       int := 0;
  v_user        record;
  v_dashboard   text;
  v_btc_now     numeric;
  v_btc_prev    numeric;
  v_btc_delta   numeric;
  v_event_rows  int;
  v_top_kind    text;
  v_run_rows    int;
  v_subject     text;
  v_html        text;
  v_name        text;
BEGIN
  SELECT value INTO v_dashboard FROM quant.app_config WHERE key = 'dashboard_url';
  v_dashboard := COALESCE(v_dashboard, 'https://quant.panda.qzz.io');

  -- BTC % move over the past 7 days (daily close).
  SELECT close INTO v_btc_now
    FROM quant.ohlc_1d WHERE pair = 'BTC/USDT'
    ORDER BY bucket DESC LIMIT 1;
  SELECT close INTO v_btc_prev
    FROM quant.ohlc_1d WHERE pair = 'BTC/USDT' AND bucket < now() - INTERVAL '7 days'
    ORDER BY bucket DESC LIMIT 1;
  v_btc_delta := CASE WHEN v_btc_prev IS NULL OR v_btc_prev = 0 THEN 0
                      ELSE ((v_btc_now - v_btc_prev) / v_btc_prev) * 100 END;

  -- Event DCA triggers this week.
  SELECT count(*)::int INTO v_event_rows
    FROM quant.event_dca_triggers WHERE ts >= now() - INTERVAL '7 days';
  SELECT kind INTO v_top_kind
    FROM quant.event_dca_triggers WHERE ts >= now() - INTERVAL '7 days'
    ORDER BY severity DESC NULLS LAST LIMIT 1;

  -- New backtest runs this week.
  SELECT count(*)::int INTO v_run_rows
    FROM quant.backtest_runs WHERE imported_at >= now() - INTERVAL '7 days';

  FOR v_user IN
    SELECT up.user_id, u.email, up.display_name
    FROM quant.user_preferences up
    JOIN quant.users u ON u.id = up.user_id
    WHERE up.email_digest = true AND u.email IS NOT NULL
  LOOP
    v_name := COALESCE(
      v_user.display_name,
      split_part(v_user.email, '@', 1)
    );
    v_subject := format(
      'Crypto Quant weekly — BTC %s%%, %s events',
      CASE WHEN v_btc_delta >= 0 THEN '+' ELSE '' END || round(v_btc_delta, 1),
      v_event_rows
    );
    v_html := format($F$
<!doctype html><html><body style="margin:0;padding:0;background:#0b0d11;color:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,'Inter',sans-serif;">
  <table width="100%%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:0 auto;padding:32px 20px;">
    <tr><td>
      <h1 style="font-size:22px;margin:0 0 6px;color:#fff;">Crypto Quant · weekly</h1>
      <p style="color:#9ca3af;font-size:13px;margin:0 0 24px;">Hi %s — here's what the bots did this week.</p>

      <table width="100%%" cellpadding="0" cellspacing="0" style="border:1px solid #1f2937;border-radius:10px;padding:20px;">
        <tr><td>
          <div style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:.5px;">BTC · 7d</div>
          <div style="font-size:28px;font-weight:600;color:%s;margin-top:4px;">%s%% </div>
          <div style="color:#6b7280;font-size:12px;margin-top:2px;">now $%s · 7 days ago $%s</div>
        </td></tr>
      </table>

      <table width="100%%" cellpadding="0" cellspacing="0" style="margin-top:16px;">
        <tr>
          <td width="50%%" valign="top" style="padding-right:8px;">
            <div style="border:1px solid #1f2937;border-radius:10px;padding:16px;">
              <div style="font-size:11px;color:#9ca3af;text-transform:uppercase;">Event DCA triggers</div>
              <div style="font-size:22px;font-weight:600;color:#fff;margin-top:4px;">%s</div>
              <div style="color:#6b7280;font-size:12px;margin-top:2px;">top kind: %s</div>
            </div>
          </td>
          <td width="50%%" valign="top" style="padding-left:8px;">
            <div style="border:1px solid #1f2937;border-radius:10px;padding:16px;">
              <div style="font-size:11px;color:#9ca3af;text-transform:uppercase;">New backtests</div>
              <div style="font-size:22px;font-weight:600;color:#fff;margin-top:4px;">%s</div>
              <div style="color:#6b7280;font-size:12px;margin-top:2px;">imported this week</div>
            </div>
          </td>
        </tr>
      </table>

      <div style="margin-top:28px;text-align:center;">
        <a href="%s" style="display:inline-block;background:#3b82f6;color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;font-weight:500;font-size:14px;">See the full dashboard →</a>
      </div>

      <p style="color:#6b7280;font-size:11px;margin-top:32px;text-align:center;line-height:1.5;">
        You're getting this because you opted in on /dca.<br>
        Unsubscribe: toggle the weekly digest checkbox on <a href="%s/dca" style="color:#9ca3af;">/dca</a>.
      </p>
    </td></tr>
  </table>
</body></html>
$F$,
      v_name,
      CASE WHEN v_btc_delta >= 0 THEN '#22c55e' ELSE '#ef4444' END,
      CASE WHEN v_btc_delta >= 0 THEN '+' ELSE '' END || round(v_btc_delta, 1),
      to_char(round(v_btc_now),  'FM999G999'),
      to_char(round(v_btc_prev), 'FM999G999'),
      v_event_rows,
      COALESCE(v_top_kind, '—'),
      v_run_rows,
      v_dashboard,
      v_dashboard
    );

    INSERT INTO quant.email_queue (user_id, to_email, subject, html)
    VALUES (v_user.user_id, v_user.email, v_subject, v_html);
    v_count := v_count + 1;
  END LOOP;

  RETURN v_count;
END;
$$;

-- ---------------------------------------------------------------------------
-- 5. PostgREST pre-request hook: first request from a new Auth0 user creates
--    their quant.users row so the business-table FKs are satisfiable.
--    Wired up at cutover via postgrest `db-pre-request = "quant.ensure_user"`.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION quant.ensure_user()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = quant
AS $$
BEGIN
  -- PostgREST wraps GET/HEAD in READ ONLY transactions where the INSERT would
  -- fail (25006). The row is only needed before writes anyway, and every
  -- FK-relevant write request runs read-write.
  IF current_setting('transaction_read_only') = 'off'
     AND auth.role() = 'authenticated' AND auth.uid() IS NOT NULL THEN
    INSERT INTO quant.users (id, email)
    VALUES (auth.uid(), auth.email())
    ON CONFLICT (id) DO NOTHING;
  END IF;
END;
$$;
ALTER FUNCTION quant.ensure_user() OWNER TO postgres;
GRANT EXECUTE ON FUNCTION quant.ensure_user()
  TO anon, authenticated, service_role, api_authenticator;

COMMIT;
