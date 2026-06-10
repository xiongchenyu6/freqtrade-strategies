<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { subscribeTo, realtimeStatus, type RealtimeStatus } from '$lib/realtime';
	import type { PageData } from './$types';
	import type { BacktestRun, LiveTrade, EventDcaTrigger } from '$lib/types';
	import { fmtPct, fmtTime, fmtUSD } from '$lib/utils';
	import { t, type Lang } from '$lib/i18n';
	import StatusPill from '$lib/components/status-pill.svelte';
	import ChartInfo from '$lib/components/chart-info.svelte';
	import StrategyInfo from '$lib/components/strategy-info.svelte';

	let { data }: { data: PageData } = $props();
	const lang = $derived<Lang>(data.lang ?? 'zh');
	const en = $derived(lang === 'en');

	// Fields referenced by some optional charts that are NOT part of the
	// api.live_trades row (legacy freqtrade payloads only) — typed optional so
	// those charts degrade to "no data" instead of failing the type-check.
	type LiveRow = LiveTrade & {
		trade_duration_min?: number | null;
		trade_duration?: number | null;
		max_drawdown_pct?: number | null;
		exchange?: string | null;
		trade_direction?: string | null;
	};

	let runs = $state<BacktestRun[]>(data.runs);
	let trades = $state<LiveRow[]>(data.trades);
	let events = $state<EventDcaTrigger[]>(data.events);
	let status = $state<RealtimeStatus>('idle');
	let feed = $state<Array<{ kind: string; msg: string; ts: string; hot?: boolean }>>([]);

	// --- P&L panel ---
	let prices = $state<Record<string, number>>({});
	let pricesUpdatedAt = $state<Date | null>(null);
	let pricesPending = $state(false);

	const openTrades = $derived(trades.filter((t) => !t.close_date));
	const liveTrades = $derived(data.trades as LiveRow[]);
	const closedTrades = $derived(data.closedTrades as LiveRow[]);

	// Convert freqtrade pair "BTC/USDT" → Binance symbol "BTCUSDT"
	function toBinanceSymbol(pair: string) {
		return pair.replace('/', '');
	}

	async function fetchPrices() {
		if (openTrades.length === 0) return;
		const symbols = [...new Set(openTrades.map((t) => toBinanceSymbol(t.pair)))];
		if (symbols.length === 0) return;
		pricesPending = true;
		try {
			const query = encodeURIComponent(JSON.stringify(symbols));
			const res = await fetch(`https://api.binance.com/api/v3/ticker/price?symbols=${query}`);
			if (res.ok) {
				const data: Array<{ symbol: string; price: string }> = await res.json();
				const map: Record<string, number> = {};
				for (const d of data) map[d.symbol] = parseFloat(d.price);
				prices = map;
				pricesUpdatedAt = new Date();
			}
		} catch {
			// silently ignore — stale prices remain
		} finally {
			pricesPending = false;
		}
	}

	function holdingDuration(openDate: string) {
		const ms = Date.now() - new Date(openDate).getTime();
		const h = Math.floor(ms / 3600000);
		const d = Math.floor(h / 24);
		return d > 0 ? `${d}d ${h % 24}h` : `${h}h`;
	}

	// uPnL for one trade given current price
	function calcUPnL(trade: LiveTrade, currentPrice: number) {
		if (!trade.open_rate || !trade.stake_amount) return 0;
		const qty = trade.stake_amount / trade.open_rate;
		return trade.is_short
			? (trade.open_rate - currentPrice) * qty
			: (currentPrice - trade.open_rate) * qty;
	}
	const unsubs: Array<() => void> = [];

	let notifPermission = $state<NotificationPermission>('default');
	let hasNotifications = $state(false);

	// Position size calculator
	let calcAccount = $state(100000);
	let calcRiskPct = $state(1);
	let calcEntry = $state(0);
	let calcStop = $state(0);

	function browserNotify(title: string, body: string) {
		if (notifPermission !== 'granted') return;
		try { new Notification(title, { body, icon: '/favicon.png', tag: 'dca-alert' }); } catch { /* ignore */ }
	}

	async function requestNotifPermission() {
		if (!('Notification' in window)) return;
		const result = await Notification.requestPermission();
		notifPermission = result;
	}

	function push(kind: string, msg: string) {
		feed = [{ kind, msg, ts: new Date().toISOString(), hot: true }, ...feed.slice(0, 99)];
		setTimeout(() => {
			feed = feed.map((f, i) => (i === 0 ? { ...f, hot: false } : f));
		}, 2000);
		if (kind === 'dca') browserNotify('DCA Trigger 🎯', msg);
	}

	onMount(() => {
		hasNotifications = 'Notification' in window;
		if (hasNotifications) notifPermission = Notification.permission;
		fetchPrices();
		const priceTimer = setInterval(fetchPrices, 30_000);
		unsubs.push(() => clearInterval(priceTimer));

		unsubs.push(
			subscribeTo<BacktestRun>('backtest_runs', (p) => {
				if (p.eventType === 'INSERT') {
					runs = [p.new, ...runs].slice(0, 10);
					push('backtest', `#${p.new.id} ${p.new.strategy} · ${p.new.total_trades} trades · ${fmtPct(p.new.total_profit_pct)}`);
				} else if (p.eventType === 'UPDATE') {
					runs = runs.map((r) => (r.id === p.new.id ? p.new : r));
				}
			})
		);
		unsubs.push(
			subscribeTo<LiveTrade>('trades', (p) => {
				if (p.eventType === 'INSERT') {
					trades = [p.new, ...trades].slice(0, 10);
					const dir = p.new.is_short ? '▼ SHORT' : '▲ LONG';
					push('trade', `${dir} ${p.new.pair} @ ${fmtUSD(p.new.open_rate)} (${p.new.bot_name})`);
					fetchPrices();
				} else if (p.eventType === 'UPDATE') {
					trades = trades.map((t) =>
						t.bot_name === p.new.bot_name && t.open_date === p.new.open_date ? p.new : t
					);
					if (p.new.close_date && !p.old?.close_date) {
						push('close', `${p.new.pair} closed: ${fmtPct((p.new.profit_pct ?? 0) * 100)}`);
					}
				}
			})
		);
		unsubs.push(
			subscribeTo<EventDcaTrigger>('event_dca_triggers', (p) => {
				if (p.eventType === 'INSERT') {
					events = [p.new, ...events].slice(0, 10);
					push(
						'dca',
						`${p.new.kind} · ${fmtUSD(p.new.price)} · sev ${((p.new.severity ?? 0) * 100).toFixed(2)}% · $${Math.round(p.new.amount_usdt ?? 0)}`
					);
				}
			})
		);

		// Reactive status via store — no polling
		const unsubStatus = realtimeStatus.subscribe((s) => (status = s));
		unsubs.push(unsubStatus);
	});

	onDestroy(() => unsubs.forEach((fn) => fn()));

	// Daily closed P&L chart
	const dailyPnl = $derived.by(() => {
		const closed = closedTrades.filter(t => t.close_date && t.profit_abs != null);
		if (closed.length === 0) return null;
		const byDay = new Map<string, number>();
		for (const t of closed) {
			const day = t.close_date!.slice(0, 10);
			byDay.set(day, (byDay.get(day) ?? 0) + t.profit_abs!);
		}
		const days = [...byDay.entries()].sort((a, b) => a[0].localeCompare(b[0]));
		if (days.length < 2) return null;
		const vals = days.map(d => d[1]);
		const maxAbs = Math.max(1, ...vals.map(Math.abs));
		const W = 560, H = 80;
		const barW = Math.max(2, (W / days.length) - 1);
		const bars = days.map(([date, v], i) => ({
			x: i * (W / days.length),
			h: Math.abs(v) / maxAbs * (H / 2),
			positive: v >= 0,
			date,
			v,
		}));
		const cumulative = vals.reduce<number[]>((acc, v) => {
			acc.push((acc[acc.length - 1] ?? 0) + v);
			return acc;
		}, []);
		const cMin = Math.min(0, ...cumulative), cMax = Math.max(0.01, ...cumulative);
		const cumPts = cumulative.map((v, i) => {
			const x = (i / (cumulative.length - 1)) * W;
			const y = H - ((v - cMin) / (cMax - cMin)) * H;
			return `${x.toFixed(1)},${y.toFixed(1)}`;
		}).join(' ');
		return { bars, barW, W, H, maxAbs, cumPts, total: cumulative[cumulative.length - 1] };
	});

	// Pair P&L breakdown from closedTrades
	const pairPnl = $derived.by(() => {
		const closed = closedTrades.filter(t => t.close_date && t.profit_abs != null && t.pair);
		if (closed.length < 3) return null;
		const map = new Map<string, { profit: number; count: number; wins: number }>();
		for (const t of closed) {
			if (!map.has(t.pair!)) map.set(t.pair!, { profit: 0, count: 0, wins: 0 });
			const p = map.get(t.pair!)!;
			p.profit += t.profit_abs!;
			p.count++;
			if ((t.profit_pct ?? 0) > 0) p.wins++;
		}
		const rows = [...map.entries()]
			.map(([pair, v]) => ({ pair, ...v, wr: v.wins / v.count }))
			.sort((a, b) => b.profit - a.profit);
		const maxAbs = Math.max(1, ...rows.map(r => Math.abs(r.profit)));
		return { rows, maxAbs };
	});

	const kindColor = {
		backtest: 'text-blue-400',
		trade: 'text-green-400',
		close: 'text-yellow-400',
		dca: 'text-purple-400'
	} as Record<string, string>;

	// Monthly P&L heatmap from live closed trades
	const liveMonthlyPnl = $derived.by(() => {
		const closed = closedTrades.filter(t => t.close_date && t.profit_abs != null);
		if (closed.length < 5) return null;
		const byYM = new Map<string, number>();
		for (const t of closed) {
			const key = t.close_date!.slice(0, 7);
			byYM.set(key, (byYM.get(key) ?? 0) + t.profit_abs!);
		}
		const keys = [...byYM.keys()].sort();
		const years = [...new Set(keys.map(k => k.slice(0, 4)))].sort();
		if (years.length === 0) return null;
		const vals = [...byYM.values()];
		const maxAbs = Math.max(1, ...vals.map(Math.abs));
		const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
		const grid = years.map(yr =>
			MONTHS.map((_, mi) => {
				const key = `${yr}-${String(mi + 1).padStart(2, '0')}`;
				const v = byYM.get(key) ?? null;
				return { key, v, pct: v == null ? 0 : v / maxAbs };
			})
		);
		const winMonths = vals.filter(v => v > 0).length;
		const total = vals.reduce((a, b) => a + b, 0);
		return { grid, years, MONTHS, total, winMonths, total_months: byYM.size };
	});

	const weeklyPnl = $derived.by(() => {
		const closed = closedTrades.filter(t => t.close_date && t.profit_abs != null);
		if (closed.length < 5) return null;
		const byWeek = new Map<string, number>();
		for (const t of closed) {
			const d = new Date(t.close_date!);
			// ISO week key: YYYY-Www
			const jan4 = new Date(d.getFullYear(), 0, 4);
			const startOfWeek = new Date(jan4);
			startOfWeek.setDate(jan4.getDate() - ((jan4.getDay() + 6) % 7));
			const weekNum = Math.ceil(((d.getTime() - startOfWeek.getTime()) / 86400000 + 1) / 7);
			const key = `${d.getFullYear()}-W${String(weekNum).padStart(2, '0')}`;
			byWeek.set(key, (byWeek.get(key) ?? 0) + t.profit_abs!);
		}
		const weeks = [...byWeek.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(-26);
		if (weeks.length < 3) return null;
		const vals = weeks.map(w => w[1]);
		const maxAbs = Math.max(1, ...vals.map(Math.abs));
		const W = 560, H = 80;
		const bars = weeks.map(([week, v], i) => ({
			x: i * (W / weeks.length),
			h: Math.abs(v) / maxAbs * (H / 2 - 2),
			positive: v >= 0,
			week,
			v,
		}));
		const wins = vals.filter(v => v > 0).length;
		const total = vals.reduce((a, b) => a + b, 0);
		return { bars, W, H, barW: Math.max(3, W / weeks.length - 1), maxAbs, wins, total, weeks: weeks.length };
	});

	// Closed trade equity curve: running cumulative P&L
	const closedEquityCurve = $derived.by(() => {
		const sorted = closedTrades
			.filter(t => t.close_date && t.profit_abs != null)
			.sort((a, b) => a.close_date!.localeCompare(b.close_date!));
		if (sorted.length < 5) return null;
		let running = 0;
		const pts = sorted.map((t, i) => {
			running += t.profit_abs!;
			return { i, profit: running, date: t.close_date!.slice(0, 10) };
		});
		const vals = pts.map(p => p.profit);
		const pMin = Math.min(0, ...vals), pMax = Math.max(0.001, ...vals);
		const W = 560, H = 80, PAD = 6;
		const toX = (i: number) => PAD + (i / Math.max(1, pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - pMin) / (pMax - pMin || 0.001)) * (H - PAD * 2);
		const zeroY = toY(0);
		const polyline = pts.map(p => `${toX(p.i).toFixed(1)},${toY(p.profit).toFixed(1)}`).join(' ');
		const final = vals[vals.length - 1];
		const peak = Math.max(...vals);
		const trough = Math.min(...vals);
		return { polyline, W, H, PAD, zeroY, pMin, pMax, final, peak, trough, n: pts.length };
	});

	// Trade profit % distribution histogram
	const tradeProfitDist = $derived.by(() => {
		const vals = closedTrades.filter(t => t.profit_pct != null).map(t => t.profit_pct! * 100);
		if (vals.length < 5) return null;
		const BUCKETS = [
			{ label: '<-5%', lo: -Infinity, hi: -5, count: 0, color: 'var(--ch-loss)' },
			{ label: '-5–0%', lo: -5, hi: 0, count: 0, color: 'var(--ch-loss-light)' },
			{ label: '0–3%', lo: 0, hi: 3, count: 0, color: 'var(--ch-warn-light)' },
			{ label: '3–10%', lo: 3, hi: 10, count: 0, color: 'var(--ch-profit-light)' },
			{ label: '10%+', lo: 10, hi: Infinity, count: 0, color: 'var(--ch-profit-strong)' },
		];
		for (const v of vals) {
			const b = BUCKETS.find(bk => v >= bk.lo && v < bk.hi);
			if (b) b.count++;
		}
		const maxCount = Math.max(1, ...BUCKETS.map(b => b.count));
		const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
		return { buckets: BUCKETS.map(b => ({ ...b, barPct: (b.count / maxCount) * 100 })), avg, total: vals.length };
	});

	// Live exit reason breakdown
	const liveExitReasons = $derived.by(() => {
		const closed = closedTrades.filter(t => t.close_date && t.profit_abs != null && t.exit_reason);
		if (closed.length < 3) return null;
		const map = new Map<string, { count: number; profit: number; wins: number }>();
		for (const t of closed) {
			const r = t.exit_reason!;
			if (!map.has(r)) map.set(r, { count: 0, profit: 0, wins: 0 });
			const e = map.get(r)!;
			e.count++;
			e.profit += t.profit_abs!;
			if ((t.profit_pct ?? 0) > 0) e.wins++;
		}
		const rows = [...map.entries()]
			.map(([reason, v]) => ({ reason, ...v, wr: v.wins / v.count }))
			.sort((a, b) => b.count - a.count)
			.slice(0, 12);
		const maxCount = Math.max(1, ...rows.map(r => r.count));
		return rows.map(r => ({ ...r, barPct: (r.count / maxCount) * 100 }));
	});

	// Monthly win rate trend: last 12 months of closed trade win rate
	const monthlyWinRateTrend = $derived.by(() => {
		const closed = closedTrades.filter(t => t.close_date && t.profit_pct != null);
		if (closed.length < 10) return null;
		const now = new Date();
		const months = Array.from({ length: 12 }, (_, i) => {
			const d = new Date(now.getFullYear(), now.getMonth() - (11 - i), 1);
			const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
			const label = d.toLocaleDateString('en', { month: 'short' });
			return { key, label, wins: 0, total: 0 };
		});
		for (const t of closed) {
			const key = t.close_date!.slice(0, 7);
			const m = months.find(m => m.key === key);
			if (!m) continue;
			m.total++;
			if ((t.profit_pct ?? 0) > 0) m.wins++;
		}
		const active = months.filter(m => m.total >= 2);
		if (active.length < 3) return null;
		const W = 520, H = 80, PAD = 16;
		const wrs = active.map(m => m.wins / m.total);
		const toX = (i: number) => PAD + (i / (active.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - v * (H - PAD * 2);
		const pts = active.map((m, i) => `${toX(i).toFixed(1)},${toY(m.wins / m.total).toFixed(1)}`).join(' ');
		const avgWr = wrs.reduce((a, b) => a + b, 0) / wrs.length;
		return { active, pts, W, H, PAD, avgWr, zeroY: toY(0.5) };
	});

	// Rolling 20-trade win rate sparkline: shows whether performance is improving or degrading
	const rollingWinRate = $derived.by(() => {
		const closed = closedTrades
			.filter(t => t.close_date && t.profit_pct != null)
			.sort((a, b) => a.close_date!.localeCompare(b.close_date!));
		if (closed.length < 25) return null;
		const W = 560, H = 80, PAD = 8;
		const WINDOW = 20;
		const points: { i: number; wr: number; date: string }[] = [];
		for (let i = WINDOW - 1; i < closed.length; i++) {
			const slice = closed.slice(i - WINDOW + 1, i + 1);
			const wins = slice.filter(t => (t.profit_pct ?? 0) > 0).length;
			points.push({ i: i - WINDOW + 1, wr: wins / WINDOW, date: closed[i].close_date!.slice(0, 10) });
		}
		const toX = (idx: number) => PAD + (idx / Math.max(1, points.length - 1)) * (W - PAD * 2);
		const toY = (wr: number) => PAD + (1 - wr) * (H - PAD * 2);
		const fiftyY = toY(0.5);
		const polyline = points.map(p => `${toX(p.i).toFixed(1)},${toY(p.wr).toFixed(1)}`).join(' ');
		const lastWr = points[points.length - 1]?.wr ?? 0;
		const avgWr = points.reduce((s, p) => s + p.wr, 0) / points.length;
		return { polyline, W, H, PAD, fiftyY, lastWr, avgWr, count: points.length, firstDate: points[0].date, lastDate: points[points.length - 1].date };
	});

	// Profit factor per bot: gross win USDT / gross loss USDT per bot_name
	const profitFactorByBot = $derived.by(() => {
		const closed = closedTrades.filter(t => t.bot_name && t.profit_abs != null);
		if (closed.length < 5) return null;
		const map = new Map<string, { wins: number; losses: number }>();
		for (const t of closed) {
			if (!map.has(t.bot_name!)) map.set(t.bot_name!, { wins: 0, losses: 0 });
			const e = map.get(t.bot_name!)!;
			if (t.profit_abs! > 0) e.wins += t.profit_abs!;
			else e.losses += Math.abs(t.profit_abs!);
		}
		const rows = [...map.entries()]
			.map(([bot, { wins, losses }]) => ({ bot, pf: losses === 0 ? (wins > 0 ? 4 : 1) : Math.min(8, wins / losses), wins, losses }))
			.sort((a, b) => b.pf - a.pf);
		if (rows.length < 1) return null;
		const maxPf = Math.max(0.01, rows[0].pf);
		return rows.map(r => ({ ...r, barPct: (r.pf / maxPf) * 100 }));
	});

</script>

<svelte:head>
	<title>{t(lang, 'live.title')} · Crypto Quant</title>
</svelte:head>

<main class="w-full max-w-[1600px] mx-auto px-4 sm:px-6 py-8">
	<div class="mb-4 flex flex-wrap items-start justify-between gap-3">
		<div>
			<h1 class="text-2xl font-semibold tracking-tight">{t(lang, 'live.title')}</h1>
			<p class="mt-1 text-sm text-muted-foreground">{t(lang, 'live.subtitle')}</p>
		</div>
		<div class="flex items-center gap-2">
			{#if hasNotifications && notifPermission !== 'granted'}
				<button
					type="button"
					onclick={requestNotifPermission}
					class="flex items-center gap-1.5 rounded-md border border-border bg-secondary px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
					title="Get browser notifications for DCA alerts"
				>
					🔔 {notifPermission === 'denied' ? 'Notifications blocked' : 'Enable alerts'}
				</button>
			{:else if hasNotifications && notifPermission === 'granted'}
				<span class="rounded-full bg-green-950/60 px-2.5 py-1 text-[10px] text-green-400">🔔 Alerts on</span>
			{/if}
			<span
				class="rounded-full px-3 py-1 text-xs font-mono"
				class:bg-green-900={status === 'open'}
				class:text-green-400={status === 'open'}
				class:bg-yellow-900={status === 'connecting'}
				class:text-yellow-400={status === 'connecting'}
				class:bg-red-900={status === 'closed' || status === 'closing'}
				class:text-red-400={status === 'closed' || status === 'closing'}
				class:bg-muted={status === 'idle'}
				class:text-muted-foreground={status === 'idle'}
			>
				{t(lang, 'live.wsStatus')}: {status}
			</span>
		</div>
	</div>

	<!-- ── P&L Panel ─────────────────────────────────────────────── -->
	<section class="mt-4 rounded-lg border bg-card">
		<div class="flex items-center justify-between border-b border-border px-4 py-3">
			<h2 class="text-sm font-semibold">{t(lang, 'live.pnl.title')}</h2>
			<div class="flex items-center gap-3 text-xs text-muted-foreground">
				{#if pricesUpdatedAt}
					<span>{t(lang, 'live.pnl.refreshed')}: {pricesUpdatedAt.toLocaleTimeString()}</span>
				{/if}
				<button
					type="button"
					onclick={fetchPrices}
					disabled={pricesPending}
					class="rounded border border-border px-2 py-0.5 hover:bg-accent disabled:opacity-40"
				>
					{pricesPending ? '…' : '↻'}
				</button>
			</div>
		</div>

		{#if openTrades.length === 0}
			<div class="px-4 py-6 text-center text-xs text-muted-foreground">
				{t(lang, 'live.pnl.empty')}
			</div>
		{:else}
			{@const rows = openTrades.map((t) => {
				const sym = toBinanceSymbol(t.pair);
				const cur = prices[sym] ?? null;
				const upnl = cur !== null ? calcUPnL(t, cur) : null;
				const chgPct = cur !== null && t.open_rate ? ((cur - t.open_rate) / t.open_rate) * 100 * (t.is_short ? -1 : 1) : null;
				return { t, cur, upnl, chgPct };
			})}
			{@const totalStake = openTrades.reduce((s, t) => s + (t.stake_amount ?? 0), 0)}
			{@const totalUPnL = rows.reduce((s, r) => s + (r.upnl ?? 0), 0)}

			<!-- Allocation donut -->
			{@const donutPairs = openTrades.map((t, i) => ({ pair: t.pair, stake: t.stake_amount ?? 0 }))}
			{@const donutTotal = donutPairs.reduce((s, p) => s + p.stake, 0)}
			{#if donutTotal > 0}
				{@const COLORS = ['#4a9eff','#7b5fff','#34d399','#f59e0b','#f87171','#a78bfa','#fb923c','#60a5fa']}
				{@const slices = (() => {
					let start = -Math.PI / 2;
					return donutPairs.map((p, i) => {
						const frac = p.stake / donutTotal;
						const sweep = frac * 2 * Math.PI;
						const x1 = 50 + 36 * Math.cos(start);
						const y1 = 50 + 36 * Math.sin(start);
						const x2 = 50 + 36 * Math.cos(start + sweep);
						const y2 = 50 + 36 * Math.sin(start + sweep);
						const lx = 50 + 28 * Math.cos(start + sweep / 2);
						const ly = 50 + 28 * Math.sin(start + sweep / 2);
						const large = sweep > Math.PI ? 1 : 0;
						const d = `M50,50 L${x1.toFixed(1)},${y1.toFixed(1)} A36,36 0 ${large},1 ${x2.toFixed(1)},${y2.toFixed(1)} Z`;
						const result = { d, color: COLORS[i % COLORS.length], pair: p.pair, pct: (frac * 100).toFixed(1), lx, ly };
						start += sweep;
						return result;
					});
				})()}
				<div class="flex items-center gap-4 border-b border-border px-4 py-3">
					<svg viewBox="0 0 100 100" width="80" height="80" class="shrink-0">
						{#each slices as s}
							<path d={s.d} fill={s.color} opacity="0.85" />
						{/each}
						<circle cx="50" cy="50" r="20" fill="var(--color-card)" />
					</svg>
					<div class="flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
						{#each slices as s}
							<span class="flex items-center gap-1">
								<span class="inline-block h-2 w-2 rounded-full" style="background:{s.color}"></span>
								<span class="font-mono text-foreground">{s.pair}</span>
								<span class="text-muted-foreground">{s.pct}%</span>
							</span>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Summary bar -->
			<div class="flex flex-wrap items-center gap-6 border-b border-border px-4 py-2 font-mono text-sm">
				<div>
					<span class="text-xs text-muted-foreground">{t(lang, 'live.pnl.stake')}</span>
					<span class="ml-2 font-semibold">${totalStake.toFixed(0)}</span>
				</div>
				<div>
					<span class="text-xs text-muted-foreground">{t(lang, 'live.pnl.total')} uPnL</span>
					<span
						class="ml-2 text-lg font-bold"
						class:text-green-400={totalUPnL > 0}
						class:text-red-400={totalUPnL < 0}
						class:text-muted-foreground={totalUPnL === 0}
					>
						{totalUPnL >= 0 ? '+' : ''}{totalUPnL.toFixed(2)} USDT
					</span>
					{#if totalStake > 0}
						<span
							class="ml-1 text-xs"
							class:text-green-400={totalUPnL > 0}
							class:text-red-400={totalUPnL < 0}
						>
							({((totalUPnL / totalStake) * 100).toFixed(2)}%)
						</span>
					{/if}
				</div>
				<div class="text-xs text-muted-foreground">{openTrades.length} open</div>
			</div>

			<!-- Per-position rows -->
			<div class="overflow-x-auto">
				<table class="w-full text-xs">
					<thead class="bg-secondary text-left text-[10px] uppercase text-muted-foreground">
						<tr>
							<th class="px-4 py-2">Pair</th>
							<th class="px-3 py-2 text-right">{t(lang, 'live.pnl.stake')}</th>
							<th class="px-3 py-2 text-right">{t(lang, 'live.pnl.entry')}</th>
							<th class="px-3 py-2 text-right">{t(lang, 'live.pnl.current')}</th>
							<th class="px-3 py-2 text-right">{t(lang, 'live.pnl.change')}</th>
							<th class="px-3 py-2 text-right">{t(lang, 'live.pnl.upnl')}</th>
							<th class="px-3 py-2 text-right">{t(lang, 'live.pnl.duration')}</th>
						</tr>
					</thead>
					<tbody class="font-mono">
						{#each rows as { t: tr, cur, upnl, chgPct } (tr.bot_name + '_' + tr.open_date)}
							<tr class="border-t border-border hover:bg-accent/30">
								<td class="px-4 py-2">
									<span class="mr-2 align-middle"><StatusPill status={tr.is_short ? 'short' : 'long'} /></span>
									<span class="font-semibold">{tr.pair}</span>
									<span class="ml-1.5 text-[10px] text-muted-foreground">{tr.bot_name}</span>
								</td>
								<td class="px-3 py-2 text-right text-muted-foreground">
									${(tr.stake_amount ?? 0).toFixed(0)}
								</td>
								<td class="px-3 py-2 text-right">{(tr.open_rate ?? 0).toLocaleString()}</td>
								<td class="px-3 py-2 text-right">
									{#if cur !== null}
										{cur.toLocaleString()}
									{:else}
										<span class="text-muted-foreground">—</span>
									{/if}
								</td>
								<td class="px-3 py-2 text-right">
									{#if chgPct !== null}
										<span class:text-green-400={chgPct > 0} class:text-red-400={chgPct < 0}>
											{chgPct >= 0 ? '+' : ''}{chgPct.toFixed(2)}%
										</span>
									{:else}
										<span class="text-muted-foreground">—</span>
									{/if}
								</td>
								<td class="px-3 py-2 text-right">
									{#if upnl !== null}
										<span class="font-semibold" class:text-green-400={upnl > 0} class:text-red-400={upnl < 0}>
											{upnl >= 0 ? '+' : ''}{upnl.toFixed(2)}
										</span>
									{:else}
										<span class="text-muted-foreground">—</span>
									{/if}
								</td>
								<td class="px-3 py-2 text-right text-muted-foreground">
									{holdingDuration(tr.open_date)}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>

	<section class="mt-4 grid gap-4 lg:grid-cols-3">
		<!-- Live feed -->
		<div class="rounded-lg border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">{t(lang, 'live.feed.title')}</h2>
			{#if feed.length === 0}
				<div class="rounded border border-dashed p-6 text-center text-xs text-muted-foreground">
					{t(lang, 'live.feed.empty')}
				</div>
			{:else}
				<ul class="max-h-[60vh] space-y-1 overflow-y-auto font-mono text-xs">
					{#each feed as f (f.ts + f.msg)}
						<li
							class="flex items-start gap-2 rounded px-2 py-1 transition-colors"
							class:bg-yellow-950={f.hot}
						>
							<span class="w-4 shrink-0 {kindColor[f.kind] ?? 'text-muted-foreground'}">
								{f.kind === 'backtest' ? '📦' : f.kind === 'trade' ? '🟢' : f.kind === 'close' ? '🏁' : '💰'}
							</span>
							<span class="shrink-0 text-[10px] text-muted-foreground">{f.ts.slice(11, 19)}</span>
							<span class="min-w-0 flex-1 text-foreground">{f.msg}</span>
						</li>
					{/each}
				</ul>
			{/if}
		</div>

		<!-- Backtest runs -->
		<div class="rounded-lg border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">{t(lang, 'live.backtests.title')}</h2>
			<ul class="space-y-1 font-mono text-xs">
				{#each runs as r (r.id)}
					<li class="flex items-center justify-between border-b border-border py-1">
						<div>
							<span class="text-muted-foreground">#{r.id}</span>
							<span class="ml-2 font-semibold">{r.strategy}</span>
							<StrategyInfo strategy={r.strategy} {lang} size="xs" />
						</div>
						<span
							class:text-green-500={(r.total_profit_pct ?? 0) > 0}
							class:text-red-500={(r.total_profit_pct ?? 0) < 0}
						>
							{fmtPct(r.total_profit_pct)}
						</span>
					</li>
				{/each}
			</ul>
		</div>

		<!-- Live trades -->
		<div class="rounded-lg border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">{t(lang, 'live.trades.title')}</h2>
			{#if trades.length === 0}
				<div class="text-center text-xs text-muted-foreground">{t(lang, 'live.trades.empty')}</div>
			{:else}
				<ul class="space-y-1 font-mono text-xs">
					{#each trades as t (t.bot_name + '_' + t.open_date)}
						<li class="border-b border-border py-1">
							<div class="flex items-center justify-between gap-2">
								<span class="inline-flex items-center gap-1.5"><StatusPill status={t.is_short ? 'short' : 'long'} /> <span class="font-semibold">{t.pair}</span></span>
								<span class="text-muted-foreground">{fmtTime(t.open_date)}</span>
							</div>
							{#if t.close_date}
								<span
									class:text-green-500={(t.profit_abs ?? 0) > 0}
									class:text-red-500={(t.profit_abs ?? 0) < 0}
								>
									${(t.profit_abs ?? 0).toFixed(2)} · {((t.profit_pct ?? 0) * 100).toFixed(2)}%
								</span>
							{:else}
								<span class="text-yellow-500">open</span>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	</section>

	<!-- Position size calculator -->
	<section class="mt-6 rounded-lg border bg-card p-5">
		<h2 class="mb-4 text-sm font-semibold">Position Size Calculator <ChartInfo metric="positionSize" {lang} /></h2>
		<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
			<label class="flex flex-col gap-1">
				<span class="text-[11px] text-muted-foreground">Account Size (USDT)</span>
				<input
					type="number"
					bind:value={calcAccount}
					min="0" step="100"
					class="rounded-md border border-border bg-background px-3 py-1.5 font-mono text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
				/>
			</label>
			<label class="flex flex-col gap-1">
				<span class="text-[11px] text-muted-foreground">Risk per Trade (%)</span>
				<input
					type="number"
					bind:value={calcRiskPct}
					min="0.1" max="100" step="0.1"
					class="rounded-md border border-border bg-background px-3 py-1.5 font-mono text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
				/>
			</label>
			<label class="flex flex-col gap-1">
				<span class="text-[11px] text-muted-foreground">Entry Price</span>
				<input
					type="number"
					bind:value={calcEntry}
					min="0" step="0.01"
					class="rounded-md border border-border bg-background px-3 py-1.5 font-mono text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
				/>
			</label>
			<label class="flex flex-col gap-1">
				<span class="text-[11px] text-muted-foreground">Stop-Loss Price</span>
				<input
					type="number"
					bind:value={calcStop}
					min="0" step="0.01"
					class="rounded-md border border-border bg-background px-3 py-1.5 font-mono text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
				/>
			</label>
		</div>
		{#if calcEntry > 0 && calcStop > 0 && calcEntry !== calcStop && calcAccount > 0 && calcRiskPct > 0}
			{@const riskUSDT = calcAccount * (calcRiskPct / 100)}
			{@const stopDist = Math.abs(calcEntry - calcStop)}
			{@const stopPct = (stopDist / calcEntry) * 100}
			{@const qty = riskUSDT / stopDist}
			{@const positionUSDT = qty * calcEntry}
			{@const positionPct = (positionUSDT / calcAccount) * 100}
			<div class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 rounded-lg border border-border bg-secondary/30 p-3">
				<div>
					<div class="text-[10px] uppercase text-muted-foreground">Max Risk</div>
					<div class="font-mono text-sm font-semibold text-red-400">${riskUSDT.toFixed(2)} USDT</div>
				</div>
				<div>
					<div class="text-[10px] uppercase text-muted-foreground">Stop Distance</div>
					<div class="font-mono text-sm font-semibold">{stopPct.toFixed(2)}%</div>
				</div>
				<div>
					<div class="text-[10px] uppercase text-muted-foreground">Position Size</div>
					<div class="font-mono text-sm font-semibold text-primary">${positionUSDT.toFixed(2)} <span class="text-xs text-muted-foreground">({positionPct.toFixed(1)}% of account)</span></div>
				</div>
				<div>
					<div class="text-[10px] uppercase text-muted-foreground">Qty</div>
					<div class="font-mono text-sm font-semibold">{qty.toFixed(4)} units</div>
				</div>
			</div>
		{/if}
	</section>

	{#if dailyPnl}
		<section class="mt-4 rounded-lg border bg-card p-5">
			<div class="mb-3 flex items-baseline justify-between">
				<h2 class="text-sm font-semibold">{en ? 'Profit or loss each day?' : '每天赚了还是亏了?'} <span class="ml-1 font-normal text-muted-foreground text-xs">Daily Closed P&L · {data.closedTrades.filter(t => t.close_date).length} trades · last {dailyPnl.bars.length} days</span> <ChartInfo metric="totalProfit" {lang} /></h2>
				<span class="font-mono text-xs" class:text-green-400={dailyPnl.total >= 0} class:text-red-400={dailyPnl.total < 0}>
					{dailyPnl.total >= 0 ? '+' : ''}{dailyPnl.total.toFixed(0)} USDT total
				</span>
			</div>
			<div class="overflow-x-auto">
				<svg viewBox="0 0 {dailyPnl.W} {dailyPnl.H * 2 + 8}" class="w-full" style="height:130px;min-width:300px">
					<!-- Zero line for bars -->
					<line x1="0" y1={dailyPnl.H} x2={dailyPnl.W} y2={dailyPnl.H} stroke="var(--ch-rule)" stroke-width="1" />
					<!-- Daily bars -->
					{#each dailyPnl.bars as b}
						<rect
							x={b.x}
							y={b.positive ? dailyPnl.H - b.h : dailyPnl.H}
							width={dailyPnl.barW}
							height={Math.max(1, b.h)}
							fill={b.positive ? 'var(--ch-profit)' : 'var(--ch-loss)'}
						>
							<title>{b.date}: {b.v >= 0 ? '+' : ''}{b.v.toFixed(2)} USDT</title>
						</rect>
					{/each}
					<!-- Cumulative equity line -->
					<polyline points={dailyPnl.cumPts.split(' ').map((p, i) => {
						const [x, y] = p.split(',');
						return `${x},${(parseFloat(y) + dailyPnl.H + 8).toFixed(1)}`;
					}).join(' ')} fill="none" stroke="rgb(251,191,36)" stroke-width="1.5" />
				</svg>
			</div>
			<div class="mt-1 flex items-center gap-4 text-[10px] text-muted-foreground">
				<span class="flex items-center gap-1"><span class="inline-block h-3 w-3 rounded-sm bg-green-500/70"></span>Profit day</span>
				<span class="flex items-center gap-1"><span class="inline-block h-3 w-3 rounded-sm bg-red-500/70"></span>Loss day</span>
				<span class="flex items-center gap-1"><span class="inline-block h-0.5 w-4 rounded bg-amber-400"></span>Cumulative</span>
			</div>
		</section>
	{/if}

	{#if pairPnl && pairPnl.rows.length > 1}
		<section class="mb-6 rounded-lg border bg-card p-5">
			<div class="mb-3 flex items-baseline justify-between">
				<h2 class="text-sm font-semibold">{en ? 'Which coins make money, which lose?' : '哪些币赚钱、哪些亏钱?'} <span class="ml-1 font-normal text-muted-foreground text-xs">Pair P&L Breakdown · {pairPnl.rows.length} pairs · closed trades</span> <ChartInfo metric="leaderboard" {lang} /></h2>
				<span class="text-[11px] text-muted-foreground">profit USDT · bar width ∝ |profit|</span>
			</div>
			<div class="space-y-1.5 font-mono text-xs">
				{#each pairPnl.rows as row}
					{@const pct = Math.abs(row.profit) / pairPnl.maxAbs * 100}
					<div class="flex items-center gap-2">
						<span class="w-28 shrink-0 truncate text-[11px] text-muted-foreground">{row.pair}</span>
						<div class="relative flex-1 h-4 rounded bg-muted/20">
							<div
								class="absolute top-0 h-full rounded {row.profit >= 0 ? 'bg-green-500/60 left-0' : 'bg-red-500/55 left-0'}"
								style="width:{pct}%"
							></div>
						</div>
						<span class="w-20 shrink-0 text-right {row.profit >= 0 ? 'text-green-400' : 'text-red-400'}">{row.profit >= 0 ? '+' : ''}{row.profit.toFixed(1)}</span>
						<span class="w-12 shrink-0 text-right text-muted-foreground">{(row.wr * 100).toFixed(0)}%wr</span>
						<span class="w-8 shrink-0 text-right text-muted-foreground">{row.count}t</span>
					</div>
				{/each}
			</div>
		</section>
	{/if}

	{#if closedEquityCurve}
		{@const ec = closedEquityCurve}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<div class="mb-3 flex items-baseline justify-between">
				<h2 class="text-sm font-semibold">{en ? 'How has the account equity moved?' : '账户净值怎么走的?'} <span class="ml-1 font-normal text-muted-foreground text-xs">Closed Trade Equity Curve · {ec.n} trades · cumulative P&amp;L</span> <ChartInfo metric="equityCurve" {lang} /></h2>
				<span class="font-mono text-xs {ec.final >= 0 ? 'text-green-400' : 'text-red-400'}">{ec.final >= 0 ? '+' : ''}{ec.final.toFixed(0)} USDT</span>
			</div>
			<svg viewBox="0 0 {ec.W} {ec.H}" class="w-full" style="height:{ec.H}px;min-width:240px">
				{#if ec.zeroY >= ec.PAD && ec.zeroY <= ec.H - ec.PAD}
					<line x1={ec.PAD} y1={ec.zeroY} x2={ec.W - ec.PAD} y2={ec.zeroY}
						stroke="var(--ch-rule-strong)" stroke-width="1" stroke-dasharray="4 3"/>
				{/if}
				<polygon
					points="{ec.PAD},{ec.zeroY} {ec.polyline} {ec.W - ec.PAD},{ec.zeroY}"
					fill={ec.final >= 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'}
				/>
				<polyline points={ec.polyline} fill="none"
					stroke={ec.final >= 0 ? '#34d399' : '#f87171'}
					stroke-width="1.5" stroke-linejoin="round"/>
				<text x={ec.W - ec.PAD} y="10" font-size="7" fill="var(--ch-profit-light)" text-anchor="end">peak {ec.peak >= 0 ? '+' : ''}{ec.peak.toFixed(0)}</text>
				{#if ec.trough < 0}
					<text x={ec.W - ec.PAD} y={ec.H - 2} font-size="7" fill="var(--ch-loss-light)" text-anchor="end">trough {ec.trough.toFixed(0)}</text>
				{/if}
			</svg>
			<p class="mt-1 text-[10px] text-muted-foreground">Each step = one closed trade · running USDT P&amp;L · start=0</p>
		</section>
	{/if}

	{#if liveMonthlyPnl}
		{@const lm = liveMonthlyPnl}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<div class="mb-3 flex items-baseline justify-between">
				<h2 class="text-sm font-semibold">{en ? 'P&L each month?' : '每个月的盈亏?'} <span class="ml-1 font-normal text-muted-foreground text-xs">Monthly P&L Calendar · {lm.winMonths}/{lm.total_months} green months</span> <ChartInfo metric="calendar" {lang} /></h2>
				<span class="font-mono text-xs {lm.total >= 0 ? 'text-green-400' : 'text-red-400'}">{lm.total >= 0 ? '+' : ''}{lm.total.toFixed(0)} USDT total</span>
			</div>
			<div class="overflow-x-auto">
				<table class="w-full min-w-[480px] text-[10px]">
					<thead>
						<tr>
							<th class="pr-2 text-right font-normal text-muted-foreground">Year</th>
							{#each lm.MONTHS as m}
								<th class="w-9 text-center font-normal text-muted-foreground">{m}</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each lm.grid as row, yi}
							<tr>
								<td class="pr-2 text-right font-mono text-muted-foreground">{lm.years[yi]}</td>
								{#each row as cell}
									<td class="p-0.5">
										{#if cell.v != null}
											{@const alpha = Math.min(0.9, 0.15 + Math.abs(cell.pct) * 0.75)}
											<div
												class="flex h-7 w-full items-center justify-center rounded font-mono text-[9px] font-semibold leading-none"
												style="background:rgba({cell.v >= 0 ? '34,197,94' : '248,113,113'},{alpha});color:{cell.v >= 0 ? '#86efac' : '#fca5a5'}"
												title="{cell.key}: {cell.v >= 0 ? '+' : ''}{cell.v.toFixed(0)} USDT"
											>
												{cell.v >= 0 ? '+' : ''}{Math.abs(cell.v) >= 1000 ? (cell.v / 1000).toFixed(1) + 'k' : cell.v.toFixed(0)}
											</div>
										{:else}
											<div class="h-7 w-full rounded bg-muted/20"></div>
										{/if}
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	{/if}

	{#if tradeProfitDist}
		{@const tpd = tradeProfitDist}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">{en ? 'Per-trade profit distribution' : '单笔交易盈亏分布'} <span class="ml-1 font-normal text-muted-foreground text-xs">Trade Profit Distribution · {tpd.total} trades · avg {tpd.avg >= 0 ? '+' : ''}{tpd.avg.toFixed(2)}%</span> <ChartInfo metric="distribution" {lang} /></h2>
			<div class="flex items-end gap-3 h-20">
				{#each tpd.buckets as b}
					<div class="flex flex-1 flex-col items-center gap-1">
						<span class="font-mono text-[9px] text-muted-foreground">{b.count > 0 ? b.count : ''}</span>
						<div class="w-full rounded-t-sm transition-all" style="height:{Math.max(2, b.barPct * 0.64)}px; background:{b.color}"></div>
						<span class="font-mono text-[9px] text-muted-foreground text-center leading-tight">{b.label}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Distribution of closed trade profit% · avg {tpd.avg >= 0 ? '+' : ''}{tpd.avg.toFixed(2)}% per trade</p>
		</section>
	{/if}

	<section class="mt-4 rounded-lg border border-dashed bg-card p-4 text-xs text-muted-foreground">
		{t(lang, 'live.how')}
	</section>

	<details class="mt-8 rounded-xl border border-border bg-card">
		<summary class="cursor-pointer p-4 text-sm font-semibold text-muted-foreground">📊 高级分析(给量化爱好者)/ Advanced analytics</summary>
		<div class="p-4 pt-0 space-y-8">
			{#if rollingWinRate}
				{@const rwr = rollingWinRate}
				<section class="mt-6 rounded-lg border bg-card p-5">
					<h2 class="mb-2 text-sm font-semibold">Rolling 20-Trade Win Rate
						<span class="ml-1 font-normal text-muted-foreground text-xs">
							(current {(rwr.lastWr * 100).toFixed(0)}% · avg {(rwr.avgWr * 100).toFixed(0)}%)
						</span> <ChartInfo metric="winRate" {lang} /></h2>
					<svg viewBox="0 0 {rwr.W} {rwr.H}" class="w-full" style="height:{rwr.H}px">
						<line x1={rwr.PAD} y1={rwr.fiftyY.toFixed(1)} x2={rwr.W - rwr.PAD} y2={rwr.fiftyY.toFixed(1)}
							stroke="var(--ch-rule-strong)" stroke-width="1" stroke-dasharray="4 3"/>
						<text x={rwr.W - rwr.PAD - 2} y={rwr.fiftyY - 3} font-size="7" fill="var(--ch-rule-strong)" text-anchor="end">50%</text>
						<polyline points={rwr.polyline} fill="none"
							stroke={rwr.lastWr >= 0.55 ? 'var(--ch-profit-strong)' : rwr.lastWr >= 0.45 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
							stroke-width="1.5" stroke-linejoin="round"/>
						<text x={rwr.PAD} y={rwr.H - 2} font-size="7" fill="var(--ch-rule)">{rwr.firstDate}</text>
						<text x={rwr.W - rwr.PAD} y={rwr.H - 2} font-size="7" fill="var(--ch-rule)" text-anchor="end">{rwr.lastDate}</text>
					</svg>
					<p class="mt-1 text-[10px] text-muted-foreground">Each point = win rate of last 20 closed trades · dashed line = 50% breakeven · green ≥55% · yellow 45–55% · red &lt;45%</p>
				</section>
			{/if}

			{#if monthlyWinRateTrend}
				{@const mwr = monthlyWinRateTrend}
				<section class="mt-6 rounded-lg border bg-card p-5">
					<h2 class="mb-2 text-sm font-semibold">Monthly Win Rate Trend
						<span class="ml-1 font-normal text-muted-foreground text-xs">(last 12 months · avg {(mwr.avgWr * 100).toFixed(1)}%)</span> <ChartInfo metric="winRate" {lang} /></h2>
					<svg viewBox="0 0 {mwr.W} {mwr.H}" class="w-full" style="height:{mwr.H}px">
						<!-- 50% reference line -->
						<line x1={mwr.PAD} y1={mwr.zeroY.toFixed(1)} x2={mwr.W - mwr.PAD} y2={mwr.zeroY.toFixed(1)}
							stroke="var(--ch-rule)" stroke-width="1" stroke-dasharray="3 2"/>
						<polyline points={mwr.pts} fill="none" stroke="var(--ch-violet-strong)" stroke-width="2" stroke-linejoin="round"/>
						{#each mwr.active as m, i}
							<circle cx={(mwr.PAD + (i / (mwr.active.length - 1)) * (mwr.W - mwr.PAD * 2)).toFixed(1)}
								cy={(mwr.H - mwr.PAD - (m.wins / m.total) * (mwr.H - mwr.PAD * 2)).toFixed(1)}
								r="3" fill={m.wins / m.total >= 0.5 ? 'var(--ch-profit-strong)' : 'var(--ch-loss)'}>
								<title>{m.label}: {m.wins}/{m.total} wins ({(m.wins/m.total*100).toFixed(1)}%)</title>
							</circle>
						{/each}
					</svg>
					<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
						<span>{mwr.active[0]?.label}</span><span>{mwr.active[mwr.active.length - 1]?.label}</span>
					</div>
					<p class="mt-1 text-[10px] text-muted-foreground">Line = monthly win rate · green dot ≥ 50% · dashed line = 50% breakeven · hover for exact counts</p>
				</section>
			{/if}

			{#if profitFactorByBot}
				<section class="mt-4 rounded-lg border bg-card p-4">
					<h2 class="mb-3 text-sm font-semibold">Profit Factor by Bot
						<span class="ml-1 font-normal text-muted-foreground text-xs">(gross wins ÷ gross losses · PF &gt;1 = profitable · PF &gt;2 = strong)</span> <ChartInfo metric="factor" {lang} /></h2>
					<div class="space-y-1.5">
						{#each profitFactorByBot as r}
							<div class="flex items-center gap-2">
								<span class="w-28 shrink-0 truncate text-xs text-foreground" title={r.bot}>{r.bot}</span>
								<div class="relative flex-1 rounded bg-muted h-5 overflow-hidden">
									<div class="absolute inset-y-0 left-0 rounded"
										style="width:{r.barPct.toFixed(1)}%; background:{r.pf >= 2 ? 'var(--ch-profit)' : r.pf >= 1 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)'}"></div>
									<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">{r.pf.toFixed(2)}</span>
								</div>
								<span class="w-20 shrink-0 text-right font-mono text-[10px] text-muted-foreground">+${r.wins.toFixed(0)} / -${r.losses.toFixed(0)}</span>
							</div>
						{/each}
					</div>
					<p class="mt-2 text-[10px] text-muted-foreground">PF = gross profit ÷ gross loss · green ≥2 · yellow 1–2 · red &lt;1 · capped at 8</p>
				</section>
			{/if}

			{#if liveExitReasons}
				<section class="mt-6 rounded-lg border bg-card p-5">
					<h2 class="mb-3 text-sm font-semibold">Exit Reason Breakdown <span class="ml-1 font-normal text-muted-foreground text-xs">({data.closedTrades.length} closed trades)</span> <ChartInfo metric="exitReason" {lang} /></h2>
					<div class="space-y-1.5">
						{#each liveExitReasons as r}
							<div class="flex items-center gap-2 text-xs">
								<span class="w-32 shrink-0 truncate font-mono text-muted-foreground" title={r.reason}>{r.reason}</span>
								<div class="relative flex-1 h-5 rounded-sm bg-muted/20 overflow-hidden">
									<div class="absolute inset-y-0 left-0 rounded-sm transition-all"
										style="width:{r.barPct.toFixed(1)}%; background:hsl({Math.round(r.wr * 120)},55%,38%)"></div>
									<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">{r.count}×</span>
								</div>
								<span class="w-20 shrink-0 text-right font-mono text-[10px]"
									class:text-green-400={r.profit > 0} class:text-red-400={r.profit < 0}
								>{r.profit >= 0 ? '+' : ''}{r.profit.toFixed(0)} USDT</span>
								<span class="w-10 shrink-0 text-right font-mono text-[10px]"
									class:text-green-400={r.wr >= 0.5} class:text-red-400={r.wr < 0.5}
								>{(r.wr * 100).toFixed(0)}%</span>
							</div>
						{/each}
					</div>
					<p class="mt-2 text-[10px] text-muted-foreground">Bar width = relative count · color: green = high WR · profit = cumulative USDT per exit type</p>
				</section>
			{/if}

			{#if weeklyPnl}
				<section class="mb-6 rounded-lg border bg-card p-5">
					<div class="mb-3 flex flex-wrap items-baseline justify-between gap-2">
						<h2 class="text-sm font-semibold">Weekly P&L <span class="ml-1 font-normal text-muted-foreground text-xs">(last {weeklyPnl.weeks} weeks)</span> <ChartInfo metric="totalProfit" {lang} /></h2>
						<div class="flex items-center gap-4 text-[11px]">
							<span class="text-muted-foreground">Total <span class="font-mono font-semibold" class:text-green-400={weeklyPnl.total >= 0} class:text-red-400={weeklyPnl.total < 0}>{weeklyPnl.total >= 0 ? '+' : ''}{weeklyPnl.total.toFixed(0)} USDT</span></span>
							<span class="text-muted-foreground">Win weeks <span class="font-mono text-foreground">{weeklyPnl.wins}/{weeklyPnl.weeks}</span></span>
						</div>
					</div>
					<div class="overflow-x-auto">
						<svg viewBox="0 0 {weeklyPnl.W} {weeklyPnl.H}" class="w-full" style="height:80px;min-width:300px">
							<line x1="0" y1={weeklyPnl.H / 2} x2={weeklyPnl.W} y2={weeklyPnl.H / 2} stroke="var(--ch-rule)" stroke-width="1" />
							{#each weeklyPnl.bars as b}
								<rect
									x={b.x + 0.5}
									y={b.positive ? weeklyPnl.H / 2 - b.h : weeklyPnl.H / 2}
									width={weeklyPnl.barW}
									height={b.h}
									fill={b.positive ? 'var(--ch-profit)' : 'var(--ch-loss)'}
									rx="1"
								>
									<title>{b.week}: {b.v >= 0 ? '+' : ''}{b.v.toFixed(1)} USDT</title>
								</rect>
							{/each}
						</svg>
					</div>
					<div class="mt-1 flex items-center gap-4 text-[10px] text-muted-foreground">
						<span class="flex items-center gap-1"><span class="inline-block h-3 w-3 rounded-sm bg-green-500/70"></span>Profit week</span>
						<span class="flex items-center gap-1"><span class="inline-block h-3 w-3 rounded-sm bg-red-500/70"></span>Loss week</span>
						<span class="ml-auto font-mono">Each bar = 1 ISO week · max ±{weeklyPnl.maxAbs.toFixed(0)} USDT</span>
					</div>
				</section>
			{/if}
		</div>
	</details>
</main>
