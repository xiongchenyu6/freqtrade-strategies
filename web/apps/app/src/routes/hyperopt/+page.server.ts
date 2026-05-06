import type { PageServerLoad } from './$types';
import { vps } from '$lib/api';
import type { HyperoptEpoch } from '$lib/types';

export const load: PageServerLoad = async ({ fetch, cookies }) => {
	const jwt = cookies.get('qt_jwt');
	const auth = jwt ? `Bearer ${jwt}` : undefined;

	// Fetch up to 2000 epochs across all strategies; PostgREST sorts by loss asc.
	// Gracefully return empty array if table doesn't exist yet.
	const epochs: HyperoptEpoch[] = await vps
		.hyperoptEpochs(fetch, { limit: 2000, authHeader: auth })
		.catch(() => []);

	// Group epochs by strategy name
	const byStrategy: Record<string, HyperoptEpoch[]> = {};
	for (const e of epochs) {
		if (!byStrategy[e.strategy]) byStrategy[e.strategy] = [];
		byStrategy[e.strategy].push(e);
	}

	// Sort each strategy's epochs by epoch number for the loss curve
	for (const list of Object.values(byStrategy)) {
		list.sort((a, b) => a.epoch - b.epoch);
	}

	return { byStrategy };
};
