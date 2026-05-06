import type { PageServerLoad } from './$types';
import { vps } from '$lib/api';

export const load: PageServerLoad = async ({ fetch, cookies }) => {
	const jwt = cookies.get('qt_jwt');
	const auth = jwt ? `Bearer ${jwt}` : undefined;
	// Initial snapshot. Realtime streams deltas on top.
	const [runs, trades, events, closedTrades] = await Promise.all([
		vps.backtestRuns(fetch, { limit: 10, authHeader: auth }).catch(() => []),
		vps.liveTrades(fetch, { limit: 10, authHeader: auth }).catch(() => []),
		vps.eventDcaTriggers(fetch, { limit: 10, authHeader: auth }).catch(() => []),
		vps.liveTrades(fetch, { limit: 200, authHeader: auth }).catch(() => []),
	]);
	return { runs, trades, events, closedTrades };
};
