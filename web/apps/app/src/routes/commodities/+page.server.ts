import type { PageServerLoad } from './$types';
import { CONFIG } from '$lib/config';

/** One quant.market_snapshots row whose payload is a commodity daily-close
 * series (collector stores ~400 points per continuous-futures symbol). */
export type CommodityRow = {
	asset: string;
	ts: string;
	payload: { kind: 'commodity'; zh: string; en: string; closes: [number, number][] };
};

// Canonical display order — mirrors COMMODITY_ASSETS in $lib/backtests.
const ORDER = ['GC', 'SI', 'CL', 'BZ', 'HG', 'NG', 'PL', 'PA', 'KT', 'ZW', 'ZS', 'ZC'];
const orderOf = (sym: string) => {
	const i = ORDER.indexOf(sym);
	return i < 0 ? ORDER.length : i;
};

export const load: PageServerLoad = async ({ fetch }) => {
	// The whole table is ~14 rows (BTC/ETH market payloads + 12 commodities), so
	// fetch once and filter on kind here — simpler than a PostgREST JSON filter.
	const url = new URL('/market_snapshots', CONFIG.API_BASE);
	url.searchParams.set('select', 'asset,ts,payload');
	let rows: unknown = [];
	try {
		const r = await fetch(url.toString(), { headers: { Accept: 'application/json' } });
		if (r.ok) rows = await r.json();
		// CF Workers warn if a Response body is dropped unread — cancel explicitly.
		else await r.body?.cancel().catch(() => {});
	} catch {
		// API unreachable — the page renders its honest empty state.
	}
	// Coerce to an array: a malformed 200 must not 500 the page.
	const arr = Array.isArray(rows) ? (rows as CommodityRow[]) : [];
	const commodities = arr
		.filter((r) => r?.payload?.kind === 'commodity' && Array.isArray(r.payload.closes))
		.sort((a, b) => orderOf(a.asset) - orderOf(b.asset));
	return { commodities };
};
