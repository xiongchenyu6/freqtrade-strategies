// Unified API client for quant.
//
// Three data sources; use the right helper:
//   vps.*       — PostgREST on VPS (heavy data: OHLC, backtests, live trades)
//   supabase.*  — Supabase cloud (application events: KOL, DCA log, sentiment)
//   pages.*     — our own Cloudflare Pages Functions (merged / server-secret)
//
// Auth:
//   vps requests auto-include Bearer JWT if logged in via auth.js (RLS on VPS).
//   Unauthenticated reads fall back to api_anon role (works on any view that
//   granted SELECT to api_anon, e.g. migration 002).
//
// Always returns parsed JSON. Throws on non-2xx (with { status, body }).
import { CONFIG } from './config.js';
import { auth } from './auth.js';

async function request(base, path, opts = {}) {
  const url = new URL(path, base).toString() +
              (opts.params ? '?' + new URLSearchParams(opts.params) : '');
  const headers = new Headers(opts.headers || {});
  headers.set('Accept', 'application/json');
  if (opts.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (opts.withAuth !== false) {
    const t = auth.token();
    if (t) headers.set('Authorization', `Bearer ${t}`);
  }
  const r = await fetch(url, {
    method: opts.method || 'GET',
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) {
    const text = await r.text().catch(() => '');
    const err = new Error(`${opts.method || 'GET'} ${url} → ${r.status}`);
    err.status = r.status;
    err.body = text;
    throw err;
  }
  if (r.status === 204) return null;
  const ct = r.headers.get('content-type') || '';
  return ct.includes('application/json') ? r.json() : r.text();
}

// ============================================================================
// VPS PostgREST  (api.panda.qzz.io)
// ============================================================================
export const vps = {
  async ohlcDaily(pair, { from, to, limit = 3000 } = {}) {
    const params = {
      pair: `eq.${pair}`,
      order: 'bucket.asc',
      limit,
    };
    if (from) params['bucket'] = `gte.${from}`;
    if (to)   params['and']    = `(bucket.lt.${to})`;
    return request(CONFIG.API_BASE, '/ohlc_1d', { params });
  },

  async ohlcHourly(pair, { from, to, limit = 3000 } = {}) {
    const params = { pair: `eq.${pair}`, order: 'bucket.asc', limit };
    if (from) params['bucket'] = `gte.${from}`;
    if (to)   params['and']    = `(bucket.lt.${to})`;
    return request(CONFIG.API_BASE, '/ohlc_1h_recent', { params });
  },

  async ohlc15m(pair, { from, to, limit = 3000 } = {}) {
    const params = { pair: `eq.${pair}`, order: 'bucket.asc', limit };
    if (from) params['bucket'] = `gte.${from}`;
    if (to)   params['and']    = `(bucket.lt.${to})`;
    return request(CONFIG.API_BASE, '/ohlc_15m_recent', { params });
  },

  /**
   * Auto-granularity: picks view based on span.
   * span_minutes / max_points target_min:
   *   ≤ 30  → 15m   (last 30 days only, PostgREST returns empty beyond)
   *   ≤ 300 → 1h    (last 90 days)
   *   else  → 1d    (full history)
   */
  async ohlcAuto(pair, { from, to, maxPoints = 2000 } = {}) {
    const fromD = from instanceof Date ? from : new Date(from);
    const toD   = to   instanceof Date ? to   : new Date(to);
    const spanMin = (toD - fromD) / 60_000;
    const target  = spanMin / maxPoints;

    const fromIso = fromD.toISOString();
    const toIso   = toD.toISOString();
    let source;
    if (target <= 30) {
      source = await this.ohlc15m(pair, { from: fromIso, to: toIso, limit: maxPoints });
      source._table = 'ohlc_15m_recent';
    } else if (target <= 300) {
      source = await this.ohlcHourly(pair, { from: fromIso, to: toIso, limit: maxPoints });
      source._table = 'ohlc_1h_recent';
    } else {
      source = await this.ohlcDaily(pair, { from: fromIso, to: toIso, limit: maxPoints });
      source._table = 'ohlc_1d';
    }
    return source;
  },

  async backtestRuns({ strategy, limit = 100, order = 'started_at.desc' } = {}) {
    const params = { order, limit };
    if (strategy) params['strategy'] = `eq.${strategy}`;
    return request(CONFIG.API_BASE, '/backtest_runs', { params });
  },

  async backtestTrades(runId) {
    return request(CONFIG.API_BASE, '/backtest_trades',
      { params: { run_id: `eq.${runId}`, order: 'open_date.asc' } });
  },

  async liveTrades({ bot, limit = 100 } = {}) {
    const params = { order: 'open_date.desc', limit };
    if (bot) params['bot_name'] = `eq.${bot}`;
    return request(CONFIG.API_BASE, '/live_trades', { params });
  },

  async walkForward({ strategy, limit = 200 } = {}) {
    const params = { order: 'run_date.desc,window_label.asc', limit };
    if (strategy) params['strategy'] = `eq.${strategy}`;
    return request(CONFIG.API_BASE, '/wf_results', { params });
  },

  async eventDcaTriggers({ limit = 100 } = {}) {
    return request(CONFIG.API_BASE, '/event_dca_triggers',
      { params: { order: 'ts.desc', limit } });
  },
};

// ============================================================================
// Supabase cloud  (rhweqsxothaezsbxjwaj.supabase.co)
// ============================================================================
async function supabaseRequest(path, opts = {}) {
  const headers = new Headers(opts.headers || {});
  headers.set('apikey', CONFIG.SUPABASE_ANON);
  headers.set('Authorization', `Bearer ${CONFIG.SUPABASE_ANON}`);
  return request(CONFIG.SUPABASE_URL, `/rest/v1${path}`,
    { ...opts, withAuth: false, headers });
}

export const supabase = {
  kolEvents:         ({ limit = 100 } = {}) =>
    supabaseRequest('/kol_events',
      { params: { order: 'timestamp.desc', limit } }),
  dcaLog:            ({ limit = 100 } = {}) =>
    supabaseRequest('/dca_log',
      { params: { order: 'timestamp.desc', limit } }),
  sentimentSnapshots:({ limit = 100 } = {}) =>
    supabaseRequest('/sentiment_snapshots',
      { params: { order: 'timestamp.desc', limit } }),
  deribitSnapshots:  ({ limit = 20  } = {}) =>
    supabaseRequest('/deribit_snapshots',
      { params: { order: 'timestamp.desc', limit } }),
};

// ============================================================================
// Pages Functions (this site's own /api/*)
// ============================================================================
export const pages = {
  summary: () => request('', '/api/summary'),
};

// Health check — useful for status badges
export async function healthCheck() {
  const results = await Promise.allSettled([
    fetch(CONFIG.API_BASE + '/').then(r => r.ok),
    fetch(CONFIG.AUTH_BASE + '/health').then(r => r.ok),
    fetch(CONFIG.SUPABASE_URL + '/rest/v1/').then(r => r.status === 200 || r.status === 404),
  ]);
  return {
    api:      results[0].status === 'fulfilled' && results[0].value,
    auth:     results[1].status === 'fulfilled' && results[1].value,
    supabase: results[2].status === 'fulfilled' && results[2].value,
  };
}
