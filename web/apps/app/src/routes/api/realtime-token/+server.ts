// Exchange an Auth0 access token for a supabase-realtime token.
//
// Why: realtime requires a top-level `role` claim to authorize the socket and
// to SET ROLE for CDC RLS, but Auth0 strips non-namespaced custom claims from
// access tokens — so the browser can never present `role` directly. Both
// tokens share one HS256 secret (the Auth0 API signing secret), so this Worker
// can verify the incoming token and mint the realtime-shaped one.
import type { RequestHandler } from './$types';

const NS = 'https://panda.qzz.io';
const enc = new TextEncoder();

function b64urlToBytes(s: string): Uint8Array<ArrayBuffer> {
	const b = atob(s.replace(/-/g, '+').replace(/_/g, '/'));
	return Uint8Array.from(b, (c) => c.charCodeAt(0)) as Uint8Array<ArrayBuffer>;
}
function bytesToB64url(u: Uint8Array): string {
	let s = '';
	for (const b of u) s += String.fromCharCode(b);
	return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function hmacKey(secret: string): Promise<CryptoKey> {
	return crypto.subtle.importKey(
		'raw',
		enc.encode(secret),
		{ name: 'HMAC', hash: 'SHA-256' },
		false,
		['sign', 'verify']
	);
}

function json(status: number, body: unknown): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

export const GET: RequestHandler = async ({ request, platform }) => {
	const secret = platform?.env?.REALTIME_SIGNING_SECRET;
	if (!secret) return json(500, { error: 'REALTIME_SIGNING_SECRET not configured' });

	const auth = request.headers.get('authorization');
	if (!auth?.startsWith('Bearer ')) return json(401, { error: 'auth required' });
	const tok = auth.slice(7);
	const parts = tok.split('.');
	if (parts.length !== 3) return json(401, { error: 'malformed token' });

	const key = await hmacKey(secret);
	const ok = await crypto.subtle.verify(
		'HMAC',
		key,
		b64urlToBytes(parts[2]),
		enc.encode(`${parts[0]}.${parts[1]}`)
	);
	if (!ok) return json(401, { error: 'bad signature' });

	let claims: Record<string, unknown>;
	try {
		claims = JSON.parse(new TextDecoder().decode(b64urlToBytes(parts[1])));
	} catch {
		return json(401, { error: 'bad payload' });
	}
	const now = Math.floor(Date.now() / 1000);
	const exp = typeof claims.exp === 'number' ? claims.exp : 0;
	if (exp <= now) return json(401, { error: 'expired' });
	if (claims[`${NS}/role`] !== 'authenticated') return json(403, { error: 'not authenticated' });

	const payload = {
		role: 'authenticated',
		sub: claims[`${NS}/uid`] ?? claims.sub,
		iss: 'quant-worker',
		ref: 'quant',
		iat: now,
		exp // realtime token dies with the Auth0 token that minted it
	};
	const header = bytesToB64url(enc.encode(JSON.stringify({ alg: 'HS256', typ: 'JWT' })));
	const body = bytesToB64url(enc.encode(JSON.stringify(payload)));
	const sig = new Uint8Array(
		await crypto.subtle.sign('HMAC', key, enc.encode(`${header}.${body}`))
	);
	return json(200, { token: `${header}.${body}.${bytesToB64url(sig)}`, expires_at: exp * 1000 });
};
