// Personal DCA execution ledger — thin wrapper around api.dca_executions
// (PostgREST, migration 021). Mirrors userPrefs.ts/alerts.ts. RLS scopes rows
// to the JWT user. The ledger is self-reported by design: prices are
// snapshotted client-side from Binance's public ticker at log time.
import { CONFIG } from './config';
import { getToken } from './auth';
import type { CoinSymbol } from './dcaSim';

export interface DcaBreakdownEntry {
	/** USDT spent on this coin in this execution. */
	amount: number;
	/** Spot price snapshot at log time. */
	price: number;
}

export type DcaBreakdown = Partial<Record<CoinSymbol, DcaBreakdownEntry>>;

export interface DcaExecution {
	id: number;
	user_id: string;
	ts: string;
	total_usdt: number;
	breakdown: DcaBreakdown;
	note: string | null;
}

export interface LogExecutionInput {
	user_id: string;
	total_usdt: number;
	breakdown: DcaBreakdown;
	note?: string;
}

function authHeaders(): HeadersInit {
	const t = getToken();
	if (!t) throw new Error('not authenticated');
	return {
		Authorization: `Bearer ${t}`,
		'Content-Type': 'application/json',
		Accept: 'application/json'
	};
}

/** The current user's executions, newest first (RLS scopes to them). */
export async function myExecutions(f: typeof fetch = fetch): Promise<DcaExecution[]> {
	const r = await f(`${CONFIG.API_BASE}/dca_executions?select=*&order=ts.desc`, {
		headers: authHeaders()
	});
	if (!r.ok) throw new Error(`ledger ${r.status}`);
	return (await r.json()) as DcaExecution[];
}

/** Log one real buy. `id` is GENERATED ALWAYS and `ts` defaults to now() — send neither. */
export async function logExecution(
	input: LogExecutionInput,
	f: typeof fetch = fetch
): Promise<DcaExecution> {
	const r = await f(`${CONFIG.API_BASE}/dca_executions`, {
		method: 'POST',
		headers: { ...authHeaders(), Prefer: 'return=representation' },
		body: JSON.stringify(input)
	});
	if (!r.ok) throw new Error(`log ${r.status}: ${await r.text().catch(() => '')}`.slice(0, 200));
	return ((await r.json()) as DcaExecution[])[0];
}

export async function deleteExecution(id: number, f: typeof fetch = fetch): Promise<void> {
	const r = await f(`${CONFIG.API_BASE}/dca_executions?id=eq.${id}`, {
		method: 'DELETE',
		headers: authHeaders()
	});
	if (!r.ok) throw new Error(`delete ${r.status}`);
}

/**
 * Current spot prices from Binance's public ticker (no auth). Tries the batch
 * endpoint first; if that fails (some proxies choke on the encoded JSON
 * array), falls back to one request per symbol. Missing symbols are simply
 * absent from the result — callers handle that explicitly.
 */
export async function fetchSpotPrices(
	symbols: CoinSymbol[],
	f: typeof fetch = fetch
): Promise<Partial<Record<CoinSymbol, number>>> {
	const out: Partial<Record<CoinSymbol, number>> = {};
	if (symbols.length === 0) return out;
	const pairs = symbols.map((s) => `${s}USDT`);
	const batch = await f(
		`https://api.binance.com/api/v3/ticker/price?symbols=${encodeURIComponent(JSON.stringify(pairs))}`
	)
		.then((r) => (r.ok ? (r.json() as Promise<{ symbol: string; price: string }[]>) : null))
		.catch(() => null);
	if (batch) {
		for (const row of batch) {
			const sym = row.symbol.replace(/USDT$/, '') as CoinSymbol;
			const px = parseFloat(row.price);
			if (symbols.includes(sym) && Number.isFinite(px)) out[sym] = px;
		}
		return out;
	}
	await Promise.all(
		symbols.map(async (s) => {
			try {
				const r = await f(`https://api.binance.com/api/v3/ticker/price?symbol=${s}USDT`);
				if (!r.ok) return;
				const d = (await r.json()) as { price: string };
				const px = parseFloat(d.price);
				if (Number.isFinite(px)) out[s] = px;
			} catch {
				// ignore — missing prices are handled by the caller
			}
		})
	);
	return out;
}
