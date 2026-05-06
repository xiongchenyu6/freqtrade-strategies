import { error } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';
import { CONFIG } from '$lib/config';
import type { BacktestRun, WfResult, BacktestTrade } from '$lib/types';

export const load: PageServerLoad = async ({ fetch, params }) => {
	const { name } = params;
	const base = CONFIG.API_BASE;
	const headers = { Accept: 'application/json' };

	const [runsRes, wfRes] = await Promise.all([
		fetch(
			`${base}/backtest_runs?strategy=eq.${name}&order=total_profit_pct.desc.nullslast&limit=5`,
			{ headers }
		),
		fetch(`${base}/wf_results?strategy=eq.${name}&order=run_date.desc&limit=50`, { headers })
	]);

	const topRuns: BacktestRun[] = runsRes.ok ? await runsRes.json() : [];
	const wfAll: WfResult[] = wfRes.ok ? await wfRes.json() : [];

	if (topRuns.length === 0) throw error(404, `No backtest runs found for strategy: ${name}`);

	const bestRun = topRuns[0];

	// Latest WF date grouping
	const latestWfDate = wfAll.reduce<string | null>(
		(m, r) => (m && m > r.run_date ? m : r.run_date),
		null
	);
	const wfLatest = wfAll.filter((r) => r.run_date === latestWfDate);

	// Fetch trades for best run equity curve
	let trades: BacktestTrade[] = [];
	if (bestRun?.id != null) {
		const tradesRes = await fetch(
			`${base}/backtest_trades?run_id=eq.${bestRun.id}&order=close_date.asc&limit=10000`,
			{ headers }
		);
		if (tradesRes.ok) trades = await tradesRes.json();
	}

	return {
		strategyName: name,
		topRuns,
		wfLatest,
		trades,
		bestRun
	};
};
