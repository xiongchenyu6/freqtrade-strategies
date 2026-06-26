import type { PageServerLoad } from './$types';
import { vps } from '$lib/api';

export const load: PageServerLoad = async ({ fetch }) => {
	// High limit on purpose: the globe needs breadth across all source cities,
	// not just the most recent items (a busy feed would crowd out whole regions).
	const news = await vps.newsItems(fetch, { limit: 500 }).catch(() => []);
	return { news: Array.isArray(news) ? news : [] };
};
