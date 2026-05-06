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

function client(): RealtimeClient {
	if (_client) return _client;
	const jwt = getToken() ?? CONFIG.REALTIME_ANON_JWT;
	// eslint-disable-next-line no-console
	console.info('[realtime] creating client →', CONFIG.REALTIME_URL);
	_client = new RealtimeClient(CONFIG.REALTIME_URL, {
		params: { apikey: jwt },
		transport: typeof WebSocket !== 'undefined' ? WebSocket : undefined,
		timeout: 20_000
	});
	_status.set('connecting');
	_client.connect();
	startStatusPolling();
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
	const channel = client().channel(topic, { config: { broadcast: { self: false } } });
	channel
		.on(
			'postgres_changes' as never,
			{ event, schema, table },
			(payload: unknown) => handler(payload as ChangePayload<T>)
		)
		.subscribe((status: string, err?: Error) => {
			// eslint-disable-next-line no-console
			console.info(`[realtime] channel ${topic} → ${status}`, err ?? '');
		});
	return () => {
		channel.unsubscribe();
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
