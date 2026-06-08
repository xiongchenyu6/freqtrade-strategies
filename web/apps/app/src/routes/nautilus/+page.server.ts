import type { PageServerLoad } from './$types';
import { vps } from '$lib/api';

export const load: PageServerLoad = async ({ fetch, cookies }) => {
	const jwt = cookies.get('qt_jwt');
	const auth = jwt ? `Bearer ${jwt}` : undefined;
	const trades = await vps.nautilusTrades(fetch, { limit: 200, authHeader: auth }).catch(() => []);
	return { trades };
};
