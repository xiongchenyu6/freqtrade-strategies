import type { PageServerLoad } from './$types';
import { vps } from '$lib/api';

export const load: PageServerLoad = async ({ fetch, cookies }) => {
	const jwt = cookies.get('qt_jwt');
	const auth = jwt ? `Bearer ${jwt}` : undefined;
	const runs = await vps
		.backtestRuns(fetch, { limit: 500, authHeader: auth })
		.catch(() => []);
	const strategies = [...new Set(runs.map((r) => r.strategy))].sort();
	return { runs, strategies };
};
