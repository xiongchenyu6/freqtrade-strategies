/**
 * GET /api/summary
 * Aggregates data from VPS PostgREST + Supabase into a single response.
 * Runs at CF edge — fast for users globally.
 *
 * Why this function:
 *  - Would require 3 round-trips from browser (cold start latency for friends abroad)
 *  - Here: single HTTPS to CF edge, three parallel fetches from edge → sources
 *  - Edge can cache (see response headers)
 */

interface Env {
  API_BASE: string;
  SUPABASE_URL: string;
  SUPABASE_ANON: string;
}

interface SummaryResponse {
  updated_at: string;
  backtest: {
    total_runs: number;
    best_profit_pct: number | null;
    best_calmar: number | null;
    top_3: any[];
  };
  live: {
    total_trades: number;
    open_trades: number;
    recent_5: any[];
  };
  events: {
    recent_kol: any[];
    recent_dca: any[];
  };
  health: Record<string, boolean>;
}

export const onRequestGet: PagesFunction<Env> = async ({ env }) => {
  const api = env.API_BASE || 'https://api.panda.qzz.io';
  const sb  = env.SUPABASE_URL || 'https://rhweqsxothaezsbxjwaj.supabase.co';
  const sbKey = env.SUPABASE_ANON || '';

  const jsonHeaders = { 'Accept': 'application/json' };
  const sbHeaders   = { ...jsonHeaders,
                         apikey: sbKey,
                         Authorization: `Bearer ${sbKey}` };

  const fetchOk = async (url: string, headers = jsonHeaders) => {
    try {
      const r = await fetch(url, { headers, cf: { cacheTtl: 30 } as any });
      if (!r.ok) return null;
      return r.json();
    } catch { return null; }
  };

  const [runs, liveTrades, kol, dca] = await Promise.all([
    fetchOk(`${api}/backtest_runs?order=total_profit_pct.desc.nullslast&limit=500`),
    fetchOk(`${api}/live_trades?order=open_date.desc&limit=50`),
    fetchOk(`${sb}/rest/v1/kol_events?order=timestamp.desc&limit=10`, sbHeaders),
    fetchOk(`${sb}/rest/v1/dca_log?order=timestamp.desc&limit=10`, sbHeaders),
  ]);

  const runsArr: any[] = Array.isArray(runs) ? runs : [];
  const liveArr: any[] = Array.isArray(liveTrades) ? liveTrades : [];

  const payload: SummaryResponse = {
    updated_at: new Date().toISOString(),
    backtest: {
      total_runs: runsArr.length,
      best_profit_pct: runsArr.length
        ? Math.max(...runsArr.map(r => r.total_profit_pct ?? -Infinity))
        : null,
      best_calmar: runsArr.length
        ? Math.max(...runsArr.map(r => r.calmar ?? -Infinity))
        : null,
      top_3: runsArr.slice(0, 3).map(r => ({
        id: r.id, strategy: r.strategy, timeframe: r.timeframe,
        total_profit_pct: r.total_profit_pct,
        max_drawdown_pct: r.max_drawdown_pct,
        total_trades: r.total_trades,
        started_at: r.started_at,
      })),
    },
    live: {
      total_trades: liveArr.length,
      open_trades: liveArr.filter(t => !t.close_date).length,
      recent_5: liveArr.slice(0, 5),
    },
    events: {
      recent_kol: Array.isArray(kol) ? kol : [],
      recent_dca: Array.isArray(dca) ? dca : [],
    },
    health: {
      vps_api:  !!runs,
      supabase: !!kol || !!dca,
    },
  };

  return new Response(JSON.stringify(payload), {
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'public, max-age=30',
      'Access-Control-Allow-Origin': '*',
    },
  });
};
