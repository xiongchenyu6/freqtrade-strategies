<script lang="ts">
	import type { PageData } from './$types';
	import type { EventDcaTrigger, BacktestRun } from '$lib/types';
	import { fmtTime, fmtUSD, fmtPct } from '$lib/utils';
	import { t, type Lang } from '$lib/i18n';

	let { data }: { data: PageData } = $props();
	const lang = $derived<Lang>(data.lang ?? 'zh');
	const runs = $derived(data.runs);
	// Top-level shared constant referenced by sort callbacks in many
	// $derived.by blocks; missing from those local scopes, so declared
	// here as a module-level fallback to avoid ReferenceError at SSR
	// time when authed users get real run data.
	const TF_ORDER = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d'];

	type Tab = 'all' | 'events' | 'backtests';
	type SignalItem =
		| { _type: 'event'; _ts: string; item: EventDcaTrigger }
		| { _type: 'backtest'; _ts: string; item: BacktestRun };

	let query = $state('');
	let activeTab = $state<Tab>('all');

	const KIND_BORDER: Record<string, string> = {
		FLASH: 'border-l-[#e84040]',
		FAST: 'border-l-[#e88a00]',
		SUSTAIN: 'border-l-[#4a9eff]',
		CAPITUL: 'border-l-[#7b5fff]'
	};
	const KIND_BADGE: Record<string, string> = {
		FLASH: 'bg-red-950/60 text-red-400',
		FAST: 'bg-orange-950/60 text-orange-400',
		SUSTAIN: 'bg-blue-950/60 text-blue-400',
		CAPITUL: 'bg-purple-950/60 text-purple-400'
	};

	const merged = $derived.by((): SignalItem[] => {
		const evItems: SignalItem[] = data.events.map((e) => ({
			_type: 'event',
			_ts: e.ts,
			item: e
		}));
		const runItems: SignalItem[] = data.runs.map((r) => ({
			_type: 'backtest',
			_ts: r.started_at ?? r.imported_at,
			item: r
		}));

		let all: SignalItem[];
		if (activeTab === 'events') all = evItems;
		else if (activeTab === 'backtests') all = runItems;
		else all = [...evItems, ...runItems];

		// sort descending by timestamp
		all.sort((a, b) => (a._ts < b._ts ? 1 : -1));

		// apply text search
		const q = query.trim().toLowerCase();
		if (!q) return all;

		return all.filter((s) => {
			if (s._type === 'event') {
				const e = s.item;
				return (
					e.kind.toLowerCase().includes(q) ||
					(e.mode ?? '').toLowerCase().includes(q) ||
					(e.severity != null && String(e.severity).includes(q))
				);
			} else {
				const r = s.item;
				return (
					r.strategy.toLowerCase().includes(q) ||
					(r.timeframe ?? '').toLowerCase().includes(q)
				);
			}
		});
	});

	const isGated = $derived(data.events.length === 0 && data.runs.length === 0);

	// 30-day event activity calendar
	const eventCalendar = $derived.by(() => {
		if (data.events.length === 0) return null;
		const now = new Date();
		const days: { date: string; count: number; kinds: Record<string, number> }[] = [];
		for (let i = 29; i >= 0; i--) {
			const d = new Date(now);
			d.setDate(d.getDate() - i);
			days.push({ date: d.toISOString().slice(0, 10), count: 0, kinds: {} });
		}
		for (const e of data.events) {
			const day = e.ts?.slice(0, 10);
			const cell = days.find(d => d.date === day);
			if (!cell) continue;
			cell.count++;
			cell.kinds[e.kind] = (cell.kinds[e.kind] ?? 0) + 1;
		}
		const maxCount = Math.max(1, ...days.map(d => d.count));
		// Split into 5 rows of 6 columns (30 days)
		const rows: typeof days[] = [];
		for (let i = 0; i < 30; i += 6) rows.push(days.slice(i, i + 6));
		return { rows, maxCount };
	});

	// Strategy freshness: days since last import per strategy
	const stratFreshness = $derived.by(() => {
		const now = Date.now();
		const byStrat = new Map<string, { lastImport: string; runCount: number; bestProfit: number | null }>();
		for (const r of data.runs) {
			const ts = r.imported_at ?? r.started_at ?? '';
			if (!ts) continue;
			if (!byStrat.has(r.strategy)) byStrat.set(r.strategy, { lastImport: ts, runCount: 0, bestProfit: null });
			const s = byStrat.get(r.strategy)!;
			if (ts > s.lastImport) s.lastImport = ts;
			s.runCount++;
			if (r.total_profit_pct != null && (s.bestProfit == null || r.total_profit_pct > s.bestProfit)) s.bestProfit = r.total_profit_pct;
		}
		return [...byStrat.entries()]
			.map(([strategy, v]) => ({
				strategy,
				...v,
				daysAgo: Math.floor((now - new Date(v.lastImport).getTime()) / 86400000),
			}))
			.sort((a, b) => a.daysAgo - b.daysAgo);
	});

	// Rolling severity trend (7-event moving average)
	const severityTrend = $derived.by(() => {
		const pts = data.events
			.filter(e => e.ts && e.severity != null)
			.sort((a, b) => a.ts!.localeCompare(b.ts!));
		if (pts.length < 10) return null;
		const WINDOW = 7;
		const smoothed: { ts: string; avg: number }[] = [];
		for (let i = WINDOW - 1; i < pts.length; i++) {
			const slice = pts.slice(i - WINDOW + 1, i + 1);
			smoothed.push({ ts: pts[i].ts!, avg: slice.reduce((s, e) => s + e.severity!, 0) / WINDOW });
		}
		const W = 560, H = 60, PAD = 4;
		const avgs = smoothed.map(p => p.avg);
		const mn = Math.min(...avgs), mx = Math.max(...avgs, 0.01);
		const toX = (i: number) => PAD + (i / (smoothed.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / (mx - mn || 0.01)) * (H - PAD * 2);
		const poly = smoothed.map((p, i) => `${toX(i).toFixed(1)},${toY(p.avg).toFixed(1)}`).join(' ');
		const latest = avgs[avgs.length - 1];
		const prev = avgs[Math.max(0, avgs.length - 8)];
		const rising = latest > prev + 0.02;
		const falling = latest < prev - 0.02;
		return { poly, W, H, PAD, latest, rising, falling, mn, mx };
	});

	// Weekly event kind timeline (last 8 weeks)
	const KIND_COLORS: Record<string, string> = {
		FLASH: 'var(--ch-loss)',
		FAST: 'var(--ch-warn)',
		SUSTAIN: 'var(--ch-violet)',
		CAPITUL: 'var(--ch-violet-strong)',
	};
	const signalKindTimeline = $derived.by(() => {
		if (data.events.length === 0) return null;
		const KINDS = ['FLASH', 'FAST', 'SUSTAIN', 'CAPITUL'];
		const weekMap = new Map<string, Record<string, number>>();
		for (const e of data.events) {
			if (!e.ts) continue;
			const d = new Date(e.ts);
			const jan4 = new Date(d.getFullYear(), 0, 4);
			const startOfWeek = new Date(jan4);
			startOfWeek.setDate(jan4.getDate() - ((jan4.getDay() + 6) % 7));
			const wn = Math.ceil(((d.getTime() - startOfWeek.getTime()) / 86400000 + 1) / 7);
			const key = `${d.getFullYear()}-W${String(wn).padStart(2, '0')}`;
			if (!weekMap.has(key)) weekMap.set(key, {});
			const wk = weekMap.get(key)!;
			wk[e.kind] = (wk[e.kind] ?? 0) + 1;
		}
		const weeks = [...weekMap.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(-8);
		if (weeks.length < 2) return null;
		const maxTotal = Math.max(1, ...weeks.map(([, k]) => KINDS.reduce((s, kk) => s + (k[kk] ?? 0), 0)));
		return { weeks, KINDS, maxTotal };
	});

	// Mode distribution: count + avg severity per mode
	const modeBreakdown = $derived.by(() => {
		if (data.events.length === 0) return null;
		const map = new Map<string, { count: number; sevSum: number; sevN: number; kinds: Record<string, number> }>();
		for (const e of data.events) {
			const m = e.mode ?? 'unknown';
			if (!map.has(m)) map.set(m, { count: 0, sevSum: 0, sevN: 0, kinds: {} });
			const v = map.get(m)!;
			v.count++;
			if (e.severity != null) { v.sevSum += e.severity; v.sevN++; }
			v.kinds[e.kind] = (v.kinds[e.kind] ?? 0) + 1;
		}
		const rows = [...map.entries()]
			.map(([mode, v]) => ({
				mode,
				count: v.count,
				avgSev: v.sevN > 0 ? v.sevSum / v.sevN : null,
				topKind: Object.entries(v.kinds).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—',
			}))
			.sort((a, b) => b.count - a.count);
		if (rows.length < 2) return null;
		const maxCount = Math.max(1, ...rows.map(r => r.count));
		return rows.map(r => ({ ...r, barPct: (r.count / maxCount) * 100 }));
	});

	// FNG distribution: histogram of fear & greed index values at trigger time
	const fngHistogram = $derived.by(() => {
		const vals = data.events.filter(e => e.fng != null).map(e => e.fng!);
		if (vals.length < 5) return null;
		const BINS = 10;
		const buckets = Array.from({ length: BINS }, (_, i) => ({
			lo: i * 10, count: 0,
			color: i < 3 ? 'var(--ch-profit)' : i >= 7 ? 'var(--ch-loss)' : 'var(--ch-warn-light)',
			label: i === 0 ? 'XFear' : i === 9 ? 'XGreed' : String(i * 10),
		}));
		for (const v of vals) {
			buckets[Math.min(BINS - 1, Math.floor(v / 10))].count++;
		}
		const maxCount = Math.max(1, ...buckets.map(b => b.count));
		const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
		return { buckets: buckets.map(b => ({ ...b, barPct: (b.count / maxCount) * 100 })), avg, total: vals.length };
	});

	// Summary stats
	// Severity range per trigger kind: min/median/max
	const severityByKind = $derived.by(() => {
		const evts = data.events.filter(e => e.severity != null && e.kind);
		if (evts.length < 4) return null;
		const map = new Map<string, number[]>();
		for (const e of evts) {
			if (!map.has(e.kind)) map.set(e.kind, []);
			map.get(e.kind)!.push(e.severity!);
		}
		const rows = [...map.entries()].map(([kind, vals]) => {
			const sorted = [...vals].sort((a, b) => a - b);
			const mid = Math.floor(sorted.length / 2);
			const median = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
			return { kind, min: sorted[0], median, max: sorted[sorted.length - 1], count: sorted.length };
		}).sort((a, b) => b.median - a.median);
		if (rows.length < 2) return null;
		return rows;
	});

	// Cumulative DCA spend over time
	const dcaCumulativeSpend = $derived.by(() => {
		const evts = data.events
			.filter(e => e.ts && e.amount_usdt != null && e.amount_usdt > 0)
			.sort((a, b) => a.ts.localeCompare(b.ts));
		if (evts.length < 3) return null;
		let running = 0;
		const pts = evts.map((e, i) => { running += e.amount_usdt!; return { i, total: running, date: e.ts.slice(0, 10), kind: e.kind }; });
		const maxTotal = Math.max(0.01, pts[pts.length - 1].total);
		const W = 520, H = 70, PAD = 6;
		const toX = (i: number) => PAD + (i / Math.max(1, pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v / maxTotal) * (H - PAD * 2);
		const polyline = pts.map(p => `${toX(p.i).toFixed(1)},${toY(p.total).toFixed(1)}`).join(' ');
		return { polyline, W, H, PAD, total: pts[pts.length - 1].total, n: pts.length, firstDate: pts[0].date, lastDate: pts[pts.length - 1].date };
	});

	// Top events by USDT deployed with severity color coding
	// Fear & greed vs amount deployed scatter
	const fngVsAmount = $derived.by(() => {
		const pts = data.events.filter(e => e.fng != null && e.amount_usdt != null && e.amount_usdt > 0);
		if (pts.length < 8) return null;
		const xs = pts.map(e => e.fng!);
		const ys = pts.map(e => e.amount_usdt!);
		const xMin = 0, xMax = 100;
		const yMin = 0, yMax = Math.max(...ys, 1);
		const W = 520, H = 110, PAD = 20;
		const toX = (v: number) => PAD + (v / xMax) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - yMin) / (yMax - yMin || 1)) * (H - PAD * 2);
		const n = pts.length;
		const mx = xs.reduce((a, b) => a + b, 0) / n, my = ys.reduce((a, b) => a + b, 0) / n;
		const num = xs.reduce((s, x, i) => s + (x - mx) * (ys[i] - my), 0);
		const den = Math.sqrt(xs.reduce((s, x) => s + (x - mx) ** 2, 0) * ys.reduce((s, y) => s + (y - my) ** 2, 0));
		const corr = den === 0 ? 0 : num / den;
		const dots = pts.map(e => ({
			x: toX(e.fng!), y: toY(e.amount_usdt!),
			fng: e.fng!, amount: e.amount_usdt!, kind: e.kind,
			color: e.fng! <= 25 ? 'var(--ch-profit)' : e.fng! >= 75 ? 'var(--ch-loss)' : 'var(--ch-warn)',
		}));
		return { dots, W, H, PAD, corr, yMax };
	});

	const eventAmountRanking = $derived.by(() => {
		const evts = data.events.filter(e => e.amount_usdt != null && e.amount_usdt > 0);
		if (evts.length < 4) return null;
		const rows = [...evts]
			.sort((a, b) => b.amount_usdt! - a.amount_usdt!)
			.slice(0, 12)
			.map(e => ({ kind: e.kind, amount: e.amount_usdt!, severity: e.severity ?? 0, ts: e.ts }));
		const maxAmount = Math.max(0.01, ...rows.map(r => r.amount));
		return rows.map(r => ({ ...r, barPct: (r.amount / maxAmount) * 100 }));
	});

	// Kind trend: monthly event count per kind (last 6 months)
	const kindMonthlyTrend = $derived.by(() => {
		const evts = data.events.filter(e => e.ts && e.kind);
		if (evts.length < 10) return null;
		const now = new Date();
		const months = Array.from({ length: 6 }, (_, i) => {
			const d = new Date(now.getFullYear(), now.getMonth() - (5 - i), 1);
			return { key: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2,'0')}`, label: d.toLocaleDateString('en', { month: 'short' }) };
		});
		const kinds = [...new Set(evts.map(e => e.kind))].slice(0, 4);
		const KIND_COLORS = ['var(--ch-violet)', 'var(--ch-profit)', 'var(--ch-warn)', 'var(--ch-loss)'];
		const data2 = months.map(m => {
			const bucket = evts.filter(e => e.ts.startsWith(m.key));
			const byKind = Object.fromEntries(kinds.map(k => [k, bucket.filter(e => e.kind === k).length]));
			return { ...m, byKind, total: bucket.length };
		});
		const maxTotal = Math.max(1, ...data2.map(d => d.total));
		return { months: data2, kinds, colors: KIND_COLORS, maxTotal };
	});

	// Hourly event distribution: count + avg severity per UTC hour
	const hourlyEventDist = $derived.by(() => {
		const evts = data.events.filter(e => e.ts && e.severity != null);
		if (evts.length < 12) return null;
		const hours = Array.from({ length: 24 }, (_, i) => ({ h: i, count: 0, sevSum: 0, amountSum: 0 }));
		for (const e of evts) {
			const h = new Date(e.ts).getUTCHours();
			hours[h].count++;
			hours[h].sevSum += e.severity ?? 0;
			hours[h].amountSum += e.amount_usdt ?? 0;
		}
		const maxCount = Math.max(...hours.map(h => h.count), 1);
		const bars = hours.map(h => ({
			h: h.h,
			count: h.count,
			pct: h.count / maxCount,
			avgSev: h.count ? h.sevSum / h.count : 0,
			avgAmount: h.count ? h.amountSum / h.count : 0,
		}));
		const peakH = bars.reduce((a, b) => (b.count > a.count ? b : a)).h;
		return { bars, maxCount, peakH };
	});

	// Signal kind proportion: share of each kind vs total, with avg severity
	const kindProportions = $derived.by(() => {
		const evts = data.events.filter(e => e.kind);
		if (evts.length < 4) return null;
		const map = new Map<string, { count: number; sevSum: number; amountSum: number }>();
		for (const e of evts) {
			if (!map.has(e.kind)) map.set(e.kind, { count: 0, sevSum: 0, amountSum: 0 });
			const v = map.get(e.kind)!;
			v.count++;
			v.sevSum += e.severity ?? 0;
			v.amountSum += e.amount_usdt ?? 0;
		}
		const total = evts.length;
		const rows = [...map.entries()]
			.map(([kind, v]) => ({
				kind,
				count: v.count,
				pct: v.count / total,
				avgSev: v.sevSum / v.count,
				avgAmount: v.amountSum / v.count,
			}))
			.sort((a, b) => b.count - a.count);
		return { rows, total };
	});

	// F&G zone event count + avg USDT: how much we deploy per sentiment zone
	// Avg severity per UTC hour: which hours produce the most intense signals?
	const severityTimeOfDay = $derived.by(() => {
		const evts = data.events.filter(e => e.ts && e.severity != null);
		if (evts.length < 10) return null;
		const hours = Array.from({ length: 24 }, (_, h) => ({ h, sum: 0, count: 0 }));
		for (const e of evts) {
			const h = new Date(e.ts).getUTCHours();
			hours[h].sum += e.severity!;
			hours[h].count++;
		}
		const rows = hours.map(h => ({
			h: h.h,
			label: `${String(h.h).padStart(2, '0')}h`,
			count: h.count,
			avg: h.count > 0 ? h.sum / h.count : null,
		}));
		if (rows.every(r => r.count === 0)) return null;
		const maxAvg = Math.max(0.001, ...rows.map(r => r.avg ?? 0));
		return rows.map(r => ({ ...r, barPct: r.avg != null ? (r.avg / maxAvg) * 100 : 0 }));
	});

	const fngZoneEventCount = $derived.by(() => {
		const evts = data.events.filter(e => e.fng != null);
		if (evts.length < 8) return null;
		const ZONES = [
			{ label: 'Extreme Fear', lo: 0, hi: 25, color: 'var(--ch-profit)' },
			{ label: 'Fear', lo: 25, hi: 45, color: 'var(--ch-profit-light)' },
			{ label: 'Neutral', lo: 45, hi: 55, color: 'var(--ch-warn-light)' },
			{ label: 'Greed', lo: 55, hi: 75, color: 'var(--ch-loss-light)' },
			{ label: 'Ext. Greed', lo: 75, hi: 101, color: 'var(--ch-loss)' },
		];
		const rows = ZONES.map(z => {
			const bucket = evts.filter(e => e.fng! >= z.lo && e.fng! < z.hi);
			const withAmt = bucket.filter(e => e.amount_usdt != null && e.amount_usdt > 0);
			const avgAmt = withAmt.length ? withAmt.reduce((s, e) => s + e.amount_usdt!, 0) / withAmt.length : null;
			return { ...z, count: bucket.length, avgAmt };
		});
		if (rows.every(r => r.count === 0)) return null;
		const maxCount = Math.max(1, ...rows.map(r => r.count));
		return rows.map(r => ({ ...r, barPct: (r.count / maxCount) * 100 }));
	});

	// Avg time between consecutive same-kind events — shows signal cadence per kind
	const kindAvgInterval = $derived.by(() => {
		const sorted = [...data.events]
			.filter(e => e.ts && e.kind)
			.sort((a, b) => a.ts.localeCompare(b.ts));
		if (sorted.length < 5) return null;
		const byKind = new Map<string, number[]>();
		for (let i = 1; i < sorted.length; i++) {
			const prev = sorted[i - 1];
			const curr = sorted[i];
			if (prev.kind !== curr.kind) continue;
			const diffHours = (new Date(curr.ts).getTime() - new Date(prev.ts).getTime()) / 3600000;
			if (diffHours > 0 && diffHours < 720) {
				if (!byKind.has(curr.kind)) byKind.set(curr.kind, []);
				byKind.get(curr.kind)!.push(diffHours);
			}
		}
		const rows = [...byKind.entries()]
			.filter(([, diffs]) => diffs.length >= 2)
			.map(([kind, diffs]) => {
				const avg = diffs.reduce((a, b) => a + b, 0) / diffs.length;
				const s2 = [...diffs].sort((a, b) => a - b);
				const mid = Math.floor(s2.length / 2);
				const med = s2.length % 2 ? s2[mid] : (s2[mid - 1] + s2[mid]) / 2;
				return { kind, avg, med, count: diffs.length };
			})
			.sort((a, b) => a.avg - b.avg);
		if (rows.length < 1) return null;
		const maxAvg = Math.max(1, ...rows.map(r => r.avg));
		return rows.map(r => ({ ...r, barPct: (r.avg / maxAvg) * 100 }));
	});

	// Run profit timeline: backtest run profit% sorted by imported_at — shows improvement trend
	const runProfitTimeline = $derived.by(() => {
		const sorted = data.runs
			.filter(r => (r.imported_at || r.started_at) && r.total_profit_pct != null)
			.sort((a, b) => (a.imported_at ?? a.started_at ?? '').localeCompare(b.imported_at ?? b.started_at ?? ''))
			.slice(-40);
		if (sorted.length < 6) return null;
		const vals = sorted.map(r => r.total_profit_pct!);
		const W = 560, H = 80, PAD = 8;
		const mn = Math.min(...vals), mx = Math.max(...vals, mn + 0.01);
		const toX = (i: number) => PAD + (i / (sorted.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / (mx - mn)) * (H - PAD * 2);
		const zeroY = toY(0);
		const polyline = sorted.map((r, i) => `${toX(i).toFixed(1)},${toY(r.total_profit_pct!).toFixed(1)}`).join(' ');
		const recent = vals.slice(-5);
		const early = vals.slice(0, 5);
		const recentAvg = recent.reduce((a, b) => a + b, 0) / recent.length;
		const earlyAvg = early.reduce((a, b) => a + b, 0) / early.length;
		const improving = recentAvg > earlyAvg + 2;
		return { polyline, W, H, PAD, zeroY, mn, mx, count: sorted.length, recentAvg, earlyAvg, improving };
	});

	const runCalmarTimeline = $derived.by(() => {
		const sorted = data.runs
			.filter(r => (r.imported_at || r.started_at) && r.calmar != null && isFinite(r.calmar) && r.calmar > -20 && r.calmar < 50)
			.sort((a, b) => (a.imported_at ?? a.started_at ?? '').localeCompare(b.imported_at ?? b.started_at ?? ''))
			.slice(-40);
		if (sorted.length < 6) return null;
		const vals = sorted.map(r => r.calmar!);
		const W = 560, H = 72, PAD = 8;
		const mn = Math.min(...vals), mx = Math.max(...vals, mn + 0.1);
		const toX = (i: number) => PAD + (i / (sorted.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / (mx - mn)) * (H - PAD * 2);
		const zeroY = mn < 0 ? toY(0) : H - PAD;
		const polyline = sorted.map((r, i) => `${toX(i).toFixed(1)},${toY(r.calmar!).toFixed(1)}`).join(' ');
		const recent = vals.slice(-5).reduce((a, b) => a + b, 0) / 5;
		const early = vals.slice(0, 5).reduce((a, b) => a + b, 0) / 5;
		return { polyline, W, H, PAD, zeroY, mn, mx, recent, early, improving: recent > early + 0.1, count: sorted.length };
	});

	const runSortinoTimeline = $derived.by(() => {
		const sorted = data.runs
			.filter(r => (r.imported_at || r.started_at) && r.sortino != null && isFinite(r.sortino) && r.sortino > -50 && r.sortino < 200)
			.sort((a, b) => (a.imported_at ?? a.started_at ?? '').localeCompare(b.imported_at ?? b.started_at ?? ''))
			.slice(-40);
		if (sorted.length < 6) return null;
		const vals = sorted.map(r => r.sortino!);
		const W = 560, H = 72, PAD = 8;
		const mn = Math.min(...vals), mx = Math.max(...vals, mn + 0.1);
		const toX = (i: number) => PAD + (i / (sorted.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / (mx - mn)) * (H - PAD * 2);
		const zeroY = mn < 0 ? toY(0) : H - PAD;
		const polyline = sorted.map((r, i) => `${toX(i).toFixed(1)},${toY(r.sortino!).toFixed(1)}`).join(' ');
		const recent = vals.slice(-5).reduce((a, b) => a + b, 0) / 5;
		const early = vals.slice(0, 5).reduce((a, b) => a + b, 0) / 5;
		return { polyline, W, H, PAD, zeroY, mn, mx, recent, early, improving: recent > early + 0.5, count: sorted.length };
	});

	const fngSeverityMatrix = $derived.by(() => {
		const ZONES = [
			{ label: 'Ext Fear', lo: 0, hi: 20, color: 'var(--ch-loss)' },
			{ label: 'Fear', lo: 20, hi: 40, color: 'var(--ch-warn)' },
			{ label: 'Neutral', lo: 40, hi: 60, color: 'var(--ch-warn-light)' },
			{ label: 'Greed', lo: 60, hi: 80, color: 'var(--ch-profit-light)' },
			{ label: 'Ext Greed', lo: 80, hi: 101, color: 'var(--ch-violet-light)' },
		];
		const evts = data.events.filter(e => e.fng != null && e.severity != null);
		if (evts.length < 8) return null;
		const sevs = [...new Set(evts.map(e => e.severity!))].sort((a, b) => a - b);
		const matrix = sevs.map(sev => {
			const sub = evts.filter(e => e.severity === sev);
			const counts = ZONES.map(z => sub.filter(e => e.fng! >= z.lo && e.fng! < z.hi).length);
			const total = sub.length;
			return { sev, counts, total };
		});
		const maxTotal = Math.max(1, ...matrix.map(r => r.total));
		return { matrix, ZONES, maxTotal };
	});

	// Win-rate sparkline across backtest runs over time (distinct from runProfitTimeline/runCalmarTimeline/runSortinoTimeline)
	const runWinRateTimeline = $derived.by(() => {
		const sorted = [...data.runs]
			.filter(r => r.imported_at && r.win_rate_pct != null)
			.sort((a, b) => a.imported_at.localeCompare(b.imported_at))
			.slice(-60);
		if (sorted.length < 5) return null;
		const vals = sorted.map(r => r.win_rate_pct!);
		const W = 560, H = 64, PAD = 4;
		const mn = Math.min(...vals), mx = Math.max(...vals, mn + 0.01);
		const toX = (i: number) => PAD + (i / (vals.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / (mx - mn)) * (H - PAD * 2);
		const fiftyY = mn < 50 && mx > 50 ? toY(50) : null;
		const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
		const avgY = toY(avg);
		const poly = vals.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
		const trend = vals[vals.length - 1] - vals[0];
		const latest = vals[vals.length - 1];
		return { poly, W, H, PAD, mn, mx, avg, avgY, fiftyY, trend, latest, count: sorted.length };
	});

	// Profit factor sparkline across runs by import date (distinct from runProfitTimeline/runCalmarTimeline/runSortinoTimeline/runWinRateTimeline)
	const runProfitFactorTimeline = $derived.by(() => {
		const sorted = [...data.runs]
			.filter(r => r.imported_at && r.profit_factor != null && isFinite(r.profit_factor) && r.profit_factor >= 0 && r.profit_factor <= 10)
			.sort((a, b) => a.imported_at.localeCompare(b.imported_at))
			.slice(-60);
		if (sorted.length < 5) return null;
		const vals = sorted.map(r => r.profit_factor!);
		const W = 560, H = 64, PAD = 4;
		const mn = Math.min(...vals), mx = Math.max(...vals, mn + 0.01);
		const toX = (i: number) => PAD + (i / (vals.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / (mx - mn)) * (H - PAD * 2);
		const oneY = mn < 1 && mx > 1 ? toY(1) : null;
		const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
		const trend = vals[vals.length - 1] - vals[0];
		const poly = vals.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
		const latest = vals[vals.length - 1];
		return { poly, W, H, PAD, mn, mx, oneY, avg, trend, latest, count: sorted.length };
	});

	const stats = $derived.by(() => {
		const kindCounts: Record<string, number> = {};
		for (const e of data.events) {
			kindCounts[e.kind] = (kindCounts[e.kind] ?? 0) + 1;
		}
		const profits = data.runs.map(r => r.total_profit_pct).filter((v): v is number => v != null);
		const avgProfit = profits.length ? profits.reduce((a, b) => a + b, 0) / profits.length : null;
		const lastEvent = data.events[0]?.ts ?? null;
		const lastRun = data.runs[0]?.started_at ?? data.runs[0]?.imported_at ?? null;
		const lastActivity = [lastEvent, lastRun].filter(Boolean).sort().reverse()[0] ?? null;
		return { kindCounts, avgProfit, lastActivity, totalEvents: data.events.length, totalRuns: data.runs.length };
	});

	const runCalmarSignalTimeline = $derived.by(() => {
		const sorted = data.runs
			.filter(r => r.calmar != null && isFinite(r.calmar) && r.calmar > 0 && r.imported_at)
			.sort((a, b) => new Date(a.imported_at!).getTime() - new Date(b.imported_at!).getTime());
		if (sorted.length < 5) return null;
		const vals = sorted.map(r => r.calmar!);
		const mn = Math.min(...vals), mx = Math.max(...vals);
		const range = mx - mn || 1;
		const W = 400, H = 60, PAD = 6;
		const toX = (i: number) => PAD + (i / Math.max(1, vals.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / range) * (H - PAD * 2);
		const poly = vals.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
		const trend = vals[vals.length - 1] - vals[0];
		return { poly, W, H, PAD, mn, mx, trend };
	});

	const runSortinoDistribution = $derived.by(() => {
		const vals = data.runs.filter(r => r.sortino != null && isFinite(r.sortino) && r.sortino > 0 && r.sortino < 50).map(r => r.sortino!);
		if (vals.length < 8) return null;
		const BINS = 8;
		const mx = Math.max(...vals);
		const step = mx / BINS;
		const buckets = Array.from({ length: BINS }, (_, i) => ({
			label: `${(i * step).toFixed(1)}–${((i + 1) * step).toFixed(1)}`,
			lo: i * step, hi: (i + 1) * step, count: 0
		}));
		for (const v of vals) {
			const idx = Math.min(BINS - 1, Math.floor(v / step));
			buckets[idx].count++;
		}
		const maxCount = Math.max(1, ...buckets.map(b => b.count));
		const median = [...vals].sort((a, b) => a - b)[Math.floor(vals.length / 2)];
		return { buckets: buckets.map(b => ({ ...b, barPct: (b.count / maxCount) * 100 })), median, total: vals.length };
	});

	const runMaxDrawdownTimeline = $derived.by(() => {
		const sorted = data.runs
			.filter(r => r.max_drawdown_pct != null && isFinite(r.max_drawdown_pct) && r.imported_at)
			.sort((a, b) => new Date(a.imported_at!).getTime() - new Date(b.imported_at!).getTime());
		if (sorted.length < 5) return null;
		const vals = sorted.map(r => r.max_drawdown_pct!);
		const mn = Math.min(...vals), mx = Math.max(...vals);
		const range = mx - mn || 1;
		const W = 400, H = 60, PAD = 6;
		const toX = (i: number) => PAD + (i / Math.max(1, vals.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / range) * (H - PAD * 2);
		const poly = vals.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
		const trend = vals[vals.length - 1] - vals[0];
		return { poly, W, H, PAD, mn, mx, trend };
	});

	const runProfitFactorDistribution = $derived.by(() => {
		const vals = data.runs.filter(r => r.profit_factor != null && isFinite(r.profit_factor) && r.profit_factor > 0 && r.profit_factor < 20).map(r => r.profit_factor!);
		if (vals.length < 8) return null;
		const mn = Math.min(...vals), mx = Math.max(...vals);
		const range = mx - mn || 1;
		const BINS = 8;
		const step = range / BINS;
		const buckets = Array.from({ length: BINS }, (_, i) => ({
			lo: mn + i * step, hi: mn + (i + 1) * step,
			label: (mn + i * step).toFixed(1),
			count: 0
		}));
		for (const v of vals) {
			const idx = Math.min(BINS - 1, Math.floor((v - mn) / step));
			buckets[idx].count++;
		}
		const maxCount = Math.max(1, ...buckets.map(b => b.count));
		const median = [...vals].sort((a, b) => a - b)[Math.floor(vals.length / 2)];
		return { buckets: buckets.map(b => ({ ...b, barPct: (b.count / maxCount) * 100 })), median, mn, mx, total: vals.length };
	});

	const runCalmarVsSortino = $derived.by(() => {
		const pts = data.runs.filter(r => r.calmar != null && r.sortino != null && isFinite(r.calmar) && isFinite(r.sortino) && r.calmar > -50 && r.calmar < 200 && r.sortino > -50 && r.sortino < 200);
		if (pts.length < 10) return null;
		const W = 360, H = 80, PAD = 8;
		const xs = pts.map(r => r.calmar!), ys = pts.map(r => r.sortino!);
		const xMin = Math.min(...xs), xMax = Math.max(...xs, xMin + 0.01);
		const yMin = Math.min(...ys), yMax = Math.max(...ys, yMin + 0.01);
		const toX = (v: number) => PAD + ((v - xMin) / (xMax - xMin)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - yMin) / (yMax - yMin)) * (H - PAD * 2);
		const dots = pts.map(r => ({
			cx: toX(r.calmar!), cy: toY(r.sortino!),
			good: r.calmar! > 0 && r.sortino! > 0
		}));
		return { dots, W, H, PAD, xMin, xMax, yMin, yMax };
	});

	const runWinRateDistribution = $derived.by(() => {
		const vals = data.runs.filter(r => r.win_rate_pct != null && isFinite(r.win_rate_pct) && r.win_rate_pct >= 0 && r.win_rate_pct <= 100).map(r => r.win_rate_pct!);
		if (vals.length < 8) return null;
		const BINS = 10;
		const step = 100 / BINS;
		const buckets = Array.from({ length: BINS }, (_, i) => ({
			lo: i * step, hi: (i + 1) * step,
			label: `${(i * step).toFixed(0)}%`,
			count: 0
		}));
		for (const v of vals) {
			const idx = Math.min(BINS - 1, Math.floor(v / step));
			buckets[idx].count++;
		}
		const maxCount = Math.max(1, ...buckets.map(b => b.count));
		const median = [...vals].sort((a, b) => a - b)[Math.floor(vals.length / 2)];
		return { buckets: buckets.map(b => ({ ...b, barPct: (b.count / maxCount) * 100 })), median, total: vals.length };
	});

	const runTradeCountDistribution = $derived.by(() => {
		const vals = data.runs.filter(r => (r as any).total_trades != null && isFinite((r as any).total_trades) && (r as any).total_trades > 0).map(r => (r as any).total_trades as number);
		if (vals.length < 8) return null;
		const mx = Math.max(...vals);
		const BINS = 8, step = mx / BINS;
		const buckets = Array.from({ length: BINS }, (_, i) => ({
			label: i === BINS - 1 ? `>${(i * step).toFixed(0)}` : `${(i * step).toFixed(0)}–${((i + 1) * step).toFixed(0)}`,
			count: 0
		}));
		for (const v of vals) {
			const idx = Math.min(BINS - 1, Math.floor(v / step));
			buckets[idx].count++;
		}
		const maxCount = Math.max(1, ...buckets.map(b => b.count));
		const median = [...vals].sort((a, b) => a - b)[Math.floor(vals.length / 2)];
		return { buckets: buckets.map(b => ({ ...b, barPct: (b.count / maxCount) * 100 })), median, total: vals.length };
	});

	const runProfitVsDrawdownScatter = $derived.by(() => {
		const pts = data.runs.filter(r => r.total_profit_pct != null && isFinite(r.total_profit_pct) && r.max_drawdown_pct != null && isFinite(r.max_drawdown_pct) && r.max_drawdown_pct >= 0);
		if (pts.length < 8) return null;
		const W = 360, H = 90, PAD = 10;
		const xs = pts.map(r => r.max_drawdown_pct!);
		const ys = pts.map(r => r.total_profit_pct!);
		const xMin = Math.min(...xs), xMax = Math.max(...xs, xMin + 0.01);
		const yMin = Math.min(...ys), yMax = Math.max(...ys, yMin + 0.01);
		const toX = (v: number) => PAD + ((v - xMin) / (xMax - xMin)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - yMin) / (yMax - yMin)) * (H - PAD * 2);
		const zeroY = toY(0);
		const dots = pts.map(r => ({
			cx: toX(r.max_drawdown_pct!), cy: toY(r.total_profit_pct!),
			good: r.total_profit_pct! > 0 && r.max_drawdown_pct! < (xMax - xMin) * 0.4 + xMin,
			profit: r.total_profit_pct!, dd: r.max_drawdown_pct!
		}));
		return { dots, W, H, zeroY, xMin, xMax, yMin, yMax };
	});

	const runSharpeVsCalmar = $derived.by(() => {
		const pts = data.runs.filter(r =>
			r.sharpe != null && isFinite(r.sharpe) && r.sharpe > -20 && r.sharpe < 100 &&
			r.calmar != null && isFinite(r.calmar) && r.calmar > -20 && r.calmar < 100
		);
		if (pts.length < 8) return null;
		const W = 360, H = 90, PAD = 10;
		const xs = pts.map(r => r.sharpe!), ys = pts.map(r => r.calmar!);
		const xMin = Math.min(...xs), xMax = Math.max(...xs, xMin + 0.01);
		const yMin = Math.min(...ys), yMax = Math.max(...ys, yMin + 0.01);
		const toX = (v: number) => PAD + ((v - xMin) / (xMax - xMin)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - yMin) / (yMax - yMin)) * (H - PAD * 2);
		const zeroX = toX(0), zeroY = toY(0);
		const dots = pts.map(r => ({
			cx: toX(r.sharpe!), cy: toY(r.calmar!),
			good: r.sharpe! > 0 && r.calmar! > 0
		}));
		return { dots, W, H, zeroX, zeroY, xMin, xMax, yMin, yMax };
	});

	const runStrategyBestProfitRanking = $derived.by(() => {
		const map = new Map<string, { best: number; count: number }>();
		for (const r of data.runs) {
			if (r.total_profit_pct == null || !isFinite(r.total_profit_pct)) continue;
			if (!map.has(r.strategy)) map.set(r.strategy, { best: -Infinity, count: 0 });
			const e = map.get(r.strategy)!;
			if (r.total_profit_pct > e.best) e.best = r.total_profit_pct;
			e.count++;
		}
		const rows = [...map.entries()]
			.filter(([, v]) => v.count >= 2 && isFinite(v.best))
			.map(([strategy, v]) => ({ strategy, best: v.best, count: v.count }))
			.sort((a, b) => b.best - a.best)
			.slice(0, 12);
		if (rows.length < 3) return null;
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.best)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.best) / maxAbs) * 100, positive: r.best >= 0 }));
	});

	const runTimeframeWinRateMatrix = $derived.by(() => {
		const strategies = [...new Set(data.runs.map(r => r.strategy).filter(Boolean))] as string[];
		const timeframes = [...new Set(data.runs.map(r => r.timeframe).filter(Boolean))] as string[];
		if (strategies.length < 2 || timeframes.length < 2) return null;
		const map = new Map<string, Map<string, { wins: number; total: number }>>();
		for (const r of data.runs) {
			if (!r.strategy || !r.timeframe || r.total_profit_pct == null || !isFinite(r.total_profit_pct)) continue;
			if (!map.has(r.strategy)) map.set(r.strategy, new Map());
			const tm = map.get(r.strategy)!;
			if (!tm.has(r.timeframe)) tm.set(r.timeframe, { wins: 0, total: 0 });
			const e = tm.get(r.timeframe)!;
			e.total++;
			if (r.total_profit_pct > 0) e.wins++;
		}
		const validStrats = strategies.filter(s => {
			const tm = map.get(s);
			return tm && [...tm.values()].some(v => v.total >= 2);
		}).slice(0, 10);
		const tfOrder = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d'];
		const sortedTf = timeframes.sort((a, b) => {
			const ai = tfOrder.indexOf(a), bi = tfOrder.indexOf(b);
			return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
		});
		if (validStrats.length < 2) return null;
		const cells = validStrats.map(s => ({
			strategy: s,
			tfs: sortedTf.map(tf => {
				const e = map.get(s)?.get(tf);
				if (!e || e.total < 2) return { tf, wr: null, total: 0 };
				return { tf, wr: e.wins / e.total, total: e.total };
			})
		}));
		return { cells, timeframes: sortedTf };
	});

	const runSortinoByStrategy = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of data.runs) {
			if (!r.strategy || r.sortino == null || !isFinite(r.sortino) || r.sortino < -10 || r.sortino > 200) continue;
			if (!map.has(r.strategy)) map.set(r.strategy, []);
			map.get(r.strategy)!.push(r.sortino);
		}
		const rows = [...map.entries()]
			.filter(([, vals]) => vals.length >= 3)
			.map(([strategy, vals]) => {
				const sorted = [...vals].sort((a, b) => a - b);
				const mid = Math.floor(sorted.length / 2);
				const med = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
				return { strategy, sortino: med, count: vals.length };
			})
			.sort((a, b) => b.sortino - a.sortino)
			.slice(0, 12);
		if (rows.length < 3) return null;
		const absMax = Math.max(0.01, ...rows.map(r => Math.abs(r.sortino)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.sortino) / absMax) * 100, positive: r.sortino > 0 }));
	});

	const runMaxDrawdownByStrategy = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of data.runs) {
			if (!r.strategy || r.max_drawdown_pct == null || !isFinite(r.max_drawdown_pct) || r.max_drawdown_pct < 0) continue;
			if (!map.has(r.strategy)) map.set(r.strategy, []);
			map.get(r.strategy)!.push(r.max_drawdown_pct);
		}
		const rows = [...map.entries()]
			.filter(([, vals]) => vals.length >= 3)
			.map(([strategy, vals]) => {
				const sorted = [...vals].sort((a, b) => a - b);
				const mid = Math.floor(sorted.length / 2);
				const med = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
				return { strategy, dd: med, count: vals.length };
			})
			.sort((a, b) => a.dd - b.dd)
			.slice(0, 12);
		if (rows.length < 3) return null;
		const maxDd = Math.max(0.01, ...rows.map(r => r.dd));
		return rows.map(r => ({ ...r, barPct: (r.dd / maxDd) * 100, safe: r.dd < 20 }));
	});

	// Win/loss ratio per strategy: cumulative wins÷losses across all runs (distinct from win_rate)
	const runWinLossRatioByStrategy = $derived.by(() => {
		const map = new Map<string, { wins: number; losses: number }>();
		for (const r of data.runs) {
			if (!r.strategy || r.wins == null || r.losses == null || r.losses === 0) continue;
			if (!map.has(r.strategy)) map.set(r.strategy, { wins: 0, losses: 0 });
			const e = map.get(r.strategy)!;
			e.wins += r.wins;
			e.losses += r.losses;
		}
		const rows = [...map.entries()]
			.filter(([, v]) => v.losses > 0)
			.map(([strategy, v]) => ({ strategy, ratio: v.wins / v.losses, wins: v.wins, losses: v.losses }))
			.filter(r => r.ratio > 0 && r.ratio < 50)
			.sort((a, b) => b.ratio - a.ratio)
			.slice(0, 12);
		if (rows.length < 3) return null;
		const maxRatio = Math.max(0.01, ...rows.map(r => r.ratio));
		return rows.map(r => ({ ...r, barPct: (r.ratio / maxRatio) * 100 }));
	});

	// Median profit_factor per timeframe (distinct from per-strategy or time-based timelines)
	const runProfitFactorByTimeframe = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of data.runs) {
			if (!r.timeframe || r.profit_factor == null || !isFinite(r.profit_factor) || r.profit_factor <= 0 || r.profit_factor > 100) continue;
			if (!map.has(r.timeframe)) map.set(r.timeframe, []);
			map.get(r.timeframe)!.push(r.profit_factor);
		}
		const TF_ORDER = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d'];
		const rows = [...map.entries()]
			.filter(([, vals]) => vals.length >= 3)
			.map(([tf, vals]) => {
				const sorted = [...vals].sort((a, b) => a - b);
				const mid = Math.floor(sorted.length / 2);
				const med = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
				return { tf, pf: med, count: vals.length };
			})
			.sort((a, b) => {
				const ai = TF_ORDER.indexOf(a.tf), bi = TF_ORDER.indexOf(b.tf);
				return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
			});
		if (rows.length < 2) return null;
		const maxPf = Math.max(0.01, ...rows.map(r => r.pf));
		return rows.map(r => ({ ...r, barPct: (r.pf / maxPf) * 100, good: r.pf >= 1.5 }));
	});

	const runProfitByTimeframe = $derived.by(() => {
		const valid = data.runs.filter(r => r.timeframe && r.total_profit_pct != null && isFinite(r.total_profit_pct));
		if (valid.length < 4) return null;
		const map = new Map<string, { sum: number; count: number; best: number }>();
		for (const r of valid) {
			if (!map.has(r.timeframe)) map.set(r.timeframe, { sum: 0, count: 0, best: -Infinity });
			const e = map.get(r.timeframe)!;
			e.sum += r.total_profit_pct!;
			e.count++;
			if (r.total_profit_pct! > e.best) e.best = r.total_profit_pct!;
		}
		const TF_ORDER = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d'];
		const rows = [...map.entries()]
			.map(([tf, v]) => ({ tf, avg: v.sum / v.count, best: v.best, count: v.count }))
			.sort((a, b) => {
				const ai = TF_ORDER.indexOf(a.tf), bi = TF_ORDER.indexOf(b.tf);
				return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
			});
		if (rows.length < 2) return null;
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.avg)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.avg) / maxAbs) * 100 }));
	});

	const runSharpeDistribution = $derived.by(() => {
		const vals = data.runs.filter(r => r.sharpe != null && isFinite(r.sharpe) && r.sharpe > -20 && r.sharpe < 50).map(r => r.sharpe!);
		if (vals.length < 5) return null;
		const mn = Math.min(...vals), mx = Math.max(...vals);
		const range = mx - mn || 1;
		const BINS = 10;
		const step = range / BINS;
		const buckets = Array.from({ length: BINS }, (_, i) => ({
			lo: mn + i * step, hi: mn + (i + 1) * step, count: 0,
			label: (mn + i * step).toFixed(1)
		}));
		for (const v of vals) {
			const idx = Math.min(BINS - 1, Math.floor((v - mn) / step));
			buckets[idx].count++;
		}
		const maxCount = Math.max(1, ...buckets.map(b => b.count));
		const sorted = [...vals].sort((a, b) => a - b);
		const median = sorted[Math.floor(sorted.length / 2)];
		const positive = vals.filter(v => v > 0).length;
		return { buckets, maxCount, median, positive, total: vals.length, step };
	});

	const eventFngMovingAvg = $derived.by(() => {
		const pts = data.events
			.filter(e => e.fng != null && e.ts)
			.sort((a, b) => a.ts.localeCompare(b.ts));
		const WINDOW = 7;
		if (pts.length < WINDOW + 2) return null;
		const smoothed = pts.slice(WINDOW - 1).map((_, i) => {
			const slice = pts.slice(i, i + WINDOW);
			const avg = slice.reduce((s, e) => s + e.fng!, 0) / WINDOW;
			return { ts: pts[i + WINDOW - 1].ts.slice(0, 10), avg };
		});
		const vals = smoothed.map(p => p.avg);
		const W = 560, H = 72, PAD = 8;
		const mn = Math.min(...vals), mx = Math.max(...vals, mn + 1);
		const toX = (i: number) => PAD + (i / Math.max(1, smoothed.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / (mx - mn)) * (H - PAD * 2);
		const polyline = smoothed.map((p, i) => `${toX(i).toFixed(1)},${toY(p.avg).toFixed(1)}`).join(' ');
		const y50 = mn < 50 && mx > 50 ? toY(50) : null;
		const latest = vals[vals.length - 1];
		const trend = vals[vals.length - 1] - vals[0];
		return { W, H, polyline, y50, latest, trend, count: smoothed.length };
	});

	const runCalmarVsWinRate = $derived.by(() => {
		const pts = merged.filter(r =>
			r.calmar != null && isFinite(r.calmar) && r.calmar > -50 && r.calmar < 200 &&
			r.win_rate_pct != null && isFinite(r.win_rate_pct) && r.win_rate_pct >= 0 && r.win_rate_pct <= 100
		).map(r => ({ calmar: r.calmar!, wr: r.win_rate_pct!, tf: r.timeframe ?? '' }));
		if (pts.length < 6) return null;
		const cMin = Math.min(...pts.map(p => p.calmar));
		const cMax = Math.max(...pts.map(p => p.calmar), cMin + 0.01);
		const wMin = Math.min(...pts.map(p => p.wr));
		const wMax = Math.max(...pts.map(p => p.wr), wMin + 1);
		const W = 560, H = 130, PAD = 10;
		const TF_COL: Record<string, string> = { '5m': 'var(--ch-violet)', '15m': 'var(--ch-profit)', '1h': 'var(--ch-warn)', '4h': 'var(--ch-loss)', '1d': 'var(--ch-teal)' };
		const toX = (w: number) => PAD + ((w - wMin) / (wMax - wMin)) * (W - PAD * 2);
		const toY = (c: number) => H - PAD - ((c - cMin) / (cMax - cMin)) * (H - PAD * 2);
		const zeroY = cMin < 0 && cMax > 0 ? toY(0) : null;
		const dots = pts.map(p => ({ cx: toX(p.wr), cy: toY(p.calmar), color: TF_COL[p.tf] ?? 'var(--ch-axis-muted)' }));
		const positive = pts.filter(p => p.calmar > 0).length;
		return { W, H, dots, zeroY, wMin: wMin.toFixed(0), wMax: wMax.toFixed(0), cMin: cMin.toFixed(1), cMax: cMax.toFixed(1), total: pts.length, positive };
	});

	const runSortinoVsDrawdown = $derived.by(() => {
		const pts = merged.filter(r =>
			r.sortino != null && isFinite(r.sortino) && r.sortino > -50 && r.sortino < 200 &&
			r.max_drawdown_pct != null && isFinite(r.max_drawdown_pct) && r.max_drawdown_pct > 0
		).map(r => ({ sortino: r.sortino!, dd: r.max_drawdown_pct!, tf: r.timeframe ?? '' }));
		if (pts.length < 6) return null;
		const sMin = Math.min(...pts.map(p => p.sortino)), sMax = Math.max(...pts.map(p => p.sortino), sMin + 0.01);
		const dMin = Math.min(...pts.map(p => p.dd)), dMax = Math.max(...pts.map(p => p.dd), dMin + 0.01);
		const W = 560, H = 130, PAD = 10;
		const TF_COL: Record<string, string> = { '5m': 'var(--ch-violet)', '15m': 'var(--ch-profit)', '1h': 'var(--ch-warn)', '4h': 'var(--ch-loss)', '1d': 'var(--ch-teal)' };
		const toX = (d: number) => PAD + ((d - dMin) / (dMax - dMin)) * (W - PAD * 2);
		const toY = (s: number) => H - PAD - ((s - sMin) / (sMax - sMin)) * (H - PAD * 2);
		const zeroY = sMin < 0 && sMax > 0 ? toY(0) : null;
		const dots = pts.map(p => ({ cx: toX(p.dd), cy: toY(p.sortino), color: TF_COL[p.tf] ?? 'var(--ch-axis-muted)' }));
		const positive = pts.filter(p => p.sortino > 0).length;
		return { W, H, dots, zeroY, dMin: dMin.toFixed(1), dMax: dMax.toFixed(1), sMin: sMin.toFixed(1), sMax: sMax.toFixed(1), total: pts.length, positive };
	});

	const runProfitFactorVsCalmar = $derived.by(() => {
		const pts = merged.filter(r =>
			r.profit_factor != null && isFinite(r.profit_factor) && r.profit_factor > 0 && r.profit_factor < 30 &&
			r.calmar != null && isFinite(r.calmar) && r.calmar > -50 && r.calmar < 200
		).map(r => ({ pf: r.profit_factor!, calmar: r.calmar!, tf: r.timeframe ?? '' }));
		if (pts.length < 6) return null;
		const pfMin = Math.min(...pts.map(p => p.pf)), pfMax = Math.max(...pts.map(p => p.pf), pfMin + 0.01);
		const cMin = Math.min(...pts.map(p => p.calmar)), cMax = Math.max(...pts.map(p => p.calmar), cMin + 0.01);
		const W = 560, H = 130, PAD = 10;
		const TF_COL: Record<string, string> = { '5m': 'var(--ch-violet)', '15m': 'var(--ch-profit)', '1h': 'var(--ch-warn)', '4h': 'var(--ch-loss)', '1d': 'var(--ch-teal)' };
		const toX = (pf: number) => PAD + ((pf - pfMin) / (pfMax - pfMin)) * (W - PAD * 2);
		const toY = (c: number) => H - PAD - ((c - cMin) / (cMax - cMin)) * (H - PAD * 2);
		const zeroY = cMin < 0 && cMax > 0 ? toY(0) : null;
		const oneX = pfMin < 1 && pfMax > 1 ? toX(1) : null;
		const dots = pts.map(p => ({ cx: toX(p.pf), cy: toY(p.calmar), color: TF_COL[p.tf] ?? 'var(--ch-axis-muted)' }));
		const positive = pts.filter(p => p.calmar > 0 && p.pf > 1).length;
		return { W, H, dots, zeroY, oneX, pfMin: pfMin.toFixed(2), pfMax: pfMax.toFixed(2), cMin: cMin.toFixed(1), cMax: cMax.toFixed(1), total: pts.length, positive };
	});

	const runSharpeVsProfit = $derived.by(() => {
		const pts = merged.filter(r =>
			r.sharpe != null && isFinite(r.sharpe) && Math.abs(r.sharpe) < 50 &&
			r.total_profit_pct != null && isFinite(r.total_profit_pct)
		).map(r => ({ sharpe: r.sharpe!, profit: r.total_profit_pct!, tf: r.timeframe ?? '' }));
		if (pts.length < 6) return null;
		const sMin = Math.min(...pts.map(p => p.sharpe)), sMax = Math.max(...pts.map(p => p.sharpe), sMin + 0.01);
		const pMin = Math.min(...pts.map(p => p.profit)), pMax = Math.max(...pts.map(p => p.profit), pMin + 0.01);
		const W = 560, H = 130, PAD = 10;
		const TF_COL: Record<string, string> = { '5m': 'var(--ch-violet)', '15m': 'var(--ch-profit)', '1h': 'var(--ch-warn)', '4h': 'var(--ch-loss)', '1d': 'var(--ch-teal)' };
		const toX = (s: number) => PAD + ((s - sMin) / (sMax - sMin)) * (W - PAD * 2);
		const toY = (p: number) => H - PAD - ((p - pMin) / (pMax - pMin)) * (H - PAD * 2);
		const zeroX = sMin < 0 && sMax > 0 ? toX(0) : null;
		const zeroY = pMin < 0 && pMax > 0 ? toY(0) : null;
		const dots = pts.map(p => ({ cx: toX(p.sharpe), cy: toY(p.profit), color: TF_COL[p.tf] ?? 'var(--ch-axis-muted)' }));
		const quadrant = pts.filter(p => p.sharpe > 0 && p.profit > 0).length;
		return { W, H, dots, zeroX, zeroY, sMin: sMin.toFixed(2), sMax: sMax.toFixed(2), pMin: pMin.toFixed(1), pMax: pMax.toFixed(1), total: pts.length, quadrant };
	});

	const runDrawdownByStrategy = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const r of merged) {
			if (!r.strategy || r.max_drawdown_pct == null || !isFinite(r.max_drawdown_pct)) continue;
			if (!map[r.strategy]) map[r.strategy] = [];
			map[r.strategy].push(r.max_drawdown_pct);
		}
		const rows = Object.entries(map)
			.filter(([, v]) => v.length >= 1)
			.map(([strategy, vals]) => ({
				strategy,
				avg: vals.reduce((a, b) => a + b, 0) / vals.length,
				best: Math.min(...vals),
				count: vals.length
			}))
			.sort((a, b) => a.avg - b.avg)
			.slice(0, 12);
		if (rows.length < 3) return null;
		const maxAvg = Math.max(...rows.map(r => r.avg), 0.01);
		return { rows, maxAvg };
	});

	const runWinRateVsDrawdown = $derived.by(() => {
		const pts = merged.filter(r =>
			r.win_rate_pct != null && isFinite(r.win_rate_pct) &&
			r.max_drawdown_pct != null && isFinite(r.max_drawdown_pct)
		).map(r => ({ wr: r.win_rate_pct!, dd: r.max_drawdown_pct!, tf: r.timeframe ?? '' }));
		if (pts.length < 6) return null;
		const wrMin = Math.min(...pts.map(p => p.wr)), wrMax = Math.max(...pts.map(p => p.wr), wrMin + 1);
		const dMin = Math.min(...pts.map(p => p.dd)), dMax = Math.max(...pts.map(p => p.dd), dMin + 0.01);
		const W = 560, H = 130, PAD = 10;
		const TF_COL: Record<string, string> = { '5m': 'var(--ch-violet)', '15m': 'var(--ch-profit)', '1h': 'var(--ch-warn)', '4h': 'var(--ch-loss)', '1d': 'var(--ch-teal)' };
		const toX = (w: number) => PAD + ((w - wrMin) / (wrMax - wrMin)) * (W - PAD * 2);
		const toY = (d: number) => H - PAD - ((d - dMin) / (dMax - dMin)) * (H - PAD * 2);
		const dots = pts.map(p => ({ cx: toX(p.wr), cy: toY(p.dd), color: TF_COL[p.tf] ?? 'var(--ch-axis-muted)' }));
		const ideal = pts.filter(p => p.wr > 55 && p.dd < 15).length;
		return { W, H, dots, wrMin: wrMin.toFixed(0), wrMax: wrMax.toFixed(0), dMin: dMin.toFixed(1), dMax: dMax.toFixed(1), total: pts.length, ideal };
	});

	const runWeeklyCalmarTimeline = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const r of merged) {
			if (!r.imported_at || r.calmar == null || !isFinite(r.calmar) || Math.abs(r.calmar) > 200) continue;
			const week = r.imported_at.slice(0, 10);
			if (!map[week]) map[week] = [];
			map[week].push(r.calmar);
		}
		const weeks = Object.entries(map)
			.map(([week, vals]) => ({ week, avg: vals.reduce((a, b) => a + b, 0) / vals.length, count: vals.length }))
			.sort((a, b) => a.week.localeCompare(b.week));
		if (weeks.length < 4) return null;
		const vals = weeks.map(w => w.avg);
		const vMin = Math.min(...vals), vMax = Math.max(...vals, vMin + 0.01);
		const W = 560, H = 100, PAD = 12;
		const toX = (i: number) => PAD + (i / (weeks.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - vMin) / (vMax - vMin)) * (H - PAD * 2);
		const pts = weeks.map((w, i) => ({ x: toX(i), y: toY(w.avg), week: w.week, avg: w.avg, count: w.count }));
		const polyline = pts.map(p => `${p.x},${p.y}`).join(' ');
		const zeroY = vMin <= 0 && vMax >= 0 ? toY(0) : null;
		const latest = weeks[weeks.length - 1];
		const trend = weeks.length >= 3 ? (latest.avg - weeks[weeks.length - 3].avg) : 0;
		return { pts, polyline, W, H, zeroY, total: weeks.length, latest: latest.avg.toFixed(2), trend: trend.toFixed(2), vMin: vMin.toFixed(2), vMax: vMax.toFixed(2) };
	});

	const runWeeklyProfitFactorTimeline = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const r of merged) {
			if (!r.imported_at || r.profit_factor == null || !isFinite(r.profit_factor) || r.profit_factor <= 0 || r.profit_factor > 30) continue;
			const week = r.imported_at.slice(0, 10);
			if (!map[week]) map[week] = [];
			map[week].push(r.profit_factor);
		}
		const weeks = Object.entries(map)
			.map(([week, vals]) => ({ week, avg: vals.reduce((a, b) => a + b, 0) / vals.length, count: vals.length }))
			.sort((a, b) => a.week.localeCompare(b.week));
		if (weeks.length < 4) return null;
		const vals = weeks.map(w => w.avg);
		const vMin = Math.min(...vals), vMax = Math.max(...vals, vMin + 0.01);
		const W = 560, H = 90, PAD = 10;
		const toX = (i: number) => PAD + (i / Math.max(1, weeks.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - vMin) / (vMax - vMin)) * (H - PAD * 2);
		const pts = weeks.map((w, i) => ({ x: toX(i), y: toY(w.avg), avg: w.avg }));
		const polyline = pts.map(p => `${p.x},${p.y}`).join(' ');
		const oneY = vMin <= 1 && vMax >= 1 ? toY(1) : null;
		const latest = weeks[weeks.length - 1].avg;
		const aboveOne = weeks.filter(w => w.avg >= 1).length;
		return { W, H, pts, polyline, oneY, total: weeks.length, latest: latest.toFixed(2), aboveOne, vMin: vMin.toFixed(2), vMax: vMax.toFixed(2) };
	});

	const runStrategyTimeframeCalmarMatrix = $derived.by(() => {
		const TF_ORDER = ['5m', '15m', '1h', '4h', '1d'];
		const map: Record<string, Record<string, number[]>> = {};
		for (const r of merged) {
			if (!r.strategy || !r.timeframe || r.calmar == null || !isFinite(r.calmar) || Math.abs(r.calmar) > 200) continue;
			if (!map[r.strategy]) map[r.strategy] = {};
			if (!map[r.strategy][r.timeframe]) map[r.strategy][r.timeframe] = [];
			map[r.strategy][r.timeframe].push(r.calmar);
		}
		const TFS = TF_ORDER.filter(tf => Object.values(map).some(m => m[tf]));
		const strategies = Object.entries(map)
			.filter(([, tfMap]) => Object.values(tfMap).flat().length >= 3)
			.map(([strategy, tfMap]) => {
				const overall = Object.values(tfMap).flat();
				const avg = overall.reduce((a, b) => a + b, 0) / overall.length;
				return { strategy, tfMap, avg };
			})
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 10);
		if (strategies.length < 2 || TFS.length < 2) return null;
		const cells = strategies.flatMap(s => TFS.map(tf => {
			const vals = s.tfMap[tf] ?? [];
			const avg = vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
			return { strategy: s.strategy, tf, avg, count: vals.length };
		}));
		const filled = cells.filter(c => c.avg !== null);
		const vMin = Math.min(...filled.map(c => c.avg!));
		const vMax = Math.max(...filled.map(c => c.avg!), vMin + 0.01);
		return { strategies: strategies.map(s => s.strategy), TFS, cells, vMin: vMin.toFixed(2), vMax: vMax.toFixed(2), vRange: vMax - vMin };
	});

	const runProfitByDayOfWeek = $derived.by(() => {
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const map: Record<number, number[]> = {};
		for (const r of data.runs) {
			if (r.imported_at == null || r.total_profit_pct == null || !isFinite(r.total_profit_pct)) continue;
			const dow = new Date(r.imported_at).getDay();
			if (!map[dow]) map[dow] = [];
			map[dow].push(r.total_profit_pct);
		}
		const rows = DAYS.map((day, i) => {
			const vals = map[i] ?? [];
			const avg = vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
			return { day, avg, count: vals.length };
		});
		if (rows.every(r => r.count === 0)) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 420, H = 70, PAD = 8, barW = Math.floor((W - PAD * 2) / 7) - 2;
		return { rows, maxAbs, W, H, PAD, barW };
	});

	const runSharpeLeaderboard = $derived.by(() => {
		const best: Record<string, number> = {};
		for (const r of data.runs) {
			if (!r.strategy || r.sharpe == null || !isFinite(r.sharpe)) continue;
			if (best[r.strategy] == null || r.sharpe > best[r.strategy]) best[r.strategy] = r.sharpe;
		}
		const rows = Object.entries(best)
			.map(([strategy, sharpe]) => ({ strategy: strategy.slice(0, 22), sharpe }))
			.sort((a, b) => b.sharpe - a.sharpe)
			.slice(0, 12);
		if (rows.length < 3) return null;
		const maxSharpe = Math.max(...rows.map(r => r.sharpe), 0.01);
		return { rows, maxSharpe };
	});

	const runWinRateByTimeframe = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const r of data.runs) {
			if (!r.timeframe || r.win_rate_pct == null || !isFinite(r.win_rate_pct)) continue;
			if (!map[r.timeframe]) map[r.timeframe] = [];
			map[r.timeframe].push(r.win_rate_pct);
		}
		const TF_ORDER = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d'];
		const rows = Object.entries(map)
			.filter(([, v]) => v.length >= 2)
			.map(([tf, vals]) => {
				const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
				return { tf, avg, count: vals.length };
			})
			.sort((a, b) => (TF_ORDER.indexOf(a.tf) === -1 ? 99 : TF_ORDER.indexOf(a.tf)) - (TF_ORDER.indexOf(b.tf) === -1 ? 99 : TF_ORDER.indexOf(b.tf)));
		if (rows.length < 2) return null;
		const maxAvg = Math.max(...rows.map(r => r.avg), 0.01);
		const W = 420, H = 70, PAD = 8, barW = Math.min(55, Math.floor((W - PAD * 2) / rows.length) - 3);
		return { rows, maxAvg, W, H, PAD, barW };
	});

	const runCalmarByTimeframe = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const r of runs) {
			if (r.calmar == null || !r.timeframe) continue;
			if (!map[r.timeframe]) map[r.timeframe] = [];
			map[r.timeframe].push(r.calmar);
		}
		const rows = Object.entries(map)
			.map(([tf, vals]) => ({ tf, avg: vals.reduce((a, b) => a + b, 0) / vals.length, count: vals.length }))
			.sort((a, b) => (TF_ORDER.indexOf(a.tf) === -1 ? 99 : TF_ORDER.indexOf(a.tf)) - (TF_ORDER.indexOf(b.tf) === -1 ? 99 : TF_ORDER.indexOf(b.tf)));
		if (rows.length < 2) return null;
		const maxAvg = Math.max(...rows.map(r => r.avg), 0.01);
		const W = 420, H = 80, PAD = 8, barW = Math.min(55, Math.floor((W - PAD * 2) / rows.length) - 3);
		return { rows, maxAvg, W, H, PAD, barW };
	});

	const runAvgProfitFactorByTF = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const r of runs) {
			if (!r.timeframe || r.profit_factor == null || !isFinite(r.profit_factor) || r.profit_factor <= 0 || r.profit_factor > 20) continue;
			if (!map[r.timeframe]) map[r.timeframe] = [];
			map[r.timeframe].push(r.profit_factor);
		}
		const rows = Object.entries(map)
			.map(([tf, vals]) => ({ tf, avg: vals.reduce((a, b) => a + b, 0) / vals.length, count: vals.length }))
			.sort((a, b) => (TF_ORDER.indexOf(a.tf) === -1 ? 99 : TF_ORDER.indexOf(a.tf)) - (TF_ORDER.indexOf(b.tf) === -1 ? 99 : TF_ORDER.indexOf(b.tf)));
		if (rows.length < 2) return null;
		const maxAvg = Math.max(...rows.map(r => r.avg), 0.01);
		const W = 420, H = 80, PAD = 8, barW = Math.min(55, Math.floor((W - PAD * 2) / rows.length) - 3);
		return { rows, maxAvg, W, H, PAD, barW };
	});

	const runTopPairsByProfit = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const r of runs) {
			if (!r.pairs || !Array.isArray(r.pairs)) continue;
			for (const pair of r.pairs as string[]) {
				if (!map[pair]) map[pair] = [];
				if (r.total_profit_pct != null) map[pair].push(r.total_profit_pct);
			}
		}
		const rows = Object.entries(map)
			.filter(([, vals]) => vals.length >= 2)
			.map(([pair, vals]) => ({ pair: pair.split('/')[0], avg: vals.reduce((a, b) => a + b, 0) / vals.length, count: vals.length }))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 14);
		if (rows.length < 3) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 400, H = rows.length * 14 + 20, PAD = 8, midX = W / 2, barMaxW = (W - PAD * 2) / 2 - 40;
		return { rows, maxAbs, W, H, PAD, midX, barMaxW };
	});

	const runSortinoLeaderboard = $derived.by(() => {
		const best: Record<string, number> = {};
		for (const r of runs) {
			if (!r.strategy || r.sortino == null || !isFinite(r.sortino) || r.sortino <= 0) continue;
			if (!best[r.strategy] || r.sortino > best[r.strategy]) best[r.strategy] = r.sortino;
		}
		const rows = Object.entries(best)
			.map(([strategy, sortino]) => ({ strategy: strategy.slice(0, 22), sortino }))
			.sort((a, b) => b.sortino - a.sortino)
			.slice(0, 12);
		if (rows.length < 3) return null;
		const maxSortino = Math.max(...rows.map(r => r.sortino), 0.01);
		return { rows, maxSortino };
	});

	const runProfitDistributionHistogram = $derived.by(() => {
		const vals = runs.filter(r => r.total_profit_pct != null && isFinite(r.total_profit_pct)).map(r => r.total_profit_pct!);
		if (vals.length < 6) return null;
		const mn = Math.min(...vals), mx = Math.max(...vals);
		const bins = 14, step = (mx - mn) / bins || 1;
		const counts = Array.from({ length: bins }, (_, i) => {
			const lo = mn + i * step, hi = lo + step;
			return { lo, count: vals.filter(v => v >= lo && (i === bins - 1 ? v <= hi : v < hi)).length };
		});
		const maxCount = Math.max(...counts.map(c => c.count), 1);
		const W = 400, H = 72, PAD = 8, barW = Math.floor((W - PAD * 2) / bins) - 1;
		const avg = (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1);
		const pos = vals.filter(v => v >= 0).length;
		return { counts, maxCount, W, H, PAD, barW, mn: mn.toFixed(0), mx: mx.toFixed(0), avg, total: vals.length, pct: ((pos / vals.length) * 100).toFixed(0) };
	});

	const runTopStrategyByWinRate = $derived.by(() => {
		const map = new Map<string, { wins: number; total: number; profits: number[] }>();
		for (const r of runs) {
			if (!r.strategy || r.win_rate_pct == null || !isFinite(r.win_rate_pct)) continue;
			if (!map.has(r.strategy)) map.set(r.strategy, { wins: 0, total: 0, profits: [] });
			const e = map.get(r.strategy)!;
			e.wins += r.win_rate_pct / 100;
			e.total++;
			if (r.total_profit_pct != null && isFinite(r.total_profit_pct)) e.profits.push(r.total_profit_pct);
		}
		const rows = [...map.entries()]
			.filter(([, e]) => e.total >= 3)
			.map(([strat, e]) => ({
				strat: strat.slice(0, 18),
				wr: (e.wins / e.total) * 100,
				avgProfit: e.profits.length ? e.profits.reduce((a, v) => a + v, 0) / e.profits.length : 0,
				count: e.total
			}))
			.sort((a, b) => b.wr - a.wr)
			.slice(0, 12);
		if (rows.length < 3) return null;
		const maxWr = Math.max(...rows.map(r => r.wr), 0.01);
		return { rows, maxWr };
	});

	const runSharpeVsCalmarScatter = $derived.by(() => {
		const pts = runs
			.filter(r => r.sharpe != null && isFinite(r.sharpe) && r.calmar != null && isFinite(r.calmar) && r.calmar < 100 && r.sharpe < 50)
			.map(r => ({ sharpe: r.sharpe!, calmar: r.calmar!, profit: r.total_profit_pct ?? 0, strat: (r.strategy ?? '').slice(0, 10) }));
		if (pts.length < 5) return null;
		const sMin = Math.min(...pts.map(p => p.sharpe)), sMax = Math.max(...pts.map(p => p.sharpe), sMin + 0.1);
		const cMin = Math.min(...pts.map(p => p.calmar)), cMax = Math.max(...pts.map(p => p.calmar), cMin + 0.1);
		const W = 380, H = 105, PAD = 12;
		const toX = (v: number) => PAD + ((v - sMin) / (sMax - sMin)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - (v - cMin) / (cMax - cMin)) * (H - PAD * 2);
		const dots = pts.map(p => ({
			cx: toX(p.sharpe), cy: toY(p.calmar),
			color: p.profit >= 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'
		}));
		return { dots, W, H, PAD, sMin: sMin.toFixed(1), sMax: sMax.toFixed(1), cMin: cMin.toFixed(1), cMax: cMax.toFixed(1), count: pts.length };
	});

	const runProfitByPairCount = $derived.by(() => {
		const bins = [
			{ label: '1–5', min: 1, max: 5 },
			{ label: '6–10', min: 6, max: 10 },
			{ label: '11–20', min: 11, max: 20 },
			{ label: '21–50', min: 21, max: 50 },
			{ label: '51+', min: 51, max: Infinity }
		];
		const buckets = bins.map(b => ({ ...b, profits: [] as number[] }));
		for (const r of runs) {
			if (r.total_profit_pct == null || !isFinite(r.total_profit_pct)) continue;
			const pc = r.num_pairs ?? 0;
			const b = buckets.find(b => pc >= b.min && pc <= b.max);
			if (b) b.profits.push(r.total_profit_pct);
		}
		const rows = buckets.filter(b => b.profits.length >= 2).map(b => ({
			label: b.label,
			avg: b.profits.reduce((a, v) => a + v, 0) / b.profits.length,
			count: b.profits.length
		}));
		if (rows.length < 2) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 300, H = 75, PAD = 10, barW = Math.floor((W - PAD * 2) / rows.length) - 4, midY = H / 2;
		return { rows, maxAbs, W, H, PAD, barW, midY };
	});

	const runCalmarByFactorCount = $derived.by(() => {
		const bins = [
			{ label: '0', min: 0, max: 0 },
			{ label: '1', min: 1, max: 1 },
			{ label: '2', min: 2, max: 2 },
			{ label: '3', min: 3, max: 3 },
			{ label: '4+', min: 4, max: Infinity }
		];
		const buckets = bins.map(b => ({ ...b, calmars: [] as number[] }));
		for (const r of runs) {
			if (r.calmar == null || !isFinite(r.calmar) || r.calmar > 50) continue;
			const fc = r.factors?.length ?? 0;
			const b = buckets.find(b => fc >= b.min && fc <= b.max);
			if (b) b.calmars.push(r.calmar);
		}
		const rows = buckets.filter(b => b.calmars.length >= 3).map(b => ({
			label: b.label,
			avg: b.calmars.reduce((a, v) => a + v, 0) / b.calmars.length,
			count: b.calmars.length
		}));
		if (rows.length < 2) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 280, H = 70, PAD = 8, barW = Math.floor((W - PAD * 2) / rows.length) - 3, midY = H / 2;
		return { rows, maxAbs, W, H, PAD, barW, midY };
	});

	const runWinRateVsProfitFactor = $derived.by(() => {
		const pts = runs.filter(r =>
			r.win_rate != null && isFinite(r.win_rate) &&
			r.profit_factor != null && isFinite(r.profit_factor) && r.profit_factor < 20 &&
			r.total_profit_pct != null && isFinite(r.total_profit_pct)
		).map(r => ({ wr: r.win_rate! * 100, pf: r.profit_factor!, profit: r.total_profit_pct! }));
		if (pts.length < 8) return null;
		const wrMin = Math.min(...pts.map(p => p.wr)), wrMax = Math.max(...pts.map(p => p.wr), wrMin + 0.1);
		const pfMin = Math.min(...pts.map(p => p.pf)), pfMax = Math.max(...pts.map(p => p.pf), pfMin + 0.1);
		const W = 360, H = 95, PAD = 10;
		const toX = (v: number) => PAD + ((v - wrMin) / (wrMax - wrMin)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - (v - pfMin) / (pfMax - pfMin)) * (H - PAD * 2);
		const dots = pts.map(p => ({ cx: toX(p.wr), cy: toY(p.pf), color: p.profit >= 10 ? 'var(--ch-profit-light)' : p.profit >= 0 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)' }));
		return { dots, W, H, PAD, wrMin: wrMin.toFixed(0), wrMax: wrMax.toFixed(0), pfMin: pfMin.toFixed(1), pfMax: pfMax.toFixed(1), count: pts.length };
	});

	const runProfitDecileChart = $derived.by(() => {
		const profits = runs.filter(r => r.total_profit_pct != null && isFinite(r.total_profit_pct)).map(r => r.total_profit_pct!).sort((a, b) => a - b);
		if (profits.length < 10) return null;
		const percentile = (p: number) => { const idx = Math.floor((p / 100) * (profits.length - 1)); return profits[idx]; };
		const deciles = [10, 20, 30, 40, 50, 60, 70, 80, 90].map(p => ({ p, val: percentile(p) }));
		const mn = deciles[0].val, mx = deciles[deciles.length - 1].val;
		const range = Math.max(mx - mn, 0.01);
		const W = 300, H = 60, PAD = 10, barW = Math.floor((W - PAD * 2) / deciles.length) - 2;
		const midY = PAD + (mx / (mx - mn + 0.001)) * (H - PAD * 2);
		const zero = mn <= 0 && mx >= 0 ? PAD + (mx / range) * (H - PAD * 2) : mn > 0 ? H - PAD : PAD;
		return { deciles, mn, mx, range, W, H, PAD, barW, zero, count: profits.length };
	});

	const runSharpeByTimeframe = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.timeframe || r.sharpe_ratio == null || !isFinite(r.sharpe_ratio) || Math.abs(r.sharpe_ratio) > 100) continue;
			if (!map.has(r.timeframe)) map.set(r.timeframe, []);
			map.get(r.timeframe)!.push(r.sharpe_ratio);
		}
		const TF_ORDER = ['5m','15m','30m','1h','2h','4h','8h','1d'];
		const rows = TF_ORDER
			.filter(tf => (map.get(tf)?.length ?? 0) >= 3)
			.map(tf => {
				const vals = map.get(tf)!;
				const avg = vals.reduce((a, v) => a + v, 0) / vals.length;
				return { tf, avg, count: vals.length };
			});
		if (rows.length < 2) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 320, H = 72, PAD = 8, barW = Math.floor((W - PAD * 2) / rows.length) - 3, midY = H / 2;
		return { rows, maxAbs, W, H, PAD, barW, midY };
	});

	const runTopStrategyMonthlyTrend = $derived.by(() => {
		const stratTotals = new Map<string, number>();
		for (const r of runs) {
			if (r.strategy && r.total_profit_pct != null && isFinite(r.total_profit_pct))
				stratTotals.set(r.strategy, (stratTotals.get(r.strategy) ?? 0) + r.total_profit_pct);
		}
		const top3 = [...stratTotals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([s]) => s);
		if (top3.length < 2) return null;
		const sColors = ['var(--ch-profit-strong)', 'var(--ch-violet-strong)', 'var(--ch-warn)'];
		const stratMonths = new Map<string, Map<string, number[]>>();
		for (const r of runs) {
			if (!r.strategy || !top3.includes(r.strategy) || !r.imported_at || r.total_profit_pct == null) continue;
			const mo = r.imported_at.slice(0, 7);
			if (!stratMonths.has(r.strategy)) stratMonths.set(r.strategy, new Map());
			if (!stratMonths.get(r.strategy)!.has(mo)) stratMonths.get(r.strategy)!.set(mo, []);
			stratMonths.get(r.strategy)!.get(mo)!.push(r.total_profit_pct);
		}
		const allMonths = [...new Set([...stratMonths.values()].flatMap(m => [...m.keys()]))].sort();
		if (allMonths.length < 3) return null;
		const W = 360, H = 80, PAD = 10;
		const toX = (i: number) => PAD + (i / Math.max(allMonths.length - 1, 1)) * (W - PAD * 2);
		const lines = top3.map((strat, si) => {
			const pts = allMonths.map((mo, i) => {
				const vals = stratMonths.get(strat)?.get(mo) ?? [];
				return vals.length ? { i, avg: vals.reduce((a, v) => a + v, 0) / vals.length } : null;
			}).filter(Boolean) as { i: number; avg: number }[];
			return { strat: strat.slice(0, 14), color: sColors[si], pts };
		}).filter(l => l.pts.length >= 2);
		if (lines.length < 2) return null;
		const allAvgs = lines.flatMap(l => l.pts.map(p => p.avg));
		const mn = Math.min(...allAvgs), mx = Math.max(...allAvgs, mn + 0.1);
		const toY = (v: number) => PAD + (1 - (v - mn) / (mx - mn)) * (H - PAD * 2);
		const zeroY = Math.max(PAD, Math.min(H - PAD, toY(0)));
		const polylines = lines.map(l => ({ ...l, poly: l.pts.map(p => `${toX(p.i).toFixed(1)},${toY(p.avg).toFixed(1)}`).join(' ') }));
		return { polylines, allMonths, W, H, PAD, zeroY };
	});

	const runSortinoVsCalmarScatter = $derived.by(() => {
		const pts = data.runs.filter(r =>
			r.sortino != null && isFinite(r.sortino) && Math.abs(r.sortino) < 80 &&
			r.calmar != null && isFinite(r.calmar) && Math.abs(r.calmar) < 200 &&
			r.total_profit_pct != null && isFinite(r.total_profit_pct)
		).map(r => ({ sortino: r.sortino!, calmar: r.calmar!, profit: r.total_profit_pct! }));
		if (pts.length < 8) return null;
		const soMin = Math.min(...pts.map(p => p.sortino)), soMax = Math.max(...pts.map(p => p.sortino), soMin + 0.1);
		const cMin = Math.min(...pts.map(p => p.calmar)), cMax = Math.max(...pts.map(p => p.calmar), cMin + 0.1);
		const W = 360, H = 92, PAD = 12;
		const toX = (v: number) => PAD + ((v - soMin) / (soMax - soMin)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - (v - cMin) / (cMax - cMin)) * (H - PAD * 2);
		const zeroX = Math.max(PAD, Math.min(W - PAD, toX(0)));
		const zeroY = Math.max(PAD, Math.min(H - PAD, toY(0)));
		const dots = pts.map(p => ({
			cx: toX(p.sortino), cy: toY(p.calmar),
			color: p.profit >= 10 ? 'var(--ch-profit-light)' : p.profit >= 0 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)',
		}));
		return { dots, W, H, PAD, zeroX, zeroY, soMin: soMin.toFixed(1), soMax: soMax.toFixed(1), cMin: cMin.toFixed(1), cMax: cMax.toFixed(1), count: pts.length };
	});

	const runMaxDrawdownByTimeframe = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of data.runs) {
			if (!r.timeframe || r.max_drawdown == null || !isFinite(r.max_drawdown)) continue;
			const arr = map.get(r.timeframe) ?? [];
			arr.push(Math.abs(r.max_drawdown));
			map.set(r.timeframe, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()].map(([tf, vals]) => ({
			tf,
			avg: vals.reduce((a, v) => a + v, 0) / vals.length,
			count: vals.length,
		})).sort((a, b) => b.avg - a.avg);
		const maxVal = Math.max(...rows.map(r => r.avg), 0.01);
		const W = 300, H = rows.length * 18 + 8, PAD = 8, barMaxW = W - 70;
		return { rows, maxVal, W, H, PAD, barMaxW };
	});

	const runProfitByFactorCount = $derived.by(() => {
		const buckets = new Map<number, number[]>();
		for (const r of data.runs) {
			if (r.total_profit_pct == null || !isFinite(r.total_profit_pct)) continue;
			const fc = Array.isArray(r.factors) ? r.factors.length : (r.factor_count ?? 0);
			if (fc <= 0 || fc > 20) continue;
			const arr = buckets.get(fc) ?? [];
			arr.push(r.total_profit_pct);
			buckets.set(fc, arr);
		}
		if (buckets.size < 3) return null;
		const rows = [...buckets.entries()].sort((a, b) => a[0] - b[0]).map(([fc, profits]) => ({
			fc,
			avg: profits.reduce((a, v) => a + v, 0) / profits.length,
			count: profits.length,
		}));
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 340, H = 72, PAD = 10, barW = Math.max(4, Math.floor((W - PAD * 2) / rows.length) - 3), midY = H / 2;
		return { rows, maxAbs, W, H, PAD, barW, midY };
	});

	const runWinRateHistogram = $derived.by(() => {
		const vals = data.runs.filter(r => r.win_rate_pct != null && isFinite(r.win_rate_pct) && r.win_rate_pct >= 0 && r.win_rate_pct <= 100)
			.map(r => r.win_rate_pct!);
		if (vals.length < 8) return null;
		const bins = 14;
		const binSize = 100 / bins;
		const buckets = Array.from({ length: bins }, (_, i) => ({ lo: i * binSize, count: 0 }));
		for (const v of vals) {
			const bi = Math.min(bins - 1, Math.floor(v / binSize));
			buckets[bi].count++;
		}
		const maxC = Math.max(...buckets.map(b => b.count), 1);
		const W = 360, H = 68, PAD = 10;
		const bw = (W - PAD * 2) / bins - 1;
		const x50 = PAD + (50 / 100) * (W - PAD * 2);
		const bars = buckets.map((b, i) => ({
			x: PAD + i * ((W - PAD * 2) / bins),
			h: Math.max(2, (b.count / maxC) * (H - PAD - 14)),
			color: b.lo >= 50 ? 'var(--ch-profit)' : 'var(--ch-loss-light)',
		}));
		return { bars, bw, W, H, PAD, x50, total: vals.length };
	});

	const runTopStrategyBySharpe = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of data.runs) {
			if (!r.strategy || r.sharpe_ratio == null || !isFinite(r.sharpe_ratio) || Math.abs(r.sharpe_ratio) > 200) continue;
			const arr = map.get(r.strategy) ?? [];
			arr.push(r.sharpe_ratio);
			map.set(r.strategy, arr);
		}
		if (map.size < 3) return null;
		const rows = [...map.entries()].map(([strat, vals]) => ({
			strat: strat.slice(0, 18), best: Math.max(...vals), count: vals.length,
		})).sort((a, b) => b.best - a.best).slice(0, 8);
		const maxVal = Math.max(...rows.map(r => r.best), 0.01);
		const W = 340, H = rows.length * 16 + 6, PAD = 8, barMaxW = W - 100;
		return { rows, maxVal, W, H, PAD, barMaxW };
	});

	const runCalmarVsDrawdownScatter = $derived.by(() => {
		const pts = data.runs.filter(r =>
			r.calmar != null && isFinite(r.calmar) && Math.abs(r.calmar) < 500 &&
			r.max_drawdown_pct != null && isFinite(r.max_drawdown_pct) && r.max_drawdown_pct >= 0
		).map(r => ({ calmar: r.calmar!, dd: r.max_drawdown_pct!, tf: r.timeframe ?? '' }));
		if (pts.length < 5) return null;
		const calMin = Math.min(...pts.map(p => p.calmar)), calMax = Math.max(...pts.map(p => p.calmar), calMin + 0.1);
		const ddMax = Math.max(...pts.map(p => p.dd), 0.1);
		const W = 360, H = 90, PAD = 12;
		const toX = (v: number) => PAD + ((v - calMin) / (calMax - calMin)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (v / ddMax) * (H - PAD * 2);
		const zeroX = Math.max(PAD, Math.min(W - PAD, toX(0)));
		const dots = pts.map(p => ({
			cx: toX(p.calmar), cy: toY(p.dd),
			color: p.calmar >= 2 ? 'var(--ch-profit-light)' : p.calmar >= 0 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)',
		}));
		return { dots, W, H, PAD, zeroX, calMin: calMin.toFixed(1), calMax: calMax.toFixed(1), ddMax: ddMax.toFixed(1) };
	});

	const runMonthlyProfitByTF = $derived.by(() => {
		const tfs = [...new Set(data.runs.filter(r => r.timeframe).map(r => r.timeframe!))].sort();
		const months = [...new Set(data.runs.filter(r => r.created_at).map(r => r.created_at!.slice(0, 7)))].sort().slice(-8);
		if (tfs.length < 2 || months.length < 2) return null;
		const grid = tfs.map(tf => months.map(mo => {
			const vals = data.runs.filter(r => r.timeframe === tf && r.created_at?.startsWith(mo) && r.profit_pct != null && isFinite(r.profit_pct)).map(r => r.profit_pct!);
			return vals.length ? vals.reduce((a, v) => a + v, 0) / vals.length : null;
		}));
		const allVals = grid.flat().filter((v): v is number => v !== null);
		if (allVals.length < 4) return null;
		const maxAbs = Math.max(...allVals.map(v => Math.abs(v)), 0.01);
		const CW = 36, CH = 14, PAD = 30;
		const W = PAD + months.length * CW + 4, H = PAD + tfs.length * CH + 4;
		return { grid, tfs, months: months.map(m => m.slice(5)), CW, CH, PAD, W, H, maxAbs };
	});

	const runSortinoMonthlyTrend = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of data.runs) {
			if (!r.created_at || r.sortino == null || !isFinite(r.sortino) || Math.abs(r.sortino) > 200) continue;
			const mo = r.created_at.slice(0, 7);
			const arr = map.get(mo) ?? [];
			arr.push(r.sortino);
			map.set(mo, arr);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const pts = months.map(m => ({ m: m.slice(5), avg: map.get(m)!.reduce((a, v) => a + v, 0) / map.get(m)!.length }));
		const minV = Math.min(...pts.map(p => p.avg));
		const maxV = Math.max(...pts.map(p => p.avg));
		const range = maxV - minV || 1;
		const W = 360, H = 64, PAD = 10;
		const toX = (i: number) => PAD + (i / (pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => PAD + ((maxV - v) / range) * (H - PAD * 2);
		const polyline = pts.map((p, i) => `${toX(i)},${toY(p.avg)}`).join(' ');
		const zeroY = Math.max(PAD, Math.min(H - PAD, toY(0)));
		const area = `${toX(0)},${zeroY} ` + pts.map((p, i) => `${toX(i)},${toY(p.avg)}`).join(' ') + ` ${toX(pts.length - 1)},${zeroY}`;
		const last = pts[pts.length - 1].avg;
		const color = last >= 1 ? 'var(--ch-profit-strong)' : last >= 0 ? 'var(--ch-warn)' : 'var(--ch-loss-strong)';
		return { polyline, area, W, H, PAD, color, fillColor: last >= 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)', zeroY, firstMo: pts[0].m, lastMo: pts[pts.length - 1].m, last: last.toFixed(2) };
	});

	const runProfitFactorMonthlyTrend = $derived.by(() => {
		if (!runs || runs.length < 6) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.run_date || !r.profit_factor) continue;
			const mo = (r.run_date as string).slice(0, 7);
			const arr = map.get(mo) ?? [];
			arr.push(r.profit_factor as number);
			map.set(mo, arr);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const pts = months.map(m => { const arr = map.get(m)!; return { m: m.slice(5), avg: arr.reduce((a, v) => a + v, 0) / arr.length }; });
		const maxV = Math.max(...pts.map(p => p.avg), 1);
		const minV = Math.min(...pts.map(p => p.avg), 0);
		const range = maxV - minV || 0.01;
		const W = 380, H = 68, PAD = 10;
		const toX = (i: number) => PAD + (i / (pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => PAD + ((maxV - v) / range) * (H - PAD * 2);
		const oneY = toY(1);
		const polyline = pts.map((p, i) => `${toX(i)},${toY(p.avg)}`).join(' ');
		const last = pts[pts.length - 1].avg;
		const color = last >= 1.5 ? 'var(--ch-profit-strong)' : last >= 1 ? 'var(--ch-warn)' : 'var(--ch-loss-strong)';
		return { pts, polyline, W, H, PAD, toX, toY, oneY, color, last: last.toFixed(2), firstMo: pts[0].m, lastMo: pts[pts.length - 1].m };
	});

	const runWinRateVsSharpeScatter = $derived.by(() => {
		if (!runs || runs.length < 8) return null;
		const pts = runs
			.filter(r => r.win_rate != null && r.sharpe_ratio != null)
			.map(r => ({ wr: (r.win_rate as number) * 100, sh: r.sharpe_ratio as number, profit: r.profit_total_pct as number ?? 0 }));
		if (pts.length < 6) return null;
		const shMax = Math.max(...pts.map(p => p.sh), 1);
		const shMin = Math.min(...pts.map(p => p.sh), 0);
		const range = shMax - shMin || 0.01;
		const W = 320, H = 110, PAD = 14;
		const toX = (wr: number) => PAD + (wr / 100) * (W - PAD * 2);
		const toY = (sh: number) => H - PAD - ((sh - shMin) / range) * (H - PAD * 2);
		const zeroY = toY(0);
		return { pts, W, H, PAD, toX, toY, zeroY, shMax: shMax.toFixed(2), shMin: shMin.toFixed(2) };
	});

	const runDrawdownVsProfitScatter = $derived.by(() => {
		if (!runs || runs.length < 8) return null;
		const pts = runs
			.filter(r => r.max_drawdown_pct != null && r.profit_total_pct != null)
			.map(r => ({ dd: r.max_drawdown_pct as number, profit: r.profit_total_pct as number, tf: r.timeframe as string ?? '' }));
		if (pts.length < 6) return null;
		const ddMax = Math.max(...pts.map(p => p.dd), 0.01);
		const profMin = Math.min(...pts.map(p => p.profit), 0);
		const profMax = Math.max(...pts.map(p => p.profit), 0.01);
		const range = profMax - profMin || 0.01;
		const W = 320, H = 110, PAD = 14;
		const toX = (dd: number) => PAD + (dd / ddMax) * (W - PAD * 2);
		const toY = (p: number) => H - PAD - ((p - profMin) / range) * (H - PAD * 2);
		const zeroY = toY(0);
		return { pts, W, H, PAD, toX, toY, zeroY, ddMax: ddMax.toFixed(1), profMax: profMax.toFixed(1), profMin: profMin.toFixed(1) };
	});

	const runTradeCountVsProfitScatter = $derived.by(() => {
		if (!runs || runs.length < 8) return null;
		const pts = runs
			.filter(r => r.total_trades != null && r.profit_total_pct != null && (r.total_trades as number) > 0)
			.map(r => ({ tc: r.total_trades as number, profit: r.profit_total_pct as number, tf: (r.timeframe as string) ?? '' }));
		if (pts.length < 6) return null;
		const tcMax = Math.max(...pts.map(p => p.tc), 1);
		const profMin = Math.min(...pts.map(p => p.profit), 0);
		const profMax = Math.max(...pts.map(p => p.profit), 0.01);
		const range = profMax - profMin || 0.01;
		const W = 320, H = 100, PAD = 12;
		const toX = (tc: number) => PAD + (tc / tcMax) * (W - PAD * 2);
		const toY = (p: number) => H - PAD - ((p - profMin) / range) * (H - PAD * 2);
		const zeroY = toY(0);
		return { pts, W, H, PAD, toX, toY, zeroY, tcMax, profMax: profMax.toFixed(1), profMin: profMin.toFixed(1) };
	});

	const runAvgProfitByPairCount = $derived.by(() => {
		if (!runs || runs.length < 6) return null;
		const map = new Map<number, number[]>();
		for (const r of runs) {
			if (r.paircount == null || r.profit_total_pct == null) continue;
			const pc = r.paircount as number;
			const bucket = Math.round(pc / 5) * 5;
			const arr = map.get(bucket) ?? [];
			arr.push(r.profit_total_pct as number);
			map.set(bucket, arr);
		}
		if (map.size < 3) return null;
		const buckets = [...map.keys()].sort((a, b) => a - b);
		const rows = buckets.map(b => { const arr = map.get(b)!; return { b, avg: arr.reduce((a, v) => a + v, 0) / arr.length }; });
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 320, H = 80, PAD = 10;
		const barW = (W - PAD * 2) / rows.length;
		const midY = H / 2;
		return { rows, maxAbs, W, H, PAD, barW, midY };
	});

	const runSortinoRanking = $derived.by(() => {
		if (!runs || runs.length < 6) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.strategy_name || r.sortino_ratio == null) continue;
			const arr = map.get(r.strategy_name as string) ?? [];
			arr.push(r.sortino_ratio as number);
			map.set(r.strategy_name as string, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([name, vals]) => ({ name: name.slice(0, 18), avg: vals.reduce((a, v) => a + v, 0) / vals.length }))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 10);
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 340, H = rows.length * 16 + 6, PAD = 8, barMaxW = W - 110;
		const zeroX = PAD + (barMaxW / 2);
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const runProfitByMonth = $derived.by(() => {
		if (!runs || runs.length < 6) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.created_at || r.profit_total_pct == null) continue;
			const mo = (r.created_at as string).slice(0, 7);
			const arr = map.get(mo) ?? [];
			arr.push(r.profit_total_pct as number);
			map.set(mo, arr);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const pts = months.map(m => { const arr = map.get(m)!; return { m: m.slice(5), avg: arr.reduce((a, v) => a + v, 0) / arr.length }; });
		const maxAbs = Math.max(...pts.map(p => Math.abs(p.avg)), 0.01);
		const W = 340, H = 72, PAD = 8;
		const bw = (W - PAD * 2) / pts.length - 1;
		const midY = H / 2;
		return { pts, maxAbs, W, H, PAD, bw, midY };
	});

	const runSortinoByPairCount = $derived.by(() => {
		if (!runs || runs.length < 8) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (r.nb_trades == null || r.sortino == null) continue;
			const bucket = `${Math.floor((r.nb_trades as number) / 5) * 5}+`;
			const arr = map.get(bucket) ?? [];
			arr.push(r.sortino as number);
			map.set(bucket, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([bucket, vals]) => ({ bucket, avg: vals.reduce((a, v) => a + v, 0) / vals.length }))
			.sort((a, b) => parseInt(a.bucket) - parseInt(b.bucket));
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 340, H = rows.length * 20 + 6, PAD = 8, barMaxW = W - 50;
		const zeroX = PAD + barMaxW / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const runProfitByDow = $derived.by(() => {
		if (!runs || runs.length < 10) return null;
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const buckets: number[][] = Array.from({ length: 7 }, () => []);
		for (const r of runs) {
			if (!r.created_at || r.profit_total_pct == null) continue;
			const dow = new Date(r.created_at as string).getDay();
			buckets[dow].push(r.profit_total_pct as number);
		}
		const pts = DAYS.map((d, i) => ({
			d,
			avg: buckets[i].length ? buckets[i].reduce((a, v) => a + v, 0) / buckets[i].length : 0,
			n: buckets[i].length
		}));
		const maxAbs = Math.max(...pts.map(p => Math.abs(p.avg)), 0.01);
		const W = 340, H = 64, PAD = 8;
		const bw = (W - PAD * 2) / 7 - 2;
		const midY = H / 2;
		return { pts, maxAbs, W, H, PAD, bw, midY };
	});

	const runCalmarByStrategy = $derived.by(() => {
		if (!runs || runs.length < 6) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.strategy_name || r.calmar_ratio == null) continue;
			const arr = map.get(r.strategy_name as string) ?? [];
			arr.push(r.calmar_ratio as number);
			map.set(r.strategy_name as string, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([name, vals]) => ({ name: name.slice(0, 16), avg: vals.reduce((a, v) => a + v, 0) / vals.length }))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 10);
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 340, H = rows.length * 18 + 6, PAD = 8, barMaxW = W - 110;
		const zeroX = PAD + barMaxW / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const runProfitByTFMonth = $derived.by(() => {
		if (!runs || runs.length < 10) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.timeframe || !r.created_at || r.profit_total_pct == null) continue;
			const key = `${r.timeframe}|${(r.created_at as string).slice(0, 7)}`;
			const arr = map.get(key) ?? [];
			arr.push(r.profit_total_pct as number);
			map.set(key, arr);
		}
		if (map.size < 4) return null;
		const tfs = [...new Set([...map.keys()].map(k => k.split('|')[0]))].sort();
		const months = [...new Set([...map.keys()].map(k => k.split('|')[1]))].sort().slice(-6);
		if (tfs.length < 2 || months.length < 2) return null;
		const cellW = 36, cellH = 18, PAD = 4;
		const W = PAD + (months.length + 1) * cellW + PAD;
		const H = PAD + (tfs.length + 1) * cellH + PAD;
		const cells: { x: number; y: number; avg: number; label: string }[] = [];
		let maxAbs = 0.01;
		for (let ti = 0; ti < tfs.length; ti++) {
			for (let mi = 0; mi < months.length; mi++) {
				const key = `${tfs[ti]}|${months[mi]}`;
				const arr = map.get(key);
				const avg = arr ? arr.reduce((a, v) => a + v, 0) / arr.length : 0;
				maxAbs = Math.max(maxAbs, Math.abs(avg));
				cells.push({ x: PAD + (mi + 1) * cellW, y: PAD + (ti + 1) * cellH, avg, label: avg.toFixed(1) });
			}
		}
		return { cells, tfs, months, cellW, cellH, PAD, W, H, maxAbs };
	});

	const runSharpeVsDrawdownRatio = $derived.by(() => {
		if (!runs || runs.length < 10) return null;
		const pts = runs
			.filter(r => r.sharpe_ratio != null && r.max_drawdown_pct != null && (r.max_drawdown_pct as number) > 0)
			.map(r => ({ x: r.sharpe_ratio as number, y: (r.sharpe_ratio as number) / (r.max_drawdown_pct as number), profit: r.profit_total_pct as number ?? 0 }));
		if (pts.length < 8) return null;
		const xMin = Math.min(...pts.map(p => p.x));
		const xMax = Math.max(...pts.map(p => p.x), 0.01);
		const yMin = Math.min(...pts.map(p => p.y));
		const yMax = Math.max(...pts.map(p => p.y), 0.01);
		const xRange = xMax - xMin || 0.01;
		const yRange = yMax - yMin || 0.01;
		const W = 340, H = 80, PAD = 10;
		const toX = (v: number) => PAD + ((v - xMin) / xRange) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - yMin) / yRange) * (H - PAD * 2);
		const zeroX = toX(0);
		return { pts, W, H, PAD, toX, toY, zeroX };
	});

	const runTopPairsByWinRate = $derived.by(() => {
		if (!runs || runs.length < 6) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.strategy_name || r.win_rate == null) continue;
			const arr = map.get(r.strategy_name as string) ?? [];
			arr.push((r.win_rate as number) * 100);
			map.set(r.strategy_name as string, arr);
		}
		if (map.size < 3) return null;
		const rows = [...map.entries()]
			.map(([name, vals]) => ({ name: name.slice(0, 16), avg: vals.reduce((a, v) => a + v, 0) / vals.length }))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 8);
		const maxWR = Math.max(...rows.map(r => r.avg), 1);
		const W = 340, H = rows.length * 18 + 6, PAD = 8, barMaxW = W - 110;
		return { rows, maxWR, W, H, PAD, barMaxW };
	});

	const runProfitVsTradeCountScatter = $derived.by(() => {
		if (!runs || runs.length < 8) return null;
		const pts = runs
			.filter(r => r.profit_total_pct != null && r.trade_count != null)
			.map(r => ({ p: r.profit_total_pct as number, tc: r.trade_count as number }));
		if (pts.length < 6) return null;
		const minP = Math.min(...pts.map(p => p.p)), maxP = Math.max(...pts.map(p => p.p), minP + 0.1);
		const minTC = Math.min(...pts.map(p => p.tc)), maxTC = Math.max(...pts.map(p => p.tc), minTC + 1);
		const W = 340, H = 80, PAD = 10;
		const toX = (v: number) => PAD + ((v - minP) / (maxP - minP)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - (v - minTC) / (maxTC - minTC)) * (H - PAD * 2);
		const zeroX = toX(0);
		return { pts, toX, toY, zeroX, W, H, PAD, minP: minP.toFixed(1), maxP: maxP.toFixed(1) };
	});

	const runSortinoCDF = $derived.by(() => {
		if (!runs || runs.length < 10) return null;
		const vals = runs.filter(r => r.sortino_ratio != null).map(r => r.sortino_ratio as number).sort((a, b) => a - b);
		if (vals.length < 8) return null;
		const minV = vals[0], maxV = vals[vals.length - 1];
		if (maxV === minV) return null;
		const W = 340, H = 70, PAD = 10;
		const toX = (v: number) => PAD + ((v - minV) / (maxV - minV)) * (W - PAD * 2);
		const toY = (i: number) => H - PAD - (i / (vals.length - 1)) * (H - PAD * 2);
		const pts = vals.map((v, i) => `${toX(v).toFixed(1)},${toY(i).toFixed(1)}`).join(' ');
		const zeroX = toX(0);
		const median = vals[Math.floor(vals.length / 2)].toFixed(2);
		return { pts, zeroX, W, H, PAD, minV: minV.toFixed(2), maxV: maxV.toFixed(2), median };
	});

	const runMonthlyAvgProfitBars = $derived.by(() => {
		if (!runs || runs.length < 5) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.created_at || r.profit_total_pct == null) continue;
			const mo = (r.created_at as string).slice(0, 7);
			const arr = map.get(mo) ?? [];
			arr.push(r.profit_total_pct as number);
			map.set(mo, arr);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort().slice(-10);
		const avgs = months.map(m => { const a = map.get(m)!; return a.reduce((s, v) => s + v, 0) / a.length; });
		const maxAbs = Math.max(...avgs.map(v => Math.abs(v)), 0.01);
		const W = 340, H = 64, PAD = 8, bw = (W - PAD * 2) / months.length - 1;
		const midY = H / 2;
		return { months, avgs, maxAbs, W, H, PAD, bw, midY };
	});

	const runCalmarVsWinRateScatter = $derived.by(() => {
		if (!runs || runs.length < 8) return null;
		const pts = runs
			.filter(r => r.calmar_ratio != null && r.win_rate != null)
			.map(r => ({ calmar: r.calmar_ratio as number, wr: (r.win_rate as number) * 100 }));
		if (pts.length < 6) return null;
		const minC = Math.min(...pts.map(p => p.calmar)), maxC = Math.max(...pts.map(p => p.calmar), minC + 0.1);
		const minWR = Math.min(...pts.map(p => p.wr)), maxWR = Math.max(...pts.map(p => p.wr), minWR + 1);
		const W = 340, H = 80, PAD = 10;
		const toX = (v: number) => PAD + ((v - minC) / (maxC - minC)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - (v - minWR) / (maxWR - minWR)) * (H - PAD * 2);
		const zeroX = toX(0);
		return { pts, toX, toY, zeroX, W, H, PAD, minC: minC.toFixed(2), maxC: maxC.toFixed(2) };
	});

	const runProfitBySortinoBucket = $derived.by(() => {
		if (!runs || runs.length < 8) return null;
		const buckets = new Map<string, number[]>([['<0', []], ['0-1', []], ['1-2', []], ['>2', []]]);
		for (const r of runs) {
			if (r.sortino_ratio == null || r.profit_total_pct == null) continue;
			const s = r.sortino_ratio as number;
			const key = s < 0 ? '<0' : s < 1 ? '0-1' : s < 2 ? '1-2' : '>2';
			buckets.get(key)!.push(r.profit_total_pct as number);
		}
		const ORDER = ['<0', '0-1', '1-2', '>2'];
		const rows = ORDER.filter(k => (buckets.get(k)?.length ?? 0) >= 2).map(k => {
			const arr = buckets.get(k)!;
			return { k, avg: arr.reduce((s, v) => s + v, 0) / arr.length };
		});
		if (rows.length < 2) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 280, H = rows.length * 22 + 8, PAD = 8, barMaxW = W - 50;
		const zeroX = PAD + 30 + barMaxW / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const runStrategyWinRateRanking = $derived.by(() => {
		if (!runs || runs.length < 5) return null;
		const map = new Map<string, { wins: number; total: number }>();
		for (const r of runs) {
			if (!r.strategy || r.win_rate == null) continue;
			const name = r.strategy as string;
			const s = map.get(name) ?? { wins: 0, total: 0 };
			s.total++;
			if ((r.win_rate as number) > 0.5) s.wins++;
			map.set(name, s);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.filter(([, s]) => s.total >= 2)
			.map(([name, s]) => ({ name: name.slice(0, 18), rate: s.wins / s.total * 100 }))
			.sort((a, b) => b.rate - a.rate)
			.slice(0, 8);
		if (rows.length < 2) return null;
		const W = 340, H = rows.length * 18 + 10, PAD = 8, barMaxW = W - PAD * 2 - 80;
		return { rows, W, H, PAD, barMaxW };
	});

	const runSharpeVsWinRateScatter = $derived.by(() => {
		if (!runs || runs.length < 8) return null;
		const pts = runs
			.filter(r => r.sharpe_ratio != null && r.win_rate != null)
			.map(r => ({ sharpe: r.sharpe_ratio as number, wr: (r.win_rate as number) * 100 }));
		if (pts.length < 6) return null;
		const minS = Math.min(...pts.map(p => p.sharpe)), maxS = Math.max(...pts.map(p => p.sharpe), minS + 0.1);
		const minWR = Math.min(...pts.map(p => p.wr)), maxWR = Math.max(...pts.map(p => p.wr), minWR + 1);
		const W = 320, H = 80, PAD = 10;
		const toX = (v: number) => PAD + ((v - minS) / (maxS - minS)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - (v - minWR) / (maxWR - minWR)) * (H - PAD * 2);
		const zeroX = toX(0);
		const zeroY = toY(50);
		return { pts, toX, toY, zeroX, zeroY, W, H, PAD, minS: minS.toFixed(1), maxS: maxS.toFixed(1) };
	});

	const runProfitByTFBars = $derived.by(() => {
		if (!runs || runs.length < 5) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.timeframe || r.profit_total_pct == null) continue;
			const arr = map.get(r.timeframe as string) ?? [];
			arr.push(r.profit_total_pct as number);
			map.set(r.timeframe as string, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.filter(([, arr]) => arr.length >= 2)
			.map(([tf, arr]) => ({ tf, avg: arr.reduce((s, v) => s + v, 0) / arr.length }))
			.sort((a, b) => b.avg - a.avg);
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 300, H = rows.length * 20 + 6, PAD = 8, barMaxW = W - PAD * 2 - 40;
		const zeroX = PAD + 30 + barMaxW / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const runCalmarCDF = $derived.by(() => {
		if (!runs || runs.length < 10) return null;
		const vals = runs
			.filter(r => r.calmar_ratio != null)
			.map(r => r.calmar_ratio as number)
			.sort((a, b) => a - b);
		if (vals.length < 10) return null;
		const minV = vals[0], maxV = vals[vals.length - 1];
		const W = 300, H = 70, PAD = 10;
		const points = vals.map((v, i) => {
			const x = PAD + ((v - minV) / Math.max(maxV - minV, 0.01)) * (W - PAD * 2);
			const y = H - PAD - ((i + 1) / vals.length) * (H - PAD * 2);
			return `${x.toFixed(1)},${y.toFixed(1)}`;
		});
		const median = vals[Math.floor(vals.length / 2)];
		return { polyline: points.join(' '), minV: minV.toFixed(2), maxV: maxV.toFixed(2), median: median.toFixed(2), W, H, PAD };
	});

	const runWinRateByTF = $derived.by(() => {
		if (!runs || runs.length < 5) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.timeframe || r.win_rate == null) continue;
			const arr = map.get(r.timeframe as string) ?? [];
			arr.push((r.win_rate as number) * 100);
			map.set(r.timeframe as string, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.filter(([, arr]) => arr.length >= 2)
			.map(([tf, arr]) => ({ tf, avg: arr.reduce((s, v) => s + v, 0) / arr.length }))
			.sort((a, b) => b.avg - a.avg);
		const maxV = Math.max(...rows.map(r => r.avg), 1);
		const W = 280, H = rows.length * 20 + 8, PAD = 8, barMaxW = W - PAD * 2 - 40;
		return { rows, maxV, W, H, PAD, barMaxW };
	});

	const runAvgDrawdownByStrategy = $derived.by(() => {
		if (!runs || runs.length < 5) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.strategy || r.max_drawdown_pct == null) continue;
			const arr = map.get(r.strategy as string) ?? [];
			arr.push(r.max_drawdown_pct as number);
			map.set(r.strategy as string, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.filter(([, arr]) => arr.length >= 2)
			.map(([name, arr]) => ({ name: (name as string).slice(0, 18), avg: arr.reduce((s, v) => s + v, 0) / arr.length }))
			.sort((a, b) => a.avg - b.avg)
			.slice(0, 8);
		const maxAvg = Math.max(...rows.map(r => r.avg), 1);
		const W = 300, H = rows.length * 20 + 8, PAD = 8, barMaxW = W - PAD * 2 - 90;
		return { rows, maxAvg, W, H, PAD, barMaxW };
	});

	const runWinRateSortinoCDF = $derived.by(() => {
		if (!runs || runs.length < 10) return null;
		const vals = runs
			.filter(r => r.sortino_ratio != null)
			.map(r => r.sortino_ratio as number)
			.sort((a, b) => a - b);
		if (vals.length < 10) return null;
		const minV = vals[0], maxV = vals[vals.length - 1];
		const W = 300, H = 70, PAD = 10;
		const points = vals.map((v, i) => {
			const x = PAD + ((v - minV) / Math.max(maxV - minV, 0.01)) * (W - PAD * 2);
			const y = H - PAD - ((i + 1) / vals.length) * (H - PAD * 2);
			return `${x.toFixed(1)},${y.toFixed(1)}`;
		});
		const median = vals[Math.floor(vals.length / 2)];
		return { polyline: points.join(' '), minV: minV.toFixed(2), maxV: maxV.toFixed(2), median: median.toFixed(2), W, H, PAD };
	});

	const runProfitByPairGroup = $derived.by(() => {
		if (!runs || runs.length < 10) return null;
		const byBase = new Map<string, number[]>();
		for (const r of runs) {
			if (r.pair == null || r.profit_ratio == null) continue;
			const base = (r.pair as string).split('/')[0] ?? 'OTHER';
			const arr = byBase.get(base) ?? [];
			arr.push((r.profit_ratio as number) * 100);
			byBase.set(base, arr);
		}
		if (byBase.size < 3) return null;
		const bars = [...byBase.entries()]
			.map(([base, arr]) => ({ base, avg: arr.reduce((s, v) => s + v, 0) / arr.length, n: arr.length }))
			.filter(b => b.n >= 3)
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 12);
		if (bars.length < 3) return null;
		const maxAbs = Math.max(...bars.map(b => Math.abs(b.avg)), 0.01);
		const W = 320, H = 80, PAD = 8, midY = H / 2;
		const bw = Math.max(5, (W - PAD * 2) / bars.length - 2);
		return { bars, maxAbs, W, H, PAD, midY, bw };
	});

	const runHoldTimeHistogram = $derived.by(() => {
		if (!runs || runs.length < 10) return null;
		const hrs = runs
			.filter(r => r.avg_duration_minutes != null)
			.map(r => (r.avg_duration_minutes as number) / 60);
		if (hrs.length < 8) return null;
		const maxH = Math.min(Math.max(...hrs), 168);
		const bins = 10;
		const binW = maxH / bins;
		const counts = Array(bins).fill(0);
		for (const h of hrs) {
			if (h > maxH) continue;
			const idx = Math.min(bins - 1, Math.floor(h / binW));
			counts[idx]++;
		}
		const maxCnt = Math.max(...counts, 1);
		const W = 320, H = 70, PAD = 8;
		const bw = (W - PAD * 2) / bins - 1;
		return { counts, maxCnt, bins, binW, W, H, PAD, bw };
	});

	const runAvgCalmarByStrategy = $derived.by(() => {
		if (!runs || runs.length < 10) return null;
		const byStrat = new Map<string, number[]>();
		for (const r of runs) {
			if (r.strategy == null || r.calmar_ratio == null) continue;
			const s = (r.strategy as string).slice(0, 14);
			const arr = byStrat.get(s) ?? [];
			arr.push(r.calmar_ratio as number);
			byStrat.set(s, arr);
		}
		if (byStrat.size < 2) return null;
		const bars = [...byStrat.entries()]
			.map(([s, arr]) => ({ s, avg: arr.reduce((a, v) => a + v, 0) / arr.length, n: arr.length }))
			.filter(b => b.n >= 2)
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 10);
		if (bars.length < 2) return null;
		const maxAbs = Math.max(...bars.map(b => Math.abs(b.avg)), 0.01);
		const W = 320, H = bars.length * 18 + 10, PAD = 8, midX = W / 2;
		const bh = 12;
		return { bars, maxAbs, W, H, PAD, midX, bh };
	});

	const runSharpeWinRateScatter2 = $derived.by(() => {
		if (!runs || runs.length < 10) return null;
		const pts = runs
			.filter(r => r.sharpe_ratio != null && r.win_rate != null)
			.map(r => ({
				x: (r.win_rate as number) * 100,
				y: r.sharpe_ratio as number,
				pf: r.profit_factor as number ?? 1
			}))
			.filter(p => p.x > 0 && p.x <= 100 && Math.abs(p.y) < 20);
		if (pts.length < 8) return null;
		const maxY = Math.max(...pts.map(p => Math.abs(p.y)), 0.01);
		const W = 320, H = 100, PAD = 12, midY = H / 2;
		return { pts, maxY, W, H, PAD, midY };
	});

	const runTopDrawdownByStrategy = $derived.by(() => {
		if (!runs || runs.length < 10) return null;
		const byStrat = new Map<string, number[]>();
		for (const r of runs) {
			if (r.strategy == null || r.max_drawdown == null) continue;
			const s = (r.strategy as string).slice(0, 14);
			const arr = byStrat.get(s) ?? [];
			arr.push((r.max_drawdown as number) * 100);
			byStrat.set(s, arr);
		}
		if (byStrat.size < 2) return null;
		const bars = [...byStrat.entries()]
			.map(([s, arr]) => ({ s, avg: arr.reduce((a, v) => a + v, 0) / arr.length, n: arr.length }))
			.filter(b => b.n >= 2)
			.sort((a, b) => a.avg - b.avg)
			.slice(0, 10);
		if (bars.length < 2) return null;
		const maxAvg = Math.max(...bars.map(b => b.avg), 1);
		const W = 320, H = bars.length * 18 + 10, PAD = 8, barMaxW = W - PAD * 2 - 70;
		return { bars, maxAvg, W, H, PAD, barMaxW };
	});

	const runProfitFactorByDow = $derived.by(() => {
		if (!runs || runs.length < 10) return null;
		const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const byDow = new Map<number, number[]>();
		for (const r of runs) {
			if (!r.start_date || r.profit_factor == null) continue;
			const d = new Date(r.start_date as string).getUTCDay();
			const arr = byDow.get(d) ?? [];
			arr.push(r.profit_factor as number);
			byDow.set(d, arr);
		}
		const bars = [0, 1, 2, 3, 4, 5, 6]
			.filter(d => byDow.has(d) && (byDow.get(d)?.length ?? 0) >= 2)
			.map(d => ({ label: DOW[d], avg: (byDow.get(d) ?? []).reduce((s, v) => s + v, 0) / (byDow.get(d)?.length ?? 1) }));
		if (bars.length < 3) return null;
		const maxAbs = Math.max(...bars.map(b => Math.abs(b.avg - 1)), 0.01);
		const W = 320, H = 70, PAD = 8, midY = H / 2;
		const bw = Math.max(8, (W - PAD * 2) / bars.length - 2);
		return { bars, maxAbs, W, H, PAD, midY, bw };
	});
</script>

<svelte:head>
	<title>{t(lang, 'signals.title')} · Crypto Quant</title>
</svelte:head>

<main class="mx-auto max-w-[1600px] px-4 sm:px-6 py-8">
	<!-- Page header -->
	<header class="mb-6">
		<h1 class="text-2xl font-semibold tracking-tight">{t(lang, 'signals.title')}</h1>
		<p class="mt-1 text-sm text-muted-foreground">{t(lang, 'signals.subtitle')}</p>
	</header>

	<!-- Stats bar -->
	{#if !isGated}
		<div class="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
			<div class="rounded-lg border border-border bg-card px-4 py-3">
				<div class="text-[11px] uppercase text-muted-foreground">DCA Events</div>
				<div class="mt-1 font-mono text-lg font-semibold">{stats.totalEvents}</div>
				<div class="mt-1 flex flex-wrap gap-1">
					{#each Object.entries(stats.kindCounts) as [kind, n]}
						<span class="rounded px-1.5 py-0.5 text-[10px] font-bold {KIND_BADGE[kind] ?? 'bg-secondary text-muted-foreground'}">{kind} {n}</span>
					{/each}
				</div>
			</div>
			<div class="rounded-lg border border-border bg-card px-4 py-3">
				<div class="text-[11px] uppercase text-muted-foreground">Backtests</div>
				<div class="mt-1 font-mono text-lg font-semibold">{stats.totalRuns}</div>
				{#if stats.avgProfit != null}
					<div class="mt-1 text-xs text-muted-foreground">
						avg <span class="font-mono font-semibold" class:text-green-400={stats.avgProfit > 0} class:text-red-400={stats.avgProfit < 0}>{stats.avgProfit >= 0 ? '+' : ''}{stats.avgProfit.toFixed(1)}%</span>
					</div>
				{/if}
			</div>
			<div class="rounded-lg border border-border bg-card px-4 py-3">
				<div class="text-[11px] uppercase text-muted-foreground">Total Signals</div>
				<div class="mt-1 font-mono text-lg font-semibold">{stats.totalEvents + stats.totalRuns}</div>
			</div>
			<div class="rounded-lg border border-border bg-card px-4 py-3">
				<div class="text-[11px] uppercase text-muted-foreground">Last Activity</div>
				<div class="mt-1 text-xs font-mono text-foreground">{stats.lastActivity ? fmtTime(stats.lastActivity) : '—'}</div>
			</div>
		</div>
	{/if}

	<!-- Sticky search + filter bar -->
	<div class="sticky top-14 z-40 mb-6 rounded-xl border border-border bg-card px-4 py-3">
		<div class="flex flex-col gap-3 sm:flex-row sm:items-center">
			<!-- Search -->
			<div class="relative flex-1">
				<span class="pointer-events-none absolute inset-y-0 left-3 flex items-center text-muted-foreground">
					<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
					</svg>
				</span>
				<input
					type="search"
					bind:value={query}
					placeholder={t(lang, 'signals.search')}
					class="w-full rounded-lg border border-border bg-background py-2 pl-9 pr-3 text-sm text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary"
				/>
			</div>
			<!-- Tab chips -->
			<div class="flex gap-2">
				{#each ([['all', 'signals.tab.all'], ['events', 'signals.tab.events'], ['backtests', 'signals.tab.backtests']] as const) as [tab, key]}
					<button
						type="button"
						onclick={() => (activeTab = tab)}
						class="rounded-full px-3 py-1 text-xs font-medium transition-colors"
						class:bg-primary={activeTab === tab}
						class:text-primary-foreground={activeTab === tab}
						class:bg-secondary={activeTab !== tab}
						class:text-muted-foreground={activeTab !== tab}
						class:border={activeTab !== tab}
						class:border-border={activeTab !== tab}
					>
						{t(lang, key)}
					</button>
				{/each}
			</div>
		</div>
	</div>

	<!-- Anon gate -->
	{#if isGated}
		<div class="rounded-xl border border-border bg-card p-10 text-center">
			<p class="mb-1 text-base font-semibold">{t(lang, 'signals.gate.title')}</p>
			<p class="mb-4 text-sm text-muted-foreground">{t(lang, 'signals.gate.body')}</p>
			<a
				href="/login?next=/signals"
				class="inline-block rounded-lg bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
			>
				{t(lang, 'signals.gate.cta')}
			</a>
		</div>

	<!-- Empty state after filtering -->
	{:else if merged.length === 0}
		<div class="rounded-xl border border-dashed border-border bg-card p-10 text-center text-sm text-muted-foreground">
			{t(lang, 'signals.empty')}
		</div>

	<!-- Signal feed -->
	{:else}
		<ul class="space-y-3">
			{#each merged as signal (signal._ts + signal._type + (signal._type === 'event' ? signal.item.kind : signal.item.id))}
				{#if signal._type === 'event'}
					{@const e = signal.item}
					{@const borderCls = KIND_BORDER[e.kind] ?? 'border-l-[#4a9eff]'}
					{@const badgeCls = KIND_BADGE[e.kind] ?? 'bg-blue-950/60 text-blue-400'}
					<li class="rounded-xl border border-border bg-card border-l-4 {borderCls} px-5 py-4">
						<div class="mb-2 flex flex-wrap items-center gap-2">
							<span class="rounded-full px-2 py-0.5 text-xs font-bold {badgeCls}">{e.kind}</span>
							<span class="text-xs text-muted-foreground">{fmtTime(e.ts)}</span>
							<span class="ml-auto rounded-full bg-orange-950/60 px-2 py-0.5 text-[10px] font-semibold text-orange-400 border border-orange-900">EVENT DCA</span>
						</div>
						<div class="flex flex-wrap gap-x-4 gap-y-1 text-sm">
							<span class="font-medium">BTC {fmtUSD(e.price)}</span>
							{#if e.fng != null}
								<span class="text-muted-foreground">FnG <span class="font-mono text-foreground">{e.fng}</span></span>
							{/if}
							{#if e.severity != null}
								<span class="text-muted-foreground">
									{lang === 'zh' ? '严重度' : 'Severity'}
									<span class="font-mono font-semibold text-foreground">{(e.severity * 100).toFixed(1)}%</span>
								</span>
							{/if}
						</div>
						<div class="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
							{#if e.amount_usdt != null}
								<span>{lang === 'zh' ? '金额' : 'Amount'}: <span class="font-mono text-foreground">{fmtUSD(e.amount_usdt)} USDT</span></span>
							{/if}
							{#if e.mode}
								<span>mode: <span class="font-mono text-foreground">{e.mode}</span></span>
							{/if}
						</div>
					</li>
				{:else}
					{@const r = signal.item}
					{@const profit = r.total_profit_pct ?? 0}
					<li class="rounded-xl border border-border bg-card border-l-4 border-l-green-500 px-5 py-4">
						<div class="mb-2 flex flex-wrap items-center gap-2">
							<span class="rounded-full bg-green-950/60 px-2 py-0.5 text-xs font-bold text-green-400">BACKTEST</span>
							<span class="text-xs text-muted-foreground">{fmtTime(r.started_at ?? r.imported_at)}</span>
							{#if r.timeframe}
								<span class="rounded bg-secondary px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{r.timeframe}</span>
							{/if}
						</div>
						<div class="mb-1 flex items-baseline gap-2">
							<span class="font-semibold">{r.strategy}</span>
						</div>
						<div class="flex flex-wrap gap-x-4 gap-y-1 text-sm">
							<span
								class:text-green-400={profit > 0}
								class:text-red-400={profit < 0}
								class:text-muted-foreground={profit === 0}
								class="font-mono font-semibold"
							>{fmtPct(profit)}</span>
							{#if r.calmar != null}
								<span class="text-muted-foreground">Calmar <span class="font-mono text-foreground">{r.calmar.toFixed(2)}</span></span>
							{/if}
							{#if r.sharpe != null}
								<span class="text-muted-foreground">Sharpe <span class="font-mono text-foreground">{r.sharpe.toFixed(2)}</span></span>
							{/if}
						</div>
						<div class="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
							{#if r.total_trades != null}
								<span><span class="font-mono text-foreground">{r.total_trades}</span> trades</span>
							{/if}
							{#if r.max_drawdown_pct != null}
								<span>MaxDD <span class="font-mono text-red-500">{r.max_drawdown_pct.toFixed(1)}%</span></span>
							{/if}
						</div>
					</li>
				{/if}
			{/each}
		</ul>
	{/if}

	{#if stratFreshness.length > 0}
		<section class="mt-8 rounded-lg border bg-card p-5">
			<div class="mb-3 flex items-baseline justify-between">
				<h2 class="text-sm font-semibold">Strategy Freshness</h2>
				<span class="text-[11px] text-muted-foreground">Days since last backtest import</span>
			</div>
			<div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
				{#each stratFreshness as s}
					{@const tone = s.daysAgo <= 7 ? 'border-green-700/50 bg-green-950/20' : s.daysAgo <= 30 ? 'border-yellow-700/50 bg-yellow-950/20' : 'border-red-700/40 bg-red-950/15'}
					{@const badge = s.daysAgo <= 7 ? 'bg-green-500/25 text-green-400' : s.daysAgo <= 30 ? 'bg-yellow-500/20 text-yellow-400' : 'bg-red-500/20 text-red-400'}
					<a href="/strategies/{s.strategy}" class="flex items-center justify-between rounded-lg border {tone} px-3 py-2 transition hover:opacity-80">
						<div class="min-w-0">
							<div class="truncate text-xs font-semibold">{s.strategy}</div>
							<div class="font-mono text-[10px] text-muted-foreground">{s.runCount} runs · best {s.bestProfit != null ? (s.bestProfit >= 0 ? '+' : '') + s.bestProfit.toFixed(1) + '%' : '—'}</div>
						</div>
						<span class="ml-2 shrink-0 rounded-full px-2 py-0.5 text-[11px] font-mono {badge}">
							{s.daysAgo === 0 ? 'today' : s.daysAgo + 'd'}
						</span>
					</a>
				{/each}
			</div>
		</section>
	{/if}

	{#if modeBreakdown}
		<section class="mt-6 rounded-lg border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">Event Mode Breakdown <span class="ml-1 font-normal text-muted-foreground text-xs">({data.events.length} events · count + avg severity per mode)</span></h2>
			<div class="space-y-1.5">
				{#each modeBreakdown as row}
					<div class="flex items-center gap-2 text-xs">
						<span class="w-24 shrink-0 truncate font-mono text-muted-foreground text-[10px]" title={row.mode}>{row.mode}</span>
						<div class="relative flex-1 h-5 rounded-sm bg-muted/20 overflow-hidden">
							<div class="absolute inset-y-0 left-0 rounded-sm bg-indigo-500/45 transition-all"
								style="width:{row.barPct.toFixed(1)}%"></div>
							<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">{row.count}×</span>
						</div>
						<span class="w-20 shrink-0 text-right font-mono text-[10px] text-muted-foreground">
							{row.avgSev != null ? 'sev ' + row.avgSev.toFixed(3) : '—'}
						</span>
						<span class="w-16 shrink-0 text-right font-mono text-[10px]"
							style="color:{KIND_COLORS[row.topKind] ?? 'var(--ch-axis-strong)'}"
						>{row.topKind}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar = relative count · avg sev = mean severity for that mode · top kind = most frequent trigger kind</p>
		</section>
	{/if}

	{#if severityTrend}
		{@const st = severityTrend}
		<section class="mt-6 rounded-lg border bg-card p-4">
			<div class="mb-2 flex items-baseline justify-between">
				<h2 class="text-sm font-semibold">Market Stress Trend <span class="ml-1 font-normal text-muted-foreground text-xs">(7-event rolling avg severity)</span></h2>
				<span class="font-mono text-xs {st.rising ? 'text-red-400' : st.falling ? 'text-green-400' : 'text-muted-foreground'}">
					{st.latest.toFixed(3)} {st.rising ? '↑ rising' : st.falling ? '↓ easing' : '→ stable'}
				</span>
			</div>
			<svg viewBox="0 0 {st.W} {st.H}" class="w-full" style="height:{st.H}px;min-width:200px">
				<polyline points={st.poly} fill="none"
					stroke={st.rising ? 'var(--ch-loss-strong)' : st.falling ? 'var(--ch-profit-strong)' : 'var(--ch-axis)'}
					stroke-width="1.5" stroke-linejoin="round"/>
				<text x={st.PAD} y={st.H - 2} font-size="7" fill="var(--ch-rule-strong)">oldest</text>
				<text x={st.W - st.PAD} y={st.H - 2} font-size="7" fill="var(--ch-rule-strong)" text-anchor="end">latest</text>
			</svg>
			<p class="mt-1 text-[10px] text-muted-foreground">Severity 0 = mild signal · 1 = extreme · red = stress rising · green = stress easing</p>
		</section>
	{/if}

	{#if signalKindTimeline}
		{@const skt = signalKindTimeline}
		<section class="mt-6 rounded-lg border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">Weekly Signal Mix <span class="ml-1 font-normal text-muted-foreground text-xs">(last 8 weeks · stacked by kind)</span></h2>
			<div class="flex items-end gap-1">
				{#each skt.weeks as [week, kinds]}
					{@const total = skt.KINDS.reduce((s, k) => s + (kinds[k] ?? 0), 0)}
					{@const barH = Math.round((total / skt.maxTotal) * 80)}
					<div class="flex flex-1 flex-col items-center gap-1">
						<div class="relative flex w-full flex-col-reverse overflow-hidden rounded-t-sm" style="height:{Math.max(2, barH)}px">
							{#each skt.KINDS as k}
								{#if (kinds[k] ?? 0) > 0}
									{@const segH = Math.round(((kinds[k] ?? 0) / total) * barH)}
									<div style="height:{Math.max(1, segH)}px;background:{KIND_COLORS[k] ?? 'var(--ch-axis-muted)'}" title="{k}: {kinds[k]}"></div>
								{/if}
							{/each}
						</div>
						<span class="font-mono text-[8px] text-muted-foreground rotate-[-45deg] origin-center">{week.slice(5)}</span>
					</div>
				{/each}
			</div>
			<div class="mt-2 flex flex-wrap gap-3">
				{#each skt.KINDS as k}
					<span class="flex items-center gap-1 text-[10px] text-muted-foreground">
						<span class="inline-block h-2.5 w-2.5 rounded-sm" style="background:{KIND_COLORS[k]}"></span>
						{k}
					</span>
				{/each}
			</div>
		</section>
	{/if}

	{#if fngHistogram}
		{@const fh = fngHistogram}
		<section class="mt-6 rounded-lg border bg-card p-4">
			<div class="mb-3 flex items-baseline justify-between">
				<h2 class="text-sm font-semibold">Fear &amp; Greed at Trigger Time <span class="ml-1 font-normal text-muted-foreground text-xs">({fh.total} events with FNG data)</span></h2>
				<span class="font-mono text-xs text-muted-foreground">avg {fh.avg.toFixed(0)}</span>
			</div>
			<div class="flex items-end gap-1">
				{#each fh.buckets as b}
					<div class="flex flex-1 flex-col items-center gap-0.5" title="{b.lo}-{b.lo + 10}: {b.count} events">
						<div class="w-full rounded-t-sm" style="height:{Math.max(1, Math.round(b.barPct * 0.6))}px; background:{b.color}"></div>
						<span class="font-mono text-[7px] text-muted-foreground text-center">{b.label}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Green = fear zone (&lt;30) · amber = neutral · red = greed zone (&gt;70) · x-axis = FNG index 0→100</p>
		</section>
	{/if}

	{#if severityByKind}
		<section class="mt-6 rounded-lg border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">Severity Range by Trigger Kind <span class="ml-1 font-normal text-muted-foreground text-xs">(min · median · max)</span></h2>
			<div class="space-y-2">
				{#each severityByKind as row}
					<div class="flex items-center gap-3 text-xs">
						<span class="w-24 shrink-0 truncate font-mono text-muted-foreground text-[11px]">{row.kind}</span>
						<div class="relative flex-1 h-4 rounded-sm bg-muted/20">
							<div class="absolute inset-y-1 rounded-sm bg-indigo-500/30"
								style="left:{(row.min * 100).toFixed(1)}%; width:{((row.max - row.min) * 100).toFixed(1)}%"></div>
							<div class="absolute top-0 bottom-0 w-0.5 bg-indigo-400"
								style="left:{(row.median * 100).toFixed(1)}%"></div>
						</div>
						<span class="w-28 shrink-0 text-right font-mono text-[10px] text-muted-foreground">
							{(row.min * 100).toFixed(0)}–{(row.median * 100).toFixed(0)}–{(row.max * 100).toFixed(0)}%
						</span>
						<span class="w-8 shrink-0 text-right font-mono text-[10px] text-muted-foreground">{row.count}×</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar = min–max range · vertical line = median severity · higher = stronger trigger signal</p>
		</section>
	{/if}

	{#if dcaCumulativeSpend}
		{@const dcs = dcaCumulativeSpend}
		<section class="mt-6 rounded-lg border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">Cumulative DCA Spend <span class="ml-1 font-normal text-muted-foreground text-xs">({dcs.n} events · {dcs.firstDate} → {dcs.lastDate})</span></h2>
			<svg viewBox="0 0 {dcs.W} {dcs.H}" class="w-full" style="height:{dcs.H}px">
				<polyline points={dcs.polyline} fill="none" stroke="var(--ch-violet-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={dcs.PAD} y={dcs.H - 2} font-size="7" fill="var(--ch-rule)">{dcs.firstDate}</text>
				<text x={dcs.W - dcs.PAD} y={dcs.H - 2} font-size="7" fill="var(--ch-rule)" text-anchor="end">{dcs.lastDate}</text>
				<text x={dcs.W - dcs.PAD} y="10" font-size="8" fill="var(--ch-violet-strong)" text-anchor="end">${dcs.total.toFixed(0)} total</text>
			</svg>
			<p class="mt-1 text-[10px] text-muted-foreground">Running cumulative USDT deployed across all DCA trigger events · total deployed: ${dcs.total.toFixed(0)}</p>
		</section>
	{/if}

	{#if eventCalendar}
		<section class="mt-6 rounded-lg border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">30-Day Event Activity <span class="ml-1 font-normal text-muted-foreground text-xs">(DCA triggers · last 30 days)</span></h2>
			<div class="space-y-1.5">
				{#each eventCalendar.rows as row}
					<div class="grid grid-cols-6 gap-1.5">
						{#each row as cell}
							{@const alpha = cell.count === 0 ? 0 : 0.15 + (cell.count / eventCalendar.maxCount) * 0.75}
							<div
								class="flex h-10 flex-col items-center justify-center rounded text-[10px] font-mono leading-tight"
								style="background:rgba(99,102,241,{alpha.toFixed(2)})"
								title="{cell.date}: {cell.count} event{cell.count !== 1 ? 's' : ''}{Object.keys(cell.kinds).length ? ' · ' + Object.entries(cell.kinds).map(([k,v]) => k+':'+v).join(', ') : ''}"
							>
								<span class="text-[9px] text-muted-foreground">{cell.date.slice(5)}</span>
								{#if cell.count > 0}
									<span class="font-semibold text-indigo-300">{cell.count}</span>
								{:else}
									<span class="text-muted-foreground/30">·</span>
								{/if}
							</div>
						{/each}
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Each cell = 1 day · indigo intensity ∝ event count</p>
		</section>
	{/if}

	{#if fngVsAmount}
		{@const fva = fngVsAmount}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-2 text-sm font-semibold">Fear &amp; Greed vs Amount Deployed
				<span class="ml-1 font-normal text-muted-foreground text-xs">({fva.dots.length} events · r = {fva.corr >= 0 ? '+' : ''}{fva.corr.toFixed(2)})</span>
			</h2>
			<svg viewBox="0 0 {fva.W} {fva.H}" class="w-full" style="height:{fva.H}px">
				<!-- zone lines: fear=25, greed=75 -->
				<line x1={fva.PAD + 25/100*(fva.W-fva.PAD*2)} y1={fva.PAD} x2={fva.PAD + 25/100*(fva.W-fva.PAD*2)} y2={fva.H-fva.PAD} stroke="var(--ch-profit-light)" stroke-width="1" stroke-dasharray="3 2"/>
				<line x1={fva.PAD + 75/100*(fva.W-fva.PAD*2)} y1={fva.PAD} x2={fva.PAD + 75/100*(fva.W-fva.PAD*2)} y2={fva.H-fva.PAD} stroke="var(--ch-loss-light)" stroke-width="1" stroke-dasharray="3 2"/>
				{#each fva.dots as d}
					<circle cx={d.x.toFixed(1)} cy={d.y.toFixed(1)} r="3.5" fill={d.color} opacity="0.8">
						<title>FNG {d.fng} ({d.kind}) · ${d.amount.toFixed(0)}</title>
					</circle>
				{/each}
				<text x={fva.PAD} y={fva.H-3} font-size="7" fill="var(--ch-rule)">0 (fear)</text>
				<text x={fva.W-fva.PAD} y={fva.H-3} font-size="7" fill="var(--ch-rule)" text-anchor="end">100 (greed)</text>
			</svg>
			<div class="mt-1 flex gap-4 text-[10px] text-muted-foreground">
				<span class="flex items-center gap-1"><span class="inline-block h-2 w-2 rounded-full bg-green-500/70"></span>Fear ≤25</span>
				<span class="flex items-center gap-1"><span class="inline-block h-2 w-2 rounded-full bg-yellow-500/60"></span>Neutral</span>
				<span class="flex items-center gap-1"><span class="inline-block h-2 w-2 rounded-full bg-red-500/60"></span>Greed ≥75</span>
				<span class="ml-auto">Pearson r = {fva.corr >= 0 ? '+' : ''}{fva.corr.toFixed(2)}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">x = FNG index · y = USDT deployed · negative r = more capital deployed during fear</p>
		</section>
	{/if}

	{#if eventAmountRanking}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Top Events by USDT Deployed
				<span class="ml-1 font-normal text-muted-foreground text-xs">(largest single-event deployments)</span>
			</h2>
			<div class="space-y-1.5">
				{#each eventAmountRanking as r}
					<div class="flex items-center gap-2">
						<span class="w-20 shrink-0 font-mono text-[10px] text-muted-foreground">{r.ts.slice(0, 10)}</span>
						<span class="w-16 shrink-0 font-mono text-[10px] truncate">{r.kind}</span>
						<div class="relative flex-1 h-5 rounded-sm bg-muted/20 overflow-hidden">
							<div class="absolute inset-y-0 left-0 rounded-sm"
								style="width:{r.barPct.toFixed(1)}%; background:rgba(99,102,241,{(r.severity * 0.7 + 0.25).toFixed(2)})"></div>
							<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">
								${r.amount.toFixed(0)} USDT
							</span>
						</div>
						<span class="w-14 shrink-0 text-right font-mono text-[10px] text-muted-foreground">
							sev {(r.severity * 100).toFixed(0)}%
						</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar opacity ∝ severity · shows which events triggered the largest capital deployments</p>
		</section>
	{/if}

	{#if hourlyEventDist}
		{@const hed = hourlyEventDist}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Trigger Hour Distribution (UTC)
				<span class="ml-1 font-normal text-muted-foreground text-xs">(peak at {hed.peakH.toString().padStart(2,'0')}:00 UTC · {data.events.length} events)</span>
			</h2>
			<div class="flex items-end gap-px" style="height:72px">
				{#each hed.bars as b}
					<div class="flex-1 flex flex-col justify-end" title="Hour {b.h.toString().padStart(2,'0')}:00 UTC · {b.count} events · avg sev {(b.avgSev*100).toFixed(0)}% · ${b.avgAmount.toFixed(0)}">
						<div class="w-full rounded-t-sm" style="height:{Math.max(2, b.pct * 64)}px; background:rgba(99,102,241,{0.25 + b.avgSev * 0.7})"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>00h</span><span>06h</span><span>12h</span><span>18h</span><span>23h</span>
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar height = event count · opacity = avg severity · UTC hours</p>
		</section>
	{/if}

	{#if kindProportions}
		{@const kp = kindProportions}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Signal Kind Proportions
				<span class="ml-1 font-normal text-muted-foreground text-xs">({kp.total} total triggers)</span>
			</h2>
			<div class="space-y-2">
				{#each kp.rows as r}
					<div class="flex items-center gap-2">
						<span class="w-20 shrink-0 font-mono text-[10px] truncate">{r.kind}</span>
						<div class="relative flex-1 h-5 rounded-sm bg-muted/20 overflow-hidden">
							<div class="absolute inset-y-0 left-0 rounded-sm bg-indigo-500/50"
								style="width:{(r.pct * 100).toFixed(1)}%"></div>
							<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">
								{r.count} · {(r.pct * 100).toFixed(1)}%
							</span>
						</div>
						<span class="w-20 shrink-0 text-right font-mono text-[10px] text-muted-foreground">
							sev {(r.avgSev * 100).toFixed(0)}% · ${r.avgAmount.toFixed(0)}
						</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar width = share of total triggers · right = avg severity and avg USDT deployed per trigger</p>
		</section>
	{/if}

	{#if kindMonthlyTrend}
		{@const kmt = kindMonthlyTrend}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Signal Kind Trend
				<span class="ml-1 font-normal text-muted-foreground text-xs">(last 6 months · events per kind)</span>
			</h2>
			<div class="flex items-end gap-2" style="height:80px">
				{#each kmt.months as m}
					<div class="flex flex-1 flex-col gap-px items-stretch justify-end" title="{m.label}: {m.total} events">
						{#each kmt.kinds as k, ki}
							{#if m.byKind[k]}
								<div class="w-full rounded-sm"
									style="height:{Math.max(2, (m.byKind[k] / kmt.maxTotal) * 68)}px; background:{kmt.colors[ki]}"></div>
							{/if}
						{/each}
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				{#each kmt.months as m}<span>{m.label}</span>{/each}
			</div>
			<div class="mt-2 flex flex-wrap gap-3 text-[10px] text-muted-foreground">
				{#each kmt.kinds as k, ki}
					<span class="flex items-center gap-1">
						<span class="inline-block h-2 w-3 rounded-sm" style="background:{kmt.colors[ki]}"></span>{k}
					</span>
				{/each}
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Stacked bar height = events per kind per month · rising = increasing signal frequency</p>
		</section>
	{/if}

	{#if fngZoneEventCount}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Events by Fear & Greed Zone
				<span class="ml-1 font-normal text-muted-foreground text-xs">(count + avg USDT deployed per sentiment zone)</span>
			</h2>
			<div class="space-y-2">
				{#each fngZoneEventCount as z}
					<div class="flex items-center gap-3">
						<span class="w-24 shrink-0 text-[10px] font-medium">{z.label}</span>
						<div class="relative flex-1 h-5 rounded-sm bg-muted/20 overflow-hidden">
							<div class="absolute inset-y-0 left-0 rounded-sm transition-all" style="width:{z.barPct.toFixed(1)}%; background:{z.color}"></div>
							<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">{z.count} events</span>
						</div>
						{#if z.avgAmt != null}
							<span class="w-16 shrink-0 text-right font-mono text-[10px] text-muted-foreground">{z.avgAmt.toFixed(0)} USDT</span>
						{:else}
							<span class="w-16 shrink-0 text-right font-mono text-[10px] text-muted-foreground">—</span>
						{/if}
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar = event count · right = avg USDT deployed · green = fear zones (buy signals) · red = greed zones</p>
		</section>
	{/if}

	{#if severityTimeOfDay}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Signal Severity by Hour (UTC)
				<span class="ml-1 font-normal text-muted-foreground text-xs">(avg severity score · which hours produce most intense signals?)</span>
			</h2>
			<div class="flex items-end gap-px" style="height:56px">
				{#each severityTimeOfDay as h}
					<div class="flex flex-1 flex-col items-center justify-end"
						title="Hour {h.label} UTC: {h.count} events · avg severity {h.avg != null ? h.avg.toFixed(2) : '—'}">
						{#if h.avg != null && h.count > 0}
							<div class="w-full rounded-t-sm"
								style="height:{Math.max(1, h.barPct * 0.48)}px; background:{h.avg > 0.7 ? 'var(--ch-loss)' : h.avg > 0.4 ? 'var(--ch-warn)' : 'var(--ch-violet-light)'}"></div>
						{:else}
							<div class="w-full" style="height:1px; background:var(--ch-rule-faint)"></div>
						{/if}
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>00h</span><span>06h</span><span>12h</span><span>18h</span><span>23h</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Bar height = avg severity · red &gt;0.7 · yellow 0.4–0.7 · purple &lt;0.4 · empty hours = no signals fired</p>
		</section>
	{/if}

	{#if kindAvgInterval}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Avg Interval Between Events by Kind
				<span class="ml-1 font-normal text-muted-foreground text-xs">(mean hours between consecutive same-kind events · shorter bar = more frequent)</span>
			</h2>
			<div class="space-y-2">
				{#each kindAvgInterval as row}
					<div class="flex items-center gap-2">
						<span class="w-16 shrink-0 rounded px-1.5 py-0.5 text-xs font-bold {KIND_BADGE[row.kind] ?? 'bg-secondary text-muted-foreground'}">{row.kind}</span>
						<div class="flex-1 rounded bg-muted h-4 overflow-hidden">
							<div class="h-full rounded" style="width:{row.barPct.toFixed(1)}%; background:var(--ch-violet-light)"></div>
						</div>
						<span class="w-20 shrink-0 text-right font-mono text-xs text-muted-foreground">{row.avg < 24 ? row.avg.toFixed(1) + 'h' : (row.avg / 24).toFixed(1) + 'd'} avg</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar length ∝ avg wait time · shorter = more frequent signal · consecutive same-kind pairs only</p>
		</section>
	{/if}

	{#if runProfitTimeline}
		{@const rpt = runProfitTimeline}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-2 text-sm font-semibold">Backtest Run Profit Trend
				<span class="ml-2 text-xs font-normal text-muted-foreground">(last {rpt.count} runs by import date · {rpt.improving ? '📈 improving' : '→ stable'})</span>
			</h2>
			<svg viewBox="0 0 {rpt.W} {rpt.H}" class="w-full" style="height:72px">
				<line x1={rpt.PAD} x2={rpt.W - rpt.PAD} y1={rpt.zeroY} y2={rpt.zeroY} stroke="var(--ch-rule)" stroke-width="1" stroke-dasharray="4 3"/>
				<polyline points={rpt.polyline} fill="none" stroke="var(--ch-violet)" stroke-width="1.5"/>
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>oldest → newest</span>
				<span>recent avg {rpt.recentAvg >= 0 ? '+' : ''}{rpt.recentAvg.toFixed(1)}%</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Each point = one backtest run sorted by import date · zero line = breakeven · upward trend = strategy improving</p>
		</section>
	{/if}
	{#if fngSeverityMatrix}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">F&amp;G Zone by Severity
				<span class="ml-1 font-normal text-muted-foreground text-xs">(at which market sentiment does each severity fire?)</span>
			</h2>
			<div class="mt-3 space-y-2">
				{#each fngSeverityMatrix.matrix as row}
					<div class="flex items-center gap-2">
						<span class="w-8 text-center font-mono text-[10px] text-muted-foreground">s{row.sev}</span>
						<div class="flex flex-1 gap-0.5" style="height:18px">
							{#each row.counts as cnt, zi}
								{#if cnt > 0}
									<div class="flex items-center justify-center rounded text-[9px] font-mono text-white"
										style="flex:{cnt}; background:{fngSeverityMatrix.ZONES[zi].color}" title="{fngSeverityMatrix.ZONES[zi].label}: {cnt}">{cnt}</div>
								{:else}
									<div style="flex:0.2"></div>
								{/if}
							{/each}
						</div>
						<span class="w-8 text-right font-mono text-[9px] text-muted-foreground">{row.total}</span>
					</div>
				{/each}
			</div>
			<div class="mt-2 flex gap-2">
				{#each fngSeverityMatrix.ZONES as z}
					<span class="flex items-center gap-1 text-[9px] text-muted-foreground">
						<span class="inline-block h-2 w-2 rounded-sm" style="background:{z.color}"></span>{z.label}
					</span>
				{/each}
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Row = severity level · bars = F&amp;G zone proportion · wider = more events in that zone</p>
		</section>
	{/if}
	{#if runSortinoTimeline}
		{@const rst = runSortinoTimeline}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Backtest Run Sortino Trend
				<span class="ml-1 font-normal text-muted-foreground text-xs">(last {rst.count} runs · {rst.improving ? '↑ improving' : '→ stable'})</span>
			</h2>
			<svg viewBox="0 0 {rst.W} {rst.H}" class="w-full" style="height:72px">
				<line x1={rst.PAD} x2={rst.W - rst.PAD} y1={rst.zeroY} y2={rst.zeroY} stroke="var(--ch-rule)" stroke-width="1" stroke-dasharray="4 3"/>
				<polyline points={rst.polyline} fill="none" stroke="var(--ch-violet)" stroke-width="1.5"/>
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>oldest → newest</span>
				<span>recent avg {rst.recent.toFixed(2)}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Sortino ratio per run by import date · upward trend = strategy producing better risk-adjusted returns over time</p>
		</section>
	{/if}
	{#if runWinRateTimeline}
		{@const rwrt = runWinRateTimeline}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Backtest Run Win-Rate Trend
				<span class="ml-1 font-normal text-muted-foreground text-xs">(last {rwrt.count} runs by import date · latest {rwrt.latest.toFixed(1)}% · {rwrt.trend >= 0 ? '↑' : '↓'} {Math.abs(rwrt.trend).toFixed(1)}pp)</span>
			</h2>
			<svg viewBox="0 0 {rwrt.W} {rwrt.H}" class="mt-3 w-full" style="height:64px">
				{#if rwrt.fiftyY != null}
					<line x1={rwrt.PAD} x2={rwrt.W - rwrt.PAD} y1={rwrt.fiftyY} y2={rwrt.fiftyY} stroke="var(--ch-rule)" stroke-width="1" stroke-dasharray="4 3"/>
				{/if}
				<line x1={rwrt.PAD} x2={rwrt.W - rwrt.PAD} y1={rwrt.avgY} y2={rwrt.avgY} stroke="var(--ch-violet-light)" stroke-width="1" stroke-dasharray="2 4"/>
				<polyline points={rwrt.poly} fill="none" stroke={rwrt.trend >= 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss)'} stroke-width="1.5"/>
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>WR {rwrt.mn.toFixed(1)}%</span>
				<span>avg {rwrt.avg.toFixed(1)}%</span>
				<span>{rwrt.mx.toFixed(1)}%</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Win rate% per backtest run sorted by import date · dashed line = avg · 50% = break-even on equal win/loss</p>
		</section>
	{/if}
	{#if runCalmarTimeline}
		{@const rct = runCalmarTimeline}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Backtest Run Calmar Trend
				<span class="ml-1 font-normal text-muted-foreground text-xs">(last {rct.count} runs · {rct.improving ? '↑ improving' : '→ stable'})</span>
			</h2>
			<svg viewBox="0 0 {rct.W} {rct.H}" class="w-full" style="height:72px">
				<line x1={rct.PAD} x2={rct.W - rct.PAD} y1={rct.zeroY} y2={rct.zeroY} stroke="var(--ch-rule)" stroke-width="1" stroke-dasharray="4 3"/>
				<polyline points={rct.polyline} fill="none" stroke={rct.improving ? 'var(--ch-profit)' : 'var(--ch-violet)'} stroke-width="1.5"/>
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>oldest → newest</span>
				<span>recent avg {rct.recent.toFixed(2)}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Calmar = annualized return / max drawdown · upward trend = strategy improving risk-adjusted returns over optimizations</p>
		</section>
	{/if}
	{#if runProfitFactorTimeline}
		{@const rpft = runProfitFactorTimeline}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Backtest Run Profit Factor Trend
				<span class="ml-1 font-normal text-muted-foreground text-xs">(last {rpft.count} runs · latest {rpft.latest.toFixed(2)} · avg {rpft.avg.toFixed(2)} · {rpft.trend >= 0 ? '↑' : '↓'})</span>
			</h2>
			<svg viewBox="0 0 {rpft.W} {rpft.H}" class="mt-3 w-full" style="height:64px">
				{#if rpft.oneY != null}
					<line x1={rpft.PAD} x2={rpft.W - rpft.PAD} y1={rpft.oneY} y2={rpft.oneY} stroke="var(--ch-rule)" stroke-width="1" stroke-dasharray="4 3"/>
				{/if}
				<polyline points={rpft.poly} fill="none" stroke={rpft.trend >= 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss)'} stroke-width="1.5"/>
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>PF {rpft.mn.toFixed(2)}</span><span>→ runs by import date →</span><span>{rpft.mx.toFixed(2)}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Profit factor = gross wins / gross losses · dashed = break-even (PF 1.0) · upward = strategies becoming more efficient over time</p>
		</section>
	{/if}

	{#if runCalmarSignalTimeline}
		{@const rct = runCalmarSignalTimeline}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Calmar Ratio Timeline</h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Calmar ratio (return / max drawdown) across runs sorted by import date · {rct.trend >= 0 ? 'improving' : 'declining'}</p>
			<svg viewBox="0 0 {rct.W} {rct.H}" class="mt-2 w-full" style="height:60px">
				<polyline points={rct.poly} fill="none" stroke={rct.trend >= 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss)'} stroke-width="1.5"/>
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>Calmar {rct.mn.toFixed(2)}</span><span>→ runs by import date →</span><span>{rct.mx.toFixed(2)}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Higher Calmar = better risk-adjusted return · rising line = newer strategies survive drawdowns more efficiently</p>
		</section>
	{/if}

	{#if runSortinoDistribution}
		{@const rsd = runSortinoDistribution}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Sortino Distribution</h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Histogram of Sortino ratios across {rsd.total} runs · median {rsd.median.toFixed(2)}</p>
			<div class="mt-3 flex items-end gap-1" style="height:72px">
				{#each rsd.buckets as b}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<span class="font-mono text-[8px] text-muted-foreground">{b.count > 0 ? b.count : ''}</span>
						<div class="w-full rounded-sm" style="height:{b.barPct}%; background:var(--ch-violet); min-height:{b.count > 0 ? 2 : 0}px"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[8px] text-muted-foreground">
				{#each rsd.buckets as b, i}
					{#if i === 0 || i === rsd.buckets.length - 1}
						<span>{b.lo.toFixed(1)}</span>
					{/if}
				{/each}
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Right-skewed = most strategies have low Sortino · tall right bars = research producing high-quality risk-adjusted returns</p>
		</section>
	{/if}

	{#if runMaxDrawdownTimeline}
		{@const rmdt = runMaxDrawdownTimeline}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Max Drawdown Timeline</h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Max drawdown% across runs sorted by import date · {rmdt.trend <= 0 ? 'improving (falling)' : 'worsening (rising)'}</p>
			<svg viewBox="0 0 {rmdt.W} {rmdt.H}" class="mt-2 w-full" style="height:60px">
				<polyline points={rmdt.poly} fill="none" stroke={rmdt.trend <= 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss)'} stroke-width="1.5"/>
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>DD {rmdt.mn.toFixed(1)}%</span><span>→ runs by import date →</span><span>{rmdt.mx.toFixed(1)}%</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Falling line = newer strategies have smaller drawdowns · rising = research drifting toward higher-risk configurations</p>
		</section>
	{/if}

	{#if runProfitFactorDistribution}
		{@const rpfd = runProfitFactorDistribution}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Run Profit Factor Distribution</h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Histogram of profit factor across {rpfd.total} runs · median {rpfd.median.toFixed(2)} · PF&gt;1 = gross wins exceed gross losses</p>
			<div class="mt-3 flex items-end gap-1" style="height:72px">
				{#each rpfd.buckets as b}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<span class="font-mono text-[8px] text-muted-foreground">{b.count > 0 ? b.count : ''}</span>
						<div class="w-full rounded-sm" style="height:{b.barPct}%; background:{b.lo >= 1 ? 'var(--ch-profit)' : 'var(--ch-loss-light)'}; min-height:{b.count > 0 ? 2 : 0}px"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>{rpfd.mn.toFixed(1)}</span><span>→ profit factor →</span><span>{rpfd.mx.toFixed(1)}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Green bars = PF≥1 (profitable) · red = PF&lt;1 (losing) · right-skewed distribution = most research produces profitable configs</p>
		</section>
	{/if}

	{#if runCalmarVsSortino}
		{@const rcvs = runCalmarVsSortino}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Calmar vs Sortino Scatter</h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Each dot = one backtest run · X = Calmar ratio · Y = Sortino ratio · top-right = strong risk-adjusted returns on both measures</p>
			<svg viewBox="0 0 {rcvs.W} {rcvs.H}" class="mt-2 w-full" style="height:80px">
				<line x1={rcvs.PAD} y1={rcvs.H - rcvs.PAD - ((0 - rcvs.yMin) / (rcvs.yMax - rcvs.yMin)) * (rcvs.H - rcvs.PAD * 2)} x2={rcvs.W - rcvs.PAD} y2={rcvs.H - rcvs.PAD - ((0 - rcvs.yMin) / (rcvs.yMax - rcvs.yMin)) * (rcvs.H - rcvs.PAD * 2)} stroke="var(--ch-rule)" stroke-width="0.5"/>
				<line x1={rcvs.PAD + ((0 - rcvs.xMin) / (rcvs.xMax - rcvs.xMin)) * (rcvs.W - rcvs.PAD * 2)} y1={rcvs.PAD} x2={rcvs.PAD + ((0 - rcvs.xMin) / (rcvs.xMax - rcvs.xMin)) * (rcvs.W - rcvs.PAD * 2)} y2={rcvs.H - rcvs.PAD} stroke="var(--ch-rule)" stroke-width="0.5"/>
				{#each rcvs.dots as d}
					<circle cx={d.cx} cy={d.cy} r="2" fill={d.good ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'}/>
				{/each}
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>Calmar {rcvs.xMin.toFixed(1)}</span><span>→ Calmar →</span><span>{rcvs.xMax.toFixed(1)}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Green = both metrics positive (top-right quadrant) · runs clustering here have both low drawdown and low downside volatility</p>
		</section>
	{/if}

	{#if runWinRateDistribution}
		{@const rwrd = runWinRateDistribution}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Run Win Rate Distribution</h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Histogram of win rate% across {rwrd.total} runs · median {rwrd.median.toFixed(1)}% · how often do backtested strategies hit their targets?</p>
			<div class="mt-3 flex items-end gap-1" style="height:72px">
				{#each rwrd.buckets as b}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<span class="font-mono text-[8px] text-muted-foreground">{b.count > 0 ? b.count : ''}</span>
						<div class="w-full rounded-sm" style="height:{b.barPct}%; background:{b.lo >= 50 ? 'var(--ch-profit)' : 'var(--ch-loss-light)'}; min-height:{b.count > 0 ? 2 : 0}px"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>0%</span><span>→ win rate →</span><span>100%</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Green = WR≥50% (more wins than losses) · right-skewed distribution = research consistently finds high-winrate configs</p>
		</section>
	{/if}

	{#if runTradeCountDistribution}
		{@const rtcd = runTradeCountDistribution}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Run Trade Count Distribution</h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Histogram of total trades per backtest run across {rtcd.total} runs · median {rtcd.median}</p>
			<div class="mt-3 flex items-end gap-1" style="height:72px">
				{#each rtcd.buckets as b}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<span class="font-mono text-[8px] text-muted-foreground">{b.count > 0 ? b.count : ''}</span>
						<div class="w-full rounded-sm" style="height:{b.barPct}%; background:var(--ch-warn); min-height:{b.count > 0 ? 2 : 0}px"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>{rtcd.buckets[0].label}</span><span>→ trades per run →</span><span>{rtcd.buckets[rtcd.buckets.length - 1].label}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Low trade counts = selective strategies · very high counts = overtrading risk · median shows typical strategy activity level</p>
		</section>
	{/if}

	{#if runProfitVsDrawdownScatter}
		{@const sc = runProfitVsDrawdownScatter}
		<section class="rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Run Profit vs Drawdown Scatter</h2>
			<p class="mb-2 text-[11px] text-muted-foreground">Each dot = one backtest run · x-axis: max drawdown % · y-axis: total profit % · upper-left = ideal</p>
			<svg viewBox="0 0 {sc.W} {sc.H}" class="w-full" style="height:100px">
				<line x1="10" y1={sc.zeroY} x2={sc.W - 10} y2={sc.zeroY} stroke="var(--ch-rule)" stroke-width="0.8" />
				{#each sc.dots as d}
					<circle cx={d.cx} cy={d.cy} r="2.5" fill={d.good ? 'var(--ch-profit)' : 'var(--ch-loss-light)'} />
				{/each}
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>DD {sc.xMin.toFixed(1)}%</span><span>← drawdown →</span><span>DD {sc.xMax.toFixed(1)}%</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Green = profitable · red = loss-making · runs clustering upper-left have best risk-adjusted return profile · n={sc.dots.length}</p>
		</section>
	{/if}

	{#if runSharpeVsCalmar}
		{@const rsc = runSharpeVsCalmar}
		<section class="rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Sharpe vs Calmar Scatter</h2>
			<p class="mb-2 text-[11px] text-muted-foreground">Each dot = one backtest run · x = Sharpe · y = Calmar · upper-right = excellent on both metrics · n={rsc.dots.length}</p>
			<svg viewBox="0 0 {rsc.W} {rsc.H}" class="w-full" style="height:100px">
				<line x1={rsc.zeroX} y1="10" x2={rsc.zeroX} y2={rsc.H - 10} stroke="var(--ch-rule)" stroke-width="0.8"/>
				<line x1="10" y1={rsc.zeroY} x2={rsc.W - 10} y2={rsc.zeroY} stroke="var(--ch-rule)" stroke-width="0.8"/>
				{#each rsc.dots as d}
					<circle cx={d.cx} cy={d.cy} r="2.5" fill={d.good ? 'var(--ch-profit)' : 'var(--ch-loss-light)'}/>
				{/each}
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>Sharpe {rsc.xMin.toFixed(1)}</span><span>← Sharpe ratio →</span><span>{rsc.xMax.toFixed(1)}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Sharpe penalises all volatility · Calmar penalises drawdown only · runs in upper-right corner combine low-volatility and low-drawdown profiles</p>
		</section>
	{/if}

	{#if runStrategyBestProfitRanking}
		<section class="rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Strategy Best Run Profit Ranking</h2>
			<p class="mb-3 text-[11px] text-muted-foreground">Best total profit% achieved across all runs per strategy (≥2 runs)</p>
			<div class="space-y-1">
				{#each runStrategyBestProfitRanking as r}
					<div class="flex items-center gap-2">
						<span class="w-36 truncate text-right font-mono text-[10px] text-muted-foreground">{r.strategy}</span>
						<div class="h-4 flex-1 overflow-hidden rounded-sm bg-muted">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{r.positive ? 'var(--ch-profit)' : 'var(--ch-loss)'}"></div>
						</div>
						<span class="w-16 text-right font-mono text-[10px]" style="color:{r.positive ? 'var(--ch-profit-solid)' : 'var(--ch-loss-solid)'}">{r.best > 0 ? '+' : ''}{r.best.toFixed(1)}%</span>
						<span class="w-8 text-right font-mono text-[9px] text-muted-foreground">n={r.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Best run shows peak potential · compare with avg profit to gauge consistency · large gap = high variance strategy</p>
		</section>
	{/if}

	{#if runTimeframeWinRateMatrix}
		{@const rwm = runTimeframeWinRateMatrix}
		<section class="rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Strategy × Timeframe Win-Rate Matrix</h2>
			<p class="mb-2 text-[11px] text-muted-foreground">Win rate (% runs with positive profit) per strategy and timeframe · grey = insufficient data</p>
			<div class="overflow-x-auto">
				<table class="w-full text-[9px]">
					<thead>
						<tr>
							<th class="pr-2 text-right font-mono text-muted-foreground">Strategy</th>
							{#each rwm.timeframes as tf}
								<th class="px-1 text-center font-mono text-muted-foreground">{tf}</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each rwm.cells as row}
							<tr class="border-t border-border/30">
								<td class="py-0.5 pr-2 text-right font-mono text-muted-foreground truncate max-w-[8rem]">{row.strategy}</td>
								{#each row.tfs as cell}
									<td class="px-1 py-0.5 text-center font-mono" title="{cell.tf}: {cell.wr != null ? (cell.wr * 100).toFixed(0) + '% (' + cell.total + ' runs)' : 'no data'}">
										{#if cell.wr != null}
											<span class="inline-block rounded px-0.5" style="background:{cell.wr >= 0.6 ? 'var(--ch-profit-light)' : cell.wr >= 0.4 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)'}; color:{cell.wr >= 0.6 ? 'var(--ch-profit-solid)' : cell.wr >= 0.4 ? 'var(--ch-warn)' : 'var(--ch-loss-solid)'}">{(cell.wr * 100).toFixed(0)}%</span>
										{:else}
											<span class="text-muted-foreground/30">—</span>
										{/if}
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Green ≥60% win rate · yellow 40–60% · red &lt;40% · blank = fewer than 2 runs · best strategy×timeframe combos for live deployment</p>
		</section>
	{/if}

	{#if runSortinoByStrategy}
		<section class="rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Median Sortino by Strategy</h2>
			<p class="mb-3 text-[11px] text-muted-foreground">Median Sortino ratio across all runs per strategy (≥3 runs) · Sortino penalises only downside volatility</p>
			<div class="space-y-1">
				{#each runSortinoByStrategy as r}
					<div class="flex items-center gap-2">
						<span class="w-36 truncate text-right font-mono text-[10px] text-muted-foreground">{r.strategy}</span>
						<div class="h-4 flex-1 overflow-hidden rounded-sm bg-muted">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{r.positive ? 'var(--ch-profit)' : 'var(--ch-loss)'}"></div>
						</div>
						<span class="w-16 text-right font-mono text-[10px]" style="color:{r.positive ? 'var(--ch-profit-solid)' : 'var(--ch-loss-solid)'}">{r.sortino.toFixed(2)}</span>
						<span class="w-8 text-right font-mono text-[9px] text-muted-foreground">n={r.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">High Sortino = good return per unit of downside risk · better than Sharpe for asymmetric return profiles · positive = risk-adjusted edge present</p>
		</section>
	{/if}

	{#if runMaxDrawdownByStrategy}
		<section class="rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Median Max Drawdown by Strategy</h2>
			<p class="mb-3 text-[11px] text-muted-foreground">Median max drawdown% per strategy across all runs (≥3 runs) · sorted lowest first — lower is safer</p>
			<div class="space-y-1">
				{#each runMaxDrawdownByStrategy as r}
					<div class="flex items-center gap-2">
						<span class="w-36 truncate text-right font-mono text-[10px] text-muted-foreground">{r.strategy}</span>
						<div class="h-4 flex-1 overflow-hidden rounded-sm bg-muted">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{r.safe ? 'var(--ch-profit)' : 'var(--ch-loss)'}"></div>
						</div>
						<span class="w-14 text-right font-mono text-[10px]" style="color:{r.safe ? 'var(--ch-profit-solid)' : 'var(--ch-loss-solid)'}">{r.dd.toFixed(1)}% DD</span>
						<span class="w-8 text-right font-mono text-[9px] text-muted-foreground">n={r.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Green &lt;20% DD = capital-efficient · red = high drawdown risk · pair with Sortino to identify strategies with both low drawdown and good downside-adjusted returns</p>
		</section>
	{/if}
	{#if runWinLossRatioByStrategy}
		<section class="rounded-lg border border-border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">Strategy Win/Loss Ratio Ranking</h2>
			<div class="space-y-1">
				{#each runWinLossRatioByStrategy as r}
					{@const color = r.ratio >= 2 ? 'var(--ch-profit-strong)' : r.ratio >= 1 ? 'var(--ch-violet)' : 'var(--ch-loss)'}
					<div class="flex items-center gap-2">
						<span class="w-36 truncate text-right font-mono text-[10px] text-muted-foreground">{r.strategy}</span>
						<div class="h-4 flex-1 overflow-hidden rounded-sm bg-muted">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{color}"></div>
						</div>
						<span class="w-14 text-right font-mono text-[10px]" style="color:{color}">{r.ratio.toFixed(2)}×</span>
						<span class="w-16 text-right font-mono text-[9px] text-muted-foreground">{r.wins}W/{r.losses}L</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Cumulative wins÷losses across all backtest runs · ≥2× = strong win edge · distinct from win rate (wins/total) — measures raw count advantage over losses</p>
		</section>
	{/if}
	{#if runProfitFactorByTimeframe}
		<section class="rounded-lg border border-border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">Median Profit Factor by Timeframe</h2>
			<div class="space-y-1">
				{#each runProfitFactorByTimeframe as r}
					{@const color = r.good ? 'var(--ch-profit-strong)' : r.pf >= 1 ? 'var(--ch-violet)' : 'var(--ch-loss)'}
					<div class="flex items-center gap-2">
						<span class="w-12 text-right font-mono text-[11px] font-medium text-muted-foreground">{r.tf}</span>
						<div class="h-4 flex-1 overflow-hidden rounded-sm bg-muted">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{color}"></div>
						</div>
						<span class="w-12 text-right font-mono text-[10px]" style="color:{color}">{r.pf.toFixed(2)}</span>
						<span class="w-8 text-right font-mono text-[9px] text-muted-foreground">n={r.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Median profit_factor per timeframe · ≥1.5 = solid edge · sorted by TF granularity · identifies which candle period produces best gross-profit to gross-loss ratio</p>
		</section>
	{/if}
	{#if runProfitByTimeframe}
		<section class="rounded-xl border border-border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">Avg Total Profit % by Timeframe</h2>
			<p class="mb-3 text-[10px] text-muted-foreground">Average total_profit_pct across all backtest runs for each timeframe — shows which candle granularity produces highest mean return</p>
			<div class="space-y-2">
				{#each runProfitByTimeframe as r}
					{@const color = r.avg > 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss)'}
					<div class="flex items-center gap-2">
						<span class="w-12 text-right font-mono text-[11px] font-semibold text-muted-foreground">{r.tf}</span>
						<div class="h-4 flex-1 overflow-hidden rounded-sm bg-muted">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{color}"></div>
						</div>
						<span class="w-16 text-right font-mono text-[10px]" style="color:{color}">{r.avg > 0 ? '+' : ''}{r.avg.toFixed(1)}%</span>
						<span class="w-20 text-right font-mono text-[9px] text-muted-foreground">best {r.best.toFixed(1)}% · n={r.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar = normalized avg profit · green = positive mean · best = peak single run · n = run count per timeframe</p>
		</section>
	{/if}
	{#if runSharpeDistribution}
		<section class="rounded-xl border border-border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">Sharpe Ratio Distribution</h2>
			<p class="mb-3 text-[10px] text-muted-foreground">Histogram of Sharpe ratios across all backtest runs · median {runSharpeDistribution.median.toFixed(2)} · {runSharpeDistribution.positive}/{runSharpeDistribution.total} positive</p>
			<div class="flex h-20 items-end gap-0.5">
				{#each runSharpeDistribution.buckets as b}
					{@const pct = (b.count / runSharpeDistribution.maxCount) * 100}
					{@const isPos = b.lo >= 0}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<div class="w-full rounded-t-sm" style="height:{Math.max(2, pct * 0.72)}px; background:{isPos ? 'var(--ch-profit)' : 'var(--ch-loss)'}"></div>
						<span class="w-full truncate text-center font-mono text-[7px] text-muted-foreground">{b.label}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Green = Sharpe ≥ 0 · red = negative · each bin width = {runSharpeDistribution.step.toFixed(2)} · right-skewed distribution = many good runs · left tail = optimizer exploring losses</p>
		</section>
	{/if}
	{#if eventFngMovingAvg}
		<section class="rounded-xl border border-border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">7-Event Rolling Avg F&amp;G Index</h2>
			<p class="mb-2 text-[10px] text-muted-foreground">Smoothed Fear &amp; Greed index at trigger times (7-event window) · latest {eventFngMovingAvg.latest.toFixed(1)} · trend {eventFngMovingAvg.trend > 2 ? '↑ rising greed' : eventFngMovingAvg.trend < -2 ? '↓ rising fear' : '→ stable'}</p>
			<svg viewBox="0 0 {eventFngMovingAvg.W} {eventFngMovingAvg.H}" class="w-full">
				{#if eventFngMovingAvg.y50 !== null}
					<line x1="0" y1={eventFngMovingAvg.y50} x2={eventFngMovingAvg.W} y2={eventFngMovingAvg.y50} stroke="var(--ch-axis-muted)" stroke-width="1" stroke-dasharray="4,3"/>
				{/if}
				<polyline points={eventFngMovingAvg.polyline} fill="none" stroke="var(--ch-warn)" stroke-width="2"/>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Gold line = smoothed FNG at DCA triggers · dashed at 50 (neutral) · rising = triggers increasingly during greed · falling = fear-driven activity · {eventFngMovingAvg.count} data points</p>
		</section>
	{/if}

	{#if runCalmarVsWinRate}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">Calmar vs Win Rate</h3>
			<p class="mb-2 text-[10px] text-muted-foreground">Each dot = one backtest run · x = win rate % · y = Calmar ratio · top-right = high win rate AND strong risk-adjusted return · color = timeframe</p>
			<svg viewBox="0 0 {runCalmarVsWinRate.W} {runCalmarVsWinRate.H}" class="w-full">
				{#if runCalmarVsWinRate.zeroY !== null}
					<line x1="0" y1={runCalmarVsWinRate.zeroY} x2={runCalmarVsWinRate.W} y2={runCalmarVsWinRate.zeroY} stroke="var(--ch-axis-faint)" stroke-width="1" stroke-dasharray="4,3"/>
				{/if}
				{#each runCalmarVsWinRate.dots as d}
					<circle cx={d.cx} cy={d.cy} r="2.5" fill={d.color} opacity="0.8"/>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">{runCalmarVsWinRate.total} runs · {runCalmarVsWinRate.positive} positive Calmar · WR [{runCalmarVsWinRate.wMin}%–{runCalmarVsWinRate.wMax}%] · Calmar [{runCalmarVsWinRate.cMin}–{runCalmarVsWinRate.cMax}] · color = timeframe</p>
		</section>
	{/if}

	{#if runSortinoVsDrawdown}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">Sortino vs Max Drawdown</h3>
			<p class="mb-2 text-[10px] text-muted-foreground">Each dot = one backtest run · x = max drawdown % · y = Sortino ratio · top-left = low drawdown AND strong downside risk control · ideal quadrant</p>
			<svg viewBox="0 0 {runSortinoVsDrawdown.W} {runSortinoVsDrawdown.H}" class="w-full">
				{#if runSortinoVsDrawdown.zeroY !== null}
					<line x1="0" y1={runSortinoVsDrawdown.zeroY} x2={runSortinoVsDrawdown.W} y2={runSortinoVsDrawdown.zeroY} stroke="var(--ch-axis-faint)" stroke-width="1" stroke-dasharray="4,3"/>
				{/if}
				{#each runSortinoVsDrawdown.dots as d}
					<circle cx={d.cx} cy={d.cy} r="2.5" fill={d.color} opacity="0.8"/>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">{runSortinoVsDrawdown.total} runs · {runSortinoVsDrawdown.positive} positive Sortino · DD [{runSortinoVsDrawdown.dMin}%–{runSortinoVsDrawdown.dMax}%] · Sortino [{runSortinoVsDrawdown.sMin}–{runSortinoVsDrawdown.sMax}] · color = timeframe</p>
		</section>
	{/if}

	{#if runProfitFactorVsCalmar}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">Profit Factor vs Calmar Ratio</h3>
			<p class="mb-2 text-[10px] text-muted-foreground">Each dot = one backtest run · x = profit factor · y = Calmar ratio · top-right = gross edge AND strong annual-return/drawdown control · vertical dashed = PF breakeven</p>
			<svg viewBox="0 0 {runProfitFactorVsCalmar.W} {runProfitFactorVsCalmar.H}" class="w-full">
				{#if runProfitFactorVsCalmar.zeroY !== null}
					<line x1="0" y1={runProfitFactorVsCalmar.zeroY} x2={runProfitFactorVsCalmar.W} y2={runProfitFactorVsCalmar.zeroY} stroke="var(--ch-axis-faint)" stroke-width="1" stroke-dasharray="4,3"/>
				{/if}
				{#if runProfitFactorVsCalmar.oneX !== null}
					<line x1={runProfitFactorVsCalmar.oneX} y1="0" x2={runProfitFactorVsCalmar.oneX} y2={runProfitFactorVsCalmar.H} stroke="var(--ch-warn-light)" stroke-width="1" stroke-dasharray="4,3"/>
				{/if}
				{#each runProfitFactorVsCalmar.dots as d}
					<circle cx={d.cx} cy={d.cy} r="2.5" fill={d.color} opacity="0.8"/>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">{runProfitFactorVsCalmar.total} runs · {runProfitFactorVsCalmar.positive} with PF&gt;1 &amp; Calmar&gt;0 · PF [{runProfitFactorVsCalmar.pfMin}–{runProfitFactorVsCalmar.pfMax}] · Calmar [{runProfitFactorVsCalmar.cMin}–{runProfitFactorVsCalmar.cMax}] · color = timeframe</p>
		</section>
	{/if}

	{#if runSharpeVsProfit}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">Sharpe vs Total Profit</h3>
			<p class="mb-2 text-[10px] text-muted-foreground">Each dot = one backtest run · x = Sharpe ratio · y = total profit % · top-right = high profit AND strong risk-adjustment · color = timeframe</p>
			<svg viewBox="0 0 {runSharpeVsProfit.W} {runSharpeVsProfit.H}" class="w-full">
				{#if runSharpeVsProfit.zeroX !== null}
					<line x1={runSharpeVsProfit.zeroX} y1="0" x2={runSharpeVsProfit.zeroX} y2={runSharpeVsProfit.H} stroke="var(--ch-axis-faint)" stroke-width="1" stroke-dasharray="4,3"/>
				{/if}
				{#if runSharpeVsProfit.zeroY !== null}
					<line x1="0" y1={runSharpeVsProfit.zeroY} x2={runSharpeVsProfit.W} y2={runSharpeVsProfit.zeroY} stroke="var(--ch-axis-faint)" stroke-width="1" stroke-dasharray="4,3"/>
				{/if}
				{#each runSharpeVsProfit.dots as d}
					<circle cx={d.cx} cy={d.cy} r="2.5" fill={d.color} opacity="0.8"/>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">{runSharpeVsProfit.total} runs · {runSharpeVsProfit.quadrant} in top-right quadrant · Sharpe [{runSharpeVsProfit.sMin}–{runSharpeVsProfit.sMax}] · Profit [{runSharpeVsProfit.pMin}%–{runSharpeVsProfit.pMax}%] · color = timeframe</p>
		</section>
	{/if}

	{#if runDrawdownByStrategy}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">Avg Max Drawdown by Strategy</h3>
			<p class="mb-2 text-[10px] text-muted-foreground">Average max drawdown % per strategy across all runs · lower = more capital-preserving · sorted best to worst</p>
			<div class="space-y-1">
				{#each runDrawdownByStrategy.rows as row}
					{@const pct = (row.avg / runDrawdownByStrategy.maxAvg * 100).toFixed(1)}
					{@const color = row.avg <= 10 ? 'var(--ch-profit)' : row.avg <= 25 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
					<div class="flex items-center gap-2 text-[10px]">
						<span class="w-36 truncate font-mono text-[9px]">{row.strategy}</span>
						<div class="flex h-3 flex-1 overflow-hidden rounded bg-muted/30">
							<div class="h-full rounded" style="width:{pct}%; background:{color}"></div>
						</div>
						<span class="w-14 text-right font-mono" style="color:{color}">{row.avg.toFixed(1)}%</span>
						<span class="w-10 text-right text-[9px] text-muted-foreground">n={row.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Green ≤10% · yellow 10–25% · red &gt;25% · best drawdown shown in tooltip · pair with Calmar for risk-adjusted comparison</p>
		</section>
	{/if}

	{#if runWinRateVsDrawdown}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">Win Rate vs Max Drawdown</h3>
			<p class="mb-2 text-[10px] text-muted-foreground">Each dot = one backtest run · x = win rate % · y = max drawdown % · ideal = top-left (high WR, low DD) · color = timeframe</p>
			<svg viewBox="0 0 {runWinRateVsDrawdown.W} {runWinRateVsDrawdown.H}" class="w-full">
				{#each runWinRateVsDrawdown.dots as d}
					<circle cx={d.cx} cy={d.cy} r="2.5" fill={d.color} opacity="0.8"/>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">{runWinRateVsDrawdown.total} runs · {runWinRateVsDrawdown.ideal} with WR&gt;55% &amp; DD&lt;15% · WR [{runWinRateVsDrawdown.wrMin}%–{runWinRateVsDrawdown.wrMax}%] · DD [{runWinRateVsDrawdown.dMin}%–{runWinRateVsDrawdown.dMax}%] · color = timeframe</p>
		</section>
	{/if}

	{#if runWeeklyCalmarTimeline}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Weekly Avg Calmar Trend</h3>
			<svg viewBox="0 0 {runWeeklyCalmarTimeline.W} {runWeeklyCalmarTimeline.H}" class="w-full" style="height:100px">
				{#if runWeeklyCalmarTimeline.zeroY !== null}
					<line x1="12" y1={runWeeklyCalmarTimeline.zeroY} x2={runWeeklyCalmarTimeline.W - 12} y2={runWeeklyCalmarTimeline.zeroY} stroke="var(--ch-axis-muted)" stroke-width="1" stroke-dasharray="3,3"/>
				{/if}
				<polyline points={runWeeklyCalmarTimeline.polyline} fill="none" stroke="var(--ch-violet-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				{#each runWeeklyCalmarTimeline.pts as p}
					<circle cx={p.x} cy={p.y} r="2" fill={p.avg >= 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss-strong)'}/>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">{runWeeklyCalmarTimeline.total} weeks · latest avg: {runWeeklyCalmarTimeline.latest} · 2-week trend: {parseFloat(runWeeklyCalmarTimeline.trend) >= 0 ? '+' : ''}{runWeeklyCalmarTimeline.trend} · range [{runWeeklyCalmarTimeline.vMin} – {runWeeklyCalmarTimeline.vMax}]</p>
		</section>
	{/if}

	{#if runWeeklyProfitFactorTimeline}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Weekly Avg Profit Factor Trend</h3>
			<svg viewBox="0 0 {runWeeklyProfitFactorTimeline.W} {runWeeklyProfitFactorTimeline.H}" class="w-full" style="height:90px">
				{#if runWeeklyProfitFactorTimeline.oneY !== null}
					<line x1="0" y1={runWeeklyProfitFactorTimeline.oneY} x2={runWeeklyProfitFactorTimeline.W} y2={runWeeklyProfitFactorTimeline.oneY} stroke="var(--ch-axis-muted)" stroke-width="1" stroke-dasharray="4,3"/>
				{/if}
				<polyline points={runWeeklyProfitFactorTimeline.polyline} fill="none" stroke="var(--ch-warn)" stroke-width="2" stroke-linejoin="round"/>
				{#each runWeeklyProfitFactorTimeline.pts as p}
					<circle cx={p.x} cy={p.y} r="2" fill={p.avg >= 1 ? 'var(--ch-profit-strong)' : 'var(--ch-loss-strong)'}/>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">{runWeeklyProfitFactorTimeline.total} weeks · latest PF: {runWeeklyProfitFactorTimeline.latest} · {runWeeklyProfitFactorTimeline.aboveOne} weeks above PF=1 · dashed = break-even line · green dot = profitable week</p>
		</section>
	{/if}

	{#if runStrategyTimeframeCalmarMatrix}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Calmar Score — Strategy × Timeframe</h3>
			<div class="overflow-x-auto">
				<table class="w-full text-[9px]">
					<thead>
						<tr>
							<th class="w-28 text-left font-normal text-muted-foreground pb-1">Strategy</th>
							{#each runStrategyTimeframeCalmarMatrix.TFS as tf}
								<th class="text-center font-normal text-muted-foreground pb-1 px-1">{tf}</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each runStrategyTimeframeCalmarMatrix.strategies as strategy}
							<tr>
								<td class="truncate text-muted-foreground py-0.5 pr-2 max-w-[112px]">{strategy}</td>
								{#each runStrategyTimeframeCalmarMatrix.TFS as tf}
									{@const cell = runStrategyTimeframeCalmarMatrix.cells.find(c => c.strategy === strategy && c.tf === tf)}
									{@const frac = cell?.avg != null ? (cell.avg - parseFloat(runStrategyTimeframeCalmarMatrix.vMin)) / runStrategyTimeframeCalmarMatrix.vRange : null}
									{@const bg = frac != null ? (cell!.avg! >= 0 ? `rgba(34,197,94,${(0.1 + frac * 0.75).toFixed(2)})` : `rgba(239,68,68,${(0.1 + (1 - frac) * 0.5).toFixed(2)})`) : 'transparent'}
									<td class="text-center py-0.5 px-1 rounded font-mono" style="background:{bg}; color:{frac != null ? (frac > 0.5 ? 'var(--ch-axis-strong)' : 'var(--ch-axis-strong)') : 'rgba(100,100,100,0.4)'}">
										{cell?.avg != null ? cell.avg.toFixed(1) : '—'}
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Avg Calmar per strategy per timeframe · green = positive · red = negative · — = no data · top 10 strategies by overall avg shown</p>
		</section>
	{/if}

	{#if runProfitByDayOfWeek}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Backtest Profit by Day of Week</h3>
			<svg viewBox="0 0 {runProfitByDayOfWeek.W} {runProfitByDayOfWeek.H}" class="w-full" style="height:70px">
				<line x1="0" y1={runProfitByDayOfWeek.H / 2} x2={runProfitByDayOfWeek.W} y2={runProfitByDayOfWeek.H / 2} stroke="var(--ch-axis-faint)" stroke-width="1"/>
				{#each runProfitByDayOfWeek.rows as row, i}
					{@const x = runProfitByDayOfWeek.PAD + i * ((runProfitByDayOfWeek.W - runProfitByDayOfWeek.PAD * 2) / 7)}
					{@const midY = runProfitByDayOfWeek.H / 2}
					{@const barH = Math.max(1, (Math.abs(row.avg) / runProfitByDayOfWeek.maxAbs) * (midY - runProfitByDayOfWeek.PAD - 4))}
					{@const color = row.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					{#if row.avg >= 0}
						<rect x={x} y={midY - barH} width={runProfitByDayOfWeek.barW} height={barH} rx="1" fill={color}/>
					{:else}
						<rect x={x} y={midY} width={runProfitByDayOfWeek.barW} height={barH} rx="1" fill={color}/>
					{/if}
					<text x={x + runProfitByDayOfWeek.barW / 2} y={runProfitByDayOfWeek.H - 2} text-anchor="middle" font-size="8" fill="var(--ch-axis)">{row.day}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg total_profit_pct of runs imported each day of week · green = positive avg · red = negative · bars above/below center line</p>
		</section>
	{/if}

	{#if runSharpeLeaderboard}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Best Sharpe Ratio Leaderboard</h3>
			<div class="space-y-1.5">
				{#each runSharpeLeaderboard.rows as row, i}
					{@const pct = (row.sharpe / runSharpeLeaderboard.maxSharpe * 100).toFixed(1)}
					{@const color = row.sharpe >= 2 ? 'var(--ch-profit)' : row.sharpe >= 1 ? 'var(--ch-violet)' : 'var(--ch-warn)'}
					<div class="flex items-center gap-2">
						<span class="w-5 text-right text-[9px] text-muted-foreground">{i + 1}.</span>
						<span class="w-36 truncate text-[9px] text-muted-foreground">{row.strategy}</span>
						<div class="flex-1 h-3 rounded bg-muted/20 overflow-hidden">
							<div class="h-full rounded" style="width:{pct}%; background:{color}"></div>
						</div>
						<span class="w-12 text-right font-mono text-[10px]" style="color:{color}">{row.sharpe.toFixed(2)}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Best Sharpe ratio per strategy across all runs · green ≥ 2 (excellent) · indigo ≥ 1 (good) · yellow &lt; 1 (marginal)</p>
		</section>
	{/if}

	{#if runWinRateByTimeframe}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Win Rate by Timeframe</h3>
			<svg viewBox="0 0 {runWinRateByTimeframe.W} {runWinRateByTimeframe.H}" class="w-full" style="height:70px">
				{#each runWinRateByTimeframe.rows as row, i}
					{@const x = runWinRateByTimeframe.PAD + i * ((runWinRateByTimeframe.W - runWinRateByTimeframe.PAD * 2) / runWinRateByTimeframe.rows.length)}
					{@const barH = Math.max(2, (row.avg / runWinRateByTimeframe.maxAvg) * (runWinRateByTimeframe.H - runWinRateByTimeframe.PAD * 2 - 10))}
					{@const color = row.avg >= 55 ? 'var(--ch-profit)' : row.avg >= 45 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
					<rect x={x} y={runWinRateByTimeframe.H - 10 - barH} width={runWinRateByTimeframe.barW} height={barH} rx="2" fill={color}/>
					<text x={x + runWinRateByTimeframe.barW / 2} y={runWinRateByTimeframe.H - 1} text-anchor="middle" font-size="8" fill="var(--ch-axis)">{row.tf}</text>
					<text x={x + runWinRateByTimeframe.barW / 2} y={runWinRateByTimeframe.H - 12 - barH} text-anchor="middle" font-size="7" fill={color}>{row.avg.toFixed(0)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg win_rate_pct per timeframe · green ≥ 55% · yellow 45–55% · red &lt; 45% · useful for assessing timeframe-level trade quality</p>
		</section>
	{/if}

	{#if runCalmarByTimeframe}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Calmar Ratio by Timeframe</h3>
			<svg viewBox="0 0 {runCalmarByTimeframe.W} {runCalmarByTimeframe.H}" class="w-full" style="height:80px">
				{#each runCalmarByTimeframe.rows as row, i}
					{@const x = runCalmarByTimeframe.PAD + i * ((runCalmarByTimeframe.W - runCalmarByTimeframe.PAD * 2) / runCalmarByTimeframe.rows.length)}
					{@const barH = Math.max(2, (row.avg / runCalmarByTimeframe.maxAvg) * (runCalmarByTimeframe.H - runCalmarByTimeframe.PAD * 2 - 12))}
					{@const color = row.avg >= 1.5 ? 'var(--ch-violet-strong)' : row.avg >= 0.8 ? 'var(--ch-profit)' : 'var(--ch-warn)'}
					<rect x={x} y={runCalmarByTimeframe.H - 12 - barH} width={runCalmarByTimeframe.barW} height={barH} rx="2" fill={color}/>
					<text x={x + runCalmarByTimeframe.barW / 2} y={runCalmarByTimeframe.H - 1} text-anchor="middle" font-size="8" fill="var(--ch-axis)">{row.tf}</text>
					<text x={x + runCalmarByTimeframe.barW / 2} y={runCalmarByTimeframe.H - 13 - barH} text-anchor="middle" font-size="7" fill={color}>{row.avg.toFixed(2)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg Calmar ratio across all runs per timeframe · indigo ≥1.5 (excellent) · green ≥0.8 (solid) · yellow &lt;0.8 (marginal) · higher Calmar = better risk-adjusted return</p>
		</section>
	{/if}

	{#if runAvgProfitFactorByTF}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Profit Factor by Timeframe</h3>
			<svg viewBox="0 0 {runAvgProfitFactorByTF.W} {runAvgProfitFactorByTF.H}" class="w-full" style="height:80px">
				{#each runAvgProfitFactorByTF.rows as row, i}
					{@const x = runAvgProfitFactorByTF.PAD + i * ((runAvgProfitFactorByTF.W - runAvgProfitFactorByTF.PAD * 2) / runAvgProfitFactorByTF.rows.length)}
					{@const barH = Math.max(2, (row.avg / runAvgProfitFactorByTF.maxAvg) * (runAvgProfitFactorByTF.H - runAvgProfitFactorByTF.PAD * 2 - 12))}
					{@const color = row.avg >= 2 ? 'var(--ch-profit)' : row.avg >= 1.3 ? 'var(--ch-violet)' : 'var(--ch-warn)'}
					<rect x={x} y={runAvgProfitFactorByTF.H - 12 - barH} width={runAvgProfitFactorByTF.barW} height={barH} rx="2" fill={color}/>
					<text x={x + runAvgProfitFactorByTF.barW / 2} y={runAvgProfitFactorByTF.H - 1} text-anchor="middle" font-size="8" fill="var(--ch-axis)">{row.tf}</text>
					<text x={x + runAvgProfitFactorByTF.barW / 2} y={runAvgProfitFactorByTF.H - 13 - barH} text-anchor="middle" font-size="7" fill={color}>{row.avg.toFixed(2)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg profit factor per timeframe · green ≥2 · indigo ≥1.3 · yellow &lt;1.3 · PF = gross profit ÷ gross loss · higher = more consistent winning</p>
		</section>
	{/if}

	{#if runTopPairsByProfit}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Top Pairs by Avg Backtest Profit</h3>
			<svg viewBox="0 0 {runTopPairsByProfit.W} {runTopPairsByProfit.H}" class="w-full" style="height:{runTopPairsByProfit.H}px">
				<line x1={runTopPairsByProfit.midX} y1={runTopPairsByProfit.PAD} x2={runTopPairsByProfit.midX} y2={runTopPairsByProfit.H - runTopPairsByProfit.PAD} stroke="var(--ch-axis-muted)" stroke-width="0.8"/>
				{#each runTopPairsByProfit.rows as row, i}
					{@const cy = runTopPairsByProfit.PAD + i * 14 + 7}
					{@const bw = (Math.abs(row.avg) / runTopPairsByProfit.maxAbs) * runTopPairsByProfit.barMaxW}
					{@const positive = row.avg >= 0}
					{@const color = positive ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect x={positive ? runTopPairsByProfit.midX : runTopPairsByProfit.midX - bw} y={cy - 5} width={bw} height={10} rx="1" fill={color}/>
					<text x={runTopPairsByProfit.midX - 4} y={cy + 3.5} text-anchor="end" font-size="7" fill="var(--ch-axis-strong)">{row.pair}</text>
					<text x={runTopPairsByProfit.midX + bw + 3} y={cy + 3.5} font-size="7" fill={color}>{row.avg >= 0 ? '+' : ''}{row.avg.toFixed(2)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg total profit % per pair across all runs that include it · reveals which pairs consistently contribute to profitable strategies</p>
		</section>
	{/if}

	{#if runSortinoLeaderboard}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Best Sortino Ratio Leaderboard</h3>
			<div class="space-y-1.5">
				{#each runSortinoLeaderboard.rows as row, i}
					{@const pct = (row.sortino / runSortinoLeaderboard.maxSortino * 100).toFixed(1)}
					{@const color = row.sortino >= 3 ? 'var(--ch-profit)' : row.sortino >= 1.5 ? 'var(--ch-violet)' : 'var(--ch-warn)'}
					<div class="flex items-center gap-2">
						<span class="w-5 text-right text-[9px] text-muted-foreground">{i + 1}.</span>
						<span class="w-36 truncate text-[9px] text-muted-foreground">{row.strategy}</span>
						<div class="flex-1 h-3 rounded bg-muted/20 overflow-hidden">
							<div class="h-full rounded" style="width:{pct}%; background:{color}"></div>
						</div>
						<span class="w-12 text-right font-mono text-[10px]" style="color:{color}">{row.sortino.toFixed(2)}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Best Sortino per strategy across all backtest runs · green ≥3 · indigo ≥1.5 · yellow &lt;1.5 · complements Sharpe leaderboard above</p>
		</section>
	{/if}

	{#if runProfitDistributionHistogram}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Total Profit % Distribution ({runProfitDistributionHistogram.pct}% runs profitable)</h3>
			<svg viewBox="0 0 {runProfitDistributionHistogram.W} {runProfitDistributionHistogram.H}" class="w-full" style="height:72px">
				{#each runProfitDistributionHistogram.counts as b, i}
					{@const x = runProfitDistributionHistogram.PAD + i * (runProfitDistributionHistogram.barW + 1)}
					{@const barH = Math.max(1, (b.count / runProfitDistributionHistogram.maxCount) * (runProfitDistributionHistogram.H - runProfitDistributionHistogram.PAD * 2 - 10))}
					{@const color = b.lo >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect x={x} y={runProfitDistributionHistogram.H - 10 - barH} width={runProfitDistributionHistogram.barW} height={barH} rx="1" fill={color}/>
				{/each}
				<text x={runProfitDistributionHistogram.PAD} y={runProfitDistributionHistogram.H - 1} font-size="7" fill="var(--ch-axis)">{runProfitDistributionHistogram.mn}%</text>
				<text x={runProfitDistributionHistogram.W - runProfitDistributionHistogram.PAD} y={runProfitDistributionHistogram.H - 1} text-anchor="end" font-size="7" fill="var(--ch-axis)">{runProfitDistributionHistogram.mx}%</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">{runProfitDistributionHistogram.total} runs · avg {runProfitDistributionHistogram.avg}% · green = profitable bins · red = losing · right-skewed distribution = research pipeline tilted toward winners</p>
		</section>
	{/if}

	{#if runTopStrategyByWinRate}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Top Strategies by Avg Win Rate (min 3 runs)</h3>
			<div class="space-y-1.5">
				{#each runTopStrategyByWinRate.rows as row, i}
					{@const pct = (row.wr / runTopStrategyByWinRate.maxWr * 100).toFixed(1)}
					{@const color = row.avgProfit >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<div class="flex items-center gap-2">
						<span class="w-5 text-right text-[9px] text-muted-foreground">{i + 1}.</span>
						<span class="w-36 truncate text-[9px] text-muted-foreground">{row.strat}</span>
						<div class="flex-1 h-3 rounded bg-muted/20 overflow-hidden">
							<div class="h-full rounded" style="width:{pct}%; background:{color}"></div>
						</div>
						<span class="w-10 text-right font-mono text-[10px]" style="color:{color}">{row.wr.toFixed(0)}%</span>
						<span class="w-16 text-right text-[9px] text-muted-foreground">avg {row.avgProfit >= 0 ? '+' : ''}{row.avgProfit.toFixed(1)}%·{row.count}r</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Average win rate per strategy · green=positive avg profit · red=losing on average · high win rate with green color = genuinely good signal quality</p>
		</section>
	{/if}

	{#if runSharpeVsCalmarScatter}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Sharpe vs Calmar Scatter ({runSharpeVsCalmarScatter.count} runs)</h3>
			<svg viewBox="0 0 {runSharpeVsCalmarScatter.W} {runSharpeVsCalmarScatter.H}" class="w-full" style="height:105px">
				{#each runSharpeVsCalmarScatter.dots as d}
					<circle cx={d.cx} cy={d.cy} r="2.5" fill={d.color}/>
				{/each}
				<text x={runSharpeVsCalmarScatter.PAD} y={runSharpeVsCalmarScatter.H - 2} font-size="6.5" fill="var(--ch-axis-muted)">Sharpe {runSharpeVsCalmarScatter.sMin}</text>
				<text x={runSharpeVsCalmarScatter.W - runSharpeVsCalmarScatter.PAD} y={runSharpeVsCalmarScatter.H - 2} text-anchor="end" font-size="6.5" fill="var(--ch-axis-muted)">{runSharpeVsCalmarScatter.sMax}</text>
				<text x={runSharpeVsCalmarScatter.PAD - 2} y={runSharpeVsCalmarScatter.PAD + 4} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{runSharpeVsCalmarScatter.cMax}</text>
				<text x={runSharpeVsCalmarScatter.PAD - 2} y={runSharpeVsCalmarScatter.H - runSharpeVsCalmarScatter.PAD} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{runSharpeVsCalmarScatter.cMin}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">x=Sharpe · y=Calmar · green=profitable run · red=losing · top-right corner = best risk-adjusted quality on both metrics simultaneously</p>
		</section>
	{/if}

	{#if runProfitByPairCount}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Profit by Pair Count Bucket</h3>
			<svg viewBox="0 0 {runProfitByPairCount.W} {runProfitByPairCount.H}" class="w-full" style="height:75px">
				<line x1={runProfitByPairCount.PAD} y1={runProfitByPairCount.midY} x2={runProfitByPairCount.W - runProfitByPairCount.PAD} y2={runProfitByPairCount.midY} stroke="var(--ch-axis-faint)" stroke-width="0.8"/>
				{#each runProfitByPairCount.rows as row, i}
					{@const x = runProfitByPairCount.PAD + i * (runProfitByPairCount.barW + 4)}
					{@const bh = Math.max(2, (Math.abs(row.avg) / runProfitByPairCount.maxAbs) * (runProfitByPairCount.midY - runProfitByPairCount.PAD - 10))}
					{@const positive = row.avg >= 0}
					{@const color = positive ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect x={x} y={positive ? runProfitByPairCount.midY - bh : runProfitByPairCount.midY} width={runProfitByPairCount.barW} height={bh} rx="2" fill={color}/>
					<text x={x + runProfitByPairCount.barW / 2} y={runProfitByPairCount.H - 1} text-anchor="middle" font-size="7.5" fill="var(--ch-axis)">{row.label}</text>
					<text x={x + runProfitByPairCount.barW / 2} y={positive ? runProfitByPairCount.midY - bh - 2 : runProfitByPairCount.midY + bh + 8} text-anchor="middle" font-size="6.5" fill={color}>{row.avg >= 0 ? '+' : ''}{row.avg.toFixed(1)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg total profit % grouped by number of pairs in the backtest · reveals whether diversification improves or hurts strategy performance</p>
		</section>
	{/if}
	{#if runCalmarByFactorCount}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Calmar by Factor Count</h3>
			<svg viewBox="0 0 {runCalmarByFactorCount.W} {runCalmarByFactorCount.H}" class="w-full" style="height:70px">
				<line x1={runCalmarByFactorCount.PAD} y1={runCalmarByFactorCount.midY} x2={runCalmarByFactorCount.W - runCalmarByFactorCount.PAD} y2={runCalmarByFactorCount.midY} stroke="var(--ch-axis-faint)" stroke-width="0.7"/>
				{#each runCalmarByFactorCount.rows as row, i}
					{@const x = runCalmarByFactorCount.PAD + i * (runCalmarByFactorCount.barW + 3)}
					{@const bh = Math.max(2, (Math.abs(row.avg) / runCalmarByFactorCount.maxAbs) * (runCalmarByFactorCount.midY - runCalmarByFactorCount.PAD))}
					{@const color = row.avg >= 1 ? 'var(--ch-profit)' : row.avg >= 0 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
					<rect {x} y={row.avg >= 0 ? runCalmarByFactorCount.midY - bh : runCalmarByFactorCount.midY} width={runCalmarByFactorCount.barW} height={bh} rx="1" fill={color}/>
					<text x={x + runCalmarByFactorCount.barW / 2} y={runCalmarByFactorCount.H - 1} text-anchor="middle" font-size="7.5" fill="var(--ch-axis)">{row.label}f</text>
					<text x={x + runCalmarByFactorCount.barW / 2} y={row.avg >= 0 ? runCalmarByFactorCount.midY - bh - 2 : runCalmarByFactorCount.midY + bh + 8} text-anchor="middle" font-size="6" fill={color}>{row.avg.toFixed(2)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg Calmar ratio by number of strategy factors · green≥1 · yellow≥0 · reveals whether adding more factor signals improves drawdown-adjusted returns</p>
		</section>
	{/if}
	{#if runWinRateVsProfitFactor}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Win Rate vs Profit Factor ({runWinRateVsProfitFactor.count} runs)</h3>
			<svg viewBox="0 0 {runWinRateVsProfitFactor.W} {runWinRateVsProfitFactor.H}" class="w-full" style="height:95px">
				{#each runWinRateVsProfitFactor.dots as d}
					<circle cx={d.cx} cy={d.cy} r="2.5" fill={d.color}/>
				{/each}
				<text x={runWinRateVsProfitFactor.PAD} y={runWinRateVsProfitFactor.H - 2} font-size="6.5" fill="var(--ch-axis-muted)">WR {runWinRateVsProfitFactor.wrMin}%</text>
				<text x={runWinRateVsProfitFactor.W - runWinRateVsProfitFactor.PAD} y={runWinRateVsProfitFactor.H - 2} text-anchor="end" font-size="6.5" fill="var(--ch-axis-muted)">{runWinRateVsProfitFactor.wrMax}%</text>
				<text x={runWinRateVsProfitFactor.PAD} y={runWinRateVsProfitFactor.PAD + 4} font-size="6" fill="var(--ch-axis-muted)">PF {runWinRateVsProfitFactor.pfMax}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">x=win rate % · y=profit factor · green=profit≥10% · yellow≥0% · red=losing · top-right = high win rate AND favorable win/loss ratio simultaneously</p>
		</section>
	{/if}
	{#if runProfitDecileChart}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Profit % Decile Distribution ({runProfitDecileChart.count} runs)</h3>
			<svg viewBox="0 0 {runProfitDecileChart.W} {runProfitDecileChart.H}" class="w-full" style="height:60px">
				<line x1={runProfitDecileChart.PAD} y1={runProfitDecileChart.zero} x2={runProfitDecileChart.W - runProfitDecileChart.PAD} y2={runProfitDecileChart.zero} stroke="var(--ch-axis-faint)" stroke-width="0.8" stroke-dasharray="2,2"/>
				{#each runProfitDecileChart.deciles as d, i}
					{@const x = runProfitDecileChart.PAD + i * (runProfitDecileChart.barW + 2)}
					{@const normH = (Math.abs(d.val) / runProfitDecileChart.range) * (runProfitDecileChart.H - runProfitDecileChart.PAD * 2)}
					{@const bh = Math.max(1.5, normH)}
					{@const color = d.val >= 0 ? `rgba(34,197,94,${0.35 + (i / 9) * 0.45})` : `rgba(239,68,68,${0.7 - (i / 9) * 0.35})`}
					<rect {x} y={d.val >= 0 ? runProfitDecileChart.zero - bh : runProfitDecileChart.zero} width={runProfitDecileChart.barW} height={bh} rx="1" fill={color}/>
					<text x={x + runProfitDecileChart.barW / 2} y={runProfitDecileChart.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{d.p}</text>
				{/each}
				<text x={runProfitDecileChart.PAD} y={runProfitDecileChart.PAD + 4} font-size="5.5" fill="var(--ch-axis-muted)">{runProfitDecileChart.mx.toFixed(1)}%</text>
				<text x={runProfitDecileChart.PAD} y={runProfitDecileChart.H - runProfitDecileChart.PAD} font-size="5.5" fill="var(--ch-axis-muted)">{runProfitDecileChart.mn.toFixed(1)}%</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">10th–90th percentile profit % across all runs · x-labels = percentile · green = positive · red = negative · shows profit distribution skew</p>
		</section>
	{/if}
	{#if runSharpeByTimeframe}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Sharpe Ratio by Timeframe</h3>
			<svg viewBox="0 0 {runSharpeByTimeframe.W} {runSharpeByTimeframe.H}" class="w-full" style="height:72px">
				<line x1={runSharpeByTimeframe.PAD} y1={runSharpeByTimeframe.midY} x2={runSharpeByTimeframe.W - runSharpeByTimeframe.PAD} y2={runSharpeByTimeframe.midY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each runSharpeByTimeframe.rows as row, i}
					{@const x = runSharpeByTimeframe.PAD + i * (runSharpeByTimeframe.barW + 3)}
					{@const bh = Math.max(2, (Math.abs(row.avg) / runSharpeByTimeframe.maxAbs) * (runSharpeByTimeframe.midY - runSharpeByTimeframe.PAD))}
					{@const color = row.avg >= 1 ? 'var(--ch-profit)' : row.avg >= 0 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
					<rect {x} y={row.avg >= 0 ? runSharpeByTimeframe.midY - bh : runSharpeByTimeframe.midY} width={runSharpeByTimeframe.barW} height={bh} rx="1" fill={color}/>
					<text x={x + runSharpeByTimeframe.barW / 2} y={runSharpeByTimeframe.H - 1} text-anchor="middle" font-size="7" fill="var(--ch-axis)">{row.tf}</text>
					<text x={x + runSharpeByTimeframe.barW / 2} y={row.avg >= 0 ? runSharpeByTimeframe.midY - bh - 2 : runSharpeByTimeframe.midY + bh + 8} text-anchor="middle" font-size="6" fill={color}>{row.avg >= 0 ? '+' : ''}{row.avg.toFixed(2)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Average Sharpe ratio per timeframe · green≥1 · yellow≥0 · red=negative · identifies which timeframes consistently produce better risk-adjusted performance</p>
		</section>
	{/if}
	{#if runTopStrategyMonthlyTrend}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Top-3 Strategy Monthly Avg Profit Trend</h3>
			<svg viewBox="0 0 {runTopStrategyMonthlyTrend.W} {runTopStrategyMonthlyTrend.H}" class="w-full" style="height:80px">
				<line x1={runTopStrategyMonthlyTrend.PAD} y1={runTopStrategyMonthlyTrend.zeroY} x2={runTopStrategyMonthlyTrend.W - runTopStrategyMonthlyTrend.PAD} y2={runTopStrategyMonthlyTrend.zeroY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each runTopStrategyMonthlyTrend.polylines as line}
					<polyline points={line.poly} fill="none" stroke={line.color} stroke-width="1.5" stroke-linejoin="round"/>
				{/each}
				{#each runTopStrategyMonthlyTrend.allMonths as mo, i}
					{#if i % Math.max(1, Math.floor(runTopStrategyMonthlyTrend.allMonths.length / 5)) === 0}
						{@const x = runTopStrategyMonthlyTrend.PAD + (i / Math.max(runTopStrategyMonthlyTrend.allMonths.length - 1, 1)) * (runTopStrategyMonthlyTrend.W - runTopStrategyMonthlyTrend.PAD * 2)}
						<text {x} y={runTopStrategyMonthlyTrend.H - 1} text-anchor="middle" font-size="6" fill="var(--ch-axis-muted)">{mo.slice(5)}</text>
					{/if}
				{/each}
			</svg>
			<div class="mt-1 flex flex-wrap gap-2 text-[9px]">
				{#each runTopStrategyMonthlyTrend.polylines as line}
					<span style="color:{line.color}">■ {line.strat}</span>
				{/each}
				<span class="text-muted-foreground">· top 3 by cumulative profit · monthly avg across runs</span>
			</div>
		</section>
	{/if}

	{#if runSortinoVsCalmarScatter}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Sortino vs Calmar Scatter ({runSortinoVsCalmarScatter.count} runs)</h3>
			<svg viewBox="0 0 {runSortinoVsCalmarScatter.W} {runSortinoVsCalmarScatter.H}" class="w-full" style="height:92px">
				<line x1={runSortinoVsCalmarScatter.zeroX} y1={runSortinoVsCalmarScatter.PAD} x2={runSortinoVsCalmarScatter.zeroX} y2={runSortinoVsCalmarScatter.H - runSortinoVsCalmarScatter.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				<line x1={runSortinoVsCalmarScatter.PAD} y1={runSortinoVsCalmarScatter.zeroY} x2={runSortinoVsCalmarScatter.W - runSortinoVsCalmarScatter.PAD} y2={runSortinoVsCalmarScatter.zeroY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each runSortinoVsCalmarScatter.dots as d}
					<circle cx={d.cx} cy={d.cy} r="2.5" fill={d.color}/>
				{/each}
				<text x={runSortinoVsCalmarScatter.PAD} y={runSortinoVsCalmarScatter.H - 2} font-size="6.5" fill="var(--ch-axis-muted)">Sortino {runSortinoVsCalmarScatter.soMin}</text>
				<text x={runSortinoVsCalmarScatter.W - runSortinoVsCalmarScatter.PAD} y={runSortinoVsCalmarScatter.H - 2} text-anchor="end" font-size="6.5" fill="var(--ch-axis-muted)">{runSortinoVsCalmarScatter.soMax}</text>
				<text x={runSortinoVsCalmarScatter.PAD} y={runSortinoVsCalmarScatter.PAD + 5} font-size="6" fill="var(--ch-axis-muted)">Calmar {runSortinoVsCalmarScatter.cMax}</text>
				<text x={runSortinoVsCalmarScatter.PAD} y={runSortinoVsCalmarScatter.H - runSortinoVsCalmarScatter.PAD + 2} font-size="6" fill="var(--ch-axis-muted)">{runSortinoVsCalmarScatter.cMin}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">x=Sortino · y=Calmar · green=profit≥10% · yellow=profit≥0 · red=loss · top-right = best downside-adjusted AND drawdown-adjusted performance simultaneously</p>
		</section>
	{/if}

	{#if runMaxDrawdownByTimeframe}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Max Drawdown by Timeframe</h3>
			<svg viewBox="0 0 {runMaxDrawdownByTimeframe.W} {runMaxDrawdownByTimeframe.H}" class="w-full" style="height:{runMaxDrawdownByTimeframe.H}px">
				{#each runMaxDrawdownByTimeframe.rows as row, i}
					{@const y = i * 18 + 4}
					{@const bw = Math.max(2, (row.avg / runMaxDrawdownByTimeframe.maxVal) * runMaxDrawdownByTimeframe.barMaxW)}
					{@const alpha = 0.35 + (row.avg / runMaxDrawdownByTimeframe.maxVal) * 0.5}
					<text x={runMaxDrawdownByTimeframe.PAD} y={y + 11} font-size="8" fill="var(--ch-axis-strong)">{row.tf}</text>
					<rect x={runMaxDrawdownByTimeframe.PAD + 30} {y} width={bw} height="13" rx="2" fill="rgba(239,68,68,{alpha})"/>
					<text x={runMaxDrawdownByTimeframe.PAD + 30 + bw + 3} y={y + 10} font-size="7" fill="var(--ch-loss-strong)">-{row.avg.toFixed(1)}%</text>
					<text x={runMaxDrawdownByTimeframe.W - 2} y={y + 10} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{row.count}r</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Average max drawdown % per timeframe · longer bar = deeper drawdowns typical for that timeframe · count = number of runs</p>
		</section>
	{/if}

	{#if runProfitByFactorCount}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Profit by Factor Count</h3>
			<svg viewBox="0 0 {runProfitByFactorCount.W} {runProfitByFactorCount.H}" class="w-full" style="height:72px">
				<line x1={runProfitByFactorCount.PAD} y1={runProfitByFactorCount.midY} x2={runProfitByFactorCount.W - runProfitByFactorCount.PAD} y2={runProfitByFactorCount.midY} stroke="var(--ch-axis-faint)" stroke-width="0.7"/>
				{#each runProfitByFactorCount.rows as row, i}
					{@const x = runProfitByFactorCount.PAD + i * (runProfitByFactorCount.barW + 3)}
					{@const bh = Math.max(2, (Math.abs(row.avg) / runProfitByFactorCount.maxAbs) * (runProfitByFactorCount.midY - runProfitByFactorCount.PAD - 4))}
					{@const color = row.avg >= 2 ? 'var(--ch-profit)' : row.avg >= 0 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
					<rect {x} y={row.avg >= 0 ? runProfitByFactorCount.midY - bh : runProfitByFactorCount.midY} width={runProfitByFactorCount.barW} height={bh} rx="2" fill={color}/>
					<text x={x + runProfitByFactorCount.barW / 2} y={runProfitByFactorCount.H - runProfitByFactorCount.PAD + 5} text-anchor="middle" font-size="6.5" fill="var(--ch-axis)">{row.fc}f</text>
					<text x={x + runProfitByFactorCount.barW / 2} y={row.avg >= 0 ? runProfitByFactorCount.midY - bh - 2 : runProfitByFactorCount.midY + bh + 8} text-anchor="middle" font-size="5.5" fill={color}>{row.avg >= 0 ? '+' : ''}{row.avg.toFixed(1)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg total profit % grouped by number of factors used · x-labels = factor count · reveals whether more factors improve or hurt backtest performance</p>
		</section>
	{/if}
	{#if runCalmarVsDrawdownScatter}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Calmar vs Max Drawdown</h3>
			<svg viewBox="0 0 {runCalmarVsDrawdownScatter.W} {runCalmarVsDrawdownScatter.H}" class="w-full" style="height:{runCalmarVsDrawdownScatter.H}px">
				<line x1={runCalmarVsDrawdownScatter.zeroX} y1={runCalmarVsDrawdownScatter.PAD} x2={runCalmarVsDrawdownScatter.zeroX} y2={runCalmarVsDrawdownScatter.H - runCalmarVsDrawdownScatter.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.8" stroke-dasharray="3,2"/>
				{#each runCalmarVsDrawdownScatter.dots as d}
					<circle cx={d.cx} cy={d.cy} r="2" fill={d.color}/>
				{/each}
				<text x={runCalmarVsDrawdownScatter.PAD} y={runCalmarVsDrawdownScatter.H - 2} font-size="6" fill="var(--ch-axis-muted)">Cal {runCalmarVsDrawdownScatter.calMin}</text>
				<text x={runCalmarVsDrawdownScatter.W - runCalmarVsDrawdownScatter.PAD} y={runCalmarVsDrawdownScatter.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{runCalmarVsDrawdownScatter.calMax}</text>
				<text x={runCalmarVsDrawdownScatter.PAD} y={runCalmarVsDrawdownScatter.PAD + 4} font-size="6" fill="var(--ch-axis-muted)">DD {runCalmarVsDrawdownScatter.ddMax}%</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">x=Calmar ratio · y=max drawdown % · green≥2 · yellow≥0 · red&lt;0 · dashed zero line · ideal = high Calmar (right) with low drawdown (bottom)</p>
		</section>
	{/if}
	{#if runWinRateHistogram}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Win Rate % Distribution</h3>
			<svg viewBox="0 0 {runWinRateHistogram.W} {runWinRateHistogram.H}" class="w-full" style="height:{runWinRateHistogram.H}px">
				<line x1={runWinRateHistogram.x50} y1="0" x2={runWinRateHistogram.x50} y2={runWinRateHistogram.H - 14} stroke="var(--ch-axis-muted)" stroke-width="0.8" stroke-dasharray="3,2"/>
				{#each runWinRateHistogram.bars as bar}
					<rect x={bar.x} y={runWinRateHistogram.H - 14 - bar.h} width={runWinRateHistogram.bw} height={bar.h} rx="1" fill={bar.color}/>
				{/each}
				<text x={runWinRateHistogram.PAD} y={runWinRateHistogram.H - 2} font-size="7" fill="var(--ch-axis)">0%</text>
				<text x={runWinRateHistogram.x50} y={runWinRateHistogram.H - 2} text-anchor="middle" font-size="7" fill="var(--ch-axis-muted)">50%</text>
				<text x={runWinRateHistogram.W - runWinRateHistogram.PAD} y={runWinRateHistogram.H - 2} text-anchor="end" font-size="7" fill="var(--ch-axis)">100%</text>
				<text x={runWinRateHistogram.W / 2} y={runWinRateHistogram.PAD + 5} text-anchor="middle" font-size="6" fill="var(--ch-axis-muted)">n={runWinRateHistogram.total}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Distribution of win rate % across all backtest runs · green≥50% · red&lt;50% · dashed 50% line · reveals what fraction of strategies achieve better than coin-flip win rates</p>
		</section>
	{/if}
	{#if runTopStrategyBySharpe}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Top Strategies by Best Sharpe</h3>
			<svg viewBox="0 0 {runTopStrategyBySharpe.W} {runTopStrategyBySharpe.H}" class="w-full" style="height:{runTopStrategyBySharpe.H}px">
				{#each runTopStrategyBySharpe.rows as row, i}
					{@const y = i * 16 + 2}
					{@const bw = Math.max(2, (row.best / runTopStrategyBySharpe.maxVal) * runTopStrategyBySharpe.barMaxW)}
					{@const color = row.best >= 2 ? 'var(--ch-profit)' : row.best >= 1 ? 'var(--ch-warn)' : 'var(--ch-violet)'}
					<text x={runTopStrategyBySharpe.PAD} y={y + 10} font-size="7" fill="var(--ch-axis-strong)">{row.strat}</text>
					<rect x={runTopStrategyBySharpe.PAD + 118} {y} width={bw} height="12" rx="2" fill={color}/>
					<text x={runTopStrategyBySharpe.PAD + 118 + bw + 3} y={y + 10} font-size="7" fill={color}>{row.best.toFixed(2)}</text>
					<text x={runTopStrategyBySharpe.W - 2} y={y + 10} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{row.count}r</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Strategies ranked by best Sharpe ratio across all backtest runs · green≥2 · yellow≥1 · indigo&lt;1 · count=runs · reveals which strategies achieve the best risk-adjusted returns</p>
		</section>
	{/if}
	{#if runMonthlyProfitByTF}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Avg Profit % by Timeframe × Month</h3>
			<svg viewBox="0 0 {runMonthlyProfitByTF.W} {runMonthlyProfitByTF.H}" class="w-full" style="height:{runMonthlyProfitByTF.H}px">
				{#each runMonthlyProfitByTF.tfs as tf, ti}
					<text x={runMonthlyProfitByTF.PAD - 2} y={runMonthlyProfitByTF.PAD + ti * runMonthlyProfitByTF.CH + runMonthlyProfitByTF.CH - 3} text-anchor="end" font-size="6.5" fill="var(--ch-axis-strong)">{tf}</text>
					{#each runMonthlyProfitByTF.months as mo, mi}
						{@const val = runMonthlyProfitByTF.grid[ti][mi]}
						{@const alpha = val !== null ? Math.min(0.85, Math.abs(val) / runMonthlyProfitByTF.maxAbs * 0.8 + 0.1) : 0.05}
						{@const fill = val === null ? 'var(--ch-axis-faint)' : val >= 0 ? `rgba(34,197,94,${alpha})` : `rgba(239,68,68,${alpha})`}
						<rect x={runMonthlyProfitByTF.PAD + mi * runMonthlyProfitByTF.CW} y={runMonthlyProfitByTF.PAD + ti * runMonthlyProfitByTF.CH} width={runMonthlyProfitByTF.CW - 1} height={runMonthlyProfitByTF.CH - 1} fill={fill} rx="1"/>
						{#if val !== null}
							<text x={runMonthlyProfitByTF.PAD + mi * runMonthlyProfitByTF.CW + runMonthlyProfitByTF.CW / 2} y={runMonthlyProfitByTF.PAD + ti * runMonthlyProfitByTF.CH + runMonthlyProfitByTF.CH - 3} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-strong)">{val.toFixed(1)}</text>
						{/if}
					{/each}
				{/each}
				{#each runMonthlyProfitByTF.months as mo, mi}
					<text x={runMonthlyProfitByTF.PAD + mi * runMonthlyProfitByTF.CW + runMonthlyProfitByTF.CW / 2} y={runMonthlyProfitByTF.PAD - 3} text-anchor="middle" font-size="6" fill="var(--ch-axis-muted)">{mo}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Heatmap of avg profit % per timeframe (rows) × month (columns) · green=positive · red=negative · intensity=magnitude · reveals which TF+month combinations are most profitable</p>
		</section>
	{/if}
	{#if runSortinoMonthlyTrend}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Monthly Avg Sortino Trend</h3>
			<svg viewBox="0 0 {runSortinoMonthlyTrend.W} {runSortinoMonthlyTrend.H}" class="w-full" style="height:{runSortinoMonthlyTrend.H}px">
				<polygon points={runSortinoMonthlyTrend.area} fill={runSortinoMonthlyTrend.fillColor}/>
				<line x1={runSortinoMonthlyTrend.PAD} y1={runSortinoMonthlyTrend.zeroY} x2={runSortinoMonthlyTrend.W - runSortinoMonthlyTrend.PAD} y2={runSortinoMonthlyTrend.zeroY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				<polyline points={runSortinoMonthlyTrend.polyline} fill="none" stroke={runSortinoMonthlyTrend.color} stroke-width="1.5" stroke-linejoin="round"/>
				<text x={runSortinoMonthlyTrend.PAD} y={runSortinoMonthlyTrend.H - 2} font-size="6" fill="var(--ch-axis-muted)">{runSortinoMonthlyTrend.firstMo}</text>
				<text x={runSortinoMonthlyTrend.W - runSortinoMonthlyTrend.PAD} y={runSortinoMonthlyTrend.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{runSortinoMonthlyTrend.lastMo}</text>
				<text x={runSortinoMonthlyTrend.W - runSortinoMonthlyTrend.PAD} y={runSortinoMonthlyTrend.PAD + 6} text-anchor="end" font-size="7" fill={runSortinoMonthlyTrend.color}>{runSortinoMonthlyTrend.last}</text>
				<text x={runSortinoMonthlyTrend.PAD} y={runSortinoMonthlyTrend.PAD + 6} font-size="6" fill="var(--ch-axis-muted)">Sortino</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Monthly avg Sortino ratio across backtest runs · green≥1 · yellow≥0 · red&lt;0 · zero baseline · reveals trend in downside-risk-adjusted return quality over time</p>
		</section>
	{/if}
	{#if runProfitFactorMonthlyTrend}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Profit Factor Monthly Trend</h3>
			<svg viewBox="0 0 {runProfitFactorMonthlyTrend.W} {runProfitFactorMonthlyTrend.H}" class="w-full" style="height:{runProfitFactorMonthlyTrend.H}px">
				<line x1={runProfitFactorMonthlyTrend.PAD} y1={runProfitFactorMonthlyTrend.oneY} x2={runProfitFactorMonthlyTrend.W - runProfitFactorMonthlyTrend.PAD} y2={runProfitFactorMonthlyTrend.oneY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				<polyline points={runProfitFactorMonthlyTrend.polyline} fill="none" stroke={runProfitFactorMonthlyTrend.color} stroke-width="1.5" stroke-linejoin="round"/>
				{#each runProfitFactorMonthlyTrend.pts as p, i}
					{#if i === 0 || i === runProfitFactorMonthlyTrend.pts.length - 1}
						<text x={runProfitFactorMonthlyTrend.toX(i)} y={runProfitFactorMonthlyTrend.H - 2} text-anchor={i === 0 ? 'start' : 'end'} font-size="6" fill="var(--ch-axis-muted)">{p.m}</text>
					{/if}
				{/each}
				<text x={runProfitFactorMonthlyTrend.W - runProfitFactorMonthlyTrend.PAD} y={runProfitFactorMonthlyTrend.PAD + 6} text-anchor="end" font-size="7" fill={runProfitFactorMonthlyTrend.color}>{runProfitFactorMonthlyTrend.last}</text>
				<text x={runProfitFactorMonthlyTrend.PAD} y={runProfitFactorMonthlyTrend.PAD + 6} font-size="6" fill="var(--ch-axis-muted)">PF</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Monthly avg profit factor across backtest runs · green≥1.5 · yellow≥1 · red&lt;1 · dashed line at PF=1 · reveals whether strategy exploration is finding edge</p>
		</section>
	{/if}
	{#if runWinRateVsSharpeScatter}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Win Rate vs Sharpe (per Run)</h3>
			<svg viewBox="0 0 {runWinRateVsSharpeScatter.W} {runWinRateVsSharpeScatter.H}" class="w-full" style="height:{runWinRateVsSharpeScatter.H}px">
				<line x1={runWinRateVsSharpeScatter.PAD} y1={runWinRateVsSharpeScatter.H - runWinRateVsSharpeScatter.PAD} x2={runWinRateVsSharpeScatter.W - runWinRateVsSharpeScatter.PAD} y2={runWinRateVsSharpeScatter.H - runWinRateVsSharpeScatter.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.7"/>
				<line x1={runWinRateVsSharpeScatter.PAD} y1={runWinRateVsSharpeScatter.zeroY} x2={runWinRateVsSharpeScatter.W - runWinRateVsSharpeScatter.PAD} y2={runWinRateVsSharpeScatter.zeroY} stroke="var(--ch-axis-faint)" stroke-width="0.6" stroke-dasharray="3,2"/>
				{#each runWinRateVsSharpeScatter.pts as p}
					{@const cx = runWinRateVsSharpeScatter.toX(p.wr)}
					{@const cy = runWinRateVsSharpeScatter.toY(p.sh)}
					{@const col = p.profit >= 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'}
					<circle {cx} {cy} r="2" fill={col}/>
				{/each}
				<text x={runWinRateVsSharpeScatter.PAD} y={runWinRateVsSharpeScatter.PAD + 6} font-size="6" fill="var(--ch-axis-muted)">sh {runWinRateVsSharpeScatter.shMax}</text>
				<text x={runWinRateVsSharpeScatter.W - runWinRateVsSharpeScatter.PAD} y={runWinRateVsSharpeScatter.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">wr 100%</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Scatter of win rate % (X) vs Sharpe ratio (Y) · green=profitable run · red=loss · upper-right is best; reveals whether high win rate actually correlates with better risk-adjusted returns</p>
		</section>
	{/if}
	{#if runDrawdownVsProfitScatter}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Max Drawdown vs Total Profit (per Run)</h3>
			<svg viewBox="0 0 {runDrawdownVsProfitScatter.W} {runDrawdownVsProfitScatter.H}" class="w-full" style="height:{runDrawdownVsProfitScatter.H}px">
				<line x1={runDrawdownVsProfitScatter.PAD} y1={runDrawdownVsProfitScatter.zeroY} x2={runDrawdownVsProfitScatter.W - runDrawdownVsProfitScatter.PAD} y2={runDrawdownVsProfitScatter.zeroY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				<line x1={runDrawdownVsProfitScatter.PAD} y1={runDrawdownVsProfitScatter.PAD} x2={runDrawdownVsProfitScatter.PAD} y2={runDrawdownVsProfitScatter.H - runDrawdownVsProfitScatter.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.7"/>
				{#each runDrawdownVsProfitScatter.pts as p}
					{@const cx = runDrawdownVsProfitScatter.toX(p.dd)}
					{@const cy = runDrawdownVsProfitScatter.toY(p.profit)}
					{@const col = p.profit >= 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'}
					<circle {cx} {cy} r="1.8" fill={col}/>
				{/each}
				<text x={runDrawdownVsProfitScatter.PAD} y={runDrawdownVsProfitScatter.PAD + 6} font-size="6" fill="var(--ch-axis-muted)">+{runDrawdownVsProfitScatter.profMax}%</text>
				<text x={runDrawdownVsProfitScatter.W - runDrawdownVsProfitScatter.PAD} y={runDrawdownVsProfitScatter.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">dd {runDrawdownVsProfitScatter.ddMax}%</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Scatter of max drawdown % (X) vs total profit % (Y) per run · green=profitable · red=loss · ideal cluster is upper-left: high profit with low drawdown</p>
		</section>
	{/if}
	{#if runTradeCountVsProfitScatter}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Trade Count vs Total Profit Scatter</h3>
			<svg viewBox="0 0 {runTradeCountVsProfitScatter.W} {runTradeCountVsProfitScatter.H}" class="w-full" style="height:{runTradeCountVsProfitScatter.H}px">
				<line x1={runTradeCountVsProfitScatter.PAD} y1={runTradeCountVsProfitScatter.zeroY} x2={runTradeCountVsProfitScatter.W - runTradeCountVsProfitScatter.PAD} y2={runTradeCountVsProfitScatter.zeroY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each runTradeCountVsProfitScatter.pts as p}
					{@const cx = runTradeCountVsProfitScatter.toX(p.tc)}
					{@const cy = runTradeCountVsProfitScatter.toY(p.profit)}
					{@const col = p.profit >= 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'}
					<circle {cx} {cy} r="1.8" fill={col}/>
				{/each}
				<text x={runTradeCountVsProfitScatter.PAD} y={runTradeCountVsProfitScatter.PAD + 6} font-size="6" fill="var(--ch-axis-muted)">+{runTradeCountVsProfitScatter.profMax}%</text>
				<text x={runTradeCountVsProfitScatter.W - runTradeCountVsProfitScatter.PAD} y={runTradeCountVsProfitScatter.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{runTradeCountVsProfitScatter.tcMax} trades</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Scatter of total trade count (X) vs total profit % (Y) per run · green=profit · red=loss · reveals if higher trade frequency leads to better or worse outcomes</p>
		</section>
	{/if}
	{#if runAvgProfitByPairCount}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Profit% by Pair Count (buckets of 5)</h3>
			<svg viewBox="0 0 {runAvgProfitByPairCount.W} {runAvgProfitByPairCount.H}" class="w-full" style="height:{runAvgProfitByPairCount.H}px">
				<line x1={runAvgProfitByPairCount.PAD} y1={runAvgProfitByPairCount.midY} x2={runAvgProfitByPairCount.W - runAvgProfitByPairCount.PAD} y2={runAvgProfitByPairCount.midY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each runAvgProfitByPairCount.rows as row, i}
					{@const x = runAvgProfitByPairCount.PAD + i * runAvgProfitByPairCount.barW}
					{@const bh = Math.max(2, (Math.abs(row.avg) / runAvgProfitByPairCount.maxAbs) * (runAvgProfitByPairCount.midY - runAvgProfitByPairCount.PAD))}
					{@const y = row.avg >= 0 ? runAvgProfitByPairCount.midY - bh : runAvgProfitByPairCount.midY}
					{@const color = row.avg >= 0 ? 'var(--ch-violet)' : 'var(--ch-loss)'}
					<rect {x} {y} width={runAvgProfitByPairCount.barW - 1} height={bh} fill={color}/>
					<text x={x + runAvgProfitByPairCount.barW / 2} y={runAvgProfitByPairCount.H - 2} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{row.b}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg total profit% per backtest run grouped by pair count in buckets of 5 · reveals optimal portfolio breadth · indigo=positive · red=negative</p>
		</section>
	{/if}
	{#if runSortinoRanking}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Sortino Ratio by Strategy</h3>
			<svg viewBox="0 0 {runSortinoRanking.W} {runSortinoRanking.H}" class="w-full" style="height:{runSortinoRanking.H}px">
				<line x1={runSortinoRanking.zeroX} y1="0" x2={runSortinoRanking.zeroX} y2={runSortinoRanking.H} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each runSortinoRanking.rows as row, i}
					{@const y = runSortinoRanking.PAD + i * 16}
					{@const bw = Math.max(2, (Math.abs(row.avg) / runSortinoRanking.maxAbs) * (runSortinoRanking.barMaxW / 2))}
					{@const x = row.avg >= 0 ? runSortinoRanking.zeroX : runSortinoRanking.zeroX - bw}
					{@const color = row.avg >= 1 ? 'var(--ch-profit)' : row.avg >= 0 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
					<rect {x} {y} width={bw} height="12" rx="1" fill={color}/>
					<text x={runSortinoRanking.PAD} y={y + 10} font-size="6.5" fill="var(--ch-axis-strong)">{row.name}</text>
					<text x={row.avg >= 0 ? runSortinoRanking.zeroX + bw + 2 : runSortinoRanking.zeroX - bw - 2} y={y + 10} text-anchor={row.avg >= 0 ? 'start' : 'end'} font-size="6.5" fill={color}>{row.avg.toFixed(2)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg Sortino ratio per strategy · green≥1 · yellow≥0 · red&lt;0 · Sortino penalizes only downside volatility · diverging from zero center line</p>
		</section>
	{/if}
	{#if runProfitByMonth}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Total Profit% by Month</h3>
			<svg viewBox="0 0 {runProfitByMonth.W} {runProfitByMonth.H}" class="w-full" style="height:{runProfitByMonth.H}px">
				<line x1={runProfitByMonth.PAD} y1={runProfitByMonth.midY} x2={runProfitByMonth.W - runProfitByMonth.PAD} y2={runProfitByMonth.midY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each runProfitByMonth.pts as p, i}
					{@const x = runProfitByMonth.PAD + i * (runProfitByMonth.bw + 1)}
					{@const bh = Math.max(2, (Math.abs(p.avg) / runProfitByMonth.maxAbs) * (runProfitByMonth.midY - runProfitByMonth.PAD))}
					{@const y = p.avg >= 0 ? runProfitByMonth.midY - bh : runProfitByMonth.midY}
					{@const color = p.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect {x} {y} width={runProfitByMonth.bw} height={bh} fill={color}/>
					{#if i % 3 === 0}
						<text x={x + runProfitByMonth.bw / 2} y={runProfitByMonth.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{p.m}</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Monthly avg total profit% across all backtest runs · green=positive · red=negative · diverging from zero · reveals seasonal patterns and backtest quality trends over time</p>
		</section>
	{/if}
	{#if runSortinoByPairCount}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Sortino by Pair Count Bucket</h3>
			<svg viewBox="0 0 {runSortinoByPairCount.W} {runSortinoByPairCount.H}" class="w-full" style="height:{runSortinoByPairCount.H}px">
				<line x1={runSortinoByPairCount.zeroX} y1="0" x2={runSortinoByPairCount.zeroX} y2={runSortinoByPairCount.H} stroke="var(--ch-axis-faint)" stroke-width="1"/>
				{#each runSortinoByPairCount.rows as row, i}
					{@const y = runSortinoByPairCount.PAD + i * 20}
					{@const bw = Math.max(2, (Math.abs(row.avg) / runSortinoByPairCount.maxAbs) * (runSortinoByPairCount.barMaxW / 2))}
					{@const x = row.avg >= 0 ? runSortinoByPairCount.zeroX : runSortinoByPairCount.zeroX - bw}
					{@const color = row.avg >= 0 ? 'var(--ch-violet)' : 'var(--ch-loss)'}
					<rect {x} {y} width={bw} height="13" rx="2" fill={color}/>
					<text x={runSortinoByPairCount.PAD} y={y + 10} font-size="7" fill="var(--ch-axis-strong)">{row.bucket} pairs</text>
					<text x={row.avg >= 0 ? runSortinoByPairCount.zeroX + bw + 2 : runSortinoByPairCount.zeroX - bw - 2} y={y + 10} text-anchor={row.avg >= 0 ? 'start' : 'end'} font-size="6.5" fill={color}>{row.avg.toFixed(2)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg Sortino ratio by pair count bucket (grouped in 5s) · indigo/red diverging · identifies optimal portfolio size for risk-adjusted returns in backtests</p>
		</section>
	{/if}
	{#if runProfitByDow}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Profit% by Day of Week (Runs Created)</h3>
			<svg viewBox="0 0 {runProfitByDow.W} {runProfitByDow.H}" class="w-full" style="height:{runProfitByDow.H}px">
				<line x1={runProfitByDow.PAD} y1={runProfitByDow.midY} x2={runProfitByDow.W - runProfitByDow.PAD} y2={runProfitByDow.midY} stroke="var(--ch-axis-faint)" stroke-width="1"/>
				{#each runProfitByDow.pts as p, i}
					{@const x = runProfitByDow.PAD + i * (runProfitByDow.bw + 2)}
					{@const bh = Math.max(1, (Math.abs(p.avg) / runProfitByDow.maxAbs) * (runProfitByDow.H / 2 - runProfitByDow.PAD))}
					{@const y = p.avg >= 0 ? runProfitByDow.midY - bh : runProfitByDow.midY}
					{@const color = p.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect {x} {y} width={runProfitByDow.bw} height={bh} rx="1" fill={color}/>
					<text x={x + runProfitByDow.bw / 2} y={runProfitByDow.H - 1} text-anchor="middle" font-size="6" fill="var(--ch-axis)">{p.d}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg total profit% by day of week backtest runs were created · reveals whether certain creation days correlate with better-performing backtest configurations</p>
		</section>
	{/if}
	{#if runCalmarByStrategy}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Calmar by Strategy</h3>
			<svg viewBox="0 0 {runCalmarByStrategy.W} {runCalmarByStrategy.H}" class="w-full" style="height:{runCalmarByStrategy.H}px">
				<line x1={runCalmarByStrategy.zeroX} y1="0" x2={runCalmarByStrategy.zeroX} y2={runCalmarByStrategy.H} stroke="var(--ch-axis-faint)" stroke-width="1"/>
				{#each runCalmarByStrategy.rows as row, i}
					{@const y = runCalmarByStrategy.PAD + i * 18}
					{@const bw = Math.max(2, (Math.abs(row.avg) / runCalmarByStrategy.maxAbs) * (runCalmarByStrategy.barMaxW / 2))}
					{@const x = row.avg >= 0 ? runCalmarByStrategy.zeroX : runCalmarByStrategy.zeroX - bw}
					{@const color = row.avg >= 0 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					<rect {x} {y} width={bw} height="12" rx="2" fill={color}/>
					<text x={runCalmarByStrategy.PAD} y={y + 10} font-size="6.5" fill="var(--ch-axis-strong)">{row.name}</text>
					<text x={row.avg >= 0 ? runCalmarByStrategy.zeroX + bw + 2 : runCalmarByStrategy.zeroX - bw - 2} y={y + 10} text-anchor={row.avg >= 0 ? 'start' : 'end'} font-size="6" fill={color}>{row.avg.toFixed(2)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg Calmar ratio per strategy across all backtest runs · teal=positive · red=negative · ranks strategies by risk-adjusted return relative to max drawdown</p>
		</section>
	{/if}
	{#if runProfitByTFMonth}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Profit% Heatmap (Timeframe × Month)</h3>
			<svg viewBox="0 0 {runProfitByTFMonth.W} {runProfitByTFMonth.H}" class="w-full" style="height:{runProfitByTFMonth.H}px">
				{#each runProfitByTFMonth.tfs as tf, ti}
					<text x={runProfitByTFMonth.PAD} y={runProfitByTFMonth.PAD + (ti + 1) * runProfitByTFMonth.cellH + 12} font-size="6.5" fill="var(--ch-axis)">{tf}</text>
				{/each}
				{#each runProfitByTFMonth.months as mo, mi}
					<text x={runProfitByTFMonth.PAD + (mi + 1) * runProfitByTFMonth.cellW + runProfitByTFMonth.cellW / 2} y={runProfitByTFMonth.PAD + 8} text-anchor="middle" font-size="5.5" fill="var(--ch-axis)">{mo.slice(5)}</text>
				{/each}
				{#each runProfitByTFMonth.cells as cell}
					{@const intensity = Math.min(1, Math.abs(cell.avg) / runProfitByTFMonth.maxAbs)}
					{@const alpha = (intensity * 0.55 + 0.1).toFixed(2)}
					{@const fill = cell.avg >= 0 ? `rgba(34,197,94,${alpha})` : `rgba(239,68,68,${alpha})`}
					<rect x={cell.x} y={cell.y} width={runProfitByTFMonth.cellW - 2} height={runProfitByTFMonth.cellH - 2} rx="2" fill={fill}/>
					<text x={cell.x + runProfitByTFMonth.cellW / 2 - 1} y={cell.y + 11} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-strong)">{cell.label}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Heatmap of avg total profit% by timeframe (rows) and month (cols, last 6) · green=positive · red=negative · intensity=magnitude · shows seasonal/TF interaction patterns</p>
		</section>
	{/if}
	{#if runSharpeVsDrawdownRatio}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Sharpe vs Sharpe/Drawdown Ratio (Scatter)</h3>
			<svg viewBox="0 0 {runSharpeVsDrawdownRatio.W} {runSharpeVsDrawdownRatio.H}" class="w-full" style="height:{runSharpeVsDrawdownRatio.H}px">
				<line x1={runSharpeVsDrawdownRatio.zeroX} y1={runSharpeVsDrawdownRatio.PAD} x2={runSharpeVsDrawdownRatio.zeroX} y2={runSharpeVsDrawdownRatio.H - runSharpeVsDrawdownRatio.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each runSharpeVsDrawdownRatio.pts as p}
					{@const cx = runSharpeVsDrawdownRatio.toX(p.x)}
					{@const cy = runSharpeVsDrawdownRatio.toY(p.y)}
					{@const color = p.profit > 0 && p.x > 0 ? 'var(--ch-profit)' : p.x > 0 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)'}
					<circle {cx} {cy} r="2.5" fill={color}/>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Scatter of Sharpe ratio (X) vs Sharpe/Drawdown ratio (Y) · green=profitable+positive Sharpe · top-right = best risk efficiency · reveals which runs have strong Sharpe relative to their drawdown</p>
		</section>
	{/if}
	{#if runTopPairsByWinRate}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Top Strategies by Avg Win Rate</h3>
			<svg viewBox="0 0 {runTopPairsByWinRate.W} {runTopPairsByWinRate.H}" class="w-full" style="height:{runTopPairsByWinRate.H}px">
				{#each runTopPairsByWinRate.rows as row, i}
					{@const y = runTopPairsByWinRate.PAD + i * 18}
					{@const bw = Math.max(2, (row.avg / runTopPairsByWinRate.maxWR) * runTopPairsByWinRate.barMaxW)}
					{@const color = row.avg >= 60 ? 'var(--ch-profit)' : row.avg >= 50 ? 'var(--ch-violet)' : 'var(--ch-warn)'}
					<text x={runTopPairsByWinRate.PAD} y={y + 12} font-size="6.5" fill="var(--ch-axis-strong)">{row.name}</text>
					<rect x={runTopPairsByWinRate.PAD + 108} {y} width={bw} height="13" rx="2" fill={color}/>
					<text x={runTopPairsByWinRate.PAD + 108 + bw + 3} y={y + 12} font-size="6.5" fill={color}>{row.avg.toFixed(1)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Top 8 strategies by avg win rate across all backtest runs · green≥60% · indigo≥50% · yellow&lt;50% · high win rate strategies tend to have better expectancy per trade</p>
		</section>
	{/if}
	{#if runProfitVsTradeCountScatter}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Profit% vs Trade Count (Scatter)</h3>
			<svg viewBox="0 0 {runProfitVsTradeCountScatter.W} {runProfitVsTradeCountScatter.H}" class="w-full" style="height:{runProfitVsTradeCountScatter.H}px">
				<line x1={runProfitVsTradeCountScatter.zeroX} y1={runProfitVsTradeCountScatter.PAD} x2={runProfitVsTradeCountScatter.zeroX} y2={runProfitVsTradeCountScatter.H - runProfitVsTradeCountScatter.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each runProfitVsTradeCountScatter.pts as p}
					{@const cx = runProfitVsTradeCountScatter.toX(p.p)}
					{@const cy = runProfitVsTradeCountScatter.toY(p.tc)}
					{@const color = p.p > 0 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					<circle {cx} {cy} r="2.5" fill={color}/>
				{/each}
				<text x={runProfitVsTradeCountScatter.PAD} y={runProfitVsTradeCountScatter.H - 2} font-size="6" fill="var(--ch-axis-muted)">{runProfitVsTradeCountScatter.minP}%</text>
				<text x={runProfitVsTradeCountScatter.W - runProfitVsTradeCountScatter.PAD} y={runProfitVsTradeCountScatter.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{runProfitVsTradeCountScatter.maxP}%</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Scatter of profit% (X) vs trade count (Y) · teal=profitable · red=losing · high trade count with high profit = highly active and effective strategy</p>
		</section>
	{/if}
	{#if runSortinoCDF}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Sortino Ratio CDF (All Backtest Runs)</h3>
			<svg viewBox="0 0 {runSortinoCDF.W} {runSortinoCDF.H}" class="w-full" style="height:{runSortinoCDF.H}px">
				<line x1={runSortinoCDF.zeroX} y1={runSortinoCDF.PAD} x2={runSortinoCDF.zeroX} y2={runSortinoCDF.H - runSortinoCDF.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				<polyline points={runSortinoCDF.pts} fill="none" stroke="var(--ch-teal-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={runSortinoCDF.PAD} y={runSortinoCDF.H - 2} font-size="6" fill="var(--ch-axis-muted)">{runSortinoCDF.minV}</text>
				<text x={runSortinoCDF.W - runSortinoCDF.PAD} y={runSortinoCDF.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{runSortinoCDF.maxV}</text>
				<text x={runSortinoCDF.W / 2} y={runSortinoCDF.PAD + 8} text-anchor="middle" font-size="7" fill="var(--ch-teal-strong)">median {runSortinoCDF.median}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">CDF of Sortino ratios across all backtest signal runs · teal S-curve · dashed zero line · right-skewed = majority of runs have positive downside-adjusted returns</p>
		</section>
	{/if}
	{#if runMonthlyAvgProfitBars}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Monthly Avg Profit% (Signal Runs)</h3>
			<svg viewBox="0 0 {runMonthlyAvgProfitBars.W} {runMonthlyAvgProfitBars.H}" class="w-full" style="height:{runMonthlyAvgProfitBars.H}px">
				<line x1={runMonthlyAvgProfitBars.PAD} y1={runMonthlyAvgProfitBars.midY} x2={runMonthlyAvgProfitBars.W - runMonthlyAvgProfitBars.PAD} y2={runMonthlyAvgProfitBars.midY} stroke="var(--ch-axis-faint)" stroke-width="1"/>
				{#each runMonthlyAvgProfitBars.avgs as avg, i}
					{@const x = runMonthlyAvgProfitBars.PAD + i * (runMonthlyAvgProfitBars.bw + 1)}
					{@const bh = Math.max(1, (Math.abs(avg) / runMonthlyAvgProfitBars.maxAbs) * (runMonthlyAvgProfitBars.H / 2 - runMonthlyAvgProfitBars.PAD))}
					{@const y = avg >= 0 ? runMonthlyAvgProfitBars.midY - bh : runMonthlyAvgProfitBars.midY}
					{@const color = avg >= 0 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					<rect {x} {y} width={runMonthlyAvgProfitBars.bw} height={bh} rx="1" fill={color}/>
					{#if i % 2 === 0}
						<text x={x + runMonthlyAvgProfitBars.bw / 2} y={runMonthlyAvgProfitBars.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{runMonthlyAvgProfitBars.months[i].slice(5)}</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Monthly avg total profit% of backtest signal runs · teal=positive · red=negative · diverging bars from center · reveals which months had best signal quality</p>
		</section>
	{/if}
	{#if runCalmarVsWinRateScatter}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Calmar vs Win Rate Scatter</h3>
			<svg viewBox="0 0 {runCalmarVsWinRateScatter.W} {runCalmarVsWinRateScatter.H}" class="w-full" style="height:{runCalmarVsWinRateScatter.H}px">
				<line x1={runCalmarVsWinRateScatter.zeroX} y1={runCalmarVsWinRateScatter.PAD} x2={runCalmarVsWinRateScatter.zeroX} y2={runCalmarVsWinRateScatter.H - runCalmarVsWinRateScatter.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each runCalmarVsWinRateScatter.pts as p}
					{@const cx = runCalmarVsWinRateScatter.toX(p.calmar)}
					{@const cy = runCalmarVsWinRateScatter.toY(p.wr)}
					{@const color = p.calmar > 0 && p.wr >= 50 ? 'var(--ch-profit)' : p.calmar > 0 ? 'var(--ch-teal)' : 'var(--ch-loss-light)'}
					<circle {cx} {cy} r="2.5" fill={color}/>
				{/each}
				<text x={runCalmarVsWinRateScatter.PAD} y={runCalmarVsWinRateScatter.H - 2} font-size="6" fill="var(--ch-axis-muted)">{runCalmarVsWinRateScatter.minC}</text>
				<text x={runCalmarVsWinRateScatter.W - runCalmarVsWinRateScatter.PAD} y={runCalmarVsWinRateScatter.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{runCalmarVsWinRateScatter.maxC}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Scatter of Calmar (X) vs win rate% (Y) · green=positive Calmar+≥50% WR · teal=positive Calmar only · red=negative Calmar · top-right = ideal risk-adjusted winners</p>
		</section>
	{/if}
	{#if runProfitBySortinoBucket}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Profit% by Sortino Bucket</h3>
			<svg viewBox="0 0 {runProfitBySortinoBucket.W} {runProfitBySortinoBucket.H}" class="w-full" style="height:{runProfitBySortinoBucket.H}px">
				<line x1={runProfitBySortinoBucket.zeroX} y1="0" x2={runProfitBySortinoBucket.zeroX} y2={runProfitBySortinoBucket.H} stroke="var(--ch-axis-faint)" stroke-width="0.8"/>
				{#each runProfitBySortinoBucket.rows as row, i}
					{@const y = runProfitBySortinoBucket.PAD + i * 22}
					{@const bw = Math.max(2, (Math.abs(row.avg) / runProfitBySortinoBucket.maxAbs) * (runProfitBySortinoBucket.barMaxW / 2))}
					{@const x = row.avg >= 0 ? runProfitBySortinoBucket.zeroX : runProfitBySortinoBucket.zeroX - bw}
					{@const color = row.avg >= 0 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					<text x={runProfitBySortinoBucket.PAD} y={y + 14} font-size="8" fill="var(--ch-axis-strong)">{row.k}</text>
					<rect {x} {y} width={bw} height="15" rx="2" fill={color}/>
					<text x={row.avg >= 0 ? runProfitBySortinoBucket.zeroX + bw + 2 : runProfitBySortinoBucket.zeroX - bw - 2} y={y + 12} text-anchor={row.avg >= 0 ? 'start' : 'end'} font-size="6.5" fill={color}>{row.avg.toFixed(1)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg total profit% grouped by Sortino ratio bucket · teal=positive · red=negative · higher Sortino buckets should show higher profits — validates that Sortino predicts real-world returns</p>
		</section>
	{/if}
	{#if runStrategyWinRateRanking}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Strategy Win Rate% Ranking (Signals)</h3>
			<svg viewBox="0 0 {runStrategyWinRateRanking.W} {runStrategyWinRateRanking.H}" class="w-full" style="height:{runStrategyWinRateRanking.H}px">
				{#each runStrategyWinRateRanking.rows as row, i}
					{@const y = runStrategyWinRateRanking.PAD + i * 18}
					{@const bw = Math.max(2, (row.rate / 100) * runStrategyWinRateRanking.barMaxW)}
					{@const color = row.rate >= 60 ? 'var(--ch-profit)' : row.rate >= 50 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					<text x={runStrategyWinRateRanking.PAD} y={y + 12} font-size="7" fill="var(--ch-axis-strong)">{row.name}</text>
					<rect x={runStrategyWinRateRanking.PAD + 80} {y} width={bw} height="13" rx="2" fill={color}/>
					<text x={runStrategyWinRateRanking.PAD + 80 + bw + 3} y={y + 12} font-size="6.5" fill={color}>{row.rate.toFixed(1)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">% of signal runs where win rate &gt;50% per strategy (≥2 runs) · green≥60% · teal≥50% · red&lt;50% · consistently above 50% = strategy has reliable edge in signal period</p>
		</section>
	{/if}
	{#if runSharpeVsWinRateScatter}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Sharpe vs Win Rate Scatter</h3>
			<svg viewBox="0 0 {runSharpeVsWinRateScatter.W} {runSharpeVsWinRateScatter.H}" class="w-full" style="height:{runSharpeVsWinRateScatter.H}px">
				<line x1={runSharpeVsWinRateScatter.zeroX} y1={runSharpeVsWinRateScatter.PAD} x2={runSharpeVsWinRateScatter.zeroX} y2={runSharpeVsWinRateScatter.H - runSharpeVsWinRateScatter.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				<line x1={runSharpeVsWinRateScatter.PAD} y1={runSharpeVsWinRateScatter.zeroY} x2={runSharpeVsWinRateScatter.W - runSharpeVsWinRateScatter.PAD} y2={runSharpeVsWinRateScatter.zeroY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each runSharpeVsWinRateScatter.pts as p}
					{@const cx = runSharpeVsWinRateScatter.toX(p.sharpe)}
					{@const cy = runSharpeVsWinRateScatter.toY(p.wr)}
					{@const color = p.sharpe > 0 && p.wr >= 50 ? 'var(--ch-profit)' : p.sharpe > 0 ? 'var(--ch-teal)' : 'var(--ch-loss-light)'}
					<circle {cx} {cy} r="2.5" fill={color}/>
				{/each}
				<text x={runSharpeVsWinRateScatter.PAD} y={runSharpeVsWinRateScatter.H - 2} font-size="6" fill="var(--ch-axis-muted)">{runSharpeVsWinRateScatter.minS}</text>
				<text x={runSharpeVsWinRateScatter.W - runSharpeVsWinRateScatter.PAD} y={runSharpeVsWinRateScatter.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{runSharpeVsWinRateScatter.maxS}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Scatter of Sharpe ratio (X) vs win rate% (Y) · green=positive Sharpe+≥50%WR · teal=positive Sharpe only · red=negative Sharpe · top-right = ideal signal quality</p>
		</section>
	{/if}
	{#if runProfitByTFBars}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Profit% by Timeframe (Signals)</h3>
			<svg viewBox="0 0 {runProfitByTFBars.W} {runProfitByTFBars.H}" class="w-full" style="height:{runProfitByTFBars.H}px">
				<line x1={runProfitByTFBars.zeroX} y1="0" x2={runProfitByTFBars.zeroX} y2={runProfitByTFBars.H} stroke="var(--ch-axis-faint)" stroke-width="0.8"/>
				{#each runProfitByTFBars.rows as row, i}
					{@const y = runProfitByTFBars.PAD + i * 20}
					{@const bw = Math.max(2, (Math.abs(row.avg) / runProfitByTFBars.maxAbs) * (runProfitByTFBars.barMaxW / 2))}
					{@const x = row.avg >= 0 ? runProfitByTFBars.zeroX : runProfitByTFBars.zeroX - bw}
					{@const color = row.avg >= 0 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					<text x={runProfitByTFBars.PAD} y={y + 13} font-size="8" fill="var(--ch-axis-strong)">{row.tf}</text>
					<rect {x} {y} width={bw} height="14" rx="2" fill={color}/>
					<text x={row.avg >= 0 ? runProfitByTFBars.zeroX + bw + 2 : runProfitByTFBars.zeroX - bw - 2} y={y + 11} text-anchor={row.avg >= 0 ? 'start' : 'end'} font-size="6.5" fill={color}>{row.avg.toFixed(1)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg total profit% by timeframe across signal runs · teal=positive · red=negative · reveals which timeframes produce the most profitable signal-period backtests</p>
		</section>
	{/if}
	{#if runCalmarCDF}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Signal Run Calmar CDF</h3>
			<svg viewBox="0 0 {runCalmarCDF.W} {runCalmarCDF.H}" class="w-full" style="height:{runCalmarCDF.H}px">
				<polyline points={runCalmarCDF.polyline} fill="none" stroke="var(--ch-teal-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={runCalmarCDF.PAD} y={runCalmarCDF.H - 2} font-size="6" fill="var(--ch-axis-muted)">{runCalmarCDF.minV}</text>
				<text x={runCalmarCDF.W - runCalmarCDF.PAD} y={runCalmarCDF.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{runCalmarCDF.maxV}</text>
				<text x={runCalmarCDF.W / 2} y={runCalmarCDF.PAD + 8} text-anchor="middle" font-size="7" fill="var(--ch-teal-strong)">median {runCalmarCDF.median}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">CDF of Calmar ratio across signal window runs · teal S-curve · median above 1 = more than half of signal runs have good return-per-drawdown · left tail = worst-case periods</p>
		</section>
	{/if}
	{#if runWinRateByTF}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Win Rate% by Timeframe</h3>
			<svg viewBox="0 0 {runWinRateByTF.W} {runWinRateByTF.H}" class="w-full" style="height:{runWinRateByTF.H}px">
				{#each runWinRateByTF.rows as row, i}
					{@const y = runWinRateByTF.PAD + i * 20}
					{@const bw = Math.max(2, (row.avg / runWinRateByTF.maxV) * runWinRateByTF.barMaxW)}
					{@const color = row.avg >= 55 ? 'var(--ch-profit)' : row.avg >= 45 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					<text x={runWinRateByTF.PAD} y={y + 13} font-size="8" fill="var(--ch-axis-strong)">{row.tf}</text>
					<rect x={runWinRateByTF.PAD + 40} {y} width={bw} height="14" rx="2" fill={color}/>
					<text x={runWinRateByTF.PAD + 40 + bw + 3} y={y + 12} font-size="6.5" fill={color}>{row.avg.toFixed(1)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg win rate% by timeframe · green≥55% · teal≥45% · red&lt;45% · identifies which signal timeframes generate above-50% accuracy entries</p>
		</section>
	{/if}
	{#if runAvgDrawdownByStrategy}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Drawdown% by Strategy</h3>
			<svg viewBox="0 0 {runAvgDrawdownByStrategy.W} {runAvgDrawdownByStrategy.H}" class="w-full" style="height:{runAvgDrawdownByStrategy.H}px">
				{#each runAvgDrawdownByStrategy.rows as row, i}
					{@const y = runAvgDrawdownByStrategy.PAD + i * 20}
					{@const bw = Math.max(2, (row.avg / runAvgDrawdownByStrategy.maxAvg) * runAvgDrawdownByStrategy.barMaxW)}
					{@const color = row.avg <= 8 ? 'var(--ch-profit)' : row.avg <= 20 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
					<text x={runAvgDrawdownByStrategy.PAD} y={y + 13} font-size="7" fill="var(--ch-axis-strong)">{row.name}</text>
					<rect x={runAvgDrawdownByStrategy.PAD + 90} {y} width={bw} height="14" rx="2" fill={color}/>
					<text x={runAvgDrawdownByStrategy.PAD + 90 + bw + 3} y={y + 12} font-size="6.5" fill={color}>{row.avg.toFixed(1)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg max drawdown% per strategy across signal runs · green≤8% · yellow≤20% · red&gt;20% · sorted ascending — strategies at top have most stable signal windows</p>
		</section>
	{/if}
	{#if runWinRateSortinoCDF}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Signal Run Sortino CDF</h3>
			<svg viewBox="0 0 {runWinRateSortinoCDF.W} {runWinRateSortinoCDF.H}" class="w-full" style="height:{runWinRateSortinoCDF.H}px">
				<polyline points={runWinRateSortinoCDF.polyline} fill="none" stroke="var(--ch-teal-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={runWinRateSortinoCDF.PAD} y={runWinRateSortinoCDF.H - 2} font-size="6" fill="var(--ch-axis-muted)">{runWinRateSortinoCDF.minV}</text>
				<text x={runWinRateSortinoCDF.W - runWinRateSortinoCDF.PAD} y={runWinRateSortinoCDF.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{runWinRateSortinoCDF.maxV}</text>
				<text x={runWinRateSortinoCDF.W / 2} y={runWinRateSortinoCDF.PAD + 8} text-anchor="middle" font-size="7" fill="var(--ch-teal-strong)">median {runWinRateSortinoCDF.median}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">CDF of Sortino ratio across signal runs · teal S-curve · Sortino above 1 for majority = consistent downside-adjusted outperformance across signal windows</p>
		</section>
	{/if}
	{#if runProfitByPairGroup}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Profit% by Base Asset</h3>
			<svg viewBox="0 0 {runProfitByPairGroup.W} {runProfitByPairGroup.H}" class="w-full" style="height:{runProfitByPairGroup.H}px">
				<line x1={runProfitByPairGroup.PAD} y1={runProfitByPairGroup.midY} x2={runProfitByPairGroup.W - runProfitByPairGroup.PAD} y2={runProfitByPairGroup.midY} stroke="var(--ch-axis-faint)" stroke-width="0.5" stroke-dasharray="2,2"/>
				{#each runProfitByPairGroup.bars as b, i}
					{@const bh = (Math.abs(b.avg) / runProfitByPairGroup.maxAbs) * (runProfitByPairGroup.midY - runProfitByPairGroup.PAD)}
					{@const x = runProfitByPairGroup.PAD + i * (runProfitByPairGroup.bw + 2)}
					{@const y = b.avg >= 0 ? runProfitByPairGroup.midY - bh : runProfitByPairGroup.midY}
					{@const color = b.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect {x} {y} width={runProfitByPairGroup.bw} height={bh} fill={color} rx="1"/>
					<text x={x + runProfitByPairGroup.bw / 2} y={runProfitByPairGroup.H} text-anchor="middle" font-size="5.5" fill="var(--ch-axis)">{b.base}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg profit% per base asset across signal runs · green=profitable · red=losing · top assets reveal which signals have strongest alpha by coin</p>
		</section>
	{/if}
	{#if runHoldTimeHistogram}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Hold Time Distribution</h3>
			<svg viewBox="0 0 {runHoldTimeHistogram.W} {runHoldTimeHistogram.H}" class="w-full" style="height:{runHoldTimeHistogram.H}px">
				{#each runHoldTimeHistogram.counts as cnt, i}
					{@const bh = Math.max(1, (cnt / runHoldTimeHistogram.maxCnt) * (runHoldTimeHistogram.H - runHoldTimeHistogram.PAD * 2))}
					{@const x = runHoldTimeHistogram.PAD + i * (runHoldTimeHistogram.bw + 1)}
					{@const y = runHoldTimeHistogram.H - runHoldTimeHistogram.PAD - bh}
					{@const label = (i * runHoldTimeHistogram.binW).toFixed(0)}
					<rect {x} {y} width={runHoldTimeHistogram.bw} height={bh} fill="var(--ch-teal)" rx="1"/>
					{#if i % 2 === 0}
						<text x={x + runHoldTimeHistogram.bw / 2} y={runHoldTimeHistogram.H} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{label}h</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Histogram of avg hold time in hours across signal runs · teal bars · left-skewed = mostly short holds (momentum) · right tail = trend-following runs</p>
		</section>
	{/if}
	{#if runAvgCalmarByStrategy}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Calmar by Strategy</h3>
			<svg viewBox="0 0 {runAvgCalmarByStrategy.W} {runAvgCalmarByStrategy.H}" class="w-full" style="height:{runAvgCalmarByStrategy.H}px">
				<line x1={runAvgCalmarByStrategy.midX} y1={runAvgCalmarByStrategy.PAD} x2={runAvgCalmarByStrategy.midX} y2={runAvgCalmarByStrategy.H - runAvgCalmarByStrategy.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.5"/>
				{#each runAvgCalmarByStrategy.bars as b, i}
					{@const bw = (Math.abs(b.avg) / runAvgCalmarByStrategy.maxAbs) * (runAvgCalmarByStrategy.midX - runAvgCalmarByStrategy.PAD)}
					{@const y = runAvgCalmarByStrategy.PAD + i * (runAvgCalmarByStrategy.bh + 6)}
					{@const color = b.avg >= 1 ? 'var(--ch-profit)' : b.avg >= 0 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					{@const x = b.avg >= 0 ? runAvgCalmarByStrategy.midX : runAvgCalmarByStrategy.midX - bw}
					<rect {x} {y} width={bw} height={runAvgCalmarByStrategy.bh} fill={color} rx="1"/>
					<text x={runAvgCalmarByStrategy.midX - 3} y={y + runAvgCalmarByStrategy.bh / 2 + 2.5} text-anchor="end" font-size="6" fill="var(--ch-axis-strong)">{b.s}</text>
					<text x={b.avg >= 0 ? runAvgCalmarByStrategy.midX + bw + 2 : runAvgCalmarByStrategy.midX - bw - 2} y={y + runAvgCalmarByStrategy.bh / 2 + 2.5} text-anchor={b.avg >= 0 ? 'start' : 'end'} font-size="5.5" fill={color}>{b.avg.toFixed(2)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg Calmar ratio per strategy across signal runs · green≥1 · teal≥0 · red&lt;0 · Calmar = return/max-DD — strategies with consistently high Calmar are most risk-efficient</p>
		</section>
	{/if}
	{#if runSharpeWinRateScatter2}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Sharpe vs Win Rate Scatter</h3>
			<svg viewBox="0 0 {runSharpeWinRateScatter2.W} {runSharpeWinRateScatter2.H}" class="w-full" style="height:{runSharpeWinRateScatter2.H}px">
				<line x1={runSharpeWinRateScatter2.PAD} y1={runSharpeWinRateScatter2.midY} x2={runSharpeWinRateScatter2.W - runSharpeWinRateScatter2.PAD} y2={runSharpeWinRateScatter2.midY} stroke="var(--ch-axis-faint)" stroke-width="0.5" stroke-dasharray="2,2"/>
				{#each runSharpeWinRateScatter2.pts as p}
					{@const cx = runSharpeWinRateScatter2.PAD + (p.x / 100) * (runSharpeWinRateScatter2.W - runSharpeWinRateScatter2.PAD * 2)}
					{@const cy = runSharpeWinRateScatter2.midY - (p.y / runSharpeWinRateScatter2.maxY) * (runSharpeWinRateScatter2.H / 2 - runSharpeWinRateScatter2.PAD)}
					{@const color = p.pf >= 1.5 ? 'var(--ch-profit-light)' : p.pf >= 1 ? 'var(--ch-teal-light)' : 'var(--ch-loss-light)'}
					<circle {cx} {cy} r="2" fill={color}/>
				{/each}
				<text x={runSharpeWinRateScatter2.W - runSharpeWinRateScatter2.PAD} y={runSharpeWinRateScatter2.midY - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">WR%→</text>
				<text x={runSharpeWinRateScatter2.PAD + 2} y={runSharpeWinRateScatter2.PAD + 7} font-size="6" fill="var(--ch-axis-muted)">Sharpe↑</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Scatter: Win rate% (X) vs Sharpe (Y) · green=PF≥1.5 · teal=PF≥1 · red&lt;1 · top-right = best signals with high WR and high Sharpe ratio</p>
		</section>
	{/if}
	{#if runTopDrawdownByStrategy}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Drawdown% by Strategy (Best→Worst)</h3>
			<svg viewBox="0 0 {runTopDrawdownByStrategy.W} {runTopDrawdownByStrategy.H}" class="w-full" style="height:{runTopDrawdownByStrategy.H}px">
				{#each runTopDrawdownByStrategy.bars as b, i}
					{@const bw = Math.max(2, (b.avg / runTopDrawdownByStrategy.maxAvg) * runTopDrawdownByStrategy.barMaxW)}
					{@const y = runTopDrawdownByStrategy.PAD + i * 18}
					{@const color = b.avg <= 10 ? 'var(--ch-profit)' : b.avg <= 25 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
					<text x={runTopDrawdownByStrategy.PAD} y={y + 12} font-size="6.5" fill="var(--ch-axis-strong)">{b.s}</text>
					<rect x={runTopDrawdownByStrategy.PAD + 72} {y} width={bw} height="13" fill={color} rx="1"/>
					<text x={runTopDrawdownByStrategy.PAD + 72 + bw + 3} y={y + 10} font-size="6" fill={color}>{b.avg.toFixed(1)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg max drawdown% per strategy · green≤10% · yellow≤25% · red&gt;25% · sorted lowest DD first — strategies with low DD are most capital-efficient signal generators</p>
		</section>
	{/if}
	{#if runProfitFactorByDow}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Profit Factor by Start Day</h3>
			<svg viewBox="0 0 {runProfitFactorByDow.W} {runProfitFactorByDow.H}" class="w-full" style="height:{runProfitFactorByDow.H}px">
				<line x1={runProfitFactorByDow.PAD} y1={runProfitFactorByDow.midY} x2={runProfitFactorByDow.W - runProfitFactorByDow.PAD} y2={runProfitFactorByDow.midY} stroke="var(--ch-axis-faint)" stroke-width="0.5" stroke-dasharray="2,2"/>
				{#each runProfitFactorByDow.bars as b, i}
					{@const dev = b.avg - 1}
					{@const bh = (Math.abs(dev) / runProfitFactorByDow.maxAbs) * (runProfitFactorByDow.midY - runProfitFactorByDow.PAD)}
					{@const x = runProfitFactorByDow.PAD + i * (runProfitFactorByDow.bw + 2)}
					{@const y = dev >= 0 ? runProfitFactorByDow.midY - bh : runProfitFactorByDow.midY}
					{@const color = b.avg >= 1.2 ? 'var(--ch-profit)' : b.avg >= 1 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					<rect {x} {y} width={runProfitFactorByDow.bw} height={bh} fill={color} rx="1"/>
					<text x={x + runProfitFactorByDow.bw / 2} y={runProfitFactorByDow.H} text-anchor="middle" font-size="6" fill="var(--ch-axis)">{b.label}</text>
					<text x={x + runProfitFactorByDow.bw / 2} y={dev >= 0 ? y - 2 : y + bh + 7} text-anchor="middle" font-size="5.5" fill={color}>{b.avg.toFixed(2)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg profit factor by run start day of week · green≥1.2 · teal≥1 · red&lt;1 · diverging from PF=1 baseline · reveals if day-of-week affects signal window quality</p>
		</section>
	{/if}
</main>
