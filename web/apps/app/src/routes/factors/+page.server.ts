import type { PageServerLoad } from './$types';
import { vps } from '$lib/api';

export const load: PageServerLoad = async ({ fetch, cookies }) => {
	const jwt = cookies.get('qt_jwt');
	const auth = jwt ? `Bearer ${jwt}` : undefined;
	const runs = await vps.backtestRuns(fetch, { limit: 500, authHeader: auth }).catch(() => []);
	return { runs };
};
