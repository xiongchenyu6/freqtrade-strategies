<script lang="ts">
	import type { PageData } from './$types';
	import Kpi from '$lib/components/kpi.svelte';
	import PersonalPlan from '$lib/components/personal-plan.svelte';
	import BinanceConnect from '$lib/components/binance-connect.svelte';
	import { fmtTime, fmtUSD } from '$lib/utils';
	import { t, type Lang } from '$lib/i18n';
	import { onMount } from 'svelte';
	import ChartInfo from '$lib/components/chart-info.svelte';
	import AlertSubscribe from '$lib/components/alert-subscribe.svelte';

	let { data }: { data: PageData } = $props();
	const lang = $derived<Lang>(data.lang ?? 'zh');

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
	const SCENARIOS = $derived([
		{ label: lang === 'en' ? 'Bear (0% CAGR)' : '熊市 (0%)', cagr: 0,   color: 'var(--ch-loss-strong)' },
		{ label: lang === 'en' ? 'Base (40% CAGR)' : '基础 (40%)', cagr: 0.4, color: 'var(--ch-warn)' },
		{ label: lang === 'en' ? 'Extreme bull (100% CAGR, unlikely to repeat)' : '极端牛市 (100%,历史不可重复)', cagr: 1.0, color: 'var(--ch-profit-strong)' },
	] as const);
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

	function fmt(key: string, vars: Record<string, string | number>) {
		let s = t(lang, key);
		for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v));
		return s;
	}

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

	// Individual trigger amount distribution: histogram of DCA amounts
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

	// ===== Advanced analytics (collapsed by default) =====

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

	// Cumulative USDT deployed per kind over time — shows which kinds contribute most capital
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
</script>

<svelte:head><title>{t(lang, 'dca.title')}</title></svelte:head>

<main class="w-full max-w-[1600px] mx-auto px-4 sm:px-6 py-8">
	<header class="mb-8">
		<h1 class="text-3xl font-semibold tracking-tight">{t(lang, 'dca.title')}</h1>
		<p class="mt-2 max-w-3xl text-sm text-muted-foreground">{t(lang, 'dca.subtitle')}</p>
	</header>

	<!-- Telegram alert subscription — the component handles anonymous visitors itself. -->
	<div class="mb-8">
		<AlertSubscribe />
	</div>

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
			<h2 class="mb-1 text-sm font-semibold">{lang === 'en' ? 'How much has been invested in total?' : '一共投了多少钱?'}</h2>
			<p class="mb-3 text-[10px] text-muted-foreground">{lang === 'en' ? 'Cumulative deployment curve' : '累积投入曲线'}</p>
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

	{#if kindAmountChart}
		<section class="mb-8 rounded-lg border bg-card p-5">
			<h2 class="mb-1 text-sm font-semibold">{lang === 'en' ? 'Which signal types got the money?' : '钱花在哪种信号上?'} <ChartInfo metric="signalKind" {lang} /></h2>
			<p class="mb-4 text-[10px] text-muted-foreground">{lang === 'en' ? 'FLASH crash / FAST rapid drop / SUSTAIN slow bleed / CAPITUL capitulation selling — glossary at /start' : 'FLASH 闪崩 / FAST 快速下跌 / SUSTAIN 阴跌 / CAPITUL 投降式抛售 — 词典见 /start'} · {data.triggers.length} {lang === 'en' ? 'triggers' : '次触发'}</p>
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
			<p class="mt-2 text-[10px] text-muted-foreground">{lang === 'en' ? 'Bar width = relative USDT deployed · % = share of total capital · × = trigger count' : '条宽 = 相对投入金额 · % = 占总资金比例 · × = 触发次数'}</p>
		</section>
	{/if}

	{#if monthlyTriggerSummary}
		<section class="mb-8 rounded-lg border bg-card p-5">
			<h2 class="mb-1 text-sm font-semibold">{lang === 'en' ? 'How much each month, and how many triggers?' : '每个月投了多少、触发了几次?'} <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<p class="mb-3 text-[10px] text-muted-foreground">{lang === 'en' ? 'Monthly trigger summary' : '月度触发汇总'} · {monthlyTriggerSummary.reduce((s,m)=>s+m.count,0)} {lang === 'en' ? 'triggers in the last 12 months' : '次触发 · 最近 12 个月'}</p>
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
			<p class="mt-2 text-[10px] text-muted-foreground">{lang === 'en' ? 'Bar width = trigger count · right = total USDT deployed that month' : '条宽 = 触发次数 · 右侧 = 当月投入总额 (USDT)'}</p>
		</section>
	{/if}

	{#if triggerAmountDistribution}
		{@const tad = triggerAmountDistribution}
		<section class="mb-8 rounded-lg border border-border bg-card p-5">
			<h2 class="mb-1 text-sm font-semibold">{lang === 'en' ? 'How big is a typical single buy?' : '单次买入一般是多大金额?'} <ChartInfo metric="distribution" {lang} /></h2>
			<p class="mb-3 text-[10px] text-muted-foreground">{lang === 'en' ? 'Histogram of individual trigger sizes' : '单次买入金额分布直方图'} · {lang === 'en' ? 'avg' : '平均'} ${tad.avg.toFixed(0)} · {lang === 'en' ? 'median' : '中位数'} ${tad.median.toFixed(0)}</p>
			<div class="mt-3 flex items-end gap-1" style="height:72px">
				{#each tad.buckets as b}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<span class="font-mono text-[8px] text-muted-foreground">{b.count > 0 ? b.count : ''}</span>
						<div class="w-full rounded-t" style="height:{Math.max(2, b.barPct * 0.62)}px; background:var(--ch-violet-light)"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>${tad.mn.toFixed(0)}</span><span>→ USDT {lang === 'en' ? 'per trigger' : '每次买入'} →</span><span>${tad.mx.toFixed(0)}</span>
			</div>
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

	<section class="rounded-lg border border-dashed bg-card p-5 text-xs text-muted-foreground">
		<b class="text-foreground">{t(lang, 'dca.how')}</b>
		{t(lang, 'dca.howText')}
		<a class="ml-2 text-primary hover:underline" href="/docs/strategies/event-dca/">{t(lang, 'dca.howLink')}</a>
	</section>

	<details class="mt-8 rounded-xl border border-border bg-card">
		<summary class="cursor-pointer p-4 text-sm font-semibold text-muted-foreground">📊 高级分析(给量化爱好者)/ Advanced analytics</summary>
		<div class="p-4 pt-0 space-y-8">
			{#if severityHistogram}
				{@const sh = severityHistogram}
				<section class="rounded-lg border bg-card p-5">
					<h2 class="mb-4 text-sm font-semibold">Signal Severity Distribution <span class="ml-1 font-normal text-muted-foreground text-xs">({sh.total} triggers · severity 0 = mild → 1 = extreme)</span> <ChartInfo metric="fearGreed" {lang} /></h2>
					<div class="flex items-end gap-1">
						{#each sh.buckets as b}
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

			{#if sevAmountScatter}
				{@const sa = sevAmountScatter}
				<section class="rounded-lg border bg-card p-5">
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

			{#if dcaAmountTrend}
				{@const dat = dcaAmountTrend}
				<section class="rounded-lg border bg-card p-5">
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

			{#if avgAmountBySeverity}
				<section class="rounded-lg border bg-card p-5">
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
				<section class="rounded-lg border bg-card p-5">
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

			{#if fngKindAvg}
				<section class="rounded-lg border border-border bg-card p-5">
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

			{#if kindCumulativeLines}
				{@const kcl = kindCumulativeLines}
				<section class="rounded-lg border border-border bg-card p-5">
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
		</div>
	</details>
</main>
