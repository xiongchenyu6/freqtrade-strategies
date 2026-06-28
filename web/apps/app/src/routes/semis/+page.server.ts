import type { PageServerLoad } from './$types';
import { vps } from '$lib/api';
import type { SemiTicker, SemiGroup, SemiSegment } from '$lib/types';

export const load: PageServerLoad = async ({ fetch }) => {
	const [universe, groups, segments] = await Promise.all([
		vps.semiUniverse(fetch).catch(() => [] as SemiTicker[]),
		vps.semiGroups(fetch).catch(() => [] as SemiGroup[]),
		vps.semiSegments(fetch).catch(() => [] as SemiSegment[])
	]);
	return { universe, groups, segments };
};
