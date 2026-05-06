// Portfolio sync endpoints — proxy Binance calls so the user's secret never
// leaves the Worker unencrypted. All three handlers require a valid JWT
// (Authorization: Bearer …) forwarded to PostgREST; RLS on
// quant.user_preferences ensures each user only touches their own row.
//
// The stored columns binance_api_key / binance_api_secret hold base64(iv || ct)
// AES-GCM ciphertext, wrapped with the BINANCE_KEK Worker secret. Without the
// KEK, the data is inert even if the DB is dumped.
import type { RequestHandler } from './$types';
import { CONFIG } from '$lib/config';

interface BinancePrefs {
	binance_api_key: string | null;
	binance_api_secret: string | null;
	binance_connected_at: string | null;
}

interface BinanceBalance {
	asset: string;
	free: string;
	locked: string;
}

interface Holding {
	asset: string;
	total: number;
	usd_value: number;
	usd_price: number | null;
}

// ---------- AES-GCM wrap/unwrap ----------

function b64decode(s: string): Uint8Array {
	return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}
function b64encode(u: Uint8Array): string {
	let s = '';
	for (const b of u) s += String.fromCharCode(b);
	return btoa(s);
}

async function importKek(kekB64: string): Promise<CryptoKey> {
	return crypto.subtle.importKey(
		'raw',
		b64decode(kekB64),
		{ name: 'AES-GCM' },
		false,
		['encrypt', 'decrypt']
	);
}

async function encryptSecret(plaintext: string, kekB64: string): Promise<string> {
	const key = await importKek(kekB64);
	const iv = crypto.getRandomValues(new Uint8Array(12));
	const ct = await crypto.subtle.encrypt(
		{ name: 'AES-GCM', iv },
		key,
		new TextEncoder().encode(plaintext)
	);
	const combined = new Uint8Array(iv.length + ct.byteLength);
	combined.set(iv, 0);
	combined.set(new Uint8Array(ct), iv.length);
	return b64encode(combined);
}

async function decryptSecret(ciphertextB64: string, kekB64: string): Promise<string> {
	const combined = b64decode(ciphertextB64);
	const iv = combined.slice(0, 12);
	const ct = combined.slice(12);
	const key = await importKek(kekB64);
	const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ct);
	return new TextDecoder().decode(pt);
}

function requireKek(platform: App.Platform | undefined): string | Response {
	const k = platform?.env?.BINANCE_KEK;
	if (!k) {
		return new Response(
			JSON.stringify({ error: 'BINANCE_KEK not configured on this deployment' }),
			{ status: 500, headers: { 'content-type': 'application/json' } }
		);
	}
	return k;
}

// ---------- helpers ----------

async function hmacHex(secret: string, msg: string): Promise<string> {
	const enc = new TextEncoder();
	const key = await crypto.subtle.importKey(
		'raw',
		enc.encode(secret),
		{ name: 'HMAC', hash: 'SHA-256' },
		false,
		['sign']
	);
	const sig = await crypto.subtle.sign('HMAC', key, enc.encode(msg));
	return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function binanceSigned(key: string, secret: string, path: string): Promise<unknown> {
	const query = `timestamp=${Date.now()}&recvWindow=10000`;
	const sig = await hmacHex(secret, query);
	const r = await fetch(`https://api.binance.com${path}?${query}&signature=${sig}`, {
		headers: { 'X-MBX-APIKEY': key }
	});
	if (!r.ok) {
		const body = await r.text().catch(() => '');
		throw new Error(`binance ${r.status}: ${body.slice(0, 200)}`);
	}
	return r.json();
}

async function binanceAllPrices(): Promise<Map<string, number>> {
	const r = await fetch('https://api.binance.com/api/v3/ticker/price');
	if (!r.ok) return new Map();
	const arr = (await r.json()) as { symbol: string; price: string }[];
	const m = new Map<string, number>();
	for (const p of arr) m.set(p.symbol, Number(p.price));
	return m;
}

function priceInUsd(asset: string, prices: Map<string, number>): number | null {
	if (asset === 'USDT' || asset === 'USDC' || asset === 'BUSD' || asset === 'FDUSD') return 1;
	const direct = prices.get(`${asset}USDT`);
	if (direct) return direct;
	const viaBtc = prices.get(`${asset}BTC`);
	const btcUsd = prices.get('BTCUSDT');
	if (viaBtc && btcUsd) return viaBtc * btcUsd;
	return null;
}

async function loadPrefs(auth: string): Promise<BinancePrefs | null> {
	const r = await fetch(
		`${CONFIG.API_BASE}/user_preferences?select=binance_api_key,binance_api_secret,binance_connected_at`,
		{ headers: { Authorization: auth, Accept: 'application/json' } }
	);
	if (!r.ok) return null;
	const rows = (await r.json()) as BinancePrefs[];
	return rows[0] ?? null;
}

function requireAuth(request: Request): string | Response {
	const auth = request.headers.get('authorization');
	if (!auth?.startsWith('Bearer ')) {
		return new Response(JSON.stringify({ error: 'auth required' }), {
			status: 401,
			headers: { 'content-type': 'application/json' }
		});
	}
	return auth;
}

function jwtSubject(authHeader: string): string | null {
	try {
		const tok = authHeader.replace(/^Bearer\s+/, '');
		const [, p] = tok.split('.');
		const payload = JSON.parse(atob(p.replace(/-/g, '+').replace(/_/g, '/')));
		return payload.sub ?? null;
	} catch {
		return null;
	}
}

// ---------- handlers ----------

export const GET: RequestHandler = async ({ request, platform }) => {
	const auth = requireAuth(request);
	if (typeof auth !== 'string') return auth;

	const prefs = await loadPrefs(auth);
	if (!prefs?.binance_api_key || !prefs.binance_api_secret) {
		return new Response(JSON.stringify({ connected: false }), {
			headers: { 'content-type': 'application/json' }
		});
	}

	const kek = requireKek(platform);
	if (typeof kek !== 'string') return kek;

	let apiKey: string;
	let apiSecret: string;
	try {
		apiKey = await decryptSecret(prefs.binance_api_key, kek);
		apiSecret = await decryptSecret(prefs.binance_api_secret, kek);
	} catch (e) {
		return new Response(
			JSON.stringify({ error: `decrypt failed (KEK rotated?): ${(e as Error).message}` }),
			{ status: 500, headers: { 'content-type': 'application/json' } }
		);
	}

	try {
		const [account, prices] = await Promise.all([
			binanceSigned(apiKey, apiSecret, '/api/v3/account') as Promise<{
				balances: BinanceBalance[];
			}>,
			binanceAllPrices()
		]);

		const holdings: Holding[] = [];
		let totalUsd = 0;
		for (const b of account.balances) {
			const total = Number(b.free) + Number(b.locked);
			if (total <= 0) continue;
			const px = priceInUsd(b.asset, prices);
			const usd = px ? total * px : 0;
			if (usd < 0.5 && b.asset !== 'USDT' && b.asset !== 'USDC') continue; // skip dust
			holdings.push({ asset: b.asset, total, usd_price: px, usd_value: usd });
			totalUsd += usd;
		}
		holdings.sort((a, b) => b.usd_value - a.usd_value);

		return new Response(
			JSON.stringify({
				connected: true,
				connected_at: prefs.binance_connected_at,
				total_usd: totalUsd,
				holdings
			}),
			{ headers: { 'content-type': 'application/json' } }
		);
	} catch (e) {
		return new Response(JSON.stringify({ error: (e as Error).message }), {
			status: 502,
			headers: { 'content-type': 'application/json' }
		});
	}
};

export const POST: RequestHandler = async ({ request, platform }) => {
	const auth = requireAuth(request);
	if (typeof auth !== 'string') return auth;
	const sub = jwtSubject(auth);
	if (!sub) return new Response('bad token', { status: 401 });

	const kek = requireKek(platform);
	if (typeof kek !== 'string') return kek;

	const body = (await request.json().catch(() => null)) as {
		apiKey?: string;
		apiSecret?: string;
	} | null;
	if (!body?.apiKey || !body?.apiSecret) {
		return new Response(JSON.stringify({ error: 'apiKey and apiSecret required' }), {
			status: 400,
			headers: { 'content-type': 'application/json' }
		});
	}

	// Smoke-test the plaintext keys before we persist. Better to fail here
	// than save broken creds and hit 401s every refresh.
	try {
		await binanceSigned(body.apiKey, body.apiSecret, '/api/v3/account');
	} catch (e) {
		return new Response(JSON.stringify({ error: `binance rejected: ${(e as Error).message}` }), {
			status: 400,
			headers: { 'content-type': 'application/json' }
		});
	}

	// Wrap before persisting — DB at rest never sees plaintext.
	const encKey = await encryptSecret(body.apiKey, kek);
	const encSecret = await encryptSecret(body.apiSecret, kek);

	// Upsert via PostgREST using the user's own JWT (RLS enforced).
	const upsert = await fetch(`${CONFIG.API_BASE}/user_preferences`, {
		method: 'POST',
		headers: {
			Authorization: auth,
			'Content-Type': 'application/json',
			Prefer: 'resolution=merge-duplicates,return=representation'
		},
		body: JSON.stringify({
			user_id: sub,
			binance_api_key: encKey,
			binance_api_secret: encSecret,
			binance_connected_at: new Date().toISOString()
		})
	});
	if (!upsert.ok) {
		const t = await upsert.text().catch(() => '');
		return new Response(JSON.stringify({ error: `save failed ${upsert.status}: ${t.slice(0, 200)}` }), {
			status: 500,
			headers: { 'content-type': 'application/json' }
		});
	}
	return new Response(JSON.stringify({ connected: true }), {
		headers: { 'content-type': 'application/json' }
	});
};

export const DELETE: RequestHandler = async ({ request }) => {
	const auth = requireAuth(request);
	if (typeof auth !== 'string') return auth;
	const sub = jwtSubject(auth);
	if (!sub) return new Response('bad token', { status: 401 });

	const r = await fetch(`${CONFIG.API_BASE}/user_preferences?user_id=eq.${sub}`, {
		method: 'PATCH',
		headers: {
			Authorization: auth,
			'Content-Type': 'application/json',
			Prefer: 'return=minimal'
		},
		body: JSON.stringify({
			binance_api_key: null,
			binance_api_secret: null,
			binance_connected_at: null
		})
	});
	if (!r.ok) {
		return new Response(JSON.stringify({ error: `disconnect ${r.status}` }), {
			status: 500,
			headers: { 'content-type': 'application/json' }
		});
	}
	return new Response(JSON.stringify({ connected: false }), {
		headers: { 'content-type': 'application/json' }
	});
};
