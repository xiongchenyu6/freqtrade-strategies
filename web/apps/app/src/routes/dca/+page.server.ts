import type { PageServerLoad } from './$types';
import { vps, supabase } from '$lib/api';
import type { EventDcaTrigger, DcaLogRow, OhlcRow } from '$lib/types';

export interface DcaKindAgg {
	kind: string;
	count: number;
	total_usdt: number;
	avg_severity: number | null;
}

export const load: PageServerLoad = async ({ fetch, cookies }) => {
	const jwt = cookies.get('qt_jwt');
	const auth = jwt ? `Bearer ${jwt}` : undefined;
	const isAuthed = Boolean(jwt);

	const ohlcFor = (pair: string) =>
		isAuthed
			? vps
					.ohlcDaily(fetch, pair, { from: '2017-01-01', limit: 4000, authHeader: auth })
					.catch(() => [] as OhlcRow[])
			: vps
					.publicOhlcDaily(fetch, pair, { from: '2017-01-01', limit: 4000 })
					.catch(() => [] as OhlcRow[]);

	const [triggers, log, btcOhlc, ethOhlc, bnbOhlc, solOhlc] = await Promise.all([
		isAuthed
			? vps
					.eventDcaTriggers(fetch, { limit: 500, authHeader: auth })
					.catch(() => [] as EventDcaTrigger[])
			: vps.publicEventTriggers(fetch, { limit: 500 }).catch(() => [] as EventDcaTrigger[]),
		supabase.dcaLog(fetch, { limit: 200 }).catch(() => [] as DcaLogRow[]),
		ohlcFor('BTC/USDT'),
		ohlcFor('ETH/USDT'),
		ohlcFor('BNB/USDT'),
		ohlcFor('SOL/USDT')
	]);
	const ohlcByCoin = { BTC: btcOhlc, ETH: ethOhlc, BNB: bnbOhlc, SOL: solOhlc };

	const byKind = new Map<string, EventDcaTrigger[]>();
	for (const t of triggers) {
		const k = t.kind || 'UNKNOWN';
		if (!byKind.has(k)) byKind.set(k, []);
		byKind.get(k)!.push(t);
	}
	const kindAggs: DcaKindAgg[] = [...byKind]
		.map(([kind, xs]) => {
			const total = xs.reduce((s, x) => s + (x.amount_usdt ?? 0), 0);
			const sevs = xs.map((x) => x.severity).filter((v): v is number => v != null);
			const avg = sevs.length ? sevs.reduce((s, v) => s + v, 0) / sevs.length : null;
			return { kind, count: xs.length, total_usdt: total, avg_severity: avg };
		})
		.sort((a, b) => b.count - a.count);

	const sortedLog = [...log].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
	let cum = 0;
	const cumulative = sortedLog.map((r) => {
		cum += r.amount_usdt ?? 0;
		return { ts: r.timestamp, amount: r.amount_usdt ?? 0, cum, mode: r.mode };
	});

	const totalEventUsdt = triggers.reduce((s, t) => s + (t.amount_usdt ?? 0), 0);
	const totalScheduledUsdt = log.reduce((s, r) => s + (r.amount_usdt ?? 0), 0);

	return {
		isAuthed,
		triggers,
		log,
		kindAggs,
		cumulative,
		ohlcByCoin,
		summary: {
			event_count: triggers.length,
			event_total_usdt: totalEventUsdt,
			scheduled_count: log.length,
			scheduled_total_usdt: totalScheduledUsdt,
			last_event: triggers[0]?.ts ?? null,
			last_scheduled: log[0]?.timestamp ?? null
		}
	};
};
