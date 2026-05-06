<script lang="ts">
	import type { PageData } from './$types';
	import Kpi from '$lib/components/kpi.svelte';
	import PersonalPlan from '$lib/components/personal-plan.svelte';
	import BinanceConnect from '$lib/components/binance-connect.svelte';
	import { fmtTime, fmtUSD } from '$lib/utils';
	import { t, type Lang } from '$lib/i18n';
	import { onMount } from 'svelte';
	import ChartInfo from '$lib/components/chart-info.svelte';

	let { data }: { data: PageData } = $props();
	const lang = $derived<Lang>(data.lang ?? 'zh');
	const triggers = $derived(data.triggers);
	const dcaEvents = $derived(data.triggers);
	const orders = $derived(data.log);

	let kindFilter = $state<string | null>(null);
	const filteredTriggers = $derived.by(() => {
		if (!kindFilter) return data.triggers;
		return data.triggers.filter((t) => t.kind === kindFilter);
	});

	const cumMax = $derived(Math.max(1, ...data.cumulative.map((c) => c.cum)));

	const kindColor: Record<string, string> = {
		FLASH: 'bg-red-950 text-red-300 border-red-800',
		FAST: 'bg-orange-950 text-orange-300 border-orange-800',
		SUSTAIN: 'bg-yellow-950 text-yellow-300 border-yellow-800',
		CAPITUL: 'bg-purple-950 text-purple-300 border-purple-800'
	};

	const REPORT_CARDS = $derived([
		{
			title: t(lang, 'dca.report.weekly.title'),
			desc: t(lang, 'dca.report.weekly.desc'),
			href: '/reports/dca_backtest/index.html'
		},
		{
			title: t(lang, 'dca.report.dist.title'),
			desc: t(lang, 'dca.report.dist.desc'),
			href: '/reports/dca_backtest/multiplier_distribution.html'
		},
		{
			title: t(lang, 'dca.report.comparison.title'),
			desc: t(lang, 'dca.report.comparison.desc'),
			href: '/reports/dca_backtest/dca_comparison.html'
		},
		{
			title: t(lang, 'dca.report.event.title'),
			desc: t(lang, 'dca.report.event.desc'),
			href: '/reports/event_dca/index.html'
		}
	]);

	// Cumulative DCA SVG area chart
	const cumChart = $derived.by(() => {
		const pts = data.cumulative;
		if (pts.length < 2) return null;
		const W = 560, H = 100, PAD = 4;
		const maxVal = Math.max(1, ...pts.map(p => p.cum));
		const toX = (i: number) => PAD + (i / (pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v / maxVal) * (H - PAD * 2));
		const linePts = pts.map((p, i) => `${toX(i).toFixed(1)},${toY(p.cum).toFixed(1)}`).join(' ');
		const areaPts = `${PAD},${H - PAD} ` + linePts + ` ${W - PAD},${H - PAD}`;
		const last = pts[pts.length - 1];
		return { linePts, areaPts, W, H, PAD, last, maxVal };
	});

	// DCA projection chart
	let projMonthly = $state(500);
	let projBtcPrice = $state<number | null>(null);
	const SCENARIOS = [
		{ label: lang === 'en' ? 'Bear (0% CAGR)' : '熊市 (0%)', cagr: 0,   color: 'var(--ch-loss-strong)' },
		{ label: lang === 'en' ? 'Base (40% CAGR)' : '基础 (40%)', cagr: 0.4, color: 'var(--ch-warn)' },
		{ label: lang === 'en' ? 'Bull (100% CAGR)' : '牛市 (100%)', cagr: 1.0, color: 'var(--ch-profit-strong)' },
	] as const;
	const projectionData = $derived.by(() => {
		const btc = projBtcPrice ?? 60000;
		const months = 60; // 5 years
		const W = 560, H = 140;
		const curves = SCENARIOS.map(sc => {
			let btcStack = 0;
			const pts: [number, number][] = [[0, 0]];
			for (let m = 1; m <= months; m++) {
				const btcBought = projMonthly / btc;
				btcStack += btcBought;
				const btcFuturePrice = btc * Math.pow(1 + sc.cagr, m / 12);
				pts.push([m, btcStack * btcFuturePrice]);
			}
			return { ...sc, pts, final: btcStack * btc * Math.pow(1 + sc.cagr, 5) };
		});
		const maxVal = Math.max(...curves.flatMap(c => c.pts.map(p => p[1])), 1);
		function toX(m: number) { return (m / months) * W; }
		function toY(v: number) { return H - (v / maxVal) * H; }
		return curves.map(c => ({
			...c,
			polyline: c.pts.map(([m, v]) => `${toX(m).toFixed(1)},${toY(v).toFixed(1)}`).join(' '),
		}));
	});
	onMount(async () => {
		try {
			const r = await fetch('https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT');
			if (r.ok) { const d = await r.json(); projBtcPrice = parseFloat(d.price); }
		} catch { /* ignore */ }
	});

	// Weekly trigger activity — last 26 weeks grouped by ISO week
	const weeklyTriggers = $derived.by(() => {
		if (data.triggers.length === 0) return null;
		const byWeek = new Map<string, { count: number; usdt: number }>();
		for (const tr of data.triggers) {
			const d = new Date(tr.ts);
			const dow = (d.getDay() + 6) % 7;
			const mon = new Date(d); mon.setDate(d.getDate() - dow);
			const key = mon.toISOString().slice(0, 10);
			const cur = byWeek.get(key) ?? { count: 0, usdt: 0 };
			cur.count++;
			cur.usdt += tr.amount_usdt ?? 0;
			byWeek.set(key, cur);
		}
		const sorted = [...byWeek.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(-26);
		if (sorted.length < 2) return null;
		const maxCount = Math.max(1, ...sorted.map(([, v]) => v.count));
		const totalUsdt = sorted.reduce((s, [, v]) => s + v.usdt, 0);
		const W = 520, H = 60;
		const barW = Math.max(3, W / sorted.length - 1);
		return {
			bars: sorted.map(([week, v], i) => ({
				x: i * (W / sorted.length),
				h: (v.count / maxCount) * (H - 4),
				week,
				count: v.count,
				usdt: v.usdt,
			})),
			W, H, barW, totalUsdt, weeks: sorted.length,
		};
	});

	// Severity distribution histogram (10 bins from 0 to 1)
	const severityHistogram = $derived.by(() => {
		const vals = data.triggers.map(t => t.severity).filter((v): v is number => v != null && v >= 0 && v <= 1);
		if (vals.length < 5) return null;
		const BINS = 10;
		const buckets = Array.from({ length: BINS }, (_, i) => ({
			lo: i / BINS, hi: (i + 1) / BINS,
			FLASH: 0, FAST: 0, SUSTAIN: 0, CAPITUL: 0, other: 0, total: 0,
		}));
		for (let i = 0; i < vals.length; i++) {
			const v = vals[i];
			const kind = data.triggers[i]?.kind ?? 'other';
			const idx = Math.min(BINS - 1, Math.floor(v * BINS));
			const b = buckets[idx];
			b.total++;
			if (kind === 'FLASH') b.FLASH++;
			else if (kind === 'FAST') b.FAST++;
			else if (kind === 'SUSTAIN') b.SUSTAIN++;
			else if (kind === 'CAPITUL') b.CAPITUL++;
			else b.other++;
		}
		const maxTotal = Math.max(1, ...buckets.map(b => b.total));
		return { buckets, maxTotal, total: vals.length };
	});

	// Capital deployed by signal kind
	const KIND_DEPLOY_COLORS: Record<string, string> = {
		FLASH:   'var(--ch-loss)',
		FAST:    'var(--ch-warn)',
		SUSTAIN: 'var(--ch-violet)',
		CAPITUL: 'var(--ch-violet-strong)',
	};
	const kindAmountChart = $derived.by(() => {
		const KINDS = ['FLASH', 'FAST', 'SUSTAIN', 'CAPITUL'];
		const map = new Map<string, { usdt: number; count: number }>(KINDS.map(k => [k, { usdt: 0, count: 0 }]));
		for (const tr of data.triggers) {
			if (!map.has(tr.kind)) continue;
			const e = map.get(tr.kind)!;
			e.usdt += tr.amount_usdt ?? 0;
			e.count++;
		}
		const rows = KINDS.map(k => ({ kind: k, ...map.get(k)! })).filter(r => r.count > 0);
		if (rows.length === 0) return null;
		const total = rows.reduce((s, r) => s + r.usdt, 0);
		const maxUsdt = Math.max(1, ...rows.map(r => r.usdt));
		return rows.map(r => ({ ...r, pct: (r.usdt / total) * 100, barPct: (r.usdt / maxUsdt) * 100 }));
	});

	// Severity vs Amount scatter: do higher-severity events deploy more capital?
	const sevAmountScatter = $derived.by(() => {
		const pts = data.triggers.filter(tr => tr.severity != null && tr.amount_usdt != null && tr.amount_usdt > 0);
		if (pts.length < 5) return null;
		const sevs = pts.map(tr => tr.severity!);
		const amounts = pts.map(tr => tr.amount_usdt!);
		const sMin = Math.min(...sevs), sMax = Math.max(...sevs);
		const aMax = Math.max(...amounts);
		const W = 400, H = 100, PAD = 12;
		const toX = (v: number) => PAD + ((v - sMin) / (sMax - sMin || 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v / aMax) * (H - PAD * 2);
		const KIND_COLOR: Record<string, string> = {
			FLASH: 'var(--ch-loss)', FAST: 'var(--ch-warn)',
			SUSTAIN: 'var(--ch-violet)', CAPITUL: 'var(--ch-violet-strong)',
		};
		const dots = pts.map(tr => ({
			x: toX(tr.severity!), y: toY(tr.amount_usdt!),
			kind: tr.kind, amount: tr.amount_usdt!, sev: tr.severity!,
			color: KIND_COLOR[tr.kind] ?? 'var(--ch-axis-muted)',
		}));
		return { dots, W, H, PAD, sMin, sMax, aMax };
	});

	// Trigger hour-of-day distribution (UTC)
	// Rolling 5-event moving average of DCA amount — is sizing growing or shrinking?
	const dcaAmountTrend = $derived.by(() => {
		const evts = data.triggers
			.filter(tr => tr.ts && tr.amount_usdt != null && tr.amount_usdt > 0)
			.sort((a, b) => a.ts.localeCompare(b.ts));
		if (evts.length < 8) return null;
		const WINDOW = 5;
		const mas: { i: number; ma: number; amount: number; date: string }[] = [];
		for (let i = WINDOW - 1; i < evts.length; i++) {
			const slice = evts.slice(i - WINDOW + 1, i + 1);
			const ma = slice.reduce((s, e) => s + e.amount_usdt!, 0) / WINDOW;
			mas.push({ i, ma, amount: evts[i].amount_usdt!, date: evts[i].ts.slice(0, 10) });
		}
		if (mas.length < 3) return null;
		const W = 520, H = 70, PAD = 6;
		const vals = mas.map(m => m.ma);
		const vMin = Math.min(...vals), vMax = Math.max(...vals, vMin + 0.01);
		const toX = (i: number) => PAD + (i / Math.max(1, mas.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - vMin) / (vMax - vMin)) * (H - PAD * 2);
		const polyline = mas.map((m, i) => `${toX(i).toFixed(1)},${toY(m.ma).toFixed(1)}`).join(' ');
		const trend = mas[mas.length - 1].ma - mas[0].ma;
		return { polyline, W, H, PAD, trend, first: mas[0].date, last: mas[mas.length - 1].date, latest: mas[mas.length - 1].ma, n: mas.length };
	});

	const triggerHourChart = $derived.by(() => {
		const events = data.triggers.filter(tr => tr.ts);
		if (events.length < 5) return null;
		const hours = Array.from({ length: 24 }, (_, h) => ({ h, count: 0, amount: 0 }));
		for (const tr of events) {
			const h = new Date(tr.ts).getUTCHours();
			hours[h].count++;
			hours[h].amount += tr.amount_usdt ?? 0;
		}
		const maxCount = Math.max(1, ...hours.map(h => h.count));
		return hours.map(h => ({ ...h, barPct: (h.count / maxCount) * 100 }));
	});

	// Kind × day-of-week heatmap: how many triggers of each kind fire on each weekday
	const kindDowHeatmap = $derived.by(() => {
		const evts = data.triggers.filter(tr => tr.ts && tr.kind);
		if (evts.length < 6) return null;
		const kinds = [...new Set(evts.map(e => e.kind))].sort();
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const grid: Record<string, number[]> = {};
		for (const k of kinds) grid[k] = Array(7).fill(0);
		for (const e of evts) {
			const dow = new Date(e.ts).getDay();
			grid[e.kind][dow]++;
		}
		const maxVal = Math.max(1, ...kinds.flatMap(k => grid[k]));
		return { kinds, days: DAYS, grid, maxVal };
	});

	// Severity timeline: rolling 5-event avg of trigger severity over time
	const severityTimeline = $derived.by(() => {
		const evts = data.triggers
			.filter(e => e.ts && e.severity != null)
			.sort((a, b) => a.ts.localeCompare(b.ts));
		if (evts.length < 8) return null;
		const WINDOW = 5;
		const pts: { i: number; ma: number; date: string; kind: string }[] = [];
		for (let i = WINDOW - 1; i < evts.length; i++) {
			const slice = evts.slice(i - WINDOW + 1, i + 1);
			const ma = slice.reduce((s, e) => s + e.severity!, 0) / WINDOW;
			pts.push({ i, ma, date: evts[i].ts.slice(0, 10), kind: evts[i].kind });
		}
		if (pts.length < 3) return null;
		const W = 520, H = 70, PAD = 6;
		const vals = pts.map(p => p.ma);
		const vMin = 0, vMax = 1;
		const toX = (i: number) => PAD + (i / Math.max(1, pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - vMin) / (vMax - vMin)) * (H - PAD * 2);
		const polyline = pts.map((p, i) => `${toX(i).toFixed(1)},${toY(p.ma).toFixed(1)}`).join(' ');
		const latest = vals[vals.length - 1];
		const peak = Math.max(...vals);
		return { polyline, W, H, PAD, pts, latest, peak, first: pts[0].date, last: pts[pts.length - 1].date };
	});

	// Kind cumulative USDT share: total capital deployed per trigger kind
	// Trigger gap distribution: time between consecutive triggers
	const triggerGapDistribution = $derived.by(() => {
		const sorted = data.triggers
			.filter(t => t.ts)
			.map(t => new Date(t.ts).getTime())
			.sort((a, b) => a - b);
		if (sorted.length < 5) return null;
		const BUCKETS = [
			{ label: '<1h', lo: 0, hi: 3600 * 1000 },
			{ label: '1–6h', lo: 3600 * 1000, hi: 6 * 3600 * 1000 },
			{ label: '6–24h', lo: 6 * 3600 * 1000, hi: 24 * 3600 * 1000 },
			{ label: '1–7d', lo: 24 * 3600 * 1000, hi: 7 * 24 * 3600 * 1000 },
			{ label: '7d+', lo: 7 * 24 * 3600 * 1000, hi: Infinity },
		];
		const counts = BUCKETS.map(b => ({ ...b, count: 0 }));
		for (let i = 1; i < sorted.length; i++) {
			const gap = sorted[i] - sorted[i - 1];
			const bucket = counts.find(b => gap >= b.lo && gap < b.hi);
			if (bucket) bucket.count++;
		}
		const maxCount = Math.max(1, ...counts.map(c => c.count));
		const avgGapH = (sorted[sorted.length - 1] - sorted[0]) / Math.max(1, sorted.length - 1) / 3600000;
		return { buckets: counts, maxCount, avgGapH };
	});

	// USDT deployed by day of week
	// Monthly trigger summary: count + total USDT per month (last 12 months)
	const monthlyTriggerSummary = $derived.by(() => {
		const evts = data.triggers.filter(t => t.ts);
		if (evts.length < 5) return null;
		const now = new Date();
		const months = Array.from({ length: 12 }, (_, i) => {
			const d = new Date(now.getFullYear(), now.getMonth() - (11 - i), 1);
			const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
			const label = d.toLocaleDateString('en', { month: 'short', year: '2-digit' });
			return { key, label, count: 0, total: 0 };
		});
		for (const t of evts) {
			const key = t.ts.slice(0, 7);
			const m = months.find(m => m.key === key);
			if (!m) continue;
			m.count++;
			m.total += t.amount_usdt ?? 0;
		}
		const active = months.filter(m => m.count > 0);
		if (active.length < 2) return null;
		const maxCount = Math.max(1, ...active.map(m => m.count));
		return active.map(m => ({ ...m, barPct: (m.count / maxCount) * 100 }));
	});

	const amountByDayOfWeek = $derived.by(() => {
		const evts = data.triggers.filter(t => t.ts && t.amount_usdt != null && t.amount_usdt > 0);
		if (evts.length < 7) return null;
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const days = DAYS.map((label, dow) => ({ label, dow, total: 0, count: 0 }));
		for (const e of evts) {
			const dow = new Date(e.ts).getDay();
			days[dow].total += e.amount_usdt!;
			days[dow].count++;
		}
		const maxTotal = Math.max(1, ...days.map(d => d.total));
		// reorder Mon-Sun
		const ordered = [1,2,3,4,5,6,0].map(i => days[i]);
		return ordered.map(d => ({ ...d, barPct: (d.total / maxTotal) * 100, avg: d.count > 0 ? d.total / d.count : 0 }));
	});

	// Avg USDT deployed per severity bucket: does higher severity = more capital?
	const avgAmountBySeverity = $derived.by(() => {
		const evts = data.triggers.filter(e => e.severity != null && e.amount_usdt != null && e.amount_usdt > 0);
		if (evts.length < 8) return null;
		const BUCKETS = [
			{ label: '0.0–0.2', lo: 0, hi: 0.2, vals: [] as number[] },
			{ label: '0.2–0.4', lo: 0.2, hi: 0.4, vals: [] as number[] },
			{ label: '0.4–0.6', lo: 0.4, hi: 0.6, vals: [] as number[] },
			{ label: '0.6–0.8', lo: 0.6, hi: 0.8, vals: [] as number[] },
			{ label: '0.8–1.0', lo: 0.8, hi: 1.01, vals: [] as number[] },
		];
		for (const e of evts) {
			const b = BUCKETS.find(bk => e.severity! >= bk.lo && e.severity! < bk.hi);
			if (b) b.vals.push(e.amount_usdt!);
		}
		const rows = BUCKETS.map(b => ({
			label: b.label,
			count: b.vals.length,
			avg: b.vals.length ? b.vals.reduce((a, x) => a + x, 0) / b.vals.length : null,
		})).filter(r => r.count > 0);
		if (rows.length < 2) return null;
		const maxAvg = Math.max(0.01, ...rows.map(r => r.avg ?? 0));
		return rows.map(r => ({ ...r, barPct: r.avg != null ? (r.avg / maxAvg) * 100 : 0 }));
	});

	// F&G distribution at trigger time: which sentiment levels actually produce DCA signals?
	const triggerFngDistribution = $derived.by(() => {
		const evts = data.triggers.filter(e => e.fng != null);
		if (evts.length < 8) return null;
		const BINS = 10;
		const buckets = Array.from({ length: BINS }, (_, i) => ({
			lo: i * 10, hi: (i + 1) * 10,
			label: `${i * 10}–${(i + 1) * 10}`,
			count: 0, totalAmt: 0,
			color: i < 3 ? 'var(--ch-profit)' : i < 5 ? 'var(--ch-profit-light)' : i < 6 ? 'var(--ch-warn-light)' : i < 8 ? 'var(--ch-loss-light)' : 'var(--ch-loss)',
		}));
		for (const e of evts) {
			const idx = Math.min(BINS - 1, Math.floor(e.fng! / 10));
			buckets[idx].count++;
			buckets[idx].totalAmt += e.amount_usdt ?? 0;
		}
		const maxCount = Math.max(1, ...buckets.map(b => b.count));
		return buckets.map(b => ({ ...b, barPct: (b.count / maxCount) * 100, avgAmt: b.count > 0 ? b.totalAmt / b.count : null }));
	});

	const kindCumulativeShare = $derived.by(() => {
		const evts = data.triggers.filter(e => e.kind && e.amount_usdt != null && e.amount_usdt > 0);
		if (evts.length < 4) return null;
		const map = new Map<string, { total: number; count: number; avgSev: number; sevSum: number }>();
		for (const e of evts) {
			if (!map.has(e.kind)) map.set(e.kind, { total: 0, count: 0, avgSev: 0, sevSum: 0 });
			const v = map.get(e.kind)!;
			v.total += e.amount_usdt!;
			v.count++;
			v.sevSum += e.severity ?? 0;
		}
		const grandTotal = [...map.values()].reduce((s, v) => s + v.total, 0);
		if (grandTotal === 0) return null;
		const rows = [...map.entries()]
			.map(([kind, v]) => ({ kind, total: v.total, count: v.count, pct: v.total / grandTotal, avgSev: v.sevSum / v.count }))
			.sort((a, b) => b.total - a.total);
		return { rows, grandTotal };
	});

	// Monthly trigger volume: count + total USDT per calendar month for last 12 months
	const monthlyTriggerVolume = $derived.by(() => {
		if (data.triggers.length < 5) return null;
		const now = new Date();
		const months = Array.from({ length: 12 }, (_, i) => {
			const d = new Date(now.getFullYear(), now.getMonth() - (11 - i), 1);
			const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
			const label = d.toLocaleDateString('en', { month: 'short', year: '2-digit' });
			return { key, label, count: 0, usdt: 0 };
		});
		for (const tr of data.triggers) {
			if (!tr.ts) continue;
			const key = tr.ts.slice(0, 7);
			const m = months.find(mo => mo.key === key);
			if (!m) continue;
			m.count++;
			if (tr.amount_usdt != null) m.usdt += tr.amount_usdt;
		}
		const active = months.filter(m => m.count > 0);
		if (active.length < 2) return null;
		const maxCount = Math.max(1, ...months.map(m => m.count));
		const maxUsdt = Math.max(1, ...months.map(m => m.usdt));
		return months.map(m => ({ ...m, countPct: (m.count / maxCount) * 100, usdtPct: (m.usdt / maxUsdt) * 100 }));
	});

	// F&G sentiment drift: rolling 8-event avg of F&G at trigger time — shows if DCA fires in increasingly fearful/greedy markets
	const fngAtTriggerTimeline = $derived.by(() => {
		const evts = [...data.triggers]
			.filter(e => e.fng != null && e.ts)
			.sort((a, b) => a.ts.localeCompare(b.ts));
		if (evts.length < 10) return null;
		const WINDOW = 8;
		const pts: { i: number; avg: number; date: string }[] = [];
		for (let i = WINDOW - 1; i < evts.length; i++) {
			const slice = evts.slice(i - WINDOW + 1, i + 1);
			const avg = slice.reduce((s, e) => s + e.fng!, 0) / slice.length;
			pts.push({ i: i - WINDOW + 1, avg, date: evts[i].ts.slice(0, 10) });
		}
		const W = 560, H = 72, PAD = 8;
		const toX = (idx: number) => PAD + (idx / Math.max(1, pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - 0) / 100) * (H - PAD * 2);
		const polyline = pts.map(p => `${toX(p.i).toFixed(1)},${toY(p.avg).toFixed(1)}`).join(' ');
		const fearY = toY(25), greedY = toY(75);
		const latest = pts[pts.length - 1].avg;
		const earliest = pts[0].avg;
		return { polyline, W, H, PAD, fearY, greedY, latest, earliest, drift: latest - earliest, count: evts.length, firstDate: pts[0].date, lastDate: pts[pts.length - 1].date };
	});

	const severityAmountCumulative = $derived.by(() => {
		const evts = [...data.triggers]
			.filter(e => e.ts && e.amount_usdt != null && e.severity != null)
			.sort((a, b) => a.ts.localeCompare(b.ts));
		if (evts.length < 5) return null;
		const sevs = [...new Set(evts.map(e => e.severity!))].sort((a, b) => a - b).slice(0, 5);
		const COLORS = ['var(--ch-violet)', 'var(--ch-warn)', 'var(--ch-loss)', 'var(--ch-profit)', 'var(--ch-warn)'];
		const running = Object.fromEntries(sevs.map(s => [s, 0]));
		const pts = evts.map(e => {
			if (sevs.includes(e.severity!)) running[e.severity!] += e.amount_usdt!;
			return { ts: e.ts.slice(0, 10), snap: { ...running } };
		});
		const last = pts[pts.length - 1].snap;
		const totals = sevs.map(s => ({ sev: s, total: last[s] ?? 0 }));
		const grandTotal = Math.max(0.01, totals.reduce((s, r) => s + r.total, 0));
		return { totals, sevs, grandTotal, COLORS };
	});

	const triggerDayOfMonth = $derived.by(() => {
		const counts = Array.from({ length: 31 }, (_, i) => ({ day: i + 1, count: 0 }));
		for (const e of data.triggers) {
			if (!e.ts) continue;
			const d = new Date(e.ts).getUTCDate();
			if (d >= 1 && d <= 31) counts[d - 1].count++;
		}
		const filled = counts.filter(c => c.count > 0);
		if (filled.length < 5) return null;
		const maxCount = Math.max(1, ...counts.map(c => c.count));
		return counts.map(c => ({ ...c, barPct: (c.count / maxCount) * 100 }));
	});

	const fngKindAvg = $derived.by(() => {
		const evts = data.triggers.filter(e => e.fng != null && e.kind);
		if (evts.length < 8) return null;
		const map = new Map<string, number[]>();
		for (const e of evts) {
			if (!map.has(e.kind)) map.set(e.kind, []);
			map.get(e.kind)!.push(e.fng!);
		}
		const rows = [...map.entries()]
			.filter(([, vals]) => vals.length >= 3)
			.map(([kind, vals]) => ({ kind, avg: vals.reduce((a, b) => a + b, 0) / vals.length, count: vals.length }))
			.sort((a, b) => a.avg - b.avg);
		if (rows.length < 2) return null;
		return rows;
	});

	// Cumulative USDT deployed per kind over time — shows which kinds contribute most capital (distinct from kindCumulativeShare proportional bars and severityAmountCumulative)
	const kindCumulativeLines = $derived.by(() => {
		const kinds = [...new Set(data.triggers.filter(e => e.amount_usdt != null && e.kind).map(e => e.kind))].sort();
		if (kinds.length < 2) return null;
		const sorted = [...data.triggers]
			.filter(e => e.ts && e.amount_usdt != null)
			.sort((a, b) => a.ts.localeCompare(b.ts));
		if (sorted.length < 5) return null;
		const COLORS: Record<string, string> = { FLASH: 'var(--ch-loss-strong)', FAST: 'var(--ch-warn)', SUSTAIN: 'var(--ch-violet-strong)', CAPITUL: 'var(--ch-violet-strong)' };
		const cumByKind = new Map<string, number>(kinds.map(k => [k, 0]));
		const points: { ts: string; totals: Map<string, number> }[] = [];
		for (const e of sorted) {
			if (e.amount_usdt == null) continue;
			cumByKind.set(e.kind, (cumByKind.get(e.kind) ?? 0) + e.amount_usdt);
			points.push({ ts: e.ts, totals: new Map(cumByKind) });
		}
		const finalMax = Math.max(1, ...kinds.map(k => cumByKind.get(k) ?? 0));
		const W = 560, H = 80, PAD = 4;
		const toX = (i: number) => PAD + (i / Math.max(1, points.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v / finalMax) * (H - PAD * 2);
		const lines = kinds.map(k => ({
			kind: k,
			color: COLORS[k] ?? 'var(--ch-axis)',
			poly: points.map((p, i) => `${toX(i).toFixed(1)},${toY(p.totals.get(k) ?? 0).toFixed(1)}`).join(' '),
			final: cumByKind.get(k) ?? 0,
		}));
		return { lines, W, H, PAD, finalMax };
	});

	// Individual trigger amount distribution: histogram of DCA amounts (distinct from avgAmountBySeverity, severityAmountCumulative, kindCumulativeLines)
	const triggerAmountDistribution = $derived.by(() => {
		const vals = data.triggers.filter(e => e.amount_usdt != null && e.amount_usdt > 0).map(e => e.amount_usdt!);
		if (vals.length < 6) return null;
		const mn = Math.min(...vals), mx = Math.max(...vals);
		if (mn === mx) return null;
		const BINS = 8;
		const step = (mx - mn) / BINS;
		const buckets = Array.from({ length: BINS }, (_, i) => ({
			lo: mn + i * step,
			hi: mn + (i + 1) * step,
			label: `$${(mn + i * step).toFixed(0)}`,
			count: 0,
		}));
		for (const v of vals) {
			const idx = Math.min(BINS - 1, Math.floor((v - mn) / step));
			buckets[idx].count++;
		}
		const maxCount = Math.max(1, ...buckets.map(b => b.count));
		const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
		const median = [...vals].sort((a, b) => a - b)[Math.floor(vals.length / 2)];
		return { buckets: buckets.map(b => ({ ...b, barPct: (b.count / maxCount) * 100 })), avg, median, total: vals.length, mn, mx };
	});

	const fngAmountScatter = $derived.by(() => {
		const pts = data.triggers
			.filter(e => e.fng != null && e.amount_usdt != null && e.amount_usdt > 0 && isFinite(e.fng) && isFinite(e.amount_usdt))
			.map(e => ({ fng: e.fng!, amt: e.amount_usdt! }));
		if (pts.length < 8) return null;
		const minF = Math.min(...pts.map(p => p.fng)), maxF = Math.max(...pts.map(p => p.fng));
		const minA = Math.min(...pts.map(p => p.amt)), maxA = Math.max(...pts.map(p => p.amt));
		const W = 300, H = 80, PAD = 12;
		const toX = (f: number) => PAD + ((f - minF) / Math.max(1, maxF - minF)) * (W - PAD * 2);
		const toY = (a: number) => H - PAD - ((a - minA) / Math.max(0.01, maxA - minA)) * (H - PAD * 2);
		const mapped = pts.map(p => ({ cx: toX(p.fng), cy: toY(p.amt), fng: p.fng, amt: p.amt }));
		return { mapped, W, H, PAD, minF, maxF, minA, maxA };
	});

	const triggerIntervalDistribution = $derived.by(() => {
		const ts = data.triggers
			.filter(e => e.ts)
			.map(e => new Date(e.ts!).getTime())
			.sort((a, b) => a - b);
		if (ts.length < 6) return null;
		const gaps = ts.slice(1).map((t, i) => (t - ts[i]) / 3600000);
		const filtered = gaps.filter(g => g < 720);
		if (filtered.length < 5) return null;
		const BINS = 8, mx = Math.max(...filtered);
		const step = mx / BINS;
		const buckets = Array.from({ length: BINS }, (_, i) => ({
			label: i === BINS - 1 ? `>${(i * step).toFixed(0)}h` : `${(i * step).toFixed(0)}–${((i + 1) * step).toFixed(0)}h`,
			count: 0
		}));
		for (const g of filtered) {
			const idx = Math.min(BINS - 1, Math.floor(g / step));
			buckets[idx].count++;
		}
		const maxCount = Math.max(1, ...buckets.map(b => b.count));
		const median = [...filtered].sort((a, b) => a - b)[Math.floor(filtered.length / 2)];
		return { buckets: buckets.map(b => ({ ...b, barPct: (b.count / maxCount) * 100 })), median: median.toFixed(1), total: filtered.length };
	});

	const triggerHourDistribution = $derived.by(() => {
		const counts = Array(24).fill(0);
		let total = 0;
		for (const e of data.triggers) {
			if (!e.ts) continue;
			const h = new Date(e.ts).getUTCHours();
			counts[h]++;
			total++;
		}
		if (total < 10) return null;
		const maxCount = Math.max(1, ...counts);
		return { counts: counts.map((c, h) => ({ h, count: c, barPct: (c / maxCount) * 100 })), total };
	});

	const triggerMonthlyCount = $derived.by(() => {
		const map = new Map<string, number>();
		for (const e of data.triggers) {
			if (!e.ts) continue;
			const ym = new Date(e.ts).toISOString().slice(0, 7);
			map.set(ym, (map.get(ym) ?? 0) + 1);
		}
		if (map.size < 3) return null;
		const rows = [...map.entries()].map(([ym, count]) => ({ ym, count })).sort((a, b) => a.ym.localeCompare(b.ym));
		const maxCount = Math.max(1, ...rows.map(r => r.count));
		return rows.map(r => ({ ...r, barPct: (r.count / maxCount) * 100 }));
	});

	const triggerAmountByMonth = $derived.by(() => {
		const map = new Map<string, number>();
		for (const e of data.triggers) {
			if (!e.ts || e.amount_usdt == null || !isFinite(e.amount_usdt)) continue;
			const ym = new Date(e.ts).toISOString().slice(0, 7);
			map.set(ym, (map.get(ym) ?? 0) + e.amount_usdt);
		}
		if (map.size < 3) return null;
		const rows = [...map.entries()].map(([ym, total]) => ({ ym, total })).sort((a, b) => a.ym.localeCompare(b.ym));
		const maxTotal = Math.max(1, ...rows.map(r => r.total));
		return rows.map(r => ({ ...r, barPct: (r.total / maxTotal) * 100 }));
	});

	const kindFngProfile = $derived.by(() => {
		const map = new Map<string, { sum: number; count: number }>();
		for (const e of data.triggers) {
			if (!e.kind || e.fng == null || !isFinite(e.fng)) continue;
			const entry = map.get(e.kind);
			if (!entry) map.set(e.kind, { sum: e.fng, count: 1 });
			else { entry.sum += e.fng; entry.count++; }
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([kind, v]) => ({ kind, avg: v.sum / v.count, count: v.count }))
			.sort((a, b) => a.avg - b.avg);
		const maxAvg = Math.max(1, ...rows.map(r => r.avg));
		const KIND_COLORS: Record<string, string> = { FLASH: 'var(--ch-loss)', FAST: 'var(--ch-warn)', SUSTAIN: 'var(--ch-violet)', CAPITUL: 'var(--ch-violet-strong)' };
		return rows.map(r => ({ ...r, barPct: (r.avg / maxAvg) * 100, color: KIND_COLORS[r.kind] ?? 'var(--ch-axis)' }));
	});

	const triggerSeverityBreakdown = $derived.by(() => {
		const sevVals = data.triggers.filter(e => e.severity != null && isFinite(e.severity as number)).map(e => e.severity as number);
		if (sevVals.length < 5) return null;
		const mn = Math.min(...sevVals), mx = Math.max(...sevVals);
		if (mx === mn) return null;
		const BINS = 4;
		const step = (mx - mn) / BINS;
		const SEV_LABELS = ['Low', 'Medium', 'High', 'Extreme'];
		const SEV_COLORS = ['var(--ch-profit)', 'var(--ch-warn)', 'var(--ch-warn)', 'var(--ch-loss-strong)'];
		const buckets = Array.from({ length: BINS }, (_, i) => ({ label: SEV_LABELS[i], lo: mn + i * step, hi: mn + (i + 1) * step, count: 0, sumAmt: 0, sumFng: 0, color: SEV_COLORS[i] }));
		for (const e of data.triggers) {
			if (e.severity == null || !isFinite(e.severity)) continue;
			const idx = Math.min(BINS - 1, Math.floor((e.severity - mn) / step));
			buckets[idx].count++;
			if (e.amount_usdt != null && isFinite(e.amount_usdt)) buckets[idx].sumAmt += e.amount_usdt;
			if (e.fng != null && isFinite(e.fng)) buckets[idx].sumFng += e.fng;
		}
		const active = buckets.filter(b => b.count > 0);
		if (active.length < 2) return null;
		const maxCount = Math.max(1, ...active.map(b => b.count));
		return active.map(b => ({ ...b, barPct: (b.count / maxCount) * 100, avgAmt: b.count > 0 ? b.sumAmt / b.count : 0, avgFng: b.count > 0 ? b.sumFng / b.count : 0 }));
	});

	const triggerCumulativeAmount = $derived.by(() => {
		const sorted = data.triggers
			.filter(e => e.ts && e.amount_usdt != null && isFinite(e.amount_usdt))
			.sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
		if (sorted.length < 5) return null;
		let cum = 0;
		const pts = sorted.map(e => { cum += e.amount_usdt!; return cum; });
		const mn = pts[0], mx = pts[pts.length - 1];
		const range = mx - mn || 1;
		const W = 400, H = 60, PAD = 6;
		const toX = (i: number) => PAD + (i / Math.max(1, pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / range) * (H - PAD * 2);
		const poly = pts.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
		const first = sorted[0].ts.slice(0, 7), last = sorted[sorted.length - 1].ts.slice(0, 7);
		return { poly, W, H, PAD, total: mx, first, last, count: sorted.length };
	});

	const triggerFngTimeline = $derived.by(() => {
		const sorted = data.triggers
			.filter(e => e.ts && e.fng != null && isFinite(e.fng))
			.sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
		if (sorted.length < 5) return null;
		const vals = sorted.map(e => e.fng!);
		const mn = Math.min(...vals), mx = Math.max(...vals);
		const range = mx - mn || 1;
		const W = 400, H = 60, PAD = 6;
		const toX = (i: number) => PAD + (i / Math.max(1, vals.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / range) * (H - PAD * 2);
		const poly = vals.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
		const fearY = toY(25);
		const greedY = toY(75);
		const avgFng = vals.reduce((a, b) => a + b, 0) / vals.length;
		const first = sorted[0].ts.slice(0, 7), last = sorted[sorted.length - 1].ts.slice(0, 7);
		return { poly, W, H, PAD, mn, mx, avgFng, fearY, greedY, first, last, count: vals.length };
	});

	const triggerKindTimeline = $derived.by(() => {
		const kinds = [...new Set(data.triggers.map(e => e.kind).filter(Boolean))] as string[];
		if (kinds.length < 2) return null;
		const map = new Map<string, Map<string, number>>();
		for (const e of data.triggers) {
			if (!e.ts || !e.kind) continue;
			const ym = e.ts.slice(0, 7);
			if (!map.has(ym)) map.set(ym, new Map());
			const km = map.get(ym)!;
			km.set(e.kind, (km.get(e.kind) ?? 0) + 1);
		}
		if (map.size < 2) return null;
		const months = [...map.keys()].sort();
		const KIND_COLORS: Record<string, string> = { FLASH: 'var(--ch-loss)', FAST: 'var(--ch-warn)', SUSTAIN: 'var(--ch-violet)', CAPITUL: 'var(--ch-violet-strong)' };
		const rows = months.map(ym => ({
			ym,
			kinds: kinds.map(k => ({ kind: k, count: map.get(ym)?.get(k) ?? 0, color: KIND_COLORS[k] ?? 'var(--ch-axis)' }))
		}));
		const maxTotal = Math.max(1, ...rows.map(r => r.kinds.reduce((s, k) => s + k.count, 0)));
		return { rows, kinds, maxTotal, KIND_COLORS };
	});

	const triggerDowDistribution = $derived.by(() => {
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const counts = new Array(7).fill(0);
		let total = 0;
		for (const e of data.triggers) {
			if (!e.ts) continue;
			const dow = new Date(e.ts).getDay();
			counts[dow]++;
			total++;
		}
		if (total < 7) return null;
		const maxCount = Math.max(1, ...counts);
		return DAYS.map((label, i) => ({ label, count: counts[i], barPct: (counts[i] / maxCount) * 100, pct: counts[i] / total }));
	});

	const triggerAmountVsSeverity = $derived.by(() => {
		const pts = data.triggers.filter(e =>
			e.amount_usdt != null && isFinite(e.amount_usdt) && e.amount_usdt > 0 &&
			e.severity != null && isFinite(e.severity as number)
		);
		if (pts.length < 8) return null;
		const xs = pts.map(e => e.severity as number);
		const ys = pts.map(e => e.amount_usdt);
		const xMin = Math.min(...xs), xMax = Math.max(...xs);
		const yMin = Math.min(...ys), yMax = Math.max(...ys);
		if (xMax - xMin < 0.01 || yMax - yMin < 0.01) return null;
		const W = 400, H = 90, PAD = 10;
		const toX = (v: number) => PAD + ((v - xMin) / (xMax - xMin)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - yMin) / (yMax - yMin)) * (H - PAD * 2);
		const KIND_COLORS: Record<string, string> = { FLASH: 'var(--ch-loss)', FAST: 'var(--ch-warn)', SUSTAIN: 'var(--ch-violet)', CAPITUL: 'var(--ch-violet-strong)' };
		const dots = pts.map(e => ({
			cx: toX(e.severity as number),
			cy: toY(e.amount_usdt),
			color: KIND_COLORS[e.kind ?? ''] ?? 'var(--ch-axis)',
			sev: e.severity as number,
			amt: e.amount_usdt,
			kind: e.kind
		}));
		return { dots, W, H, PAD, xMin, xMax, yMin, yMax };
	});

	// Kind-to-kind transition matrix: what event type follows what
	const dcaKindSequence = $derived.by(() => {
		const evts = data.triggers.filter(e => e.ts && e.kind).sort((a, b) => a.ts.localeCompare(b.ts));
		if (evts.length < 6) return null;
		const kinds = ['FLASH', 'FAST', 'SUSTAIN', 'CAPITUL'].filter(k => evts.some(e => e.kind === k));
		if (kinds.length < 2) return null;
		const matrix = new Map<string, number>();
		for (const k1 of kinds) for (const k2 of kinds) matrix.set(`${k1}→${k2}`, 0);
		for (let i = 0; i < evts.length - 1; i++) {
			const key = `${evts[i].kind}→${evts[i + 1].kind}`;
			if (matrix.has(key)) matrix.set(key, matrix.get(key)! + 1);
		}
		const rowTotals = new Map<string, number>();
		for (const k of kinds) {
			rowTotals.set(k, kinds.reduce((s, k2) => s + (matrix.get(`${k}→${k2}`) ?? 0), 0));
		}
		const maxCount = Math.max(1, ...[...matrix.values()]);
		return { kinds, matrix, rowTotals, maxCount, n: evts.length - 1 };
	});

	// Consecutive same-kind trigger streaks: how often does each kind cluster in runs
	const dcaTriggerStreaks = $derived.by(() => {
		const evts = data.triggers.filter(e => e.ts && e.kind).sort((a, b) => a.ts.localeCompare(b.ts));
		if (evts.length < 5) return null;
		const streaks: Record<string, number[]> = {};
		let curKind = evts[0].kind, curLen = 1;
		for (let i = 1; i < evts.length; i++) {
			if (evts[i].kind === curKind) {
				curLen++;
			} else {
				if (!streaks[curKind]) streaks[curKind] = [];
				streaks[curKind].push(curLen);
				curKind = evts[i].kind;
				curLen = 1;
			}
		}
		if (!streaks[curKind]) streaks[curKind] = [];
		streaks[curKind].push(curLen);
		const kinds = Object.keys(streaks).filter(k => streaks[k].length >= 2);
		if (kinds.length === 0) return null;
		const rows = kinds.map(k => {
			const vals = streaks[k];
			const avg = vals.reduce((s, x) => s + x, 0) / vals.length;
			const max = Math.max(...vals);
			return { kind: k, avg, max, count: vals.length };
		}).sort((a, b) => b.avg - a.avg);
		const maxAvg = Math.max(0.01, ...rows.map(r => r.avg));
		return rows.map(r => ({ ...r, barPct: (r.avg / maxAvg) * 100 }));
	});

	// Avg USDT deployed per FNG bucket (0-20, 20-40, 40-60, 60-80, 80-100)
	const dcaAmountByFngBucket = $derived.by(() => {
		const evts = data.triggers.filter(e => e.fng != null && e.amount_usdt != null && e.amount_usdt > 0);
		if (evts.length < 5) return null;
		const BINS = [
			{ lo: 0,  hi: 20,  label: '0–20\nExtr.Fear' },
			{ lo: 20, hi: 40,  label: '20–40\nFear' },
			{ lo: 40, hi: 60,  label: '40–60\nNeutral' },
			{ lo: 60, hi: 80,  label: '60–80\nGreed' },
			{ lo: 80, hi: 101, label: '80–100\nExtr.Greed' },
		];
		const buckets = BINS.map(b => ({ ...b, sum: 0, count: 0 }));
		for (const e of evts) {
			const idx = buckets.findIndex(b => e.fng! >= b.lo && e.fng! < b.hi);
			if (idx >= 0) { buckets[idx].sum += e.amount_usdt!; buckets[idx].count++; }
		}
		const filled = buckets.filter(b => b.count > 0);
		if (filled.length < 2) return null;
		const rows = buckets.map(b => ({ ...b, avg: b.count > 0 ? b.sum / b.count : 0 }));
		const maxAvg = Math.max(0.01, ...rows.map(r => r.avg));
		return rows.map(r => ({ ...r, barPct: (r.avg / maxAvg) * 100 }));
	});

	const dcaTriggerByKindHour = $derived.by(() => {
		const evts = data.triggers.filter(e => e.kind && e.ts);
		if (evts.length < 8) return null;
		const kinds = [...new Set(evts.map(e => e.kind!))].slice(0, 4);
		const KIND_COLORS: Record<string, string> = {
			FLASH: 'var(--ch-loss)', FAST: 'var(--ch-warn)',
			SUSTAIN: 'var(--ch-violet)', CAPITUL: 'var(--ch-violet-strong)'
		};
		const data2 = kinds.map(kind => {
			const sub = evts.filter(e => e.kind === kind);
			const hours = Array.from({ length: 24 }, (_, h) => ({ h, count: 0 }));
			for (const e of sub) hours[new Date(e.ts).getUTCHours()].count++;
			const maxCount = Math.max(1, ...hours.map(h => h.count));
			return { kind, hours: hours.map(h => ({ ...h, barPct: (h.count / maxCount) * 100 })), total: sub.length, color: KIND_COLORS[kind] ?? 'var(--ch-axis)' };
		});
		const peakHours = data2.map(k => ({ kind: k.kind, peakH: k.hours.reduce((a, b) => b.count > a.count ? b : a).h, color: k.color }));
		return { kinds: data2, peakHours };
	});

	const dcaWeeklyAmountMovingAvg = $derived.by(() => {
		const evts = data.triggers
			.filter(e => e.ts && e.amount_usdt != null && e.amount_usdt > 0)
			.sort((a, b) => a.ts.localeCompare(b.ts));
		if (evts.length < 8) return null;
		const weekMap = new Map<string, number>();
		for (const e of evts) {
			const d = new Date(e.ts);
			const mon = new Date(d); mon.setUTCDate(d.getUTCDate() - d.getUTCDay() + 1);
			const key = mon.toISOString().slice(0, 10);
			weekMap.set(key, (weekMap.get(key) ?? 0) + e.amount_usdt!);
		}
		const weeks = [...weekMap.entries()].sort((a, b) => a[0].localeCompare(b[0]));
		if (weeks.length < 4) return null;
		const WINDOW = 4;
		const pts = weeks.slice(WINDOW - 1).map((_, i) => {
			const slice = weeks.slice(i, i + WINDOW);
			const avg = slice.reduce((s, [, v]) => s + v, 0) / WINDOW;
			return { week: weeks[i + WINDOW - 1][0], avg, raw: weeks[i + WINDOW - 1][1] };
		});
		const W = 560, H = 72, PAD = 8;
		const vals = pts.map(p => p.avg);
		const mn = 0, mx = Math.max(0.01, ...vals);
		const toX = (i: number) => PAD + (i / Math.max(1, pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v / mx) * (H - PAD * 2);
		const polyline = pts.map((p, i) => `${toX(i).toFixed(1)},${toY(p.avg).toFixed(1)}`).join(' ');
		const latest = vals[vals.length - 1];
		const overall = vals.reduce((a, b) => a + b, 0) / vals.length;
		return { W, H, polyline, latest, overall, count: pts.length, mx };
	});

	function fmt(key: string, vars: Record<string, string | number>) {
		let s = t(lang, key);
		for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v));
		return s;
	}

	const dcaCumulativeByKind = $derived.by(() => {
		const sorted = [...filteredTriggers].sort((a, b) => a.ts.localeCompare(b.ts));
		if (sorted.length < 4) return null;
		const kinds = [...new Set(sorted.map(t => t.kind))].slice(0, 5);
		const cumByKind: Record<string, number> = {};
		for (const k of kinds) cumByKind[k] = 0;
		const points: { ts: string; totals: Record<string, number> }[] = [];
		for (const t of sorted) {
			if (cumByKind[t.kind] !== undefined) cumByKind[t.kind] += t.amount_usdt;
			points.push({ ts: t.ts, totals: { ...cumByKind } });
		}
		const W = 560, H = 100, PAD = 8;
		const maxTotal = Math.max(...points.map(p => kinds.reduce((s, k) => s + (p.totals[k] ?? 0), 0)), 1);
		const KIND_COL: Record<string, string> = { event: 'var(--ch-loss)', weekly: 'var(--ch-profit)', manual: 'var(--ch-violet)', dip: 'var(--ch-warn)', fear: 'var(--ch-teal)' };
		const toX = (i: number) => PAD + (i / Math.max(1, points.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v / maxTotal) * (H - PAD * 2);
		const lines = kinds.map(k => ({
			kind: k,
			color: KIND_COL[k] ?? 'var(--ch-axis)',
			poly: points.map((p, i) => `${toX(i).toFixed(1)},${toY(p.totals[k] ?? 0).toFixed(1)}`).join(' '),
			final: cumByKind[k]
		}));
		return { W, H, lines, maxTotal };
	});

	const dcaFngBucketTriggerCount = $derived.by(() => {
		const buckets = [
			{ label: 'Extreme Fear', range: [0, 25], color: 'var(--ch-loss-strong)', count: 0 },
			{ label: 'Fear', range: [25, 50], color: 'var(--ch-warn)', count: 0 },
			{ label: 'Greed', range: [50, 75], color: 'var(--ch-profit)', count: 0 },
			{ label: 'Extreme Greed', range: [75, 100], color: 'var(--ch-violet)', count: 0 }
		];
		for (const t of filteredTriggers) {
			if (t.fng == null) continue;
			for (const b of buckets) {
				if (t.fng >= b.range[0] && t.fng < b.range[1]) { b.count++; break; }
			}
		}
		const total = buckets.reduce((s, b) => s + b.count, 0);
		if (total === 0) return null;
		const maxCount = Math.max(...buckets.map(b => b.count), 1);
		return { buckets, total, maxCount };
	});

	const dcaSeverityTrendTimeline = $derived.by(() => {
		const SEV_SCORE: Record<string, number> = { mild: 1, moderate: 2, severe: 3, extreme: 4 };
		const pts = [...filteredTriggers]
			.filter(t => t.severity && SEV_SCORE[t.severity] != null)
			.sort((a, b) => a.ts.localeCompare(b.ts))
			.map(t => SEV_SCORE[t.severity]);
		if (pts.length < 5) return null;
		const window = 5;
		const smoothed = pts.slice(window - 1).map((_, i) => {
			const slice = pts.slice(i, i + window);
			return slice.reduce((a, b) => a + b, 0) / slice.length;
		});
		const mn = Math.min(...smoothed), mx = Math.max(...smoothed, mn + 0.01);
		const W = 560, H = 72, PAD = 8;
		const toX = (i: number) => PAD + (i / Math.max(1, smoothed.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / (mx - mn)) * (H - PAD * 2);
		const polyline = smoothed.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
		const avg = smoothed.reduce((a, b) => a + b, 0) / smoothed.length;
		const avgY = toY(avg);
		const latest = smoothed[smoothed.length - 1];
		const trend = latest - smoothed[0];
		return { W, H, polyline, avg, avgY, latest, trend, count: smoothed.length };
	});

	const dcaMonthlyTriggerIntensity = $derived.by(() => {
		const map: Record<string, { count: number; totalAmt: number }> = {};
		for (const t of filteredTriggers) {
			if (!t.ts || t.amount_usdt == null || !isFinite(t.amount_usdt)) continue;
			const mo = t.ts.slice(0, 7);
			if (!map[mo]) map[mo] = { count: 0, totalAmt: 0 };
			map[mo].count++;
			map[mo].totalAmt += t.amount_usdt;
		}
		const rows = Object.entries(map)
			.map(([month, v]) => {
				const avgAmt = v.totalAmt / v.count;
				const intensity = v.count * avgAmt;
				return { month, count: v.count, avgAmt, intensity };
			})
			.sort((a, b) => a.month.localeCompare(b.month));
		if (rows.length < 3) return null;
		const maxI = Math.max(...rows.map(r => r.intensity), 0.01);
		const W = 560, H = 80, PAD = 8;
		const barW = Math.max(2, ((W - PAD * 2) / rows.length) - 1);
		const bars = rows.map((r, i) => {
			const x = PAD + i * ((W - PAD * 2) / rows.length);
			const h = Math.max(2, (r.intensity / maxI) * (H - PAD * 2));
			const frac = r.intensity / maxI;
			const color = `rgba(${Math.round(99 + frac * 120)},${Math.round(179 - frac * 100)},${Math.round(246 - frac * 200)},0.82)`;
			return { ...r, x, y: H - PAD - h, h, color };
		});
		return { bars, barW, W, H, maxI, total: rows.length };
	});

	const dcaKindAmountRange = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const t of filteredTriggers) {
			if (!t.kind || t.amount_usdt == null || !isFinite(t.amount_usdt) || t.amount_usdt <= 0) continue;
			if (!map[t.kind]) map[t.kind] = [];
			map[t.kind].push(t.amount_usdt);
		}
		const rows = Object.entries(map)
			.filter(([, v]) => v.length >= 2)
			.map(([kind, vals]) => {
				vals.sort((a, b) => a - b);
				const mn = vals[0];
				const mx = vals[vals.length - 1];
				const median = vals[Math.floor(vals.length / 2)];
				const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
				return { kind, mn, mx, median, avg, count: vals.length };
			})
			.sort((a, b) => b.avg - a.avg);
		if (rows.length < 2) return null;
		const globalMax = Math.max(...rows.map(r => r.mx), 0.01);
		const KIND_COL: Record<string, string> = {
			fear: 'var(--ch-loss)', greed: 'var(--ch-profit)',
			scheduled: 'var(--ch-violet)', manual: 'var(--ch-warn)'
		};
		return { rows, globalMax, KIND_COL };
	});

	const dcaDowAmountProfile = $derived.by(() => {
		const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const map: Record<number, number[]> = {};
		for (const t of filteredTriggers) {
			if (!t.ts || t.amount_usdt == null || !isFinite(t.amount_usdt)) continue;
			const dow = new Date(t.ts).getUTCDay();
			if (!map[dow]) map[dow] = [];
			map[dow].push(t.amount_usdt);
		}
		const rows = DOW.map((label, i) => {
			const vals = map[i] ?? [];
			const total = vals.reduce((a, b) => a + b, 0);
			const count = vals.length;
			const avg = count > 0 ? total / count : 0;
			return { label, total, count, avg };
		});
		if (rows.filter(r => r.count > 0).length < 3) return null;
		const maxTotal = Math.max(...rows.map(r => r.total), 0.01);
		const maxCount = Math.max(...rows.map(r => r.count), 1);
		return { rows, maxTotal, maxCount };
	});

	const dcaHourlyTriggerProfile = $derived.by(() => {
		const hourCounts = Array.from({ length: 24 }, (_, h) => ({ hour: h, count: 0, totalAmt: 0 }));
		for (const t of filteredTriggers) {
			if (!t.ts || t.amount_usdt == null || !isFinite(t.amount_usdt)) continue;
			const h = new Date(t.ts).getUTCHours();
			if (h >= 0 && h < 24) { hourCounts[h].count++; hourCounts[h].totalAmt += t.amount_usdt; }
		}
		const active = hourCounts.filter(h => h.count > 0);
		if (active.length < 3) return null;
		const maxCount = Math.max(...hourCounts.map(h => h.count), 1);
		const W = 560, H = 80, PAD = 8, BAR_W = Math.floor((W - PAD * 2) / 24) - 1;
		const bars = hourCounts.map((h, i) => {
			const x = PAD + i * ((W - PAD * 2) / 24);
			const frac = h.count / maxCount;
			const barH = Math.max(h.count > 0 ? 2 : 0, frac * (H - PAD * 2 - 12));
			const color = frac > 0.66 ? 'var(--ch-loss)' : frac > 0.33 ? 'var(--ch-warn)' : 'var(--ch-violet)';
			return { ...h, x, barH, y: H - PAD - 12 - barH, color };
		});
		const total = filteredTriggers.filter(t => t.ts).length;
		const peakHour = hourCounts.reduce((a, b) => b.count > a.count ? b : a).hour;
		return { bars, BAR_W, W, H, PAD, total, peakHour };
	});

	const dcaAmountVsFngScatter = $derived.by(() => {
		const pts = filteredTriggers
			.filter(t => t.fng != null && isFinite(t.fng) && t.amount_usdt != null && isFinite(t.amount_usdt) && t.amount_usdt > 0)
			.map(t => ({ fng: t.fng!, amt: t.amount_usdt!, kind: t.kind ?? '' }));
		if (pts.length < 6) return null;
		const fMin = Math.min(...pts.map(p => p.fng)), fMax = Math.max(...pts.map(p => p.fng), fMin + 1);
		const aMin = Math.min(...pts.map(p => p.amt)), aMax = Math.max(...pts.map(p => p.amt), aMin + 0.01);
		const W = 560, H = 130, PAD = 12;
		const KIND_COL: Record<string, string> = { fng: 'var(--ch-violet)', price_drop: 'var(--ch-loss)', schedule: 'var(--ch-profit)', manual: 'var(--ch-warn)' };
		const toX = (f: number) => PAD + ((f - fMin) / (fMax - fMin)) * (W - PAD * 2);
		const toY = (a: number) => H - PAD - ((a - aMin) / (aMax - aMin)) * (H - PAD * 2);
		const dots = pts.map(p => ({ cx: toX(p.fng), cy: toY(p.amt), color: KIND_COL[p.kind] ?? 'var(--ch-axis-muted)', fng: p.fng, amt: p.amt }));
		const fearDots = pts.filter(p => p.fng <= 30);
		const avgAmtFear = fearDots.length > 0 ? fearDots.reduce((s, p) => s + p.amt, 0) / fearDots.length : null;
		const greedDots = pts.filter(p => p.fng >= 70);
		const avgAmtGreed = greedDots.length > 0 ? greedDots.reduce((s, p) => s + p.amt, 0) / greedDots.length : null;
		return { W, H, dots, total: pts.length, avgAmtFear: avgAmtFear?.toFixed(0) ?? null, avgAmtGreed: avgAmtGreed?.toFixed(0) ?? null, fMin: fMin.toFixed(0), fMax: fMax.toFixed(0) };
	});

	const dcaSeverityAmountSummary = $derived.by(() => {
		const SEVS = ['low', 'medium', 'high', 'critical'];
		const map: Record<string, number[]> = {};
		for (const t of filteredTriggers) {
			if (!t.severity || t.amount_usdt == null || !isFinite(t.amount_usdt) || t.amount_usdt <= 0) continue;
			const sev = t.severity.toLowerCase();
			if (!map[sev]) map[sev] = [];
			map[sev].push(t.amount_usdt);
		}
		const rows = SEVS.map(sev => {
			const vals = map[sev] ?? [];
			if (vals.length === 0) return null;
			const sorted = [...vals].sort((a, b) => a - b);
			const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
			const p25 = sorted[Math.floor(sorted.length * 0.25)];
			const p75 = sorted[Math.floor(sorted.length * 0.75)];
			return { sev, avg, p25, p75, count: vals.length, min: sorted[0], max: sorted[sorted.length - 1] };
		}).filter((r): r is NonNullable<typeof r> => r !== null);
		if (rows.length < 2) return null;
		const SEV_COL: Record<string, string> = { low: 'var(--ch-profit)', medium: 'var(--ch-warn)', high: 'var(--ch-loss)', critical: 'var(--ch-violet-strong)' };
		const maxAvg = Math.max(...rows.map(r => r.avg), 0.01);
		return { rows, SEV_COL, maxAvg };
	});

	const dcaCumulativeSpend = $derived.by(() => {
		const sorted = [...data.triggers]
			.filter(t => t.amount_usdt != null && isFinite(t.amount_usdt) && t.ts != null)
			.sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());
		if (sorted.length < 3) return null;
		let cum = 0;
		const pts = sorted.map(t => { cum += t.amount_usdt; return cum; });
		const W = 560, H = 70, PAD = 8;
		const mn = 0, mx = pts[pts.length - 1];
		if (mx <= 0) return null;
		const toX = (i: number) => PAD + (i / Math.max(1, pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / (mx - mn)) * (H - PAD * 2);
		const polyline = pts.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
		const total = mx;
		return { W, H, polyline, total: total.toFixed(0), count: sorted.length };
	});

	const dcaKindBreakdown = $derived.by(() => {
		const map: Record<string, { count: number; total: number }> = {};
		for (const t of data.triggers) {
			const kind = t.kind ?? 'unknown';
			if (!map[kind]) map[kind] = { count: 0, total: 0 };
			map[kind].count++;
			if (t.amount_usdt != null && isFinite(t.amount_usdt)) map[kind].total += t.amount_usdt;
		}
		const rows = Object.entries(map)
			.map(([kind, v]) => ({ kind, count: v.count, total: v.total, avg: v.count > 0 ? v.total / v.count : 0 }))
			.sort((a, b) => b.count - a.count);
		if (rows.length < 2) return null;
		const maxCount = Math.max(...rows.map(r => r.count), 1);
		const COLORS = ['var(--ch-violet)', 'var(--ch-profit)', 'var(--ch-warn)', 'var(--ch-loss)', 'var(--ch-violet-strong)'];
		return { rows, maxCount, COLORS };
	});

	const dcaWeeklySpendProfile = $derived.by(() => {
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const map: Record<number, number[]> = {};
		for (const t of data.triggers) {
			if (t.ts == null || t.amount_usdt == null || !isFinite(t.amount_usdt)) continue;
			const dow = new Date(t.ts).getDay();
			if (!map[dow]) map[dow] = [];
			map[dow].push(t.amount_usdt);
		}
		const rows = DAYS.map((day, i) => {
			const vals = map[i] ?? [];
			const avg = vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
			return { day, avg, count: vals.length };
		});
		if (rows.every(r => r.count === 0)) return null;
		const maxAvg = Math.max(...rows.map(r => r.avg), 1);
		const W = 380, H = 70, PAD = 8, barW = Math.floor((W - PAD * 2) / 7) - 2;
		return { rows, maxAvg, W, H, PAD, barW };
	});

	const dcaMonthlySpend = $derived.by(() => {
		const map: Record<string, number> = {};
		for (const t of triggers) {
			if (!t.ts || t.amount_usdt == null) continue;
			const d = new Date(t.ts);
			const key = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
			map[key] = (map[key] ?? 0) + t.amount_usdt;
		}
		const months = Object.keys(map).sort().slice(-12);
		if (months.length < 3) return null;
		const rows = months.map(m => ({ label: m.slice(5), total: map[m] }));
		const maxTotal = Math.max(...rows.map(r => r.total), 1);
		const W = 420, H = 70, PAD = 8, barW = Math.min(28, Math.floor((W - PAD * 2) / rows.length) - 2);
		const grandTotal = rows.reduce((a, b) => a + b.total, 0);
		return { rows, maxTotal, W, H, PAD, barW, grandTotal: grandTotal.toFixed(0) };
	});

	const dcaTriggerHourOfDay = $derived.by(() => {
		const counts = Array.from({ length: 24 }, (_, h) => ({ h, count: 0, total: 0 }));
		for (const t of triggers) {
			if (!t.ts) continue;
			const h = new Date(t.ts).getUTCHours();
			counts[h].count++;
			counts[h].total += t.amount_usdt ?? 0;
		}
		if (counts.every(c => c.count === 0)) return null;
		const maxCount = Math.max(...counts.map(c => c.count), 1);
		const W = 520, H = 70, PAD = 6, barW = Math.floor((W - PAD * 2) / 24) - 1;
		return { counts, maxCount, W, H, PAD, barW };
	});

	const dcaFngAmountDotPlot = $derived.by(() => {
		const pts = triggers
			.filter(t => t.fng != null && t.amount_usdt != null && t.amount_usdt > 0)
			.map(t => ({ fng: t.fng as number, amount: t.amount_usdt, kind: t.kind }));
		if (pts.length < 4) return null;
		const W = 380, H = 110, PAD = 20;
		const maxAmt = Math.max(...pts.map(p => p.amount), 1);
		const toX = (v: number) => PAD + (v / 100) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - v / maxAmt) * (H - PAD * 2);
		const color = (kind: string) => kind === 'event' ? 'var(--ch-loss)' : 'var(--ch-violet)';
		return { pts, W, H, PAD, toX, toY, color, maxAmt };
	});

	const dcaFngScoreTimeline = $derived.by(() => {
		const pts = triggers
			.filter(t => t.fng != null && t.ts != null)
			.map(t => ({ ts: new Date(t.ts).getTime(), fng: t.fng as number }))
			.sort((a, b) => a.ts - b.ts);
		if (pts.length < 3) return null;
		const W = 400, H = 100, PAD = 20;
		const minTs = pts[0].ts, maxTs = pts[pts.length - 1].ts;
		const x = (ts: number) => PAD + ((ts - minTs) / (maxTs - minTs || 1)) * (W - PAD * 2);
		const y = (v: number) => PAD + (1 - v / 100) * (H - PAD * 2);
		const polyline = pts.map(p => `${x(p.ts).toFixed(1)},${y(p.fng).toFixed(1)}`).join(' ');
		const zoneColor = (v: number) => v <= 25 ? 'var(--ch-loss-light)' : v <= 45 ? 'rgba(249,115,22,0.10)' : v <= 55 ? 'var(--ch-axis-faint)' : v <= 75 ? 'var(--ch-profit-light)' : 'var(--ch-violet-light)';
		return { pts, W, H, PAD, x, y, polyline, zoneColor };
	});

	const dcaSeverityTimeline = $derived.by(() => {
		const pts = triggers
			.filter(t => t.severity != null && t.ts != null)
			.map(t => ({ ts: new Date(t.ts).getTime(), sev: t.severity as number, kind: t.kind ?? '' }))
			.sort((a, b) => a.ts - b.ts);
		if (pts.length < 3) return null;
		const W = 400, H = 90, PAD = 12;
		const minTs = pts[0].ts, maxTs = pts[pts.length - 1].ts;
		const maxSev = Math.max(...pts.map(p => p.sev), 1);
		const toX = (ts: number) => PAD + ((ts - minTs) / (maxTs - minTs || 1)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - v / maxSev) * (H - PAD * 2);
		const polyline = pts.map(p => `${toX(p.ts).toFixed(1)},${toY(p.sev).toFixed(1)}`).join(' ');
		const kindColor = (k: string) => k === 'FLASH' ? 'var(--ch-loss-strong)' : k === 'CAPITUL' ? 'var(--ch-warn)' : k === 'SUSTAIN' ? 'var(--ch-violet-strong)' : 'var(--ch-axis)';
		return { pts, W, H, PAD, toX, toY, polyline, kindColor, maxSev };
	});

	const dcaInterTriggerGap = $derived.by(() => {
		const ts = triggers
			.filter(t => t.ts != null)
			.map(t => new Date(t.ts).getTime())
			.sort((a, b) => a - b);
		if (ts.length < 4) return null;
		const gaps = ts.slice(1).map((t, i) => (t - ts[i]) / 3600000);
		const maxGap = Math.max(...gaps);
		const BIN_COUNT = 12;
		const binSize = Math.max(1, maxGap / BIN_COUNT);
		const bins: number[] = Array(BIN_COUNT).fill(0);
		for (const g of gaps) {
			const idx = Math.min(BIN_COUNT - 1, Math.floor(g / binSize));
			bins[idx]++;
		}
		const maxBin = Math.max(...bins, 1);
		const W = 400, H = 80, PAD = 10;
		const barW = Math.floor((W - PAD * 2) / BIN_COUNT) - 2;
		const rects = bins.map((cnt, i) => ({
			x: PAD + i * ((W - PAD * 2) / BIN_COUNT),
			h: (cnt / maxBin) * (H - PAD * 2 - 12),
			cnt,
			label: `${(i * binSize).toFixed(0)}h`,
			color: i === 0 ? 'var(--ch-loss)' : i <= 2 ? 'var(--ch-warn)' : 'var(--ch-violet)'
		}));
		return { rects, W, H, PAD, barW, maxBin, binSize: binSize.toFixed(0), total: gaps.length, medGap: gaps.sort((a,b)=>a-b)[Math.floor(gaps.length/2)].toFixed(1) };
	});

	const dcaKindAmountTimeline = $derived.by(() => {
		const pts = triggers
			.filter(t => t.ts != null && t.amount_usdt != null && isFinite(t.amount_usdt))
			.map(t => ({ ts: new Date(t.ts).getTime(), amount: t.amount_usdt as number, kind: t.kind ?? '' }))
			.sort((a, b) => a.ts - b.ts);
		if (pts.length < 3) return null;
		const minTs = pts[0].ts, maxTs = pts[pts.length - 1].ts;
		const maxAmt = Math.max(...pts.map(p => p.amount), 1);
		const W = 400, H = 85, PAD = 12;
		const toX = (ts: number) => PAD + ((ts - minTs) / (maxTs - minTs || 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v / maxAmt) * (H - PAD * 2);
		const kindColor = (k: string) => k === 'SCHEDULED' ? 'var(--ch-violet)' : k === 'EVENT' ? 'var(--ch-loss-strong)' : 'var(--ch-axis)';
		return { pts, W, H, PAD, toX, toY, kindColor, maxAmt: maxAmt.toFixed(0) };
	});

	const dcaAssetAllocationByKind = $derived.by(() => {
		const kinds = ['SCHEDULED', 'EVENT'];
		const map = new Map<string, Map<string, number>>();
		for (const t of triggers) {
			if (!t.asset || !t.kind || t.amount_usdt == null || !isFinite(t.amount_usdt)) continue;
			if (!map.has(t.kind)) map.set(t.kind, new Map());
			const inner = map.get(t.kind)!;
			inner.set(t.asset, (inner.get(t.asset) ?? 0) + t.amount_usdt);
		}
		const usedKinds = kinds.filter(k => map.has(k));
		if (usedKinds.length === 0) return null;
		const allAssets = [...new Set([...map.values()].flatMap(m => [...m.keys()]))].sort();
		if (allAssets.length < 2) return null;
		const rows = allAssets.map(asset => {
			const byKind = usedKinds.map(k => ({ kind: k, amt: map.get(k)?.get(asset) ?? 0 }));
			const total = byKind.reduce((s, e) => s + e.amt, 0);
			return { asset: asset.slice(0, 6), byKind, total };
		}).filter(r => r.total > 0).sort((a, b) => b.total - a.total).slice(0, 8);
		if (rows.length < 2) return null;
		const maxTotal = Math.max(...rows.map(r => r.total), 0.01);
		const colors: Record<string, string> = { SCHEDULED: 'var(--ch-violet)', EVENT: 'var(--ch-loss)' };
		return { rows, usedKinds, maxTotal, colors };
	});

	const dcaMonthlyAssetSpend = $derived.by(() => {
		const assetTotals = new Map<string, number>();
		for (const t of triggers) {
			if (!t.asset || t.amount_usdt == null || !isFinite(t.amount_usdt)) continue;
			assetTotals.set(t.asset, (assetTotals.get(t.asset) ?? 0) + t.amount_usdt);
		}
		const topAssets = [...assetTotals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([a]) => a);
		if (topAssets.length < 2) return null;
		const monthMap = new Map<string, Map<string, number>>();
		for (const t of triggers) {
			if (!t.triggered_at || !t.asset || t.amount_usdt == null || !topAssets.includes(t.asset)) continue;
			const mo = t.triggered_at.slice(0, 7);
			if (!monthMap.has(mo)) monthMap.set(mo, new Map());
			const inner = monthMap.get(mo)!;
			inner.set(t.asset, (inner.get(t.asset) ?? 0) + t.amount_usdt);
		}
		const months = [...monthMap.keys()].sort().slice(-9);
		if (months.length < 2) return null;
		const aColors = ['var(--ch-violet)','var(--ch-profit)','var(--ch-warn)','var(--ch-warn)'];
		const rows = months.map(mo => {
			const inner = monthMap.get(mo)!;
			const segs = topAssets.map((a, i) => ({ asset: a, amt: inner.get(a) ?? 0, color: aColors[i] }));
			const total = segs.reduce((s, e) => s + e.amt, 0);
			return { mo: mo.slice(5), segs, total };
		});
		const maxTotal = Math.max(...rows.map(r => r.total), 0.01);
		const W = 380, H = 72, PAD = 8, barW = Math.max(6, Math.floor((W - PAD * 2) / months.length) - 2);
		const toH = (v: number) => Math.max(0, (v / maxTotal) * (H - PAD * 2));
		return { rows, topAssets, aColors, W, H, PAD, barW, toH, maxTotal: maxTotal.toFixed(0) };
	});

	const dcaTriggerCountByDow = $derived.by(() => {
		const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const counts = Array(7).fill(0) as number[];
		for (const t of triggers) {
			if (!t.triggered_at) continue;
			const dow = new Date(t.triggered_at).getUTCDay();
			counts[dow]++;
		}
		if (counts.every(c => c === 0)) return null;
		const maxCount = Math.max(...counts, 1);
		const rows = days.map((label, i) => ({ label, count: counts[i] }));
		const W = 280, H = 65, PAD = 8, barW = Math.floor((W - PAD * 2) / 7) - 2;
		return { rows, maxCount, W, H, PAD, barW };
	});

	const dcaCumSpendByAsset = $derived.by(() => {
		const assetTotals = new Map<string, number>();
		for (const t of triggers) {
			if (!t.asset || t.amount_usdt == null || !isFinite(t.amount_usdt)) continue;
			assetTotals.set(t.asset, (assetTotals.get(t.asset) ?? 0) + t.amount_usdt);
		}
		const topAssets = [...assetTotals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([a]) => a);
		if (topAssets.length < 2) return null;
		const sorted = [...triggers]
			.filter(t => t.triggered_at && t.asset && topAssets.includes(t.asset) && t.amount_usdt != null && isFinite(t.amount_usdt))
			.sort((a, b) => a.triggered_at!.localeCompare(b.triggered_at!));
		if (sorted.length < 5) return null;
		const cumMap = new Map<string, number>(topAssets.map(a => [a, 0]));
		const events: { i: number; asset: string; cum: number }[] = [];
		sorted.forEach((t, i) => {
			cumMap.set(t.asset!, (cumMap.get(t.asset!) ?? 0) + t.amount_usdt!);
			events.push({ i, asset: t.asset!, cum: cumMap.get(t.asset!)! });
		});
		const maxCum = Math.max(...[...cumMap.values()], 0.01);
		const aColors = ['var(--ch-violet-strong)', 'var(--ch-profit-strong)', 'var(--ch-warn)', 'var(--ch-warn)'];
		const W = 380, H = 85, PAD = 10;
		const toX = (i: number) => PAD + (i / Math.max(sorted.length - 1, 1)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - v / maxCum) * (H - PAD * 2);
		const lines = topAssets.map((asset, ai) => {
			const pts = events.filter(e => e.asset === asset);
			const poly = pts.map(p => `${toX(p.i).toFixed(1)},${toY(p.cum).toFixed(1)}`).join(' ');
			return { asset, color: aColors[ai], poly, final: cumMap.get(asset)!.toFixed(0) };
		}).filter(l => l.poly.length > 0);
		return { lines, W, H, PAD, maxCum: maxCum.toFixed(0) };
	});

	const dcaAvgAmountByKindTrend = $derived.by(() => {
		const kindMonths = new Map<string, Map<string, number[]>>();
		for (const t of triggers) {
			if (!t.kind || !t.triggered_at || t.amount_usdt == null || !isFinite(t.amount_usdt)) continue;
			const mo = t.triggered_at.slice(0, 7);
			if (!kindMonths.has(t.kind)) kindMonths.set(t.kind, new Map());
			if (!kindMonths.get(t.kind)!.has(mo)) kindMonths.get(t.kind)!.set(mo, []);
			kindMonths.get(t.kind)!.get(mo)!.push(t.amount_usdt);
		}
		const allMonths = [...new Set([...kindMonths.values()].flatMap(m => [...m.keys()]))].sort();
		if (allMonths.length < 3 || kindMonths.size < 2) return null;
		const kinds = [...kindMonths.keys()].slice(0, 4);
		const kColors = ['var(--ch-violet-strong)', 'var(--ch-profit-strong)', 'var(--ch-warn)', 'var(--ch-warn)'];
		const W = 360, H = 80, PAD = 10;
		const toX = (i: number) => PAD + (i / Math.max(allMonths.length - 1, 1)) * (W - PAD * 2);
		const lines = kinds.map((kind, ki) => {
			const pts = allMonths.map((mo, i) => {
				const vals = kindMonths.get(kind)?.get(mo) ?? [];
				return vals.length ? { i, avg: vals.reduce((a, v) => a + v, 0) / vals.length } : null;
			}).filter(Boolean) as { i: number; avg: number }[];
			return { kind, color: kColors[ki], pts };
		}).filter(l => l.pts.length >= 2);
		if (lines.length < 2) return null;
		const maxAvg = Math.max(...lines.flatMap(l => l.pts.map(p => p.avg)), 0.01);
		const toY = (v: number) => PAD + (1 - v / maxAvg) * (H - PAD * 2);
		const polylines = lines.map(l => ({ ...l, poly: l.pts.map(p => `${toX(p.i).toFixed(1)},${toY(p.avg).toFixed(1)}`).join(' ') }));
		return { polylines, allMonths, W, H, PAD, maxAvg: maxAvg.toFixed(0) };
	});

	const dcaTriggerHourDistribution = $derived.by(() => {
		const buckets = Array.from({ length: 24 }, (_, h) => ({ h, count: 0 }));
		for (const t of triggers) {
			if (!t.triggered_at) continue;
			const h = new Date(t.triggered_at).getUTCHours();
			if (h >= 0 && h < 24) buckets[h].count++;
		}
		const active = buckets.filter(b => b.count > 0);
		if (active.length < 4) return null;
		const maxCount = Math.max(...buckets.map(b => b.count), 1);
		const W = 360, H = 60, PAD = 6, barW = Math.max(2, Math.floor((W - PAD * 2) / 24) - 1);
		return { buckets, maxCount, W, H, PAD, barW };
	});

	const dcaAvgFngByMonth = $derived.by(() => {
		const map = new Map<string, { sum: number; count: number }>();
		for (const e of data.triggers) {
			if (!e.triggered_at || e.fng_value == null || !isFinite(e.fng_value)) continue;
			const mo = e.triggered_at.slice(0, 7);
			const cur = map.get(mo) ?? { sum: 0, count: 0 };
			cur.sum += e.fng_value;
			cur.count++;
			map.set(mo, cur);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const avgs = months.map(m => { const d = map.get(m)!; return { mo: m, avg: d.sum / d.count }; });
		const mn = Math.min(...avgs.map(a => a.avg)), mx = Math.max(...avgs.map(a => a.avg), mn + 1);
		const W = 360, H = 72, PAD = 10;
		const toX = (i: number) => PAD + (i / Math.max(avgs.length - 1, 1)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - (v - mn) / (mx - mn)) * (H - PAD * 2);
		const pts = avgs.map((a, i) => `${toX(i).toFixed(1)},${toY(a.avg).toFixed(1)}`).join(' ');
		const fearY = toY(25), greedY = toY(75);
		return { pts, avgs, W, H, PAD, mn: mn.toFixed(0), mx: mx.toFixed(0), fearY, greedY, count: avgs.length };
	});

	const dcaAmountBoxByKind = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const e of data.triggers) {
			if (!e.kind || e.amount_usdt == null || !isFinite(e.amount_usdt) || e.amount_usdt <= 0) continue;
			const arr = map.get(e.kind) ?? [];
			arr.push(e.amount_usdt);
			map.set(e.kind, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()].map(([kind, amounts]) => {
			const sorted = [...amounts].sort((a, b) => a - b);
			const n = sorted.length;
			const q1 = sorted[Math.floor(n / 4)];
			const median = n % 2 ? sorted[Math.floor(n / 2)] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
			const q3 = sorted[Math.floor((n * 3) / 4)];
			return { kind, q1, median, q3, count: n };
		}).sort((a, b) => b.median - a.median);
		const allVals = rows.flatMap(r => [r.q1, r.q3]);
		const mn = 0, mx = Math.max(...allVals, 1);
		const W = 320, H = rows.length * 22 + 10, PAD = 8, barMaxW = W - 90;
		const toX = (v: number) => PAD + (v / mx) * barMaxW;
		const items = rows.map(r => ({ ...r, q1X: toX(r.q1), medX: toX(r.median), q3X: toX(r.q3) }));
		return { items, W, H, PAD, barMaxW, mx: mx.toFixed(0) };
	});

	const dcaMonthlyTriggerCount = $derived.by(() => {
		const map = new Map<string, number>();
		for (const e of data.triggers) {
			if (!e.triggered_at) continue;
			const mo = e.triggered_at.slice(0, 7);
			map.set(mo, (map.get(mo) ?? 0) + 1);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const pts = months.map(m => ({ mo: m.slice(5), count: map.get(m)! }));
		const maxC = Math.max(...pts.map(p => p.count), 1);
		const W = 360, H = 72, PAD = 10;
		const toX = (i: number) => PAD + (i / Math.max(pts.length - 1, 1)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - v / maxC) * (H - PAD * 2);
		const poly = pts.map((p, i) => `${toX(i).toFixed(1)},${toY(p.count).toFixed(1)}`).join(' ');
		const area = poly + ` ${toX(pts.length - 1).toFixed(1)},${H - PAD} ${toX(0).toFixed(1)},${H - PAD}`;
		const dots = pts.map((p, i) => ({ x: toX(i), y: toY(p.count), count: p.count, mo: p.mo }));
		return { pts, poly, area, dots, W, H, PAD, maxC, total: pts.reduce((a, p) => a + p.count, 0) };
	});

	const dcaAssetBuyFrequency = $derived.by(() => {
		const map = new Map<string, number>();
		for (const e of data.triggers) {
			if (!e.asset) continue;
			map.set(e.asset, (map.get(e.asset) ?? 0) + 1);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()].map(([asset, count]) => ({ asset: asset.slice(0, 10), count }))
			.sort((a, b) => b.count - a.count).slice(0, 8);
		const maxC = Math.max(...rows.map(r => r.count), 1);
		const W = 340, H = rows.length * 16 + 6, PAD = 8, barMaxW = W - 80;
		return { rows, maxC, W, H, PAD, barMaxW, total: rows.reduce((a, r) => a + r.count, 0) };
	});

	const dcaAmountByDow = $derived.by(() => {
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const map = new Map<number, number[]>();
		for (const e of data.triggers) {
			if (!e.triggered_at || e.amount == null || !isFinite(e.amount) || e.amount <= 0) continue;
			const dow = new Date(e.triggered_at).getDay();
			const arr = map.get(dow) ?? [];
			arr.push(e.amount);
			map.set(dow, arr);
		}
		if (map.size < 3) return null;
		const rows = [0, 1, 2, 3, 4, 5, 6].filter(d => map.has(d)).map(d => ({
			day: DAYS[d], avg: map.get(d)!.reduce((a, v) => a + v, 0) / map.get(d)!.length, count: map.get(d)!.length,
		}));
		if (rows.length < 3) return null;
		const maxVal = Math.max(...rows.map(r => r.avg), 0.01);
		const W = 340, H = 72, PAD = 10;
		const bw = Math.max(4, Math.floor((W - PAD * 2) / rows.length) - 4);
		const bars = rows.map((r, i) => ({
			x: PAD + i * ((W - PAD * 2) / rows.length) + 2,
			h: Math.max(3, (r.avg / maxVal) * (H - PAD * 2 - 14)),
			avg: r.avg, day: r.day, count: r.count,
		}));
		return { bars, bw, W, H, PAD };
	});

	const dcaCumSpendTimeline = $derived.by(() => {
		const sorted = data.triggers
			.filter(e => e.triggered_at && e.amount != null && isFinite(e.amount) && e.amount > 0)
			.sort((a, b) => a.triggered_at!.localeCompare(b.triggered_at!));
		if (sorted.length < 5) return null;
		let cum = 0;
		const pts = sorted.map((e, i) => { cum += e.amount!; return { i, cum, date: e.triggered_at!.slice(0, 10) }; });
		const maxCum = pts[pts.length - 1].cum;
		const W = 360, H = 68, PAD = 10;
		const toX = (i: number) => PAD + (i / Math.max(pts.length - 1, 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v / maxCum) * (H - PAD * 2);
		const polyline = pts.map(p => `${toX(p.i).toFixed(1)},${toY(p.cum).toFixed(1)}`).join(' ');
		const area = `${toX(0).toFixed(1)},${H - PAD} ` + polyline + ` ${toX(pts.length - 1).toFixed(1)},${H - PAD}`;
		return { pts, polyline, area, W, H, PAD, maxCum, toX, firstDate: pts[0].date, lastDate: pts[pts.length - 1].date };
	});

	const dcaMonthlyAvgAmount = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const e of data.triggers) {
			if (!e.triggered_at || e.amount == null || !isFinite(e.amount) || e.amount <= 0) continue;
			const mo = e.triggered_at.slice(0, 7);
			const arr = map.get(mo) ?? [];
			arr.push(e.amount);
			map.set(mo, arr);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const rows = months.map(m => {
			const vals = map.get(m)!;
			return { mo: m.slice(5), avg: vals.reduce((a, v) => a + v, 0) / vals.length, count: vals.length };
		});
		const maxAvg = Math.max(...rows.map(r => r.avg), 0.01);
		const W = 360, H = 68, PAD = 10;
		const bw = Math.max(3, (W - PAD * 2) / rows.length - 2);
		const bars = rows.map((r, i) => ({
			x: PAD + i * ((W - PAD * 2) / rows.length),
			h: Math.max(2, (r.avg / maxAvg) * (H - PAD * 2 - 14)),
			mo: r.mo, avg: r.avg, count: r.count,
		}));
		return { bars, bw, W, H, PAD, maxAvg };
	});

	const dcaTotalSpendByAsset = $derived.by(() => {
		const map = new Map<string, number>();
		for (const e of data.triggers) {
			if (!e.asset || e.amount == null || !isFinite(e.amount) || e.amount <= 0) continue;
			map.set(e.asset, (map.get(e.asset) ?? 0) + e.amount);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([asset, total]) => ({ asset: asset.slice(0, 10), total }))
			.sort((a, b) => b.total - a.total).slice(0, 12);
		const maxTotal = Math.max(...rows.map(r => r.total), 0.01);
		const W = 340, H = rows.length * 16 + 6, PAD = 8, barMaxW = W - 90;
		return { rows, maxTotal, W, H, PAD, barMaxW };
	});

	const dcaOrderCountByMonth = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 4) return null;
		const map = new Map<string, number>();
		for (const e of dcaEvents) {
			if (!e.timestamp) continue;
			const mo = (e.timestamp as string).slice(0, 7);
			map.set(mo, (map.get(mo) ?? 0) + 1);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const counts = months.map(m => map.get(m) ?? 0);
		const maxCount = Math.max(...counts, 1);
		const W = 380, H = 70, PAD = 10;
		const bw = Math.max(2, (W - PAD * 2) / months.length - 2);
		const toX = (i: number) => PAD + i * ((W - PAD * 2) / months.length);
		const toH = (v: number) => (v / maxCount) * (H - PAD * 2 - 12);
		return { months, counts, W, H, PAD, bw, toX, toH, maxCount };
	});

	const dcaAvgAmountByDow = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 7) return null;
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const map = new Map<number, { sum: number; count: number }>();
		for (const e of dcaEvents) {
			if (!e.timestamp || e.amount == null) continue;
			const dow = new Date(e.timestamp as string).getUTCDay();
			const s = map.get(dow) ?? { sum: 0, count: 0 };
			s.sum += e.amount as number;
			s.count++;
			map.set(dow, s);
		}
		if (map.size < 3) return null;
		const rows = DAYS.map((day, d) => {
			const s = map.get(d);
			return { day, avg: s ? s.sum / s.count : 0, count: s?.count ?? 0 };
		});
		const maxAvg = Math.max(...rows.map(r => r.avg), 0.01);
		const W = 300, H = 72, PAD = 10;
		const bw = (W - PAD * 2) / 7 - 2;
		const toH = (v: number) => (v / maxAvg) * (H - PAD * 2 - 12);
		return { rows, W, H, PAD, bw, toH, maxAvg: maxAvg.toFixed(0) };
	});

	const dcaCumSpendByAssetTimeline = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 5) return null;
		const assets = [...new Set(dcaEvents.filter(e => e.asset).map(e => e.asset as string))].slice(0, 4);
		if (assets.length < 2) return null;
		const sorted = [...dcaEvents].filter(e => e.timestamp && e.amount).sort((a, b) => new Date(a.timestamp as string).getTime() - new Date(b.timestamp as string).getTime());
		const cumMap = new Map(assets.map(a => [a, 0]));
		const timeline = sorted.map(e => {
			const a = e.asset as string;
			if (assets.includes(a)) cumMap.set(a, (cumMap.get(a) ?? 0) + (e.amount as number));
			return { t: e.timestamp as string, snap: new Map(cumMap) };
		});
		const maxCum = Math.max(...assets.flatMap(a => timeline.map(t => t.snap.get(a) ?? 0)), 0.01);
		const COLORS = ['var(--ch-teal)', 'var(--ch-profit-strong)', 'var(--ch-warn)', 'var(--ch-violet-strong)'];
		const W = 380, H = 90, PAD = 10;
		const toX = (i: number) => PAD + (i / (timeline.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v / maxCum) * (H - PAD * 2);
		const lines = assets.map((a, ai) => ({
			name: a.slice(0, 6), color: COLORS[ai],
			polyline: timeline.map((t, i) => `${toX(i)},${toY(t.snap.get(a) ?? 0)}`).join(' '),
		}));
		return { lines, W, H, PAD, maxCum: maxCum.toFixed(0) };
	});

	const dcaAvgOrdersByAsset = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 5) return null;
		const map = new Map<string, { count: number; total: number }>();
		for (const e of dcaEvents) {
			if (!e.asset || e.amount == null) continue;
			const s = map.get(e.asset as string) ?? { count: 0, total: 0 };
			s.count++;
			s.total += e.amount as number;
			map.set(e.asset as string, s);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([asset, s]) => ({ asset: asset.slice(0, 8), count: s.count, avg: s.total / s.count }))
			.sort((a, b) => b.count - a.count)
			.slice(0, 10);
		const maxCount = Math.max(...rows.map(r => r.count), 1);
		const maxAvg = Math.max(...rows.map(r => r.avg), 0.01);
		const W = 340, H = rows.length * 17 + 6, PAD = 8, barW = W - 100;
		return { rows, maxCount, maxAvg, W, H, PAD, barW };
	});

	const dcaAmountHistogram = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 10) return null;
		const amounts = dcaEvents.filter(e => e.amount != null).map(e => e.amount as number);
		if (amounts.length < 8) return null;
		const maxA = Math.max(...amounts);
		const bins = 12;
		const bucketSize = maxA / bins;
		const counts = new Array(bins).fill(0);
		for (const a of amounts) {
			const b = Math.min(Math.floor(a / bucketSize), bins - 1);
			counts[b]++;
		}
		const maxCount = Math.max(...counts, 1);
		const W = 300, H = 68, PAD = 8;
		const barW = (W - PAD * 2) / bins;
		return { counts, maxCount, W, H, PAD, barW, bins, maxA: maxA.toFixed(0), bucketSize: bucketSize.toFixed(0) };
	});

	const dcaWeeklySpendTrend = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 10) return null;
		const map = new Map<string, number>();
		for (const e of dcaEvents) {
			if (!e.triggered_at || e.amount == null) continue;
			const d = new Date(e.triggered_at as string);
			const yr = d.getUTCFullYear();
			const wk = Math.ceil(((d.getTime() - new Date(yr, 0, 1).getTime()) / 86400000 + new Date(yr, 0, 1).getUTCDay() + 1) / 7);
			const key = `${yr}-W${String(wk).padStart(2, '0')}`;
			map.set(key, (map.get(key) ?? 0) + (e.amount as number));
		}
		if (map.size < 4) return null;
		const weeks = [...map.keys()].sort();
		const pts = weeks.map(w => ({ w: w.slice(5), total: map.get(w)! }));
		const maxV = Math.max(...pts.map(p => p.total), 0.01);
		const W = 360, H = 68, PAD = 10;
		const toX = (i: number) => PAD + (i / (pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v / maxV) * (H - PAD * 2);
		const polyline = pts.map((p, i) => `${toX(i)},${toY(p.total)}`).join(' ');
		const area = `${toX(0)},${H - PAD} ${polyline} ${toX(pts.length - 1)},${H - PAD}`;
		return { pts, polyline, area, W, H, PAD, toX, maxV: maxV.toFixed(0), firstW: pts[0].w, lastW: pts[pts.length - 1].w };
	});

	const dcaSpendByHour = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 10) return null;
		const counts = new Array(24).fill(0);
		const sums = new Array(24).fill(0);
		for (const e of dcaEvents) {
			if (!e.triggered_at || e.amount == null) continue;
			const h = new Date(e.triggered_at as string).getUTCHours();
			counts[h]++;
			sums[h] += e.amount as number;
		}
		const maxSum = Math.max(...sums, 0.01);
		const W = 340, H = 56, PAD = 6;
		const barW = (W - PAD * 2) / 24;
		return { sums, maxSum, W, H, PAD, barW };
	});

	const dcaMonthlyOrderCount = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 10) return null;
		const map = new Map<string, number>();
		for (const e of dcaEvents) {
			if (!e.triggered_at) continue;
			const mo = (e.triggered_at as string).slice(0, 7);
			map.set(mo, (map.get(mo) ?? 0) + 1);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const pts = months.map(m => ({ m: m.slice(5), count: map.get(m)! }));
		const maxCount = Math.max(...pts.map(p => p.count), 1);
		const W = 340, H = 60, PAD = 8;
		const bw = (W - PAD * 2) / pts.length - 1;
		return { pts, maxCount, W, H, PAD, bw };
	});

	const dcaAvgAmountByMonth = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 10) return null;
		const map = new Map<string, number[]>();
		for (const e of dcaEvents) {
			if (!e.triggered_at || e.amount == null) continue;
			const mo = (e.triggered_at as string).slice(0, 7);
			const arr = map.get(mo) ?? [];
			arr.push(e.amount as number);
			map.set(mo, arr);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const pts = months.map(m => { const arr = map.get(m)!; return { m: m.slice(5), avg: arr.reduce((a, v) => a + v, 0) / arr.length }; });
		const maxAvg = Math.max(...pts.map(p => p.avg), 0.01);
		const W = 340, H = 60, PAD = 8;
		const bw = (W - PAD * 2) / pts.length - 1;
		return { pts, maxAvg, W, H, PAD, bw };
	});

	const dcaSpendByDow = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 14) return null;
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const sums = new Array(7).fill(0);
		const counts = new Array(7).fill(0);
		for (const e of dcaEvents) {
			if (!e.triggered_at || e.amount == null) continue;
			const dow = new Date(e.triggered_at as string).getDay();
			sums[dow] += e.amount as number;
			counts[dow]++;
		}
		const pts = DAYS.map((d, i) => ({ d, avg: counts[i] ? sums[i] / counts[i] : 0 }));
		const maxAvg = Math.max(...pts.map(p => p.avg), 0.01);
		const W = 340, H = 64, PAD = 8;
		const bw = (W - PAD * 2) / 7 - 2;
		return { pts, maxAvg, W, H, PAD, bw };
	});

	const dcaCumAmountCDF = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 15) return null;
		const vals = dcaEvents
			.filter(e => e.amount != null)
			.map(e => e.amount as number)
			.sort((a, b) => a - b);
		if (vals.length < 15) return null;
		const minV = vals[0], maxV = vals[vals.length - 1];
		const range = maxV - minV || 0.01;
		const W = 340, H = 80, PAD = 10;
		const toX = (v: number) => PAD + ((v - minV) / range) * (W - PAD * 2);
		const toY = (i: number) => H - PAD - (i / (vals.length - 1)) * (H - PAD * 2);
		const polyline = vals.map((v, i) => `${toX(v)},${toY(i)}`).join(' ');
		const median = vals[Math.floor(vals.length * 0.5)];
		const p80 = vals[Math.floor(vals.length * 0.8)];
		return { polyline, W, H, PAD, minV: minV.toFixed(0), maxV: maxV.toFixed(0), median: median.toFixed(0), p80: p80.toFixed(0) };
	});

	const dcaAmountByKindMonth = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 10) return null;
		const kinds = [...new Set(dcaEvents.filter(e => e.kind).map(e => e.kind as string))].slice(0, 4);
		if (kinds.length < 2) return null;
		const months = [...new Set(dcaEvents.filter(e => e.triggered_at).map(e => (e.triggered_at as string).slice(0, 7)))].sort().slice(-6);
		if (months.length < 2) return null;
		const map = new Map<string, number>();
		for (const e of dcaEvents) {
			if (!e.triggered_at || !e.kind || e.amount == null) continue;
			const mo = (e.triggered_at as string).slice(0, 7);
			if (!months.includes(mo)) continue;
			const key = `${e.kind}|${mo}`;
			map.set(key, (map.get(key) ?? 0) + (e.amount as number));
		}
		const maxVal = Math.max(...kinds.flatMap(k => months.map(m => map.get(`${k}|${m}`) ?? 0)), 0.01);
		const COLORS = ['var(--ch-violet-strong)', 'var(--ch-violet)', 'var(--ch-teal)', 'var(--ch-warn)'];
		const cellW = 32, cellH = 18, PAD = 4;
		const W = PAD + (months.length + 1) * cellW, H = PAD + (kinds.length + 1) * cellH;
		const cells = kinds.flatMap((k, ki) => months.map((mo, mi) => {
			const val = map.get(`${k}|${mo}`) ?? 0;
			return { x: PAD + (mi + 1) * cellW, y: PAD + (ki + 1) * cellH, val, color: COLORS[ki], k, mo };
		}));
		return { cells, kinds, months, cellW, cellH, PAD, W, H, maxVal };
	});

	const dcaOrderGapDays = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 5) return null;
		const sorted = dcaEvents
			.filter(e => e.triggered_at)
			.map(e => new Date(e.triggered_at as string).getTime())
			.sort((a, b) => a - b);
		if (sorted.length < 5) return null;
		const gaps = sorted.slice(1).map((t, i) => (t - sorted[i]) / 86400000);
		const maxGap = Math.min(Math.max(...gaps), 60);
		const BINS = 12;
		const step = maxGap / BINS;
		const counts = Array(BINS).fill(0);
		for (const g of gaps) { const bi = Math.min(Math.floor(g / step), BINS - 1); counts[bi]++; }
		const maxCount = Math.max(...counts, 1);
		const W = 300, H = 60, PAD = 8;
		const bw = (W - PAD * 2) / BINS - 1;
		return { counts, maxCount, step, BINS, W, H, PAD, bw, maxGap: maxGap.toFixed(0) };
	});

	const dcaAssetShareByMonth = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 10) return null;
		const assetKey = (e: any) => (e.coin as string | undefined) ?? (e.asset as string | undefined) ?? (e.pair as string | undefined);
		const assets = [...new Set(dcaEvents.map(assetKey).filter(Boolean))].slice(0, 4) as string[];
		if (assets.length < 2) return null;
		const months = [...new Set(dcaEvents.filter(e => e.triggered_at).map(e => (e.triggered_at as string).slice(0, 7)))].sort().slice(-6);
		if (months.length < 2) return null;
		const map = new Map<string, number>();
		for (const e of dcaEvents) {
			if (!e.triggered_at || e.amount == null) continue;
			const mo = (e.triggered_at as string).slice(0, 7);
			if (!months.includes(mo)) continue;
			const asset = assetKey(e);
			if (!asset || !assets.includes(asset)) continue;
			map.set(`${asset}|${mo}`, (map.get(`${asset}|${mo}`) ?? 0) + (e.amount as number));
		}
		const COLORS = ['var(--ch-violet-strong)', 'var(--ch-violet)', 'var(--ch-teal)', 'var(--ch-warn)'];
		const cellW = 32, cellH = 18, PAD = 4;
		const W = PAD + (months.length + 1) * cellW, H = PAD + (assets.length + 1) * cellH;
		const maxVal = Math.max(...assets.flatMap(a => months.map(m => map.get(`${a}|${m}`) ?? 0)), 0.01);
		const cells = assets.flatMap((a, ai) => months.map((mo, mi) => ({
			x: PAD + (mi + 1) * cellW, y: PAD + (ai + 1) * cellH,
			val: map.get(`${a}|${mo}`) ?? 0, color: COLORS[ai], a, mo
		})));
		return { cells, assets, months, cellW, cellH, PAD, W, H, maxVal };
	});

	const dcaOrderCountByAsset = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 5) return null;
		const assetKey = (e: any) => (e.coin as string | undefined) ?? (e.asset as string | undefined) ?? (e.pair as string | undefined);
		const map = new Map<string, number>();
		for (const e of dcaEvents) {
			const a = assetKey(e);
			if (!a) continue;
			map.set(a, (map.get(a) ?? 0) + 1);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([asset, count]) => ({ asset: asset.slice(0, 10), count }));
		const maxCount = Math.max(...rows.map(r => r.count), 1);
		const W = 300, H = rows.length * 18 + 10, PAD = 8, barMaxW = W - PAD * 2 - 60;
		return { rows, maxCount, W, H, PAD, barMaxW };
	});

	const dcaCumSpendAssetLines = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 5) return null;
		const assetKey = (e: any) => (e.coin as string | undefined) ?? (e.asset as string | undefined) ?? (e.pair as string | undefined);
		const assets = [...new Set(dcaEvents.map(assetKey).filter(Boolean))].slice(0, 4) as string[];
		if (assets.length < 2) return null;
		const sorted = [...dcaEvents].filter(e => e.triggered_at && e.amount != null).sort((a, b) =>
			new Date(a.triggered_at as string).getTime() - new Date(b.triggered_at as string).getTime()
		);
		const lines = assets.map(a => {
			let cum = 0;
			return sorted.map(e => {
				if (assetKey(e) === a) cum += e.amount as number;
				return cum;
			});
		});
		const maxCum = Math.max(...lines.flat(), 1);
		const W = 300, H = 70, PAD = 8;
		const COLORS = ['var(--ch-violet-strong)', 'var(--ch-violet-strong)', 'var(--ch-teal-strong)', 'var(--ch-warn)'];
		const polylines = lines.map((vals, ai) =>
			vals.map((v, i) => {
				const x = PAD + (i / Math.max(vals.length - 1, 1)) * (W - PAD * 2);
				const y = PAD + (1 - v / maxCum) * (H - PAD * 2);
				return `${x.toFixed(1)},${y.toFixed(1)}`;
			}).join(' ')
		);
		return { assets, polylines, COLORS, maxCum: maxCum.toFixed(0), W, H, PAD };
	});

	const dcaSpendByQuarter = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 5) return null;
		const map = new Map<string, number>();
		for (const e of dcaEvents) {
			if (!e.triggered_at || e.amount == null) continue;
			const d = new Date(e.triggered_at as string);
			const q = `${d.getFullYear()}-Q${Math.floor(d.getMonth() / 3) + 1}`;
			map.set(q, (map.get(q) ?? 0) + (e.amount as number));
		}
		if (map.size < 2) return null;
		const pts = [...map.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([q, total]) => ({ q: q.slice(2), total }));
		const maxTotal = Math.max(...pts.map(p => p.total), 1);
		const W = 300, H = 64, PAD = 8;
		const bw = (W - PAD * 2) / pts.length - 1;
		return { pts, maxTotal, bw, W, H, PAD };
	});

	const dcaAmountByAssetCDF = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 10) return null;
		const assetKey = (e: any) => (e.coin as string | undefined) ?? (e.asset as string | undefined) ?? (e.pair as string | undefined);
		const vals = dcaEvents.filter(e => e.amount != null && assetKey(e)).map(e => e.amount as number).sort((a, b) => a - b);
		if (vals.length < 8) return null;
		const minV = vals[0], maxV = vals[vals.length - 1];
		if (maxV === minV) return null;
		const W = 300, H = 70, PAD = 10;
		const toX = (v: number) => PAD + ((v - minV) / (maxV - minV)) * (W - PAD * 2);
		const toY = (i: number) => H - PAD - (i / (vals.length - 1)) * (H - PAD * 2);
		const polyline = vals.map((v, i) => `${toX(v).toFixed(1)},${toY(i).toFixed(1)}`).join(' ');
		const median = vals[Math.floor(vals.length / 2)].toFixed(0);
		return { polyline, W, H, PAD, minV: minV.toFixed(0), maxV: maxV.toFixed(0), median };
	});

	const dcaAvgAmountTrend = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 8) return null;
		const byMonth = new Map<string, number[]>();
		for (const e of dcaEvents) {
			if (!e.triggered_at || e.amount == null) continue;
			const mo = (e.triggered_at as string).slice(0, 7);
			const arr = byMonth.get(mo) ?? [];
			arr.push(e.amount as number);
			byMonth.set(mo, arr);
		}
		if (byMonth.size < 3) return null;
		const pts = [...byMonth.entries()]
			.sort(([a], [b]) => a.localeCompare(b))
			.map(([mo, arr]) => ({ mo: mo.slice(5), avg: arr.reduce((s, v) => s + v, 0) / arr.length }));
		const maxAvg = Math.max(...pts.map(p => p.avg), 1);
		const W = 300, H = 60, PAD = 10;
		const toX = (i: number) => PAD + (i / Math.max(pts.length - 1, 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v / maxAvg) * (H - PAD * 2);
		const polyline = pts.map((p, i) => `${toX(i).toFixed(1)},${toY(p.avg).toFixed(1)}`).join(' ');
		return { pts, polyline, toX, W, H, PAD, maxAvg: maxAvg.toFixed(0) };
	});

	const dcaOrdersByDow = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 7) return null;
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const counts = Array(7).fill(0);
		for (const e of dcaEvents) {
			if (!e.triggered_at) continue;
			counts[new Date(e.triggered_at as string).getDay()]++;
		}
		const maxCount = Math.max(...counts, 1);
		const W = 260, H = 60, PAD = 8;
		const bw = (W - PAD * 2) / 7 - 1;
		return { counts, DAYS, maxCount, bw, W, H, PAD };
	});

	const dcaSpendByHourOfDay = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 12) return null;
		const counts = Array(24).fill(0);
		const amounts = Array(24).fill(0);
		for (const e of dcaEvents) {
			if (!e.triggered_at || e.amount == null) continue;
			const h = new Date(e.triggered_at as string).getHours();
			counts[h]++;
			amounts[h] += e.amount as number;
		}
		const maxAmount = Math.max(...amounts, 1);
		const W = 300, H = 60, PAD = 8;
		const bw = Math.max(1, (W - PAD * 2) / 24 - 0.5);
		return { amounts, maxAmount, bw, W, H, PAD };
	});

	const dcaAvgAmountByWeekday = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 7) return null;
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const sums = Array(7).fill(0);
		const cnts = Array(7).fill(0);
		for (const e of dcaEvents) {
			if (!e.triggered_at || e.amount == null) continue;
			const d = new Date(e.triggered_at as string).getDay();
			sums[d] += e.amount as number;
			cnts[d]++;
		}
		const avgs = sums.map((s, i) => cnts[i] ? s / cnts[i] : 0);
		const maxAvg = Math.max(...avgs, 1);
		const W = 260, H = 65, PAD = 8;
		const bw = (W - PAD * 2) / 7 - 1;
		return { avgs, DAYS, maxAvg, bw, W, H, PAD };
	});

	const dcaMonthlySpendTrend = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 5) return null;
		const byMonth = new Map<string, number>();
		for (const e of dcaEvents) {
			if (!e.triggered_at || e.amount == null) continue;
			const mo = (e.triggered_at as string).slice(0, 7);
			byMonth.set(mo, (byMonth.get(mo) ?? 0) + (e.amount as number));
		}
		if (byMonth.size < 3) return null;
		const pts = [...byMonth.entries()]
			.sort(([a], [b]) => a.localeCompare(b))
			.map(([mo, total]) => ({ mo: mo.slice(5), total }));
		const maxTotal = Math.max(...pts.map(p => p.total), 1);
		const W = 280, H = 70, PAD = 10;
		const toX = (i: number) => PAD + (i / Math.max(pts.length - 1, 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v / maxTotal) * (H - PAD * 2);
		const polyline = pts.map((p, i) => `${toX(i).toFixed(1)},${toY(p.total).toFixed(1)}`).join(' ');
		return { pts, polyline, toX, maxTotal, W, H, PAD };
	});

	const dcaAmountCumulativeByAsset = $derived.by(() => {
		if (!dcaEvents || dcaEvents.length < 5) return null;
		const map = new Map<string, number>();
		for (const e of dcaEvents) {
			if (!e.asset || e.amount == null) continue;
			map.set(e.asset as string, (map.get(e.asset as string) ?? 0) + (e.amount as number));
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([asset, total]) => ({ asset: (asset as string).slice(0, 12), total }))
			.sort((a, b) => b.total - a.total)
			.slice(0, 8);
		const maxTotal = Math.max(...rows.map(r => r.total), 1);
		const W = 280, H = rows.length * 20 + 8, PAD = 8, barMaxW = W - PAD * 2 - 60;
		return { rows, maxTotal, W, H, PAD, barMaxW };
	});

	const dcaSpendByWeekday = $derived.by(() => {
		if (!orders || orders.length < 5) return null;
		const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const byDow = new Map<number, number[]>();
		for (const o of orders) {
			if (!o.created_at || o.amount == null) continue;
			const d = new Date(o.created_at as string).getUTCDay();
			const arr = byDow.get(d) ?? [];
			arr.push(o.amount as number);
			byDow.set(d, arr);
		}
		const bars = [0, 1, 2, 3, 4, 5, 6]
			.filter(d => byDow.has(d))
			.map(d => ({ label: DOW[d], avg: (byDow.get(d) ?? []).reduce((s, v) => s + v, 0) / (byDow.get(d)?.length ?? 1), n: byDow.get(d)?.length ?? 0 }));
		if (bars.length < 3) return null;
		const maxAvg = Math.max(...bars.map(b => b.avg), 1);
		const W = 280, H = 65, PAD = 8;
		const bw = Math.max(8, (W - PAD * 2) / bars.length - 2);
		return { bars, maxAvg, W, H, PAD, bw };
	});

	const dcaInterOrderGapCDF = $derived.by(() => {
		if (!orders || orders.length < 10) return null;
		const sorted = [...orders]
			.filter(o => o.created_at != null)
			.sort((a, b) => new Date(a.created_at as string).getTime() - new Date(b.created_at as string).getTime());
		if (sorted.length < 10) return null;
		const gaps: number[] = [];
		for (let i = 1; i < sorted.length; i++) {
			const diff = (new Date(sorted[i].created_at as string).getTime() - new Date(sorted[i - 1].created_at as string).getTime()) / 86400000;
			if (diff > 0 && diff < 90) gaps.push(diff);
		}
		if (gaps.length < 8) return null;
		gaps.sort((a, b) => a - b);
		const W = 280, H = 65, PAD = 8;
		const minV = gaps[0], maxV = gaps[gaps.length - 1];
		const toX = (v: number) => PAD + ((v - minV) / (maxV - minV || 1)) * (W - PAD * 2);
		const toY = (i: number) => H - PAD - (i / (gaps.length - 1)) * (H - PAD * 2);
		const polyline = gaps.map((v, i) => `${toX(v)},${toY(i)}`).join(' ');
		const median = gaps[Math.floor(gaps.length / 2)];
		return { polyline, W, H, PAD, toX, toY, minV: minV.toFixed(1), maxV: maxV.toFixed(1), median: median.toFixed(1) };
	});

	const dcaAssetConcentration = $derived.by(() => {
		if (!orders || orders.length < 8) return null;
		const byAsset = new Map<string, number>();
		let total = 0;
		for (const o of orders) {
			if (!o.pair || o.amount == null || (o.amount as number) <= 0) continue;
			const asset = (o.pair as string).split('/')[0];
			byAsset.set(asset, (byAsset.get(asset) ?? 0) + (o.amount as number));
			total += o.amount as number;
		}
		if (byAsset.size < 3 || total === 0) return null;
		const shares = [...byAsset.entries()].map(([a, v]) => ({ asset: a, share: v / total })).sort((a, b) => b.share - a.share).slice(0, 10);
		const hhi = shares.reduce((s, p) => s + p.share * p.share, 0);
		const W = 280, H = 65, PAD = 8;
		const bw = Math.max(10, (W - PAD * 2) / shares.length - 2);
		return { shares, hhi, W, H, PAD, bw };
	});

	const dcaAmountDistribution = $derived.by(() => {
		if (!orders || orders.length < 8) return null;
		const amounts = orders
			.filter(o => o.amount != null && (o.amount as number) > 0)
			.map(o => o.amount as number)
			.sort((a, b) => a - b);
		if (amounts.length < 6) return null;
		const p95 = amounts[Math.floor(amounts.length * 0.95)];
		const clipped = amounts.filter(v => v <= p95);
		const bins = 10;
		const binW = (clipped[clipped.length - 1] - clipped[0]) / bins || 1;
		const counts = Array(bins).fill(0);
		for (const v of clipped) {
			const idx = Math.min(bins - 1, Math.floor((v - clipped[0]) / binW));
			counts[idx]++;
		}
		const maxCnt = Math.max(...counts, 1);
		const W = 280, H = 65, PAD = 8;
		const bw = (W - PAD * 2) / bins - 1;
		return { counts, maxCnt, bins, binW, clipped, W, H, PAD, bw, minV: clipped[0].toFixed(1), maxV: clipped[clipped.length - 1].toFixed(1) };
	});
</script>

<svelte:head><title>{t(lang, 'dca.title')}</title></svelte:head>

<main class="w-full max-w-[1600px] mx-auto px-4 sm:px-6 py-8">
	<header class="mb-8">
		<h1 class="text-3xl font-semibold tracking-tight">{t(lang, 'dca.title')}</h1>
		<p class="mt-2 max-w-3xl text-sm text-muted-foreground">{t(lang, 'dca.subtitle')}</p>
	</header>

	<PersonalPlan ohlcByCoin={data.ohlcByCoin} events={data.triggers} />
	<BinanceConnect />

	<section class="mb-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
		<Kpi label={t(lang, 'dca.kpi.scheduled')} value={data.summary.scheduled_count} sub={t(lang, 'dca.kpi.scheduledSub')} />
		<Kpi label={t(lang, 'dca.kpi.scheduledUsdt')} value={fmtUSD(data.summary.scheduled_total_usdt)} sub="USDT" />
		<Kpi
			label={t(lang, 'dca.kpi.event')}
			value={data.summary.event_count}
			tone={data.summary.event_count > 0 ? 'good' : 'default'}
			sub={t(lang, 'dca.kpi.eventSub')}
		/>
		<Kpi label={t(lang, 'dca.kpi.eventUsdt')} value={fmtUSD(data.summary.event_total_usdt)} sub="USDT" />
	</section>

	<section class="mb-8 grid gap-4 lg:grid-cols-3">
		<div class="rounded-lg border bg-card p-5 lg:col-span-2">
			<h2 class="mb-3 text-sm font-semibold">{t(lang, 'dca.cumTitle')}</h2>
			{#if data.cumulative.length === 0}
				<div class="rounded border border-dashed p-6 text-center text-xs text-muted-foreground">
					{t(lang, 'dca.cumEmpty')}
				</div>
			{:else}
				{#if cumChart}
					<div class="mb-3 overflow-x-auto">
						<svg viewBox="0 0 {cumChart.W} {cumChart.H}" class="w-full" style="height:100px;min-width:280px">
							<defs>
								<linearGradient id="cumGrad" x1="0" y1="0" x2="0" y2="1">
									<stop offset="0%" stop-color="var(--ch-violet-light)" />
									<stop offset="100%" stop-color="var(--ch-violet-light)" />
								</linearGradient>
							</defs>
							<polygon points={cumChart.areaPts} fill="url(#cumGrad)" />
							<polyline points={cumChart.linePts} fill="none" stroke="rgba(129,140,248,0.9)" stroke-width="2" stroke-linejoin="round" />
						</svg>
					</div>
					<div class="flex items-center justify-between font-mono text-xs text-muted-foreground">
						<span>{fmtTime(data.cumulative[0].ts)}</span>
						<span class="text-indigo-400 font-semibold">Σ {fmtUSD(cumChart.last.cum)}</span>
						<span>{fmtTime(cumChart.last.ts)}</span>
					</div>
				{/if}
				<div class="mt-3 max-h-48 overflow-y-auto space-y-1 font-mono text-xs">
					{#each data.cumulative.slice(-15) as c}
						<div class="flex items-center gap-2">
							<span class="w-32 shrink-0 text-muted-foreground">{fmtTime(c.ts)}</span>
							<div class="relative flex-1 h-3 rounded bg-muted/30">
								<div
									class="absolute left-0 top-0 h-full rounded bg-indigo-500/50"
									style="width: {(c.cum / cumMax) * 100}%"
								></div>
							</div>
							<span class="w-20 shrink-0 text-right text-foreground">{fmtUSD(c.amount)}</span>
							<span class="w-24 shrink-0 text-right text-muted-foreground">Σ {fmtUSD(c.cum)}</span>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<div class="rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">{t(lang, 'dca.kindsTitle')}</h2>
			{#if data.kindAggs.length === 0}
				<div class="rounded border border-dashed p-6 text-center text-xs text-muted-foreground">
					{t(lang, 'dca.kindsEmpty')}
				</div>
			{:else}
				<ul class="space-y-2">
					{#each data.kindAggs as a}
						<li>
							<button
								type="button"
								onclick={() => (kindFilter = kindFilter === a.kind ? null : a.kind)}
								class="flex w-full items-center justify-between rounded border p-2 text-left text-xs transition-colors hover:bg-accent"
								class:border-primary={kindFilter === a.kind}
							>
								<span class="rounded px-1.5 py-0.5 font-mono text-[10px] {kindColor[a.kind] ?? 'bg-muted'}">
									{a.kind}
								</span>
								<span class="text-muted-foreground">
									<span class="font-mono text-foreground">{a.count}</span> · {fmtUSD(a.total_usdt)}
								</span>
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	</section>

	{#if data.triggers.length > 0}
		<section class="mb-8">
			<div class="mb-3 flex items-baseline justify-between">
				<h2 class="text-sm font-semibold">
					{t(lang, 'dca.timelineTitle')}
					{#if kindFilter}
						<span class="ml-2 text-xs text-muted-foreground">{fmt('dca.timelineFilter', { k: kindFilter })}</span>
					{/if}
				</h2>
				{#if kindFilter}
					<button
						type="button"
						onclick={() => (kindFilter = null)}
						class="text-xs text-primary hover:underline"
					>
						{t(lang, 'common.clear')} ×
					</button>
				{/if}
			</div>
			<div class="overflow-hidden rounded-lg border bg-card">
				<table class="w-full text-xs">
					<thead class="bg-secondary text-left text-[10px] uppercase text-muted-foreground">
						<tr>
							<th class="px-3 py-2">{t(lang, 'common.time')}</th>
							<th class="px-3">{t(lang, 'dca.table.kind')}</th>
							<th class="px-3 text-right">{t(lang, 'dca.table.price')}</th>
							<th class="px-3 text-right">{t(lang, 'dca.table.sev')}</th>
							<th class="px-3 text-right">{t(lang, 'dca.table.fng')}</th>
							<th class="px-3 text-right">{t(lang, 'dca.table.amount')}</th>
							<th class="px-3">{t(lang, 'dca.table.mode')}</th>
						</tr>
					</thead>
					<tbody class="font-mono">
						{#each filteredTriggers as t}
							<tr class="border-t border-border hover:bg-accent/40">
								<td class="px-3 py-1.5 text-muted-foreground">{fmtTime(t.ts)}</td>
								<td class="px-3">
									<span class="rounded px-1.5 py-0.5 text-[10px] {kindColor[t.kind] ?? 'bg-muted'}">
										{t.kind}
									</span>
								</td>
								<td class="px-3 text-right">{t.price == null ? '—' : fmtUSD(t.price)}</td>
								<td class="px-3 text-right">{t.severity == null ? '—' : (t.severity * 100).toFixed(2) + '%'}</td>
								<td class="px-3 text-right">{t.fng ?? '—'}</td>
								<td class="px-3 text-right text-foreground">{fmtUSD(t.amount_usdt)}</td>
								<td class="px-3 text-muted-foreground">{t.mode ?? '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	{/if}

	{#if data.log.length > 0}
		<section class="mb-8">
			<h2 class="mb-3 text-sm font-semibold">{t(lang, 'dca.log.title')}</h2>
			<div class="overflow-hidden rounded-lg border bg-card">
				<table class="w-full text-xs">
					<thead class="bg-secondary text-left text-[10px] uppercase text-muted-foreground">
						<tr>
							<th class="px-3 py-2">{t(lang, 'common.time')}</th>
							<th class="px-3">{t(lang, 'dca.table.mode')}</th>
							<th class="px-3 text-right">{t(lang, 'dca.log.base')}</th>
							<th class="px-3 text-right">{t(lang, 'dca.log.mult')}</th>
							<th class="px-3 text-right">{t(lang, 'dca.log.actual')}</th>
							<th class="px-3 text-right">{t(lang, 'dca.table.fng')}</th>
							<th class="px-3">{t(lang, 'dca.log.cycle')}</th>
						</tr>
					</thead>
					<tbody class="font-mono">
						{#each data.log.slice(0, 30) as r}
							<tr class="border-t border-border hover:bg-accent/40">
								<td class="px-3 py-1.5 text-muted-foreground">{fmtTime(r.timestamp)}</td>
								<td class="px-3">{r.mode}</td>
								<td class="px-3 text-right">{fmtUSD(r.base_usdt)}</td>
								<td class="px-3 text-right">×{(r.multiplier ?? 1).toFixed(2)}</td>
								<td class="px-3 text-right text-foreground">{fmtUSD(r.amount_usdt)}</td>
								<td class="px-3 text-right">{r.fng_value ?? '—'}</td>
								<td class="px-3 text-muted-foreground">{r.cycle_signal ?? '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	{/if}

	{#if weeklyTriggers}
		{@const wt = weeklyTriggers}
		<section class="mb-8 rounded-lg border bg-card p-5">
			<div class="mb-2 flex items-baseline justify-between">
				<h2 class="text-sm font-semibold">Weekly Trigger Activity <span class="ml-1 font-normal text-muted-foreground text-xs">(last {wt.weeks} weeks)</span> <ChartInfo metric="dcaTrigger" {lang} /></h2>
				<span class="font-mono text-xs text-muted-foreground">Σ {fmtUSD(wt.totalUsdt)}</span>
			</div>
			<svg viewBox="0 0 {wt.W} {wt.H}" class="w-full" style="height:60px;min-width:280px">
				{#each wt.bars as b}
					<rect
						x={b.x + 0.5}
						y={wt.H - b.h - 2}
						width={Math.max(2, wt.barW - 1)}
						height={b.h}
						fill="var(--ch-violet)"
						rx="1"
					>
						<title>{b.week}: {b.count} trigger{b.count !== 1 ? 's' : ''} · {fmtUSD(b.usdt)}</title>
					</rect>
				{/each}
			</svg>
			<div class="mt-1 flex justify-between text-[10px] text-muted-foreground font-mono">
				<span>{wt.bars[0].week}</span>
				<span>Each bar = 1 week</span>
				<span>{wt.bars[wt.bars.length - 1].week}</span>
			</div>
		</section>
	{/if}

	<!-- DCA projection chart -->
	<section class="mb-8 rounded-lg border bg-card p-5">
		<div class="mb-4 flex flex-wrap items-baseline justify-between gap-3">
			<h2 class="text-sm font-semibold">{lang === 'en' ? '📈 5-Year Accumulation Projection' : '📈 5年积累预测'}</h2>
			<div class="flex items-center gap-3 text-xs">
				<label class="flex items-center gap-2 text-muted-foreground">
					{lang === 'en' ? 'Monthly' : '月投'}
					<input type="number" bind:value={projMonthly} min="50" max="10000" step="50"
						class="w-20 rounded border border-border bg-background px-2 py-1 font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary" />
					USDT
				</label>
			</div>
		</div>
		<div class="overflow-x-auto">
			<svg viewBox="0 0 560 140" class="w-full" style="height:120px;min-width:280px">
				{#each [0.25, 0.5, 0.75, 1] as f}
					<line x1="0" y1={140*(1-f)} x2="560" y2={140*(1-f)} stroke="var(--ch-rule-faint)" stroke-width="1"/>
				{/each}
				{#each [12,24,36,48,60] as m}
					<line x1={m/60*560} y1="0" x2={m/60*560} y2="140" stroke="var(--ch-rule-faint)" stroke-width="1"/>
					<text x={m/60*560} y="138" text-anchor="middle" font-size="8" fill="var(--ch-rule-strong)">Y{m/12}</text>
				{/each}
				{#each projectionData as sc}
					<polyline points={sc.polyline} fill="none" stroke={sc.color} stroke-width="2"/>
				{/each}
			</svg>
		</div>
		<div class="mt-3 flex flex-wrap gap-4">
			{#each projectionData as sc}
				<div class="flex items-center gap-2 text-xs">
					<span class="inline-block h-0.5 w-6 rounded" style="background:{sc.color}"></span>
					<span class="text-muted-foreground">{sc.label}</span>
					<span class="font-mono font-semibold" style="color:{sc.color}">${sc.final.toLocaleString('en-US', { maximumFractionDigits: 0 })}</span>
				</div>
			{/each}
		</div>
		<p class="mt-2 text-[10px] text-muted-foreground">{lang === 'en' ? `BTC entry price: $${(projBtcPrice ?? 60000).toLocaleString('en-US', { maximumFractionDigits: 0 })} · assumes constant monthly DCA + CAGR applied to total BTC stack` : `BTC 入场价: $${(projBtcPrice ?? 60000).toLocaleString('en-US', { maximumFractionDigits: 0 })} · 假设固定月投 + 对全部 BTC 持仓应用 CAGR`}</p>
	</section>

	{#if severityHistogram}
		{@const sh = severityHistogram}
		<section class="mb-8 rounded-lg border bg-card p-5">
			<h2 class="mb-4 text-sm font-semibold">Signal Severity Distribution <span class="ml-1 font-normal text-muted-foreground text-xs">({sh.total} triggers · severity 0 = mild → 1 = extreme)</span> <ChartInfo metric="fearGreed" {lang} /></h2>
			<div class="flex items-end gap-1">
				{#each sh.buckets as b, i}
					{@const barH = Math.round((b.total / sh.maxTotal) * 80)}
					<div class="flex flex-1 flex-col items-center gap-0.5" title="{(b.lo * 100).toFixed(0)}-{(b.hi * 100).toFixed(0)}%: {b.total} events">
						<div class="relative w-full overflow-hidden rounded-t-sm flex flex-col-reverse" style="height:{Math.max(2, barH)}px">
							{#if b.FLASH > 0}<div style="height:{Math.round((b.FLASH/Math.max(1,b.total))*barH)}px;background:var(--ch-loss)"></div>{/if}
							{#if b.FAST > 0}<div style="height:{Math.round((b.FAST/Math.max(1,b.total))*barH)}px;background:var(--ch-warn)"></div>{/if}
							{#if b.SUSTAIN > 0}<div style="height:{Math.round((b.SUSTAIN/Math.max(1,b.total))*barH)}px;background:var(--ch-violet)"></div>{/if}
							{#if b.CAPITUL > 0}<div style="height:{Math.round((b.CAPITUL/Math.max(1,b.total))*barH)}px;background:var(--ch-violet-strong)"></div>{/if}
						</div>
						<span class="font-mono text-[8px] text-muted-foreground">{(b.lo * 100).toFixed(0)}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar height = event count per severity bucket · colors match signal kind</p>
		</section>
	{/if}

	{#if kindAmountChart}
		<section class="mb-8 rounded-lg border bg-card p-5">
			<h2 class="mb-4 text-sm font-semibold">Capital Deployed by Signal Kind <span class="ml-1 font-normal text-muted-foreground text-xs">({data.triggers.length} total triggers)</span> <ChartInfo metric="signalKind" {lang} /></h2>
			<div class="space-y-2">
				{#each kindAmountChart as row}
					<div class="flex items-center gap-2 text-xs">
						<span class="w-16 shrink-0 font-mono font-semibold" style="color:{KIND_DEPLOY_COLORS[row.kind]}">{row.kind}</span>
						<div class="relative flex-1 h-6 rounded-sm bg-muted/20 overflow-hidden">
							<div class="absolute inset-y-0 left-0 rounded-sm transition-all"
								style="width:{row.barPct.toFixed(1)}%; background:{KIND_DEPLOY_COLORS[row.kind]}"></div>
							<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">${row.usdt.toFixed(0)} USDT</span>
						</div>
						<span class="w-12 shrink-0 text-right font-mono text-[10px] text-muted-foreground">{row.pct.toFixed(0)}%</span>
						<span class="w-10 shrink-0 text-right font-mono text-[10px] text-muted-foreground">{row.count}×</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar width = relative USDT deployed · % = share of total capital · × = trigger count</p>
		</section>
	{/if}

	{#if triggerHourChart}
		<section class="mt-6 mb-8 rounded-lg border bg-card p-5">
			<h2 class="mb-4 text-sm font-semibold">Trigger Hour of Day (UTC) <span class="ml-1 font-normal text-muted-foreground text-xs">(when DCA events fire · {data.triggers.length} total)</span> <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<div class="flex items-end gap-px">
				{#each triggerHourChart as h}
					<div class="flex flex-1 flex-col items-center gap-0.5" title="Hour {h.h}:00 UTC: {h.count} events · {h.amount.toFixed(0)} USDT">
						<div class="w-full rounded-t-sm"
							style="height:{Math.max(1, Math.round(h.barPct * 0.6))}px; background:{h.count === 0 ? 'var(--ch-axis-faint)' : 'var(--ch-violet-light)'}">
						</div>
						{#if h.h % 6 === 0}
							<span class="font-mono text-[8px] text-muted-foreground">{h.h}h</span>
						{/if}
					</div>
				{/each}
			</div>
			<div class="mt-2 flex gap-4 text-[10px] text-muted-foreground">
				<span>Bar height = relative trigger count · Asia: 0-8 · EU: 8-16 · US: 14-22</span>
			</div>
		</section>
	{/if}

	{#if sevAmountScatter}
		{@const sa = sevAmountScatter}
		<section class="mt-6 mb-8 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Severity vs Capital Deployed <span class="ml-1 font-normal text-muted-foreground text-xs">({sa.dots.length} events with both fields)</span> <ChartInfo metric="fearGreed" {lang} /></h2>
			<svg viewBox="0 0 {sa.W} {sa.H}" class="w-full" style="height:{sa.H}px;min-width:200px">
				<line x1={sa.PAD} y1={sa.PAD} x2={sa.PAD} y2={sa.H - sa.PAD} stroke="var(--ch-rule-faint)" stroke-width="1"/>
				<line x1={sa.PAD} y1={sa.H - sa.PAD} x2={sa.W - sa.PAD} y2={sa.H - sa.PAD} stroke="var(--ch-rule-faint)" stroke-width="1"/>
				{#each sa.dots as d}
					<circle cx={d.x.toFixed(1)} cy={d.y.toFixed(1)} r="3" fill={d.color}>
						<title>{d.kind} · sev {d.sev.toFixed(3)} · {d.amount.toFixed(0)} USDT</title>
					</circle>
				{/each}
				<text x={sa.PAD} y={sa.H - 2} font-size="7" fill="var(--ch-rule)">{sa.sMin.toFixed(2)}</text>
				<text x={sa.W - sa.PAD} y={sa.H - 2} font-size="7" fill="var(--ch-rule)" text-anchor="end">{sa.sMax.toFixed(2)} →sev</text>
				<text x={sa.PAD + 2} y={sa.PAD + 8} font-size="7" fill="var(--ch-rule)">{sa.aMax.toFixed(0)} USDT ↑</text>
			</svg>
			<p class="mt-1 text-[10px] text-muted-foreground">x = severity · y = USDT deployed · color = event kind · positive correlation = model scales correctly with fear</p>
		</section>
	{/if}

	<section class="mb-8">
		<h2 class="mb-3 text-sm font-semibold">{t(lang, 'dca.reports')}</h2>
		<div class="grid gap-3 md:grid-cols-2">
			{#each REPORT_CARDS as c}
				<a
					href={c.href}
					data-sveltekit-reload
					class="group rounded-lg border bg-card p-4 transition-colors hover:border-primary"
				>
					<div class="font-semibold">{c.title}</div>
					<div class="mt-1 text-xs text-muted-foreground">{c.desc}</div>
					<div class="mt-2 font-mono text-[10px] text-primary opacity-0 transition-opacity group-hover:opacity-100">
						{c.href} →
					</div>
				</a>
			{/each}
		</div>
	</section>

	{#if dcaAmountTrend}
		{@const dat = dcaAmountTrend}
		<section class="mt-6 mb-8 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">DCA Sizing Trend <span class="ml-1 font-normal text-muted-foreground text-xs">(5-event rolling avg · {dat.first} → {dat.last})</span> <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<svg viewBox="0 0 {dat.W} {dat.H}" class="w-full" style="height:{dat.H}px">
				<polyline points={dat.polyline} fill="none"
					stroke={dat.trend >= 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss)'}
					stroke-width="1.5" stroke-linejoin="round"/>
				<text x={dat.PAD} y={dat.H - 2} font-size="7" fill="var(--ch-rule)">{dat.first}</text>
				<text x={dat.W - dat.PAD} y={dat.H - 2} font-size="7" fill="var(--ch-rule)" text-anchor="end">{dat.last}</text>
				<text x={dat.W - dat.PAD} y="10" font-size="8"
					fill={dat.trend >= 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss-strong)'}
					text-anchor="end">latest avg: ${dat.latest.toFixed(0)}</text>
			</svg>
			<p class="mt-1 text-[10px] text-muted-foreground">
				5-event moving average of USDT deployed per trigger · trend {dat.trend >= 0 ? '↑ growing' : '↓ shrinking'} by ${Math.abs(dat.trend).toFixed(0)} from first to last
			</p>
		</section>
	{/if}

	{#if kindDowHeatmap}
		{@const kdh = kindDowHeatmap}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Trigger Kind × Day-of-Week
				<span class="ml-1 font-normal text-muted-foreground text-xs">(frequency heatmap — darker = more triggers)</span> <ChartInfo metric="distribution" {lang} /></h2>
			<div class="overflow-x-auto">
				<table class="w-full text-[11px]">
					<thead>
						<tr>
							<th class="pr-3 text-left font-normal text-muted-foreground w-20">Kind</th>
							{#each kdh.days as day}
								<th class="px-2 text-center font-normal text-muted-foreground">{day}</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each kdh.kinds as kind}
							<tr class="border-t border-border/30">
								<td class="pr-3 py-1.5 font-mono text-[10px] text-foreground">{kind}</td>
								{#each kdh.days as _, di}
									<td class="px-2 py-1 text-center">
										{#if kdh.grid[kind][di] > 0}
											<span class="inline-flex items-center justify-center rounded w-7 h-6 font-mono text-[10px] font-semibold"
												style="background:rgba(99,102,241,{(kdh.grid[kind][di] / kdh.maxVal * 0.8 + 0.1).toFixed(2)}); color:white">
												{kdh.grid[kind][di]}
											</span>
										{:else}
											<span class="text-muted-foreground/30">·</span>
										{/if}
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Days are UTC · darker cells = more triggers of that kind on that weekday</p>
		</section>
	{/if}

	{#if severityTimeline}
		{@const st = severityTimeline}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-2 text-sm font-semibold">Market Stress Timeline
				<span class="ml-1 font-normal text-muted-foreground text-xs">
					(5-event rolling avg severity · latest {(st.latest * 100).toFixed(0)}% · peak {(st.peak * 100).toFixed(0)}%)
				</span> <ChartInfo metric="fearGreed" {lang} /></h2>
			<svg viewBox="0 0 {st.W} {st.H}" class="w-full" style="height:{st.H}px">
				<line x1={st.PAD} y1={(st.H - st.PAD - (0.5) * (st.H - st.PAD * 2)).toFixed(1)}
					x2={st.W - st.PAD} y2={(st.H - st.PAD - (0.5) * (st.H - st.PAD * 2)).toFixed(1)}
					stroke="var(--ch-rule-faint)" stroke-width="1" stroke-dasharray="3 2"/>
				<polyline points={st.polyline} fill="none" stroke="var(--ch-loss)" stroke-width="1.5"/>
				{#each st.pts as p, i}
					{#if i === st.pts.length - 1}
						<circle cx={(st.PAD + (i / Math.max(1, st.pts.length - 1)) * (st.W - st.PAD * 2)).toFixed(1)}
							cy={(st.H - st.PAD - p.ma * (st.H - st.PAD * 2)).toFixed(1)}
							r="3" fill="var(--ch-loss-strong)"/>
					{/if}
				{/each}
			</svg>
			<div class="mt-1 flex justify-between text-[10px] text-muted-foreground">
				<span>{st.first}</span>
				<span class:text-red-400={st.latest > 0.6} class:text-yellow-400={st.latest > 0.3 && st.latest <= 0.6} class:text-green-400={st.latest <= 0.3}>
					current {(st.latest * 100).toFixed(0)}%
				</span>
				<span>{st.last}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Higher = more market stress · red &gt;60% · yellow 30–60% · green ≤30%</p>
		</section>
	{/if}

	{#if kindCumulativeShare}
		{@const kcs = kindCumulativeShare}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Capital Deployed by Kind
				<span class="ml-1 font-normal text-muted-foreground text-xs">(total ${kcs.grandTotal.toFixed(0)} USDT across all triggers)</span> <ChartInfo metric="signalKind" {lang} /></h2>
			<div class="space-y-2">
				{#each kcs.rows as r}
					<div class="flex items-center gap-2">
						<span class="w-20 shrink-0 font-mono text-[10px] truncate">{r.kind}</span>
						<div class="relative flex-1 h-5 rounded-sm bg-muted/20 overflow-hidden">
							<div class="absolute inset-y-0 left-0 rounded-sm"
								style="width:{(r.pct * 100).toFixed(1)}%; background:rgba(99,102,241,{(r.avgSev * 0.7 + 0.25).toFixed(2)})"></div>
							<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">
								${r.total.toFixed(0)} · {(r.pct * 100).toFixed(1)}%
							</span>
						</div>
						<span class="w-14 shrink-0 text-right font-mono text-[10px] text-muted-foreground">
							{r.count}× avg ${(r.total / r.count).toFixed(0)}
						</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar width = share of total capital · opacity ∝ avg severity · right = trigger count and avg size</p>
		</section>
	{/if}

	{#if amountByDayOfWeek}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Capital Deployed by Weekday
				<span class="ml-1 font-normal text-muted-foreground text-xs">(total USDT · Mon – Sun)</span> <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<div class="flex items-end gap-2" style="height:72px">
				{#each amountByDayOfWeek as d}
					<div class="flex flex-1 flex-col items-center gap-1 justify-end"
						title="{d.label}: ${d.total.toFixed(0)} total · ${d.avg.toFixed(0)} avg · {d.count} triggers">
						<div class="w-full rounded-t-sm transition-all bg-cyan-500/50"
							style="height:{Math.max(2, d.barPct * 0.6)}px"></div>
						<span class="font-mono text-[10px] font-semibold">{d.label}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar height = total USDT deployed that weekday · hover for avg per trigger and count</p>
		</section>
	{/if}

	{#if triggerGapDistribution}
		{@const tgd = triggerGapDistribution}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Trigger Gap Distribution
				<span class="ml-1 font-normal text-muted-foreground text-xs">(time between consecutive triggers · avg {tgd.avgGapH.toFixed(1)}h)</span> <ChartInfo metric="distribution" {lang} /></h2>
			<div class="flex items-end gap-3" style="height:72px">
				{#each tgd.buckets as b}
					<div class="flex flex-1 flex-col items-center gap-1 justify-end">
						<span class="font-mono text-[9px] text-muted-foreground">{b.count}</span>
						<div class="w-full rounded-t-sm transition-all bg-cyan-500/50"
							style="height:{Math.max(2, (b.count / tgd.maxCount) * 60)}px"></div>
						<span class="font-mono text-[10px] font-semibold text-center leading-tight">{b.label}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Gap between consecutive DCA triggers · tall bar at &lt;1h = clustered (event-driven) · tall bar at 1–7d = periodic</p>
		</section>
	{/if}

	{#if monthlyTriggerSummary}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Monthly Trigger Summary
				<span class="ml-1 font-normal text-muted-foreground text-xs">({monthlyTriggerSummary.reduce((s,m)=>s+m.count,0)} total triggers · last 12 months)</span> <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<div class="space-y-1.5">
				{#each monthlyTriggerSummary as m}
					<div class="flex items-center gap-2">
						<span class="w-16 shrink-0 font-mono text-[10px] text-muted-foreground">{m.label}</span>
						<div class="relative flex-1 h-5 rounded-sm bg-muted/20 overflow-hidden">
							<div class="absolute inset-y-0 left-0 rounded-sm bg-indigo-500/50"
								style="width:{m.barPct.toFixed(1)}%"></div>
							<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">
								{m.count} trigger{m.count !== 1 ? 's' : ''}
							</span>
						</div>
						<span class="w-20 shrink-0 text-right font-mono text-[10px] text-muted-foreground">
							${m.total.toFixed(0)}
						</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar width = trigger count · right = total USDT deployed that month</p>
		</section>
	{/if}

	{#if avgAmountBySeverity}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Avg Deploy by Severity
				<span class="ml-1 font-normal text-muted-foreground text-xs">(mean USDT deployed per severity range)</span> <ChartInfo metric="fearGreed" {lang} /></h2>
			<div class="space-y-2">
				{#each avgAmountBySeverity as b}
					<div class="flex items-center gap-3">
						<span class="w-16 shrink-0 font-mono text-[10px] text-muted-foreground">{b.label}</span>
						<div class="relative flex-1 h-5 rounded-sm bg-muted/20 overflow-hidden">
							<div class="absolute inset-y-0 left-0 rounded-sm transition-all"
								style="width:{b.barPct.toFixed(1)}%; background:var(--ch-violet)"></div>
							{#if b.avg != null}
								<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">
									${b.avg.toFixed(0)}
								</span>
							{/if}
						</div>
						<span class="w-14 shrink-0 text-right font-mono text-[10px] text-muted-foreground">{b.count} evt{b.count !== 1 ? 's' : ''}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar = avg USDT deployed per event · x axis = severity score range · higher severity → larger position sizing?</p>
		</section>
	{/if}

	{#if triggerFngDistribution}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Fear &amp; Greed at Trigger Time
				<span class="ml-1 font-normal text-muted-foreground text-xs">(distribution of F&amp;G index when DCA signals fired)</span> <ChartInfo metric="fearGreed" {lang} /></h2>
			<div class="flex items-end gap-1" style="height:64px">
				{#each triggerFngDistribution as b}
					<div class="flex flex-1 flex-col items-center justify-end"
						title="{b.label}: {b.count} triggers{b.avgAmt != null ? ' · avg $' + b.avgAmt.toFixed(0) : ''}">
						{#if b.count > 0}
							<div class="w-full rounded-t-sm" style="height:{Math.max(2, b.barPct * 0.52)}px; background:{b.color}"></div>
						{/if}
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>0 (Fear)</span><span>50</span><span>100 (Greed)</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Each bar = count of triggers at that F&amp;G range · green = fear zones · red = greed zones · taller bars = more frequent signals at that sentiment level</p>
		</section>
	{/if}

	{#if monthlyTriggerVolume}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Monthly DCA Activity (last 12 months)
				<span class="ml-1 font-normal text-muted-foreground text-xs">(trigger count + USDT deployed per calendar month)</span> <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<div class="flex items-end gap-1" style="height:80px">
				{#each monthlyTriggerVolume as m}
					<div class="flex flex-1 flex-col items-center justify-end gap-px"
						title="{m.label}: {m.count} triggers · ${m.usdt.toFixed(0)} USDT">
						{#if m.count > 0}
							<div class="w-full rounded-t-sm" style="height:{Math.max(2, m.countPct * 0.72)}px; background:var(--ch-violet)"></div>
						{:else}
							<div class="w-full" style="height:1px; background:var(--ch-rule-faint)"></div>
						{/if}
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				{#each monthlyTriggerVolume as m, i}
					{#if i === 0 || i === 5 || i === 11}
						<span>{m.label}</span>
					{/if}
				{/each}
			</div>
			<div class="mt-3 grid grid-cols-6 gap-1 sm:grid-cols-12">
				{#each monthlyTriggerVolume as m}
					<div class="flex flex-col items-center gap-0.5" title="${m.usdt.toFixed(0)} USDT in {m.label}">
						<div class="w-full rounded-sm" style="height:{Math.max(1, m.usdtPct * 0.24)}px; background:var(--ch-warn-light)"></div>
					</div>
				{/each}
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Blue bars = trigger count · gold mini-bars = USDT deployed · taller = more active DCA month</p>
		</section>
	{/if}

	<section class="rounded-lg border border-dashed bg-card p-5 text-xs text-muted-foreground">
		<b class="text-foreground">{t(lang, 'dca.how')}</b>
		{t(lang, 'dca.howText')}
		<a class="ml-2 text-primary hover:underline" href="/docs/strategies/event-dca/">{t(lang, 'dca.howLink')}</a>
	</section>

	{#if fngAtTriggerTimeline}
		{@const ftl = fngAtTriggerTimeline}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-2 text-sm font-semibold">F&amp;G Sentiment at Trigger Time (8-event rolling avg)
				<span class="ml-2 text-xs font-normal text-muted-foreground">
					{ftl.drift > 5 ? '↑ trending greedier' : ftl.drift < -5 ? '↓ trending more fearful' : '→ stable'} · latest {ftl.latest.toFixed(0)}
				</span> <ChartInfo metric="fearGreed" {lang} /></h2>
			<svg viewBox="0 0 {ftl.W} {ftl.H}" class="w-full" style="height:64px">
				<line x1={ftl.PAD} x2={ftl.W - ftl.PAD} y1={ftl.fearY} y2={ftl.fearY} stroke="var(--ch-profit-light)" stroke-width="1" stroke-dasharray="3 3"/>
				<line x1={ftl.PAD} x2={ftl.W - ftl.PAD} y1={ftl.greedY} y2={ftl.greedY} stroke="var(--ch-loss-light)" stroke-width="1" stroke-dasharray="3 3"/>
				<polyline points={ftl.polyline} fill="none" stroke="var(--ch-warn)" stroke-width="1.5"/>
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>{ftl.firstDate}</span>
				<span class="text-green-500/70">— fear ≤25</span>
				<span class="text-red-500/70">— greed ≥75</span>
				<span>{ftl.lastDate}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Gold line = rolling avg F&amp;G when DCA fired · below green dashed = fear zone · above red = greed zone · drift = {ftl.drift >= 0 ? '+' : ''}{ftl.drift.toFixed(1)} pts over {ftl.count} events</p>
		</section>
	{/if}
	{#if severityAmountCumulative}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Total USDT Deployed by Severity
				<span class="ml-1 font-normal text-muted-foreground text-xs">(cumulative capital committed per severity level)</span> <ChartInfo metric="fearGreed" {lang} /></h2>
			<div class="mt-3 flex gap-2" style="height:32px">
				{#each severityAmountCumulative.totals as r, i}
					{#if r.total > 0}
						<div class="flex items-center justify-center rounded text-[10px] font-mono text-white overflow-hidden"
							style="flex:{r.total}; background:{severityAmountCumulative.COLORS[i]}" title="Severity {r.sev}: ${r.total.toFixed(0)}">
							s{r.sev}
						</div>
					{/if}
				{/each}
			</div>
			<div class="mt-2 space-y-1">
				{#each severityAmountCumulative.totals as r, i}
					{#if r.total > 0}
						<div class="flex items-center gap-2">
							<span class="flex h-2.5 w-2.5 rounded-sm" style="background:{severityAmountCumulative.COLORS[i]}"></span>
							<span class="font-mono text-[10px] text-muted-foreground">Severity {r.sev}</span>
							<span class="ml-auto font-mono text-[10px]">${r.total.toFixed(0)}</span>
							<span class="w-10 text-right font-mono text-[9px] text-muted-foreground">{((r.total / severityAmountCumulative.grandTotal) * 100).toFixed(1)}%</span>
						</div>
					{/if}
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Proportional bar shows USDT share per severity · reveals which alert levels drive most capital deployment</p>
		</section>
	{/if}
	{#if triggerDayOfMonth}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Triggers by Day of Month
				<span class="ml-1 font-normal text-muted-foreground text-xs">(does DCA fire more at month start, mid, or end?)</span> <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<div class="mt-3 flex items-end gap-px" style="height:64px">
				{#each triggerDayOfMonth as d}
					<div class="flex flex-1 flex-col items-center">
						<div class="w-full rounded-t" style="height:{Math.max(1, d.barPct * 0.56)}px; background:{d.day <= 10 ? 'var(--ch-violet)' : d.day <= 20 ? 'var(--ch-warn-light)' : 'var(--ch-profit-light)'}"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>1st</span><span>10th</span><span>20th</span><span>31st</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Purple = days 1–10 · yellow = 11–20 · green = 21–31 · spikes reveal calendar-driven market fear patterns</p>
		</section>
	{/if}
	{#if fngKindAvg}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Avg F&amp;G When Each Kind Fires
				<span class="ml-1 font-normal text-muted-foreground text-xs">(which event types trigger in fearful vs greedy markets?)</span> <ChartInfo metric="scatter" {lang} /></h2>
			<div class="mt-3 space-y-1.5">
				{#each fngKindAvg as r}
					<div class="flex items-center gap-2">
						<span class="w-28 shrink-0 truncate font-mono text-[10px]">{r.kind}</span>
						<div class="relative flex-1 rounded bg-muted h-4 overflow-hidden">
							<div class="absolute inset-y-0 left-0 rounded"
								style="width:{r.avg}%; background:{r.avg <= 25 ? 'var(--ch-profit)' : r.avg <= 45 ? 'var(--ch-violet-light)' : r.avg <= 60 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)'}"></div>
							<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">F&amp;G {r.avg.toFixed(0)}</span>
						</div>
						<span class="w-14 shrink-0 text-right font-mono text-[9px] text-muted-foreground">{r.count} evt</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Green ≤25 = fires in extreme fear · purple = fear zone · yellow = neutral · red = fires in greed</p>
		</section>
	{/if}
	{#if kindCumulativeLines}
		{@const kcl = kindCumulativeLines}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Cumulative USDT Deployed by Kind
				<span class="ml-1 font-normal text-muted-foreground text-xs">(running total per event type over all triggers chronologically)</span> <ChartInfo metric="signalKind" {lang} /></h2>
			<svg viewBox="0 0 {kcl.W} {kcl.H}" class="mt-3 w-full" style="height:80px">
				{#each kcl.lines as ln}
					<polyline points={ln.poly} fill="none" stroke={ln.color} stroke-width="1.5"/>
				{/each}
			</svg>
			<div class="mt-2 flex flex-wrap gap-4">
				{#each kcl.lines as ln}
					<span class="flex items-center gap-1.5 font-mono text-[10px]">
						<span class="inline-block h-2.5 w-5 rounded-sm" style="background:{ln.color}"></span>
						{ln.kind} <span class="text-muted-foreground">${ln.final.toFixed(0)}</span>
					</span>
				{/each}
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Each line = one event kind's cumulative USDT deployed · steeper slope = kind fires more capital · shows which trigger type dominates total spend</p>
		</section>
	{/if}
	{#if triggerAmountDistribution}
		{@const tad = triggerAmountDistribution}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">DCA Amount Distribution
				<span class="ml-1 font-normal text-muted-foreground text-xs">(histogram of individual trigger sizes · avg ${tad.avg.toFixed(0)} · median ${tad.median.toFixed(0)})</span> <ChartInfo metric="distribution" {lang} /></h2>
			<div class="mt-3 flex items-end gap-1" style="height:72px">
				{#each tad.buckets as b}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<span class="font-mono text-[8px] text-muted-foreground">{b.count > 0 ? b.count : ''}</span>
						<div class="w-full rounded-t" style="height:{Math.max(2, b.barPct * 0.62)}px; background:var(--ch-violet-light)"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>${tad.mn.toFixed(0)}</span><span>→ USDT per trigger →</span><span>${tad.mx.toFixed(0)}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Distribution of individual DCA deployment sizes · reveals whether strategy uses fixed or variable position sizing</p>
		</section>
	{/if}

	{#if fngAmountScatter}
		{@const fas = fngAmountScatter}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Fear &amp; Greed vs Deploy Size <ChartInfo metric="fearGreed" {lang} /></h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Each dot = one DCA trigger · X = FNG index · Y = USDT deployed</p>
			<svg viewBox="0 0 {fas.W} {fas.H}" class="mt-2 w-full" style="height:80px">
				{#each fas.mapped as p}
					<circle cx={p.cx} cy={p.cy} r="2.5" fill="rgba({p.fng <= 30 ? '34,197,94' : p.fng >= 70 ? '239,68,68' : '234,179,8'},0.65)"/>
				{/each}
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>FNG {fas.minF}</span><span>→ fear/greed →</span><span>{fas.maxF}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Green = fear zone (FNG≤30) · red = greed zone (FNG≥70) · upward cluster in fear zone = strategy deploys more when market is fearful</p>
		</section>
	{/if}

	{#if triggerIntervalDistribution}
		{@const tid = triggerIntervalDistribution}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Trigger Interval Distribution <ChartInfo metric="distribution" {lang} /></h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Hours between consecutive DCA triggers across {tid.total} gaps · median {tid.median}h</p>
			<div class="mt-3 flex items-end gap-1" style="height:72px">
				{#each tid.buckets as b}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<span class="font-mono text-[8px] text-muted-foreground">{b.count > 0 ? b.count : ''}</span>
						<div class="w-full rounded-sm" style="height:{b.barPct}%; background:var(--ch-warn); min-height:{b.count > 0 ? 2 : 0}px"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>{tid.buckets[0].label}</span><span>→ gap between triggers →</span><span>{tid.buckets[tid.buckets.length - 1].label}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Left-skewed = many triggers cluster close together (fear events) · right-skewed = long quiet periods between DCA deployments</p>
		</section>
	{/if}

	{#if triggerHourDistribution}
		{@const thd = triggerHourDistribution}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Trigger Hour of Day (UTC) <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<p class="mt-0.5 text-xs text-muted-foreground">DCA triggers by UTC hour across {thd.total} events — reveals market-session clustering</p>
			<div class="mt-3 flex items-end gap-px" style="height:60px">
				{#each thd.counts as h}
					<div class="flex flex-1 flex-col items-center">
						<div class="w-full rounded-sm" style="height:{h.barPct}%; background:rgba(99,102,241,{0.35 + h.barPct / 200}); min-height:{h.count > 0 ? 1 : 0}px"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[8px] text-muted-foreground">
				<span>00h</span><span>06h</span><span>12h</span><span>18h</span><span>23h</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Spikes near 00h/08h/16h = Asia/London/NY session opens · pattern reveals which trading sessions drive fear events</p>
		</section>
	{/if}

	{#if triggerMonthlyCount}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">DCA Triggers per Month <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Monthly DCA event count — shows when markets were most fearful and DCA activity peaked</p>
			<div class="mt-3 flex items-end gap-1" style="height:72px">
				{#each triggerMonthlyCount as r}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<span class="font-mono text-[7px] text-muted-foreground">{r.count > 0 ? r.count : ''}</span>
						<div class="w-full rounded-sm" style="height:{r.barPct}%; background:var(--ch-violet-strong); min-height:{r.count > 0 ? 2 : 0}px"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>{triggerMonthlyCount[0].ym}</span><span>→ month →</span><span>{triggerMonthlyCount[triggerMonthlyCount.length - 1].ym}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Tall bars = months with multiple fear events · long gaps = calm market periods with no DCA signals · useful for correlating with market cycles</p>
		</section>
	{/if}

	{#if triggerAmountByMonth}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">DCA Capital Deployed per Month (USDT) <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Total USDT deployed via DCA triggers per calendar month — shows capital commitment over time</p>
			<div class="mt-3 flex items-end gap-1" style="height:72px">
				{#each triggerAmountByMonth as r}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<div class="w-full rounded-sm" style="height:{r.barPct}%; background:var(--ch-teal); min-height:2px"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>{triggerAmountByMonth[0].ym}</span><span>→ month →</span><span>{triggerAmountByMonth[triggerAmountByMonth.length - 1].ym}</span>
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>$0</span><span>peak: ${triggerAmountByMonth.reduce((m, r) => r.total > m ? r.total : m, 0).toFixed(0)}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Tall bars = months with heavy capital deployment · rising trend = scaling into fear · compare with monthly count to see avg deployment per trigger</p>
		</section>
	{/if}

	{#if kindFngProfile}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Average Fear & Greed by Trigger Kind <ChartInfo metric="fearGreed" {lang} /></h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Mean FNG index value at time of trigger for each DCA kind — lower = more fearful conditions</p>
			<div class="mt-3 space-y-2">
				{#each kindFngProfile as r}
					<div class="flex items-center gap-2">
						<span class="w-20 font-mono text-[10px] font-semibold" style="color:{r.color.replace('0.7', '1')}">{r.kind}</span>
						<div class="flex-1 overflow-hidden rounded-sm" style="height:14px; background:var(--ch-rule-faint)">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{r.color}"></div>
						</div>
						<span class="w-14 text-right font-mono text-[10px] text-muted-foreground">FNG {r.avg.toFixed(1)}</span>
						<span class="w-8 text-right font-mono text-[9px] text-muted-foreground">n={r.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Lower FNG = deeper fear at trigger · FLASH should show lowest FNG (acute panic) · SUSTAIN/CAPITUL at higher FNG (prolonged but less extreme fear)</p>
		</section>
	{/if}

	{#if triggerSeverityBreakdown}
		<section class="rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Trigger Severity Breakdown <ChartInfo metric="fearGreed" {lang} /></h2>
			<p class="mb-3 text-[11px] text-muted-foreground">Count, average DCA amount, and average Fear &amp; Greed index by severity level</p>
			<div class="space-y-2">
				{#each triggerSeverityBreakdown as r}
					<div class="flex items-center gap-2">
						<span class="w-16 text-right font-mono text-[11px] font-semibold" style="color:{r.color}">{r.label}</span>
						<div class="h-4 flex-1 overflow-hidden rounded-sm bg-muted">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{r.color}"></div>
						</div>
						<span class="w-10 text-right font-mono text-[10px] text-muted-foreground">{r.count}x</span>
						<span class="w-20 text-right font-mono text-[10px] text-muted-foreground">${r.avgAmt.toFixed(0)} avg</span>
						<span class="w-16 text-right font-mono text-[10px] text-muted-foreground">FNG {r.avgFng.toFixed(1)}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">EXTREME severity triggers typically occur at lowest FNG values · larger DCA amounts at higher severity reflects the deeper-discount opportunity</p>
		</section>
	{/if}

	{#if triggerCumulativeAmount}
		{@const tca = triggerCumulativeAmount}
		<section class="rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Cumulative DCA Deployed <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<p class="mb-2 text-[11px] text-muted-foreground">Running total of USDT deployed across all {tca.count} triggers · total ${tca.total.toLocaleString(undefined, {maximumFractionDigits: 0})}</p>
			<svg viewBox="0 0 {tca.W} {tca.H}" class="w-full" style="height:64px">
				<polyline points={tca.poly} fill="none" stroke="var(--ch-violet-strong)" stroke-width="1.5"/>
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>{tca.first}</span><span>← trigger timeline →</span><span>{tca.last}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Steep rises = burst of triggers in short period · flat stretches = quiet market with no DCA signals · slope = deployment velocity</p>
		</section>
	{/if}

	{#if triggerFngTimeline}
		{@const tft = triggerFngTimeline}
		<section class="rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Fear &amp; Greed at Each Trigger <ChartInfo metric="fearGreed" {lang} /></h2>
			<p class="mb-2 text-[11px] text-muted-foreground">FNG value recorded at each DCA trigger · avg {tft.avgFng.toFixed(1)} · {tft.count} triggers · dashed lines at 25 (fear) and 75 (greed)</p>
			<svg viewBox="0 0 {tft.W} {tft.H}" class="w-full" style="height:64px">
				<line x1={tft.PAD} y1={tft.fearY} x2={tft.W - tft.PAD} y2={tft.fearY} stroke="var(--ch-profit-light)" stroke-width="0.8" stroke-dasharray="3,2"/>
				<line x1={tft.PAD} y1={tft.greedY} x2={tft.W - tft.PAD} y2={tft.greedY} stroke="var(--ch-loss-light)" stroke-width="0.8" stroke-dasharray="3,2"/>
				<polyline points={tft.poly} fill="none" stroke="var(--ch-warn)" stroke-width="1.5"/>
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>{tft.first}</span><span>← trigger timeline →</span><span>{tft.last}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Triggers at low FNG (&lt;25) = best buy zones · FNG rising after trigger = market recovering · consistent low FNG = prolonged fear period</p>
		</section>
	{/if}

	{#if triggerKindTimeline}
		{@const tkt = triggerKindTimeline}
		<section class="rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Trigger Kind Mix by Month <ChartInfo metric="signalKind" {lang} /></h2>
			<p class="mb-2 text-[11px] text-muted-foreground">Monthly count of each DCA trigger kind · {tkt.rows.length} months · {tkt.kinds.join(', ')}</p>
			<div class="flex flex-col gap-1">
				{#each tkt.rows as row}
					<div class="flex items-center gap-2">
						<span class="w-12 shrink-0 font-mono text-[9px] text-muted-foreground">{row.ym}</span>
						<div class="flex h-4 flex-1 overflow-hidden rounded" style="min-width:0">
							{#each row.kinds as k}
								{#if k.count > 0}
									<div
										class="flex items-center justify-center overflow-hidden text-[8px] font-bold text-white"
										style="width:{(k.count / tkt.maxTotal) * 100}%;background:{k.color};min-width:0"
										title="{k.kind}: {k.count}"
									>{k.count > 2 ? k.kind[0] : ''}</div>
								{/if}
							{/each}
						</div>
						<span class="w-6 text-right font-mono text-[9px] text-muted-foreground">{row.kinds.reduce((s, k) => s + k.count, 0)}</span>
					</div>
				{/each}
			</div>
			<div class="mt-2 flex flex-wrap gap-3">
				{#each tkt.kinds as k}
					<span class="flex items-center gap-1 text-[9px]">
						<span class="inline-block h-2 w-2 rounded-sm" style="background:{tkt.KIND_COLORS[k] ?? 'var(--ch-axis)'}"></span>
						{k}
					</span>
				{/each}
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">FLASH = sharp drop · FAST = quick decline · SUSTAIN = prolonged weakness · CAPITUL = capitulation event · width = share of monthly total</p>
		</section>
	{/if}

	{#if triggerDowDistribution}
		<section class="rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Triggers by Day of Week <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<p class="mb-2 text-[11px] text-muted-foreground">How many DCA triggers fired on each day of week · reveals weekly seasonality in market stress events</p>
			<div class="flex items-end gap-2" style="height:64px">
				{#each triggerDowDistribution as d}
					<div class="flex flex-1 flex-col items-center gap-0.5" title="{d.label}: {d.count} ({(d.pct * 100).toFixed(0)}%)">
						<span class="font-mono text-[7px] text-muted-foreground">{d.count}</span>
						<div class="w-full rounded-sm" style="height:{d.barPct}%; background:var(--ch-violet); min-height:2px"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-around font-mono text-[9px] text-muted-foreground">
				{#each triggerDowDistribution as d}
					<span>{d.label}</span>
				{/each}
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Tall bars = market stress concentrated on certain weekdays · weekend spikes = crypto 24/7 volatility · flat distribution = no weekly bias</p>
		</section>
	{/if}

	{#if triggerAmountVsSeverity}
		{@const tas = triggerAmountVsSeverity}
		<section class="rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">DCA Amount vs Event Severity <ChartInfo metric="fearGreed" {lang} /></h2>
			<p class="mb-2 text-[11px] text-muted-foreground">Scatter of amount deployed (USDT) vs event severity score · coloured by trigger kind · higher severity → more deployed?</p>
			<svg viewBox="0 0 {tas.W} {tas.H}" class="w-full" style="height:90px">
				{#each tas.dots as d}
					<circle cx={d.cx} cy={d.cy} r="2.5" fill={d.color} title="{d.kind ?? ''} sev={d.sev.toFixed(1)} amt={d.amt.toFixed(0)} USDT"/>
				{/each}
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>Severity {tas.xMin.toFixed(1)}</span><span>← event severity →</span><span>{tas.xMax.toFixed(1)}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Rising trend = DCA strategy scales amount with severity · flat = fixed amount regardless of signal strength · clusters = severity tiers from the DCA config</p>
		</section>
	{/if}
	{#if dcaKindSequence}
		<section class="rounded-lg border border-border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">Signal Kind Transition Matrix <ChartInfo metric="signalKind" {lang} /></h2>
			<p class="mb-3 text-[11px] text-muted-foreground">How often each signal type is followed by another · row = current · column = next event</p>
			<div class="overflow-x-auto">
				<table class="w-full text-xs">
					<thead>
						<tr class="border-b border-border text-muted-foreground">
							<th class="pb-2 pr-3 text-left">From ↓ To →</th>
							{#each dcaKindSequence.kinds as k2}
								<th class="pb-2 pr-2 text-center">{k2}</th>
							{/each}
							<th class="pb-2 text-right text-muted-foreground">Total</th>
						</tr>
					</thead>
					<tbody>
						{#each dcaKindSequence.kinds as k1}
							{@const rowTotal = dcaKindSequence.rowTotals.get(k1) ?? 0}
							<tr class="border-b border-border/40 last:border-0">
								<td class="py-1.5 pr-3 font-mono font-medium">{k1}</td>
								{#each dcaKindSequence.kinds as k2}
									{@const count = dcaKindSequence.matrix.get(`${k1}→${k2}`) ?? 0}
									{@const pct = rowTotal > 0 ? count / rowTotal : 0}
									{@const alpha = Math.round(pct * 80)}
									<td class="py-1.5 pr-2 text-center font-mono" style="background:rgba(99,102,241,{pct.toFixed(2)}); color:{pct > 0.4 ? 'white' : 'inherit'}">
										{count > 0 ? count : '·'}
									</td>
								{/each}
								<td class="py-1.5 text-right font-mono text-muted-foreground">{rowTotal}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Dark cell = frequent transition · diagonal dominance = same type repeats · off-diagonal = regime changes between signal types</p>
		</section>
	{/if}
	{#if dcaTriggerStreaks}
		<section class="rounded-lg border border-border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">Same-Kind Trigger Streak Length <ChartInfo metric="streak" {lang} /></h2>
			<div class="space-y-1.5">
				{#each dcaTriggerStreaks as r}
					{@const KIND_COLORS: Record<string, string> = { FLASH: 'var(--ch-loss)', FAST: 'var(--ch-warn)', SUSTAIN: 'var(--ch-violet)', CAPITUL: 'var(--ch-violet-strong)' }}
					{@const color = KIND_COLORS[r.kind] ?? 'var(--ch-axis)'}
					<div class="flex items-center gap-2">
						<span class="w-20 text-right font-mono text-[10px]" style="color:{color}">{r.kind}</span>
						<div class="h-4 flex-1 overflow-hidden rounded-sm bg-muted">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{color}"></div>
						</div>
						<span class="w-20 text-right font-mono text-[10px] text-muted-foreground">avg {r.avg.toFixed(1)} · max {r.max}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Avg consecutive same-kind events before switching · high streak = regime clustering · low = rapid alternation · SUSTAIN streaks = prolonged fear environments</p>
		</section>
	{/if}
	{#if dcaAmountByFngBucket}
		<section class="rounded-xl border border-border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">Avg USDT Deployed by Fear &amp; Greed Level <ChartInfo metric="fearGreed" {lang} /></h2>
			<p class="mb-3 text-[10px] text-muted-foreground">Average DCA amount per trigger event, grouped by F&amp;G index range — shows which sentiment levels trigger larger deployments</p>
			<div class="space-y-2">
				{#each dcaAmountByFngBucket as b}
					{@const hue = Math.round((1 - b.lo / 100) * 240)}
					{@const color = b.count > 0 ? `hsl(${hue},70%,55%)` : 'rgba(100,100,100,0.3)'}
					<div class="flex items-center gap-2">
						<span class="w-24 truncate text-[10px] text-muted-foreground whitespace-pre-line leading-tight">{b.label}</span>
						<div class="h-4 flex-1 overflow-hidden rounded-sm bg-muted">
							<div class="h-full rounded-sm" style="width:{b.barPct}%; background:{color}"></div>
						</div>
						<span class="w-20 text-right font-mono text-[10px]" style="color:{color}">{b.count > 0 ? '$' + b.avg.toFixed(0) : '—'}</span>
						<span class="w-10 text-right font-mono text-[9px] text-muted-foreground">{b.count}×</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Blue = fear (more deployed) · green = greed · bar width = normalized avg USDT · count = trigger events in that F&amp;G range</p>
		</section>
	{/if}
	{#if dcaTriggerByKindHour}
		<section class="rounded-xl border border-border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">Trigger Hour Distribution by Kind <ChartInfo metric="distribution" {lang} /></h2>
			<p class="mb-3 text-[10px] text-muted-foreground">UTC hour-of-day frequency for each trigger kind — reveals if different signal types cluster at specific market sessions</p>
			<div class="space-y-4">
				{#each dcaTriggerByKindHour.kinds as k}
					<div>
						<div class="mb-1 flex items-center gap-2">
							<span class="text-[10px] font-semibold" style="color:{k.color}">{k.kind}</span>
							<span class="text-[9px] text-muted-foreground">peak UTC {dcaTriggerByKindHour.peakHours.find(p => p.kind === k.kind)?.peakH ?? '?'}h · n={k.total}</span>
						</div>
						<div class="flex h-8 items-end gap-px">
							{#each k.hours as h}
								<div class="flex-1 rounded-t-sm" style="height:{Math.max(2, h.barPct * 0.28)}px; background:{k.color}; opacity:{h.count > 0 ? 0.7 + h.barPct * 0.003 : 0.15}"></div>
							{/each}
						</div>
						<div class="mt-px flex justify-between font-mono text-[8px] text-muted-foreground">
							<span>00h</span><span>06h</span><span>12h</span><span>18h</span><span>23h</span>
						</div>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Each bar = one UTC hour · height = relative frequency · peaks reveal session timing (Asian 00-08h, EU 08-16h, US 14-22h)</p>
		</section>
	{/if}
	{#if dcaWeeklyAmountMovingAvg}
		<section class="rounded-xl border border-border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">4-Week Rolling Avg USDT Deployed <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<p class="mb-2 text-[10px] text-muted-foreground">Smoothed weekly DCA spend using 4-week moving average · latest ${dcaWeeklyAmountMovingAvg.latest.toFixed(0)} · overall avg ${dcaWeeklyAmountMovingAvg.overall.toFixed(0)} · {dcaWeeklyAmountMovingAvg.count} data points</p>
			<svg viewBox="0 0 {dcaWeeklyAmountMovingAvg.W} {dcaWeeklyAmountMovingAvg.H}" class="w-full">
				<polyline points={dcaWeeklyAmountMovingAvg.polyline} fill="none" stroke="var(--ch-violet-strong)" stroke-width="2"/>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Rising trend = increasing weekly DCA intensity · falling = reduced deployment · smoothed to reduce week-to-week noise · max weekly avg ${dcaWeeklyAmountMovingAvg.mx.toFixed(0)}</p>
		</section>
	{/if}

	{#if dcaCumulativeByKind}
		<section class="rounded-xl border border-border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">Cumulative USDT Deployed by Trigger Kind <ChartInfo metric="signalKind" {lang} /></h2>
			<p class="mb-2 text-[10px] text-muted-foreground">Each line = running cumulative sum of USDT deployed for that trigger kind over time · steeper slope = more aggressive deployment of that type</p>
			<svg viewBox="0 0 {dcaCumulativeByKind.W} {dcaCumulativeByKind.H}" class="w-full">
				{#each dcaCumulativeByKind.lines as line}
					<polyline points={line.poly} fill="none" stroke={line.color} stroke-width="1.8"/>
				{/each}
			</svg>
			<div class="mt-2 flex flex-wrap gap-3 text-[9px] text-muted-foreground">
				{#each dcaCumulativeByKind.lines as line}
					<span><span style="color:{line.color}">●</span> {line.kind} ${line.final.toFixed(0)}</span>
				{/each}
			</div>
			<p class="mt-1 text-[9px] text-muted-foreground">Total max ${dcaCumulativeByKind.maxTotal.toFixed(0)} · dominant kind = {dcaCumulativeByKind.lines[0]?.kind} · diverging lines = kinds used at different intensities over time</p>
		</section>
	{/if}

	{#if dcaFngBucketTriggerCount}
		<section class="rounded-xl border border-border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">Trigger Count by Fear &amp; Greed Bucket <ChartInfo metric="fearGreed" {lang} /></h2>
			<p class="mb-3 text-[10px] text-muted-foreground">How many DCA triggers fired in each market sentiment zone · reveals whether the system skews toward fear-driven or balanced deployment</p>
			<div class="space-y-2">
				{#each dcaFngBucketTriggerCount.buckets as b}
					<div class="flex items-center gap-2 text-xs">
						<span class="w-28 shrink-0 text-muted-foreground">{b.label}</span>
						<div class="relative h-5 flex-1 overflow-hidden rounded bg-muted/30">
							<div class="h-full rounded" style="width:{(b.count / dcaFngBucketTriggerCount.maxCount * 100).toFixed(1)}%; background:{b.color}"></div>
						</div>
						<span class="w-10 text-right font-mono">{b.count}</span>
						<span class="w-12 text-right text-[9px] text-muted-foreground">{(b.count / dcaFngBucketTriggerCount.total * 100).toFixed(0)}%</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">{dcaFngBucketTriggerCount.total} total triggers · heavily skewed toward fear = contrarian DCA working as intended · balanced = sentiment-agnostic system</p>
		</section>
	{/if}

	{#if dcaSeverityTrendTimeline}
		<section class="rounded-xl border border-border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">Trigger Severity Trend (5-Trigger Rolling Avg) <ChartInfo metric="fearGreed" {lang} /></h2>
			<p class="mb-2 text-[10px] text-muted-foreground">Smoothed severity score over time (mild=1, moderate=2, severe=3, extreme=4) · rising = conditions worsening · falling = recovery · latest {dcaSeverityTrendTimeline.latest.toFixed(2)}</p>
			<svg viewBox="0 0 {dcaSeverityTrendTimeline.W} {dcaSeverityTrendTimeline.H}" class="w-full">
				<line x1="0" y1={dcaSeverityTrendTimeline.avgY} x2={dcaSeverityTrendTimeline.W} y2={dcaSeverityTrendTimeline.avgY} stroke="var(--ch-warn-light)" stroke-width="1" stroke-dasharray="4,3"/>
				<polyline points={dcaSeverityTrendTimeline.polyline} fill="none" stroke="var(--ch-loss)" stroke-width="2"/>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">{dcaSeverityTrendTimeline.count} data points · avg severity {dcaSeverityTrendTimeline.avg.toFixed(2)} · trend {dcaSeverityTrendTimeline.trend > 0.2 ? '↑ escalating' : dcaSeverityTrendTimeline.trend < -0.2 ? '↓ de-escalating' : '→ stable'} · yellow dashed = mean</p>
		</section>
	{/if}

	{#if dcaMonthlyTriggerIntensity}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">Monthly DCA Trigger Intensity</h3>
			<p class="mb-2 text-[10px] text-muted-foreground">Each bar = trigger count × avg amount for that month · measures how "heavy" DCA deployment was · tall blue = high volume + large size · tall red = extreme concentration</p>
			<svg viewBox="0 0 {dcaMonthlyTriggerIntensity.W} {dcaMonthlyTriggerIntensity.H}" class="w-full">
				{#each dcaMonthlyTriggerIntensity.bars as b}
					<rect x={b.x} y={b.y} width={dcaMonthlyTriggerIntensity.barW} height={b.h} fill={b.color}/>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">{dcaMonthlyTriggerIntensity.total} months · intensity = trigger_count × avg_amount_usdt · blue = moderate · red = peak deployment month · useful for sizing capital reserves</p>
		</section>
	{/if}

	{#if dcaKindAmountRange}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">Amount Range by DCA Kind</h3>
			<p class="mb-2 text-[10px] text-muted-foreground">Min / median / max amount per trigger kind · wide spread = inconsistent sizing · narrow = disciplined fixed-size DCA</p>
			<div class="space-y-2">
				{#each dcaKindAmountRange.rows as row}
					{@const color = dcaKindAmountRange.KIND_COL[row.kind] ?? 'var(--ch-axis)'}
					{@const mnPct = (row.mn / dcaKindAmountRange.globalMax * 100).toFixed(1)}
					{@const mxPct = (row.mx / dcaKindAmountRange.globalMax * 100).toFixed(1)}
					{@const medPct = (row.median / dcaKindAmountRange.globalMax * 100).toFixed(1)}
					<div class="flex items-center gap-2 text-[10px]">
						<span class="w-20 truncate font-mono" style="color:{color}">{row.kind}</span>
						<div class="relative h-3 flex-1 rounded bg-muted/30">
							<div class="absolute h-full rounded opacity-30" style="left:{mnPct}%; width:{(Number(mxPct) - Number(mnPct)).toFixed(1)}%; background:{color}"></div>
							<div class="absolute h-full w-0.5 rounded" style="left:{medPct}%; background:{color}"></div>
						</div>
						<span class="w-28 text-right text-[9px] text-muted-foreground">{row.mn.toFixed(0)}–{row.median.toFixed(0)}–{row.mx.toFixed(0)} USDT</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Bar = range min→max · tick = median · wide spread per kind = volatile sizing · n per kind shown in legend order</p>
		</section>
	{/if}

	{#if dcaDowAmountProfile}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">DCA Amount by Day of Week</h3>
			<p class="mb-2 text-[10px] text-muted-foreground">Total USDT deployed and trigger count per day of week · reveals if DCA system is skewed toward certain days (e.g. weekend fear spikes)</p>
			<div class="flex items-end gap-1" style="height:72px">
				{#each dcaDowAmountProfile.rows as row}
					{@const hPct = (row.total / dcaDowAmountProfile.maxTotal * 100).toFixed(0)}
					{@const color = row.count > 0 ? `rgba(99,102,241,${(0.3 + (row.total / dcaDowAmountProfile.maxTotal) * 0.6).toFixed(2)})` : 'var(--ch-axis-faint)'}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<div class="w-full rounded-t" style="height:{hPct}%; background:{color}; min-height:{row.count > 0 ? 2 : 0}px"></div>
						<span class="text-[8px] text-muted-foreground">{row.label}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Bar height = total USDT · darker = higher volume · weekend vs weekday patterns reveal sentiment cycle alignment</p>
		</section>
	{/if}

	{#if dcaHourlyTriggerProfile}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Trigger Frequency by Hour (UTC)</h3>
			<svg viewBox="0 0 {dcaHourlyTriggerProfile.W} {dcaHourlyTriggerProfile.H}" class="w-full" style="height:80px">
				{#each dcaHourlyTriggerProfile.bars as bar}
					<rect x={bar.x} y={bar.y} width={dcaHourlyTriggerProfile.BAR_W} height={bar.barH} rx="1" fill={bar.color}/>
					{#if bar.hour % 6 === 0}
						<text x={bar.x + dcaHourlyTriggerProfile.BAR_W / 2} y={dcaHourlyTriggerProfile.H - 1} text-anchor="middle" font-size="7" fill="var(--ch-axis)">{bar.hour}h</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">{dcaHourlyTriggerProfile.total} triggers · peak hour: {dcaHourlyTriggerProfile.peakHour}:00 UTC · red = high activity · blue = low activity</p>
		</section>
	{/if}

	{#if dcaAmountVsFngScatter}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">DCA Amount vs Fear &amp; Greed Index</h3>
			<svg viewBox="0 0 {dcaAmountVsFngScatter.W} {dcaAmountVsFngScatter.H}" class="w-full" style="height:130px">
				<line x1={dcaAmountVsFngScatter.W * 30 / 100} y1="0" x2={dcaAmountVsFngScatter.W * 30 / 100} y2={dcaAmountVsFngScatter.H} stroke="var(--ch-profit-light)" stroke-width="1" stroke-dasharray="3,3"/>
				<line x1={dcaAmountVsFngScatter.W * 70 / 100} y1="0" x2={dcaAmountVsFngScatter.W * 70 / 100} y2={dcaAmountVsFngScatter.H} stroke="var(--ch-loss-light)" stroke-width="1" stroke-dasharray="3,3"/>
				{#each dcaAmountVsFngScatter.dots as d}
					<circle cx={d.cx} cy={d.cy} r="2.5" fill={d.color} opacity="0.75"/>
				{/each}
				<text x="4" y="10" font-size="7" fill="var(--ch-profit)">Fear</text>
				<text x={dcaAmountVsFngScatter.W - 30} y="10" font-size="7" fill="var(--ch-loss)">Greed</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">{dcaAmountVsFngScatter.total} triggers · fear zone avg: {dcaAmountVsFngScatter.avgAmtFear ?? 'n/a'} USDT · greed zone avg: {dcaAmountVsFngScatter.avgAmtGreed ?? 'n/a'} USDT · FNG [{dcaAmountVsFngScatter.fMin}–{dcaAmountVsFngScatter.fMax}]</p>
		</section>
	{/if}

	{#if dcaSeverityAmountSummary}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">DCA Amount by Severity Level</h3>
			<div class="space-y-2">
				{#each dcaSeverityAmountSummary.rows as row}
					{@const color = dcaSeverityAmountSummary.SEV_COL[row.sev] ?? 'var(--ch-axis)'}
					{@const avgPct = (row.avg / dcaSeverityAmountSummary.maxAvg * 100).toFixed(1)}
					<div class="flex items-center gap-2">
						<span class="w-14 shrink-0 capitalize text-[9px]" style="color:{color}">{row.sev}</span>
						<div class="relative flex-1 h-4 rounded bg-muted/20">
							<div class="absolute left-0 top-0 h-full rounded" style="width:{avgPct}%; background:{color}; opacity:0.5"></div>
							<div class="absolute left-0 top-0 h-full rounded" style="width:{(row.p25 / dcaSeverityAmountSummary.maxAvg * 100).toFixed(1)}%; background:transparent"></div>
						</div>
						<span class="w-16 text-right font-mono text-[9px]" style="color:{color}">{row.avg.toFixed(0)} USDT</span>
						<span class="w-20 text-right text-[9px] text-muted-foreground">P25–P75: {row.p25.toFixed(0)}–{row.p75.toFixed(0)}</span>
						<span class="w-8 text-right text-[9px] text-muted-foreground">n={row.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Avg DCA amount per trigger severity · higher severity = larger position · P25–P75 = interquartile range</p>
		</section>
	{/if}

	{#if dcaCumulativeSpend}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Cumulative DCA Spend Over Time</h3>
			<svg viewBox="0 0 {dcaCumulativeSpend.W} {dcaCumulativeSpend.H}" class="w-full" style="height:70px">
				<polyline points={dcaCumulativeSpend.polyline} fill="none" stroke="var(--ch-violet-strong)" stroke-width="2" stroke-linejoin="round"/>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">{dcaCumulativeSpend.count} triggers · total deployed: ${dcaCumulativeSpend.total} USDT · staircase = each DCA event adds to running total</p>
		</section>
	{/if}

	{#if dcaKindBreakdown}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">DCA Trigger Kind Breakdown</h3>
			<div class="space-y-1.5">
				{#each dcaKindBreakdown.rows as row, i}
					{@const color = dcaKindBreakdown.COLORS[i % dcaKindBreakdown.COLORS.length]}
					<div class="flex items-center gap-2">
						<span class="w-24 truncate text-right text-[9px] text-muted-foreground">{row.kind}</span>
						<div class="flex-1 h-3 rounded bg-muted/20 overflow-hidden">
							<div class="h-full rounded" style="width:{(row.count / dcaKindBreakdown.maxCount * 100).toFixed(1)}%; background:{color}"></div>
						</div>
						<span class="w-10 text-right font-mono text-[10px] text-muted-foreground">{row.count}</span>
						<span class="w-20 text-right text-[9px] text-muted-foreground">${row.avg.toFixed(0)} avg</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Trigger count per DCA kind · bar width = relative frequency · avg = mean USDT deployed per trigger of that kind</p>
		</section>
	{/if}

	{#if dcaWeeklySpendProfile}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg DCA Amount by Day of Week</h3>
			<svg viewBox="0 0 {dcaWeeklySpendProfile.W} {dcaWeeklySpendProfile.H}" class="w-full" style="height:70px">
				{#each dcaWeeklySpendProfile.rows as row, i}
					{@const x = dcaWeeklySpendProfile.PAD + i * ((dcaWeeklySpendProfile.W - dcaWeeklySpendProfile.PAD * 2) / 7)}
					{@const barH = Math.max(1, (row.avg / dcaWeeklySpendProfile.maxAvg) * (dcaWeeklySpendProfile.H - dcaWeeklySpendProfile.PAD * 2 - 10))}
					{@const color = row.count > 0 ? 'var(--ch-violet)' : 'var(--ch-axis-faint)'}
					<rect x={x} y={dcaWeeklySpendProfile.H - 10 - barH} width={dcaWeeklySpendProfile.barW} height={barH} rx="1" fill={color}/>
					<text x={x + dcaWeeklySpendProfile.barW / 2} y={dcaWeeklySpendProfile.H - 1} text-anchor="middle" font-size="8" fill="var(--ch-axis)">{row.day}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg USDT deployed per DCA trigger by day of week · taller = larger avg position on that day · identifies weekly rhythm in trigger sizing</p>
		</section>
	{/if}

	{#if dcaMonthlySpend}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Monthly DCA Spend (USDT)</h3>
			<svg viewBox="0 0 {dcaMonthlySpend.W} {dcaMonthlySpend.H}" class="w-full" style="height:70px">
				{#each dcaMonthlySpend.rows as row, i}
					{@const x = dcaMonthlySpend.PAD + i * ((dcaMonthlySpend.W - dcaMonthlySpend.PAD * 2) / dcaMonthlySpend.rows.length)}
					{@const barH = Math.max(2, (row.total / dcaMonthlySpend.maxTotal) * (dcaMonthlySpend.H - dcaMonthlySpend.PAD * 2 - 10))}
					{@const color = row.total === dcaMonthlySpend.maxTotal ? 'var(--ch-warn)' : 'var(--ch-violet)'}
					<rect x={x} y={dcaMonthlySpend.H - 10 - barH} width={dcaMonthlySpend.barW} height={barH} rx="1" fill={color}/>
					<text x={x + dcaMonthlySpend.barW / 2} y={dcaMonthlySpend.H - 1} text-anchor="middle" font-size="6.5" fill="var(--ch-axis)">{row.label}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Total USDT deployed per month · yellow = highest spend month · cumulative last 12 months: ${dcaMonthlySpend.grandTotal} USDT</p>
		</section>
	{/if}

	{#if dcaTriggerHourOfDay}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">DCA Triggers by Hour of Day (UTC)</h3>
			<svg viewBox="0 0 {dcaTriggerHourOfDay.W} {dcaTriggerHourOfDay.H}" class="w-full" style="height:70px">
				{#each dcaTriggerHourOfDay.counts as b}
					{@const x = dcaTriggerHourOfDay.PAD + b.h * (dcaTriggerHourOfDay.barW + 1)}
					{@const barH = Math.max(1, (b.count / dcaTriggerHourOfDay.maxCount) * (dcaTriggerHourOfDay.H - dcaTriggerHourOfDay.PAD * 2 - 10))}
					{@const color = b.count === dcaTriggerHourOfDay.maxCount ? 'var(--ch-warn)' : 'var(--ch-violet)'}
					<rect x={x} y={dcaTriggerHourOfDay.H - 10 - barH} width={dcaTriggerHourOfDay.barW} height={barH} rx="1" fill={color}/>
					{#if b.h % 6 === 0}
						<text x={x + dcaTriggerHourOfDay.barW / 2} y={dcaTriggerHourOfDay.H - 1} text-anchor="middle" font-size="7" fill="var(--ch-axis)">{b.h}h</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">DCA trigger count per UTC hour · yellow = busiest hour · reveals when scheduled and event-driven buys cluster during the day</p>
		</section>
	{/if}

	{#if dcaFngAmountDotPlot}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">DCA Amount vs Fear &amp; Greed Score</h3>
			<svg viewBox="0 0 {dcaFngAmountDotPlot.W} {dcaFngAmountDotPlot.H}" class="w-full" style="height:110px">
				{#each [25, 50, 75] as lvl}
					<line x1={dcaFngAmountDotPlot.toX(lvl)} y1={dcaFngAmountDotPlot.PAD} x2={dcaFngAmountDotPlot.toX(lvl)} y2={dcaFngAmountDotPlot.H - dcaFngAmountDotPlot.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.6" stroke-dasharray="3,2"/>
					<text x={dcaFngAmountDotPlot.toX(lvl)} y={dcaFngAmountDotPlot.H - 4} text-anchor="middle" font-size="6.5" fill="var(--ch-axis-muted)">{lvl}</text>
				{/each}
				{#each dcaFngAmountDotPlot.pts as p}
					<circle cx={dcaFngAmountDotPlot.toX(p.fng)} cy={dcaFngAmountDotPlot.toY(p.amount)} r="2.5" fill={dcaFngAmountDotPlot.color(p.kind)}/>
				{/each}
				<text x={dcaFngAmountDotPlot.PAD - 2} y={dcaFngAmountDotPlot.PAD + 4} text-anchor="end" font-size="6.5" fill="var(--ch-axis-muted)">${dcaFngAmountDotPlot.maxAmt.toFixed(0)}</text>
			</svg>
			<div class="mt-1 flex justify-between text-[9px] text-muted-foreground">
				<span>FNG 0 (extreme fear)</span>
				<span>x=FNG · y=USDT deployed · red=event DCA · indigo=scheduled</span>
				<span>FNG 100 (greed)</span>
			</div>
		</section>
	{/if}

	{#if dcaFngScoreTimeline}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Fear &amp; Greed Score at DCA Triggers</h3>
			<svg viewBox="0 0 {dcaFngScoreTimeline.W} {dcaFngScoreTimeline.H}" class="w-full" style="height:100px">
				{#each [0, 25, 45, 55, 75, 100] as zone, zi}
					{#if zi < 5}
						{@const top = dcaFngScoreTimeline.y([100,75,55,45,25][zi])}
						{@const bot = dcaFngScoreTimeline.y([75,55,45,25,0][zi])}
						{@const col = dcaFngScoreTimeline.zoneColor([87,65,50,35,12][zi])}
						<rect x={dcaFngScoreTimeline.PAD} y={top} width={dcaFngScoreTimeline.W - dcaFngScoreTimeline.PAD * 2} height={bot - top} fill={col}/>
					{/if}
				{/each}
				{#each [25,50,75] as lvl}
					<line x1={dcaFngScoreTimeline.PAD} y1={dcaFngScoreTimeline.y(lvl)} x2={dcaFngScoreTimeline.W - dcaFngScoreTimeline.PAD} y2={dcaFngScoreTimeline.y(lvl)} stroke="var(--ch-axis-faint)" stroke-width="0.5"/>
					<text x={dcaFngScoreTimeline.PAD - 2} y={dcaFngScoreTimeline.y(lvl) + 3} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{lvl}</text>
				{/each}
				<polyline points={dcaFngScoreTimeline.polyline} fill="none" stroke="var(--ch-violet-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				{#each dcaFngScoreTimeline.pts as p}
					<circle cx={dcaFngScoreTimeline.x(p.ts)} cy={dcaFngScoreTimeline.y(p.fng)} r="2" fill={p.fng <= 25 ? 'var(--ch-loss-strong)' : p.fng >= 75 ? 'var(--ch-violet-strong)' : 'var(--ch-axis)'}/>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">FNG score at each DCA trigger over time · red dots = extreme fear (&lt;25) · indigo = greed (&gt;75) · shows emotional context of each buy</p>
		</section>
	{/if}

	{#if dcaSeverityTimeline}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Trigger Severity Timeline</h3>
			<svg viewBox="0 0 {dcaSeverityTimeline.W} {dcaSeverityTimeline.H}" class="w-full" style="height:90px">
				<polyline points={dcaSeverityTimeline.polyline} fill="none" stroke="var(--ch-axis-muted)" stroke-width="1" stroke-linejoin="round"/>
				{#each dcaSeverityTimeline.pts as p}
					<circle cx={dcaSeverityTimeline.toX(p.ts)} cy={dcaSeverityTimeline.toY(p.sev)} r="3" fill={dcaSeverityTimeline.kindColor(p.kind)}/>
				{/each}
				<text x={dcaSeverityTimeline.PAD} y={dcaSeverityTimeline.H - 2} font-size="6.5" fill="var(--ch-axis-muted)">oldest</text>
				<text x={dcaSeverityTimeline.W - dcaSeverityTimeline.PAD} y={dcaSeverityTimeline.H - 2} text-anchor="end" font-size="6.5" fill="var(--ch-axis-muted)">newest</text>
			</svg>
			<div class="mt-1 flex gap-3 text-[9px] text-muted-foreground">
				<span><span class="inline-block w-2 h-2 rounded-full bg-red-400 mr-1"></span>FLASH</span>
				<span><span class="inline-block w-2 h-2 rounded-full bg-orange-400 mr-1"></span>CAPITUL</span>
				<span><span class="inline-block w-2 h-2 rounded-full bg-indigo-400 mr-1"></span>SUSTAIN</span>
				<span>· y-axis = severity score · higher = more extreme signal</span>
			</div>
		</section>
	{/if}

	{#if dcaInterTriggerGap}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Inter-Trigger Gap Distribution ({dcaInterTriggerGap.total} gaps · median {dcaInterTriggerGap.medGap}h)</h3>
			<svg viewBox="0 0 {dcaInterTriggerGap.W} {dcaInterTriggerGap.H}" class="w-full" style="height:80px">
				{#each dcaInterTriggerGap.rects as rect}
					{@const y = dcaInterTriggerGap.H - dcaInterTriggerGap.PAD - rect.h}
					<rect x={rect.x} y={y} width={dcaInterTriggerGap.barW} height={rect.h} fill={rect.color} rx="1"/>
					{#if rect.cnt > 0}
						<text x={rect.x + dcaInterTriggerGap.barW / 2} y={y - 2} text-anchor="middle" font-size="6.5" fill="var(--ch-axis-strong)">{rect.cnt}</text>
					{/if}
					<text x={rect.x + dcaInterTriggerGap.barW / 2} y={dcaInterTriggerGap.H - 2} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{rect.label}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Hours between consecutive DCA triggers · red=&lt;1× bin = very rapid · shows clustering vs spacing of DCA events · bin size ≈{dcaInterTriggerGap.binSize}h</p>
		</section>
	{/if}

	{#if dcaKindAmountTimeline}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">DCA Deployed Amount Timeline by Kind</h3>
			<svg viewBox="0 0 {dcaKindAmountTimeline.W} {dcaKindAmountTimeline.H}" class="w-full" style="height:85px">
				{#each [0.25, 0.5, 0.75, 1] as lvl}
					<line x1={dcaKindAmountTimeline.PAD} y1={dcaKindAmountTimeline.toY(Number(dcaKindAmountTimeline.maxAmt) * lvl)} x2={dcaKindAmountTimeline.W - dcaKindAmountTimeline.PAD} y2={dcaKindAmountTimeline.toY(Number(dcaKindAmountTimeline.maxAmt) * lvl)} stroke="var(--ch-axis-faint)" stroke-width="0.5"/>
				{/each}
				{#each dcaKindAmountTimeline.pts as p}
					<circle cx={dcaKindAmountTimeline.toX(p.ts)} cy={dcaKindAmountTimeline.toY(p.amount)} r="3" fill={dcaKindAmountTimeline.kindColor(p.kind)}/>
				{/each}
				<text x={dcaKindAmountTimeline.PAD} y={dcaKindAmountTimeline.H - 2} font-size="6.5" fill="var(--ch-axis-muted)">oldest</text>
				<text x={dcaKindAmountTimeline.W - dcaKindAmountTimeline.PAD} y={dcaKindAmountTimeline.H - 2} text-anchor="end" font-size="6.5" fill="var(--ch-axis-muted)">newest</text>
				<text x={dcaKindAmountTimeline.PAD - 2} y={dcaKindAmountTimeline.PAD + 4} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">${dcaKindAmountTimeline.maxAmt}</text>
			</svg>
			<div class="mt-1 flex gap-3 text-[9px] text-muted-foreground">
				<span><span class="inline-block w-2 h-2 rounded-full bg-indigo-400 mr-1"></span>SCHEDULED</span>
				<span><span class="inline-block w-2 h-2 rounded-full bg-red-400 mr-1"></span>EVENT</span>
				<span>· y=USDT deployed · reveals if event-driven buys are larger or smaller than scheduled ones</span>
			</div>
		</section>
	{/if}

	{#if dcaAssetAllocationByKind}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">USDT Deployed by Asset × Kind</h3>
			<div class="space-y-1.5">
				{#each dcaAssetAllocationByKind.rows as row}
					<div class="flex items-center gap-2">
						<span class="w-10 text-right text-[9px] font-mono text-muted-foreground">{row.asset}</span>
						<div class="flex flex-1 h-3 rounded overflow-hidden bg-muted/10">
							{#each row.byKind as k}
								{@const w = (k.amt / dcaAssetAllocationByKind.maxTotal * 100).toFixed(1)}
								<div class="h-full" style="width:{w}%; background:{dcaAssetAllocationByKind.colors[k.kind] ?? 'var(--ch-axis-muted)'}"></div>
							{/each}
						</div>
						<span class="w-14 text-right font-mono text-[9px] text-muted-foreground">${row.total.toFixed(0)}</span>
					</div>
				{/each}
			</div>
			<div class="mt-2 flex gap-3 text-[9px] text-muted-foreground">
				{#each dcaAssetAllocationByKind.usedKinds as k}
					<span style="color:{dcaAssetAllocationByKind.colors[k]}">■ {k}</span>
				{/each}
				<span>· total USDT deployed per asset sorted by volume</span>
			</div>
		</section>
	{/if}
	{#if dcaMonthlyAssetSpend}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Monthly USDT Spend by Asset (top {dcaMonthlyAssetSpend.topAssets.length})</h3>
			<svg viewBox="0 0 {dcaMonthlyAssetSpend.W} {dcaMonthlyAssetSpend.H}" class="w-full" style="height:72px">
				{#each dcaMonthlyAssetSpend.rows as row, i}
					{@const x = dcaMonthlyAssetSpend.PAD + i * (dcaMonthlyAssetSpend.barW + 2)}
					{@const barH = dcaMonthlyAssetSpend.toH(row.total)}
					{@const y0 = dcaMonthlyAssetSpend.H - dcaMonthlyAssetSpend.PAD}
					{#each row.segs as seg, si}
						{@const segH = dcaMonthlyAssetSpend.toH(seg.amt)}
						{@const segY = y0 - row.segs.slice(0, si + 1).reduce((s, e) => s + dcaMonthlyAssetSpend.toH(e.amt), 0)}
						{#if seg.amt > 0}
							<rect {x} y={segY} width={dcaMonthlyAssetSpend.barW} height={segH} rx="1" fill={seg.color}/>
						{/if}
					{/each}
					<text x={x + dcaMonthlyAssetSpend.barW / 2} y={dcaMonthlyAssetSpend.H - 1} text-anchor="middle" font-size="6.5" fill="var(--ch-axis)">{row.mo}</text>
				{/each}
			</svg>
			<div class="mt-1 flex flex-wrap gap-3 text-[9px] text-muted-foreground">
				{#each dcaMonthlyAssetSpend.topAssets as a, i}
					<span style="color:{dcaMonthlyAssetSpend.aColors[i]}">■ {a}</span>
				{/each}
				<span>· stacked USDT spend per month · reveals asset allocation shift over time</span>
			</div>
		</section>
	{/if}
	{#if dcaTriggerCountByDow}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">DCA Triggers by Day of Week (UTC)</h3>
			<svg viewBox="0 0 {dcaTriggerCountByDow.W} {dcaTriggerCountByDow.H}" class="w-full" style="height:65px">
				{#each dcaTriggerCountByDow.rows as row, i}
					{@const x = dcaTriggerCountByDow.PAD + i * (dcaTriggerCountByDow.barW + 2)}
					{@const bh = Math.max(2, (row.count / dcaTriggerCountByDow.maxCount) * (dcaTriggerCountByDow.H - dcaTriggerCountByDow.PAD * 2 - 10))}
					{@const y = dcaTriggerCountByDow.H - 10 - bh}
					<rect {x} {y} width={dcaTriggerCountByDow.barW} height={bh} rx="1" fill="var(--ch-violet)"/>
					<text x={x + dcaTriggerCountByDow.barW / 2} y={dcaTriggerCountByDow.H - 1} text-anchor="middle" font-size="7" fill="var(--ch-axis)">{row.label}</text>
					{#if row.count > 0}
						<text x={x + dcaTriggerCountByDow.barW / 2} y={y - 2} text-anchor="middle" font-size="6" fill="var(--ch-axis)">{row.count}</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">DCA trigger count per weekday (UTC) · reveals whether scheduled and event triggers cluster on specific days · weekday spikes may indicate event-driven patterns</p>
		</section>
	{/if}
	{#if dcaCumSpendByAsset}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Cumulative USDT Spend by Asset</h3>
			<svg viewBox="0 0 {dcaCumSpendByAsset.W} {dcaCumSpendByAsset.H}" class="w-full" style="height:85px">
				{#each dcaCumSpendByAsset.lines as line}
					{#if line.poly}
						<polyline points={line.poly} fill="none" stroke={line.color} stroke-width="1.5" stroke-linejoin="round"/>
					{/if}
				{/each}
				<text x={dcaCumSpendByAsset.PAD} y={dcaCumSpendByAsset.PAD + 4} font-size="6.5" fill="var(--ch-axis-muted)">${dcaCumSpendByAsset.maxCum}</text>
				<text x={dcaCumSpendByAsset.W - dcaCumSpendByAsset.PAD} y={dcaCumSpendByAsset.H - 2} text-anchor="end" font-size="6.5" fill="var(--ch-axis-muted)">trigger →</text>
			</svg>
			<div class="mt-1 flex flex-wrap gap-3 text-[9px]">
				{#each dcaCumSpendByAsset.lines as line}
					<span style="color:{line.color}">■ {line.asset} ${line.final}</span>
				{/each}
			</div>
			<p class="mt-1 text-[9px] text-muted-foreground">Running cumulative USDT deployed per asset across all DCA triggers · steeper slope = faster capital deployment · total shown per asset</p>
		</section>
	{/if}
	{#if dcaAvgAmountByKindTrend}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg DCA Amount by Kind Over Time</h3>
			<svg viewBox="0 0 {dcaAvgAmountByKindTrend.W} {dcaAvgAmountByKindTrend.H}" class="w-full" style="height:80px">
				{#each dcaAvgAmountByKindTrend.polylines as line}
					<polyline points={line.poly} fill="none" stroke={line.color} stroke-width="1.5" stroke-linejoin="round"/>
				{/each}
				{#each dcaAvgAmountByKindTrend.allMonths as mo, i}
					{#if i % Math.max(1, Math.floor(dcaAvgAmountByKindTrend.allMonths.length / 5)) === 0}
						{@const x = dcaAvgAmountByKindTrend.PAD + (i / Math.max(dcaAvgAmountByKindTrend.allMonths.length - 1, 1)) * (dcaAvgAmountByKindTrend.W - dcaAvgAmountByKindTrend.PAD * 2)}
						<text {x} y={dcaAvgAmountByKindTrend.H - 1} text-anchor="middle" font-size="6" fill="var(--ch-axis-muted)">{mo.slice(5)}</text>
					{/if}
				{/each}
				<text x={dcaAvgAmountByKindTrend.PAD} y={dcaAvgAmountByKindTrend.PAD + 5} font-size="6.5" fill="var(--ch-axis-muted)">${dcaAvgAmountByKindTrend.maxAvg}</text>
			</svg>
			<div class="mt-1 flex flex-wrap gap-3 text-[9px]">
				{#each dcaAvgAmountByKindTrend.polylines as line}
					<span style="color:{line.color}">■ {line.kind}</span>
				{/each}
				<span class="text-muted-foreground">· avg USDT per trigger event by month</span>
			</div>
			<p class="mt-1 text-[9px] text-muted-foreground">Monthly avg USDT amount per DCA kind · rising = larger buys over time · divergence = regime shift between buy types</p>
		</section>
	{/if}
	{#if dcaTriggerHourDistribution}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">DCA Trigger Count by UTC Hour</h3>
			<svg viewBox="0 0 {dcaTriggerHourDistribution.W} {dcaTriggerHourDistribution.H}" class="w-full" style="height:60px">
				{#each dcaTriggerHourDistribution.buckets as b}
					{@const x = dcaTriggerHourDistribution.PAD + b.h * (dcaTriggerHourDistribution.barW + 1)}
					{@const bh = Math.max(1.5, (b.count / dcaTriggerHourDistribution.maxCount) * (dcaTriggerHourDistribution.H - dcaTriggerHourDistribution.PAD * 2 - 8))}
					{@const alpha = 0.3 + (b.count / dcaTriggerHourDistribution.maxCount) * 0.55}
					<rect {x} y={dcaTriggerHourDistribution.H - dcaTriggerHourDistribution.PAD - 8 - bh} width={dcaTriggerHourDistribution.barW} height={bh} rx="1" fill="rgba(99,102,241,{alpha})"/>
					{#if b.h % 6 === 0}
						<text x={x} y={dcaTriggerHourDistribution.H - 1} font-size="5.5" fill="var(--ch-axis-muted)">{String(b.h).padStart(2,'0')}h</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Number of DCA trigger events per UTC hour · darker = more triggers · reveals intraday timing patterns in automated DCA execution</p>
		</section>
	{/if}

	{#if dcaAvgFngByMonth}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Fear &amp; Greed Index by Month</h3>
			<svg viewBox="0 0 {dcaAvgFngByMonth.W} {dcaAvgFngByMonth.H}" class="w-full" style="height:72px">
				{#if dcaAvgFngByMonth.fearY >= dcaAvgFngByMonth.PAD && dcaAvgFngByMonth.fearY <= dcaAvgFngByMonth.H - dcaAvgFngByMonth.PAD}
					<line x1={dcaAvgFngByMonth.PAD} y1={dcaAvgFngByMonth.fearY} x2={dcaAvgFngByMonth.W - dcaAvgFngByMonth.PAD} y2={dcaAvgFngByMonth.fearY} stroke="var(--ch-loss-light)" stroke-width="0.7" stroke-dasharray="3,2"/>
					<text x={dcaAvgFngByMonth.W - dcaAvgFngByMonth.PAD + 1} y={dcaAvgFngByMonth.fearY + 3} font-size="5.5" fill="var(--ch-loss-light)">fear</text>
				{/if}
				{#if dcaAvgFngByMonth.greedY >= dcaAvgFngByMonth.PAD && dcaAvgFngByMonth.greedY <= dcaAvgFngByMonth.H - dcaAvgFngByMonth.PAD}
					<line x1={dcaAvgFngByMonth.PAD} y1={dcaAvgFngByMonth.greedY} x2={dcaAvgFngByMonth.W - dcaAvgFngByMonth.PAD} y2={dcaAvgFngByMonth.greedY} stroke="var(--ch-profit-light)" stroke-width="0.7" stroke-dasharray="3,2"/>
					<text x={dcaAvgFngByMonth.W - dcaAvgFngByMonth.PAD + 1} y={dcaAvgFngByMonth.greedY + 3} font-size="5.5" fill="var(--ch-profit-light)">greed</text>
				{/if}
				<polyline points={dcaAvgFngByMonth.pts} fill="none" stroke="var(--ch-warn)" stroke-width="1.5"/>
				{#each dcaAvgFngByMonth.avgs as a, i}
					{@const x = dcaAvgFngByMonth.PAD + (i / Math.max(dcaAvgFngByMonth.avgs.length - 1, 1)) * (dcaAvgFngByMonth.W - dcaAvgFngByMonth.PAD * 2)}
					{@const y = dcaAvgFngByMonth.PAD + (1 - (a.avg - Number(dcaAvgFngByMonth.mn)) / (Number(dcaAvgFngByMonth.mx) - Number(dcaAvgFngByMonth.mn))) * (dcaAvgFngByMonth.H - dcaAvgFngByMonth.PAD * 2)}
					<circle cx={x} cy={y} r="2" fill={a.avg < 25 ? 'var(--ch-loss-strong)' : a.avg > 75 ? 'var(--ch-profit-strong)' : 'var(--ch-warn)'}/>
					{#if i % Math.max(1, Math.floor(dcaAvgFngByMonth.avgs.length / 5)) === 0}
						<text {x} y={dcaAvgFngByMonth.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{a.mo.slice(5)}</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Monthly avg Fear &amp; Greed score · yellow line · red dot=fear zone(&lt;25) · green dot=greed zone(&gt;75) · dashed thresholds shown when in range</p>
		</section>
	{/if}

	{#if dcaAmountBoxByKind}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">DCA Amount Distribution by Kind (Q1–Q3 box)</h3>
			<svg viewBox="0 0 {dcaAmountBoxByKind.W} {dcaAmountBoxByKind.H}" class="w-full" style="height:{dcaAmountBoxByKind.H}px">
				{#each dcaAmountBoxByKind.items as item, i}
					{@const y = i * 22 + 8}
					{@const iqrW = Math.max(2, item.q3X - item.q1X)}
					<text x={dcaAmountBoxByKind.PAD} y={y + 11} font-size="8" fill="var(--ch-axis-strong)">{item.kind}</text>
					<rect x={dcaAmountBoxByKind.PAD + item.q1X} {y} width={iqrW} height="14" rx="3" fill="var(--ch-violet-light)"/>
					<line x1={dcaAmountBoxByKind.PAD + item.medX} y1={y} x2={dcaAmountBoxByKind.PAD + item.medX} y2={y + 14} stroke="var(--ch-violet-strong)" stroke-width="2"/>
					<text x={dcaAmountBoxByKind.PAD + item.medX + 3} y={y + 11} font-size="6.5" fill="var(--ch-axis-strong)">{item.median.toFixed(0)} USDT</text>
					<text x={dcaAmountBoxByKind.W - 2} y={y + 11} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{item.count}×</text>
				{/each}
				<text x={dcaAmountBoxByKind.PAD} y={dcaAmountBoxByKind.H - 1} font-size="5.5" fill="var(--ch-axis-muted)">0</text>
				<text x={dcaAmountBoxByKind.PAD + dcaAmountBoxByKind.barMaxW} y={dcaAmountBoxByKind.H - 1} text-anchor="end" font-size="5.5" fill="var(--ch-axis-muted)">{dcaAmountBoxByKind.mx} USDT</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">USDT amount distribution per DCA kind · box = Q1–Q3 interquartile range · vertical line = median · count = total triggers of that kind</p>
		</section>
	{/if}

	{#if dcaMonthlyTriggerCount}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Monthly DCA Trigger Count ({dcaMonthlyTriggerCount.total} total)</h3>
			<svg viewBox="0 0 {dcaMonthlyTriggerCount.W} {dcaMonthlyTriggerCount.H}" class="w-full" style="height:72px">
				<polygon points={dcaMonthlyTriggerCount.area} fill="var(--ch-violet-light)"/>
				<polyline points={dcaMonthlyTriggerCount.poly} fill="none" stroke="var(--ch-violet)" stroke-width="1.5" stroke-linejoin="round"/>
				{#each dcaMonthlyTriggerCount.dots as d, i}
					<circle cx={d.x} cy={d.y} r="2.5" fill="var(--ch-violet-strong)"/>
					{#if i % Math.max(1, Math.floor(dcaMonthlyTriggerCount.dots.length / 6)) === 0}
						<text x={d.x} y={dcaMonthlyTriggerCount.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{d.mo}</text>
					{/if}
				{/each}
				<text x={dcaMonthlyTriggerCount.PAD} y={dcaMonthlyTriggerCount.PAD + 5} font-size="6" fill="var(--ch-axis-muted)">{dcaMonthlyTriggerCount.maxC} triggers</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Number of DCA triggers per month · indigo area polyline · higher = more active month · reveals DCA cadence patterns over time</p>
		</section>
	{/if}
	{#if dcaAssetBuyFrequency}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">DCA Trigger Count by Asset</h3>
			<svg viewBox="0 0 {dcaAssetBuyFrequency.W} {dcaAssetBuyFrequency.H}" class="w-full" style="height:{dcaAssetBuyFrequency.H}px">
				{#each dcaAssetBuyFrequency.rows as row, i}
					{@const y = i * 16 + 2}
					{@const bw = Math.max(2, (row.count / dcaAssetBuyFrequency.maxC) * dcaAssetBuyFrequency.barMaxW)}
					{@const pct = ((row.count / dcaAssetBuyFrequency.total) * 100).toFixed(1)}
					<text x={dcaAssetBuyFrequency.PAD} y={y + 10} font-size="8" fill="var(--ch-axis-strong)">{row.asset}</text>
					<rect x={dcaAssetBuyFrequency.PAD + 68} {y} width={bw} height="12" rx="2" fill="var(--ch-profit-light)"/>
					<text x={dcaAssetBuyFrequency.PAD + 68 + bw + 3} y={y + 10} font-size="7" fill="var(--ch-axis-strong)">{row.count}</text>
					<text x={dcaAssetBuyFrequency.W - 2} y={y + 10} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{pct}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Number of DCA buy triggers per asset · bar length = trigger frequency · % of total triggers · reveals which assets receive most DCA attention</p>
		</section>
	{/if}
	{#if dcaAmountByDow}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Avg DCA Amount by Day of Week</h3>
			<svg viewBox="0 0 {dcaAmountByDow.W} {dcaAmountByDow.H}" class="w-full" style="height:{dcaAmountByDow.H}px">
				{#each dcaAmountByDow.bars as bar}
					<rect x={bar.x} y={dcaAmountByDow.H - dcaAmountByDow.PAD - 14 - bar.h} width={dcaAmountByDow.bw} height={bar.h} rx="2" fill="var(--ch-violet-light)"/>
					<text x={bar.x + dcaAmountByDow.bw / 2} y={dcaAmountByDow.H - dcaAmountByDow.PAD - 2} text-anchor="middle" font-size="7" fill="var(--ch-axis-strong)">{bar.day}</text>
					<text x={bar.x + dcaAmountByDow.bw / 2} y={dcaAmountByDow.H - dcaAmountByDow.PAD - 14 - bar.h - 3} text-anchor="middle" font-size="6" fill="var(--ch-violet-light)">{bar.avg.toFixed(0)}</text>
					<text x={bar.x + dcaAmountByDow.bw / 2} y={dcaAmountByDow.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{bar.count}t</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg DCA buy amount per day of week · bar height = avg amount · count = triggers on that day · reveals whether position sizing varies with day of week</p>
		</section>
	{/if}
	{#if dcaCumSpendTimeline}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Cumulative DCA Spend Over Time</h3>
			<svg viewBox="0 0 {dcaCumSpendTimeline.W} {dcaCumSpendTimeline.H}" class="w-full" style="height:{dcaCumSpendTimeline.H}px">
				<polygon points={dcaCumSpendTimeline.area} fill="var(--ch-violet-light)"/>
				<polyline points={dcaCumSpendTimeline.polyline} fill="none" stroke="var(--ch-violet-light)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={dcaCumSpendTimeline.PAD} y={dcaCumSpendTimeline.H - 2} font-size="7" fill="var(--ch-axis-muted)">{dcaCumSpendTimeline.firstDate}</text>
				<text x={dcaCumSpendTimeline.W - dcaCumSpendTimeline.PAD} y={dcaCumSpendTimeline.H - 2} text-anchor="end" font-size="7" fill="var(--ch-axis-muted)">{dcaCumSpendTimeline.lastDate}</text>
				<text x={dcaCumSpendTimeline.W - dcaCumSpendTimeline.PAD} y={dcaCumSpendTimeline.PAD + 6} text-anchor="end" font-size="7" fill="var(--ch-violet-light)">{dcaCumSpendTimeline.maxCum.toFixed(0)} total</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Cumulative DCA buy amount over time · blue area · total = sum of all buy amounts · reveals overall capital deployment rate and acceleration/deceleration in DCA activity</p>
		</section>
	{/if}
	{#if dcaMonthlyAvgAmount}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Monthly Avg Buy Amount</h3>
			<svg viewBox="0 0 {dcaMonthlyAvgAmount.W} {dcaMonthlyAvgAmount.H}" class="w-full" style="height:{dcaMonthlyAvgAmount.H}px">
				{#each dcaMonthlyAvgAmount.bars as bar, i}
					<rect x={bar.x} y={dcaMonthlyAvgAmount.H - dcaMonthlyAvgAmount.PAD - bar.h - 14} width={dcaMonthlyAvgAmount.bw} height={bar.h} fill="var(--ch-violet)" rx="1"/>
					{#if i % Math.max(1, Math.floor(dcaMonthlyAvgAmount.bars.length / 6)) === 0}
						<text x={bar.x + dcaMonthlyAvgAmount.bw / 2} y={dcaMonthlyAvgAmount.H - 3} text-anchor="middle" font-size="6" fill="var(--ch-axis-muted)">{bar.mo}</text>
					{/if}
					<text x={bar.x + dcaMonthlyAvgAmount.bw / 2} y={dcaMonthlyAvgAmount.H - dcaMonthlyAvgAmount.PAD - bar.h - 16} text-anchor="middle" font-size="5.5" fill="var(--ch-axis)">{bar.avg.toFixed(0)}</text>
				{/each}
				<text x={dcaMonthlyAvgAmount.W - 2} y={dcaMonthlyAvgAmount.PAD + 6} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{dcaMonthlyAvgAmount.maxAvg.toFixed(0)} max</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Monthly avg DCA buy amount per trigger · purple bars · label=avg USDT · reveals changes in position sizing over time and response to market conditions</p>
		</section>
	{/if}
	{#if dcaTotalSpendByAsset}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Total DCA Spend by Asset</h3>
			<svg viewBox="0 0 {dcaTotalSpendByAsset.W} {dcaTotalSpendByAsset.H}" class="w-full" style="height:{dcaTotalSpendByAsset.H}px">
				{#each dcaTotalSpendByAsset.rows as row, i}
					{@const y = i * 16 + 2}
					{@const bw = Math.max(2, (row.total / dcaTotalSpendByAsset.maxTotal) * dcaTotalSpendByAsset.barMaxW)}
					<text x={dcaTotalSpendByAsset.PAD} y={y + 10} font-size="7" fill="var(--ch-axis-strong)">{row.asset}</text>
					<rect x={dcaTotalSpendByAsset.PAD + 60} {y} width={bw} height="12" rx="2" fill="var(--ch-teal)"/>
					<text x={dcaTotalSpendByAsset.PAD + 60 + bw + 3} y={y + 10} font-size="7" fill="var(--ch-teal)">{row.total.toFixed(0)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Total DCA buy amount (USDT) per asset across all events · sky-blue bars · reveals capital allocation across assets and which positions have received the most investment</p>
		</section>
	{/if}
	{#if dcaOrderCountByMonth}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">DCA Orders per Month</h3>
			<svg viewBox="0 0 {dcaOrderCountByMonth.W} {dcaOrderCountByMonth.H}" class="w-full" style="height:{dcaOrderCountByMonth.H}px">
				{#each dcaOrderCountByMonth.counts as cnt, i}
					{@const x = dcaOrderCountByMonth.toX(i)}
					{@const bh = Math.max(2, dcaOrderCountByMonth.toH(cnt))}
					{@const y = dcaOrderCountByMonth.H - dcaOrderCountByMonth.PAD - 12 - bh}
					<rect {x} {y} width={dcaOrderCountByMonth.bw} height={bh} rx="1" fill="var(--ch-violet-strong)"/>
					{#if i % 3 === 0}
						<text x={x + dcaOrderCountByMonth.bw / 2} y={dcaOrderCountByMonth.H - 2} text-anchor="middle" font-size="5.5" fill="var(--ch-axis)">{dcaOrderCountByMonth.months[i].slice(5)}</text>
					{/if}
				{/each}
				<text x={dcaOrderCountByMonth.PAD} y={dcaOrderCountByMonth.PAD + 6} font-size="6" fill="var(--ch-violet-strong)">{dcaOrderCountByMonth.maxCount}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Number of DCA buy orders executed per calendar month · purple bars · reveals buying frequency patterns and periods of high/low DCA activity</p>
		</section>
	{/if}
	{#if dcaAvgAmountByDow}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg DCA Amount by Day of Week (USDT)</h3>
			<svg viewBox="0 0 {dcaAvgAmountByDow.W} {dcaAvgAmountByDow.H}" class="w-full" style="height:{dcaAvgAmountByDow.H}px">
				{#each dcaAvgAmountByDow.rows as row, i}
					{@const x = dcaAvgAmountByDow.PAD + i * (dcaAvgAmountByDow.bw + 2)}
					{@const bh = Math.max(2, dcaAvgAmountByDow.toH(row.avg))}
					{@const y = dcaAvgAmountByDow.H - dcaAvgAmountByDow.PAD - 12 - bh}
					<rect {x} {y} width={dcaAvgAmountByDow.bw} height={bh} rx="1" fill="var(--ch-teal)"/>
					<text x={x + dcaAvgAmountByDow.bw / 2} y={dcaAvgAmountByDow.H - 2} text-anchor="middle" font-size="7" fill="var(--ch-axis)">{row.day}</text>
				{/each}
				<text x={dcaAvgAmountByDow.PAD} y={dcaAvgAmountByDow.PAD + 6} font-size="6" fill="var(--ch-teal)">{dcaAvgAmountByDow.maxAvg}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg USDT amount per DCA order by day of week · sky-blue bars · reveals whether certain days trigger larger buy orders due to price dips or triggers</p>
		</section>
	{/if}
	{#if dcaCumSpendByAssetTimeline}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Cumulative Spend by Asset (USDT)</h3>
			<svg viewBox="0 0 {dcaCumSpendByAssetTimeline.W} {dcaCumSpendByAssetTimeline.H}" class="w-full" style="height:{dcaCumSpendByAssetTimeline.H}px">
				{#each dcaCumSpendByAssetTimeline.lines as line, li}
					<polyline points={line.polyline} fill="none" stroke={line.color} stroke-width="1.4" stroke-linejoin="round"/>
					<text x={dcaCumSpendByAssetTimeline.W - dcaCumSpendByAssetTimeline.PAD + 2} y={dcaCumSpendByAssetTimeline.PAD + li * 10 + 6} font-size="6.5" fill={line.color}>{line.name}</text>
				{/each}
				<text x={dcaCumSpendByAssetTimeline.PAD} y={dcaCumSpendByAssetTimeline.PAD + 6} font-size="6" fill="var(--ch-axis-muted)">{dcaCumSpendByAssetTimeline.maxCum}</text>
				<text x={dcaCumSpendByAssetTimeline.PAD} y={dcaCumSpendByAssetTimeline.H - 2} font-size="6" fill="var(--ch-axis-muted)">earliest →</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Cumulative USDT spent per asset over time · each line=one asset (top 4) · steeper slope=faster accumulation · reveals DCA velocity and asset prioritization</p>
		</section>
	{/if}
	{#if dcaAvgOrdersByAsset}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">DCA Orders &amp; Avg Size by Asset</h3>
			<svg viewBox="0 0 {dcaAvgOrdersByAsset.W} {dcaAvgOrdersByAsset.H}" class="w-full" style="height:{dcaAvgOrdersByAsset.H}px">
				{#each dcaAvgOrdersByAsset.rows as row, i}
					{@const y = dcaAvgOrdersByAsset.PAD + i * 17}
					{@const bw = Math.max(2, (row.count / dcaAvgOrdersByAsset.maxCount) * (dcaAvgOrdersByAsset.barW * 0.55))}
					{@const bw2 = Math.max(2, (row.avg / dcaAvgOrdersByAsset.maxAvg) * (dcaAvgOrdersByAsset.barW * 0.4))}
					<text x={dcaAvgOrdersByAsset.PAD} y={y + 11} font-size="7" fill="var(--ch-axis-strong)">{row.asset}</text>
					<rect x={dcaAvgOrdersByAsset.PAD + 60} {y} width={bw} height="12" rx="1" fill="var(--ch-violet-strong)"/>
					<text x={dcaAvgOrdersByAsset.PAD + 60 + bw + 2} y={y + 11} font-size="6" fill="var(--ch-violet-strong)">{row.count}</text>
					<rect x={dcaAvgOrdersByAsset.PAD + 60 + dcaAvgOrdersByAsset.barW * 0.58} {y} width={bw2} height="12" rx="1" fill="var(--ch-teal-light)"/>
					<text x={dcaAvgOrdersByAsset.PAD + 60 + dcaAvgOrdersByAsset.barW * 0.58 + bw2 + 2} y={y + 11} font-size="6" fill="var(--ch-teal)">{row.avg.toFixed(0)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Per asset: purple=order count · sky=avg USDT per order · reveals which assets receive the most frequent vs largest DCA orders</p>
		</section>
	{/if}
	{#if dcaAmountHistogram}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">DCA Order Amount Distribution</h3>
			<svg viewBox="0 0 {dcaAmountHistogram.W} {dcaAmountHistogram.H}" class="w-full" style="height:{dcaAmountHistogram.H}px">
				{#each dcaAmountHistogram.counts as count, i}
					{@const x = dcaAmountHistogram.PAD + i * dcaAmountHistogram.barW}
					{@const bh = Math.max(2, (count / dcaAmountHistogram.maxCount) * (dcaAmountHistogram.H - dcaAmountHistogram.PAD * 2))}
					<rect {x} y={dcaAmountHistogram.H - dcaAmountHistogram.PAD - bh} width={dcaAmountHistogram.barW - 1} height={bh} fill="var(--ch-violet-strong)"/>
					{#if i % 3 === 0}
						<text x={x + dcaAmountHistogram.barW / 2} y={dcaAmountHistogram.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{(i * +dcaAmountHistogram.bucketSize).toFixed(0)}</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Distribution of DCA order sizes in USDT · purple bars · reveals typical order size distribution and identifies if most orders are small periodic buys or large infrequent ones</p>
		</section>
	{/if}
	{#if dcaWeeklySpendTrend}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Weekly DCA Spend Trend</h3>
			<svg viewBox="0 0 {dcaWeeklySpendTrend.W} {dcaWeeklySpendTrend.H}" class="w-full" style="height:{dcaWeeklySpendTrend.H}px">
				<polygon points={dcaWeeklySpendTrend.area} fill="rgba(168,85,247,0.1)"/>
				<polyline points={dcaWeeklySpendTrend.polyline} fill="none" stroke="var(--ch-violet-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={dcaWeeklySpendTrend.PAD} y={dcaWeeklySpendTrend.H - 2} font-size="6" fill="var(--ch-axis-muted)">{dcaWeeklySpendTrend.firstW}</text>
				<text x={dcaWeeklySpendTrend.W - dcaWeeklySpendTrend.PAD} y={dcaWeeklySpendTrend.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{dcaWeeklySpendTrend.lastW}</text>
				<text x={dcaWeeklySpendTrend.PAD} y={dcaWeeklySpendTrend.PAD + 7} font-size="7" fill="var(--ch-violet-strong)">{dcaWeeklySpendTrend.maxV} USDT</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Total USDT spent per calendar week · purple area · reveals spending cadence and identifies weeks with unusually high DCA activity (dip-buying spikes)</p>
		</section>
	{/if}
	{#if dcaSpendByHour}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">DCA Spend by UTC Hour</h3>
			<svg viewBox="0 0 {dcaSpendByHour.W} {dcaSpendByHour.H}" class="w-full" style="height:{dcaSpendByHour.H}px">
				{#each dcaSpendByHour.sums as sum, h}
					{@const x = dcaSpendByHour.PAD + h * dcaSpendByHour.barW}
					{@const bh = Math.max(2, (sum / dcaSpendByHour.maxSum) * (dcaSpendByHour.H - dcaSpendByHour.PAD * 2))}
					<rect {x} y={dcaSpendByHour.H - dcaSpendByHour.PAD - bh} width={dcaSpendByHour.barW - 1} height={bh} fill={`rgba(168,85,247,${(sum / dcaSpendByHour.maxSum * 0.65 + 0.15).toFixed(2)})`}/>
					{#if h % 6 === 0}
						<text x={x + dcaSpendByHour.barW / 2} y={dcaSpendByHour.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{h}h</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Total USDT spent per UTC hour across all DCA orders · purple intensity scales with spend · identifies peak buying hours and reveals scheduled vs event-driven order patterns</p>
		</section>
	{/if}
	{#if dcaMonthlyOrderCount}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Monthly DCA Order Count</h3>
			<svg viewBox="0 0 {dcaMonthlyOrderCount.W} {dcaMonthlyOrderCount.H}" class="w-full" style="height:{dcaMonthlyOrderCount.H}px">
				{#each dcaMonthlyOrderCount.pts as p, i}
					{@const x = dcaMonthlyOrderCount.PAD + i * (dcaMonthlyOrderCount.bw + 1)}
					{@const bh = Math.max(2, (p.count / dcaMonthlyOrderCount.maxCount) * (dcaMonthlyOrderCount.H - dcaMonthlyOrderCount.PAD * 2))}
					<rect {x} y={dcaMonthlyOrderCount.H - dcaMonthlyOrderCount.PAD - bh} width={dcaMonthlyOrderCount.bw} height={bh} rx="1" fill="var(--ch-violet-strong)"/>
					{#if i % 3 === 0}
						<text x={x + dcaMonthlyOrderCount.bw / 2} y={dcaMonthlyOrderCount.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{p.m}</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">DCA order count per month · purple bars · reveals whether buying frequency is increasing or decreasing over time and identifies months with high accumulation activity</p>
		</section>
	{/if}
	{#if dcaAvgAmountByMonth}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg DCA Order Size by Month</h3>
			<svg viewBox="0 0 {dcaAvgAmountByMonth.W} {dcaAvgAmountByMonth.H}" class="w-full" style="height:{dcaAvgAmountByMonth.H}px">
				{#each dcaAvgAmountByMonth.pts as p, i}
					{@const x = dcaAvgAmountByMonth.PAD + i * (dcaAvgAmountByMonth.bw + 1)}
					{@const bh = Math.max(1, (p.avg / dcaAvgAmountByMonth.maxAvg) * (dcaAvgAmountByMonth.H - dcaAvgAmountByMonth.PAD * 2))}
					{@const y = dcaAvgAmountByMonth.H - dcaAvgAmountByMonth.PAD - bh}
					<rect {x} {y} width={dcaAvgAmountByMonth.bw} height={bh} rx="1" fill="var(--ch-violet-strong)"/>
					{#if i % 3 === 0}
						<text x={x + dcaAvgAmountByMonth.bw / 2} y={dcaAvgAmountByMonth.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{p.m}</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg DCA order size in USDT per month · purple bars · rising trend indicates increasing position sizes over time · useful for sizing strategy review</p>
		</section>
	{/if}
	{#if dcaSpendByDow}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg DCA Spend by Day of Week</h3>
			<svg viewBox="0 0 {dcaSpendByDow.W} {dcaSpendByDow.H}" class="w-full" style="height:{dcaSpendByDow.H}px">
				{#each dcaSpendByDow.pts as p, i}
					{@const x = dcaSpendByDow.PAD + i * (dcaSpendByDow.bw + 2)}
					{@const bh = Math.max(1, (p.avg / dcaSpendByDow.maxAvg) * (dcaSpendByDow.H - dcaSpendByDow.PAD * 2))}
					{@const y = dcaSpendByDow.H - dcaSpendByDow.PAD - bh}
					<rect {x} {y} width={dcaSpendByDow.bw} height={bh} rx="1" fill="var(--ch-violet-strong)"/>
					<text x={x + dcaSpendByDow.bw / 2} y={dcaSpendByDow.H - 1} text-anchor="middle" font-size="6" fill="var(--ch-axis)">{p.d}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg DCA spend per event by day of week · purple bars · reveals whether certain days systematically trigger larger or smaller buy orders</p>
		</section>
	{/if}
	{#if dcaCumAmountCDF}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Order Size CDF (USDT)</h3>
			<svg viewBox="0 0 {dcaCumAmountCDF.W} {dcaCumAmountCDF.H}" class="w-full" style="height:{dcaCumAmountCDF.H}px">
				<polyline points={dcaCumAmountCDF.polyline} fill="none" stroke="var(--ch-violet-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={dcaCumAmountCDF.PAD} y={dcaCumAmountCDF.H - 2} font-size="6" fill="var(--ch-axis-muted)">{dcaCumAmountCDF.minV}</text>
				<text x={dcaCumAmountCDF.W - dcaCumAmountCDF.PAD} y={dcaCumAmountCDF.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{dcaCumAmountCDF.maxV}</text>
				<text x={dcaCumAmountCDF.W / 2} y={dcaCumAmountCDF.PAD + 8} text-anchor="middle" font-size="7" fill="var(--ch-violet-strong)">median {dcaCumAmountCDF.median} · p80 {dcaCumAmountCDF.p80}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Cumulative distribution of DCA order sizes in USDT · purple S-curve · steep center = most orders clustered near median · long right tail = occasional large buys</p>
		</section>
	{/if}
	{#if dcaAmountByKindMonth}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Total Spend Heatmap (Kind × Month)</h3>
			<svg viewBox="0 0 {dcaAmountByKindMonth.W} {dcaAmountByKindMonth.H}" class="w-full" style="height:{dcaAmountByKindMonth.H}px">
				{#each dcaAmountByKindMonth.kinds as k, ki}
					<text x={dcaAmountByKindMonth.PAD} y={dcaAmountByKindMonth.PAD + (ki + 1) * dcaAmountByKindMonth.cellH + 11} font-size="5.5" fill="var(--ch-axis)">{k}</text>
				{/each}
				{#each dcaAmountByKindMonth.months as mo, mi}
					<text x={dcaAmountByKindMonth.PAD + (mi + 1) * dcaAmountByKindMonth.cellW + dcaAmountByKindMonth.cellW / 2} y={dcaAmountByKindMonth.PAD + 8} text-anchor="middle" font-size="5.5" fill="var(--ch-axis)">{mo.slice(5)}</text>
				{/each}
				{#each dcaAmountByKindMonth.cells as cell}
					{@const alpha = cell.val === 0 ? '0.06' : (cell.val / dcaAmountByKindMonth.maxVal * 0.65 + 0.1).toFixed(2)}
					<rect x={cell.x} y={cell.y} width={dcaAmountByKindMonth.cellW - 2} height={dcaAmountByKindMonth.cellH - 2} rx="2" style="fill:{cell.color};fill-opacity:{alpha}"/>
					{#if cell.val > 0}
						<text x={cell.x + dcaAmountByKindMonth.cellW / 2 - 1} y={cell.y + 11} text-anchor="middle" font-size="5" fill="var(--ch-axis-strong)">{(cell.val / 1000).toFixed(1)}K</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Total USDT spent heatmap by DCA kind and month (last 6 months) · intensity=amount · reveals which DCA types dominate spending in each period</p>
		</section>
	{/if}
	{#if dcaOrderGapDays}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Order Gap Distribution (Days Between Orders)</h3>
			<svg viewBox="0 0 {dcaOrderGapDays.W} {dcaOrderGapDays.H}" class="w-full" style="height:{dcaOrderGapDays.H}px">
				{#each dcaOrderGapDays.counts as count, i}
					{@const x = dcaOrderGapDays.PAD + i * (dcaOrderGapDays.bw + 1)}
					{@const bh = Math.max(1, (count / dcaOrderGapDays.maxCount) * (dcaOrderGapDays.H - dcaOrderGapDays.PAD * 2))}
					{@const y = dcaOrderGapDays.H - dcaOrderGapDays.PAD - bh}
					{@const binMid = (i + 0.5) * dcaOrderGapDays.step}
					{@const color = binMid <= 3 ? 'var(--ch-violet-strong)' : binMid <= 10 ? 'var(--ch-violet)' : binMid <= 21 ? 'var(--ch-warn)' : 'var(--ch-axis-muted)'}
					<rect {x} {y} width={dcaOrderGapDays.bw} height={bh} rx="1" style="fill:{color}"/>
				{/each}
				<text x={dcaOrderGapDays.PAD} y={dcaOrderGapDays.H - 1} font-size="6" fill="var(--ch-axis-muted)">0d</text>
				<text x={dcaOrderGapDays.W - dcaOrderGapDays.PAD} y={dcaOrderGapDays.H - 1} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{dcaOrderGapDays.maxGap}d</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">12-bin histogram of days between consecutive DCA orders · purple≤3d · indigo≤10d · yellow≤21d · gray longer · left-skewed = frequent buying cadence</p>
		</section>
	{/if}
	{#if dcaAssetShareByMonth}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Spend Heatmap by Asset × Month</h3>
			<svg viewBox="0 0 {dcaAssetShareByMonth.W} {dcaAssetShareByMonth.H}" class="w-full" style="height:{dcaAssetShareByMonth.H}px">
				{#each dcaAssetShareByMonth.assets as a, ai}
					<text x={dcaAssetShareByMonth.PAD} y={dcaAssetShareByMonth.PAD + (ai + 1) * dcaAssetShareByMonth.cellH + 11} font-size="5.5" fill="var(--ch-axis)">{a}</text>
				{/each}
				{#each dcaAssetShareByMonth.months as mo, mi}
					<text x={dcaAssetShareByMonth.PAD + (mi + 1) * dcaAssetShareByMonth.cellW + dcaAssetShareByMonth.cellW / 2} y={dcaAssetShareByMonth.PAD + 8} text-anchor="middle" font-size="5.5" fill="var(--ch-axis)">{mo.slice(5)}</text>
				{/each}
				{#each dcaAssetShareByMonth.cells as cell}
					{@const alpha = cell.val === 0 ? '0.06' : (cell.val / dcaAssetShareByMonth.maxVal * 0.65 + 0.1).toFixed(2)}
					<rect x={cell.x} y={cell.y} width={dcaAssetShareByMonth.cellW - 2} height={dcaAssetShareByMonth.cellH - 2} rx="2" style="fill:{cell.color};fill-opacity:{alpha}"/>
					{#if cell.val > 0}
						<text x={cell.x + dcaAssetShareByMonth.cellW / 2 - 1} y={cell.y + 11} text-anchor="middle" font-size="5" fill="var(--ch-axis-strong)">{(cell.val).toFixed(0)}</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Total USDT spent per asset (rows) by month (cols, last 6) · intensity=amount · reveals concentration of DCA activity across coins over time</p>
		</section>
	{/if}
	{#if dcaOrderCountByAsset}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Order Count by Asset</h3>
			<svg viewBox="0 0 {dcaOrderCountByAsset.W} {dcaOrderCountByAsset.H}" class="w-full" style="height:{dcaOrderCountByAsset.H}px">
				{#each dcaOrderCountByAsset.rows as row, i}
					{@const y = dcaOrderCountByAsset.PAD + i * 18}
					{@const bw = Math.max(2, (row.count / dcaOrderCountByAsset.maxCount) * dcaOrderCountByAsset.barMaxW)}
					<text x={dcaOrderCountByAsset.PAD} y={y + 12} font-size="7" fill="var(--ch-axis-strong)">{row.asset}</text>
					<rect x={dcaOrderCountByAsset.PAD + 60} {y} width={bw} height="13" rx="2" fill="var(--ch-violet-strong)"/>
					<text x={dcaOrderCountByAsset.PAD + 60 + bw + 3} y={y + 12} font-size="6.5" fill="var(--ch-violet-strong)">{row.count}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Total DCA order count per asset · purple bars · most orders = most actively accumulated asset · reveals portfolio concentration by trade frequency</p>
		</section>
	{/if}
	{#if dcaCumSpendAssetLines}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Cumulative Spend by Asset (USDT)</h3>
			<div class="mb-1 flex flex-wrap gap-3">
				{#each dcaCumSpendAssetLines.assets as a, ai}
					<span class="flex items-center gap-1 text-[9px]" style="color:{dcaCumSpendAssetLines.COLORS[ai]}">
						<span class="inline-block h-0.5 w-4 rounded" style="background:{dcaCumSpendAssetLines.COLORS[ai]}"></span>{a}
					</span>
				{/each}
			</div>
			<svg viewBox="0 0 {dcaCumSpendAssetLines.W} {dcaCumSpendAssetLines.H}" class="w-full" style="height:{dcaCumSpendAssetLines.H}px">
				{#each dcaCumSpendAssetLines.polylines as pts, ai}
					<polyline points={pts} fill="none" stroke={dcaCumSpendAssetLines.COLORS[ai]} stroke-width="1.3" stroke-linejoin="round"/>
				{/each}
				<text x={dcaCumSpendAssetLines.W - dcaCumSpendAssetLines.PAD} y={dcaCumSpendAssetLines.PAD + 8} text-anchor="end" font-size="6.5" fill="var(--ch-axis)">max {dcaCumSpendAssetLines.maxCum}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Cumulative USDT spend over time per asset · steeper slope = faster accumulation · plateau = paused DCA · reveals relative commitment to each position</p>
		</section>
	{/if}
	{#if dcaSpendByQuarter}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Total DCA Spend by Quarter</h3>
			<svg viewBox="0 0 {dcaSpendByQuarter.W} {dcaSpendByQuarter.H}" class="w-full" style="height:{dcaSpendByQuarter.H}px">
				{#each dcaSpendByQuarter.pts as p, i}
					{@const x = dcaSpendByQuarter.PAD + i * (dcaSpendByQuarter.bw + 1)}
					{@const bh = Math.max(2, (p.total / dcaSpendByQuarter.maxTotal) * (dcaSpendByQuarter.H - dcaSpendByQuarter.PAD * 2 - 10))}
					{@const y = dcaSpendByQuarter.H - dcaSpendByQuarter.PAD - 10 - bh}
					{@const color = i % 2 === 0 ? 'var(--ch-violet-strong)' : 'var(--ch-violet)'}
					<rect {x} {y} width={dcaSpendByQuarter.bw} height={bh} rx="1" fill={color}/>
					<text x={x + dcaSpendByQuarter.bw / 2} y={dcaSpendByQuarter.H - 1} text-anchor="middle" font-size="6" fill="var(--ch-axis)">{p.q}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Total DCA spend (USDT) per quarter · purple/indigo alternating bars · rising quarters = increasing conviction or portfolio growth · falling = reduced deployment pace</p>
		</section>
	{/if}
	{#if dcaAmountByAssetCDF}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">DCA Order Amount CDF</h3>
			<svg viewBox="0 0 {dcaAmountByAssetCDF.W} {dcaAmountByAssetCDF.H}" class="w-full" style="height:{dcaAmountByAssetCDF.H}px">
				<polyline points={dcaAmountByAssetCDF.polyline} fill="none" stroke="var(--ch-violet-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={dcaAmountByAssetCDF.PAD} y={dcaAmountByAssetCDF.H - 2} font-size="6" fill="var(--ch-axis-muted)">{dcaAmountByAssetCDF.minV}</text>
				<text x={dcaAmountByAssetCDF.W - dcaAmountByAssetCDF.PAD} y={dcaAmountByAssetCDF.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{dcaAmountByAssetCDF.maxV}</text>
				<text x={dcaAmountByAssetCDF.W / 2} y={dcaAmountByAssetCDF.PAD + 8} text-anchor="middle" font-size="7" fill="var(--ch-violet-strong)">median {dcaAmountByAssetCDF.median}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">CDF of DCA order amounts across all events · purple S-curve · steep left = most orders are small · right tail = occasional large top-ups · reveals position sizing distribution</p>
		</section>
	{/if}
	{#if dcaAvgAmountTrend}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg DCA Order Amount Trend</h3>
			<svg viewBox="0 0 {dcaAvgAmountTrend.W} {dcaAvgAmountTrend.H}" class="w-full" style="height:{dcaAvgAmountTrend.H}px">
				<polyline points={dcaAvgAmountTrend.polyline} fill="none" stroke="var(--ch-violet-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				{#each dcaAvgAmountTrend.pts as p, i}
					{#if i % 3 === 0}
						<text x={dcaAvgAmountTrend.toX(i).toFixed(1)} y={dcaAvgAmountTrend.H - 2} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{p.mo}</text>
					{/if}
				{/each}
				<text x={dcaAvgAmountTrend.W - dcaAvgAmountTrend.PAD} y={dcaAvgAmountTrend.PAD + 8} text-anchor="end" font-size="6" fill="var(--ch-violet-strong)">max {dcaAvgAmountTrend.maxAvg}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Monthly avg DCA order amount (USDT) trend · purple line · rising = increasing conviction or portfolio growth · falling = more conservative sizing or cost-averaging down smaller</p>
		</section>
	{/if}
	{#if dcaOrdersByDow}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">DCA Orders by Day of Week</h3>
			<svg viewBox="0 0 {dcaOrdersByDow.W} {dcaOrdersByDow.H}" class="w-full" style="height:{dcaOrdersByDow.H}px">
				{#each dcaOrdersByDow.counts as count, i}
					{@const x = dcaOrdersByDow.PAD + i * (dcaOrdersByDow.bw + 1)}
					{@const bh = Math.max(2, (count / dcaOrdersByDow.maxCount) * (dcaOrdersByDow.H - dcaOrdersByDow.PAD * 2 - 10))}
					{@const y = dcaOrdersByDow.H - dcaOrdersByDow.PAD - 10 - bh}
					{@const color = i === 0 || i === 6 ? 'var(--ch-violet)' : 'var(--ch-violet-strong)'}
					<rect {x} {y} width={dcaOrdersByDow.bw} height={bh} rx="1" fill={color}/>
					<text x={x + dcaOrdersByDow.bw / 2} y={dcaOrdersByDow.H - 1} text-anchor="middle" font-size="6.5" fill="var(--ch-axis)">{dcaOrdersByDow.DAYS[i]}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">DCA order count by day of week · purple=weekdays · indigo=weekends · pattern reveals if DCA is manually triggered or fully automated (uniform distribution)</p>
		</section>
	{/if}
	{#if dcaSpendByHourOfDay}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">DCA Spend by Hour of Day</h3>
			<svg viewBox="0 0 {dcaSpendByHourOfDay.W} {dcaSpendByHourOfDay.H}" class="w-full" style="height:{dcaSpendByHourOfDay.H}px">
				{#each dcaSpendByHourOfDay.amounts as amount, i}
					{@const x = dcaSpendByHourOfDay.PAD + i * (dcaSpendByHourOfDay.bw + 0.3)}
					{@const bh = Math.max(1, (amount / dcaSpendByHourOfDay.maxAmount) * (dcaSpendByHourOfDay.H - 14))}
					{@const y = dcaSpendByHourOfDay.H - bh - 6}
					{@const color = i >= 8 && i <= 17 ? 'var(--ch-violet-strong)' : 'var(--ch-violet)'}
					<rect {x} {y} width={dcaSpendByHourOfDay.bw} height={bh} rx="0.5" fill={color}/>
				{/each}
				<text x={dcaSpendByHourOfDay.PAD} y={dcaSpendByHourOfDay.H} font-size="5.5" fill="var(--ch-axis-muted)">0h</text>
				<text x={dcaSpendByHourOfDay.PAD + (dcaSpendByHourOfDay.W - dcaSpendByHourOfDay.PAD * 2) / 2} y={dcaSpendByHourOfDay.H} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">12h</text>
				<text x={dcaSpendByHourOfDay.W - dcaSpendByHourOfDay.PAD} y={dcaSpendByHourOfDay.H} text-anchor="end" font-size="5.5" fill="var(--ch-axis-muted)">23h</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Total DCA spend by hour of day (UTC) · purple=business hours · indigo=overnight · spike at a specific hour = timer-based automation · uniform = market-price triggered</p>
		</section>
	{/if}
	{#if dcaAvgAmountByWeekday}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg DCA Amount by Weekday</h3>
			<svg viewBox="0 0 {dcaAvgAmountByWeekday.W} {dcaAvgAmountByWeekday.H}" class="w-full" style="height:{dcaAvgAmountByWeekday.H}px">
				{#each dcaAvgAmountByWeekday.avgs as avg, i}
					{@const x = dcaAvgAmountByWeekday.PAD + i * (dcaAvgAmountByWeekday.bw + 1)}
					{@const bh = Math.max(2, (avg / dcaAvgAmountByWeekday.maxAvg) * (dcaAvgAmountByWeekday.H - 14))}
					{@const y = dcaAvgAmountByWeekday.H - bh - 8}
					{@const color = avg >= dcaAvgAmountByWeekday.maxAvg * 0.7 ? 'var(--ch-violet-strong)' : 'var(--ch-violet)'}
					<rect {x} {y} width={dcaAvgAmountByWeekday.bw} height={bh} rx="1" fill={color}/>
					<text x={x + dcaAvgAmountByWeekday.bw / 2} y={dcaAvgAmountByWeekday.H - 1} text-anchor="middle" font-size="6.5" fill="var(--ch-axis)">{dcaAvgAmountByWeekday.DAYS[i]}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg DCA order amount by day of week · purple=high spend days · days with larger avg amounts = scheduled larger DCA tranches or price-dip triggered buys</p>
		</section>
	{/if}
	{#if dcaMonthlySpendTrend}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Monthly DCA Spend Trend</h3>
			<svg viewBox="0 0 {dcaMonthlySpendTrend.W} {dcaMonthlySpendTrend.H}" class="w-full" style="height:{dcaMonthlySpendTrend.H}px">
				<polyline points={dcaMonthlySpendTrend.polyline} fill="none" stroke="var(--ch-violet-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				{#each dcaMonthlySpendTrend.pts as p, i}
					{#if i % Math.max(1, Math.floor(dcaMonthlySpendTrend.pts.length / 6)) === 0}
						<text x={dcaMonthlySpendTrend.toX(i).toFixed(1)} y={dcaMonthlySpendTrend.H} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{p.mo}</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Total DCA spend per month · purple line · rising = increasing deployment pace · flat = stable DCA schedule · spike = opportunistic buys during market dips</p>
		</section>
	{/if}
	{#if dcaAmountCumulativeByAsset}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Cumulative Spend by Asset</h3>
			<svg viewBox="0 0 {dcaAmountCumulativeByAsset.W} {dcaAmountCumulativeByAsset.H}" class="w-full" style="height:{dcaAmountCumulativeByAsset.H}px">
				{#each dcaAmountCumulativeByAsset.rows as row, i}
					{@const y = dcaAmountCumulativeByAsset.PAD + i * 20}
					{@const bw = Math.max(2, (row.total / dcaAmountCumulativeByAsset.maxTotal) * dcaAmountCumulativeByAsset.barMaxW)}
					{@const color = row.total >= dcaAmountCumulativeByAsset.maxTotal * 0.6 ? 'var(--ch-violet-strong)' : row.total >= dcaAmountCumulativeByAsset.maxTotal * 0.3 ? 'var(--ch-violet)' : 'var(--ch-axis-muted)'}
					<text x={dcaAmountCumulativeByAsset.PAD} y={y + 13} font-size="7.5" fill="var(--ch-axis-strong)">{row.asset}</text>
					<rect x={dcaAmountCumulativeByAsset.PAD + 60} {y} width={bw} height="14" rx="2" fill={color}/>
					<text x={dcaAmountCumulativeByAsset.PAD + 60 + bw + 3} y={y + 12} font-size="6.5" fill={color}>{row.total.toFixed(0)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Total cumulative DCA spend by asset · purple = largest allocations · reveals portfolio concentration — high BTC/ETH dominance = conservative DCA strategy</p>
		</section>
	{/if}
	{#if dcaSpendByWeekday}
		<section class="rounded-lg border border-border bg-card p-3">
			<h3 class="mb-1 text-xs font-semibold text-muted-foreground">Avg DCA Amount by Weekday</h3>
			<svg viewBox={`0 0 ${dcaSpendByWeekday.W} ${dcaSpendByWeekday.H}`} width="100%" style="height:65px">
				{#each dcaSpendByWeekday.bars as b, i}
					{@const bh = (b.avg / dcaSpendByWeekday.maxAvg) * (dcaSpendByWeekday.H - dcaSpendByWeekday.PAD * 2)}
					{@const x = dcaSpendByWeekday.PAD + i * (dcaSpendByWeekday.bw + 2)}
					{@const y = dcaSpendByWeekday.H - dcaSpendByWeekday.PAD - bh}
					<rect {x} {y} width={dcaSpendByWeekday.bw} height={bh} fill="var(--ch-violet)" rx="1"/>
					<text x={x + dcaSpendByWeekday.bw / 2} y={dcaSpendByWeekday.H} text-anchor="middle" font-size="6" fill="var(--ch-axis)">{b.label}</text>
					<text x={x + dcaSpendByWeekday.bw / 2} y={y - 2} text-anchor="middle" font-size="5.5" fill="var(--ch-violet)">{b.avg.toFixed(0)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg DCA order amount by weekday · purple bars · higher bars = larger average orders placed on that day · reveals if DCA cadence varies by day</p>
		</section>
	{/if}
	{#if dcaAmountDistribution}
		<section class="rounded-lg border border-border bg-card p-3">
			<h3 class="mb-1 text-xs font-semibold text-muted-foreground">DCA Order Amount Distribution</h3>
			<svg viewBox={`0 0 ${dcaAmountDistribution.W} ${dcaAmountDistribution.H}`} width="100%" style="height:65px">
				{#each dcaAmountDistribution.counts as cnt, i}
					{@const bh = Math.max(1, (cnt / dcaAmountDistribution.maxCnt) * (dcaAmountDistribution.H - dcaAmountDistribution.PAD * 2))}
					{@const x = dcaAmountDistribution.PAD + i * (dcaAmountDistribution.bw + 1)}
					{@const y = dcaAmountDistribution.H - dcaAmountDistribution.PAD - bh}
					<rect {x} {y} width={dcaAmountDistribution.bw} height={bh} fill="var(--ch-violet)" rx="1"/>
					{#if i === 0 || i === dcaAmountDistribution.bins - 1}
						<text x={x + dcaAmountDistribution.bw / 2} y={dcaAmountDistribution.H} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{i === 0 ? dcaAmountDistribution.minV : dcaAmountDistribution.maxV}</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Histogram of DCA order amounts · purple bars · left-skewed = mostly small orders · right tail = occasional large buys · reveals position sizing discipline</p>
		</section>
	{/if}
	{#if dcaInterOrderGapCDF}
		<section class="rounded-lg border border-border bg-card p-3">
			<h3 class="mb-1 text-xs font-semibold text-muted-foreground">Inter-Order Gap Days CDF</h3>
			<svg viewBox={`0 0 ${dcaInterOrderGapCDF.W} ${dcaInterOrderGapCDF.H}`} width="100%" style="height:65px">
				<polyline points={dcaInterOrderGapCDF.polyline} fill="none" stroke="var(--ch-teal-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				<line x1={dcaInterOrderGapCDF.toX(+dcaInterOrderGapCDF.median)} y1={dcaInterOrderGapCDF.PAD} x2={dcaInterOrderGapCDF.toX(+dcaInterOrderGapCDF.median)} y2={dcaInterOrderGapCDF.H - dcaInterOrderGapCDF.PAD} stroke="rgba(248,113,113,0.5)" stroke-width="0.8" stroke-dasharray="2,2"/>
				<text x={dcaInterOrderGapCDF.PAD} y={dcaInterOrderGapCDF.H} font-size="5.5" fill="var(--ch-axis-muted)">{dcaInterOrderGapCDF.minV}d</text>
				<text x={dcaInterOrderGapCDF.W - dcaInterOrderGapCDF.PAD} y={dcaInterOrderGapCDF.H} text-anchor="end" font-size="5.5" fill="var(--ch-axis-muted)">{dcaInterOrderGapCDF.maxV}d</text>
				<text x={dcaInterOrderGapCDF.toX(+dcaInterOrderGapCDF.median)} y={dcaInterOrderGapCDF.PAD + 6} text-anchor="middle" font-size="5" fill="var(--ch-loss-light)">med {dcaInterOrderGapCDF.median}d</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">CDF of days between consecutive DCA orders · teal S-curve · red dashed = median gap · steep rise = orders cluster in time · long tail = irregular cadence</p>
		</section>
	{/if}
	{#if dcaAssetConcentration}
		<section class="rounded-lg border border-border bg-card p-3">
			<h3 class="mb-1 text-xs font-semibold text-muted-foreground">Asset Spend Concentration (HHI {dcaAssetConcentration.hhi.toFixed(3)})</h3>
			<svg viewBox={`0 0 ${dcaAssetConcentration.W} ${dcaAssetConcentration.H}`} width="100%" style="height:65px">
				{#each dcaAssetConcentration.shares as s, i}
					{@const bh = Math.max(1, s.share * (dcaAssetConcentration.H - dcaAssetConcentration.PAD * 2))}
					{@const x = dcaAssetConcentration.PAD + i * (dcaAssetConcentration.bw + 2)}
					{@const y = dcaAssetConcentration.H - dcaAssetConcentration.PAD - bh}
					{@const color = s.share > 0.3 ? 'var(--ch-loss)' : s.share > 0.15 ? 'rgba(248,113,113,0.55)' : 'var(--ch-violet)'}
					<rect {x} {y} width={dcaAssetConcentration.bw} height={bh} fill={color} rx="1"/>
					<text x={x + dcaAssetConcentration.bw / 2} y={dcaAssetConcentration.H} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{s.asset}</text>
					<text x={x + dcaAssetConcentration.bw / 2} y={y - 2} text-anchor="middle" font-size="5" fill={color}>{(s.share * 100).toFixed(0)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Asset share of total DCA spend · HHI concentration index · red=dominant(&gt;30%) · purple=minor · low HHI = diversified DCA · high HHI = single-asset concentration risk</p>
		</section>
	{/if}
</main>
