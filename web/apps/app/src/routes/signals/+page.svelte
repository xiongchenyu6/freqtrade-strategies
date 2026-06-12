<script lang="ts">
	import type { PageData } from './$types';
	import type { EventDcaTrigger, BacktestRun, NewsItem } from '$lib/types';
	import { fmtTime, fmtUSD, fmtPct } from '$lib/utils';
	import { t, type Lang } from '$lib/i18n';
	import ChartInfo from '$lib/components/chart-info.svelte';
	import StrategyInfo from '$lib/components/strategy-info.svelte';

	let { data }: { data: PageData } = $props();
	const lang = $derived<Lang>(data.lang ?? 'zh');

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

	// F&G zone event count + avg USDT: how much we deploy per sentiment zone
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

	// --- 市场快讯 / Market wire (curated headlines, reposted verbatim) ---
	type NewsCat = 'all' | 'crypto' | 'macro' | 'equity';
	const NEWS_CATS: { cat: NewsCat; zh: string; en: string }[] = [
		{ cat: 'all', zh: '全部', en: 'All' },
		{ cat: 'crypto', zh: '加密', en: 'Crypto' },
		{ cat: 'macro', zh: '宏观', en: 'Macro' },
		{ cat: 'equity', zh: '美股', en: 'Equity' }
	];
	// Official-source chips (central banks / regulators) get an amber tint.
	const OFFICIAL_SOURCES = new Set(['Fed', 'SEC', 'ECB']);

	let newsCat = $state<NewsCat>('all');
	let newsExpanded = $state(false);

	const newsFiltered = $derived(
		newsCat === 'all' ? data.news : data.news.filter((n: NewsItem) => n.category === newsCat)
	);
	const newsShown = $derived(newsFiltered.slice(0, newsExpanded ? 60 : 20));

	/** Relative time (X 分钟/小时前) for fresh items, plain date otherwise. */
	function newsAgo(iso: string): string {
		const t = new Date(iso).getTime();
		if (!Number.isFinite(t)) return iso?.slice(0, 10) ?? '';
		const mins = Math.floor((Date.now() - t) / 60_000);
		if (mins < 1) return lang === 'zh' ? '刚刚' : 'just now';
		if (mins < 60) return lang === 'zh' ? `${mins} 分钟前` : `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return lang === 'zh' ? `${hrs} 小时前` : `${hrs}h ago`;
		return iso.slice(0, 10);
	}

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
</script>

<svelte:head>
	<title>{t(lang, 'signals.title')} · Crypto Quant</title>
</svelte:head>

<main class="w-full max-w-[1600px] mx-auto px-4 sm:px-6 py-8">
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

	<!-- 市场快讯 / Market wire — curated headlines, reposted verbatim. Renders nothing when empty/failed. -->
	{#if data.news.length > 0}
		<section class="mb-6 rounded-xl border border-border bg-card p-4">
			<div class="mb-3 flex flex-wrap items-center justify-between gap-2">
				<h2 class="text-sm font-semibold">
					📰 市场快讯 / Market wire
					<a href="/globe" class="ml-2 text-[11px] font-normal text-muted-foreground hover:text-primary hover:underline"
						>🌍 {lang === 'zh' ? '上球看' : 'On the globe'}</a
					>
				</h2>
				<div class="flex gap-2">
					{#each NEWS_CATS as c (c.cat)}
						<button
							type="button"
							onclick={() => (newsCat = c.cat)}
							class="rounded-full px-3 py-1 text-xs font-medium transition-colors"
							class:bg-primary={newsCat === c.cat}
							class:text-primary-foreground={newsCat === c.cat}
							class:bg-secondary={newsCat !== c.cat}
							class:text-muted-foreground={newsCat !== c.cat}
							class:border={newsCat !== c.cat}
							class:border-border={newsCat !== c.cat}
						>
							{lang === 'zh' ? c.zh : c.en}
						</button>
					{/each}
				</div>
			</div>
			<ul class="divide-y divide-border/60">
				{#each newsShown as n (n.link)}
					<li class="flex items-start gap-3 py-2 text-sm">
						<span class="w-16 shrink-0 pt-0.5 font-mono text-[10px] text-muted-foreground tabular-nums" title={n.published_at}>{newsAgo(n.published_at)}</span>
						<span
							class="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold {OFFICIAL_SOURCES.has(n.source)
								? 'bg-amber-950/50 text-amber-400/90 border border-amber-900/50'
								: 'bg-secondary text-muted-foreground'}"
						>{n.source}</span>
						<a
							href={n.link}
							target="_blank"
							rel="noopener"
							class="min-w-0 leading-snug text-foreground/90 hover:text-primary hover:underline"
						>{n.title} <span class="text-[10px] text-muted-foreground">↗</span></a>
					</li>
				{/each}
			</ul>
			{#if !newsExpanded && newsFiltered.length > 20}
				<button
					type="button"
					onclick={() => (newsExpanded = true)}
					class="mt-2 w-full rounded-lg border border-border bg-secondary py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
				>
					{lang === 'zh' ? '更多' : 'More'} ({newsFiltered.length - 20})
				</button>
			{/if}
			<p class="mt-3 text-[10px] text-muted-foreground">
				{lang === 'zh'
					? '标题原文转载,来源可点击 —— 我们不改写、不解读。'
					: 'Headlines reposted verbatim, sources clickable — we do not rewrite or editorialize.'}
			</p>
		</section>
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
					<li class="rounded-xl border border-border bg-card border-l-4 {borderCls} px-4 py-3">
						<!-- Single-row on lg+, wrap groups on smaller screens. -->
						<div class="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
							<span class="rounded-full px-2 py-0.5 text-xs font-bold shrink-0 {badgeCls}">{e.kind}</span>
							<span class="text-xs text-muted-foreground shrink-0 tabular-nums">{fmtTime(e.ts)}</span>
							<span class="font-medium shrink-0">BTC {fmtUSD(e.price)}</span>
							{#if e.fng != null}
								<span class="text-xs text-muted-foreground shrink-0">FnG <span class="font-mono text-foreground">{e.fng}</span></span>
							{/if}
							{#if e.severity != null}
								<span class="text-xs text-muted-foreground shrink-0">
									{lang === 'zh' ? '严重度' : 'Severity'}
									<span class="font-mono font-semibold text-foreground">{(e.severity * 100).toFixed(1)}%</span>
								</span>
							{/if}
							{#if e.amount_usdt != null}
								<span class="text-xs text-muted-foreground shrink-0">{lang === 'zh' ? '金额' : 'Amount'} <span class="font-mono text-foreground">{fmtUSD(e.amount_usdt)} USDT</span></span>
							{/if}
							{#if e.mode}
								<span class="text-xs text-muted-foreground shrink-0">mode <span class="font-mono text-foreground">{e.mode}</span></span>
							{/if}
							<span class="ml-auto rounded-full bg-orange-950/60 px-2 py-0.5 text-[10px] font-semibold text-orange-400 border border-orange-900 shrink-0">EVENT DCA</span>
						</div>
					</li>
				{:else}
					{@const r = signal.item}
					{@const profit = r.total_profit_pct ?? 0}
					<li class="rounded-xl border border-border bg-card border-l-4 border-l-green-500 px-4 py-3">
						<div class="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
							<span class="rounded-full bg-green-950/60 px-2 py-0.5 text-xs font-bold text-green-400 shrink-0">BACKTEST</span>
							<span class="text-xs text-muted-foreground shrink-0 tabular-nums">{fmtTime(r.started_at ?? r.imported_at)}</span>
							{#if r.timeframe}
								<span class="rounded bg-secondary px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground shrink-0">{r.timeframe}</span>
							{/if}
							<span class="font-semibold shrink-0">{r.strategy}</span>
							<StrategyInfo strategy={r.strategy} {lang} size="xs" />
							<span
								class:text-green-400={profit > 0}
								class:text-red-400={profit < 0}
								class:text-muted-foreground={profit === 0}
								class="font-mono font-semibold shrink-0"
							>{fmtPct(profit)}</span>
							{#if r.calmar != null}
								<span class="text-xs text-muted-foreground shrink-0">Calmar <span class="font-mono text-foreground">{r.calmar.toFixed(2)}</span></span>
							{/if}
							{#if r.sharpe != null}
								<span class="text-xs text-muted-foreground shrink-0">Sharpe <span class="font-mono text-foreground">{r.sharpe.toFixed(2)}</span></span>
							{/if}
							{#if r.total_trades != null}
								<span class="text-xs text-muted-foreground shrink-0"><span class="font-mono text-foreground">{r.total_trades}</span> trades</span>
							{/if}
							{#if r.max_drawdown_pct != null}
								<span class="text-xs text-muted-foreground shrink-0">MaxDD <span class="font-mono text-red-500">{r.max_drawdown_pct.toFixed(1)}%</span></span>
							{/if}
						</div>
					</li>
				{/if}
			{/each}
		</ul>
	{/if}

	{#if eventCalendar}
		<section class="mt-8 rounded-lg border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">{lang === 'en' ? 'Which days had signals?' : '哪些天有信号?'} <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<p class="mb-3 text-[10px] text-muted-foreground">30-Day Event Activity · DCA triggers · last 30 days</p>
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

	{#if dcaCumulativeSpend}
		{@const dcs = dcaCumulativeSpend}
		<section class="mt-6 rounded-lg border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">{lang === 'en' ? 'How much have the signals bought?' : '信号累计买入了多少?'} <ChartInfo metric="dcaTrigger" {lang} /></h2>
			<p class="mb-3 text-[10px] text-muted-foreground">Cumulative DCA Spend · {dcs.n} events · {dcs.firstDate} → {dcs.lastDate}</p>
			<svg viewBox="0 0 {dcs.W} {dcs.H}" class="w-full" style="height:{dcs.H}px">
				<polyline points={dcs.polyline} fill="none" stroke="var(--ch-violet-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={dcs.PAD} y={dcs.H - 2} font-size="7" fill="var(--ch-rule)">{dcs.firstDate}</text>
				<text x={dcs.W - dcs.PAD} y={dcs.H - 2} font-size="7" fill="var(--ch-rule)" text-anchor="end">{dcs.lastDate}</text>
				<text x={dcs.W - dcs.PAD} y="10" font-size="8" fill="var(--ch-violet-strong)" text-anchor="end">${dcs.total.toFixed(0)} total</text>
			</svg>
			<p class="mt-1 text-[10px] text-muted-foreground">Running cumulative USDT deployed across all DCA trigger events · total deployed: ${dcs.total.toFixed(0)}</p>
		</section>
	{/if}

	<details class="mt-8 rounded-xl border border-border bg-card"><summary class="cursor-pointer p-4 text-sm font-semibold text-muted-foreground">📊 高级分析(给量化爱好者)/ Advanced analytics</summary><div class="p-4 pt-0 space-y-8">
		{#if stratFreshness.length > 0}
			<section class="rounded-lg border bg-card p-5">
				<div class="mb-3 flex items-baseline justify-between">
					<h2 class="text-sm font-semibold">Strategy Freshness <ChartInfo metric="leaderboard" {lang} /></h2>
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

		{#if severityTrend}
			{@const st = severityTrend}
			<section class="rounded-lg border bg-card p-4">
				<div class="mb-2 flex items-baseline justify-between">
					<h2 class="text-sm font-semibold">Market Stress Trend <span class="ml-1 font-normal text-muted-foreground text-xs">(7-event rolling avg severity)</span> <ChartInfo metric="fearGreed" {lang} /></h2>
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
			<section class="rounded-lg border bg-card p-4">
				<h2 class="mb-3 text-sm font-semibold">Weekly Signal Mix <span class="ml-1 font-normal text-muted-foreground text-xs">(last 8 weeks · stacked by kind)</span> <ChartInfo metric="dcaTrigger" {lang} /></h2>
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
			<section class="rounded-lg border bg-card p-4">
				<div class="mb-3 flex items-baseline justify-between">
					<h2 class="text-sm font-semibold">Fear &amp; Greed at Trigger Time <span class="ml-1 font-normal text-muted-foreground text-xs">({fh.total} events with FNG data)</span> <ChartInfo metric="fearGreed" {lang} /></h2>
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

		{#if fngZoneEventCount}
			<section class="rounded-lg border bg-card p-5">
				<h2 class="mb-3 text-sm font-semibold">Events by Fear & Greed Zone
					<span class="ml-1 font-normal text-muted-foreground text-xs">(count + avg USDT deployed per sentiment zone)</span> <ChartInfo metric="fearGreed" {lang} /></h2>
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
	</div></details>
</main>
