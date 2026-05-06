import type { PageServerLoad } from './$types';
import { vps } from '$lib/api';
import { STRATEGIES, pickStrategy } from '$lib/strategies';
import type { BacktestRun } from '$lib/types';

export interface StrategyAggregate {
	name: string;
	tagline: string;
	mode: string;
	timeframe: string;
	assets: string[];
	status: string;
	factors: string[];
	runs: number;
	best_profit_pct: number | null;
	best_calmar: number | null;
	best_sharpe: number | null;
	best_sortino: number | null;
	worst_dd_pct: number | null;
	best_win_rate: number | null;
	last_imported: string | null;
}

function best<T>(xs: T[], score: (x: T) => number | null | undefined): number | null {
	let m: number | null = null;
	for (const x of xs) {
		const v = score(x);
		if (v == null || !Number.isFinite(v)) continue;
		if (m == null || v > m) m = v;
	}
	return m;
}

function min<T>(xs: T[], score: (x: T) => number | null | undefined): number | null {
	let m: number | null = null;
	for (const x of xs) {
		const v = score(x);
		if (v == null || !Number.isFinite(v)) continue;
		if (m == null || v < m) m = v;
	}
	return m;
}

export const load: PageServerLoad = async ({ fetch, locals, cookies }) => {
	const jwt = cookies.get('qt_jwt');
	const auth = jwt ? `Bearer ${jwt}` : undefined;
	const runs = await vps
		.backtestRuns(fetch, { limit: 1000, authHeader: auth })
		.catch(() => [] as BacktestRun[]);
	const byName = new Map<string, BacktestRun[]>();
	for (const r of runs) {
		if (!r.strategy) continue;
		if (!byName.has(r.strategy)) byName.set(r.strategy, []);
		byName.get(r.strategy)!.push(r);
	}
	const aggregates: StrategyAggregate[] = STRATEGIES.map((meta) => {
		const flat = pickStrategy(meta, locals.lang);
		const group = byName.get(meta.name) ?? [];
		const factors = group[0]?.factors ?? [];
		const lastImported = group.reduce<string | null>(
			(acc, r) => (acc && acc > r.imported_at ? acc : r.imported_at),
			null
		);
		return {
			name: meta.name,
			tagline: flat.tagline,
			mode: flat.mode,
			timeframe: flat.timeframe,
			assets: flat.assets,
			status: flat.status,
			factors,
			runs: group.length,
			best_profit_pct: best(group, (r) => r.total_profit_pct),
			best_calmar: best(group, (r) => r.calmar),
			best_sharpe: best(group, (r) => r.sharpe),
			best_sortino: best(group, (r) => r.sortino),
			worst_dd_pct: min(group, (r) => r.max_drawdown_pct),
			best_win_rate: best(group, (r) => r.win_rate_pct),
			last_imported: lastImported
		};
	});
	// Also surface any DB strategies not in the static catalog (so we see them).
	for (const [name, group] of byName) {
		if (aggregates.find((a) => a.name === name)) continue;
		aggregates.push({
			name,
			tagline: locals.lang === 'en' ? '(not in static catalog)' : '(未在静态目录中)',
			mode: '?',
			timeframe: group[0]?.timeframe ?? '?',
			assets: group[0]?.pairs ?? [],
			status: 'research',
			factors: group[0]?.factors ?? [],
			runs: group.length,
			best_profit_pct: best(group, (r) => r.total_profit_pct),
			best_calmar: best(group, (r) => r.calmar),
			best_sharpe: best(group, (r) => r.sharpe),
			best_sortino: best(group, (r) => r.sortino),
			worst_dd_pct: min(group, (r) => r.max_drawdown_pct),
			best_win_rate: best(group, (r) => r.win_rate_pct),
			last_imported: group.reduce<string | null>(
				(acc, r) => (acc && acc > r.imported_at ? acc : r.imported_at),
				null
			)
		});
	}
	return { strategies: aggregates };
};
