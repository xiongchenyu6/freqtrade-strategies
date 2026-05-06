// GoTrue client — minimal JWT session management.
// Runs client-side only (uses localStorage). API calls use getToken() which
// safely returns null on SSR.
import { writable, derived, type Readable } from 'svelte/store';
import { browser } from '$app/environment';
import { CONFIG } from './config';

export interface Session {
	access_token: string;
	refresh_token: string;
	expires_at: number; // epoch ms
	user: { sub?: string; email?: string; role?: string };
}

const KEY = 'qt_session_v1';
/** Cookie the gate reads — route access flag. */
const GATE_COOKIE = 'qt_authed';
/** Cookie the SSR server reads to call PostgREST on behalf of the user.
 * Scoped to the same origin as the worker; PostgREST is on a different
 * subdomain so this cookie is not sent to it directly — SvelteKit SSR
 * reads it and re-emits as a Bearer header when proxying. */
const JWT_COOKIE = 'qt_jwt';

function setAuthCookies(token: string, maxAgeSec: number) {
	if (!browser) return;
	const attrs = `path=/; max-age=${maxAgeSec}; SameSite=Lax` + (location.protocol === 'https:' ? '; Secure' : '');
	document.cookie = `${GATE_COOKIE}=1; ${attrs}`;
	document.cookie = `${JWT_COOKIE}=${token}; ${attrs}`;
}
function clearAuthCookies() {
	if (!browser) return;
	document.cookie = `${GATE_COOKIE}=; path=/; max-age=0; SameSite=Lax`;
	document.cookie = `${JWT_COOKIE}=; path=/; max-age=0; SameSite=Lax`;
}

function loadInitial(): Session | null {
	if (!browser) return null;
	try {
		const raw = localStorage.getItem(KEY);
		return raw ? (JSON.parse(raw) as Session) : null;
	} catch {
		return null;
	}
}

const initialSession = loadInitial();
export const session = writable<Session | null>(initialSession);

export const user: Readable<Session['user'] | null> = derived(session, ($s) => $s?.user ?? null);

export function getToken(): string | null {
	if (!browser) return null;
	// Primary: localStorage session (kept fresh by the auth refresh timer).
	const raw = localStorage.getItem(KEY);
	if (raw) {
		try {
			const s: Session = JSON.parse(raw);
			if (Date.now() < s.expires_at) return s.access_token;
		} catch {
			// fall through to cookie
		}
	}
	// Fallback: qt_jwt cookie (set by SSR after OAuth callback). Lets API
	// calls succeed when localStorage was cleared but the cookie is still
	// live — without this, /chart's onMount fetch goes anon and gets 401
	// from auth-only views (ohlc_1h_recent, etc.).
	const m = document.cookie.match(/(?:^|;\s*)qt_jwt=([^;]+)/);
	return m ? decodeURIComponent(m[1]) : null;
}

function persist(s: Session | null) {
	if (!browser) return;
	if (s) localStorage.setItem(KEY, JSON.stringify(s));
	else localStorage.removeItem(KEY);
}

function decodeJwt<T = Record<string, unknown>>(tok: string): T | null {
	try {
		const [, p] = tok.split('.');
		return JSON.parse(atob(p.replace(/-/g, '+').replace(/_/g, '/')));
	} catch {
		return null;
	}
}

async function handleTokenResp(d: {
	access_token: string;
	refresh_token: string;
	expires_in?: number;
}): Promise<Session> {
	const payload = decodeJwt<{ sub?: string; email?: string; role?: string }>(d.access_token) ?? {};
	const expiresIn = d.expires_in ?? 3600;
	const s: Session = {
		access_token: d.access_token,
		refresh_token: d.refresh_token,
		expires_at: Date.now() + expiresIn * 1000,
		user: { sub: payload.sub, email: payload.email, role: payload.role }
	};
	persist(s);
	session.set(s);
	setAuthCookies(d.access_token, expiresIn);
	scheduleRefresh(s);
	return s;
}

export async function login(email: string, password: string) {
	const r = await fetch(`${CONFIG.AUTH_BASE}/token?grant_type=password`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ email, password })
	});
	const d = await r.json();
	if (!r.ok) throw new Error(d.error_description || d.msg || `login ${r.status}`);
	return handleTokenResp(d);
}

export async function signup(email: string, password: string) {
	const r = await fetch(`${CONFIG.AUTH_BASE}/signup`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ email, password })
	});
	const d = await r.json();
	if (!r.ok) throw new Error(d.msg || d.error || `signup ${r.status}`);
	if (d.access_token) return handleTokenResp(d);
	return null;
}

export function logout() {
	persist(null);
	session.set(null);
	clearAuthCookies();
	clearRefreshTimer();
}

// --- Silent refresh ------------------------------------------------------
// GoTrue tokens are 1h; we swap them ~5 min before expiry so a user with a
// tab open never sees a 401-and-bounce. Refresh tokens rotate on use, so two
// tabs racing will make the loser's token invalid — acceptable trade-off at
// friend scale; layer a BroadcastChannel lock later if multi-tab becomes a
// real pattern.

const REFRESH_MARGIN_MS = 5 * 60 * 1000;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let refreshInFlight: Promise<void> | null = null;

function clearRefreshTimer() {
	if (refreshTimer) {
		clearTimeout(refreshTimer);
		refreshTimer = null;
	}
}

function scheduleRefresh(s: Session) {
	if (!browser) return;
	clearRefreshTimer();
	if (!s.refresh_token) return;
	const delay = Math.max(0, s.expires_at - Date.now() - REFRESH_MARGIN_MS);
	refreshTimer = setTimeout(() => void doRefresh(), delay);
}

async function doRefresh(): Promise<void> {
	if (refreshInFlight) return refreshInFlight;
	const current = loadInitial();
	if (!current?.refresh_token) return;
	refreshInFlight = (async () => {
		try {
			const r = await fetch(`${CONFIG.AUTH_BASE}/token?grant_type=refresh_token`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ refresh_token: current.refresh_token })
			});
			if (r.status === 400 || r.status === 401) {
				// Refresh token rotated out or revoked. Force a clean logout so the
				// gate bounces the user to /login?next=... on next navigation.
				logout();
				return;
			}
			if (!r.ok) {
				// Transient failure — retry in 60s.
				refreshTimer = setTimeout(() => void doRefresh(), 60_000);
				return;
			}
			const d = (await r.json()) as {
				access_token: string;
				refresh_token: string;
				expires_in?: number;
			};
			await handleTokenResp(d);
		} catch {
			// Network blip — try again soon.
			refreshTimer = setTimeout(() => void doRefresh(), 60_000);
		} finally {
			refreshInFlight = null;
		}
	})();
	return refreshInFlight;
}

// Kick off the refresh cycle if we booted with an existing session.
if (browser && initialSession) scheduleRefresh(initialSession);

// --- OAuth (Google) ------------------------------------------------------
// Redirect the browser to GoTrue's /authorize, which in turn bounces to
// Google's consent screen. After auth, GoTrue appends an access_token to
// the `redirect_to` URL as a hash fragment — consumeOauthHash() parses it.

export function loginWithGoogle(next?: string) {
	if (!browser) return;
	const cb = new URL(`${location.origin}/auth/callback`);
	if (next) cb.searchParams.set('next', next);
	const url = `${CONFIG.AUTH_BASE}/authorize?provider=google&redirect_to=${encodeURIComponent(cb.toString())}`;
	location.href = url;
}

/**
 * Parse the hash fragment GoTrue appends after an OAuth redirect and
 * persist the session. Returns the resulting Session on success, or null
 * if the fragment didn't contain tokens (e.g. user navigated here directly).
 * Call this from /auth/callback on mount.
 */
export function consumeOauthHash(): Session | null {
	if (!browser) return null;
	const hash = location.hash.replace(/^#/, '');
	if (!hash) return null;
	const params = new URLSearchParams(hash);
	const access_token = params.get('access_token');
	const refresh_token = params.get('refresh_token') ?? '';
	const expires_in = Number(params.get('expires_in') ?? 3600);
	const error = params.get('error_description') || params.get('error');
	if (error) throw new Error(decodeURIComponent(error));
	if (!access_token) return null;

	const payload = decodeJwt<{ sub?: string; email?: string; role?: string }>(access_token) ?? {};
	const s: Session = {
		access_token,
		refresh_token,
		expires_at: Date.now() + expires_in * 1000,
		user: { sub: payload.sub, email: payload.email, role: payload.role }
	};
	persist(s);
	session.set(s);
	setAuthCookies(access_token, expires_in);
	scheduleRefresh(s);
	// Clean the token out of the URL bar (preserve pathname + non-hash query).
	history.replaceState(null, '', location.pathname + location.search);
	return s;
}
