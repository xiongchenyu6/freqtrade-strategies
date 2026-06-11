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

// Display metadata per strategy (plain-language layer — keys/params are the runner contract
// and stay unchanged): `name` is the 白话名, `tech` the technical label, `explain` a one-
// paragraph honest description, `paramHints` one-liners rendered under each param input.
export const STRATEGIES = {
	honest_trend: {
		label: 'HonestTrend (US equity)',
		name: ['美股趋势跟随', 'US trend following'] as const,
		tech: 'HonestTrend',
		explain: [
			'均线金叉买入、死叉卖出,顺势而为。涨势里拿得住,震荡市会反复止损。适合验证"长期趋势"想法。',
			'Buy the golden cross, sell the death cross. Rides trends; chops sideways. For testing long-trend ideas.'
		] as const,
		paramHints: {
			ema_fast: ['短期均线长度 — 越小越灵敏、信号越多', 'short EMA length — smaller = more sensitive'],
			ema_slow: ['长期均线长度 — 定义"趋势"的尺度', 'long EMA — defines the trend scale']
		},
		blurb: ['EMA 金叉/死叉趋势跟随，支持任意美股代码（日线 10 年历史），NVDA/AMD/QQQ 另有小时线', 'EMA cross trend-following — any US ticker (10y daily history); hourly for NVDA/AMD/QQQ'] as const,
		// `assets` are SUGGESTIONS only — anyUsSymbol opens the field to any US ticker.
		// The runner validates against its ~9.5k US-symbol list server-side; hourly bars
		// exist only for the suggested trio, everything else is daily.
		assets: ['NVDA', 'AMD', 'QQQ'],
		anyUsSymbol: true,
		note: ['非目录股票仅支持日线（10 年历史）', 'Non-catalog tickers: daily only (10y history)'] as const,
		timeframes: ['1h', '1d'],
		params: { ema_fast: { min: 5, max: 400, default: 50 }, ema_slow: { min: 5, max: 400, default: 100 } }
	},
	// Donchian breakout — crypto trend, real Binance 1h bars. Honest equity-curve maxDD.
	donchian: {
		label: 'Donchian breakout (crypto trend)',
		name: ['突破追涨', 'Breakout'] as const,
		tech: 'Donchian breakout',
		explain: [
			'价格创出过去 N 根 K 线的新高就买入,跌破过去 M 根的新低就卖出。趋势行情吃肉,震荡行情挨打 —— 用回测看它在这个币上到底行不行。',
			'Buy fresh N-bar highs, exit on M-bar lows. Feasts in trends, bleeds in chop — backtest tells you which.'
		] as const,
		paramHints: {
			entry_lb: ['突破窗口:过去多少根 K 线的最高点算"新高"(168 根 1h ≈ 7 天)', 'breakout window in bars (168×1h ≈ 7 days)'],
			exit_lb: ['离场窗口:跌破多少根 K 线的最低点就卖', 'exit window in bars'],
			risk_frac: ['每次入场动用资金的比例', 'fraction of equity per entry']
		},
		blurb: ['唐奇安通道突破做多，真实币安 1h K 线，诚实净值回撤', 'Donchian channel breakout long, real Binance 1h bars, honest drawdown'] as const,
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
		name: ['恐慌加仓定投', 'Fear-boosted DCA'] as const,
		tech: 'Smart DCA',
		explain: [
			'固定周期买入,市场恐慌(恐惧贪婪指数低)时自动加倍 —— 只买不卖,赌的是长期向上 + 恐慌时的便宜筹码。',
			'Scheduled buys, doubled in fear — never sells. Bets on long-term upside + cheap panic chips.'
		] as const,
		paramHints: {
			base_buy_usd: ['每次定投金额', 'USD per buy'],
			interval_bars: ['每隔多少天买一次', 'days between buys'],
			mode: ['smart=恐慌加倍 / naive=固定金额', 'smart doubles in fear / naive fixed']
		},
		blurb: ['恐惧贪婪指数驱动的定投，越跌越买，只买不卖', 'Fear & Greed-driven DCA — buys more on dips, never sells'] as const,
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
