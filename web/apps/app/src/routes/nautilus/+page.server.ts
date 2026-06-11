import type { PageServerLoad } from './$types';
import { vps } from '$lib/api';

export const load: PageServerLoad = async ({ fetch, cookies }) => {
	const jwt = cookies.get('qt_jwt');
	const auth = jwt ? `Bearer ${jwt}` : undefined;
	const [tradesRaw, snapsRaw] = await Promise.all([
		vps.nautilusTrades(fetch, { limit: 200, authHeader: auth }).catch(() => []),
		vps.accountSnapshots(fetch).catch(() => [])
	]);
	// Malformed-200 coercion (same class as the home/dca hardening).
	const trades = Array.isArray(tradesRaw) ? tradesRaw : [];
	const snapshots = Array.isArray(snapsRaw) ? snapsRaw : [];
	return { trades, snapshots };
};
