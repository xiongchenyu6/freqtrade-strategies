import type { PageServerLoad } from './$types';
import { vps } from '$lib/api';

export const load: PageServerLoad = async ({ fetch, cookies }) => {
	const jwt = cookies.get('qt_jwt');
	const auth = jwt ? `Bearer ${jwt}` : undefined;
	const [events, runs] = await Promise.all([
		vps.eventDcaTriggers(fetch, { limit: 200, authHeader: auth }).catch(() => []),
		vps.backtestRuns(fetch, { limit: 100, authHeader: auth }).catch(() => [])
	]);
	return { events, runs };
};
