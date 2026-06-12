import type { PageServerLoad } from './$types';
import { vps } from '$lib/api';

export const load: PageServerLoad = async ({ fetch }) => {
	const news = await vps.newsItems(fetch, { limit: 60 }).catch(() => []);
	return { news: Array.isArray(news) ? news : [] };
};
