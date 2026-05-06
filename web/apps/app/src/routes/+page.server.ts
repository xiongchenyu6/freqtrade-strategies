import type { PageServerLoad } from './$types';
import { vps, supabase } from '$lib/api';
import type { BacktestRun, OhlcRow, EventDcaTrigger, PublicStats } from '$lib/types';

// Home is the funnel's top surface: anon gets public-preview aggregates,
// authed gets the same PLUS richer Recent-25 table and full OHLC/events.

export const load: PageServerLoad = async ({ fetch, cookies }) => {
	const jwt = cookies.get('qt_jwt');
	const auth = jwt ? `Bearer ${jwt}` : undefined;
	const isAuthed = Boolean(jwt);

	const ohlcFor = (pair: string) =>
		isAuthed
			? vps
					.ohlcDaily(fetch, pair, { from: '2017-01-01', limit: 4000, authHeader: auth })
					.catch(() => [] as OhlcRow[])
			: pair === 'BTC/USDT' || pair === 'ETH/USDT' || pair === 'BNB/USDT' || pair === 'SOL/USDT'
				? vps.publicOhlcDaily(fetch, pair, { from: '2017-01-01', limit: 4000 }).catch(() => [] as OhlcRow[])
				: Promise.resolve([] as OhlcRow[]);

	const [statsRow, runs, dca, kol, btcOhlc, ethOhlc, bnbOhlc, solOhlc, triggers] =
		await Promise.all([
			vps.publicStats(fetch).catch(() => [] as PublicStats[]),
			isAuthed
				? vps.backtestRuns(fetch, { limit: 500, authHeader: auth }).catch(() => [] as BacktestRun[])
				: Promise.resolve([] as BacktestRun[]),
			supabase.dcaLog(fetch, { limit: 50 }).catch(() => []),
			supabase.kolEvents(fetch, { limit: 5 }).catch(() => []),
			ohlcFor('BTC/USDT'),
			ohlcFor('ETH/USDT'),
			ohlcFor('BNB/USDT'),
			ohlcFor('SOL/USDT'),
			isAuthed
				? vps
						.eventDcaTriggers(fetch, { limit: 500, authHeader: auth })
						.catch(() => [] as EventDcaTrigger[])
				: vps.publicEventTriggers(fetch, { limit: 500 }).catch(() => [] as EventDcaTrigger[])
		]);

	const ohlcByCoin = { BTC: btcOhlc, ETH: ethOhlc, BNB: bnbOhlc, SOL: solOhlc };
	const stats = statsRow[0] ?? null;

	const distinctStrategies = new Set(runs.map((r) => r.strategy).filter(Boolean));
	const distinctTimeframes = new Set(runs.map((r) => r.timeframe).filter((t): t is string => !!t));

	return {
		isAuthed,
		health: {
			api: (stats?.total_runs ?? 0) > 0,
			supabase: kol.length > 0 || dca.length > 0
		},
		summary: {
			total_runs: stats?.total_runs ?? 0,
			total_trades: stats?.total_trades ?? 0,
			distinct_strategies: stats?.distinct_strategies ?? 0,
			best_profit_pct: stats?.best_profit_pct ?? null,
			best_calmar: stats?.best_calmar ?? null,
			best_sharpe: stats?.best_sharpe ?? null,
			best_sortino: stats?.best_sortino ?? null,
			best_win_rate: stats?.best_win_rate ?? null,
			min_max_dd: stats?.min_max_dd ?? null,
			dca_count: dca.length
		},
		recent_runs: runs.slice(0, 50),
		strategy_options: [...distinctStrategies].sort(),
		timeframe_options: [...distinctTimeframes].sort(),
		recent_kol: kol,
		recent_dca: dca.slice(0, 5),
		ohlcByCoin,
		triggers
	};
};
