-- Weekly email digest pipeline.
--
-- Two pg_cron jobs:
--   weekly-digest-enqueue — Monday 09:00 UTC, compiles HTML per subscriber,
--                           inserts one email_queue row per user.
--   email-dispatch        — every 5 minutes, picks up pending rows and POSTs
--                           them to Resend via pgsql-http. Retries up to 3×.
--
-- Resend API key is stored in quant.app_config. If unset, dispatcher no-ops
-- silently so the rest of the pipeline can be tested without the key.
--
--   INSERT INTO quant.app_config (key, value) VALUES ('resend_api_key', 're_xxx')
--     ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
--
--   UPDATE quant.app_config SET value = 'noreply@panda.qzz.io' WHERE key = 'email_from';
--
-- Apply from VPS:
--   ssh oracle-arm-002 sudo -u postgres psql -d api -f - < migrations/005_email_pipeline.sql

BEGIN;

-- ============================================================================
-- Config table (RLS: service_role only).
-- ============================================================================
CREATE TABLE IF NOT EXISTS quant.app_config (
  key         text PRIMARY KEY,
  value       text,
  updated_at  timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE quant.app_config ENABLE ROW LEVEL SECURITY;
-- Deny everything by default; service_role bypasses RLS.
REVOKE ALL ON quant.app_config FROM PUBLIC, anon, authenticated;
GRANT ALL ON quant.app_config TO service_role;

INSERT INTO quant.app_config (key, value) VALUES
  ('resend_api_key', ''),
  ('email_from', 'Crypto Quant <noreply@panda.qzz.io>'),
  ('dashboard_url', 'https://quant.panda.qzz.io')
ON CONFLICT (key) DO NOTHING;

-- ============================================================================
-- Email queue.
-- ============================================================================
CREATE TABLE IF NOT EXISTS quant.email_queue (
  id                 bigserial PRIMARY KEY,
  user_id            uuid REFERENCES auth.users(id) ON DELETE CASCADE,
  to_email           text NOT NULL,
  subject            text NOT NULL,
  html               text NOT NULL,
  status             text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'sending', 'sent', 'failed')),
  attempts           int  NOT NULL DEFAULT 0,
  last_error         text,
  resend_message_id  text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  sent_at            timestamptz
);
CREATE INDEX IF NOT EXISTS email_queue_status_idx
  ON quant.email_queue (status, id) WHERE status IN ('pending', 'sending');

ALTER TABLE quant.email_queue ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON quant.email_queue FROM PUBLIC, anon, authenticated;
GRANT ALL ON quant.email_queue TO service_role;

-- ============================================================================
-- Weekly digest generator — one row per subscribed user.
--
-- Content: last 7 days of BTC % move, event DCA triggers (count + top kind),
-- new backtest runs, and a link back to the dashboard. Plain, single-column
-- HTML; renders in every client.
-- ============================================================================
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
    JOIN auth.users u ON u.id = up.user_id
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

-- ============================================================================
-- Dispatcher — polls the queue and POSTs to Resend.
-- ============================================================================
CREATE OR REPLACE FUNCTION quant.dispatch_emails(max_batch int DEFAULT 25)
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = quant, public, extensions
AS $$
DECLARE
  v_api_key   text;
  v_from      text;
  v_row       record;
  v_resp      record;
  v_sent      int := 0;
  v_body      text;
  v_msg_id    text;
BEGIN
  SELECT value INTO v_api_key FROM quant.app_config WHERE key = 'resend_api_key';
  SELECT value INTO v_from    FROM quant.app_config WHERE key = 'email_from';
  IF v_api_key IS NULL OR v_api_key = '' THEN
    RETURN 0;  -- graceful no-op when key unset
  END IF;

  FOR v_row IN
    SELECT id, to_email, subject, html, attempts
      FROM quant.email_queue
     WHERE status = 'pending' AND attempts < 3
     ORDER BY id
     LIMIT max_batch
  LOOP
    UPDATE quant.email_queue
       SET status = 'sending', attempts = attempts + 1
     WHERE id = v_row.id;

    v_body := json_build_object(
      'from',    v_from,
      'to',      json_build_array(v_row.to_email),
      'subject', v_row.subject,
      'html',    v_row.html
    )::text;

    BEGIN
      SELECT status, content INTO v_resp
        FROM extensions.http((
          'POST',
          'https://api.resend.com/emails',
          ARRAY[extensions.http_header('Authorization', 'Bearer ' || v_api_key)],
          'application/json',
          v_body
        )::extensions.http_request);

      IF v_resp.status BETWEEN 200 AND 299 THEN
        BEGIN
          v_msg_id := (v_resp.content::jsonb ->> 'id');
        EXCEPTION WHEN OTHERS THEN
          v_msg_id := NULL;
        END;
        UPDATE quant.email_queue
           SET status = 'sent',
               sent_at = now(),
               resend_message_id = v_msg_id
         WHERE id = v_row.id;
        v_sent := v_sent + 1;
      ELSE
        UPDATE quant.email_queue
           SET status = CASE WHEN v_row.attempts + 1 >= 3 THEN 'failed' ELSE 'pending' END,
               last_error = v_resp.status || ' ' || left(v_resp.content, 500)
         WHERE id = v_row.id;
      END IF;
    EXCEPTION WHEN OTHERS THEN
      UPDATE quant.email_queue
         SET status = CASE WHEN v_row.attempts + 1 >= 3 THEN 'failed' ELSE 'pending' END,
             last_error = SQLERRM
       WHERE id = v_row.id;
    END;
  END LOOP;

  RETURN v_sent;
END;
$$;

-- ============================================================================
-- pg_cron schedules.
-- ============================================================================

-- Drop existing (idempotent replay).
SELECT cron.unschedule(jobid) FROM cron.job
 WHERE jobname IN ('weekly-digest-enqueue', 'email-dispatch');

-- Monday 09:00 UTC — enqueue the week's digests.
SELECT cron.schedule(
  'weekly-digest-enqueue',
  '0 9 * * 1',
  $$SELECT quant.enqueue_weekly_digests()$$
);

-- Every 5 minutes — drain the queue. Cheap when empty.
SELECT cron.schedule(
  'email-dispatch',
  '*/5 * * * *',
  $$SELECT quant.dispatch_emails(25)$$
);

COMMIT;

\echo
\echo === next steps ===
\echo After signing up for Resend:
\echo   UPDATE quant.app_config SET value = 're_xxx' WHERE key = 'resend_api_key';
\echo   (optional) UPDATE quant.app_config SET value = 'Your Name <you@domain>' WHERE key = 'email_from';
\echo Trigger a test digest manually:
\echo   SELECT quant.enqueue_weekly_digests();
\echo   SELECT quant.dispatch_emails();
