// Supabase Realtime client — self-hosted tenant `quant` on
// wss://quant.realtime.panda.qzz.io/socket.
//
// `RealtimeClient` appends `/websocket` + `vsn=2.0.0` itself — pass the base
// URL only, and don't duplicate vsn in params.
//
// Public status API in @supabase/realtime-js v2.104:
//   - `connectionState(): 'connecting'|'open'|'closing'|'closed'`  (documented)
//   - `isConnected(): boolean`
//   - NO `onOpen`/`onClose`/`onError` on the client itself — those live on
//     the internal Phoenix Socket adapter. Polling `connectionState()` every
//     500ms is the simplest reliable option.
import { RealtimeClient } from '@supabase/realtime-js';
import { writable, type Readable } from 'svelte/store';
import { browser } from '$app/environment';
import { CONFIG } from './config';
import { getToken } from './auth';

export type RealtimeStatus = 'idle' | 'connecting' | 'open' | 'closing' | 'closed';

const _status = writable<RealtimeStatus>('idle');
export const realtimeStatus: Readable<RealtimeStatus> = { subscribe: _status.subscribe };

export type ChangeEvent = 'INSERT' | 'UPDATE' | 'DELETE' | '*';
export type ChangePayload<T = Record<string, unknown>> = {
	eventType: 'INSERT' | 'UPDATE' | 'DELETE';
	schema: string;
	table: string;
	commit_timestamp: string;
	new: T;
	old: T | Record<string, never>;
};

let _client: RealtimeClient | null = null;
let _statusTimer: ReturnType<typeof setInterval> | null = null;

function startStatusPolling() {
	if (_statusTimer) return;
	const tick = () => {
		try {
			const s = _client?.connectionState?.();
			if (s) _status.set(s as RealtimeStatus);
		} catch {
			/* ignore */
		}
	};
	tick();
	_statusTimer = setInterval(tick, 500);
}

/** Swap the channel-level token for a realtime-shaped authenticated one.
 * Auth0 access tokens lack the top-level `role` claim realtime needs for CDC
 * RLS, so /api/realtime-token re-mints one from the same shared secret. The
 * socket itself always connects with the anon apikey (valid role claim);
 * setAuth() upgrades what RLS sees on the channels. */
async function upgradeAuth(c: RealtimeClient) {
	const auth0Tok = getToken();
	if (!auth0Tok) return;
	try {
		const r = await fetch('/api/realtime-token', {
			headers: { Authorization: `Bearer ${auth0Tok}` }
		});
		if (!r.ok) return;
		const { token } = (await r.json()) as { token: string };
		await c.setAuth(token);
	} catch {
		// stay on the anon channel token — public streams still work
	}
}

/** Resolves once the auth upgrade attempt finished (either way). Channel
 * joins must wait on this: a postgres_changes subscription snapshots its RLS
 * role at join time, so joining before setAuth() lands would pin the channel
 * to anon — which the quant.* tables reject — and no rows would ever arrive. */
let _ready: Promise<void> | null = null;

function client(): RealtimeClient {
	if (_client) return _client;
	// eslint-disable-next-line no-console
	console.info('[realtime] creating client →', CONFIG.REALTIME_URL);
	_client = new RealtimeClient(CONFIG.REALTIME_URL, {
		params: { apikey: CONFIG.REALTIME_ANON_JWT },
		transport: typeof WebSocket !== 'undefined' ? WebSocket : undefined,
		timeout: 20_000
	});
	_status.set('connecting');
	_client.connect();
	startStatusPolling();
	_ready = upgradeAuth(_client);
	return _client;
}

export function subscribeTo<T = Record<string, unknown>>(
	table: 'backtest_runs' | 'trades' | 'event_dca_triggers',
	handler: (payload: ChangePayload<T>) => void,
	opts: { event?: ChangeEvent; schema?: string } = {}
): () => void {
	if (!browser) return () => {};
	const { event = '*', schema = 'quant' } = opts;
	const topic = `realtime:${schema}:${table}`;
	const c = client();
	let channel: ReturnType<RealtimeClient['channel']> | null = null;
	let cancelled = false;
	void (_ready ?? Promise.resolve()).then(() => {
		if (cancelled) return;
		channel = c.channel(topic, { config: { broadcast: { self: false } } });
		channel
			.on('postgres_changes' as never, { event, schema, table }, (payload: unknown) =>
				handler(payload as ChangePayload<T>)
			)
			.subscribe((status: string, err?: Error) => {
				// eslint-disable-next-line no-console
				console.info(`[realtime] channel ${topic} → ${status}`, err ?? '');
			});
	});
	return () => {
		cancelled = true;
		channel?.unsubscribe();
	};
}

export function disconnectRealtime() {
	if (_statusTimer) {
		clearInterval(_statusTimer);
		_statusTimer = null;
	}
	if (_client) {
		_client.disconnect();
		_client = null;
		_status.set('idle');
	}
}
