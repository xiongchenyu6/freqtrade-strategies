import type { PageServerLoad } from './$types';
import { fetchAssetData } from '$lib/marketData';

export const load: PageServerLoad = async ({ fetch }) => {
	const [btc, eth] = await Promise.all([
		fetchAssetData('BTC', fetch).catch(() => null),
		fetchAssetData('ETH', fetch).catch(() => null)
	]);
	return { btc, eth };
};
