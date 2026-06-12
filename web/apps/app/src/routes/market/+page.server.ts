import type { PageServerLoad } from './$types';
import { fetchAssetData } from '$lib/marketData';
import { vps } from '$lib/api';

export const load: PageServerLoad = async ({ fetch }) => {
	const [btc, eth, stress] = await Promise.all([
		fetchAssetData('BTC', fetch).catch(() => null),
		fetchAssetData('ETH', fetch).catch(() => null),
		vps
			.marketStress(fetch, { limit: 1 })
			.then((rows) => rows[0] ?? null)
			.catch(() => null)
	]);
	return { btc, eth, stress };
};
