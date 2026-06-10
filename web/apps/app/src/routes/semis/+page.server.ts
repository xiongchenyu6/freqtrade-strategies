import type { PageServerLoad } from './$types';
import { vps } from '$lib/api';
import type { SemiTicker, SemiGroup } from '$lib/types';

export const load: PageServerLoad = async ({ fetch }) => {
	const [universe, groups] = await Promise.all([
		vps.semiUniverse(fetch).catch(() => [] as SemiTicker[]),
		vps.semiGroups(fetch).catch(() => [] as SemiGroup[])
	]);
	return { universe, groups };
};
