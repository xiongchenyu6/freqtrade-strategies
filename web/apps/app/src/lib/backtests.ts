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
	equity_curve: number[] | null; // downsampled equity values (~80 pts) for a sparkline
	created_at: string;
}

// Predefined strategies + their param domains — keep in lockstep with backtest_runner.py.
// The UI renders forms from this; the runner re-validates server-side (never trust the client).
const CRYPTO_ASSETS = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'DOGE', 'LINK'] as const;

export const STRATEGIES = {
	honest_trend: {
		label: 'HonestTrend (US equity)',
		assets: ['NVDA', 'AMD', 'QQQ'],
		timeframes: ['1h', '1d'],
		params: { ema_fast: { min: 5, max: 400, default: 50 }, ema_slow: { min: 5, max: 400, default: 100 } }
	},
	// Donchian breakout — crypto trend, real Binance 1h bars. Honest equity-curve maxDD.
	donchian: {
		label: 'Donchian breakout (crypto trend)',
		assets: CRYPTO_ASSETS,
		timeframes: ['1h'],
		params: {
			entry_lb: { min: 12, max: 1000, default: 168 }, // breakout lookback (1h bars)
			exit_lb: { min: 6, max: 1000, default: 72 }, // trailing-low exit lookback; must be <= entry_lb
			risk_frac: { min: 0.01, max: 1, default: 0.2, step: 0.01 } // equity fraction deployed per entry
		}
	},
	// Fear-driven smart DCA — crypto accumulation, real Binance 1d bars. Never sells, so
	// return_pct is ROI on invested capital; max_dd/sharpe/calmar are null (round-trip metrics N/A).
	accumulator: {
		label: 'Smart DCA accumulator (crypto)',
		assets: CRYPTO_ASSETS,
		timeframes: ['1d'],
		params: {
			base_buy_usd: { min: 10, max: 100000, default: 500 }, // USD per scheduled buy
			interval_bars: { min: 1, max: 90, default: 7 }, // days between buys (1d bars)
			mode: { choices: ['smart', 'naive'], default: 'smart' } // smart = fear+dip boosted
		}
	}
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
