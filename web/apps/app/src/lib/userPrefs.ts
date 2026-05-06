// Thin wrapper around api.user_preferences (PostgREST). Requires a valid
// JWT — callers must check getToken() first or accept that unauthenticated
// requests return 401.
import { CONFIG } from './config';
import { getToken } from './auth';
import type { DcaPlan } from './dcaSim';

export interface UserPrefs {
	user_id: string;
	dca_plan: DcaPlan | null;
	email_digest: boolean;
	display_name: string | null;
	updated_at: string;
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

/** Fetch the current user's prefs row. Returns null if none exists yet. */
export async function loadPrefs(f: typeof fetch = fetch): Promise<UserPrefs | null> {
	const r = await f(`${CONFIG.API_BASE}/user_preferences?select=*`, { headers: authHeaders() });
	if (!r.ok) throw new Error(`prefs ${r.status}`);
	const rows = (await r.json()) as UserPrefs[];
	return rows[0] ?? null;
}

/** Upsert the current user's prefs. user_id is inferred from JWT sub. */
export async function savePrefs(
	patch: Partial<Pick<UserPrefs, 'dca_plan' | 'email_digest' | 'display_name'>>,
	userId: string,
	f: typeof fetch = fetch
): Promise<UserPrefs> {
	const body = { user_id: userId, ...patch };
	const r = await f(`${CONFIG.API_BASE}/user_preferences`, {
		method: 'POST',
		headers: {
			...authHeaders(),
			Prefer: 'resolution=merge-duplicates,return=representation'
		},
		body: JSON.stringify(body)
	});
	if (!r.ok) {
		const t = await r.text().catch(() => '');
		throw new Error(`save prefs ${r.status} ${t.slice(0, 200)}`);
	}
	const rows = (await r.json()) as UserPrefs[];
	return rows[0];
}
