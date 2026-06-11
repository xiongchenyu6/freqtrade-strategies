import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

// Visitors guess this URL (seen in 404 logs) — permanent-redirect to the real
// browse page. Redirect-only route: load throws before any render, so no
// +page.svelte is needed.
export const load: PageServerLoad = () => {
	throw redirect(301, '/commodities');
};
