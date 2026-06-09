// Self-service backtest playground client — thin wrapper around api.backtest_jobs /
// api.backtest_results (PostgREST). Mirrors userPrefs.ts. Requires a valid JWT; RLS
// (auth.uid()) scopes everything to the current user. The runner (game box) executes
// queued jobs and writes results. See PLAYGROUND_PLAN.md + migrations/014.
import { CONFIG } from './config';
import { getToken } from './auth';

export type Strategy = 'honest_trend' | 'accumulator' | 'donchian';
export type JobStatus = 'queued' | 'running' | 'done' | 'error';

export interface BacktestJob {
	id: string;
	user_id: string;
	strategy: Strategy;
	params: Record<string, unknown>;
	status: JobStatus;
	error: string | null;
	created_at: string;
	updated_at: string;
}

export interface BacktestResult {
	job_id: string;
	user_id: string;
	metrics: {
		return_pct: number;
		max_dd_pct: number;
		sharpe: number;
		calmar: number | null;
		trades: number;
		[k: string]: unknown;
	};
	equity_curve: [number, number][] | null;
	created_at: string;
}

// Predefined strategies + their param domains — keep in lockstep with backtest_runner.py.
// The UI renders forms from this; the runner re-validates server-side (never trust the client).
export const STRATEGIES = {
	honest_trend: {
		label: 'HonestTrend (US equity)',
		assets: ['NVDA', 'AMD', 'QQQ'],
		timeframes: ['1h', '1d'],
		params: { ema_fast: { min: 5, max: 400, default: 50 }, ema_slow: { min: 5, max: 400, default: 100 } }
	}
	// accumulator / donchian: wired once the crypto runner path lands (Phase 1b).
} as const;

function authHeaders(): HeadersInit {
	const t = getToken();
	if (!t) throw new Error('not authenticated');
	return { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json', Accept: 'application/json' };
}

/** Enqueue a backtest. user_id must equal the JWT sub (RLS enforces it). Returns the queued job. */
export async function submitBacktest(
	strategy: Strategy,
	params: Record<string, unknown>,
	userId: string,
	f: typeof fetch = fetch
): Promise<BacktestJob> {
	const r = await f(`${CONFIG.API_BASE}/backtest_jobs`, {
		method: 'POST',
		headers: { ...authHeaders(), Prefer: 'return=representation' },
		body: JSON.stringify({ user_id: userId, strategy, params, status: 'queued' })
	});
	if (!r.ok) throw new Error(`submit ${r.status}: ${await r.text().catch(() => '')}`.slice(0, 200));
	return ((await r.json()) as BacktestJob[])[0];
}

/** The current user's jobs, newest first (RLS scopes to them). */
export async function myJobs(f: typeof fetch = fetch): Promise<BacktestJob[]> {
	const r = await f(`${CONFIG.API_BASE}/backtest_jobs?select=*&order=created_at.desc&limit=50`, {
		headers: authHeaders()
	});
	if (!r.ok) throw new Error(`jobs ${r.status}`);
	return (await r.json()) as BacktestJob[];
}

/** Result for one job, or null if not finished yet. */
export async function jobResult(jobId: string, f: typeof fetch = fetch): Promise<BacktestResult | null> {
	const r = await f(`${CONFIG.API_BASE}/backtest_results?job_id=eq.${jobId}&select=*`, {
		headers: authHeaders()
	});
	if (!r.ok) throw new Error(`result ${r.status}`);
	return ((await r.json()) as BacktestResult[])[0] ?? null;
}
