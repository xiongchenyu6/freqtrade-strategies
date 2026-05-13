import { error } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';
import { vps } from '$lib/api';
import { loadKellyStatus } from '$lib/server/kelly';
import { getStrategyMeta, pickStrategy } from '$lib/strategies';
import type { BacktestRun, WfResult } from '$lib/types';

export const load: PageServerLoad = async ({ fetch, params, locals, cookies }) => {
	const { name } = params;
	const jwt = cookies.get('qt_jwt');
	const auth = jwt ? `Bearer ${jwt}` : undefined;
	const [runs, wf, kellyStatus] = await Promise.all([
		vps
			.backtestRuns(fetch, { strategy: name, limit: 200, authHeader: auth })
			.catch(() => [] as BacktestRun[]),
		vps
			.walkForward(fetch, { strategy: name, limit: 200, authHeader: auth })
			.catch(() => [] as WfResult[]),
		loadKellyStatus(fetch)
	]);
	const kelly = kellyStatus?.strategies.find((e) => e.name === name) ?? null;
	const meta = getStrategyMeta(name);
	if (!meta && runs.length === 0) throw error(404, `Unknown strategy: ${name}`);

	const sortedRuns = [...runs].sort(
		(a, b) => (b.total_profit_pct ?? -Infinity) - (a.total_profit_pct ?? -Infinity)
	);
	const latestWfDate = wf.reduce<string | null>(
		(m, r) => (m && m > r.run_date ? m : r.run_date),
		null
	);
	const wfLatest = wf.filter((r) => r.run_date === latestWfDate);

	return {
		strategyName: name,
		meta: meta ? pickStrategy(meta, locals.lang) : null,
		currentFactors: runs[0]?.factors ?? null,
		runs: sortedRuns,
		wfLatest,
		wfDate: latestWfDate,
		kelly
	};
};
