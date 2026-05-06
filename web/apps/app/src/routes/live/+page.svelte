<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { subscribeTo, realtimeStatus, type RealtimeStatus } from '$lib/realtime';
	import type { PageData } from './$types';
	import type { BacktestRun, LiveTrade, EventDcaTrigger } from '$lib/types';
	import { fmtPct, fmtTime, fmtUSD } from '$lib/utils';
	import { t, type Lang } from '$lib/i18n';
	import StatusPill from '$lib/components/status-pill.svelte';
	import ChartInfo from '$lib/components/chart-info.svelte';

	let { data }: { data: PageData } = $props();
	const lang = $derived<Lang>(data.lang ?? 'zh');

	let runs = $state<BacktestRun[]>(data.runs);
	let trades = $state<LiveTrade[]>(data.trades);
	let events = $state<EventDcaTrigger[]>(data.events);
	let status = $state<RealtimeStatus>('idle');
	let feed = $state<Array<{ kind: string; msg: string; ts: string; hot?: boolean }>>([]);

	// --- P&L panel ---
	let prices = $state<Record<string, number>>({});
	let pricesUpdatedAt = $state<Date | null>(null);
	let pricesPending = $state(false);

	const openTrades = $derived(trades.filter((t) => !t.close_date));
	const liveTrades = $derived(data.trades);
	const closedTrades = $derived(data.closedTrades);

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

	// Win/loss streak from most-recent closed trades
	const tradeStreak = $derived.by(() => {
		const sorted = data.closedTrades
			.filter(t => t.close_date && t.profit_pct != null)
			.sort((a, b) => b.close_date!.localeCompare(a.close_date!));
		if (sorted.length === 0) return null;
		const first = sorted[0];
		const isWin = (t: typeof first) => (t.profit_pct ?? 0) > 0;
		const firstWin = isWin(first);
		let count = 0;
		for (const t of sorted) {
			if (isWin(t) === firstWin) count++;
			else break;
		}
		const last5 = sorted.slice(0, 5).reverse().map(t => ({ win: isWin(t), pct: t.profit_pct ?? 0 }));
		return { win: firstWin, count, last5, lastClose: first.close_date! };
	});

	// Bot breakdown
	const botBreakdown = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.close_date && t.profit_abs != null);
		if (closed.length === 0) return null;
		const map = new Map<string, { profit: number; count: number; wins: number; lastDate: string }>();
		for (const t of closed) {
			if (!map.has(t.bot_name)) map.set(t.bot_name, { profit: 0, count: 0, wins: 0, lastDate: '' });
			const b = map.get(t.bot_name)!;
			b.profit += t.profit_abs!;
			b.count++;
			if ((t.profit_pct ?? 0) > 0) b.wins++;
			if (t.close_date! > b.lastDate) b.lastDate = t.close_date!;
		}
		return [...map.entries()]
			.map(([bot, v]) => ({ bot, ...v, wr: v.wins / v.count }))
			.sort((a, b) => b.profit - a.profit);
	});

	// Daily closed P&L chart
	const dailyPnl = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.close_date && t.profit_abs != null);
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
		const closed = data.closedTrades.filter(t => t.close_date && t.profit_abs != null && t.pair);
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

	// Weekly P&L bar chart
	// Open trade age breakdown — sorted oldest first, bar = hours held
	const openAging = $derived.by(() => {
		if (openTrades.length === 0) return null;
		const now = Date.now();
		const rows = openTrades.map(t => {
			const ms = now - new Date(t.open_date).getTime();
			const hours = ms / 3600000;
			const upnl = prices[toBinanceSymbol(t.pair)] != null ? calcUPnL(t, prices[toBinanceSymbol(t.pair)]) : null;
			const upnlPct = (t.open_rate && t.stake_amount) ? (upnl != null ? (upnl / t.stake_amount) * 100 : null) : null;
			return { pair: t.pair, hours, upnl, upnlPct, openDate: t.open_date, stake: t.stake_amount ?? 0 };
		}).sort((a, b) => b.hours - a.hours);
		const maxHours = Math.max(1, ...rows.map(r => r.hours));
		return rows.map(r => ({ ...r, barPct: (r.hours / maxHours) * 100 }));
	});

	// Monthly P&L heatmap from live closed trades
	const liveMonthlyPnl = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.close_date && t.profit_abs != null);
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

	// Day-of-week P&L from live closed trades
	const DOW_NAMES_LIVE = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
	const liveDowPnl = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.close_date && t.profit_abs != null);
		if (closed.length < 7) return null;
		const byDow = Array.from({ length: 7 }, () => ({ sum: 0, count: 0, wins: 0 }));
		for (const t of closed) {
			const dow = new Date(t.close_date!).getUTCDay();
			byDow[dow].sum += t.profit_abs!;
			byDow[dow].count++;
			if ((t.profit_pct ?? 0) > 0) byDow[dow].wins++;
		}
		const maxAbs = Math.max(1, ...byDow.map(d => Math.abs(d.sum)));
		return byDow.map((d, i) => ({
			label: DOW_NAMES_LIVE[i],
			sum: d.sum,
			count: d.count,
			wr: d.count > 0 ? d.wins / d.count : 0,
			barPct: d.count > 0 ? (Math.abs(d.sum) / maxAbs) * 100 : 0,
			positive: d.sum >= 0,
		}));
	});

	const weeklyPnl = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.close_date && t.profit_abs != null);
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

	// Trade close hour-of-day distribution
	const closeHourChart = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.close_date && t.profit_abs != null);
		if (closed.length < 5) return null;
		const hours = Array.from({ length: 24 }, (_, h) => ({ h, count: 0, profit: 0, wins: 0 }));
		for (const t of closed) {
			const h = new Date(t.close_date!).getUTCHours();
			hours[h].count++;
			hours[h].profit += t.profit_abs!;
			if ((t.profit_pct ?? 0) > 0) hours[h].wins++;
		}
		const maxCount = Math.max(1, ...hours.map(h => h.count));
		return hours.map(h => ({
			...h,
			barPct: (h.count / maxCount) * 100,
			wr: h.count > 0 ? h.wins / h.count : 0,
			positive: h.profit >= 0,
		}));
	});

	// Closed trade equity curve: running cumulative P&L
	const closedEquityCurve = $derived.by(() => {
		const sorted = data.closedTrades
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

	// Open exposure map: each open trade's stake as share of total open exposure
	const openExposureMap = $derived.by(() => {
		if (openTrades.length < 2) return null;
		const rows = openTrades
			.filter(t => t.stake_amount != null && t.stake_amount > 0)
			.map(t => ({ pair: t.pair, stake: t.stake_amount!, bot_name: t.bot_name ?? null }));
		if (rows.length < 2) return null;
		const total = rows.reduce((s, r) => s + r.stake, 0);
		if (total === 0) return null;
		const sorted = [...rows].sort((a, b) => b.stake - a.stake);
		return sorted.map(r => ({ ...r, pct: (r.stake / total) * 100 }));
	});

	// Trade duration histogram — how long trades are held
	const durationHist = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.trade_duration_min != null && t.profit_abs != null);
		if (closed.length < 5) return null;
		const BUCKETS = [
			{ label: '<30m', max: 30, count: 0, profit: 0, wins: 0 },
			{ label: '30m-2h', max: 120, count: 0, profit: 0, wins: 0 },
			{ label: '2-8h', max: 480, count: 0, profit: 0, wins: 0 },
			{ label: '8-24h', max: 1440, count: 0, profit: 0, wins: 0 },
			{ label: '1-3d', max: 4320, count: 0, profit: 0, wins: 0 },
			{ label: '3-7d', max: 10080, count: 0, profit: 0, wins: 0 },
			{ label: '7d+', max: Infinity, count: 0, profit: 0, wins: 0 },
		];
		for (const t of closed) {
			const m = t.trade_duration_min!;
			const b = BUCKETS.find(bk => m < bk.max)!;
			b.count++;
			b.profit += t.profit_abs!;
			if ((t.profit_abs ?? 0) > 0) b.wins++;
		}
		const active = BUCKETS.filter(b => b.count > 0);
		if (active.length < 2) return null;
		const maxCount = Math.max(1, ...active.map(b => b.count));
		return active.map(b => ({
			...b,
			barPct: (b.count / maxCount) * 100,
			wr: b.wins / b.count,
		}));
	});

	// Stake efficiency: profit per USDT staked per pair
	const stakeEfficiency = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.close_date && t.profit_abs != null && t.pair && t.stake_amount != null && t.stake_amount > 0);
		if (closed.length < 5) return null;
		const map = new Map<string, { profit: number; count: number; stake: number; wins: number }>();
		for (const t of closed) {
			if (!map.has(t.pair)) map.set(t.pair, { profit: 0, count: 0, stake: 0, wins: 0 });
			const e = map.get(t.pair)!;
			e.profit += t.profit_abs!;
			e.count++;
			e.stake += t.stake_amount!;
			if ((t.profit_pct ?? 0) > 0) e.wins++;
		}
		const rows = [...map.entries()]
			.map(([pair, v]) => ({ pair, ...v, efficiency: v.profit / v.stake, wr: v.wins / v.count }))
			.filter(r => r.count >= 2)
			.sort((a, b) => b.efficiency - a.efficiency)
			.slice(0, 14);
		if (rows.length < 3) return null;
		const maxAbs = Math.max(0.001, ...rows.map(r => Math.abs(r.efficiency)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.efficiency) / maxAbs) * 100 }));
	});

	// Trade profit % distribution histogram
	const tradeProfitDist = $derived.by(() => {
		const vals = data.closedTrades.filter(t => t.profit_pct != null).map(t => t.profit_pct! * 100);
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
		const closed = data.closedTrades.filter(t => t.close_date && t.profit_abs != null && t.exit_reason);
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

	// Open trade holding duration ranked chart
	const openTradeHoldingMap = $derived.by(() => {
		const open = openTrades.filter(t => t.open_date && t.pair && t.stake_amount != null);
		if (open.length < 2) return null;
		const now = Date.now();
		const rows = open.map(t => {
			const ms = now - new Date(t.open_date).getTime();
			const hours = ms / 3600000;
			const label = hours >= 48 ? `${Math.floor(hours / 24)}d` : `${Math.floor(hours)}h`;
			return { pair: t.pair, hours, label, stake: t.stake_amount!, profitPct: t.profit_pct ?? null };
		}).sort((a, b) => b.hours - a.hours);
		const maxHours = Math.max(0.1, rows[0].hours);
		return rows.map(r => ({ ...r, barPct: (r.hours / maxHours) * 100 }));
	});

	// Win/loss streak distribution: how long do streaks run?
	const streakDistribution = $derived.by(() => {
		const closed = data.closedTrades
			.filter(t => t.close_date && t.profit_pct != null)
			.sort((a, b) => a.close_date!.localeCompare(b.close_date!));
		if (closed.length < 10) return null;
		const winStreaks: number[] = [];
		const lossStreaks: number[] = [];
		let cur = 0;
		let curWin = (closed[0].profit_pct ?? 0) > 0;
		for (const t of closed) {
			const win = (t.profit_pct ?? 0) > 0;
			if (win === curWin) { cur++; }
			else {
				if (curWin) winStreaks.push(cur); else lossStreaks.push(cur);
				cur = 1; curWin = win;
			}
		}
		if (curWin) winStreaks.push(cur); else lossStreaks.push(cur);
		const maxLen = Math.max(1, ...winStreaks, ...lossStreaks);
		const buckets = Array.from({ length: Math.min(maxLen, 8) }, (_, i) => {
			const len = i + 1;
			return {
				len,
				wins: winStreaks.filter(s => s === len).length,
				losses: lossStreaks.filter(s => s === len).length,
			};
		});
		const maxCount = Math.max(1, ...buckets.map(b => Math.max(b.wins, b.losses)));
		const avgWin = winStreaks.reduce((a, b) => a + b, 0) / Math.max(1, winStreaks.length);
		const avgLoss = lossStreaks.reduce((a, b) => a + b, 0) / Math.max(1, lossStreaks.length);
		return { buckets, maxCount, avgWin, avgLoss };
	});

	// Pair profit matrix: top 12 pairs by total profit_abs with win rate bar
	const pairProfitMatrix = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.pair && t.profit_pct != null && t.profit_abs != null);
		if (closed.length < 8) return null;
		const map = new Map<string, { wins: number; count: number; profitPctSum: number; profitAbsSum: number }>();
		for (const t of closed) {
			if (!map.has(t.pair)) map.set(t.pair, { wins: 0, count: 0, profitPctSum: 0, profitAbsSum: 0 });
			const v = map.get(t.pair)!;
			v.count++;
			v.profitPctSum += t.profit_pct!;
			v.profitAbsSum += t.profit_abs!;
			if (t.profit_abs! > 0) v.wins++;
		}
		const rows = [...map.entries()]
			.map(([pair, v]) => ({
				pair,
				count: v.count,
				wr: v.wins / v.count,
				avgProfitPct: v.profitPctSum / v.count,
				totalProfitAbs: v.profitAbsSum,
			}))
			.sort((a, b) => b.totalProfitAbs - a.totalProfitAbs)
			.slice(0, 12);
		return rows;
	});

	// Bot profit ranking: total P&L and win rate per bot
	const botProfitRanking = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.bot_name && t.profit_abs != null);
		if (closed.length < 4) return null;
		const map = new Map<string, { wins: number; count: number; profitAbsSum: number }>();
		for (const t of closed) {
			if (!map.has(t.bot_name)) map.set(t.bot_name, { wins: 0, count: 0, profitAbsSum: 0 });
			const v = map.get(t.bot_name)!;
			v.count++;
			v.profitAbsSum += t.profit_abs!;
			if (t.profit_abs! > 0) v.wins++;
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([bot, v]) => ({ bot, count: v.count, wr: v.wins / v.count, totalAbs: v.profitAbsSum }))
			.sort((a, b) => b.totalAbs - a.totalAbs);
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.totalAbs)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.totalAbs) / maxAbs) * 100 }));
	});

	// Monthly win rate trend: last 12 months of closed trade win rate
	const monthlyWinRateTrend = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.close_date && t.profit_pct != null);
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
		const closed = data.closedTrades
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

	// Trade profit percentile summary: P10/P25/P50/P75/P90/P95
	const profitPercentiles = $derived.by(() => {
		const vals = data.closedTrades
			.filter(t => t.profit_pct != null)
			.map(t => t.profit_pct! * 100)
			.sort((a, b) => a - b);
		if (vals.length < 20) return null;
		const pct = (p: number) => {
			const idx = Math.floor((p / 100) * (vals.length - 1));
			return vals[idx];
		};
		const points = [
			{ label: 'P5',  p:  5, v: pct(5)  },
			{ label: 'P25', p: 25, v: pct(25) },
			{ label: 'P50', p: 50, v: pct(50) },
			{ label: 'P75', p: 75, v: pct(75) },
			{ label: 'P90', p: 90, v: pct(90) },
			{ label: 'P95', p: 95, v: pct(95) },
		];
		const absMax = Math.max(0.01, ...points.map(p => Math.abs(p.v)));
		return points.map(p => ({ ...p, barPct: (Math.abs(p.v) / absMax) * 100 }));
	});

	// Weekly win rate trend: last 12 calendar weeks win rate (distinct from rolling-20 trade and monthly)
	const weeklyWinRateTrend = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.close_date && t.profit_pct != null);
		if (closed.length < 15) return null;
		const getWeekKey = (dateStr: string) => {
			const d = new Date(dateStr);
			const day = d.getUTCDay();
			const monday = new Date(d);
			monday.setUTCDate(d.getUTCDate() - (day === 0 ? 6 : day - 1));
			return monday.toISOString().slice(0, 10);
		};
		const now = new Date();
		const nowDay = now.getUTCDay();
		const thisMonday = new Date(now);
		thisMonday.setUTCDate(now.getUTCDate() - (nowDay === 0 ? 6 : nowDay - 1));
		thisMonday.setUTCHours(0, 0, 0, 0);
		const weeks = Array.from({ length: 12 }, (_, i) => {
			const d = new Date(thisMonday);
			d.setUTCDate(thisMonday.getUTCDate() - (11 - i) * 7);
			const key = d.toISOString().slice(0, 10);
			const label = `${String(d.getUTCMonth() + 1).padStart(2, '0')}/${String(d.getUTCDate()).padStart(2, '0')}`;
			return { key, label, wins: 0, total: 0 };
		});
		for (const t of closed) {
			const key = getWeekKey(t.close_date!);
			const w = weeks.find(wk => wk.key === key);
			if (!w) continue;
			w.total++;
			if ((t.profit_pct ?? 0) > 0) w.wins++;
		}
		const active = weeks.filter(w => w.total >= 1);
		if (active.length < 4) return null;
		return active.map(w => ({ ...w, wr: w.total > 0 ? w.wins / w.total : null }));
	});

	// Profit factor per bot: gross win USDT / gross loss USDT per bot_name
	const profitFactorByBot = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.bot_name && t.profit_abs != null);
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

	const recentTradeTimeline = $derived.by(() => {
		const closed = data.closedTrades
			.filter(t => t.close_date && t.profit_pct != null)
			.sort((a, b) => a.close_date!.localeCompare(b.close_date!))
			.slice(-30);
		if (closed.length < 5) return null;
		const wins = closed.filter(t => (t.profit_pct ?? 0) > 0).length;
		const streak = (() => {
			let s = 0;
			for (let i = closed.length - 1; i >= 0; i--) {
				const win = (closed[i].profit_pct ?? 0) > 0;
				if (i === closed.length - 1) { s = win ? 1 : -1; continue; }
				if ((s > 0 && win) || (s < 0 && !win)) { s += s > 0 ? 1 : -1; } else break;
			}
			return s;
		})();
		return { trades: closed, wins, total: closed.length, streak };
	});

	const openPairUnrealizedPnl = $derived.by(() => {
		const valid = openTrades.filter(t => t.pair && t.profit_pct != null);
		if (valid.length < 2) return null;
		const map = new Map<string, { sum: number; count: number }>();
		for (const t of valid) {
			if (!map.has(t.pair)) map.set(t.pair, { sum: 0, count: 0 });
			const e = map.get(t.pair)!;
			e.sum += (t.profit_pct ?? 0) * 100;
			e.count++;
		}
		const rows = [...map.entries()]
			.map(([pair, { sum, count }]) => ({ pair, avg: sum / count }))
			.sort((a, b) => b.avg - a.avg);
		if (rows.length < 2) return null;
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.avg)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.avg) / maxAbs) * 100 }));
	});

	const tradeDoWHourHeatmap = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.close_date && t.profit_pct != null);
		if (closed.length < 20) return null;
		const cells: { sum: number; count: number }[][] = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => ({ sum: 0, count: 0 })));
		for (const t of closed) {
			const d = new Date(t.close_date!);
			const dow = d.getUTCDay(), hr = d.getUTCHours();
			cells[dow][hr].sum += (t.profit_pct ?? 0) * 100;
			cells[dow][hr].count++;
		}
		const avgs = cells.flatMap(row => row.map(c => c.count > 0 ? c.sum / c.count : null)).filter((v): v is number => v !== null);
		if (avgs.length < 5) return null;
		const maxAbs = Math.max(0.01, ...avgs.map(Math.abs));
		const DAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
		return { cells, maxAbs, DAYS };
	});

	// Bot win rate comparison: % profitable closed trades per bot (distinct from profitFactorByBot gross ratio and botProfitRanking cumulative profit)
	const botWinRateComparison = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.bot_name && t.profit_pct != null);
		if (closed.length < 6) return null;
		const map = new Map<string, { wins: number; total: number; profitSum: number }>();
		for (const t of closed) {
			if (!map.has(t.bot_name)) map.set(t.bot_name, { wins: 0, total: 0, profitSum: 0 });
			const b = map.get(t.bot_name)!;
			b.total++;
			if ((t.profit_pct ?? 0) > 0) b.wins++;
			b.profitSum += t.profit_pct ?? 0;
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([bot, v]) => ({ bot, wr: v.wins / v.total, total: v.total, avgProfit: v.profitSum / v.total }))
			.sort((a, b) => b.wr - a.wr);
		const maxWr = Math.max(0.01, ...rows.map(r => r.wr));
		return rows.map(r => ({ ...r, barPct: (r.wr / maxWr) * 100 }));
	});

	// Trade count and net profit per strategy across all bots (distinct from botBreakdown/botProfitRanking which group by bot_name)
	const strategyTradeVolume = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.strategy && t.profit_pct != null);
		if (closed.length < 6) return null;
		const map = new Map<string, { count: number; wins: number; profitSum: number }>();
		for (const t of closed) {
			const s = t.strategy!;
			if (!map.has(s)) map.set(s, { count: 0, wins: 0, profitSum: 0 });
			const e = map.get(s)!;
			e.count++;
			if ((t.profit_pct ?? 0) > 0) e.wins++;
			e.profitSum += t.profit_abs ?? 0;
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([strategy, v]) => ({ strategy, count: v.count, wr: v.wins / v.count, profitSum: v.profitSum }))
			.sort((a, b) => b.count - a.count)
			.slice(0, 10);
		const maxCount = Math.max(1, ...rows.map(r => r.count));
		return rows.map(r => ({ ...r, barPct: (r.count / maxCount) * 100 }));
	});

	const openTradeAgeDistribution = $derived.by(() => {
		const now = Date.now();
		const BUCKETS = [
			{ label: '<1h', maxH: 1 }, { label: '1–4h', maxH: 4 }, { label: '4–12h', maxH: 12 },
			{ label: '12–24h', maxH: 24 }, { label: '1–3d', maxH: 72 }, { label: '3–7d', maxH: 168 }, { label: '>7d', maxH: Infinity }
		];
		const buckets = BUCKETS.map(b => ({ ...b, count: 0 }));
		for (const t of openTrades) {
			if (!t.open_date) continue;
			const ageH = (now - new Date(t.open_date).getTime()) / 3600000;
			const idx = buckets.findIndex(b => ageH < b.maxH);
			if (idx >= 0) buckets[idx].count++;
		}
		const filled = buckets.filter(b => b.count > 0);
		if (filled.length < 2) return null;
		const maxCount = Math.max(1, ...buckets.map(b => b.count));
		return buckets.map(b => ({ ...b, barPct: (b.count / maxCount) * 100 }));
	});

	const pairProfitLeaderboard = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.pair && t.profit_abs != null && isFinite(t.profit_abs));
		if (closed.length < 5) return null;
		const map = new Map<string, { sum: number; count: number; wins: number }>();
		for (const t of closed) {
			if (!map.has(t.pair!)) map.set(t.pair!, { sum: 0, count: 0, wins: 0 });
			const e = map.get(t.pair!)!;
			e.sum += t.profit_abs!;
			e.count++;
			if (t.profit_abs! > 0) e.wins++;
		}
		const rows = [...map.entries()]
			.map(([pair, v]) => ({ pair, sum: v.sum, count: v.count, wr: v.wins / v.count }))
			.sort((a, b) => b.sum - a.sum)
			.slice(0, 10);
		if (rows.length < 3) return null;
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.sum)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.sum) / maxAbs) * 100 }));
	});

	const botCumulativePnlTimeline = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.bot_name && t.profit_abs != null && t.close_date);
		if (closed.length < 5) return null;
		const bots = [...new Set(closed.map(t => t.bot_name!))];
		if (bots.length < 2) return null;
		const sorted = [...closed].sort((a, b) => new Date(a.close_date!).getTime() - new Date(b.close_date!).getTime());
		const W = 300, H = 60, PAD = 8;
		const lines = bots.map((bot, bi) => {
			const trades = sorted.filter(t => t.bot_name === bot);
			let cum = 0;
			const pts = trades.map(t => { cum += t.profit_abs!; return cum; });
			return { bot, pts, final: cum };
		});
		const allPts = lines.flatMap(l => l.pts);
		const mn = Math.min(0, ...allPts), mx = Math.max(0.01, ...allPts);
		const range = mx - mn || 1;
		const colors = ['var(--ch-profit-strong)', 'var(--ch-violet-strong)', 'var(--ch-warn)', 'var(--ch-loss-strong)', 'var(--ch-teal-strong)'];
		const polylines = lines.map((l, i) => {
			const poly = l.pts.map((v, j) => {
				const x = PAD + (j / Math.max(1, l.pts.length - 1)) * (W - PAD * 2);
				const y = H - PAD - ((v - mn) / range) * (H - PAD * 2);
				return `${x.toFixed(1)},${y.toFixed(1)}`;
			}).join(' ');
			return { bot: l.bot, poly, final: l.final, color: colors[i % colors.length] };
		});
		return { polylines, W, H, PAD };
	});

	const openTradeUnrealizedByBot = $derived.by(() => {
		const bots = new Map<string, { sum: number; count: number }>();
		for (const t of openTrades) {
			if (!t.bot_name || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			if (!bots.has(t.bot_name)) bots.set(t.bot_name, { sum: 0, count: 0 });
			const e = bots.get(t.bot_name)!;
			e.sum += t.profit_pct;
			e.count++;
		}
		if (bots.size < 1) return null;
		const rows = [...bots.entries()]
			.map(([bot, v]) => ({ bot, sum: v.sum, count: v.count, avg: v.sum / v.count }))
			.sort((a, b) => b.sum - a.sum);
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.sum)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.sum) / maxAbs) * 100 }));
	});

	const closedTradeProfitByMonth = $derived.by(() => {
		const map = new Map<string, { sum: number; count: number }>();
		for (const t of data.closedTrades) {
			if (!t.close_date || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			const ym = new Date(t.close_date).toISOString().slice(0, 7);
			if (!map.has(ym)) map.set(ym, { sum: 0, count: 0 });
			const e = map.get(ym)!;
			e.sum += t.profit_pct;
			e.count++;
		}
		if (map.size < 3) return null;
		const rows = [...map.entries()]
			.map(([ym, v]) => ({ ym, avg: v.sum / v.count, count: v.count }))
			.sort((a, b) => a.ym.localeCompare(b.ym));
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.avg)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.avg) / maxAbs) * 100 }));
	});

	const strategyProfitLeaderboard = $derived.by(() => {
		const map = new Map<string, { sum: number; count: number; wins: number }>();
		for (const t of data.closedTrades) {
			if (!t.strategy || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			if (!map.has(t.strategy)) map.set(t.strategy, { sum: 0, count: 0, wins: 0 });
			const e = map.get(t.strategy)!;
			e.sum += t.profit_pct;
			e.count++;
			if (t.profit_pct > 0) e.wins++;
		}
		const rows = [...map.entries()]
			.filter(([, v]) => v.count >= 3)
			.map(([strategy, v]) => ({ strategy, avg: v.sum / v.count, count: v.count, wr: v.wins / v.count }))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 10);
		if (rows.length < 2) return null;
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.avg)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.avg) / maxAbs) * 100 }));
	});

	const tradeDurationVsProfit = $derived.by(() => {
		const pts = data.closedTrades.filter(t => t.trade_duration_min != null && t.profit_pct != null && isFinite(t.profit_pct) && t.trade_duration_min > 0 && t.trade_duration_min < 100000);
		if (pts.length < 10) return null;
		const durations = pts.map(t => t.trade_duration_min!);
		const profits = pts.map(t => t.profit_pct!);
		const maxD = Math.max(...durations), minP = Math.min(...profits), maxP = Math.max(...profits);
		const rangeP = maxP - minP || 1;
		const W = 360, H = 80, PAD = 8;
		const mapped = pts.map(t => ({
			cx: PAD + (t.trade_duration_min! / maxD) * (W - PAD * 2),
			cy: H - PAD - ((t.profit_pct! - minP) / rangeP) * (H - PAD * 2),
			pos: t.profit_pct! > 0
		}));
		return { mapped, W, H, PAD, maxD, minP, maxP };
	});

	const closedTradeExitReasonBreakdown = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.exit_reason && t.profit_pct != null && isFinite(t.profit_pct));
		if (closed.length < 5) return null;
		const map = new Map<string, { sum: number; count: number; wins: number }>();
		for (const t of closed) {
			const r = t.exit_reason!;
			if (!map.has(r)) map.set(r, { sum: 0, count: 0, wins: 0 });
			const e = map.get(r)!;
			e.sum += t.profit_pct!;
			e.count++;
			if (t.profit_pct! > 0) e.wins++;
		}
		const rows = [...map.entries()]
			.map(([reason, v]) => ({ reason, avg: v.sum / v.count, count: v.count, wr: v.wins / v.count }))
			.sort((a, b) => b.count - a.count)
			.slice(0, 8);
		if (rows.length < 2) return null;
		const maxCount = Math.max(1, ...rows.map(r => r.count));
		return rows.map(r => ({ ...r, barPct: (r.count / maxCount) * 100 }));
	});

	const closedTradePairFrequency = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.pair && t.profit_pct != null && isFinite(t.profit_pct));
		if (closed.length < 5) return null;
		const map = new Map<string, { sum: number; count: number; wins: number }>();
		for (const t of closed) {
			const p = t.pair!;
			if (!map.has(p)) map.set(p, { sum: 0, count: 0, wins: 0 });
			const e = map.get(p)!;
			e.sum += t.profit_pct!;
			e.count++;
			if (t.profit_pct! > 0) e.wins++;
		}
		const rows = [...map.entries()]
			.map(([pair, v]) => ({ pair, count: v.count, avgProfit: v.sum / v.count, winRate: v.wins / v.count }))
			.sort((a, b) => b.count - a.count)
			.slice(0, 12);
		if (rows.length < 3) return null;
		const maxCount = Math.max(1, ...rows.map(r => r.count));
		return rows.map(r => ({ ...r, barPct: (r.count / maxCount) * 100 }));
	});

	const closedTradeDurationDistribution = $derived.by(() => {
		const vals = data.closedTrades
			.filter(t => t.trade_duration_min != null && isFinite(t.trade_duration_min) && t.trade_duration_min >= 0)
			.map(t => t.trade_duration_min!);
		if (vals.length < 8) return null;
		const mx = Math.max(...vals);
		const BINS = 8, step = mx / BINS || 1;
		const buckets = Array.from({ length: BINS }, (_, i) => ({
			label: i === BINS - 1 ? `>${(i * step / 60).toFixed(0)}h` : `${(i * step / 60).toFixed(0)}–${((i + 1) * step / 60).toFixed(0)}h`,
			count: 0, sumProfit: 0, wins: 0
		}));
		for (const t of data.closedTrades) {
			if (t.trade_duration_min == null || !isFinite(t.trade_duration_min)) continue;
			const idx = Math.min(BINS - 1, Math.floor(t.trade_duration_min / step));
			buckets[idx].count++;
			if (t.profit_pct != null && isFinite(t.profit_pct)) { buckets[idx].sumProfit += t.profit_pct; if (t.profit_pct > 0) buckets[idx].wins++; }
		}
		const maxCount = Math.max(1, ...buckets.map(b => b.count));
		const sorted = [...vals].sort((a, b) => a - b);
		const median = sorted[Math.floor(sorted.length / 2)];
		return { buckets: buckets.map(b => ({ ...b, barPct: (b.count / maxCount) * 100, avgProfit: b.count > 0 ? b.sumProfit / b.count : 0 })), median, total: vals.length };
	});

	const closedTradeStrategyWinRate = $derived.by(() => {
		const map = new Map<string, { wins: number; total: number; sumProfit: number }>();
		for (const t of data.closedTrades) {
			if (!t.strategy || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			if (!map.has(t.strategy)) map.set(t.strategy, { wins: 0, total: 0, sumProfit: 0 });
			const e = map.get(t.strategy)!;
			e.total++;
			e.sumProfit += t.profit_pct;
			if (t.profit_pct > 0) e.wins++;
		}
		const rows = [...map.entries()]
			.filter(([, v]) => v.total >= 3)
			.map(([strategy, v]) => ({ strategy, wr: v.wins / v.total, total: v.total, avgProfit: v.sumProfit / v.total }))
			.sort((a, b) => b.wr - a.wr)
			.slice(0, 10);
		if (rows.length < 2) return null;
		const maxWr = Math.max(1, ...rows.map(r => r.wr));
		return rows.map(r => ({ ...r, barPct: (r.wr / maxWr) * 100 }));
	});

	const closedTradeBotProfitByMonth = $derived.by(() => {
		const bots = [...new Set(data.closedTrades.map(t => t.bot_name).filter(Boolean))] as string[];
		if (bots.length < 2) return null;
		const map = new Map<string, Map<string, number>>();
		for (const t of data.closedTrades) {
			if (!t.close_date || !t.bot_name || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			const ym = t.close_date.slice(0, 7);
			if (!map.has(ym)) map.set(ym, new Map());
			const bm = map.get(ym)!;
			bm.set(t.bot_name, (bm.get(t.bot_name) ?? 0) + t.profit_pct);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort().slice(-12);
		const BOT_COLORS = ['var(--ch-violet)', 'var(--ch-profit)', 'var(--ch-warn)', 'var(--ch-loss)', 'var(--ch-violet-strong)', 'var(--ch-teal)'];
		const botColors = Object.fromEntries(bots.map((b, i) => [b, BOT_COLORS[i % BOT_COLORS.length]]));
		const allVals = months.flatMap(ym => bots.map(b => map.get(ym)?.get(b) ?? 0));
		const absMax = Math.max(0.01, ...allVals.map(Math.abs));
		const W = 400, H = 80, PAD = 8;
		const barW = (W - PAD * 2) / months.length;
		const botW = barW * 0.8 / bots.length;
		const midY = H / 2;
		const scale = (midY - 4) / absMax;
		const bars = months.map((ym, mi) => ({
			ym,
			bots: bots.map((b, bi) => {
				const val = map.get(ym)?.get(b) ?? 0;
				const x = PAD + mi * barW + barW * 0.1 + bi * botW;
				const h = Math.abs(val) * scale;
				const y = val >= 0 ? midY - h : midY;
				return { b, val, x, y, h, color: botColors[b] };
			})
		}));
		return { bars, months, bots, botColors, W, H, midY };
	});

	const closedTradePairDowHeatmap = $derived.by(() => {
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const pairs = [...new Set(data.closedTrades.map(t => t.pair).filter(Boolean))] as string[];
		if (pairs.length < 2) return null;
		const map = new Map<string, { wins: number; total: number }[]>();
		for (const p of pairs) map.set(p, Array.from({ length: 7 }, () => ({ wins: 0, total: 0 })));
		for (const t of data.closedTrades) {
			if (!t.pair || !t.close_date || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			const dow = new Date(t.close_date).getDay();
			const e = map.get(t.pair)?.[dow];
			if (!e) continue;
			e.total++;
			if (t.profit_pct > 0) e.wins++;
		}
		const validPairs = pairs.filter(p => map.get(p)!.reduce((s, e) => s + e.total, 0) >= 5).slice(0, 8);
		if (validPairs.length < 2) return null;
		const cells = validPairs.map(p => ({
			pair: p,
			days: DAYS.map((label, i) => {
				const e = map.get(p)![i];
				return { label, wr: e.total >= 2 ? e.wins / e.total : null, total: e.total };
			})
		}));
		return { cells, days: DAYS };
	});

	const closedTradeMonthlyWinRate = $derived.by(() => {
		const map = new Map<string, { wins: number; total: number }>();
		for (const t of data.closedTrades) {
			if (!t.close_date || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			const ym = t.close_date.slice(0, 7);
			if (!map.has(ym)) map.set(ym, { wins: 0, total: 0 });
			const e = map.get(ym)!;
			e.total++;
			if (t.profit_pct > 0) e.wins++;
		}
		const months = [...map.keys()].sort().slice(-18);
		if (months.length < 3) return null;
		const rows = months.map(ym => {
			const e = map.get(ym)!;
			return { ym, wr: e.wins / e.total, total: e.total };
		});
		const W = 400, H = 60, PAD = 8;
		const toX = (i: number) => PAD + (i / Math.max(1, rows.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v * (H - PAD * 2));
		const poly = rows.map((r, i) => `${toX(i).toFixed(1)},${toY(r.wr).toFixed(1)}`).join(' ');
		const y50 = toY(0.5);
		const avgWr = rows.reduce((s, r) => s + r.wr, 0) / rows.length;
		return { rows, poly, W, H, PAD, y50, avgWr, first: months[0], last: months[months.length - 1] };
	});

	// Closed trade profit% distribution histogram
	const closedTradeProfitDistribution = $derived.by(() => {
		const vals = data.closedTrades.map(t => t.profit_pct).filter((v): v is number => v != null && isFinite(v));
		if (vals.length < 10) return null;
		const BINS = [
			{ lo: -Infinity, hi: -10, label: '<-10%' },
			{ lo: -10, hi: -5, label: '-10 to -5%' },
			{ lo: -5, hi: -2, label: '-5 to -2%' },
			{ lo: -2, hi: 0, label: '-2 to 0%' },
			{ lo: 0, hi: 2, label: '0 to 2%' },
			{ lo: 2, hi: 5, label: '2 to 5%' },
			{ lo: 5, hi: 10, label: '5 to 10%' },
			{ lo: 10, hi: Infinity, label: '>10%' },
		];
		const buckets = BINS.map(b => ({ ...b, count: 0, pct: 0 }));
		for (const v of vals) {
			const idx = buckets.findIndex(b => v >= b.lo && v < b.hi);
			if (idx >= 0) buckets[idx].count++;
		}
		const maxCount = Math.max(1, ...buckets.map(b => b.count));
		const wins = vals.filter(v => v > 0).length;
		return { buckets: buckets.map(b => ({ ...b, barPct: (b.count / maxCount) * 100 })), total: vals.length, wins, wr: wins / vals.length };
	});

	// Avg profit by exit reason
	const closedTradeProfitByExitReason = $derived.by(() => {
		const map = new Map<string, { sum: number; wins: number; total: number }>();
		for (const t of data.closedTrades) {
			if (!t.exit_reason || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			if (!map.has(t.exit_reason)) map.set(t.exit_reason, { sum: 0, wins: 0, total: 0 });
			const e = map.get(t.exit_reason)!;
			e.sum += t.profit_pct;
			e.total++;
			if (t.profit_pct > 0) e.wins++;
		}
		const rows = [...map.entries()]
			.filter(([, v]) => v.total >= 3)
			.map(([reason, v]) => ({ reason, avg: v.sum / v.total, wr: v.wins / v.total, count: v.total }))
			.sort((a, b) => b.avg - a.avg);
		if (rows.length < 2) return null;
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.avg)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.avg) / maxAbs) * 100 }));
	});

	const liveEntryTagPerformance = $derived.by(() => {
		const closed = data.closedTrades.filter(t => (t as any).enter_tag && t.profit_pct != null && isFinite(t.profit_pct));
		if (closed.length < 5) return null;
		const map = new Map<string, { sum: number; count: number; wins: number }>();
		for (const t of closed) {
			const tag = (t as any).enter_tag as string;
			if (!map.has(tag)) map.set(tag, { sum: 0, count: 0, wins: 0 });
			const e = map.get(tag)!;
			e.sum += t.profit_pct!;
			e.count++;
			if (t.profit_pct! > 0) e.wins++;
		}
		const rows = [...map.entries()]
			.filter(([, v]) => v.count >= 3)
			.map(([tag, v]) => ({ tag, avg: v.sum / v.count, wr: v.wins / v.count, count: v.count }))
			.sort((a, b) => b.avg - a.avg);
		if (rows.length < 2) return null;
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.avg)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.avg) / maxAbs) * 100 }));
	});

	const liveRecentTradeProfitMovingAvg = $derived.by(() => {
		const sorted = data.closedTrades
			.filter(t => t.close_date && t.profit_pct != null && isFinite(t.profit_pct))
			.sort((a, b) => a.close_date!.localeCompare(b.close_date!));
		const WINDOW = 10;
		if (sorted.length < WINDOW + 2) return null;
		const pts = sorted.slice(WINDOW - 1).map((_, i) => {
			const slice = sorted.slice(i, i + WINDOW);
			const avg = slice.reduce((s, t) => s + t.profit_pct!, 0) / WINDOW;
			return { i, avg, date: sorted[i + WINDOW - 1].close_date!.slice(0, 10) };
		});
		const W = 560, H = 72, PAD = 8;
		const vals = pts.map(p => p.avg);
		const mn = Math.min(...vals), mx = Math.max(...vals, mn + 0.01);
		const toX = (i: number) => PAD + (i / Math.max(1, pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / (mx - mn)) * (H - PAD * 2);
		const zeroY = mn < 0 && mx > 0 ? toY(0) : (mn >= 0 ? H - PAD : PAD);
		const polyline = pts.map((p, i) => `${toX(i).toFixed(1)},${toY(p.avg).toFixed(1)}`).join(' ');
		const latest = vals[vals.length - 1];
		const overall = sorted.reduce((s, t) => s + t.profit_pct!, 0) / sorted.length;
		return { W, H, polyline, zeroY, latest, overall, count: pts.length };
	});

	const liveMonthlyTradeCount = $derived.by(() => {
		const closed = data.closedTrades.filter(t => t.close_date);
		if (closed.length < 5) return null;
		const map = new Map<string, number>();
		for (const t of closed) {
			const ym = t.close_date!.slice(0, 7);
			map.set(ym, (map.get(ym) ?? 0) + 1);
		}
		const months = [...map.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(-18);
		if (months.length < 3) return null;
		const vals = months.map(m => m[1]);
		const maxCount = Math.max(1, ...vals);
		const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
		const W = 560, H = 72, PAD = 8;
		const barW = (W - PAD * 2) / months.length;
		const bars = months.map(([ym, count], i) => ({
			x: PAD + i * barW, w: barW - 1, count,
			h: (count / maxCount) * (H - PAD * 2),
			label: ym.slice(5),
			aboveAvg: count >= avg
		}));
		return { W, H, bars, avg, maxCount, PAD };
	});

	const liveStrategyProfitConcentration = $derived.by(() => {
		const map: Record<string, number> = {};
		for (const t of closedTrades) {
			if (!t.strategy || t.profit_abs == null) continue;
			map[t.strategy] = (map[t.strategy] ?? 0) + t.profit_abs;
		}
		const entries = Object.entries(map).sort((a, b) => b[1] - a[1]);
		if (entries.length < 2) return null;
		const total = entries.reduce((s, [, v]) => s + v, 0);
		if (total === 0) return null;
		const COLORS = ['var(--ch-violet-strong)', 'var(--ch-profit-strong)', 'var(--ch-warn)', 'var(--ch-loss)', 'var(--ch-teal-strong)', 'var(--ch-violet-strong)'];
		const rows = entries.slice(0, 8).map(([ strategy, profit ], i) => ({
			strategy,
			profit,
			share: (profit / total) * 100,
			color: COLORS[i % COLORS.length]
		}));
		return { rows, total };
	});

	const livePairAvgDuration = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const t of closedTrades) {
			if (!t.pair || t.trade_duration_min == null || !isFinite(t.trade_duration_min)) continue;
			if (!map[t.pair]) map[t.pair] = [];
			map[t.pair].push(t.trade_duration_min);
		}
		const rows = Object.entries(map)
			.filter(([, v]) => v.length >= 3)
			.map(([pair, durs]) => ({
				pair,
				avg: durs.reduce((a, b) => a + b, 0) / durs.length,
				count: durs.length,
				max: Math.max(...durs)
			}))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 12);
		if (rows.length < 3) return null;
		const maxAvg = Math.max(...rows.map(r => r.avg), 1);
		return { rows, maxAvg };
	});

	const liveExitReasonByBot = $derived.by(() => {
		const map: Record<string, Record<string, number>> = {};
		for (const t of closedTrades) {
			if (!t.bot_name || !t.exit_reason) continue;
			if (!map[t.bot_name]) map[t.bot_name] = {};
			map[t.bot_name][t.exit_reason] = (map[t.bot_name][t.exit_reason] ?? 0) + 1;
		}
		const bots = Object.entries(map).filter(([, v]) => Object.values(v).reduce((a, b) => a + b, 0) >= 3);
		if (bots.length < 1) return null;
		const allReasons = [...new Set(closedTrades.map(t => t.exit_reason).filter(Boolean))].slice(0, 6);
		const REASON_COL: Record<string, string> = {
			roi: 'var(--ch-profit)', stop_loss: 'var(--ch-loss)', stoploss: 'var(--ch-loss)',
			trailing_stop_loss: 'var(--ch-warn)', exit_signal: 'var(--ch-violet)', force_sell: 'var(--ch-violet-strong)'
		};
		const rows = bots.slice(0, 8).map(([bot, reasons]) => {
			const total = Object.values(reasons).reduce((a, b) => a + b, 0);
			const breakdown = allReasons.map(r => ({ reason: r, count: reasons[r] ?? 0, pct: ((reasons[r] ?? 0) / total) * 100, color: REASON_COL[r] ?? 'var(--ch-axis)' }));
			return { bot, total, breakdown };
		});
		return { rows, allReasons, REASON_COL };
	});

	const livePairSharpeProxy = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const t of closedTrades) {
			if (!t.pair || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			if (!map[t.pair]) map[t.pair] = [];
			map[t.pair].push(t.profit_pct);
		}
		const rows = Object.entries(map)
			.filter(([, v]) => v.length >= 4)
			.map(([pair, vals]) => {
				const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
				const std = Math.sqrt(vals.reduce((s, v) => s + (v - mean) ** 2, 0) / vals.length);
				const sharpe = std > 0 ? mean / std : 0;
				return { pair, sharpe, mean, count: vals.length };
			})
			.sort((a, b) => b.sharpe - a.sharpe)
			.slice(0, 12);
		if (rows.length < 3) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.sharpe)), 0.01);
		return { rows, maxAbs };
	});

	const liveBotMonthlyTradeCount = $derived.by(() => {
		const map: Record<string, Record<string, number>> = {};
		for (const t of closedTrades) {
			if (!t.bot_name || !t.close_date) continue;
			const mo = t.close_date.slice(0, 7);
			if (!map[t.bot_name]) map[t.bot_name] = {};
			map[t.bot_name][mo] = (map[t.bot_name][mo] ?? 0) + 1;
		}
		const bots = Object.keys(map).slice(0, 6);
		if (bots.length < 1) return null;
		const months = [...new Set(closedTrades.map(t => t.close_date?.slice(0, 7)).filter(Boolean) as string[])].sort().slice(-8);
		if (months.length < 2) return null;
		const maxCount = Math.max(...bots.flatMap(b => months.map(m => map[b]?.[m] ?? 0)), 1);
		const cells = bots.flatMap((bot, bi) =>
			months.map((mo, mi) => {
				const count = map[bot]?.[mo] ?? 0;
				const intensity = count / maxCount;
				return { bot, mo, count, bi, mi, color: `rgba(99,102,241,${(0.1 + intensity * 0.8).toFixed(2)})` };
			})
		);
		return { bots, months, cells, maxCount };
	});

	const liveStrategyAvgProfit = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const t of closedTrades) {
			if (!t.strategy || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			if (!map[t.strategy]) map[t.strategy] = [];
			map[t.strategy].push(t.profit_pct);
		}
		const rows = Object.entries(map)
			.filter(([, v]) => v.length >= 3)
			.map(([strategy, vals]) => ({
				strategy,
				avg: vals.reduce((a, b) => a + b, 0) / vals.length,
				count: vals.length
			}))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 12);
		if (rows.length < 2) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		return { rows, maxAbs };
	});

	const liveProfitDecileDistribution = $derived.by(() => {
		const vals = closedTrades
			.filter(t => t.profit_pct != null && isFinite(t.profit_pct))
			.map(t => t.profit_pct!)
			.sort((a, b) => a - b);
		if (vals.length < 20) return null;
		const BUCKETS = 20;
		const vMin = vals[0], vMax = vals[vals.length - 1];
		const step = (vMax - vMin) / BUCKETS || 1;
		const counts = Array.from({ length: BUCKETS }, (_, i) => {
			const lo = vMin + i * step, hi = lo + step;
			const n = vals.filter(v => v >= lo && (i === BUCKETS - 1 ? v <= hi : v < hi)).length;
			return { lo, hi, n, midPct: ((lo + hi) / 2) };
		});
		const maxN = Math.max(...counts.map(c => c.n), 1);
		const W = 560, H = 90, PAD = 8;
		const barW = Math.floor((W - PAD * 2) / BUCKETS) - 1;
		const bars = counts.map((c, i) => {
			const x = PAD + i * ((W - PAD * 2) / BUCKETS);
			const h = Math.max(c.n > 0 ? 2 : 0, (c.n / maxN) * (H - PAD * 2 - 10));
			const isPos = c.midPct >= 0;
			const frac = c.n / maxN;
			const color = isPos ? `rgba(34,197,94,${(0.3 + frac * 0.65).toFixed(2)})` : `rgba(239,68,68,${(0.3 + frac * 0.65).toFixed(2)})`;
			return { ...c, x, h, y: H - PAD - 10 - h, color };
		});
		const zeroX = PAD + ((-vMin) / (vMax - vMin)) * (W - PAD * 2);
		const posCount = vals.filter(v => v >= 0).length;
		return { bars, barW, W, H, PAD, zeroX: vMin < 0 && vMax > 0 ? zeroX : null, total: vals.length, posCount, negCount: vals.length - posCount, vMin: vMin.toFixed(2), vMax: vMax.toFixed(2) };
	});

	const livePairBotProfitMatrix = $derived.by(() => {
		const BOTS = [...new Set(closedTrades.map(t => t.bot_name).filter(Boolean))] as string[];
		const PAIRS = [...new Set(closedTrades.map(t => t.pair).filter(Boolean))] as string[];
		if (BOTS.length < 2 || PAIRS.length < 2) return null;
		const topPairs = PAIRS.map(pair => ({
			pair,
			count: closedTrades.filter(t => t.pair === pair).length
		})).sort((a, b) => b.count - a.count).slice(0, 8).map(p => p.pair);
		const topBots = BOTS.slice(0, 6);
		const cells = topPairs.flatMap(pair =>
			topBots.map(bot => {
				const ts = closedTrades.filter(t => t.pair === pair && t.bot_name === bot && t.profit_pct != null && isFinite(t.profit_pct));
				const avg = ts.length > 0 ? ts.reduce((s, t) => s + t.profit_pct!, 0) / ts.length : null;
				return { pair, bot, avg, count: ts.length };
			})
		);
		const filled = cells.filter(c => c.avg !== null);
		if (filled.length < 4) return null;
		const absMax = Math.max(...filled.map(c => Math.abs(c.avg!)), 0.01);
		return { topPairs, topBots, cells, absMax };
	});

	const liveBotStreakAnalysis = $derived.by(() => {
		const bots = [...new Set(closedTrades.map(t => t.bot_name).filter(Boolean))] as string[];
		if (bots.length === 0) return null;
		const rows = bots.map(bot => {
			const sorted = closedTrades
				.filter(t => t.bot_name === bot && t.profit_pct != null && isFinite(t.profit_pct) && t.close_date)
				.sort((a, b) => a.close_date!.localeCompare(b.close_date!));
			if (sorted.length < 5) return null;
			let maxWin = 0, maxLoss = 0, curWin = 0, curLoss = 0;
			for (const t of sorted) {
				if (t.profit_pct! >= 0) { curWin++; curLoss = 0; }
				else { curLoss++; curWin = 0; }
				maxWin = Math.max(maxWin, curWin);
				maxLoss = Math.max(maxLoss, curLoss);
			}
			const total = sorted.length;
			const wins = sorted.filter(t => t.profit_pct! >= 0).length;
			return { bot, maxWin, maxLoss, total, winRate: (wins / total) * 100 };
		}).filter((r): r is NonNullable<typeof r> => r !== null);
		if (rows.length === 0) return null;
		const maxStreak = Math.max(...rows.map(r => Math.max(r.maxWin, r.maxLoss)), 1);
		return { rows, maxStreak };
	});

	const liveStrategyProfitBoxplot = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const t of data.trades) {
			if (t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			if (!map[t.strategy]) map[t.strategy] = [];
			map[t.strategy].push(t.profit_pct);
		}
		const rows = Object.entries(map)
			.filter(([, v]) => v.length >= 3)
			.map(([strategy, vals]) => {
				const s = [...vals].sort((a, b) => a - b);
				const q1 = s[Math.floor(s.length * 0.25)];
				const med = s[Math.floor(s.length * 0.5)];
				const q3 = s[Math.floor(s.length * 0.75)];
				const avg = s.reduce((a, b) => a + b, 0) / s.length;
				return { strategy, q1, med, q3, avg, min: s[0], max: s[s.length - 1], count: s.length };
			})
			.sort((a, b) => b.med - a.med)
			.slice(0, 10);
		if (rows.length < 2) return null;
		const allVals = rows.flatMap(r => [r.min, r.max]);
		const mn = Math.min(...allVals), mx = Math.max(...allVals, mn + 0.01);
		const W = 560, PAD = 8;
		const toX = (v: number) => PAD + ((v - mn) / (mx - mn)) * (W - PAD * 2);
		const zeroX = mn <= 0 && mx >= 0 ? toX(0) : null;
		const rects = rows.map((r, i) => ({
			y: i * 18 + 5, x1: toX(r.q1), x3: toX(r.q3), xMed: toX(r.med), xAvg: toX(r.avg),
			strategy: r.strategy.slice(0, 20), count: r.count,
			color: r.med >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'
		}));
		const H = rows.length * 18 + 10;
		return { W, H, rects, zeroX, mn: mn.toFixed(2), mx: mx.toFixed(2) };
	});

	const liveDurationByPair = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const t of data.trades) {
			if (!t.pair || t.trade_duration_min == null || !isFinite(t.trade_duration_min)) continue;
			if (!map[t.pair]) map[t.pair] = [];
			map[t.pair].push(t.trade_duration_min);
		}
		const rows = Object.entries(map)
			.filter(([, v]) => v.length >= 2)
			.map(([pair, v]) => {
				const avg = v.reduce((a, b) => a + b, 0) / v.length;
				return { pair: pair.replace('/USDT', '').replace(':USDT', ''), avg, count: v.length };
			})
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 14);
		if (rows.length < 3) return null;
		const maxAvg = Math.max(...rows.map(r => r.avg), 1);
		const toHrs = (m: number) => m >= 1440 ? `${(m / 1440).toFixed(1)}d` : m >= 60 ? `${(m / 60).toFixed(1)}h` : `${m.toFixed(0)}m`;
		return { rows, maxAvg, toHrs };
	});

	const liveProfitByHourOfDay = $derived.by(() => {
		const map: Record<number, number[]> = {};
		for (const t of data.trades) {
			if (t.close_date == null || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			const hr = new Date(t.close_date).getUTCHours();
			if (!map[hr]) map[hr] = [];
			map[hr].push(t.profit_pct);
		}
		const rows = Array.from({ length: 24 }, (_, h) => {
			const vals = map[h] ?? [];
			const avg = vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
			return { hr: h, avg, count: vals.length };
		});
		if (rows.every(r => r.count === 0)) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 520, H = 70, PAD = 6, barW = Math.floor((W - PAD * 2) / 24) - 1;
		return { rows, maxAbs, W, H, PAD, barW };
	});

	const liveProfitByExitReason = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const t of trades) {
			if (!t.exit_reason) continue;
			if (!map[t.exit_reason]) map[t.exit_reason] = [];
			map[t.exit_reason].push(t.profit_pct);
		}
		const rows = Object.entries(map)
			.map(([reason, vals]) => ({ reason, avg: vals.reduce((a, b) => a + b, 0) / vals.length, count: vals.length }))
			.sort((a, b) => b.avg - a.avg);
		if (rows.length < 2) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 400, H = Math.max(80, rows.length * 14 + 20), PAD = 8, barMaxW = (W - PAD * 2) / 2 - 60, midX = W / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, midX };
	});

	const liveProfitHistogram = $derived.by(() => {
		const vals = trades.map(t => t.profit_pct).filter(v => v != null && isFinite(v)) as number[];
		if (vals.length < 5) return null;
		const mn = Math.min(...vals), mx = Math.max(...vals);
		const bins = 14;
		const step = (mx - mn) / bins || 1;
		const counts = Array.from({ length: bins }, (_, i) => {
			const lo = mn + i * step, hi = lo + step;
			return { lo, hi, count: vals.filter(v => v >= lo && (i === bins - 1 ? v <= hi : v < hi)).length };
		});
		const maxCount = Math.max(...counts.map(c => c.count), 1);
		const W = 400, H = 80, PAD = 8, barW = Math.floor((W - PAD * 2) / bins) - 1;
		const avg = (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(2);
		return { counts, maxCount, W, H, PAD, barW, mn: mn.toFixed(2), mx: mx.toFixed(2), avg };
	});

	const liveCumulativeProfitTimeline = $derived.by(() => {
		const sorted = [...trades]
			.filter(t => t.close_date != null && t.profit_pct != null)
			.sort((a, b) => new Date(a.close_date!).getTime() - new Date(b.close_date!).getTime());
		if (sorted.length < 3) return null;
		let cum = 0;
		const pts = sorted.map((t, i) => { cum += t.profit_pct!; return { i, cum }; });
		const minC = Math.min(...pts.map(p => p.cum)), maxC = Math.max(...pts.map(p => p.cum));
		const W = 520, H = 90, PAD = 16;
		const toX = (i: number) => PAD + (i / (pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - (v - minC) / (maxC - minC || 1)) * (H - PAD * 2);
		const polyline = pts.map(p => `${toX(p.i).toFixed(1)},${toY(p.cum).toFixed(1)}`).join(' ');
		const zeroY = toY(0);
		const finalCum = pts[pts.length - 1].cum;
		return { pts, polyline, W, H, PAD, toX, toY, zeroY, minC, maxC, finalCum: finalCum.toFixed(2) };
	});

	const livePairProfitScatter = $derived.by(() => {
		const map: Record<string, { profits: number[]; durations: number[] }> = {};
		for (const t of trades) {
			if (!t.pair || t.profit_pct == null) continue;
			if (!map[t.pair]) map[t.pair] = { profits: [], durations: [] };
			map[t.pair].profits.push(t.profit_pct);
			if (t.trade_duration_min != null) map[t.pair].durations.push(t.trade_duration_min);
		}
		const pts = Object.entries(map).map(([pair, v]) => ({
			pair,
			avg: v.profits.reduce((a, b) => a + b, 0) / v.profits.length,
			count: v.profits.length,
			avgDur: v.durations.length > 0 ? v.durations.reduce((a, b) => a + b, 0) / v.durations.length / 60 : 0
		}));
		if (pts.length < 3) return null;
		const W = 400, H = 120, PAD = 20;
		const maxAbs = Math.max(...pts.map(p => Math.abs(p.avg)), 0.01);
		const maxDur = Math.max(...pts.map(p => p.avgDur), 0.01);
		const maxCount = Math.max(...pts.map(p => p.count), 1);
		const toX = (v: number) => PAD + ((v + maxAbs) / (maxAbs * 2)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - v / maxDur) * (H - PAD * 2);
		const dots = pts.map(p => ({ pair: p.pair.split('/')[0], cx: toX(p.avg), cy: toY(p.avgDur), r: 2 + (p.count / maxCount) * 6, color: p.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)' }));
		return { dots, W, H, PAD, zeroX: toX(0), count: pts.length };
	});

	const liveProfitByDayOfWeek = $derived.by(() => {
		const DAY = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const buckets = DAY.map(d => ({ day: d, profits: [] as number[] }));
		for (const t of trades) {
			if (!t.close_date || t.profit_pct == null) continue;
			const dow = new Date(t.close_date).getUTCDay();
			buckets[dow].profits.push(t.profit_pct);
		}
		const rows = buckets.filter(b => b.profits.length >= 2).map(b => ({
			day: b.day,
			avg: b.profits.reduce((a, v) => a + v, 0) / b.profits.length,
			count: b.profits.length
		}));
		if (rows.length < 3) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 320, H = 80, PAD = 10, barW = Math.floor((W - PAD * 2) / 7) - 3, midY = H / 2;
		return { rows: buckets.map(b => ({ day: b.day, avg: b.profits.length >= 1 ? b.profits.reduce((a, v) => a + v, 0) / b.profits.length : 0, count: b.profits.length })), maxAbs, W, H, PAD, barW, midY };
	});

	const liveExitTagProfitRanking = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const t of trades) {
			if (!t.exit_reason || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			const tag = t.exit_reason.slice(0, 16);
			if (!map.has(tag)) map.set(tag, []);
			map.get(tag)!.push(t.profit_pct);
		}
		const rows = [...map.entries()]
			.filter(([, vals]) => vals.length >= 2)
			.map(([tag, vals]) => {
				const avg = vals.reduce((a, v) => a + v, 0) / vals.length;
				const winPct = (vals.filter(v => v >= 0).length / vals.length) * 100;
				return { tag, avg, winPct, count: vals.length };
			})
			.sort((a, b) => b.avg - a.avg);
		if (rows.length < 2) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		return { rows, maxAbs };
	});

	const liveBotProfitTimeline = $derived.by(() => {
		const botMap = new Map<string, { ts: number; profit: number }[]>();
		for (const t of trades) {
			if (!t.bot_name || !t.close_date || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			if (!botMap.has(t.bot_name)) botMap.set(t.bot_name, []);
			botMap.get(t.bot_name)!.push({ ts: new Date(t.close_date).getTime(), profit: t.profit_pct });
		}
		if (botMap.size < 2) return null;
		const bots = [...botMap.keys()].slice(0, 5);
		const colors = ['var(--ch-profit-strong)','var(--ch-violet-strong)','var(--ch-warn)','var(--ch-warn)','var(--ch-loss-strong)'];
		const allTs = [...botMap.values()].flat().map(p => p.ts);
		const minTs = Math.min(...allTs), maxTs = Math.max(...allTs);
		const W = 400, H = 85, PAD = 12;
		const toX = (ts: number) => PAD + ((ts - minTs) / (maxTs - minTs || 1)) * (W - PAD * 2);
		const lines = bots.map((bot, bi) => {
			const pts = (botMap.get(bot) ?? []).sort((a, b) => a.ts - b.ts);
			let cum = 0;
			const cumPts = pts.map(p => { cum += p.profit; return { x: toX(p.ts), cum }; });
			return { bot: bot.slice(0, 12), color: colors[bi], pts: cumPts };
		});
		const allCum = lines.flatMap(l => l.pts.map(p => p.cum));
		const mnC = Math.min(...allCum, 0), mxC = Math.max(...allCum, 0.01);
		const toY = (v: number) => PAD + (1 - (v - mnC) / (mxC - mnC)) * (H - PAD * 2);
		const zeroY = toY(0);
		const polylines = lines.map(l => ({ ...l, poly: l.pts.map(p => `${p.x.toFixed(1)},${toY(p.cum).toFixed(1)}`).join(' ') }));
		return { polylines, W, H, PAD, zeroY: Math.max(PAD, Math.min(H - PAD, zeroY)) };
	});

	const livePairAvgProfitRanking = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const t of trades) {
			if (!t.pair || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			const base = t.pair.split('/')[0];
			if (!map.has(base)) map.set(base, []);
			map.get(base)!.push(t.profit_pct);
		}
		const rows = [...map.entries()]
			.filter(([, vals]) => vals.length >= 3)
			.map(([pair, vals]) => {
				const avg = vals.reduce((a, v) => a + v, 0) / vals.length;
				return { pair, avg, count: vals.length };
			})
			.sort((a, b) => b.avg - a.avg);
		if (rows.length < 3) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		return { rows: rows.slice(0, 14), maxAbs };
	});

	const liveBotDrawdownComparison = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const t of trades) {
			if (!t.bot_name || t.max_drawdown_pct == null || !isFinite(t.max_drawdown_pct)) continue;
			if (!map.has(t.bot_name)) map.set(t.bot_name, []);
			map.get(t.bot_name)!.push(Math.abs(t.max_drawdown_pct));
		}
		const rows = [...map.entries()]
			.filter(([, vals]) => vals.length >= 3)
			.map(([bot, vals]) => {
				const sorted = [...vals].sort((a, b) => a - b);
				const med = sorted[Math.floor(sorted.length / 2)];
				const p90 = sorted[Math.floor(sorted.length * 0.9)];
				return { bot: bot.slice(0, 18), med, p90, count: vals.length };
			})
			.sort((a, b) => b.med - a.med)
			.slice(0, 8);
		if (rows.length < 2) return null;
		const maxVal = Math.max(...rows.map(r => r.p90), 0.01);
		return { rows, maxVal };
	});

	const liveProfitByStakeSize = $derived.by(() => {
		const validTrades = trades.filter(t => t.stake_amount != null && isFinite(t.stake_amount) && t.profit_pct != null && isFinite(t.profit_pct));
		if (validTrades.length < 10) return null;
		const stakes = validTrades.map(t => t.stake_amount!);
		const mn = Math.min(...stakes), mx = Math.max(...stakes);
		const step = (mx - mn) / 5 || 1;
		const bins = Array.from({ length: 5 }, (_, i) => ({ lo: mn + i * step, hi: mn + (i + 1) * step, profits: [] as number[] }));
		for (const t of validTrades) {
			const bi = Math.min(4, Math.floor((t.stake_amount! - mn) / step));
			bins[bi].profits.push(t.profit_pct!);
		}
		const rows = bins.filter(b => b.profits.length >= 3).map(b => ({
			label: `${b.lo.toFixed(0)}–${b.hi.toFixed(0)}`,
			avg: b.profits.reduce((a, v) => a + v, 0) / b.profits.length,
			count: b.profits.length
		}));
		if (rows.length < 2) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 320, H = 72, PAD = 8, barW = Math.floor((W - PAD * 2) / rows.length) - 3, midY = H / 2;
		return { rows, maxAbs, W, H, PAD, barW, midY };
	});

	const liveProfitByCloseHour = $derived.by(() => {
		const valid = trades.filter(t => t.close_date != null && t.profit_pct != null && isFinite(t.profit_pct));
		if (valid.length < 12) return null;
		const buckets = Array.from({ length: 24 }, () => [] as number[]);
		for (const t of valid) {
			const h = new Date(t.close_date!).getUTCHours();
			if (h >= 0 && h < 24) buckets[h].push(t.profit_pct!);
		}
		const hours = buckets.map((profs, h) => ({ h, avg: profs.length ? profs.reduce((a, v) => a + v, 0) / profs.length : 0, count: profs.length })).filter(x => x.count >= 1);
		if (hours.length < 4) return null;
		const maxAbs = Math.max(...hours.map(r => Math.abs(r.avg)), 0.01);
		const W = 360, H = 68, PAD = 6, barW = Math.max(2, Math.floor((W - PAD * 2) / 24) - 1), midY = H / 2;
		return { hours, maxAbs, W, H, PAD, barW, midY };
	});

	const liveBotWinRateTrend = $derived.by(() => {
		const botMonths = new Map<string, Map<string, { wins: number; total: number }>>();
		for (const t of trades) {
			if (!t.bot_name || !t.close_date || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			if (!botMonths.has(t.bot_name)) botMonths.set(t.bot_name, new Map());
			const mo = t.close_date.slice(0, 7);
			if (!botMonths.get(t.bot_name)!.has(mo)) botMonths.get(t.bot_name)!.set(mo, { wins: 0, total: 0 });
			const e = botMonths.get(t.bot_name)!.get(mo)!;
			e.total++;
			if (t.profit_pct >= 0) e.wins++;
		}
		const allMonths = [...new Set([...botMonths.values()].flatMap(m => [...m.keys()]))].sort();
		if (allMonths.length < 3 || botMonths.size < 2) return null;
		const bColors = ['var(--ch-profit-strong)', 'var(--ch-violet-strong)', 'var(--ch-warn)', 'var(--ch-warn)'];
		const bots = [...botMonths.keys()].slice(0, 4);
		const W = 360, H = 75, PAD = 10;
		const toX = (i: number) => PAD + (i / Math.max(allMonths.length - 1, 1)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - v / 100) * (H - PAD * 2);
		const y50 = toY(50);
		const lines = bots.map((bot, bi) => {
			const pts = allMonths.map((mo, i) => {
				const e = botMonths.get(bot)?.get(mo);
				return e && e.total >= 2 ? { i, wr: (e.wins / e.total) * 100 } : null;
			}).filter(Boolean) as { i: number; wr: number }[];
			const poly = pts.map(p => `${toX(p.i).toFixed(1)},${toY(p.wr).toFixed(1)}`).join(' ');
			return { bot: bot.slice(0, 14), color: bColors[bi], poly };
		}).filter(l => l.poly.length > 0);
		if (lines.length < 2) return null;
		return { lines, allMonths, W, H, PAD, y50 };
	});

	const livePairTradeCountRanking = $derived.by(() => {
		const map = new Map<string, { count: number; profits: number[] }>();
		for (const t of trades) {
			if (!t.pair) continue;
			if (!map.has(t.pair)) map.set(t.pair, { count: 0, profits: [] });
			const e = map.get(t.pair)!;
			e.count++;
			if (t.profit_pct != null && isFinite(t.profit_pct)) e.profits.push(t.profit_pct);
		}
		const rows = [...map.entries()]
			.map(([pair, e]) => ({ pair: pair.slice(0, 14), count: e.count, avgProfit: e.profits.length ? e.profits.reduce((a, v) => a + v, 0) / e.profits.length : 0 }))
			.sort((a, b) => b.count - a.count)
			.slice(0, 10);
		if (rows.length < 3) return null;
		const maxCount = Math.max(...rows.map(r => r.count), 1);
		const W = 340, H = rows.length * 16 + 4, barMaxW = W - 120;
		return { rows, maxCount, W, H, barMaxW };
	});

	const liveMonthlyTradeCountTrend = $derived.by(() => {
		const map = new Map<string, number>();
		for (const t of data.trades) {
			if (!t.close_date) continue;
			const mo = t.close_date.slice(0, 7);
			map.set(mo, (map.get(mo) ?? 0) + 1);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const counts = months.map(m => ({ mo: m, count: map.get(m)! }));
		const maxC = Math.max(...counts.map(c => c.count), 1);
		const W = 360, H = 72, PAD = 10;
		const bw = Math.max(3, (W - PAD * 2) / counts.length - 2);
		const toX = (i: number) => PAD + i * ((W - PAD * 2) / Math.max(counts.length - 1, 1));
		const bars = counts.map((c, i) => ({
			x: PAD + i * ((W - PAD * 2) / counts.length),
			h: Math.max(2, (c.count / maxC) * (H - PAD - 14)),
			count: c.count,
			mo: c.mo.slice(5),
			color: `rgba(99,102,241,${0.3 + (c.count / maxC) * 0.55})`,
		}));
		return { bars, bw, W, H, PAD, maxC, count: counts.length };
	});

	const liveProfitByDurationBucket = $derived.by(() => {
		const buckets = [
			{ label: '<1h', min: 0, max: 60 },
			{ label: '1–4h', min: 60, max: 240 },
			{ label: '4–24h', min: 240, max: 1440 },
			{ label: '1–3d', min: 1440, max: 4320 },
			{ label: '>3d', min: 4320, max: Infinity },
		].map(b => ({ ...b, profits: [] as number[] }));
		for (const t of data.trades) {
			if (t.profit_pct == null || !isFinite(t.profit_pct) || t.trade_duration == null) continue;
			const dur = t.trade_duration;
			const b = buckets.find(bk => dur >= bk.min && dur < bk.max);
			if (b) b.profits.push(t.profit_pct);
		}
		const rows = buckets.filter(b => b.profits.length >= 2).map(b => {
			const avg = b.profits.reduce((a, v) => a + v, 0) / b.profits.length;
			return { label: b.label, avg, count: b.profits.length };
		});
		if (rows.length < 2) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 320, H = 72, PAD = 10, barW = Math.floor((W - PAD * 2) / rows.length) - 4, midY = H / 2;
		return { rows, maxAbs, W, H, PAD, barW, midY };
	});

	const liveProfitPerBotBar = $derived.by(() => {
		const map = new Map<string, { sum: number; count: number }>();
		for (const t of data.trades) {
			if (!t.bot_name || t.profit_abs == null || !isFinite(t.profit_abs)) continue;
			const cur = map.get(t.bot_name) ?? { sum: 0, count: 0 };
			cur.sum += t.profit_abs;
			cur.count++;
			map.set(t.bot_name, cur);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()].map(([bot, d]) => ({ bot: bot.slice(0, 16), total: d.sum, count: d.count }))
			.sort((a, b) => b.total - a.total);
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.total)), 0.01);
		const W = 340, H = rows.length * 18 + 8, PAD = 8, barMaxW = W - 100;
		return { rows, maxAbs, W, H, PAD, barMaxW };
	});

	const liveBotAvgTradeDuration = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const t of data.trades) {
			if (!t.bot_name || t.trade_duration == null || !isFinite(t.trade_duration) || t.trade_duration < 0) continue;
			const arr = map.get(t.bot_name) ?? [];
			arr.push(t.trade_duration);
			map.set(t.bot_name, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()].map(([bot, durs]) => ({
			bot: bot.slice(0, 16),
			avg: durs.reduce((a, v) => a + v, 0) / durs.length,
			count: durs.length,
		})).sort((a, b) => b.avg - a.avg);
		const maxVal = Math.max(...rows.map(r => r.avg), 0.01);
		const W = 340, H = rows.length * 16 + 6, PAD = 8, barMaxW = W - 100;
		return { rows, maxVal, W, H, PAD, barMaxW };
	});

	const liveProfitByMonth = $derived.by(() => {
		const map = new Map<string, number>();
		for (const t of data.trades) {
			if (!t.close_date || t.profit_abs == null || !isFinite(t.profit_abs)) continue;
			const mo = t.close_date.slice(0, 7);
			map.set(mo, (map.get(mo) ?? 0) + t.profit_abs);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const rows = months.map(m => ({ mo: m.slice(5), profit: map.get(m)! }));
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.profit)), 0.01);
		const W = 360, H = 72, PAD = 10;
		const bw = Math.max(3, (W - PAD * 2) / rows.length - 2);
		const midY = H / 2;
		const bars = rows.map((r, i) => ({
			x: PAD + i * ((W - PAD * 2) / rows.length),
			h: Math.max(2, (Math.abs(r.profit) / maxAbs) * (midY - PAD - 4)),
			profit: r.profit, mo: r.mo,
			color: r.profit >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)',
		}));
		return { bars, bw, W, H, PAD, midY, total: rows.reduce((a, r) => a + r.profit, 0) };
	});

	const livePairWinRateRanking = $derived.by(() => {
		const map = new Map<string, { wins: number; total: number }>();
		for (const t of data.trades) {
			if (!t.pair || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			const cur = map.get(t.pair) ?? { wins: 0, total: 0 };
			cur.total++;
			if (t.profit_pct > 0) cur.wins++;
			map.set(t.pair, cur);
		}
		if (map.size < 3) return null;
		const rows = [...map.entries()]
			.filter(([, d]) => d.total >= 3)
			.map(([pair, d]) => ({ pair: pair.slice(0, 14), wr: (d.wins / d.total) * 100, count: d.total }))
			.sort((a, b) => b.wr - a.wr).slice(0, 10);
		if (rows.length < 3) return null;
		const W = 340, H = rows.length * 16 + 6, PAD = 8, barMaxW = W - 90;
		return { rows, W, H, PAD, barMaxW };
	});

	const liveCumProfitByBot = $derived.by(() => {
		const botMap = new Map<string, { date: string; profit: number }[]>();
		for (const t of data.trades) {
			if (!t.close_date || t.profit_abs == null || !isFinite(t.profit_abs) || !t.bot_name) continue;
			const arr = botMap.get(t.bot_name) ?? [];
			arr.push({ date: t.close_date.slice(0, 10), profit: t.profit_abs });
			botMap.set(t.bot_name, arr);
		}
		if (botMap.size < 2) return null;
		const allDates = [...new Set([...botMap.values()].flatMap(a => a.map(p => p.date)))].sort();
		if (allDates.length < 3) return null;
		const W = 380, H = 80, PAD = 10;
		const toX = (i: number) => PAD + (i / (allDates.length - 1)) * (W - PAD * 2);
		const colors = ['var(--ch-profit)', 'var(--ch-violet)', 'var(--ch-warn)', 'var(--ch-loss-strong)', 'var(--ch-teal)'];
		const lines = [...botMap.entries()].slice(0, 5).map(([bot, trades], ci) => {
			const sorted = trades.sort((a, b) => a.date.localeCompare(b.date));
			let cum = 0;
			const cumByDate = new Map(sorted.map(t => { cum += t.profit; return [t.date, cum]; }));
			let last = 0;
			const pts = allDates.map((d, i) => { if (cumByDate.has(d)) last = cumByDate.get(d)!; return { x: toX(i), cum: last }; });
			return { bot: bot.slice(0, 10), pts, color: colors[ci % colors.length], final: last };
		});
		const allCums = lines.flatMap(l => l.pts.map(p => p.cum));
		const minC = Math.min(...allCums), maxC = Math.max(...allCums);
		const range = maxC - minC || 1;
		const toY = (v: number) => PAD + ((maxC - v) / range) * (H - PAD * 2);
		const polylines = lines.map(l => ({ ...l, points: l.pts.map(p => `${p.x},${toY(p.cum)}`).join(' ') }));
		const zeroY = Math.max(PAD, Math.min(H - PAD, toY(0)));
		return { polylines, W, H, PAD, zeroY, firstDate: allDates[0], lastDate: allDates[allDates.length - 1] };
	});

	const livePairProfitDistribution = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const t of data.trades) {
			if (!t.pair || t.profit_pct == null || !isFinite(t.profit_pct)) continue;
			const arr = map.get(t.pair) ?? [];
			arr.push(t.profit_pct);
			map.set(t.pair, arr);
		}
		if (map.size < 4) return null;
		const avgs = [...map.entries()]
			.filter(([, v]) => v.length >= 2)
			.map(([, v]) => v.reduce((a, x) => a + x, 0) / v.length);
		if (avgs.length < 4) return null;
		const mn = Math.min(...avgs), mx = Math.max(...avgs);
		const bins = 10;
		const binSize = (mx - mn) / bins || 1;
		const buckets = Array.from({ length: bins }, (_, i) => ({ lo: mn + i * binSize, count: 0 }));
		for (const v of avgs) {
			const bi = Math.min(bins - 1, Math.floor((v - mn) / binSize));
			buckets[bi].count++;
		}
		const maxC = Math.max(...buckets.map(b => b.count), 1);
		const W = 360, H = 68, PAD = 10;
		const bw = (W - PAD * 2) / bins - 1;
		const zeroX = PAD + Math.max(0, (-mn / (mx - mn || 1))) * (W - PAD * 2);
		const bars = buckets.map((b, i) => ({
			x: PAD + i * ((W - PAD * 2) / bins),
			h: Math.max(2, (b.count / maxC) * (H - PAD - 14)),
			color: b.lo >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss-light)',
		}));
		return { bars, bw, W, H, PAD, zeroX, mn: mn.toFixed(2), mx: mx.toFixed(2), total: avgs.length };
	});

	const liveAvgProfitByDow = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const map = new Map<number, { sum: number; count: number }>();
		for (const t of trades) {
			if (!t.open_date) continue;
			const dow = new Date(t.open_date).getUTCDay();
			const e = map.get(dow) ?? { sum: 0, count: 0 };
			e.sum += (t.profit_ratio ?? 0) * 100;
			e.count++;
			map.set(dow, e);
		}
		if (map.size < 3) return null;
		const rows = DAYS.map((day, d) => {
			const e = map.get(d);
			return { day, avg: e ? e.sum / e.count : 0, count: e?.count ?? 0 };
		});
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 300, H = 72, PAD = 10;
		const bw = (W - PAD * 2) / 7 - 2;
		const midY = H / 2;
		const toH = (v: number) => (Math.abs(v) / maxAbs) * (midY - PAD - 2);
		return { rows, W, H, PAD, bw, midY, toH };
	});

	const liveCumProfitTimeline = $derived.by(() => {
		if (!trades || trades.length < 6) return null;
		const sorted = [...trades]
			.filter(t => t.close_date && t.profit_abs != null)
			.sort((a, b) => new Date(a.close_date as string).getTime() - new Date(b.close_date as string).getTime());
		if (sorted.length < 5) return null;
		let cum = 0;
		const pts = sorted.map(t => { cum += t.profit_abs as number; return cum; });
		const minV = Math.min(...pts, 0);
		const maxV = Math.max(...pts, 0.01);
		const range = maxV - minV || 0.01;
		const W = 380, H = 80, PAD = 10;
		const toX = (i: number) => PAD + (i / (pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - minV) / range) * (H - PAD * 2);
		const zeroY = toY(0);
		const polyline = pts.map((v, i) => `${toX(i)},${toY(v)}`).join(' ');
		const area = `${toX(0)},${zeroY} ${polyline} ${toX(pts.length - 1)},${zeroY}`;
		const last = pts[pts.length - 1];
		const color = last >= 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss-strong)';
		return { pts, polyline, area, W, H, PAD, toX, zeroY, color, last: last.toFixed(2), fillColor: last >= 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)' };
	});

	const liveProfitVsDurationScatter = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const pts = trades
			.filter(t => t.open_date && t.close_date && t.profit_ratio != null)
			.map(t => ({
				dur: (new Date(t.close_date as string).getTime() - new Date(t.open_date as string).getTime()) / 3600000,
				profit: (t.profit_ratio as number) * 100,
			}))
			.filter(p => p.dur > 0 && p.dur < 720);
		if (pts.length < 8) return null;
		const durMax = Math.max(...pts.map(p => p.dur));
		const profMin = Math.min(...pts.map(p => p.profit), 0);
		const profMax = Math.max(...pts.map(p => p.profit), 0.01);
		const range = profMax - profMin || 0.01;
		const W = 320, H = 110, PAD = 14;
		const toX = (d: number) => PAD + (d / durMax) * (W - PAD * 2);
		const toY = (p: number) => H - PAD - ((p - profMin) / range) * (H - PAD * 2);
		const zeroY = toY(0);
		return { pts, W, H, PAD, toX, toY, zeroY, durMax: durMax.toFixed(0), profMax: profMax.toFixed(1), profMin: profMin.toFixed(1) };
	});

	const livePairSharpeRanking = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const map = new Map<string, { sum: number; count: number }>();
		for (const t of trades) {
			if (!t.pair || t.profit_ratio == null) continue;
			const s = map.get(t.pair as string) ?? { sum: 0, count: 0 };
			s.sum += (t.profit_ratio as number) * 100;
			s.count++;
			map.set(t.pair as string, s);
		}
		const rows = [...map.entries()]
			.filter(([, s]) => s.count >= 3)
			.map(([pair, s]) => ({ pair: pair.replace('/USDT', '').slice(0, 10), avg: s.sum / s.count }))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 12);
		if (rows.length < 4) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 340, H = rows.length * 16 + 6, PAD = 8, barMaxW = W - 90;
		const zeroX = PAD + (barMaxW / 2);
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const liveBotProfitByPairCount = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const botPairs = new Map<string, Set<string>>();
		const botProfit = new Map<string, number>();
		for (const t of trades) {
			if (!t.bot_name || !t.pair || t.profit_abs == null) continue;
			const bot = t.bot_name as string;
			if (!botPairs.has(bot)) botPairs.set(bot, new Set());
			botPairs.get(bot)!.add(t.pair as string);
			botProfit.set(bot, (botProfit.get(bot) ?? 0) + (t.profit_abs as number));
		}
		if (botPairs.size < 3) return null;
		const pts = [...botPairs.entries()].map(([bot, pairs]) => ({
			x: pairs.size,
			y: botProfit.get(bot) ?? 0,
			bot: bot.slice(0, 12)
		}));
		const xMax = Math.max(...pts.map(p => p.x), 1);
		const yMin = Math.min(...pts.map(p => p.y), 0);
		const yMax = Math.max(...pts.map(p => p.y), 0.01);
		const range = yMax - yMin || 0.01;
		const W = 280, H = 90, PAD = 12;
		const toX = (x: number) => PAD + (x / xMax) * (W - PAD * 2);
		const toY = (y: number) => H - PAD - ((y - yMin) / range) * (H - PAD * 2);
		const zeroY = toY(0);
		return { pts, W, H, PAD, toX, toY, zeroY, xMax };
	});

	const liveHoldTimeTrend = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const map = new Map<string, number[]>();
		for (const t of trades) {
			if (!t.open_date || !t.close_date) continue;
			const mo = (t.open_date as string).slice(0, 7);
			const dur = (new Date(t.close_date as string).getTime() - new Date(t.open_date as string).getTime()) / 3600000;
			if (dur <= 0 || dur > 720) continue;
			const arr = map.get(mo) ?? [];
			arr.push(dur);
			map.set(mo, arr);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const pts = months.map(m => { const arr = map.get(m)!; return { m: m.slice(5), avg: arr.reduce((a, v) => a + v, 0) / arr.length }; });
		const maxV = Math.max(...pts.map(p => p.avg), 0.01);
		const W = 340, H = 68, PAD = 10;
		const toX = (i: number) => PAD + (i / (pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v / maxV) * (H - PAD * 2);
		const polyline = pts.map((p, i) => `${toX(i)},${toY(p.avg)}`).join(' ');
		return { pts, polyline, W, H, PAD, toX, toY, maxV: maxV.toFixed(1), firstMo: pts[0].m, lastMo: pts[pts.length - 1].m };
	});

	const liveTradeCountByBot = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const map = new Map<string, number>();
		for (const t of trades) {
			if (!t.bot_name) continue;
			map.set(t.bot_name as string, (map.get(t.bot_name as string) ?? 0) + 1);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([bot, count]) => ({ bot: bot.slice(0, 14), count }))
			.sort((a, b) => b.count - a.count)
			.slice(0, 10);
		const maxCount = Math.max(...rows.map(r => r.count), 1);
		const W = 320, H = rows.length * 16 + 6, PAD = 8, barMaxW = W - 100;
		return { rows, maxCount, W, H, PAD, barMaxW };
	});

	const liveProfitByPairGroup = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const groups: Record<string, number[]> = { BTC: [], ETH: [], SOL: [], BNB: [], Other: [] };
		for (const t of trades) {
			if (t.profit_ratio == null || !t.pair) continue;
			const base = (t.pair as string).split('/')[0];
			const key = ['BTC', 'ETH', 'SOL', 'BNB'].includes(base) ? base : 'Other';
			groups[key].push(t.profit_ratio as number);
		}
		const rows = Object.entries(groups)
			.filter(([, vals]) => vals.length > 0)
			.map(([grp, vals]) => ({ grp, avg: (vals.reduce((a, v) => a + v, 0) / vals.length) * 100 }))
			.sort((a, b) => b.avg - a.avg);
		if (rows.length < 2) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 320, H = rows.length * 22 + 6, PAD = 8, barMaxW = W - 60;
		const zeroX = PAD + barMaxW / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const liveWinStreakDistribution = $derived.by(() => {
		if (!trades || trades.length < 15) return null;
		const sorted = [...trades]
			.filter(t => t.close_date && t.profit_ratio != null)
			.sort((a, b) => (a.close_date as string).localeCompare(b.close_date as string));
		if (sorted.length < 15) return null;
		const streaks: number[] = [];
		let cur = 0;
		let prevWin: boolean | null = null;
		for (const t of sorted) {
			const win = (t.profit_ratio as number) > 0;
			if (prevWin === null || win === prevWin) { cur++; }
			else { if (cur > 0) streaks.push(prevWin ? cur : -cur); cur = 1; }
			prevWin = win;
		}
		if (cur > 0 && prevWin !== null) streaks.push(prevWin ? cur : -cur);
		const wins = streaks.filter(s => s > 0);
		const losses = streaks.filter(s => s < 0).map(s => -s);
		const maxWin = Math.max(...wins, 1);
		const maxLoss = Math.max(...losses, 1);
		const avgWin = wins.length ? wins.reduce((a, v) => a + v, 0) / wins.length : 0;
		const avgLoss = losses.length ? losses.reduce((a, v) => a + v, 0) / losses.length : 0;
		const W = 320, H = 56, PAD = 8;
		const midX = W / 2;
		const winBarW = maxWin > 0 ? ((W - PAD * 2) / 2 * avgWin / maxWin) : 0;
		const lossBarW = maxLoss > 0 ? ((W - PAD * 2) / 2 * avgLoss / maxLoss) : 0;
		return { wins: wins.length, losses: losses.length, avgWin: avgWin.toFixed(1), avgLoss: avgLoss.toFixed(1), maxWin, maxLoss, winBarW, lossBarW, midX, W, H, PAD };
	});

	const liveProfitVolatility = $derived.by(() => {
		if (!trades || trades.length < 20) return null;
		const sorted = [...trades]
			.filter(t => t.close_date && t.profit_ratio != null)
			.sort((a, b) => (a.close_date as string).localeCompare(b.close_date as string));
		if (sorted.length < 20) return null;
		const profits = sorted.map(t => (t.profit_ratio as number) * 100);
		const WINDOW = 10;
		const pts: { i: number; vol: number }[] = [];
		for (let i = WINDOW - 1; i < profits.length; i++) {
			const slice = profits.slice(i - WINDOW + 1, i + 1);
			const mean = slice.reduce((a, v) => a + v, 0) / WINDOW;
			const variance = slice.reduce((a, v) => a + (v - mean) ** 2, 0) / WINDOW;
			pts.push({ i, vol: Math.sqrt(variance) });
		}
		const maxVol = Math.max(...pts.map(p => p.vol), 0.01);
		const W = 340, H = 68, PAD = 10;
		const toX = (i: number) => PAD + ((i - (WINDOW - 1)) / (profits.length - WINDOW)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v / maxVol) * (H - PAD * 2);
		const polyline = pts.map(p => `${toX(p.i)},${toY(p.vol)}`).join(' ');
		return { pts, polyline, W, H, PAD, maxVol: maxVol.toFixed(2), lastVol: pts[pts.length - 1].vol.toFixed(2) };
	});

	const livePairCountVsProfit = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const botMap = new Map<string, { pairs: Set<string>; profits: number[] }>();
		for (const t of trades) {
			if (!t.bot_name || !t.pair || t.profit_ratio == null) continue;
			const entry = botMap.get(t.bot_name as string) ?? { pairs: new Set(), profits: [] };
			entry.pairs.add(t.pair as string);
			entry.profits.push((t.profit_ratio as number) * 100);
			botMap.set(t.bot_name as string, entry);
		}
		if (botMap.size < 3) return null;
		const pts = [...botMap.entries()].map(([, v]) => ({
			pairCount: v.pairs.size,
			avgProfit: v.profits.reduce((a, x) => a + x, 0) / v.profits.length
		}));
		const pcMax = Math.max(...pts.map(p => p.pairCount), 1);
		const profMin = Math.min(...pts.map(p => p.avgProfit));
		const profMax = Math.max(...pts.map(p => p.avgProfit), 0.01);
		const pRange = profMax - profMin || 0.01;
		const W = 320, H = 80, PAD = 10;
		const toX = (pc: number) => PAD + (pc / pcMax) * (W - PAD * 2);
		const toY = (p: number) => H - PAD - ((p - profMin) / pRange) * (H - PAD * 2);
		const zeroY = toY(0);
		return { pts, W, H, PAD, toX, toY, zeroY };
	});

	const liveProfitByExitType = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const map = new Map<string, number[]>();
		for (const t of trades) {
			if (!t.exit_reason || t.profit_ratio == null) continue;
			const reason = (t.exit_reason as string).slice(0, 14);
			const arr = map.get(reason) ?? [];
			arr.push((t.profit_ratio as number) * 100);
			map.set(reason, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([reason, vals]) => ({ reason, avg: vals.reduce((a, v) => a + v, 0) / vals.length, n: vals.length }))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 8);
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 340, H = rows.length * 20 + 6, PAD = 8, barMaxW = W - 100;
		const zeroX = PAD + barMaxW / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const liveMonthlyProfitCDF = $derived.by(() => {
		if (!trades || trades.length < 15) return null;
		const map = new Map<string, number[]>();
		for (const t of trades) {
			if (!t.close_date || t.profit_ratio == null) continue;
			const mo = (t.close_date as string).slice(0, 7);
			const arr = map.get(mo) ?? [];
			arr.push((t.profit_ratio as number) * 100);
			map.set(mo, arr);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const pts = months.map(m => { const arr = map.get(m)!; return { m: m.slice(5), sum: arr.reduce((a, v) => a + v, 0) }; });
		const minSum = Math.min(...pts.map(p => p.sum));
		const maxSum = Math.max(...pts.map(p => p.sum), 0.01);
		const range = maxSum - minSum || 0.01;
		const W = 340, H = 64, PAD = 8;
		const bw = (W - PAD * 2) / pts.length - 1;
		const midY = H / 2;
		return { pts, minSum, maxSum, range, W, H, PAD, bw, midY };
	});

	const liveTradeCountHistogram = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const vals = trades
			.filter(t => t.close_date && t.open_date)
			.map(t => {
				const open = new Date(t.open_date as string).getTime();
				const close = new Date(t.close_date as string).getTime();
				return (close - open) / 3600000;
			})
			.filter(h => h > 0 && h < 500);
		if (vals.length < 5) return null;
		const maxV = Math.min(Math.max(...vals), 200);
		const BINS = 12;
		const step = maxV / BINS;
		const counts = Array(BINS).fill(0);
		for (const v of vals) {
			const bi = Math.min(Math.floor(v / step), BINS - 1);
			counts[bi]++;
		}
		const maxCount = Math.max(...counts, 1);
		const W = 340, H = 60, PAD = 8;
		const bw = (W - PAD * 2) / BINS - 1;
		return { counts, maxCount, step, BINS, W, H, PAD, bw, maxV: maxV.toFixed(0) };
	});

	const liveAvgProfitByStakeBucket = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const map = new Map<string, number[]>();
		for (const t of trades) {
			const stake = t.stake_amount as number;
			if (stake == null || t.profit_ratio == null) continue;
			const bucket = stake < 50 ? '<50' : stake < 100 ? '50-100' : stake < 200 ? '100-200' : stake < 500 ? '200-500' : '500+';
			const arr = map.get(bucket) ?? [];
			arr.push((t.profit_ratio as number) * 100);
			map.set(bucket, arr);
		}
		if (map.size < 2) return null;
		const ORDER = ['<50', '50-100', '100-200', '200-500', '500+'];
		const rows = ORDER.filter(k => map.has(k)).map(k => {
			const arr = map.get(k)!;
			return { k, avg: arr.reduce((s, v) => s + v, 0) / arr.length };
		});
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 340, H = rows.length * 20 + 6, PAD = 8, barMaxW = W - 70;
		const zeroX = PAD + 55;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const liveBotWinRateRanking = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const map = new Map<string, { wins: number; total: number }>();
		for (const t of trades) {
			const bot = (t.bot_name as string | undefined) ?? (t.exchange as string | undefined) ?? 'default';
			const s = map.get(bot) ?? { wins: 0, total: 0 };
			s.total++;
			if ((t.profit_ratio as number) > 0) s.wins++;
			map.set(bot, s);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.filter(([, s]) => s.total >= 3)
			.map(([bot, s]) => ({ bot: bot.slice(0, 16), wr: s.wins / s.total * 100, total: s.total }))
			.sort((a, b) => b.wr - a.wr)
			.slice(0, 8);
		if (rows.length < 2) return null;
		const W = 340, H = rows.length * 18 + 10, PAD = 8, barMaxW = W - PAD * 2 - 80;
		return { rows, W, H, PAD, barMaxW };
	});

	const liveMonthlyAvgProfitPct = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const map = new Map<string, number[]>();
		for (const t of trades) {
			if (!t.close_date || t.profit_ratio == null) continue;
			const mo = (t.close_date as string).slice(0, 7);
			const arr = map.get(mo) ?? [];
			arr.push((t.profit_ratio as number) * 100);
			map.set(mo, arr);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort().slice(-12);
		const avgs = months.map(m => { const a = map.get(m)!; return a.reduce((s, v) => s + v, 0) / a.length; });
		const maxAbs = Math.max(...avgs.map(v => Math.abs(v)), 0.01);
		const W = 340, H = 64, PAD = 8, bw = (W - PAD * 2) / months.length - 1;
		const midY = H / 2;
		return { months, avgs, maxAbs, W, H, PAD, bw, midY };
	});

	const livePairWinRateCDF = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const byPair = new Map<string, { wins: number; total: number }>();
		for (const t of trades) {
			if (!t.pair || t.profit_ratio == null) continue;
			const s = byPair.get(t.pair as string) ?? { wins: 0, total: 0 };
			s.total++;
			if ((t.profit_ratio as number) > 0) s.wins++;
			byPair.set(t.pair as string, s);
		}
		const wrs = [...byPair.values()].filter(s => s.total >= 2).map(s => s.wins / s.total * 100).sort((a, b) => a - b);
		if (wrs.length < 5) return null;
		const minV = wrs[0], maxV = wrs[wrs.length - 1];
		if (maxV === minV) return null;
		const W = 320, H = 70, PAD = 10;
		const toX = (v: number) => PAD + ((v - minV) / (maxV - minV)) * (W - PAD * 2);
		const toY = (i: number) => H - PAD - (i / (wrs.length - 1)) * (H - PAD * 2);
		const polyline = wrs.map((v, i) => `${toX(v).toFixed(1)},${toY(i).toFixed(1)}`).join(' ');
		const zeroX = toX(50);
		const median = wrs[Math.floor(wrs.length / 2)].toFixed(1);
		return { polyline, zeroX, W, H, PAD, minV: minV.toFixed(1), maxV: maxV.toFixed(1), median };
	});

	const liveDurationByBot = $derived.by(() => {
		if (!trades || trades.length < 8) return null;
		const byBot = new Map<string, number[]>();
		for (const t of trades) {
			const bot = (t.bot_name ?? t.strategy ?? 'unknown') as string;
			if (t.trade_duration == null) continue;
			const arr = byBot.get(bot) ?? [];
			arr.push((t.trade_duration as number) / 60);
			byBot.set(bot, arr);
		}
		if (byBot.size < 2) return null;
		const rows = [...byBot.entries()]
			.map(([name, vals]) => ({ name: name.slice(0, 16), avg: vals.reduce((s, v) => s + v, 0) / vals.length }))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 8);
		const maxAvg = Math.max(...rows.map(r => r.avg), 1);
		const W = 320, H = rows.length * 18 + 10, PAD = 8, barMaxW = W - PAD * 2 - 80;
		return { rows, maxAvg, W, H, PAD, barMaxW };
	});

	const liveCalmarByBot = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const byBot = new Map<string, { profits: number[]; maxDD: number }>();
		for (const t of trades) {
			const bot = (t.bot_name ?? t.strategy ?? 'unknown') as string;
			if (t.profit_ratio == null) continue;
			const s = byBot.get(bot) ?? { profits: [], maxDD: 0 };
			const p = (t.profit_ratio as number) * 100;
			s.profits.push(p);
			if (p < -s.maxDD) s.maxDD = Math.abs(p);
			byBot.set(bot, s);
		}
		if (byBot.size < 2) return null;
		const rows = [...byBot.entries()]
			.filter(([, s]) => s.profits.length >= 5 && s.maxDD > 0)
			.map(([name, s]) => {
				const total = s.profits.reduce((a, v) => a + v, 0);
				return { name: name.slice(0, 16), calmar: total / s.maxDD };
			})
			.sort((a, b) => b.calmar - a.calmar)
			.slice(0, 8);
		if (rows.length < 2) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.calmar)), 0.01);
		const W = 320, H = rows.length * 18 + 10, PAD = 8, barMaxW = W - PAD * 2 - 80;
		const zeroX = PAD + 80 + barMaxW / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const liveProfitCDF = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const vals = trades.filter(t => t.profit_ratio != null).map(t => (t.profit_ratio as number) * 100).sort((a, b) => a - b);
		if (vals.length < 8) return null;
		const minV = vals[0], maxV = vals[vals.length - 1];
		if (maxV === minV) return null;
		const W = 320, H = 70, PAD = 10;
		const toX = (v: number) => PAD + ((v - minV) / (maxV - minV)) * (W - PAD * 2);
		const toY = (i: number) => H - PAD - (i / (vals.length - 1)) * (H - PAD * 2);
		const polyline = vals.map((v, i) => `${toX(v).toFixed(1)},${toY(i).toFixed(1)}`).join(' ');
		const zeroX = toX(0);
		const median = vals[Math.floor(vals.length / 2)].toFixed(2);
		return { polyline, zeroX, W, H, PAD, minV: minV.toFixed(2), maxV: maxV.toFixed(2), median };
	});

	const liveAvgProfitByPairGroup = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const map = new Map<string, number[]>();
		for (const t of trades) {
			if (!t.pair || t.profit_ratio == null) continue;
			const base = (t.pair as string).split('/')[0];
			const arr = map.get(base) ?? [];
			arr.push((t.profit_ratio as number) * 100);
			map.set(base, arr);
		}
		if (map.size < 3) return null;
		const rows = [...map.entries()]
			.filter(([, arr]) => arr.length >= 3)
			.map(([base, arr]) => ({ base, avg: arr.reduce((s, v) => s + v, 0) / arr.length, n: arr.length }))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 10);
		if (rows.length < 3) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 320, H = rows.length * 18 + 8, PAD = 8, barMaxW = W - PAD * 2 - 50;
		const zeroX = PAD + 40 + barMaxW / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const liveTradeHoldTimeDistribution = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const hrs = trades
			.filter(t => t.open_date && t.close_date)
			.map(t => (new Date(t.close_date as string).getTime() - new Date(t.open_date as string).getTime()) / 3600000)
			.filter(h => h > 0 && h < 500);
		if (hrs.length < 10) return null;
		const maxH = Math.max(...hrs);
		const bins = 10;
		const bw_val = maxH / bins;
		const counts = Array(bins).fill(0);
		for (const h of hrs) counts[Math.min(bins - 1, Math.floor(h / bw_val))]++;
		const maxCount = Math.max(...counts, 1);
		const W = 320, H = 70, PAD = 10;
		const bw = (W - PAD * 2) / bins - 1;
		return { counts, maxCount, bw, W, H, PAD, bw_val, bins };
	});

	const livePairSortinoRanking = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const map = new Map<string, number[]>();
		for (const t of trades) {
			if (!t.pair || t.profit_ratio == null) continue;
			const arr = map.get(t.pair as string) ?? [];
			arr.push((t.profit_ratio as number) * 100);
			map.set(t.pair as string, arr);
		}
		if (map.size < 3) return null;
		const rows = [...map.entries()]
			.filter(([, arr]) => arr.length >= 5)
			.map(([pair, arr]) => {
				const mean = arr.reduce((s, v) => s + v, 0) / arr.length;
				const negReturns = arr.filter(v => v < 0);
				const downDev = negReturns.length ? Math.sqrt(negReturns.reduce((s, v) => s + v * v, 0) / negReturns.length) : 0.001;
				return { pair: (pair as string).split('/')[0], sortino: mean / downDev };
			})
			.sort((a, b) => b.sortino - a.sortino)
			.slice(0, 8);
		if (rows.length < 3) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.sortino)), 0.01);
		const W = 320, H = rows.length * 20 + 8, PAD = 8, barMaxW = W - PAD * 2 - 50;
		const zeroX = PAD + 40 + barMaxW / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const liveMonthlyWinRateTrend = $derived.by(() => {
		if (!trades || trades.length < 10) return null;
		const byMonth = new Map<string, { wins: number; total: number }>();
		for (const t of trades) {
			if (!t.open_date || t.profit_ratio == null) continue;
			const mo = (t.open_date as string).slice(0, 7);
			const rec = byMonth.get(mo) ?? { wins: 0, total: 0 };
			rec.total++;
			if ((t.profit_ratio as number) > 0) rec.wins++;
			byMonth.set(mo, rec);
		}
		if (byMonth.size < 3) return null;
		const pts = [...byMonth.entries()]
			.sort(([a], [b]) => a.localeCompare(b))
			.filter(([, r]) => r.total >= 3)
			.map(([mo, r]) => ({ mo: mo.slice(5), wr: (r.wins / r.total) * 100 }));
		if (pts.length < 3) return null;
		const minV = Math.min(...pts.map(p => p.wr)), maxV = Math.max(...pts.map(p => p.wr), minV + 1);
		const W = 320, H = 70, PAD = 10;
		const toX = (i: number) => PAD + (i / Math.max(pts.length - 1, 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - minV) / (maxV - minV)) * (H - PAD * 2);
		const polyline = pts.map((p, i) => `${toX(i).toFixed(1)},${toY(p.wr).toFixed(1)}`).join(' ');
		return { pts, polyline, toX, W, H, PAD, minV: minV.toFixed(1), maxV: maxV.toFixed(1) };
	});

	const liveProfitFactorByDow = $derived.by(() => {
		if (!liveTrades || liveTrades.length < 10) return null;
		const byDow = new Map<number, { profit: number; count: number }>();
		const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		for (const t of liveTrades) {
			if (!t.open_date || t.profit_ratio == null) continue;
			const d = new Date(t.open_date as string).getUTCDay();
			const prev = byDow.get(d) ?? { profit: 0, count: 0 };
			prev.profit += (t.profit_ratio as number) * 100;
			prev.count++;
			byDow.set(d, prev);
		}
		const bars = [0, 1, 2, 3, 4, 5, 6]
			.filter(d => byDow.has(d) && (byDow.get(d)?.count ?? 0) >= 2)
			.map(d => ({ label: DOW[d], avg: (byDow.get(d)?.profit ?? 0) / (byDow.get(d)?.count ?? 1) }));
		if (bars.length < 3) return null;
		const maxAbs = Math.max(...bars.map(b => Math.abs(b.avg)), 0.01);
		const W = 320, H = 70, PAD = 8, midY = H / 2;
		const bw = Math.max(6, (W - PAD * 2) / bars.length - 2);
		return { bars, maxAbs, W, H, PAD, midY, bw };
	});

	const liveStakeAmountCDF = $derived.by(() => {
		if (!liveTrades || liveTrades.length < 10) return null;
		const vals = liveTrades
			.filter(t => t.stake_amount != null && (t.stake_amount as number) > 0)
			.map(t => t.stake_amount as number)
			.sort((a, b) => a - b);
		if (vals.length < 8) return null;
		const minV = vals[0], maxV = vals[vals.length - 1], rng = maxV - minV || 1;
		const W = 320, H = 70, PAD = 10;
		const toX = (v: number) => PAD + ((v - minV) / rng) * (W - PAD * 2);
		const toY = (i: number) => H - PAD - (i / Math.max(vals.length - 1, 1)) * (H - PAD * 2);
		const polyline = vals.map((v, i) => `${toX(v).toFixed(1)},${toY(i).toFixed(1)}`).join(' ');
		const median = vals[Math.floor(vals.length / 2)];
		return { vals, polyline, toX, toY, W, H, PAD, minV: minV.toFixed(1), maxV: maxV.toFixed(1), median: median.toFixed(1) };
	});

	const liveProfitBySide = $derived.by(() => {
		if (!liveTrades || liveTrades.length < 10) return null;
		const sides = new Map<string, { wins: number; total: number; sumProfit: number }>();
		for (const t of liveTrades) {
			const side = (t.trade_direction as string ?? 'long');
			const prev = sides.get(side) ?? { wins: 0, total: 0, sumProfit: 0 };
			prev.total++;
			prev.sumProfit += (t.profit_ratio as number ?? 0) * 100;
			if ((t.profit_ratio as number ?? 0) > 0) prev.wins++;
			sides.set(side, prev);
		}
		if (sides.size < 1) return null;
		const bars = [...sides.entries()].map(([side, v]) => ({
			side,
			avgProfit: v.sumProfit / v.total,
			wr: (v.wins / v.total) * 100,
			n: v.total
		}));
		const maxAbsProfit = Math.max(...bars.map(b => Math.abs(b.avgProfit)), 0.01);
		const W = 320, H = 70, PAD = 10, midY = H / 2;
		const bw = Math.max(24, (W - PAD * 2) / bars.length - 12);
		return { bars, maxAbsProfit, W, H, PAD, midY, bw };
	});

	const liveTradeCountByHour = $derived.by(() => {
		if (!liveTrades || liveTrades.length < 10) return null;
		const byHour = new Map<number, number>();
		for (const t of liveTrades) {
			if (!t.open_date) continue;
			const hr = new Date(t.open_date as string).getUTCHours();
			byHour.set(hr, (byHour.get(hr) ?? 0) + 1);
		}
		const counts = Array.from({ length: 24 }, (_, i) => byHour.get(i) ?? 0);
		const maxCnt = Math.max(...counts, 1);
		const W = 320, H = 65, PAD = 8;
		const bw = (W - PAD * 2) / 24 - 0.5;
		return { counts, maxCnt, W, H, PAD, bw };
	});

	const liveSortinoCDF = $derived.by(() => {
		if (!liveTrades || liveTrades.length < 15) return null;
		const byMonth = new Map<string, { profits: number[] }>();
		for (const t of liveTrades) {
			if (!t.open_date || t.profit_ratio == null) continue;
			const mo = (t.open_date as string).slice(0, 7);
			const prev = byMonth.get(mo) ?? { profits: [] };
			prev.profits.push((t.profit_ratio as number) * 100);
			byMonth.set(mo, prev);
		}
		if (byMonth.size < 3) return null;
		const sortinos = [...byMonth.values()].map(({ profits }) => {
			const avg = profits.reduce((s, v) => s + v, 0) / profits.length;
			const downside = profits.filter(v => v < 0);
			const dsd = downside.length > 1
				? Math.sqrt(downside.reduce((s, v) => s + v * v, 0) / downside.length)
				: 0.01;
			return avg / dsd;
		}).filter(v => Math.abs(v) < 50).sort((a, b) => a - b);
		if (sortinos.length < 3) return null;
		const minV = sortinos[0], maxV = sortinos[sortinos.length - 1], rng = maxV - minV || 1;
		const W = 320, H = 65, PAD = 10;
		const toX = (v: number) => PAD + ((v - minV) / rng) * (W - PAD * 2);
		const toY = (i: number) => H - PAD - (i / Math.max(sortinos.length - 1, 1)) * (H - PAD * 2);
		const polyline = sortinos.map((v, i) => `${toX(v).toFixed(1)},${toY(i).toFixed(1)}`).join(' ');
		const median = sortinos[Math.floor(sortinos.length / 2)];
		return { polyline, toX, W, H, PAD, minV: minV.toFixed(2), maxV: maxV.toFixed(2), median: median.toFixed(2) };
	});

	const liveWinRateCDF = $derived.by(() => {
		if (!liveTrades || liveTrades.length < 10) return null;
		const byPair = new Map<string, { wins: number; total: number }>();
		for (const t of liveTrades) {
			if (t.pair == null || t.profit_ratio == null) continue;
			const prev = byPair.get(t.pair as string) ?? { wins: 0, total: 0 };
			prev.total++;
			if ((t.profit_ratio as number) > 0) prev.wins++;
			byPair.set(t.pair as string, prev);
		}
		const wrs = [...byPair.values()]
			.filter(v => v.total >= 3)
			.map(v => (v.wins / v.total) * 100)
			.sort((a, b) => a - b);
		if (wrs.length < 6) return null;
		const minV = wrs[0], maxV = wrs[wrs.length - 1];
		const W = 320, H = 65, PAD = 8;
		const toX = (v: number) => PAD + ((v - minV) / (maxV - minV || 1)) * (W - PAD * 2);
		const toY = (i: number) => H - PAD - (i / (wrs.length - 1)) * (H - PAD * 2);
		const polyline = wrs.map((v, i) => `${toX(v)},${toY(i)}`).join(' ');
		const median = wrs[Math.floor(wrs.length / 2)];
		const x50 = toX(50);
		return { polyline, W, H, PAD, toX, x50, minV: minV.toFixed(0), maxV: maxV.toFixed(0), median: median.toFixed(0) };
	});

	const liveSharpeByBot = $derived.by(() => {
		if (!liveTrades || liveTrades.length < 10) return null;
		const byBot = new Map<string, number[]>();
		for (const t of liveTrades) {
			if (!t.bot_name || t.profit_ratio == null) continue;
			const arr = byBot.get(t.bot_name as string) ?? [];
			arr.push((t.profit_ratio as number) * 100);
			byBot.set(t.bot_name as string, arr);
		}
		const bars = [...byBot.entries()]
			.filter(([, arr]) => arr.length >= 5)
			.map(([bot, arr]) => {
				const mean = arr.reduce((s, v) => s + v, 0) / arr.length;
				const variance = arr.reduce((s, v) => s + (v - mean) ** 2, 0) / arr.length;
				const std = Math.sqrt(variance) || 0.01;
				return { bot: (bot as string).slice(0, 10), sharpe: mean / std };
			})
			.sort((a, b) => b.sharpe - a.sharpe)
			.slice(0, 8);
		if (bars.length < 2) return null;
		const maxAbs = Math.max(...bars.map(b => Math.abs(b.sharpe)), 0.01);
		const W = 320, H = 65, PAD = 8, midY = H / 2;
		const bw = Math.max(10, (W - PAD * 2) / bars.length - 3);
		return { bars, maxAbs, W, H, PAD, midY, bw };
	});

	const livePairProfitRanking = $derived.by(() => {
		if (!liveTrades || liveTrades.length < 10) return null;
		const byPair = new Map<string, { sum: number; count: number }>();
		for (const t of liveTrades) {
			if (t.pair == null || t.profit_ratio == null) continue;
			const base = (t.pair as string).split('/')[0];
			const prev = byPair.get(base) ?? { sum: 0, count: 0 };
			prev.sum += (t.profit_ratio as number) * 100;
			prev.count++;
			byPair.set(base, prev);
		}
		if (byPair.size < 3) return null;
		const bars = [...byPair.entries()]
			.filter(([, v]) => v.count >= 2)
			.map(([base, v]) => ({ base, avg: v.sum / v.count, n: v.count }))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 12);
		if (bars.length < 3) return null;
		const maxAbs = Math.max(...bars.map(b => Math.abs(b.avg)), 0.01);
		const W = 320, H = 70, PAD = 8, midY = H / 2;
		const bw = Math.max(5, (W - PAD * 2) / bars.length - 2);
		return { bars, maxAbs, W, H, PAD, midY, bw };
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

	{#if tradeStreak}
		<div class="mb-6 flex flex-wrap items-center gap-3 rounded-lg border bg-card px-5 py-3">
			<div class="flex items-center gap-2">
				<span class="text-xl leading-none">{tradeStreak.win ? '🔥' : '🧊'}</span>
				<div>
					<span class="text-sm font-semibold {tradeStreak.win ? 'text-green-400' : 'text-red-400'}">{tradeStreak.count}-trade {tradeStreak.win ? 'win' : 'loss'} streak</span>
					<span class="ml-2 text-xs text-muted-foreground">last close {tradeStreak.lastClose.slice(0, 10)}</span>
				</div>
			</div>
			<div class="ml-auto flex items-center gap-1.5" title="Last 5 trades">
				{#each tradeStreak.last5 as t}
					<span class="flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold {t.win ? 'bg-green-500/25 text-green-400' : 'bg-red-500/20 text-red-400'}"
						title="{t.win ? '+' : ''}{t.pct.toFixed(2)}%">
						{t.win ? 'W' : 'L'}
					</span>
				{/each}
				<span class="ml-1 text-[10px] text-muted-foreground">← recent</span>
			</div>
		</div>
	{/if}

	{#if botBreakdown && botBreakdown.length > 0}
		<section class="mt-4 rounded-lg border bg-card">
			<div class="border-b border-border px-4 py-3">
				<h2 class="text-sm font-semibold">Bot Performance <span class="ml-1 font-normal text-muted-foreground text-xs">({data.closedTrades.filter(t => t.close_date).length} closed trades)</span> <ChartInfo metric="botPnl" {lang} /></h2>
			</div>
			<div class="overflow-x-auto">
				<table class="w-full text-xs">
					<thead class="text-[10px] uppercase text-muted-foreground">
						<tr>
							<th class="px-4 py-2 text-left">Bot</th>
							<th class="px-4 py-2 text-right">Trades</th>
							<th class="px-4 py-2 text-right">Win%</th>
							<th class="px-4 py-2 text-right">Total USDT</th>
							<th class="px-4 py-2 text-left">Last Close</th>
						</tr>
					</thead>
					<tbody class="font-mono">
						{#each botBreakdown as b (b.bot)}
							<tr class="border-t border-border hover:bg-accent/30">
								<td class="px-4 py-2 font-semibold text-foreground">{b.bot}</td>
								<td class="px-4 py-2 text-right text-muted-foreground">{b.count}</td>
								<td class="px-4 py-2 text-right" class:text-green-400={b.wr >= 0.5} class:text-red-400={b.wr < 0.5}>{(b.wr * 100).toFixed(0)}%</td>
								<td class="px-4 py-2 text-right font-semibold" class:text-green-400={b.profit > 0} class:text-red-400={b.profit < 0}>{b.profit >= 0 ? '+' : ''}{b.profit.toFixed(2)}</td>
								<td class="px-4 py-2 text-muted-foreground">{fmtTime(b.lastDate)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	{/if}

	{#if dailyPnl}
		<section class="mt-4 rounded-lg border bg-card p-5">
			<div class="mb-3 flex items-baseline justify-between">
				<h2 class="text-sm font-semibold">Daily Closed P&L <span class="ml-1 font-normal text-muted-foreground text-xs">({data.closedTrades.filter(t => t.close_date).length} trades · last {dailyPnl.bars.length} days)</span> <ChartInfo metric="totalProfit" {lang} /></h2>
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
				<h2 class="text-sm font-semibold">Pair P&L Breakdown <span class="ml-1 font-normal text-muted-foreground text-xs">({pairPnl.rows.length} pairs · closed trades)</span> <ChartInfo metric="leaderboard" {lang} /></h2>
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

	{#if closedEquityCurve}
		{@const ec = closedEquityCurve}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<div class="mb-3 flex items-baseline justify-between">
				<h2 class="text-sm font-semibold">Closed Trade Equity Curve <span class="ml-1 font-normal text-muted-foreground text-xs">({ec.n} trades · cumulative P&amp;L)</span> <ChartInfo metric="equityCurve" {lang} /></h2>
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
				<h2 class="text-sm font-semibold">Monthly P&L Calendar <span class="ml-1 font-normal text-muted-foreground text-xs">({lm.winMonths}/{lm.total_months} green months)</span> <ChartInfo metric="calendar" {lang} /></h2>
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

	{#if openAging && openAging.length > 0}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Open Position Aging <span class="ml-1 font-normal text-muted-foreground text-xs">({openAging.length} positions · oldest first)</span> <ChartInfo metric="livePosition" {lang} /></h2>
			<div class="space-y-2">
				{#each openAging as row}
					<div class="flex items-center gap-2 text-xs">
						<span class="w-28 shrink-0 truncate font-mono text-foreground">{row.pair}</span>
						<div class="relative h-5 flex-1 overflow-hidden rounded bg-muted/30">
							<div
								class="absolute inset-y-0 left-0 rounded transition-all {row.upnlPct == null ? 'bg-primary/40' : row.upnlPct >= 0 ? 'bg-green-500/50' : 'bg-red-500/50'}"
								style="width:{row.barPct.toFixed(1)}%"
							></div>
							<span class="absolute inset-0 flex items-center px-2 font-mono text-foreground">
								{row.hours < 24 ? row.hours.toFixed(0) + 'h' : (row.hours / 24).toFixed(1) + 'd'}
							</span>
						</div>
						<span class="w-20 shrink-0 text-right font-mono {row.upnlPct == null ? 'text-muted-foreground' : row.upnlPct >= 0 ? 'text-green-400' : 'text-red-400'}">
							{row.upnlPct != null ? (row.upnlPct >= 0 ? '+' : '') + row.upnlPct.toFixed(2) + '%' : '—'}
						</span>
						<span class="w-20 shrink-0 text-right font-mono text-muted-foreground">
							{row.stake > 0 ? row.stake.toFixed(0) + ' USDT' : '—'}
						</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar length = relative age · color = uPnL direction (requires live prices loaded above)</p>
		</section>
	{/if}

	{#if openExposureMap}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Open Exposure Map <span class="ml-1 font-normal text-muted-foreground text-xs">({openExposureMap.length} positions · proportional stake)</span> <ChartInfo metric="livePosition" {lang} /></h2>
			<!-- Stacked bar showing each position's % of total open capital -->
			<div class="flex h-7 w-full overflow-hidden rounded-sm gap-px">
				{#each openExposureMap as row}
					<div
						class="flex items-center justify-center overflow-hidden text-[8px] font-mono text-white/80 rounded-sm"
						style="flex:{row.pct}; background:hsl({(openExposureMap.indexOf(row) * 47) % 360},45%,35%)"
						title="{row.pair}: {row.stake.toFixed(0)} USDT ({row.pct.toFixed(1)}%)"
					>
						{#if row.pct > 8}{row.pair.split('/')[0]}{/if}
					</div>
				{/each}
			</div>
			<div class="mt-2 space-y-1">
				{#each openExposureMap as row, i}
					<div class="flex items-center gap-2 text-[10px]">
						<span class="inline-block h-2 w-3 rounded-sm shrink-0"
							style="background:hsl({(i * 47) % 360},45%,35%)"></span>
						<span class="w-24 truncate font-mono">{row.pair}</span>
						<div class="flex-1 h-1.5 rounded-full bg-muted/20 overflow-hidden">
							<div class="h-full rounded-full" style="width:{row.pct.toFixed(1)}%; background:hsl({(i * 47) % 360},45%,35%)"></div>
						</div>
						<span class="w-20 text-right font-mono text-muted-foreground">{row.stake.toFixed(0)} USDT</span>
						<span class="w-10 text-right font-mono">{row.pct.toFixed(1)}%</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Width ∝ USDT allocated per position · total open = {openExposureMap.reduce((s, r) => s + r.stake, 0).toFixed(0)} USDT</p>
		</section>
	{/if}

	{#if liveDowPnl}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-4 text-sm font-semibold">Day-of-Week P&amp;L <span class="ml-1 font-normal text-muted-foreground text-xs">(cumulative profit by weekday · {data.closedTrades.length} closed trades)</span> <ChartInfo metric="totalProfit" {lang} /></h2>
			<div class="flex gap-2">
				{#each liveDowPnl as d}
					<div class="flex flex-1 flex-col items-center gap-1">
						<span class="font-mono text-[9px] text-muted-foreground">{d.count > 0 ? (d.sum >= 0 ? '+' : '') + d.sum.toFixed(0) : '—'}</span>
						<div class="relative w-full" style="height:64px">
							{#if d.count > 0}
								{@const h = Math.round(d.barPct * 0.56)}
								<div
									class="absolute bottom-0 left-0 right-0 rounded-t-sm"
									style="height:{h}px; background:{d.positive ? 'var(--ch-profit)' : 'var(--ch-loss)'}"
								></div>
							{/if}
						</div>
						<span class="font-mono text-[10px] font-semibold">{d.label}</span>
						{#if d.count > 0}
							<span class="font-mono text-[9px]" class:text-green-400={d.wr >= 0.5} class:text-red-400={d.wr < 0.5}>{(d.wr * 100).toFixed(0)}%</span>
						{/if}
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar height = relative P&amp;L magnitude · green = net positive · % = individual trade win rate</p>
		</section>
	{/if}

	{#if closeHourChart}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-4 text-sm font-semibold">Trade Close Hour (UTC) <span class="ml-1 font-normal text-muted-foreground text-xs">(when trades close · {data.closedTrades.length} trades)</span> <ChartInfo metric="totalProfit" {lang} /></h2>
			<div class="flex items-end gap-px">
				{#each closeHourChart as h}
					<div class="flex flex-1 flex-col items-center gap-0.5" title="Hour {h.h}:00 UTC: {h.count} trades · WR {(h.wr*100).toFixed(0)}%">
						<div class="w-full rounded-t-sm transition-colors"
							style="height:{Math.max(1, Math.round(h.barPct * 0.6))}px; background:{h.count === 0 ? 'var(--ch-axis-faint)' : h.positive ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'}"
						></div>
						{#if h.h % 6 === 0}
							<span class="font-mono text-[8px] text-muted-foreground">{h.h}h</span>
						{/if}
					</div>
				{/each}
			</div>
			<div class="mt-2 flex gap-4 text-[10px] text-muted-foreground">
				<span class="flex items-center gap-1"><span class="inline-block h-2 w-2 rounded-sm bg-green-500/55"></span>Net profit hour</span>
				<span class="flex items-center gap-1"><span class="inline-block h-2 w-2 rounded-sm bg-red-500/55"></span>Net loss hour</span>
				<span class="ml-auto font-mono">Asia: 0-8 · EU: 8-16 · US: 14-22</span>
			</div>
		</section>
	{/if}

	{#if durationHist}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-4 text-sm font-semibold">Trade Duration Distribution <span class="ml-1 font-normal text-muted-foreground text-xs">(how long trades were held · {data.closedTrades.length} closed)</span> <ChartInfo metric="distribution" {lang} /></h2>
			<div class="flex items-end gap-2">
				{#each durationHist as b}
					<div class="flex flex-1 flex-col items-center gap-1">
						<span class="font-mono text-[9px] text-muted-foreground">{b.count}</span>
						<div class="relative w-full" style="height:64px">
							<div class="absolute bottom-0 left-0 right-0 rounded-t-sm"
								style="height:{Math.max(2, Math.round(b.barPct * 0.6))}px; background:hsl({Math.round(b.wr * 120)},55%,38%)">
							</div>
						</div>
						<span class="font-mono text-[9px] font-semibold text-center leading-tight">{b.label}</span>
						<span class="font-mono text-[9px]"
							class:text-green-400={b.wr >= 0.5} class:text-red-400={b.wr < 0.5}
						>{(b.wr * 100).toFixed(0)}%</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar height = relative count · color = win rate (green=high, red=low) · % = WR per duration bucket</p>
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

	{#if stakeEfficiency}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Pair Stake Efficiency <span class="ml-1 font-normal text-muted-foreground text-xs">(profit / USDT deployed · ranked)</span> <ChartInfo metric="leaderboard" {lang} /></h2>
			<div class="space-y-1.5">
				{#each stakeEfficiency as r}
					<div class="flex items-center gap-2 text-xs">
						<span class="w-28 shrink-0 truncate font-mono text-muted-foreground" title={r.pair}>{r.pair}</span>
						<div class="relative flex-1 h-5 rounded-sm bg-muted/20 overflow-hidden">
							<div class="absolute inset-y-0 left-0 rounded-sm transition-all"
								style="width:{r.barPct.toFixed(1)}%; background:{r.efficiency >= 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'}"></div>
							<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">
								{r.efficiency >= 0 ? '+' : ''}{(r.efficiency * 100).toFixed(2)}%/USDT
							</span>
						</div>
						<span class="w-10 shrink-0 text-right font-mono text-[10px]">{r.count}×</span>
						<span class="w-12 shrink-0 text-right font-mono text-[10px]"
							class:text-green-400={r.wr >= 0.5} class:text-red-400={r.wr < 0.5}
						>WR {(r.wr * 100).toFixed(0)}%</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Efficiency = cumulative profit ÷ total USDT deployed · shows which pairs return the most per dollar risked</p>
		</section>
	{/if}

	{#if tradeProfitDist}
		{@const tpd = tradeProfitDist}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Trade Profit Distribution <span class="ml-1 font-normal text-muted-foreground text-xs">({tpd.total} trades · avg {tpd.avg >= 0 ? '+' : ''}{tpd.avg.toFixed(2)}%)</span> <ChartInfo metric="distribution" {lang} /></h2>
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

	{#if recentTradeTimeline}
		{@const rtl = recentTradeTimeline}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Recent Trade Timeline
				<span class="ml-1 font-normal text-muted-foreground text-xs">
					(last {rtl.total} trades · {rtl.wins}W / {rtl.total - rtl.wins}L
					· streak {rtl.streak > 0 ? '+' + rtl.streak + 'W' : rtl.streak + 'L'})
				</span> <ChartInfo metric="streak" {lang} /></h2>
			<div class="flex flex-wrap gap-1">
				{#each rtl.trades as t}
					<div class="relative group h-7 w-7 rounded-sm flex items-center justify-center text-[9px] font-mono shrink-0 cursor-default"
						style="background:{(t.profit_pct ?? 0) > 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'}">
						{(t.profit_pct ?? 0) > 0 ? '▲' : '▼'}
						<div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-10 bg-popover border border-border rounded px-2 py-1 text-[10px] whitespace-nowrap shadow-lg pointer-events-none">
							{t.pair} · {(t.profit_pct ?? 0) >= 0 ? '+' : ''}{((t.profit_pct ?? 0) * 100).toFixed(2)}%
							{#if t.close_date}<br/>{t.close_date.slice(0, 10)}{/if}
						</div>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Chronological sequence of last {rtl.total} closed trades · hover for pair and P&amp;L</p>
		</section>
	{/if}

	{#if openTradeHoldingMap}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Open Trade Holding Duration
				<span class="ml-1 font-normal text-muted-foreground text-xs">({openTradeHoldingMap.length} open · ranked oldest first)</span> <ChartInfo metric="livePosition" {lang} /></h2>
			<div class="space-y-1.5">
				{#each openTradeHoldingMap as r}
					<div class="flex items-center gap-2">
						<span class="w-28 shrink-0 truncate font-mono text-[10px] text-muted-foreground" title={r.pair}>{r.pair}</span>
						<div class="relative flex-1 h-5 rounded-sm bg-muted/20 overflow-hidden">
							<div class="absolute inset-y-0 left-0 rounded-sm"
								style="width:{r.barPct.toFixed(1)}%; background:{r.hours >= 72 ? 'var(--ch-loss-light)' : r.hours >= 24 ? 'var(--ch-warn-light)' : 'var(--ch-violet-light)'}"></div>
							<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">{r.label}</span>
						</div>
						<span class="w-14 shrink-0 text-right font-mono text-[10px]"
							class:text-green-400={r.profitPct != null && r.profitPct > 0}
							class:text-red-400={r.profitPct != null && r.profitPct < 0}
							class:text-muted-foreground={r.profitPct == null}>
							{r.profitPct != null ? (r.profitPct >= 0 ? '+' : '') + (r.profitPct * 100).toFixed(2) + '%' : '—'}
						</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Purple &lt;24h · yellow 24–72h · red &gt;72h · longer bars = older positions</p>
		</section>
	{/if}

	{#if streakDistribution}
		{@const sd = streakDistribution}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Win/Loss Streak Distribution
				<span class="ml-1 font-normal text-muted-foreground text-xs">
					(avg win streak {sd.avgWin.toFixed(1)} · avg loss streak {sd.avgLoss.toFixed(1)})
				</span> <ChartInfo metric="streak" {lang} /></h2>
			<div class="flex items-end gap-2">
				{#each sd.buckets as b}
					<div class="flex flex-1 flex-col items-center gap-1">
						<div class="flex w-full flex-col gap-0.5">
							<div class="w-full rounded-t-sm" style="height:{Math.max(2, (b.wins / sd.maxCount) * 56)}px; background:var(--ch-profit)"></div>
							<div class="w-full rounded-b-sm" style="height:{Math.max(2, (b.losses / sd.maxCount) * 56)}px; background:var(--ch-loss-light)"></div>
						</div>
						<span class="font-mono text-[10px] text-muted-foreground">{b.len}×</span>
					</div>
				{/each}
			</div>
			<div class="mt-2 flex gap-4 text-[10px] text-muted-foreground">
				<span class="flex items-center gap-1"><span class="inline-block h-2 w-3 rounded-sm bg-green-500/60"></span> Win streak</span>
				<span class="flex items-center gap-1"><span class="inline-block h-2 w-3 rounded-sm bg-red-500/50"></span> Loss streak</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">x = streak length · bar height = frequency · tall green at 1× = mostly isolated wins</p>
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

	{#if botProfitRanking}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Profit by Bot
				<span class="ml-1 font-normal text-muted-foreground text-xs">({botProfitRanking.reduce((s,r)=>s+r.count,0)} closed trades across {botProfitRanking.length} bots)</span> <ChartInfo metric="totalProfit" {lang} /></h2>
			<div class="space-y-2">
				{#each botProfitRanking as r}
					<div class="flex items-center gap-2">
						<span class="w-32 shrink-0 truncate font-mono text-[10px]" title={r.bot}>{r.bot}</span>
						<div class="relative flex-1 h-5 rounded-sm bg-muted/20 overflow-hidden">
							<div class="absolute inset-y-0 left-0 rounded-sm"
								style="width:{r.barPct.toFixed(1)}%; background:{r.totalAbs >= 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'}"></div>
							<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">
								{r.totalAbs >= 0 ? '+' : ''}{r.totalAbs.toFixed(1)} USDT
							</span>
						</div>
						<span class="w-24 shrink-0 text-right font-mono text-[10px] text-muted-foreground">
							WR {(r.wr * 100).toFixed(0)}% · {r.count}×
						</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar width ∝ absolute P&L · green = profitable · right = win rate and trade count</p>
		</section>
	{/if}

	{#if pairProfitMatrix}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Pair Profit Matrix
				<span class="ml-1 font-normal text-muted-foreground text-xs">(top {pairProfitMatrix.length} pairs by total P&L · {data.closedTrades.length} closed trades)</span> <ChartInfo metric="leaderboard" {lang} /></h2>
			<div class="space-y-1.5">
				{#each pairProfitMatrix as r}
					<div class="flex items-center gap-2">
						<span class="w-24 shrink-0 font-mono text-[10px] truncate">{r.pair.replace('/USDT:USDT','').replace('/USDT','')}</span>
						<div class="relative flex-1 h-5 rounded-sm bg-muted/20 overflow-hidden">
							<div class="absolute inset-y-0 left-0 rounded-sm"
								style="width:{(r.wr * 100).toFixed(1)}%; background:{r.wr >= 0.6 ? 'var(--ch-profit-light)' : r.wr >= 0.45 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)'}"></div>
							<span class="absolute inset-y-0 left-2 flex items-center font-mono text-[10px]">
								{(r.wr * 100).toFixed(0)}% WR
							</span>
						</div>
						<span class="w-14 shrink-0 text-right font-mono text-[10px]"
							class:text-green-400={r.totalProfitAbs > 0}
							class:text-red-400={r.totalProfitAbs < 0}>
							{r.totalProfitAbs >= 0 ? '+' : ''}{r.totalProfitAbs.toFixed(1)}
						</span>
						<span class="w-10 shrink-0 text-right font-mono text-[10px] text-muted-foreground">{r.count}×</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar = win rate · right = total USDT profit · green ≥60% WR · yellow 45-60% · red &lt;45%</p>
		</section>
	{/if}

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

	{#if profitPercentiles}
		<section class="mt-6 rounded-lg border bg-card p-5">
			<h2 class="mb-3 text-sm font-semibold">Trade Profit Percentiles
				<span class="ml-1 font-normal text-muted-foreground text-xs">({data.closedTrades.filter(t => t.profit_pct != null).length} closed trades)</span> <ChartInfo metric="totalProfit" {lang} /></h2>
			<div class="space-y-1.5">
				{#each profitPercentiles as p}
					<div class="flex items-center gap-3">
						<span class="w-8 shrink-0 font-mono text-[10px] font-semibold text-muted-foreground">{p.label}</span>
						<div class="relative flex-1 h-4 rounded-sm bg-muted/20 overflow-hidden">
							<div class="absolute inset-y-0 rounded-sm transition-all"
								style="width:{p.barPct.toFixed(1)}%; background:{p.v >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss-light)'}; {p.v < 0 ? 'right:0' : 'left:0'}"></div>
						</div>
						<span class="w-16 shrink-0 text-right font-mono text-[11px] font-semibold"
							class:text-green-400={p.v >= 0} class:text-red-400={p.v < 0}>
							{p.v >= 0 ? '+' : ''}{p.v.toFixed(2)}%
						</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">P50 = median trade · P5/P95 = tail outcomes · positive P25+ means majority of trades are profitable</p>
		</section>
	{/if}

	{#if weeklyWinRateTrend}
		<section class="mt-4 rounded-lg border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">Weekly Win Rate (last 12 weeks)
				<span class="ml-1 font-normal text-muted-foreground text-xs">(% of trades closing in-profit per calendar week)</span> <ChartInfo metric="winRate" {lang} /></h2>
			<div class="flex items-end gap-1" style="height:72px">
				{#each weeklyWinRateTrend as w}
					{@const wr = w.wr ?? 0}
					{@const color = wr >= 0.6 ? 'var(--ch-profit)' : wr >= 0.5 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
					<div class="flex flex-1 flex-col items-center justify-end gap-0.5"
						title="Week of {w.key}: {w.wins}/{w.total} trades · {(wr * 100).toFixed(0)}% win rate">
						{#if w.total > 0}
							<span class="font-mono text-[8px] text-muted-foreground">{(wr * 100).toFixed(0)}%</span>
							<div class="w-full min-h-[2px] rounded-t-sm" style="height:{Math.max(2, wr * 56)}px; background:{color}"></div>
						{:else}
							<div class="w-full" style="height:1px; background:var(--ch-rule-faint)"></div>
						{/if}
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				{#each weeklyWinRateTrend as w, i}
					{#if i === 0 || i === Math.floor(weeklyWinRateTrend.length / 2) || i === weeklyWinRateTrend.length - 1}
						<span>{w.label}</span>
					{/if}
				{/each}
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Green ≥60% · yellow 50–60% · red &lt;50% · bar height = win rate</p>
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

	{#if openTradeAgeDistribution}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Open Trade Age Distribution
				<span class="ml-1 font-normal text-muted-foreground text-xs">(how long current positions have been open)</span> <ChartInfo metric="distribution" {lang} /></h2>
			<div class="mt-3 flex items-end gap-1" style="height:72px">
				{#each openTradeAgeDistribution as b}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<span class="font-mono text-[8px] text-muted-foreground">{b.count > 0 ? b.count : ''}</span>
						<div class="w-full rounded-t" style="height:{Math.max(2, b.barPct * 0.6)}px; background:{b.maxH <= 4 ? 'var(--ch-profit-light)' : b.maxH <= 24 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)'}"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				{#each openTradeAgeDistribution as b}
					<span class="flex-1 text-center">{b.label}</span>
				{/each}
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Green = fresh &lt;4h · yellow = same-day · red = multi-day positions — old open trades may indicate stuck positions</p>
		</section>
	{/if}

	{#if openPairUnrealizedPnl}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Open Positions — Unrealized P&amp;L by Pair
				<span class="ml-1 font-normal text-muted-foreground text-xs">(avg current profit% per open pair)</span> <ChartInfo metric="leaderboard" {lang} /></h2>
			<div class="mt-3 space-y-1.5">
				{#each openPairUnrealizedPnl as r}
					<div class="flex items-center gap-2">
						<span class="w-28 truncate font-mono text-[10px]" title={r.pair}>{r.pair}</span>
						<div class="relative flex-1" style="height:14px">
							<div class="absolute rounded" style="height:100%; width:{r.barPct}%; background:{r.avg >= 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'}"></div>
						</div>
						<span class="w-16 text-right font-mono text-[10px]" style="color:{r.avg >= 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss-strong)'}">
							{r.avg >= 0 ? '+' : ''}{r.avg.toFixed(2)}%
						</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Current unrealized P&amp;L per pair · green = in profit · red = underwater · updates on page reload</p>
		</section>
	{/if}

	{#if tradeDoWHourHeatmap}
		{@const hm = tradeDoWHourHeatmap}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Profit Heatmap: Day × Hour
				<span class="ml-1 font-normal text-muted-foreground text-xs">(avg closed trade profit% by UTC day-of-week and hour)</span> <ChartInfo metric="distribution" {lang} /></h2>
			<div class="mt-3 overflow-x-auto">
				<div class="grid gap-px" style="grid-template-columns: 2rem repeat(24, minmax(0, 1fr))">
					{#each hm.DAYS as day, di}
						<span class="flex items-center justify-center font-mono text-[9px] text-muted-foreground">{day}</span>
						{#each hm.cells[di] as cell}
							{@const avg = cell.count > 0 ? cell.sum / cell.count : null}
							<div class="h-4 rounded-sm" style="background:{avg == null ? 'var(--ch-rule-faint)' : avg > 0 ? `rgba(34,197,94,${Math.min(0.8, 0.1 + (avg / hm.maxAbs) * 0.7)})` : `rgba(239,68,68,${Math.min(0.8, 0.1 + (Math.abs(avg) / hm.maxAbs) * 0.7)})`}" title={avg != null ? `${avg >= 0 ? '+' : ''}${avg.toFixed(2)}% (${cell.count})` : 'no trades'}></div>
						{/each}
					{/each}
				</div>
				<div class="mt-1 grid gap-px" style="grid-template-columns: 2rem repeat(24, minmax(0, 1fr))">
					<span></span>
					{#each Array.from({length: 24}, (_, i) => i) as h}
						<span class="text-center font-mono text-[7px] text-muted-foreground">{h % 6 === 0 ? h : ''}</span>
					{/each}
				</div>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Green = profitable hours · red = lossy · intensity ∝ magnitude · empty = no trades that slot</p>
		</section>
	{/if}

	{#if botWinRateComparison}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Win Rate by Bot
				<span class="ml-1 font-normal text-muted-foreground text-xs">(% profitable closed trades per bot · ranked highest to lowest)</span> <ChartInfo metric="winRate" {lang} /></h2>
			<div class="mt-3 space-y-2">
				{#each botWinRateComparison as r}
					<div class="flex items-center gap-2">
						<span class="w-32 truncate font-mono text-[10px]" title={r.bot}>{r.bot}</span>
						<div class="relative flex-1" style="height:14px">
							<div class="absolute rounded" style="height:100%; width:{r.barPct}%; background:{r.wr >= 0.5 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'}"></div>
						</div>
						<span class="w-12 text-right font-mono text-[10px]" style="color:{r.wr >= 0.5 ? 'rgb(74,222,128)' : 'rgb(248,113,113)'}">{(r.wr * 100).toFixed(1)}%</span>
						<span class="w-16 text-right font-mono text-[9px] text-muted-foreground">{r.total} trades</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Win rate = profitable closed trades / total closed trades per bot · above 50% = more wins than losses</p>
		</section>
	{/if}

	{#if strategyTradeVolume}
		<section class="mt-8 rounded-lg border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Trade Volume by Strategy
				<span class="ml-1 font-normal text-muted-foreground text-xs">(closed trade count per strategy across all bots · ranked by activity)</span> <ChartInfo metric="tradeCount" {lang} /></h2>
			<div class="mt-3 space-y-1.5">
				{#each strategyTradeVolume as r}
					<div class="flex items-center gap-2">
						<span class="w-44 truncate text-xs" title={r.strategy}>{r.strategy}</span>
						<div class="relative flex-1" style="height:14px">
							<div class="absolute rounded" style="height:100%; width:{r.barPct.toFixed(1)}%; background:var(--ch-violet-light)"></div>
						</div>
						<span class="w-14 text-right font-mono text-[10px] text-muted-foreground">{r.count} trades</span>
						<span class="w-12 text-right font-mono text-[10px]" style="color:{r.wr >= 0.5 ? 'rgb(74,222,128)' : 'rgb(248,113,113)'}">{(r.wr * 100).toFixed(0)}%wr</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar = trade count · wr = win rate · reveals which strategy generates the most live trade activity</p>
		</section>
	{/if}

	{#if pairProfitLeaderboard}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Pair Profit Leaderboard <ChartInfo metric="leaderboard" {lang} /></h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Top 10 pairs by cumulative closed profit (USDT) across all bots</p>
			<div class="mt-3 space-y-1.5">
				{#each pairProfitLeaderboard as r}
					<div class="flex items-center gap-2">
						<span class="w-24 truncate font-mono text-[10px] text-muted-foreground">{r.pair}</span>
						<div class="flex-1 overflow-hidden rounded-sm" style="height:14px; background:var(--ch-rule-faint)">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{r.sum >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}"></div>
						</div>
						<span class="w-16 text-right font-mono text-[10px]" style="color:{r.sum >= 0 ? 'var(--ch-profit-solid)' : 'var(--ch-loss-solid)'}">{r.sum >= 0 ? '+' : ''}{r.sum.toFixed(1)}U</span>
						<span class="w-16 text-right font-mono text-[9px] text-muted-foreground">WR {(r.wr * 100).toFixed(0)}% n={r.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Sorted by total USDT gained · reveals which pairs contribute most to live portfolio returns</p>
		</section>
	{/if}

	{#if botCumulativePnlTimeline}
		{@const bcpt = botCumulativePnlTimeline}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Bot Cumulative PnL <ChartInfo metric="botPnl" {lang} /></h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Cumulative closed profit (USDT) over time per bot</p>
			<svg viewBox="0 0 {bcpt.W} {bcpt.H}" class="mt-2 w-full" style="height:60px">
				{#each bcpt.polylines as l}
					<polyline points={l.poly} fill="none" stroke={l.color} stroke-width="1.5"/>
				{/each}
			</svg>
			<div class="mt-2 flex flex-wrap gap-x-4 gap-y-1">
				{#each bcpt.polylines as l}
					<span class="flex items-center gap-1 font-mono text-[10px]">
						<span class="inline-block h-2 w-3 rounded-sm" style="background:{l.color}"></span>
						{l.bot.slice(0, 12)} {l.final >= 0 ? '+' : ''}{l.final.toFixed(1)}U
					</span>
				{/each}
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Rising line = net profitable bot · steeper slope = faster capital accumulation · diverging lines reveal performance gaps between bots</p>
		</section>
	{/if}

	{#if openTradeUnrealizedByBot}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Open Trade Unrealized PnL by Bot <ChartInfo metric="livePosition" {lang} /></h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Sum of unrealized profit% across all currently open trades per bot</p>
			<div class="mt-3 space-y-1.5">
				{#each openTradeUnrealizedByBot as r}
					<div class="flex items-center gap-2">
						<span class="w-28 truncate font-mono text-[10px] text-muted-foreground">{r.bot}</span>
						<div class="flex-1 overflow-hidden rounded-sm" style="height:14px; background:var(--ch-rule-faint)">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{r.sum >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}"></div>
						</div>
						<span class="w-14 text-right font-mono text-[10px]" style="color:{r.sum >= 0 ? 'var(--ch-profit-solid)' : 'var(--ch-loss-solid)'}">{r.sum >= 0 ? '+' : ''}{r.sum.toFixed(1)}%</span>
						<span class="w-14 text-right font-mono text-[9px] text-muted-foreground">avg {r.avg >= 0 ? '+' : ''}{r.avg.toFixed(1)}% ×{r.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Snapshot of live exposure · green = currently winning · red = currently underwater · updates each page load</p>
		</section>
	{/if}

	{#if closedTradeExitReasonBreakdown}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Exit Reason Breakdown <ChartInfo metric="exitReason" {lang} /></h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Count and avg profit% per exit reason across all closed trades</p>
			<div class="mt-3 space-y-1.5">
				{#each closedTradeExitReasonBreakdown as r}
					<div class="flex items-center gap-2">
						<span class="w-28 truncate font-mono text-[10px] text-muted-foreground">{r.reason}</span>
						<div class="flex-1 overflow-hidden rounded-sm" style="height:14px; background:var(--ch-rule-faint)">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:var(--ch-violet)"></div>
						</div>
						<span class="w-8 text-right font-mono text-[10px] text-muted-foreground">{r.count}</span>
						<span class="w-12 text-right font-mono text-[10px]" style="color:{r.avg >= 0 ? 'var(--ch-profit-solid)' : 'var(--ch-loss-solid)'}">{r.avg >= 0 ? '+' : ''}{r.avg.toFixed(2)}%</span>
						<span class="w-10 text-right font-mono text-[9px] text-muted-foreground">WR {(r.wr * 100).toFixed(0)}%</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Bar width = trade frequency · avg% and WR show quality per exit type · stoploss-heavy = strategy struggling</p>
		</section>
	{/if}

	{#if tradeDurationVsProfit}
		{@const tdvp = tradeDurationVsProfit}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Trade Duration vs Profit Scatter <ChartInfo metric="scatter" {lang} /></h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Each dot = one closed trade · X = holding time (min) · Y = profit% · reveals if longer holds outperform</p>
			<svg viewBox="0 0 {tdvp.W} {tdvp.H}" class="mt-2 w-full" style="height:80px">
				<line x1={tdvp.PAD} y1={tdvp.H - tdvp.PAD - ((0 - tdvp.minP) / (tdvp.maxP - tdvp.minP || 1)) * (tdvp.H - tdvp.PAD * 2)} x2={tdvp.W - tdvp.PAD} y2={tdvp.H - tdvp.PAD - ((0 - tdvp.minP) / (tdvp.maxP - tdvp.minP || 1)) * (tdvp.H - tdvp.PAD * 2)} stroke="var(--ch-rule)" stroke-width="0.5"/>
				{#each tdvp.mapped as p}
					<circle cx={p.cx} cy={p.cy} r="2" fill={p.pos ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'}/>
				{/each}
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>0 min</span><span>→ holding duration →</span><span>{(tdvp.maxD / 60).toFixed(0)}h</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Green = profitable · red = loss · cluster above zero-line = positive expectancy · no clear trend = holding time is not a key profit driver</p>
		</section>
	{/if}

	{#if strategyProfitLeaderboard}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Strategy Live Profit Leaderboard <ChartInfo metric="leaderboard" {lang} /></h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Top 10 strategies by avg profit% per closed trade (min 3 trades) — live performance ranking</p>
			<div class="mt-3 space-y-1.5">
				{#each strategyProfitLeaderboard as r, i}
					<div class="flex items-center gap-2">
						<span class="w-5 text-right font-mono text-[10px] text-muted-foreground">{i + 1}</span>
						<span class="w-32 truncate font-mono text-[10px] text-muted-foreground">{r.strategy}</span>
						<div class="flex-1 overflow-hidden rounded-sm" style="height:14px; background:var(--ch-rule-faint)">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{r.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss-light)'}"></div>
						</div>
						<span class="w-14 text-right font-mono text-[10px]" style="color:{r.avg >= 0 ? 'var(--ch-profit-solid)' : 'var(--ch-loss-solid)'}">{r.avg >= 0 ? '+' : ''}{r.avg.toFixed(2)}%</span>
						<span class="w-10 text-right font-mono text-[9px] text-muted-foreground">WR {(r.wr * 100).toFixed(0)}%</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Avg profit% per trade in live/dry-run · strategies near top consistently generate positive expectancy in real market conditions</p>
		</section>
	{/if}

	{#if closedTradeProfitByMonth}
		<section class="mt-8 rounded-xl border border-border bg-card p-5">
			<h2 class="text-base font-semibold">Monthly Avg Trade Profit <ChartInfo metric="avgProfit" {lang} /></h2>
			<p class="mt-0.5 text-xs text-muted-foreground">Average profit% per closed trade grouped by calendar month — reveals seasonal or regime-driven performance patterns</p>
			<div class="mt-3 flex items-end gap-1" style="height:72px">
				{#each closedTradeProfitByMonth as r}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<span class="font-mono text-[7px]" style="color:{r.avg >= 0 ? 'var(--ch-profit-solid)' : 'var(--ch-loss-solid)'}">
							{r.avg >= 0 ? '+' : ''}{r.avg.toFixed(1)}
						</span>
						<div class="w-full rounded-sm" style="height:{r.barPct}%; background:{r.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss-light)'}; min-height:2px"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>{closedTradeProfitByMonth[0].ym}</span><span>→ month →</span><span>{closedTradeProfitByMonth[closedTradeProfitByMonth.length - 1].ym}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Consistent green = reliable across all market conditions · red months = regime where strategies underperformed · n={closedTradeProfitByMonth.reduce((s, r) => s + r.count, 0)} trades</p>
		</section>
	{/if}

	{#if closedTradePairFrequency}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Closed Trade Pair Frequency <ChartInfo metric="leaderboard" {lang} /></h2>
			<p class="mb-3 text-[11px] text-muted-foreground">Top pairs by number of closed trades, with avg profit and win rate</p>
			<div class="space-y-1">
				{#each closedTradePairFrequency as r}
					<div class="flex items-center gap-2">
						<span class="w-24 truncate text-right font-mono text-[11px] text-muted-foreground">{r.pair.replace('/USDT:USDT', '').replace('/USDT', '')}</span>
						<div class="h-4 flex-1 overflow-hidden rounded-sm bg-muted">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{r.avgProfit >= 0 ? 'var(--ch-violet)' : 'var(--ch-loss)'}"></div>
						</div>
						<span class="w-8 text-right font-mono text-[10px] text-muted-foreground">{r.count}x</span>
						<span class="w-14 text-right font-mono text-[10px]" style="color:{r.avgProfit >= 0 ? 'var(--ch-profit-solid)' : 'var(--ch-loss-solid)'}">{r.avgProfit > 0 ? '+' : ''}{r.avgProfit.toFixed(2)}%</span>
						<span class="w-10 text-right font-mono text-[9px] text-muted-foreground">WR {(r.winRate * 100).toFixed(0)}%</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Pairs traded frequently with positive avg profit = reliable edges · frequent with negative avg = position sizing candidate for reduction</p>
		</section>
	{/if}

	{#if closedTradeDurationDistribution}
		{@const ctdd = closedTradeDurationDistribution}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Trade Duration Distribution <ChartInfo metric="distribution" {lang} /></h2>
			<p class="mb-3 text-[11px] text-muted-foreground">Histogram of closed trade durations · median {(ctdd.median / 60).toFixed(1)}h · n={ctdd.total}</p>
			<div class="flex items-end gap-1" style="height:64px">
				{#each ctdd.buckets as b}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<span class="font-mono text-[7px] text-muted-foreground">{b.count > 0 ? b.count : ''}</span>
						<div class="w-full rounded-sm" style="height:{b.barPct}%; background:{b.avgProfit >= 0 ? 'var(--ch-violet)' : 'var(--ch-loss)'}; min-height:{b.count > 0 ? 2 : 0}px"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>{ctdd.buckets[0].label}</span><span>← duration →</span><span>{ctdd.buckets[ctdd.buckets.length - 1].label}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Purple = profitable bucket · red = losing duration range · very short trades = noise · very long = trapped positions</p>
		</section>
	{/if}

	{#if closedTradeStrategyWinRate}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Strategy Win Rate (Live Trades) <ChartInfo metric="winRate" {lang} /></h2>
			<p class="mb-3 text-[11px] text-muted-foreground">Win rate per strategy across closed live trades (≥3 trades) sorted by win rate</p>
			<div class="space-y-1">
				{#each closedTradeStrategyWinRate as r}
					<div class="flex items-center gap-2">
						<span class="w-32 truncate text-right font-mono text-[10px] text-muted-foreground">{r.strategy}</span>
						<div class="h-4 flex-1 overflow-hidden rounded-sm bg-muted">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{r.wr >= 0.5 ? 'var(--ch-profit)' : 'var(--ch-loss)'}"></div>
						</div>
						<span class="w-12 text-right font-mono text-[10px]" style="color:{r.wr >= 0.5 ? 'var(--ch-profit-solid)' : 'var(--ch-loss-solid)'}">{(r.wr * 100).toFixed(0)}% WR</span>
						<span class="w-14 text-right font-mono text-[10px]" style="color:{r.avgProfit >= 0 ? 'var(--ch-violet-strong)' : 'var(--ch-loss-strong)'}">{r.avgProfit > 0 ? '+' : ''}{r.avgProfit.toFixed(2)}%</span>
						<span class="w-8 text-right font-mono text-[9px] text-muted-foreground">n={r.total}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">High WR + positive avg profit = most reliable live strategies · low WR + positive avg profit = profitable via large wins</p>
		</section>
	{/if}

	{#if closedTradeBotProfitByMonth}
		{@const cbm = closedTradeBotProfitByMonth}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Per-Bot Monthly PnL Comparison <ChartInfo metric="botPnl" {lang} /></h2>
			<p class="mb-2 text-[11px] text-muted-foreground">Sum of profit% per bot per month (last 12 months) · green = profitable · red = losing</p>
			<svg viewBox="0 0 {cbm.W} {cbm.H}" class="w-full" style="height:80px">
				<line x1="0" y1={cbm.midY} x2={cbm.W} y2={cbm.midY} stroke="var(--ch-axis-muted)" stroke-width="0.5"/>
				{#each cbm.bars as bar}
					{#each bar.bots as b}
						<rect x={b.x} y={b.y} width={Math.max(1, cbm.W * 0.8 / cbm.months.length / cbm.bots.length)} height={Math.max(1, b.h)} fill={b.color} rx="0.5"/>
					{/each}
				{/each}
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>{cbm.months[0]}</span><span>← monthly bot PnL →</span><span>{cbm.months[cbm.months.length - 1]}</span>
			</div>
			<div class="mt-2 flex flex-wrap gap-3">
				{#each cbm.bots as b}
					<span class="flex items-center gap-1 text-[9px]">
						<span class="inline-block h-2 w-2 rounded-sm" style="background:{cbm.botColors[b]}"></span>
						{b}
					</span>
				{/each}
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Bars above baseline = month profitable for that bot · compare bot heights per month to spot which bots drive gains or losses</p>
		</section>
	{/if}

	{#if closedTradePairDowHeatmap}
		{@const cpdh = closedTradePairDowHeatmap}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Pair Win Rate by Day of Week <ChartInfo metric="winRate" {lang} /></h2>
			<p class="mb-2 text-[11px] text-muted-foreground">Win rate per pair × weekday across closed live trades (≥2 trades per cell)</p>
			<div class="overflow-x-auto">
				<table class="w-full text-[9px]">
					<thead>
						<tr>
							<th class="pr-2 text-right font-mono text-muted-foreground">Pair</th>
							{#each cpdh.days as d}
								<th class="px-1 text-center font-mono text-muted-foreground">{d}</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each cpdh.cells as row}
							<tr class="border-t border-border/30">
								<td class="py-0.5 pr-2 text-right font-mono text-muted-foreground">{row.pair}</td>
								{#each row.days as cell}
									<td class="px-1 py-0.5 text-center font-mono" title="{cell.label}: {cell.wr != null ? (cell.wr * 100).toFixed(0) + '% (' + cell.total + ' trades)' : 'no data'}">
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
			<p class="mt-2 text-[10px] text-muted-foreground">Green ≥60% · yellow 40–60% · red &lt;40% · avoid trading a pair on its red weekdays · green cell = historically reliable entry day for that pair</p>
		</section>
	{/if}

	{#if closedTradeMonthlyWinRate}
		{@const cmwr = closedTradeMonthlyWinRate}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h2 class="text-sm font-semibold">Monthly Win Rate Trend <ChartInfo metric="winRate" {lang} /></h2>
			<p class="mb-2 text-[11px] text-muted-foreground">Win rate per calendar month across all closed live trades · avg {(cmwr.avgWr * 100).toFixed(1)}% · {cmwr.rows.length} months</p>
			<svg viewBox="0 0 {cmwr.W} {cmwr.H}" class="w-full" style="height:62px">
				<line x1={cmwr.PAD} y1={cmwr.y50} x2={cmwr.W - cmwr.PAD} y2={cmwr.y50} stroke="var(--ch-axis-faint)" stroke-width="0.6" stroke-dasharray="3,2"/>
				<polyline points={cmwr.poly} fill="none" stroke="var(--ch-violet-strong)" stroke-width="1.5"/>
				{#each cmwr.rows as r, i}
					<circle cx={cmwr.PAD + (i / Math.max(1, cmwr.rows.length - 1)) * (cmwr.W - cmwr.PAD * 2)} cy={cmwr.H - cmwr.PAD - r.wr * (cmwr.H - cmwr.PAD * 2)} r="2" fill={r.wr >= 0.5 ? 'var(--ch-profit-strong)' : 'var(--ch-loss-strong)'}/>
				{/each}
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[9px] text-muted-foreground">
				<span>{cmwr.first}</span><span>← monthly win rate →</span><span>{cmwr.last}</span>
			</div>
			<p class="mt-1 text-[10px] text-muted-foreground">Rising trend = strategy improving over time · consistent &gt;50% = reliable edge · dips below 50% = market regime change or strategy degradation</p>
		</section>
	{/if}

	{#if closedTradeProfitDistribution}
		{@const cpd = closedTradeProfitDistribution}
		<section class="rounded-lg border border-border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">Closed Trade Profit % Distribution <ChartInfo metric="distribution" {lang} /></h2>
			<p class="mb-3 text-[11px] text-muted-foreground">{cpd.total} trades · {(cpd.wr * 100).toFixed(1)}% win rate · profit bucket histogram</p>
			<div class="flex h-24 items-end gap-1">
				{#each cpd.buckets as b}
					{@const isPos = b.lo >= 0}
					{@const color = isPos ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<div class="flex flex-1 flex-col items-center gap-0.5">
						<span class="font-mono text-[8px] text-muted-foreground">{b.count > 0 ? b.count : ''}</span>
						<div class="w-full rounded-t-sm" style="height:{b.barPct * 0.8}%; min-height:{b.count > 0 ? '2px' : '0'}; background:{color}"></div>
					</div>
				{/each}
			</div>
			<div class="mt-1 flex justify-between">
				{#each cpd.buckets as b}
					<span class="flex-1 text-center font-mono text-[7px] text-muted-foreground">{b.label}</span>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Green = profit · red = loss buckets · right-skewed histogram = trades cluster in small wins · left-skewed = tail-risk losses dominate</p>
		</section>
	{/if}

	{#if closedTradeProfitByExitReason}
		<section class="rounded-lg border border-border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">Avg Profit by Exit Reason <ChartInfo metric="exitReason" {lang} /></h2>
			<div class="space-y-1">
				{#each closedTradeProfitByExitReason as r}
					{@const color = r.avg > 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss)'}
					<div class="flex items-center gap-2">
						<span class="w-32 truncate text-right font-mono text-[10px] text-muted-foreground">{r.reason}</span>
						<div class="h-4 flex-1 overflow-hidden rounded-sm bg-muted">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{color}"></div>
						</div>
						<span class="w-16 text-right font-mono text-[10px]" style="color:{color}">{r.avg > 0 ? '+' : ''}{r.avg.toFixed(2)}%</span>
						<span class="w-12 text-right font-mono text-[9px] text-muted-foreground">{(r.wr * 100).toFixed(0)}% WR</span>
						<span class="w-8 text-right font-mono text-[9px] text-muted-foreground">n={r.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Exit type with highest avg profit = most valuable signal · stoploss exits near 0% = tight stops · large negative = wide stoploss or no stoploss on spot</p>
		</section>
	{/if}

	{#if liveEntryTagPerformance}
		<section class="rounded-lg border border-border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">Avg Profit by Entry Tag <ChartInfo metric="enterTag" {lang} /></h2>
			<div class="space-y-1">
				{#each liveEntryTagPerformance as r}
					{@const color = r.avg > 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss)'}
					<div class="flex items-center gap-2">
						<span class="w-32 truncate text-right font-mono text-[10px] text-muted-foreground" title={r.tag}>{r.tag}</span>
						<div class="h-4 flex-1 overflow-hidden rounded-sm bg-muted">
							<div class="h-full rounded-sm" style="width:{r.barPct}%; background:{color}"></div>
						</div>
						<span class="w-14 text-right font-mono text-[10px]" style="color:{color}">{r.avg > 0 ? '+' : ''}{r.avg.toFixed(2)}%</span>
						<span class="w-10 text-right font-mono text-[9px] text-muted-foreground">{(r.wr * 100).toFixed(0)}%wr</span>
						<span class="w-8 text-right font-mono text-[9px] text-muted-foreground">n={r.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[10px] text-muted-foreground">Avg profit % per entry tag · sorted by avg profit descending · win rate and trade count shown · identifies which entry signal produces best live results</p>
		</section>
	{/if}

	{#if liveRecentTradeProfitMovingAvg}
		<section class="rounded-lg border border-border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">10-Trade Rolling Avg Profit % <ChartInfo metric="avgProfit" {lang} /></h2>
			<p class="mb-2 text-[10px] text-muted-foreground">Smoothed 10-trade moving average of profit % over time · latest: <span class="font-mono" style="color:{liveRecentTradeProfitMovingAvg.latest >= 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss-strong)'};">{liveRecentTradeProfitMovingAvg.latest >= 0 ? '+' : ''}{liveRecentTradeProfitMovingAvg.latest.toFixed(2)}%</span> · overall avg: {liveRecentTradeProfitMovingAvg.overall.toFixed(2)}%</p>
			<svg viewBox="0 0 {liveRecentTradeProfitMovingAvg.W} {liveRecentTradeProfitMovingAvg.H}" class="w-full">
				<line x1="0" y1={liveRecentTradeProfitMovingAvg.zeroY} x2={liveRecentTradeProfitMovingAvg.W} y2={liveRecentTradeProfitMovingAvg.zeroY} stroke="var(--ch-axis-muted)" stroke-width="1" stroke-dasharray="4,3"/>
				<polyline points={liveRecentTradeProfitMovingAvg.polyline} fill="none" stroke="var(--ch-violet-strong)" stroke-width="2"/>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Each point = avg of last 10 trades · rising = improving recent performance · falling = recent underperformance · {liveRecentTradeProfitMovingAvg.count} data points</p>
		</section>
	{/if}

	{#if liveMonthlyTradeCount}
		<section class="rounded-lg border border-border bg-card p-4">
			<h2 class="mb-3 text-sm font-semibold">Monthly Trade Count <ChartInfo metric="tradeCount" {lang} /></h2>
			<svg viewBox="0 0 {liveMonthlyTradeCount.W} {liveMonthlyTradeCount.H}" class="w-full">
				{#each liveMonthlyTradeCount.bars as b}
					<rect x={b.x} y={liveMonthlyTradeCount.H - liveMonthlyTradeCount.PAD - b.h} width={b.w} height={b.h}
						fill={b.aboveAvg ? 'var(--ch-violet)' : 'var(--ch-axis-muted)'} rx="1"/>
				{/each}
			</svg>
			<div class="mt-1 flex justify-between font-mono text-[8px] text-muted-foreground">
				<span>{liveMonthlyTradeCount.bars[0]?.label}</span>
				<span>← monthly trade count →</span>
				<span>{liveMonthlyTradeCount.bars[liveMonthlyTradeCount.bars.length - 1]?.label}</span>
			</div>
			<p class="mt-1 text-[9px] text-muted-foreground">Purple = above monthly avg ({liveMonthlyTradeCount.avg.toFixed(0)} trades) · grey = below avg · high months = active strategy periods · low months = range-bound / low signal</p>
		</section>
	{/if}

	{#if liveStrategyProfitConcentration}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">Profit Concentration by Strategy</h3>
			<p class="mb-3 text-[10px] text-muted-foreground">Share of total closed profit contributed by each strategy · high concentration = one strategy dominates P&amp;L · diversified = spread across multiple strategies</p>
			<div class="space-y-1.5">
				{#each liveStrategyProfitConcentration.rows as row}
					<div class="flex items-center gap-2 text-xs">
						<span class="w-36 shrink-0 truncate font-mono text-[10px]">{row.strategy}</span>
						<div class="relative h-4 flex-1 overflow-hidden rounded bg-muted/30">
							<div class="h-full rounded" style="width:{Math.max(0, row.share).toFixed(1)}%; background:{row.color}"></div>
						</div>
						<span class="w-14 text-right font-mono" style="color:{row.color}">{row.share.toFixed(1)}%</span>
						<span class="w-16 text-right text-[9px] text-muted-foreground">{row.profit >= 0 ? '+' : ''}{row.profit.toFixed(1)}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Total closed profit = {liveStrategyProfitConcentration.total.toFixed(1)} USDT · top {liveStrategyProfitConcentration.rows.length} strategies shown · negative share = net loss contributor</p>
		</section>
	{/if}

	{#if livePairAvgDuration}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">Avg Trade Duration by Pair</h3>
			<p class="mb-3 text-[10px] text-muted-foreground">Average holding time in minutes per pair across closed trades · long avg = pair requires patience or has slow momentum · short avg = fast in-and-out</p>
			<div class="space-y-1.5">
				{#each livePairAvgDuration.rows as row}
					{@const hrs = row.avg / 60}
					<div class="flex items-center gap-2 text-xs">
						<span class="w-24 shrink-0 font-mono text-[10px] text-muted-foreground">{row.pair}</span>
						<div class="relative h-4 flex-1 overflow-hidden rounded bg-muted/30">
							<div class="h-full rounded" style="width:{(row.avg / livePairAvgDuration.maxAvg * 100).toFixed(1)}%; background:rgba(99,102,241,{Math.min(0.85, 0.3 + row.avg / livePairAvgDuration.maxAvg * 0.55)})"></div>
						</div>
						<span class="w-16 text-right font-mono text-[10px]">{hrs >= 1 ? hrs.toFixed(1) + 'h' : row.avg.toFixed(0) + 'm'}</span>
						<span class="w-10 text-right text-[9px] text-muted-foreground">n={row.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Top pair by hold time = {livePairAvgDuration.rows[0].pair} ({(livePairAvgDuration.rows[0].avg / 60).toFixed(1)}h avg) · long hold = momentum play · short hold = mean-reversion or scalp</p>
		</section>
	{/if}

	{#if liveExitReasonByBot}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">Exit Reason Breakdown by Bot</h3>
			<p class="mb-3 text-[10px] text-muted-foreground">Share of exit reasons per bot · high stoploss % = strategy struggling · high ROI % = strategy hitting targets cleanly · n = total closed trades</p>
			<div class="space-y-3">
				{#each liveExitReasonByBot.rows as row}
					<div>
						<div class="mb-1 flex items-center justify-between text-[10px]">
							<span class="font-mono font-medium">{row.bot}</span>
							<span class="text-muted-foreground">n={row.total}</span>
						</div>
						<div class="flex h-4 w-full overflow-hidden rounded">
							{#each row.breakdown.filter(b => b.count > 0) as b}
								<div class="h-full" style="width:{b.pct.toFixed(1)}%; background:{b.color}" title="{b.reason}: {b.count} ({b.pct.toFixed(0)}%)"></div>
							{/each}
						</div>
					</div>
				{/each}
			</div>
			<div class="mt-2 flex flex-wrap gap-3 text-[9px] text-muted-foreground">
				{#each liveExitReasonByBot.allReasons as r}
					<span><span style="color:{liveExitReasonByBot.REASON_COL[r] ?? 'var(--ch-axis)'}">●</span> {r}</span>
				{/each}
			</div>
		</section>
	{/if}

	{#if livePairSharpeProxy}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">Pair Sharpe Proxy (mean/std profit)</h3>
			<p class="mb-2 text-[10px] text-muted-foreground">For each pair with ≥4 trades: mean profit ÷ std dev of profit · higher = more consistent positive returns · negative = erratic or loss-biased pair</p>
			<div class="space-y-1">
				{#each livePairSharpeProxy.rows as row}
					{@const pct = (row.sharpe / livePairSharpeProxy.maxAbs) * 50}
					{@const color = row.sharpe >= 0 ? `var(--ch-profit)` : `var(--ch-loss)`}
					<div class="flex items-center gap-2 text-[10px]">
						<span class="w-28 truncate font-mono">{row.pair}</span>
						<div class="relative flex h-3 flex-1 items-center">
							<div class="absolute left-1/2 h-full w-px bg-border opacity-40"></div>
							{#if row.sharpe >= 0}
								<div class="absolute h-full rounded-r" style="left:50%; width:{pct.toFixed(1)}%; background:{color}"></div>
							{:else}
								<div class="absolute h-full rounded-l" style="right:50%; width:{Math.abs(pct).toFixed(1)}%; background:{color}"></div>
							{/if}
						</div>
						<span class="w-12 text-right font-mono" style="color:{color}">{row.sharpe.toFixed(2)}</span>
						<span class="w-10 text-right text-muted-foreground">n={row.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Sharpe proxy = mean_profit / std_profit · not annualized · diverges from true Sharpe without holding period · bars diverge from center</p>
		</section>
	{/if}

	{#if liveBotMonthlyTradeCount}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">Bot Monthly Trade Activity</h3>
			<p class="mb-2 text-[10px] text-muted-foreground">Trade count per bot per month · darker = more active · white = no trades · reveals bot downtime or seasonal patterns</p>
			<div class="overflow-x-auto">
				<table class="w-full text-[9px]">
					<thead>
						<tr>
							<th class="pr-2 text-left text-muted-foreground">Bot</th>
							{#each liveBotMonthlyTradeCount.months as mo}
								<th class="px-0.5 text-center text-muted-foreground">{mo.slice(5)}</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each liveBotMonthlyTradeCount.bots as bot}
							<tr>
								<td class="truncate pr-2 font-mono" style="max-width:80px">{bot}</td>
								{#each liveBotMonthlyTradeCount.months as mo}
									{@const cell = liveBotMonthlyTradeCount.cells.find(c => c.bot === bot && c.mo === mo)}
									<td class="px-0.5 text-center">
										<div class="mx-auto h-4 w-6 rounded text-center text-[8px] leading-4" style="background:{cell?.color ?? 'var(--ch-axis-faint)'}; color:var(--ch-axis-strong)">{cell?.count ?? ''}</div>
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Last 8 months · darker blue = higher trade count · empty = no trades that month · useful for detecting bot outages</p>
		</section>
	{/if}

	{#if liveStrategyAvgProfit}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-1 text-sm font-semibold">Avg Profit per Trade by Strategy</h3>
			<p class="mb-2 text-[10px] text-muted-foreground">Average profit % per closed trade grouped by strategy · distinguishes consistently profitable strategies from breakeven or losing ones</p>
			<div class="space-y-1">
				{#each liveStrategyAvgProfit.rows as row}
					{@const color = row.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					{@const pct = (Math.abs(row.avg) / liveStrategyAvgProfit.maxAbs * 50).toFixed(1)}
					<div class="flex items-center gap-2 text-[10px]">
						<span class="w-36 truncate font-mono text-[9px]">{row.strategy}</span>
						<div class="relative flex h-3 flex-1 items-center">
							<div class="absolute left-1/2 h-full w-px bg-border opacity-40"></div>
							{#if row.avg >= 0}
								<div class="absolute h-full rounded-r" style="left:50%; width:{pct}%; background:{color}"></div>
							{:else}
								<div class="absolute h-full rounded-l" style="right:50%; width:{pct}%; background:{color}"></div>
							{/if}
						</div>
						<span class="w-14 text-right font-mono" style="color:{color}">{row.avg.toFixed(3)}%</span>
						<span class="w-10 text-right text-muted-foreground">n={row.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Diverging from center · positive = net profitable trades · small avg × many trades = cumulative edge · low n strategies statistically unreliable</p>
		</section>
	{/if}

	{#if liveProfitDecileDistribution}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Profit % Distribution — All Closed Trades</h3>
			<svg viewBox="0 0 {liveProfitDecileDistribution.W} {liveProfitDecileDistribution.H}" class="w-full" style="height:90px">
				{#if liveProfitDecileDistribution.zeroX !== null}
					<line x1={liveProfitDecileDistribution.zeroX} y1={liveProfitDecileDistribution.PAD} x2={liveProfitDecileDistribution.zeroX} y2={liveProfitDecileDistribution.H - liveProfitDecileDistribution.PAD - 10} stroke="var(--ch-axis-muted)" stroke-width="1" stroke-dasharray="3,3"/>
				{/if}
				{#each liveProfitDecileDistribution.bars as bar}
					<rect x={bar.x} y={bar.y} width={liveProfitDecileDistribution.barW} height={bar.h} rx="1" fill={bar.color}/>
				{/each}
				<text x={liveProfitDecileDistribution.PAD} y={liveProfitDecileDistribution.H - 1} font-size="7" fill="var(--ch-axis)">{liveProfitDecileDistribution.vMin}%</text>
				<text x={liveProfitDecileDistribution.W - liveProfitDecileDistribution.PAD} y={liveProfitDecileDistribution.H - 1} text-anchor="end" font-size="7" fill="var(--ch-axis)">{liveProfitDecileDistribution.vMax}%</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">{liveProfitDecileDistribution.total} trades · {liveProfitDecileDistribution.posCount} profitable ({((liveProfitDecileDistribution.posCount / liveProfitDecileDistribution.total) * 100).toFixed(0)}%) · {liveProfitDecileDistribution.negCount} losses · green = profit · red = loss</p>
		</section>
	{/if}

	{#if livePairBotProfitMatrix}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Profit — Pair × Bot</h3>
			<div class="overflow-x-auto">
				<table class="w-full text-[9px]">
					<thead>
						<tr>
							<th class="w-20 text-left text-muted-foreground font-normal pb-1">Pair</th>
							{#each livePairBotProfitMatrix.topBots as bot}
								<th class="text-center text-muted-foreground font-normal pb-1 px-0.5 truncate max-w-[60px]">{bot}</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each livePairBotProfitMatrix.topPairs as pair}
							<tr>
								<td class="text-muted-foreground py-0.5 truncate">{pair}</td>
								{#each livePairBotProfitMatrix.topBots as bot}
									{@const cell = livePairBotProfitMatrix.cells.find(c => c.pair === pair && c.bot === bot)}
									{@const isPos = (cell?.avg ?? 0) >= 0}
									{@const frac = cell?.avg != null ? Math.abs(cell.avg) / livePairBotProfitMatrix.absMax : 0}
									{@const bg = cell?.avg != null ? (isPos ? `rgba(34,197,94,${(0.1 + frac * 0.7).toFixed(2)})` : `rgba(239,68,68,${(0.1 + frac * 0.7).toFixed(2)})`) : 'transparent'}
									<td class="text-center py-0.5 px-0.5 rounded font-mono" style="background:{bg}; color:{cell?.avg != null ? (frac > 0.4 ? 'var(--ch-axis-strong)' : 'var(--ch-axis-strong)') : 'var(--ch-axis-muted)'}">
										{cell?.avg != null ? cell.avg.toFixed(2) : '—'}
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Avg profit % per pair per bot · green = profitable · red = loss · — = no trades · top 8 pairs by volume shown</p>
		</section>
	{/if}

	{#if liveBotStreakAnalysis}
		<section class="mt-6 rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Win/Loss Streak Analysis by Bot</h3>
			<div class="space-y-2">
				{#each liveBotStreakAnalysis.rows as row}
					{@const winPct = (row.maxWin / liveBotStreakAnalysis.maxStreak * 100).toFixed(1)}
					{@const lossPct = (row.maxLoss / liveBotStreakAnalysis.maxStreak * 100).toFixed(1)}
					<div class="flex items-center gap-2">
						<span class="w-24 shrink-0 truncate text-[9px] text-muted-foreground">{row.bot}</span>
						<div class="flex flex-1 gap-1 h-3">
							<div class="rounded" style="width:{winPct}%; background:var(--ch-profit); min-width:2px" title="Max win streak: {row.maxWin}"></div>
							<div class="rounded" style="width:{lossPct}%; background:var(--ch-loss); min-width:2px" title="Max loss streak: {row.maxLoss}"></div>
						</div>
						<span class="w-12 text-right text-[9px]" style="color:var(--ch-profit-strong)">+{row.maxWin}W</span>
						<span class="w-12 text-right text-[9px]" style="color:var(--ch-loss-strong)">-{row.maxLoss}L</span>
						<span class="w-12 text-right text-[9px] text-muted-foreground">{row.winRate.toFixed(0)}%WR</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Green = max consecutive wins · red = max consecutive losses · long loss streaks signal strategy deterioration</p>
		</section>
	{/if}

	{#if liveStrategyProfitBoxplot}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Profit Distribution by Strategy (Box Plot)</h3>
			<svg viewBox="0 0 {liveStrategyProfitBoxplot.W} {liveStrategyProfitBoxplot.H}" class="w-full" style="height:{liveStrategyProfitBoxplot.H}px">
				{#if liveStrategyProfitBoxplot.zeroX !== null}
					<line x1={liveStrategyProfitBoxplot.zeroX} y1="0" x2={liveStrategyProfitBoxplot.zeroX} y2={liveStrategyProfitBoxplot.H} stroke="var(--ch-axis-muted)" stroke-width="1" stroke-dasharray="3,3"/>
				{/if}
				{#each liveStrategyProfitBoxplot.rects as r}
					<rect x={Math.min(r.x1,r.x3)} y={r.y+3} width={Math.abs(r.x3-r.x1)} height="10" rx="1" fill={r.color}/>
					<line x1={r.xMed} y1={r.y+2} x2={r.xMed} y2={r.y+14} stroke="var(--ch-axis-strong)" stroke-width="2"/>
					<circle cx={r.xAvg} cy={r.y+8} r="2" fill="var(--ch-warn)"/>
					<text x="4" y={r.y+11} font-size="7" fill="var(--ch-axis)">{r.strategy}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Box = Q1–Q3 profit range · white line = median · yellow dot = mean · top 10 strategies by median · {liveStrategyProfitBoxplot.mn}% to {liveStrategyProfitBoxplot.mx}%</p>
		</section>
	{/if}

	{#if liveDurationByPair}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Trade Duration by Pair (longest first)</h3>
			<div class="space-y-1.5">
				{#each liveDurationByPair.rows as row}
					{@const pct = (row.avg / liveDurationByPair.maxAvg * 100).toFixed(1)}
					<div class="flex items-center gap-2">
						<span class="w-16 text-right font-mono text-[9px] text-muted-foreground">{row.pair}</span>
						<div class="flex-1 h-3 rounded bg-muted/20 overflow-hidden">
							<div class="h-full rounded" style="width:{pct}%; background:var(--ch-violet)"></div>
						</div>
						<span class="w-14 text-right text-[10px] text-muted-foreground">{liveDurationByPair.toHrs(row.avg)}</span>
						<span class="w-8 text-right text-[9px] text-muted-foreground">n={row.count}</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Avg trade holding time per pair · longer duration = slower-moving asset or wider targets · useful for position sizing</p>
		</section>
	{/if}

	{#if liveProfitByHourOfDay}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Trade Profit by Close Hour (UTC)</h3>
			<svg viewBox="0 0 {liveProfitByHourOfDay.W} {liveProfitByHourOfDay.H}" class="w-full" style="height:70px">
				<line x1="0" y1={liveProfitByHourOfDay.H / 2} x2={liveProfitByHourOfDay.W} y2={liveProfitByHourOfDay.H / 2} stroke="var(--ch-axis-faint)" stroke-width="1"/>
				{#each liveProfitByHourOfDay.rows as row}
					{@const x = liveProfitByHourOfDay.PAD + row.hr * (liveProfitByHourOfDay.barW + 1)}
					{@const midY = liveProfitByHourOfDay.H / 2}
					{@const barH = Math.max(1, (Math.abs(row.avg) / liveProfitByHourOfDay.maxAbs) * (midY - liveProfitByHourOfDay.PAD - 4))}
					{@const color = row.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					{#if row.count > 0}
						{#if row.avg >= 0}
							<rect x={x} y={midY - barH} width={liveProfitByHourOfDay.barW} height={barH} fill={color}/>
						{:else}
							<rect x={x} y={midY} width={liveProfitByHourOfDay.barW} height={barH} fill={color}/>
						{/if}
					{/if}
				{/each}
			</svg>
			<div class="mt-1 flex justify-between text-[9px] text-muted-foreground">
				<span>00:00</span><span>Avg profit % by UTC close hour · green = profitable · red = losing · bars above/below center</span><span>23:00</span>
			</div>
		</section>
	{/if}

	<section class="mt-4 rounded-lg border border-dashed bg-card p-4 text-xs text-muted-foreground">
		{t(lang, 'live.how')}
	</section>

	{#if liveProfitByExitReason}
		<section class="mt-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Profit by Exit Reason</h3>
			<svg viewBox="0 0 {liveProfitByExitReason.W} {liveProfitByExitReason.H}" class="w-full" style="height:{liveProfitByExitReason.H}px">
				<line x1={liveProfitByExitReason.midX} y1={liveProfitByExitReason.PAD} x2={liveProfitByExitReason.midX} y2={liveProfitByExitReason.H - liveProfitByExitReason.PAD} stroke="var(--ch-axis-muted)" stroke-width="0.8"/>
				{#each liveProfitByExitReason.rows as row, i}
					{@const cy = liveProfitByExitReason.PAD + i * 14 + 7}
					{@const bw = (Math.abs(row.avg) / liveProfitByExitReason.maxAbs) * liveProfitByExitReason.barMaxW}
					{@const positive = row.avg >= 0}
					{@const color = positive ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect
						x={positive ? liveProfitByExitReason.midX : liveProfitByExitReason.midX - bw}
						y={cy - 5}
						width={bw}
						height={10}
						rx="1"
						fill={color}
					/>
					<text x={liveProfitByExitReason.midX - 4} y={cy + 3.5} text-anchor="end" font-size="7" fill="var(--ch-axis-strong)">{row.reason.slice(0, 16)}</text>
					<text x={liveProfitByExitReason.midX + bw + 3} y={cy + 3.5} font-size="7" fill={color}>{row.avg >= 0 ? '+' : ''}{row.avg.toFixed(2)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg profit % per exit reason · green = profitable · red = losing · reveals which exit signals deliver best outcomes</p>
		</section>
	{/if}

	{#if liveProfitHistogram}
		<section class="mt-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Trade Profit Distribution</h3>
			<svg viewBox="0 0 {liveProfitHistogram.W} {liveProfitHistogram.H}" class="w-full" style="height:80px">
				{#each liveProfitHistogram.counts as b, i}
					{@const x = liveProfitHistogram.PAD + i * (liveProfitHistogram.barW + 1)}
					{@const barH = Math.max(1, (b.count / liveProfitHistogram.maxCount) * (liveProfitHistogram.H - liveProfitHistogram.PAD * 2 - 10))}
					{@const color = b.lo >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect x={x} y={liveProfitHistogram.H - 10 - barH} width={liveProfitHistogram.barW} height={barH} rx="1" fill={color}/>
				{/each}
				<text x={liveProfitHistogram.PAD} y={liveProfitHistogram.H - 1} font-size="7" fill="var(--ch-axis)">{liveProfitHistogram.mn}%</text>
				<text x={liveProfitHistogram.W - liveProfitHistogram.PAD} y={liveProfitHistogram.H - 1} text-anchor="end" font-size="7" fill="var(--ch-axis)">{liveProfitHistogram.mx}%</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Profit % distribution across {liveProfitHistogram.counts.reduce((a, b) => a + b.count, 0)} live trades · avg {liveProfitHistogram.avg}% · green = winning bins · red = losing bins</p>
		</section>
	{/if}

	{#if liveCumulativeProfitTimeline}
		<section class="mt-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Cumulative Profit % Timeline</h3>
			<svg viewBox="0 0 {liveCumulativeProfitTimeline.W} {liveCumulativeProfitTimeline.H}" class="w-full" style="height:90px">
				{#if liveCumulativeProfitTimeline.zeroY >= liveCumulativeProfitTimeline.PAD && liveCumulativeProfitTimeline.zeroY <= liveCumulativeProfitTimeline.H - liveCumulativeProfitTimeline.PAD}
					<line x1={liveCumulativeProfitTimeline.PAD} y1={liveCumulativeProfitTimeline.zeroY} x2={liveCumulativeProfitTimeline.W - liveCumulativeProfitTimeline.PAD} y2={liveCumulativeProfitTimeline.zeroY} stroke="var(--ch-axis-faint)" stroke-width="0.8" stroke-dasharray="4,3"/>
				{/if}
				<polyline points={liveCumulativeProfitTimeline.polyline} fill="none" stroke={parseFloat(liveCumulativeProfitTimeline.finalCum) >= 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss-strong)'} stroke-width="1.8" stroke-linejoin="round"/>
				<circle cx={liveCumulativeProfitTimeline.toX(liveCumulativeProfitTimeline.pts.length - 1)} cy={liveCumulativeProfitTimeline.toY(parseFloat(liveCumulativeProfitTimeline.finalCum))} r="3" fill={parseFloat(liveCumulativeProfitTimeline.finalCum) >= 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss-strong)'}/>
				<text x={liveCumulativeProfitTimeline.W - liveCumulativeProfitTimeline.PAD} y={liveCumulativeProfitTimeline.toY(parseFloat(liveCumulativeProfitTimeline.finalCum)) - 4} text-anchor="end" font-size="7.5" fill={parseFloat(liveCumulativeProfitTimeline.finalCum) >= 0 ? 'var(--ch-profit-strong)' : 'var(--ch-loss-strong)'}>{liveCumulativeProfitTimeline.finalCum}%</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Running sum of profit % across all {liveCumulativeProfitTimeline.pts.length} closed live trades in chronological order · shows overall trajectory of live performance</p>
		</section>
	{/if}

	{#if livePairProfitScatter}
		<section class="mt-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Pair Profit vs Holding Time Scatter ({livePairProfitScatter.count} pairs)</h3>
			<svg viewBox="0 0 {livePairProfitScatter.W} {livePairProfitScatter.H}" class="w-full" style="height:120px">
				<line x1={livePairProfitScatter.zeroX} y1={livePairProfitScatter.PAD} x2={livePairProfitScatter.zeroX} y2={livePairProfitScatter.H - livePairProfitScatter.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.8" stroke-dasharray="3,2"/>
				{#each livePairProfitScatter.dots as d}
					<circle cx={d.cx} cy={d.cy} r={d.r} fill={d.color}/>
					<text x={d.cx} y={d.cy - d.r - 1} text-anchor="middle" font-size="6" fill="var(--ch-axis-strong)">{d.pair}</text>
				{/each}
			</svg>
			<div class="mt-1 flex justify-between text-[9px] text-muted-foreground">
				<span>← losing pairs</span>
				<span>x=avg profit · y=avg hold hrs (higher=longer) · size=trade count · green=profitable</span>
				<span>winning pairs →</span>
			</div>
		</section>
	{/if}

	{#if liveProfitByDayOfWeek}
		<section class="mt-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Trade Profit by Day of Week (UTC close)</h3>
			<svg viewBox="0 0 {liveProfitByDayOfWeek.W} {liveProfitByDayOfWeek.H}" class="w-full" style="height:80px">
				<line x1={liveProfitByDayOfWeek.PAD} y1={liveProfitByDayOfWeek.midY} x2={liveProfitByDayOfWeek.W - liveProfitByDayOfWeek.PAD} y2={liveProfitByDayOfWeek.midY} stroke="var(--ch-axis-faint)" stroke-width="0.8"/>
				{#each liveProfitByDayOfWeek.rows as row, i}
					{@const x = liveProfitByDayOfWeek.PAD + i * (liveProfitByDayOfWeek.barW + 3)}
					{@const bh = row.count >= 1 ? Math.max(2, (Math.abs(row.avg) / liveProfitByDayOfWeek.maxAbs) * (liveProfitByDayOfWeek.midY - liveProfitByDayOfWeek.PAD - 10)) : 0}
					{@const positive = row.avg >= 0}
					{@const color = positive ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					{@const opacity = row.count >= 3 ? '1' : '0.4'}
					<rect x={x} y={positive ? liveProfitByDayOfWeek.midY - bh : liveProfitByDayOfWeek.midY} width={liveProfitByDayOfWeek.barW} height={bh} rx="2" fill={color} style="opacity:{opacity}"/>
					<text x={x + liveProfitByDayOfWeek.barW / 2} y={liveProfitByDayOfWeek.H - 1} text-anchor="middle" font-size="7.5" fill="var(--ch-axis)">{row.day}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg profit % per UTC weekday · faded bars = fewer than 3 trades · reveals weekly seasonality in live trade outcomes</p>
		</section>
	{/if}

	{#if liveExitTagProfitRanking}
		<section class="mt-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Exit Reason Avg Profit Ranking</h3>
			<div class="space-y-1.5">
				{#each liveExitTagProfitRanking.rows as row, i}
					{@const pct = (Math.abs(row.avg) / liveExitTagProfitRanking.maxAbs * 100).toFixed(1)}
					{@const color = row.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<div class="flex items-center gap-2">
						<span class="w-5 text-right text-[9px] text-muted-foreground">{i + 1}.</span>
						<span class="w-28 truncate text-[9px] text-muted-foreground">{row.tag}</span>
						<div class="flex-1 h-3 rounded bg-muted/20 overflow-hidden">
							<div class="h-full rounded" style="width:{pct}%; background:{color}"></div>
						</div>
						<span class="w-10 text-right font-mono text-[10px]" style="color:{color}">{row.avg >= 0 ? '+' : ''}{row.avg.toFixed(2)}%</span>
						<span class="w-12 text-right text-[9px] text-muted-foreground">{row.winPct.toFixed(0)}%WR·{row.count}t</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Average profit per exit tag · green=positive avg · red=negative · WR=win rate for that exit reason · identifies which exit types are most profitable</p>
		</section>
	{/if}

	{#if liveBotProfitTimeline}
		<section class="mt-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Cumulative Profit Timeline by Bot</h3>
			<svg viewBox="0 0 {liveBotProfitTimeline.W} {liveBotProfitTimeline.H}" class="w-full" style="height:85px">
				<line x1={liveBotProfitTimeline.PAD} y1={liveBotProfitTimeline.zeroY} x2={liveBotProfitTimeline.W - liveBotProfitTimeline.PAD} y2={liveBotProfitTimeline.zeroY} stroke="var(--ch-axis-faint)" stroke-width="0.8" stroke-dasharray="3,2"/>
				{#each liveBotProfitTimeline.polylines as line}
					<polyline points={line.poly} fill="none" stroke={line.color} stroke-width="1.5" stroke-linejoin="round"/>
				{/each}
			</svg>
			<div class="mt-1 flex flex-wrap gap-2">
				{#each liveBotProfitTimeline.polylines as line}
					<span class="text-[9px]" style="color:{line.color}">■ {line.bot}</span>
				{/each}
				<span class="text-[9px] text-muted-foreground">· cumulative sum of trade profit % per bot · rising = net profitable · dashed zero line</span>
			</div>
		</section>
	{/if}

	{#if livePairAvgProfitRanking}
		<section class="mt-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Trade Profit by Asset (min 3 trades)</h3>
			<div class="space-y-1.5">
				{#each livePairAvgProfitRanking.rows as row, i}
					{@const pct = (Math.abs(row.avg) / livePairAvgProfitRanking.maxAbs * 100).toFixed(1)}
					{@const color = row.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<div class="flex items-center gap-2">
						<span class="w-5 text-right text-[9px] text-muted-foreground">{i + 1}.</span>
						<span class="w-14 text-[9px] text-muted-foreground">{row.pair}</span>
						<div class="flex-1 h-3 rounded bg-muted/20 overflow-hidden">
							<div class="h-full rounded" style="width:{pct}%; background:{color}"></div>
						</div>
						<span class="w-12 text-right font-mono text-[10px]" style="color:{color}">{row.avg >= 0 ? '+' : ''}{row.avg.toFixed(2)}%</span>
						<span class="w-6 text-right text-[9px] text-muted-foreground">{row.count}t</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Average trade profit % per base asset across all live bots · green=positive avg · identifies which coins are generating the best live returns</p>
		</section>
	{/if}
	{#if liveBotDrawdownComparison}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Bot Drawdown Comparison (median + p90)</h3>
			<div class="space-y-1.5">
				{#each liveBotDrawdownComparison.rows as row}
					{@const medW = (row.med / liveBotDrawdownComparison.maxVal) * 100}
					{@const p90W = (row.p90 / liveBotDrawdownComparison.maxVal) * 100}
					{@const color = row.med <= 5 ? 'var(--ch-profit)' : row.med <= 15 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
					<div class="flex items-center gap-2">
						<span class="w-32 truncate text-right text-[10px] text-muted-foreground">{row.bot}</span>
						<div class="relative h-3 flex-1 rounded bg-secondary/40">
							<div class="absolute left-0 top-0 h-3 rounded" style="width:{p90W}%;background:var(--ch-axis-faint)"></div>
							<div class="absolute left-0 top-0 h-3 rounded" style="width:{medW}%;background:{color}"></div>
						</div>
						<span class="w-12 text-right font-mono text-[10px]" style="color:{color}">{row.med.toFixed(1)}%</span>
					</div>
				{/each}
			</div>
			<p class="mt-2 text-[9px] text-muted-foreground">Median trade drawdown per bot (solid) + p90 (ghost) · green≤5% · yellow≤15% · red&gt;15% · sorted by worst median drawdown</p>
		</section>
	{/if}
	{#if liveProfitByStakeSize}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Trade Profit by Stake Size</h3>
			<svg viewBox="0 0 {liveProfitByStakeSize.W} {liveProfitByStakeSize.H}" class="w-full" style="height:72px">
				<line x1={liveProfitByStakeSize.PAD} y1={liveProfitByStakeSize.midY} x2={liveProfitByStakeSize.W - liveProfitByStakeSize.PAD} y2={liveProfitByStakeSize.midY} stroke="var(--ch-axis-faint)" stroke-width="0.7"/>
				{#each liveProfitByStakeSize.rows as row, i}
					{@const x = liveProfitByStakeSize.PAD + i * (liveProfitByStakeSize.barW + 3)}
					{@const bh = Math.max(2, (Math.abs(row.avg) / liveProfitByStakeSize.maxAbs) * (liveProfitByStakeSize.midY - liveProfitByStakeSize.PAD))}
					{@const color = row.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect {x} y={row.avg >= 0 ? liveProfitByStakeSize.midY - bh : liveProfitByStakeSize.midY} width={liveProfitByStakeSize.barW} height={bh} rx="1" fill={color}/>
					<text x={x + liveProfitByStakeSize.barW / 2} y={liveProfitByStakeSize.H - 1} text-anchor="middle" font-size="6" fill="var(--ch-axis)">{row.label}</text>
					<text x={x + liveProfitByStakeSize.barW / 2} y={row.avg >= 0 ? liveProfitByStakeSize.midY - bh - 2 : liveProfitByStakeSize.midY + bh + 8} text-anchor="middle" font-size="6" fill={color}>{row.avg >= 0 ? '+' : ''}{row.avg.toFixed(2)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg profit % grouped by stake size (USDT) · reveals whether larger or smaller positions perform better in live trading</p>
		</section>
	{/if}
	{#if liveProfitByCloseHour}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Profit by Close Hour (UTC)</h3>
			<svg viewBox="0 0 {liveProfitByCloseHour.W} {liveProfitByCloseHour.H}" class="w-full" style="height:68px">
				<line x1={liveProfitByCloseHour.PAD} y1={liveProfitByCloseHour.midY} x2={liveProfitByCloseHour.W - liveProfitByCloseHour.PAD} y2={liveProfitByCloseHour.midY} stroke="var(--ch-axis-faint)" stroke-width="0.7"/>
				{#each liveProfitByCloseHour.hours as row}
					{@const x = liveProfitByCloseHour.PAD + row.h * (liveProfitByCloseHour.barW + 1)}
					{@const bh = Math.max(1.5, (Math.abs(row.avg) / liveProfitByCloseHour.maxAbs) * (liveProfitByCloseHour.midY - liveProfitByCloseHour.PAD))}
					{@const color = row.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect {x} y={row.avg >= 0 ? liveProfitByCloseHour.midY - bh : liveProfitByCloseHour.midY} width={liveProfitByCloseHour.barW} height={bh} fill={color}/>
					{#if row.h % 6 === 0}
						<text x={x} y={liveProfitByCloseHour.H - 1} font-size="5.5" fill="var(--ch-axis-muted)">{String(row.h).padStart(2,'0')}h</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Average trade profit % by UTC close hour · identifies intraday timing patterns in live trade outcomes</p>
		</section>
	{/if}
	{#if liveBotWinRateTrend}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Bot Win Rate Trend by Month</h3>
			<svg viewBox="0 0 {liveBotWinRateTrend.W} {liveBotWinRateTrend.H}" class="w-full" style="height:75px">
				<line x1={liveBotWinRateTrend.PAD} y1={liveBotWinRateTrend.y50} x2={liveBotWinRateTrend.W - liveBotWinRateTrend.PAD} y2={liveBotWinRateTrend.y50} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each liveBotWinRateTrend.lines as line}
					<polyline points={line.poly} fill="none" stroke={line.color} stroke-width="1.4" stroke-linejoin="round"/>
				{/each}
				{#each liveBotWinRateTrend.allMonths as mo, i}
					{#if i % Math.max(1, Math.floor(liveBotWinRateTrend.allMonths.length / 5)) === 0}
						{@const x = liveBotWinRateTrend.PAD + (i / Math.max(liveBotWinRateTrend.allMonths.length - 1, 1)) * (liveBotWinRateTrend.W - liveBotWinRateTrend.PAD * 2)}
						<text {x} y={liveBotWinRateTrend.H - 1} text-anchor="middle" font-size="6" fill="var(--ch-axis-muted)">{mo.slice(5)}</text>
					{/if}
				{/each}
				<text x={liveBotWinRateTrend.PAD} y={liveBotWinRateTrend.y50 - 2} font-size="5.5" fill="var(--ch-axis-muted)">50%</text>
			</svg>
			<div class="mt-1 flex flex-wrap gap-2 text-[9px]">
				{#each liveBotWinRateTrend.lines as line}
					<span style="color:{line.color}">■ {line.bot}</span>
				{/each}
				<span class="text-muted-foreground">· above dashed = more wins than losses that month</span>
			</div>
		</section>
	{/if}
	{#if livePairTradeCountRanking}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Most Traded Pairs (top 10 by trade count)</h3>
			<svg viewBox="0 0 {livePairTradeCountRanking.W} {livePairTradeCountRanking.H}" class="w-full" style="height:{livePairTradeCountRanking.H}px">
				{#each livePairTradeCountRanking.rows as row, i}
					{@const y = i * 16 + 2}
					{@const bw = Math.max(2, (row.count / livePairTradeCountRanking.maxCount) * livePairTradeCountRanking.barMaxW)}
					{@const color = row.avgProfit >= 0.5 ? 'var(--ch-profit)' : row.avgProfit >= 0 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
					<text x="0" y={y + 9} font-size="7" fill="var(--ch-axis-strong)">{row.pair}</text>
					<rect x="115" {y} width={bw} height="11" rx="2" fill={color}/>
					<text x={115 + bw + 3} y={y + 9} font-size="7" fill="var(--ch-axis)">{row.count}</text>
					<text x={livePairTradeCountRanking.W - 2} y={y + 9} text-anchor="end" font-size="6" fill={color}>{row.avgProfit >= 0 ? '+' : ''}{row.avgProfit.toFixed(2)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Pairs ranked by trade count · bar length = frequency · right = avg profit % · color by profitability · reveals most actively traded live pairs</p>
		</section>
	{/if}

	{#if liveMonthlyTradeCountTrend}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Monthly Closed Trade Count</h3>
			<svg viewBox="0 0 {liveMonthlyTradeCountTrend.W} {liveMonthlyTradeCountTrend.H}" class="w-full" style="height:72px">
				{#each liveMonthlyTradeCountTrend.bars as bar, i}
					{@const y = liveMonthlyTradeCountTrend.H - liveMonthlyTradeCountTrend.PAD - 8 - bar.h}
					<rect x={bar.x} {y} width={liveMonthlyTradeCountTrend.bw} height={bar.h} rx="2" fill={bar.color}/>
					<text x={bar.x + liveMonthlyTradeCountTrend.bw / 2} y={y - 2} text-anchor="middle" font-size="6" fill="var(--ch-axis)">{bar.count}</text>
					{#if i % Math.max(1, Math.floor(liveMonthlyTradeCountTrend.bars.length / 6)) === 0}
						<text x={bar.x + liveMonthlyTradeCountTrend.bw / 2} y={liveMonthlyTradeCountTrend.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{bar.mo}</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Number of live trades closed per month · darker bars = higher activity months · reveals seasonal trading volume patterns</p>
		</section>
	{/if}

	{#if liveProfitByDurationBucket}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Avg Profit by Trade Duration</h3>
			<svg viewBox="0 0 {liveProfitByDurationBucket.W} {liveProfitByDurationBucket.H}" class="w-full" style="height:72px">
				<line x1={liveProfitByDurationBucket.PAD} y1={liveProfitByDurationBucket.midY} x2={liveProfitByDurationBucket.W - liveProfitByDurationBucket.PAD} y2={liveProfitByDurationBucket.midY} stroke="var(--ch-axis-faint)" stroke-width="0.7"/>
				{#each liveProfitByDurationBucket.rows as row, i}
					{@const x = liveProfitByDurationBucket.PAD + i * (liveProfitByDurationBucket.barW + 4)}
					{@const bh = Math.max(2, (Math.abs(row.avg) / liveProfitByDurationBucket.maxAbs) * (liveProfitByDurationBucket.midY - liveProfitByDurationBucket.PAD - 4))}
					{@const color = row.avg >= 0.5 ? 'var(--ch-profit)' : row.avg >= 0 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
					<rect {x} y={row.avg >= 0 ? liveProfitByDurationBucket.midY - bh : liveProfitByDurationBucket.midY} width={liveProfitByDurationBucket.barW} height={bh} rx="2" fill={color}/>
					<text x={x + liveProfitByDurationBucket.barW / 2} y={liveProfitByDurationBucket.H - liveProfitByDurationBucket.PAD + 4} text-anchor="middle" font-size="7" fill="var(--ch-axis)">{row.label}</text>
					<text x={x + liveProfitByDurationBucket.barW / 2} y={row.avg >= 0 ? liveProfitByDurationBucket.midY - bh - 2 : liveProfitByDurationBucket.midY + bh + 9} text-anchor="middle" font-size="6" fill={color}>{row.avg >= 0 ? '+' : ''}{row.avg.toFixed(2)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg profit % by trade holding duration · diverging from zero · green=positive · red=negative · reveals whether short or long holds are more profitable live</p>
		</section>
	{/if}

	{#if liveProfitPerBotBar}
		<section class="mb-6 rounded-xl border border-border bg-card p-5">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Total Profit by Bot</h3>
			<svg viewBox="0 0 {liveProfitPerBotBar.W} {liveProfitPerBotBar.H}" class="w-full" style="height:{liveProfitPerBotBar.H}px">
				{#each liveProfitPerBotBar.rows as row, i}
					{@const y = i * 18 + 4}
					{@const bw = Math.max(2, (Math.abs(row.total) / liveProfitPerBotBar.maxAbs) * liveProfitPerBotBar.barMaxW)}
					{@const color = row.total >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<text x={liveProfitPerBotBar.PAD} y={y + 11} font-size="8" fill="var(--ch-axis-strong)">{row.bot}</text>
					<rect x={liveProfitPerBotBar.PAD + 105} {y} width={bw} height="13" rx="2" fill={color}/>
					<text x={liveProfitPerBotBar.PAD + 105 + bw + 3} y={y + 11} font-size="7" fill={color}>{row.total >= 0 ? '+' : ''}{row.total.toFixed(2)}</text>
					<text x={liveProfitPerBotBar.W - 2} y={y + 11} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{row.count}t</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Total absolute profit (USDT) per bot · green=net positive · red=net negative · count=trades · reveals which bots are net profitable overall</p>
		</section>
	{/if}
	{#if livePairWinRateRanking}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Pair Win Rate Ranking</h3>
			<svg viewBox="0 0 {livePairWinRateRanking.W} {livePairWinRateRanking.H}" class="w-full" style="height:{livePairWinRateRanking.H}px">
				<line x1={livePairWinRateRanking.PAD + livePairWinRateRanking.barMaxW / 2} y1="0" x2={livePairWinRateRanking.PAD + livePairWinRateRanking.barMaxW / 2} y2={livePairWinRateRanking.H} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each livePairWinRateRanking.rows as row, i}
					{@const y = i * 16 + 2}
					{@const bw = Math.max(2, (row.wr / 100) * livePairWinRateRanking.barMaxW)}
					{@const color = row.wr >= 60 ? 'var(--ch-profit)' : row.wr >= 50 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
					<text x={livePairWinRateRanking.PAD} y={y + 10} font-size="7" fill="var(--ch-axis-strong)">{row.pair}</text>
					<rect x={livePairWinRateRanking.PAD + 82} {y} width={bw} height="12" rx="2" fill={color}/>
					<text x={livePairWinRateRanking.PAD + 82 + bw + 3} y={y + 10} font-size="7" fill={color}>{row.wr.toFixed(1)}%</text>
					<text x={livePairWinRateRanking.W - 2} y={y + 10} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{row.count}t</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Pairs ranked by win rate % (min 3 trades) · green≥60% · yellow≥50% · red&lt;50% · count=closed trades · reveals which pairs have most reliable setups</p>
		</section>
	{/if}
	{#if liveBotAvgTradeDuration}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Avg Trade Duration by Bot (min)</h3>
			<svg viewBox="0 0 {liveBotAvgTradeDuration.W} {liveBotAvgTradeDuration.H}" class="w-full" style="height:{liveBotAvgTradeDuration.H}px">
				{#each liveBotAvgTradeDuration.rows as row, i}
					{@const y = i * 16 + 2}
					{@const bw = Math.max(2, (row.avg / liveBotAvgTradeDuration.maxVal) * liveBotAvgTradeDuration.barMaxW)}
					<text x={liveBotAvgTradeDuration.PAD} y={y + 10} font-size="7" fill="var(--ch-axis-strong)">{row.bot}</text>
					<rect x={liveBotAvgTradeDuration.PAD + 105} {y} width={bw} height="12" rx="2" fill="var(--ch-violet-light)"/>
					<text x={liveBotAvgTradeDuration.PAD + 105 + bw + 3} y={y + 10} font-size="7" fill="var(--ch-axis-strong)">{row.avg >= 60 ? (row.avg / 60).toFixed(1) + 'h' : row.avg.toFixed(0) + 'm'}</text>
					<text x={liveBotAvgTradeDuration.W - 2} y={y + 10} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{row.count}t</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg trade duration in minutes per bot · indigo bars · longer = slower-trading bot · count=closed trades · reveals trading cadence and strategy time horizon per bot</p>
		</section>
	{/if}
	{#if liveProfitByMonth}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Monthly Profit (USDT) · Total {liveProfitByMonth.total >= 0 ? '+' : ''}{liveProfitByMonth.total.toFixed(2)}</h3>
			<svg viewBox="0 0 {liveProfitByMonth.W} {liveProfitByMonth.H}" class="w-full" style="height:{liveProfitByMonth.H}px">
				<line x1={liveProfitByMonth.PAD} y1={liveProfitByMonth.midY} x2={liveProfitByMonth.W - liveProfitByMonth.PAD} y2={liveProfitByMonth.midY} stroke="var(--ch-axis-faint)" stroke-width="0.7"/>
				{#each liveProfitByMonth.bars as bar, i}
					<rect x={bar.x} y={bar.profit >= 0 ? liveProfitByMonth.midY - bar.h : liveProfitByMonth.midY} width={liveProfitByMonth.bw} height={bar.h} rx="1" fill={bar.color}/>
					{#if i % Math.max(1, Math.floor(liveProfitByMonth.bars.length / 7)) === 0}
						<text x={bar.x + liveProfitByMonth.bw / 2} y={liveProfitByMonth.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{bar.mo}</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Monthly absolute profit (USDT) · green=profitable month · red=losing month · diverging from zero · reveals seasonal performance patterns and best/worst months across all bots</p>
		</section>
	{/if}
	{#if liveCumProfitByBot}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Cumulative Profit by Bot (USDT)</h3>
			<svg viewBox="0 0 {liveCumProfitByBot.W} {liveCumProfitByBot.H}" class="w-full" style="height:{liveCumProfitByBot.H}px">
				<line x1={liveCumProfitByBot.PAD} y1={liveCumProfitByBot.zeroY} x2={liveCumProfitByBot.W - liveCumProfitByBot.PAD} y2={liveCumProfitByBot.zeroY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each liveCumProfitByBot.polylines as line}
					<polyline points={line.points} fill="none" stroke={line.color} stroke-width="1.5" stroke-linejoin="round"/>
					<text x={liveCumProfitByBot.W - liveCumProfitByBot.PAD + 2} y={line.pts[line.pts.length - 1] ? liveCumProfitByBot.PAD + liveCumProfitByBot.polylines.indexOf(line) * 10 + 6 : 0} font-size="6" fill={line.color}>{line.bot}</text>
				{/each}
				<text x={liveCumProfitByBot.PAD} y={liveCumProfitByBot.H - 2} font-size="6" fill="var(--ch-axis-muted)">{liveCumProfitByBot.firstDate}</text>
				<text x={liveCumProfitByBot.W - liveCumProfitByBot.PAD} y={liveCumProfitByBot.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{liveCumProfitByBot.lastDate}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Cumulative absolute profit (USDT) per bot over time · each line = one bot · zero baseline · reveals which bots consistently grow and which stagnate or lose</p>
		</section>
	{/if}
	{#if livePairProfitDistribution}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Pair Avg Profit Distribution</h3>
			<svg viewBox="0 0 {livePairProfitDistribution.W} {livePairProfitDistribution.H}" class="w-full" style="height:{livePairProfitDistribution.H}px">
				<line x1={livePairProfitDistribution.zeroX} y1="0" x2={livePairProfitDistribution.zeroX} y2={livePairProfitDistribution.H - 14} stroke="var(--ch-axis-muted)" stroke-width="0.8" stroke-dasharray="3,2"/>
				{#each livePairProfitDistribution.bars as bar}
					<rect x={bar.x} y={livePairProfitDistribution.H - 14 - bar.h} width={livePairProfitDistribution.bw} height={bar.h} rx="1" fill={bar.color}/>
				{/each}
				<text x={livePairProfitDistribution.PAD} y={livePairProfitDistribution.H - 2} font-size="7" fill="var(--ch-axis)">{livePairProfitDistribution.mn}%</text>
				<text x={livePairProfitDistribution.W - livePairProfitDistribution.PAD} y={livePairProfitDistribution.H - 2} text-anchor="end" font-size="7" fill="var(--ch-axis)">{livePairProfitDistribution.mx}%</text>
				<text x={livePairProfitDistribution.W / 2} y={livePairProfitDistribution.H - 2} text-anchor="middle" font-size="7" fill="var(--ch-axis-muted)">n={livePairProfitDistribution.total} pairs</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Distribution of avg profit % per pair (min 2 trades) · green=positive avg · red=negative avg · zero line · reveals how many pairs are net profitable vs unprofitable</p>
		</section>
	{/if}
	{#if liveAvgProfitByDow}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Trade Profit % by Day of Week</h3>
			<svg viewBox="0 0 {liveAvgProfitByDow.W} {liveAvgProfitByDow.H}" class="w-full" style="height:{liveAvgProfitByDow.H}px">
				<line x1={liveAvgProfitByDow.PAD} y1={liveAvgProfitByDow.midY} x2={liveAvgProfitByDow.W - liveAvgProfitByDow.PAD} y2={liveAvgProfitByDow.midY} stroke="var(--ch-axis-faint)" stroke-width="0.7"/>
				{#each liveAvgProfitByDow.rows as row, i}
					{@const x = liveAvgProfitByDow.PAD + i * (liveAvgProfitByDow.bw + 2)}
					{@const bh = liveAvgProfitByDow.toH(row.avg)}
					{@const color = row.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					{@const y = row.avg >= 0 ? liveAvgProfitByDow.midY - bh : liveAvgProfitByDow.midY}
					<rect {x} {y} width={liveAvgProfitByDow.bw} height={Math.max(1, bh)} rx="1" fill={color}/>
					<text x={x + liveAvgProfitByDow.bw / 2} y={liveAvgProfitByDow.H - 1} text-anchor="middle" font-size="6.5" fill="var(--ch-axis)">{row.day}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg profit % per day-of-week (UTC open date) · green=positive · red=negative · reveals weekday patterns in live trade performance</p>
		</section>
	{/if}
	{#if liveCumProfitTimeline}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Cumulative Profit (USDT) Timeline</h3>
			<svg viewBox="0 0 {liveCumProfitTimeline.W} {liveCumProfitTimeline.H}" class="w-full" style="height:{liveCumProfitTimeline.H}px">
				<polygon points={liveCumProfitTimeline.area} fill={liveCumProfitTimeline.fillColor}/>
				<line x1={liveCumProfitTimeline.PAD} y1={liveCumProfitTimeline.zeroY} x2={liveCumProfitTimeline.W - liveCumProfitTimeline.PAD} y2={liveCumProfitTimeline.zeroY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				<polyline points={liveCumProfitTimeline.polyline} fill="none" stroke={liveCumProfitTimeline.color} stroke-width="1.5" stroke-linejoin="round"/>
				<text x={liveCumProfitTimeline.W - liveCumProfitTimeline.PAD} y={liveCumProfitTimeline.PAD + 6} text-anchor="end" font-size="7" fill={liveCumProfitTimeline.color}>{liveCumProfitTimeline.last} USDT</text>
				<text x={liveCumProfitTimeline.PAD} y={liveCumProfitTimeline.H - 2} font-size="6" fill="var(--ch-axis-muted)">oldest trade →</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Cumulative realized profit in USDT across all live trades sorted by close date · green=net positive · red=net negative · shows overall account equity curve</p>
		</section>
	{/if}
	{#if liveProfitVsDurationScatter}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Trade Profit % vs Hold Duration (hours)</h3>
			<svg viewBox="0 0 {liveProfitVsDurationScatter.W} {liveProfitVsDurationScatter.H}" class="w-full" style="height:{liveProfitVsDurationScatter.H}px">
				<line x1={liveProfitVsDurationScatter.PAD} y1={liveProfitVsDurationScatter.zeroY} x2={liveProfitVsDurationScatter.W - liveProfitVsDurationScatter.PAD} y2={liveProfitVsDurationScatter.zeroY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				<line x1={liveProfitVsDurationScatter.PAD} y1={liveProfitVsDurationScatter.PAD} x2={liveProfitVsDurationScatter.PAD} y2={liveProfitVsDurationScatter.H - liveProfitVsDurationScatter.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.7"/>
				{#each liveProfitVsDurationScatter.pts as p}
					{@const cx = liveProfitVsDurationScatter.toX(p.dur)}
					{@const cy = liveProfitVsDurationScatter.toY(p.profit)}
					{@const col = p.profit >= 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'}
					<circle {cx} {cy} r="1.8" fill={col}/>
				{/each}
				<text x={liveProfitVsDurationScatter.PAD} y={liveProfitVsDurationScatter.PAD + 6} font-size="6" fill="var(--ch-axis-muted)">+{liveProfitVsDurationScatter.profMax}%</text>
				<text x={liveProfitVsDurationScatter.W - liveProfitVsDurationScatter.PAD} y={liveProfitVsDurationScatter.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{liveProfitVsDurationScatter.durMax}h</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Scatter of trade profit % (Y) vs hold duration in hours (X) · green=win · red=loss · reveals if longer holds produce better returns or if quick exits are more profitable</p>
		</section>
	{/if}
	{#if livePairSharpeRanking}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Pair Avg Profit% Ranking</h3>
			<svg viewBox="0 0 {livePairSharpeRanking.W} {livePairSharpeRanking.H}" class="w-full" style="height:{livePairSharpeRanking.H}px">
				<line x1={livePairSharpeRanking.zeroX} y1="0" x2={livePairSharpeRanking.zeroX} y2={livePairSharpeRanking.H} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each livePairSharpeRanking.rows as row, i}
					{@const y = livePairSharpeRanking.PAD + i * 16}
					{@const bw = Math.max(2, (Math.abs(row.avg) / livePairSharpeRanking.maxAbs) * (livePairSharpeRanking.barMaxW / 2))}
					{@const x = row.avg >= 0 ? livePairSharpeRanking.zeroX : livePairSharpeRanking.zeroX - bw}
					{@const color = row.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect {x} {y} width={bw} height="12" rx="1" fill={color}/>
					<text x={livePairSharpeRanking.PAD} y={y + 10} font-size="6.5" fill="var(--ch-axis-strong)">{row.pair}</text>
					<text x={row.avg >= 0 ? livePairSharpeRanking.zeroX + bw + 2 : livePairSharpeRanking.zeroX - bw - 2} y={y + 10} text-anchor={row.avg >= 0 ? 'start' : 'end'} font-size="6.5" fill={color}>{row.avg.toFixed(2)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Pairs ranked by avg profit% per trade (min 3 trades) · green=positive · red=negative · diverging from zero center line · identifies best and worst performing pairs</p>
		</section>
	{/if}
	{#if liveBotProfitByPairCount}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Bot Profit vs Pair Count Scatter</h3>
			<svg viewBox="0 0 {liveBotProfitByPairCount.W} {liveBotProfitByPairCount.H}" class="w-full" style="height:{liveBotProfitByPairCount.H}px">
				<line x1={liveBotProfitByPairCount.PAD} y1={liveBotProfitByPairCount.zeroY} x2={liveBotProfitByPairCount.W - liveBotProfitByPairCount.PAD} y2={liveBotProfitByPairCount.zeroY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each liveBotProfitByPairCount.pts as p}
					{@const cx = liveBotProfitByPairCount.toX(p.x)}
					{@const cy = liveBotProfitByPairCount.toY(p.y)}
					{@const col = p.y >= 0 ? 'var(--ch-violet)' : 'var(--ch-loss)'}
					<circle {cx} {cy} r="4" fill={col}/>
					<text x={cx} y={cy - 5} text-anchor="middle" font-size="6" fill="var(--ch-axis-strong)">{p.bot}</text>
				{/each}
				<text x={liveBotProfitByPairCount.PAD} y={liveBotProfitByPairCount.H - 2} font-size="6" fill="var(--ch-axis-muted)">1 pair</text>
				<text x={liveBotProfitByPairCount.W - liveBotProfitByPairCount.PAD} y={liveBotProfitByPairCount.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{liveBotProfitByPairCount.xMax} pairs</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Scatter of each bot's total USDT profit (Y) vs number of unique pairs traded (X) · reveals whether more pair diversity correlates with better outcomes</p>
		</section>
	{/if}
	{#if liveHoldTimeTrend}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Monthly Avg Hold Time Trend</h3>
			<svg viewBox="0 0 {liveHoldTimeTrend.W} {liveHoldTimeTrend.H}" class="w-full" style="height:{liveHoldTimeTrend.H}px">
				<polyline points={liveHoldTimeTrend.polyline} fill="none" stroke="var(--ch-violet)" stroke-width="1.5" stroke-linejoin="round"/>
				{#each liveHoldTimeTrend.pts as p, i}
					<circle cx={liveHoldTimeTrend.toX(i)} cy={liveHoldTimeTrend.toY(p.avg)} r="2.5" fill="var(--ch-violet)"/>
				{/each}
				<text x={liveHoldTimeTrend.PAD} y={liveHoldTimeTrend.H - 2} font-size="6" fill="var(--ch-axis-muted)">{liveHoldTimeTrend.firstMo}</text>
				<text x={liveHoldTimeTrend.W - liveHoldTimeTrend.PAD} y={liveHoldTimeTrend.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{liveHoldTimeTrend.lastMo}</text>
				<text x={liveHoldTimeTrend.PAD} y={liveHoldTimeTrend.PAD + 7} font-size="7" fill="var(--ch-violet-strong)">{liveHoldTimeTrend.maxV}h</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Monthly avg trade hold time in hours · indigo line with dots · rising trend may indicate strategy shifting to longer-term holds or fewer opportunities in ranging markets</p>
		</section>
	{/if}
	{#if liveTradeCountByBot}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Trade Count by Bot</h3>
			<svg viewBox="0 0 {liveTradeCountByBot.W} {liveTradeCountByBot.H}" class="w-full" style="height:{liveTradeCountByBot.H}px">
				{#each liveTradeCountByBot.rows as row, i}
					{@const y = liveTradeCountByBot.PAD + i * 16}
					{@const bw = Math.max(2, (row.count / liveTradeCountByBot.maxCount) * liveTradeCountByBot.barMaxW)}
					<text x={liveTradeCountByBot.PAD} y={y + 11} font-size="6.5" fill="var(--ch-axis-strong)">{row.bot}</text>
					<rect x={liveTradeCountByBot.PAD + 98} {y} width={bw} height="12" rx="1" fill="var(--ch-profit)"/>
					<text x={liveTradeCountByBot.PAD + 98 + bw + 3} y={y + 11} font-size="6.5" fill="var(--ch-profit-strong)">{row.count}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Total trade count per bot instance · green bars · identifies most active bots and highlights imbalances in trading activity across the fleet</p>
		</section>
	{/if}
	{#if liveProfitByPairGroup}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Profit% by Pair Group</h3>
			<svg viewBox="0 0 {liveProfitByPairGroup.W} {liveProfitByPairGroup.H}" class="w-full" style="height:{liveProfitByPairGroup.H}px">
				<line x1={liveProfitByPairGroup.zeroX} y1="0" x2={liveProfitByPairGroup.zeroX} y2={liveProfitByPairGroup.H} stroke="var(--ch-axis-faint)" stroke-width="1"/>
				{#each liveProfitByPairGroup.rows as row, i}
					{@const y = liveProfitByPairGroup.PAD + i * 22}
					{@const bw = Math.max(2, (Math.abs(row.avg) / liveProfitByPairGroup.maxAbs) * (liveProfitByPairGroup.barMaxW / 2))}
					{@const x = row.avg >= 0 ? liveProfitByPairGroup.zeroX : liveProfitByPairGroup.zeroX - bw}
					{@const color = row.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect {x} {y} width={bw} height="14" rx="2" fill={color}/>
					<text x={liveProfitByPairGroup.PAD} y={y + 10} font-size="7.5" fill="var(--ch-axis-strong)">{row.grp}</text>
					<text x={row.avg >= 0 ? liveProfitByPairGroup.zeroX + bw + 2 : liveProfitByPairGroup.zeroX - bw - 2} y={y + 10} text-anchor={row.avg >= 0 ? 'start' : 'end'} font-size="6.5" fill={color}>{row.avg.toFixed(2)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg profit% grouped by base asset (BTC/ETH/SOL/BNB/Other) · diverging bars · reveals which asset classes are performing best across all live trades</p>
		</section>
	{/if}
	{#if liveWinStreakDistribution}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Win/Loss Streak Summary</h3>
			<svg viewBox="0 0 {liveWinStreakDistribution.W} {liveWinStreakDistribution.H}" class="w-full" style="height:{liveWinStreakDistribution.H}px">
				<text x="8" y="16" font-size="8" fill="var(--ch-axis-strong)">Win streaks: {liveWinStreakDistribution.wins}</text>
				<text x="8" y="28" font-size="8" fill="var(--ch-axis-strong)">Loss streaks: {liveWinStreakDistribution.losses}</text>
				<text x="8" y="42" font-size="9.5" font-weight="600" fill="var(--ch-profit-strong)">Avg win streak: {liveWinStreakDistribution.avgWin}</text>
				<text x="8" y="54" font-size="9.5" font-weight="600" fill="var(--ch-loss-strong)">Avg loss streak: {liveWinStreakDistribution.avgLoss}</text>
				<rect x={liveWinStreakDistribution.midX} y="36" width={liveWinStreakDistribution.winBarW} height="10" rx="2" fill="var(--ch-profit-light)"/>
				<rect x={liveWinStreakDistribution.midX - liveWinStreakDistribution.lossBarW} y="48" width={liveWinStreakDistribution.lossBarW} height="10" rx="2" fill="var(--ch-loss-light)"/>
				<text x={liveWinStreakDistribution.midX + liveWinStreakDistribution.winBarW + 3} y="44" font-size="7" fill="var(--ch-profit-strong)">max {liveWinStreakDistribution.maxWin}</text>
				<text x={liveWinStreakDistribution.midX - liveWinStreakDistribution.lossBarW - 3} y="56" text-anchor="end" font-size="7" fill="var(--ch-loss-strong)">max {liveWinStreakDistribution.maxLoss}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Win/loss streak analysis · counts distinct streaks and shows avg + max · long avg loss streaks indicate possible mean-reversion risk or strategy degradation</p>
		</section>
	{/if}
	{#if liveProfitVolatility}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Rolling Profit Volatility (10-Trade Window)</h3>
			<svg viewBox="0 0 {liveProfitVolatility.W} {liveProfitVolatility.H}" class="w-full" style="height:{liveProfitVolatility.H}px">
				<polyline points={liveProfitVolatility.polyline} fill="none" stroke="var(--ch-warn)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={liveProfitVolatility.W - liveProfitVolatility.PAD} y={liveProfitVolatility.PAD + 8} text-anchor="end" font-size="7" fill="var(--ch-warn)">σ={liveProfitVolatility.lastVol}%</text>
				<text x={liveProfitVolatility.PAD} y={liveProfitVolatility.PAD + 8} font-size="6" fill="var(--ch-axis-muted)">max σ {liveProfitVolatility.maxVol}%</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Rolling 10-trade profit% standard deviation · orange line · rising volatility indicates unstable returns · falling indicates more consistent performance over time</p>
		</section>
	{/if}
	{#if livePairCountVsProfit}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Pair Count vs Avg Profit% (by Bot)</h3>
			<svg viewBox="0 0 {livePairCountVsProfit.W} {livePairCountVsProfit.H}" class="w-full" style="height:{livePairCountVsProfit.H}px">
				<line x1={livePairCountVsProfit.PAD} y1={livePairCountVsProfit.zeroY} x2={livePairCountVsProfit.W - livePairCountVsProfit.PAD} y2={livePairCountVsProfit.zeroY} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				{#each livePairCountVsProfit.pts as p}
					{@const cx = livePairCountVsProfit.toX(p.pairCount)}
					{@const cy = livePairCountVsProfit.toY(p.avgProfit)}
					{@const color = p.avgProfit >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<circle {cx} {cy} r="3.5" fill={color}/>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Scatter of unique pair count (X) vs avg profit% (Y) per bot · green=profitable · red=loss · reveals if bots with more pairs perform better or suffer from over-diversification</p>
		</section>
	{/if}
	{#if liveProfitByExitType}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Profit% by Exit Reason</h3>
			<svg viewBox="0 0 {liveProfitByExitType.W} {liveProfitByExitType.H}" class="w-full" style="height:{liveProfitByExitType.H}px">
				<line x1={liveProfitByExitType.zeroX} y1="0" x2={liveProfitByExitType.zeroX} y2={liveProfitByExitType.H} stroke="var(--ch-axis-faint)" stroke-width="1"/>
				{#each liveProfitByExitType.rows as row, i}
					{@const y = liveProfitByExitType.PAD + i * 20}
					{@const bw = Math.max(2, (Math.abs(row.avg) / liveProfitByExitType.maxAbs) * (liveProfitByExitType.barMaxW / 2))}
					{@const x = row.avg >= 0 ? liveProfitByExitType.zeroX : liveProfitByExitType.zeroX - bw}
					{@const color = row.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect {x} {y} width={bw} height="13" rx="2" fill={color}/>
					<text x={liveProfitByExitType.PAD} y={y + 10} font-size="6.5" fill="var(--ch-axis-strong)">{row.reason}</text>
					<text x={row.avg >= 0 ? liveProfitByExitType.zeroX + bw + 2 : liveProfitByExitType.zeroX - bw - 2} y={y + 10} text-anchor={row.avg >= 0 ? 'start' : 'end'} font-size="6" fill={color}>{row.avg.toFixed(2)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg profit% grouped by exit reason · green=positive · red=negative · diverging from zero · stop_loss exits with positive avg are rare flag for review</p>
		</section>
	{/if}
	{#if liveMonthlyProfitCDF}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Monthly Total Profit% (Sum)</h3>
			<svg viewBox="0 0 {liveMonthlyProfitCDF.W} {liveMonthlyProfitCDF.H}" class="w-full" style="height:{liveMonthlyProfitCDF.H}px">
				<line x1={liveMonthlyProfitCDF.PAD} y1={liveMonthlyProfitCDF.midY} x2={liveMonthlyProfitCDF.W - liveMonthlyProfitCDF.PAD} y2={liveMonthlyProfitCDF.midY} stroke="var(--ch-axis-faint)" stroke-width="1"/>
				{#each liveMonthlyProfitCDF.pts as p, i}
					{@const x = liveMonthlyProfitCDF.PAD + i * (liveMonthlyProfitCDF.bw + 1)}
					{@const bh = Math.max(1, (Math.abs(p.sum) / Math.max(Math.abs(liveMonthlyProfitCDF.minSum), liveMonthlyProfitCDF.maxSum)) * (liveMonthlyProfitCDF.H / 2 - liveMonthlyProfitCDF.PAD))}
					{@const y = p.sum >= 0 ? liveMonthlyProfitCDF.midY - bh : liveMonthlyProfitCDF.midY}
					{@const color = p.sum >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect {x} {y} width={liveMonthlyProfitCDF.bw} height={bh} rx="1" fill={color}/>
					{#if i % 3 === 0}
						<text x={x + liveMonthlyProfitCDF.bw / 2} y={liveMonthlyProfitCDF.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{p.m}</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Monthly total profit% sum across all live trades · green=positive · red=negative · diverging bars · shows which months were net profitable vs loss-making</p>
		</section>
	{/if}
	{#if liveTradeCountHistogram}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Trade Duration Distribution (Hours)</h3>
			<svg viewBox="0 0 {liveTradeCountHistogram.W} {liveTradeCountHistogram.H}" class="w-full" style="height:{liveTradeCountHistogram.H}px">
				{#each liveTradeCountHistogram.counts as count, i}
					{@const x = liveTradeCountHistogram.PAD + i * (liveTradeCountHistogram.bw + 1)}
					{@const bh = Math.max(1, (count / liveTradeCountHistogram.maxCount) * (liveTradeCountHistogram.H - liveTradeCountHistogram.PAD * 2))}
					{@const y = liveTradeCountHistogram.H - liveTradeCountHistogram.PAD - bh}
					{@const binMid = (i + 0.5) * liveTradeCountHistogram.step}
					{@const color = binMid < 24 ? 'var(--ch-profit)' : binMid < 72 ? 'var(--ch-teal)' : binMid < 168 ? 'var(--ch-warn)' : 'var(--ch-loss-light)'}
					<rect {x} {y} width={liveTradeCountHistogram.bw} height={bh} rx="1" style="fill:{color}"/>
				{/each}
				<text x={liveTradeCountHistogram.PAD} y={liveTradeCountHistogram.H - 1} font-size="6" fill="var(--ch-axis-muted)">0h</text>
				<text x={liveTradeCountHistogram.W - liveTradeCountHistogram.PAD} y={liveTradeCountHistogram.H - 1} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{liveTradeCountHistogram.maxV}h</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">12-bin histogram of live trade hold durations in hours · green&lt;24h · teal 24-72h · yellow 72-168h · red&gt;168h · reveals if strategy tends to hold short or long</p>
		</section>
	{/if}
	{#if liveAvgProfitByStakeBucket}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Profit% by Stake Size Bucket</h3>
			<svg viewBox="0 0 {liveAvgProfitByStakeBucket.W} {liveAvgProfitByStakeBucket.H}" class="w-full" style="height:{liveAvgProfitByStakeBucket.H}px">
				<line x1={liveAvgProfitByStakeBucket.zeroX} y1="0" x2={liveAvgProfitByStakeBucket.zeroX} y2={liveAvgProfitByStakeBucket.H} stroke="var(--ch-axis-faint)" stroke-width="1"/>
				{#each liveAvgProfitByStakeBucket.rows as row, i}
					{@const y = liveAvgProfitByStakeBucket.PAD + i * 20}
					{@const bw = Math.max(2, (Math.abs(row.avg) / liveAvgProfitByStakeBucket.maxAbs) * ((liveAvgProfitByStakeBucket.barMaxW - 55) / 2))}
					{@const x = row.avg >= 0 ? liveAvgProfitByStakeBucket.zeroX : liveAvgProfitByStakeBucket.zeroX - bw}
					{@const color = row.avg >= 0 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					<text x={liveAvgProfitByStakeBucket.PAD} y={y + 12} font-size="7.5" fill="var(--ch-axis-strong)">{row.k}</text>
					<rect {x} {y} width={bw} height="13" rx="2" fill={color}/>
					<text x={row.avg >= 0 ? liveAvgProfitByStakeBucket.zeroX + bw + 2 : liveAvgProfitByStakeBucket.zeroX - bw - 2} y={y + 12} text-anchor={row.avg >= 0 ? 'start' : 'end'} font-size="6" fill={color}>{row.avg.toFixed(2)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg profit% by stake size bucket (USDT) · teal=positive · red=negative · larger stakes with positive avg = DCA scaling working · negative = oversized positions underperforming</p>
		</section>
	{/if}
	{#if liveBotWinRateRanking}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Win Rate% by Bot (Live)</h3>
			<svg viewBox="0 0 {liveBotWinRateRanking.W} {liveBotWinRateRanking.H}" class="w-full" style="height:{liveBotWinRateRanking.H}px">
				{#each liveBotWinRateRanking.rows as row, i}
					{@const y = liveBotWinRateRanking.PAD + i * 18}
					{@const bw = Math.max(2, (row.wr / 100) * liveBotWinRateRanking.barMaxW)}
					{@const color = row.wr >= 60 ? 'var(--ch-profit)' : row.wr >= 50 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					<text x={liveBotWinRateRanking.PAD} y={y + 12} font-size="7" fill="var(--ch-axis-strong)">{row.bot}</text>
					<rect x={liveBotWinRateRanking.PAD + 80} {y} width={bw} height="13" rx="2" fill={color}/>
					<text x={liveBotWinRateRanking.PAD + 80 + bw + 3} y={y + 12} font-size="6.5" fill={color}>{row.wr.toFixed(1)}% ({row.total})</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Win rate% per live bot · green≥60% · teal 50-60% · red&lt;50% · bots with low win rate may need parameter tuning or pair changes</p>
		</section>
	{/if}
	{#if liveMonthlyAvgProfitPct}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Trade Profit% by Month (Live)</h3>
			<svg viewBox="0 0 {liveMonthlyAvgProfitPct.W} {liveMonthlyAvgProfitPct.H}" class="w-full" style="height:{liveMonthlyAvgProfitPct.H}px">
				<line x1={liveMonthlyAvgProfitPct.PAD} y1={liveMonthlyAvgProfitPct.midY} x2={liveMonthlyAvgProfitPct.W - liveMonthlyAvgProfitPct.PAD} y2={liveMonthlyAvgProfitPct.midY} stroke="var(--ch-axis-faint)" stroke-width="1"/>
				{#each liveMonthlyAvgProfitPct.avgs as avg, i}
					{@const x = liveMonthlyAvgProfitPct.PAD + i * (liveMonthlyAvgProfitPct.bw + 1)}
					{@const bh = Math.max(1, (Math.abs(avg) / liveMonthlyAvgProfitPct.maxAbs) * (liveMonthlyAvgProfitPct.H / 2 - liveMonthlyAvgProfitPct.PAD))}
					{@const y = avg >= 0 ? liveMonthlyAvgProfitPct.midY - bh : liveMonthlyAvgProfitPct.midY}
					{@const color = avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect {x} {y} width={liveMonthlyAvgProfitPct.bw} height={bh} rx="1" fill={color}/>
					{#if i % 3 === 0}
						<text x={x + liveMonthlyAvgProfitPct.bw / 2} y={liveMonthlyAvgProfitPct.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{liveMonthlyAvgProfitPct.months[i].slice(5)}</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Monthly avg trade profit% · green=positive · red=negative · diverging from zero · shows seasonal profit patterns across live trading history</p>
		</section>
	{/if}
	{#if livePairWinRateCDF}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Pair Win Rate% CDF (Live)</h3>
			<svg viewBox="0 0 {livePairWinRateCDF.W} {livePairWinRateCDF.H}" class="w-full" style="height:{livePairWinRateCDF.H}px">
				<line x1={livePairWinRateCDF.zeroX} y1={livePairWinRateCDF.PAD} x2={livePairWinRateCDF.zeroX} y2={livePairWinRateCDF.H - livePairWinRateCDF.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				<polyline points={livePairWinRateCDF.polyline} fill="none" stroke="var(--ch-teal-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={livePairWinRateCDF.PAD} y={livePairWinRateCDF.H - 2} font-size="6" fill="var(--ch-axis-muted)">{livePairWinRateCDF.minV}%</text>
				<text x={livePairWinRateCDF.W - livePairWinRateCDF.PAD} y={livePairWinRateCDF.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{livePairWinRateCDF.maxV}%</text>
				<text x={livePairWinRateCDF.W / 2} y={livePairWinRateCDF.PAD + 8} text-anchor="middle" font-size="7" fill="var(--ch-teal-strong)">median {livePairWinRateCDF.median}%</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">CDF of win rate% per trading pair (≥2 trades) · teal S-curve · dashed 50% line · right-skewed = most pairs are profitable more than half the time</p>
		</section>
	{/if}
	{#if liveDurationByBot}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Trade Duration (Hours) by Bot</h3>
			<svg viewBox="0 0 {liveDurationByBot.W} {liveDurationByBot.H}" class="w-full" style="height:{liveDurationByBot.H}px">
				{#each liveDurationByBot.rows as row, i}
					{@const y = liveDurationByBot.PAD + i * 18}
					{@const bw = Math.max(2, (row.avg / liveDurationByBot.maxAvg) * liveDurationByBot.barMaxW)}
					{@const color = row.avg <= 4 ? 'var(--ch-profit)' : row.avg <= 24 ? 'var(--ch-warn)' : 'var(--ch-loss)'}
					<text x={liveDurationByBot.PAD} y={y + 12} font-size="7" fill="var(--ch-axis-strong)">{row.name}</text>
					<rect x={liveDurationByBot.PAD + 80} {y} width={bw} height="13" rx="2" fill={color}/>
					<text x={liveDurationByBot.PAD + 80 + bw + 3} y={y + 12} font-size="6.5" fill={color}>{row.avg.toFixed(1)}h</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg trade duration in hours per live bot · green≤4h · yellow≤24h · red&gt;24h · longer durations = positions held through more volatility = higher risk exposure</p>
		</section>
	{/if}
	{#if liveCalmarByBot}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Calmar Ratio by Live Bot</h3>
			<svg viewBox="0 0 {liveCalmarByBot.W} {liveCalmarByBot.H}" class="w-full" style="height:{liveCalmarByBot.H}px">
				<line x1={liveCalmarByBot.zeroX} y1="0" x2={liveCalmarByBot.zeroX} y2={liveCalmarByBot.H} stroke="var(--ch-axis-faint)" stroke-width="0.8"/>
				{#each liveCalmarByBot.rows as row, i}
					{@const y = liveCalmarByBot.PAD + i * 18}
					{@const bw = Math.max(2, (Math.abs(row.calmar) / liveCalmarByBot.maxAbs) * (liveCalmarByBot.barMaxW / 2))}
					{@const x = row.calmar >= 0 ? liveCalmarByBot.zeroX : liveCalmarByBot.zeroX - bw}
					{@const color = row.calmar >= 1 ? 'var(--ch-profit)' : row.calmar >= 0 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					<text x={liveCalmarByBot.PAD} y={y + 12} font-size="7" fill="var(--ch-axis-strong)">{row.name}</text>
					<rect {x} {y} width={bw} height="13" rx="2" fill={color}/>
					<text x={row.calmar >= 0 ? liveCalmarByBot.zeroX + bw + 2 : liveCalmarByBot.zeroX - bw - 2} y={y + 12} text-anchor={row.calmar >= 0 ? 'start' : 'end'} font-size="6" fill={color}>{row.calmar.toFixed(2)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Calmar ratio (total profit% / max single-trade DD%) per live bot · green≥1 · teal≥0 · red&lt;0 · identifies which bots generate the best return per unit of drawdown risk</p>
		</section>
	{/if}
	{#if liveProfitCDF}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Trade Profit% CDF (Live)</h3>
			<svg viewBox="0 0 {liveProfitCDF.W} {liveProfitCDF.H}" class="w-full" style="height:{liveProfitCDF.H}px">
				<line x1={liveProfitCDF.zeroX} y1={liveProfitCDF.PAD} x2={liveProfitCDF.zeroX} y2={liveProfitCDF.H - liveProfitCDF.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.7" stroke-dasharray="3,2"/>
				<polyline points={liveProfitCDF.polyline} fill="none" stroke="var(--ch-profit-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={liveProfitCDF.PAD} y={liveProfitCDF.H - 2} font-size="6" fill="var(--ch-axis-muted)">{liveProfitCDF.minV}%</text>
				<text x={liveProfitCDF.W - liveProfitCDF.PAD} y={liveProfitCDF.H - 2} text-anchor="end" font-size="6" fill="var(--ch-axis-muted)">{liveProfitCDF.maxV}%</text>
				<text x={liveProfitCDF.W / 2} y={liveProfitCDF.PAD + 8} text-anchor="middle" font-size="7" fill="var(--ch-profit-strong)">median {liveProfitCDF.median}%</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">CDF of individual trade profit% across all live trades · green S-curve · dashed zero line · right-skewed = most trades profitable · fat right tail = occasional outsized winners</p>
		</section>
	{/if}
	{#if liveAvgProfitByPairGroup}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Avg Profit% by Base Asset</h3>
			<svg viewBox="0 0 {liveAvgProfitByPairGroup.W} {liveAvgProfitByPairGroup.H}" class="w-full" style="height:{liveAvgProfitByPairGroup.H}px">
				<line x1={liveAvgProfitByPairGroup.zeroX} y1={0} x2={liveAvgProfitByPairGroup.zeroX} y2={liveAvgProfitByPairGroup.H} stroke="var(--ch-axis-muted)" stroke-width="0.5"/>
				{#each liveAvgProfitByPairGroup.rows as row, i}
					{@const y = liveAvgProfitByPairGroup.PAD + i * 18}
					{@const bw = Math.max(2, (Math.abs(row.avg) / liveAvgProfitByPairGroup.maxAbs) * (liveAvgProfitByPairGroup.barMaxW / 2))}
					{@const x = row.avg >= 0 ? liveAvgProfitByPairGroup.zeroX : liveAvgProfitByPairGroup.zeroX - bw}
					{@const color = row.avg >= 0.5 ? 'var(--ch-profit)' : row.avg >= 0 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					<text x={liveAvgProfitByPairGroup.PAD} y={y + 12} font-size="7.5" fill="var(--ch-axis-strong)">{row.base}</text>
					<rect {x} {y} width={bw} height="13" rx="2" fill={color}/>
					<text x={row.avg >= 0 ? liveAvgProfitByPairGroup.zeroX + bw + 2 : liveAvgProfitByPairGroup.zeroX - bw - 2} y={y + 11} text-anchor={row.avg >= 0 ? 'start' : 'end'} font-size="6" fill={color}>{row.avg.toFixed(2)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg trade profit% per base asset (BTC, ETH, SOL…) · green=positive · red=negative · identifies which assets are driving live performance vs dragging it down</p>
		</section>
	{/if}
	{#if liveTradeHoldTimeDistribution}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Hold Time Distribution (hours)</h3>
			<svg viewBox="0 0 {liveTradeHoldTimeDistribution.W} {liveTradeHoldTimeDistribution.H}" class="w-full" style="height:{liveTradeHoldTimeDistribution.H}px">
				{#each liveTradeHoldTimeDistribution.counts as count, i}
					{@const x = liveTradeHoldTimeDistribution.PAD + i * (liveTradeHoldTimeDistribution.bw + 1)}
					{@const barH = Math.max(2, (count / liveTradeHoldTimeDistribution.maxCount) * (liveTradeHoldTimeDistribution.H - 18))}
					{@const y = liveTradeHoldTimeDistribution.H - barH - 8}
					{@const color = count >= liveTradeHoldTimeDistribution.maxCount * 0.7 ? 'var(--ch-teal-strong)' : count >= liveTradeHoldTimeDistribution.maxCount * 0.3 ? 'var(--ch-violet)' : 'var(--ch-axis-muted)'}
					<rect {x} {y} width={liveTradeHoldTimeDistribution.bw} height={barH} rx="1" fill={color}/>
					<text x={x + liveTradeHoldTimeDistribution.bw / 2} y={liveTradeHoldTimeDistribution.H - 1} text-anchor="middle" font-size="5.5" fill="var(--ch-axis)">{(i * liveTradeHoldTimeDistribution.bw_val).toFixed(0)}h</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Histogram of live trade hold time in hours · teal = most frequent bucket · right-skewed = occasional long holds · majority of trades close quickly → intraday strategy</p>
		</section>
	{/if}
	{#if livePairSortinoRanking}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Sortino Ratio by Base Asset</h3>
			<svg viewBox="0 0 {livePairSortinoRanking.W} {livePairSortinoRanking.H}" class="w-full" style="height:{livePairSortinoRanking.H}px">
				<line x1={livePairSortinoRanking.zeroX} y1={0} x2={livePairSortinoRanking.zeroX} y2={livePairSortinoRanking.H} stroke="var(--ch-axis-muted)" stroke-width="0.5"/>
				{#each livePairSortinoRanking.rows as row, i}
					{@const y = livePairSortinoRanking.PAD + i * 20}
					{@const bw = Math.max(2, (Math.abs(row.sortino) / livePairSortinoRanking.maxAbs) * (livePairSortinoRanking.barMaxW / 2))}
					{@const x = row.sortino >= 0 ? livePairSortinoRanking.zeroX : livePairSortinoRanking.zeroX - bw}
					{@const color = row.sortino >= 2 ? 'var(--ch-profit)' : row.sortino >= 0 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					<text x={livePairSortinoRanking.PAD} y={y + 13} font-size="7.5" fill="var(--ch-axis-strong)">{row.pair}</text>
					<rect {x} {y} width={bw} height="14" rx="2" fill={color}/>
					<text x={row.sortino >= 0 ? livePairSortinoRanking.zeroX + bw + 2 : livePairSortinoRanking.zeroX - bw - 2} y={y + 11} text-anchor={row.sortino >= 0 ? 'start' : 'end'} font-size="6.5" fill={color}>{row.sortino.toFixed(2)}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Sortino ratio per base asset across live trades · green≥2 · teal≥0 · red&lt;0 · penalises only downside volatility — identifies assets with best risk-adjusted live returns</p>
		</section>
	{/if}
	{#if liveMonthlyWinRateTrend}
		<section class="rounded-xl border border-border bg-card p-4">
			<h3 class="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Monthly Win Rate% Trend (Live)</h3>
			<svg viewBox="0 0 {liveMonthlyWinRateTrend.W} {liveMonthlyWinRateTrend.H}" class="w-full" style="height:{liveMonthlyWinRateTrend.H}px">
				<polyline points={liveMonthlyWinRateTrend.polyline} fill="none" stroke="var(--ch-profit-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				{#each liveMonthlyWinRateTrend.pts as p, i}
					{#if i % Math.max(1, Math.floor(liveMonthlyWinRateTrend.pts.length / 6)) === 0}
						<text x={liveMonthlyWinRateTrend.toX(i).toFixed(1)} y={liveMonthlyWinRateTrend.H} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{p.mo}</text>
					{/if}
				{/each}
				<text x={liveMonthlyWinRateTrend.PAD} y={liveMonthlyWinRateTrend.PAD + 8} font-size="6" fill="var(--ch-profit)">{liveMonthlyWinRateTrend.maxV}%</text>
				<text x={liveMonthlyWinRateTrend.PAD} y={liveMonthlyWinRateTrend.H - liveMonthlyWinRateTrend.PAD - 2} font-size="6" fill="var(--ch-axis-muted)">{liveMonthlyWinRateTrend.minV}%</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Monthly win rate% trend across live trades · green line · rising = improving entry quality · falling = signal decay or unfavourable market regime</p>
		</section>
	{/if}
	{#if liveProfitFactorByDow}
		<section class="rounded-lg border border-border bg-card p-3">
			<h3 class="mb-1 text-xs font-semibold text-muted-foreground">Avg Profit% by Day of Week (Live)</h3>
			<svg viewBox={`0 0 ${liveProfitFactorByDow.W} ${liveProfitFactorByDow.H}`} width="100%" style="height:70px">
				<line x1={liveProfitFactorByDow.PAD} y1={liveProfitFactorByDow.midY} x2={liveProfitFactorByDow.W - liveProfitFactorByDow.PAD} y2={liveProfitFactorByDow.midY} stroke="var(--ch-axis-faint)" stroke-width="0.5" stroke-dasharray="2,2"/>
				{#each liveProfitFactorByDow.bars as b, i}
					{@const bh = (Math.abs(b.avg) / liveProfitFactorByDow.maxAbs) * (liveProfitFactorByDow.midY - liveProfitFactorByDow.PAD)}
					{@const x = liveProfitFactorByDow.PAD + i * (liveProfitFactorByDow.bw + 2)}
					{@const y = b.avg >= 0 ? liveProfitFactorByDow.midY - bh : liveProfitFactorByDow.midY}
					{@const color = b.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect {x} {y} width={liveProfitFactorByDow.bw} height={bh} fill={color} rx="1"/>
					<text x={x + liveProfitFactorByDow.bw / 2} y={liveProfitFactorByDow.H} text-anchor="middle" font-size="6" fill="var(--ch-axis)">{b.label}</text>
					<text x={x + liveProfitFactorByDow.bw / 2} y={b.avg >= 0 ? y - 2 : y + bh + 7} text-anchor="middle" font-size="5.5" fill={color}>{b.avg.toFixed(2)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg profit% by entry day of week · green=positive · red=negative · identifies which weekdays produce better live trade outcomes</p>
		</section>
	{/if}
	{#if liveStakeAmountCDF}
		<section class="rounded-lg border border-border bg-card p-3">
			<h3 class="mb-1 text-xs font-semibold text-muted-foreground">Stake Amount CDF (Live)</h3>
			<svg viewBox={`0 0 ${liveStakeAmountCDF.W} ${liveStakeAmountCDF.H}`} width="100%" style="height:70px">
				<line x1={liveStakeAmountCDF.PAD} y1={liveStakeAmountCDF.H - liveStakeAmountCDF.PAD} x2={liveStakeAmountCDF.W - liveStakeAmountCDF.PAD} y2={liveStakeAmountCDF.H - liveStakeAmountCDF.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.5"/>
				<polyline points={liveStakeAmountCDF.polyline} fill="none" stroke="var(--ch-violet)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={liveStakeAmountCDF.PAD} y={liveStakeAmountCDF.H - 2} font-size="5.5" fill="var(--ch-axis-muted)">{liveStakeAmountCDF.minV}</text>
				<text x={liveStakeAmountCDF.W - liveStakeAmountCDF.PAD} y={liveStakeAmountCDF.H - 2} text-anchor="end" font-size="5.5" fill="var(--ch-axis-muted)">{liveStakeAmountCDF.maxV}</text>
				<text x={liveStakeAmountCDF.W / 2} y={liveStakeAmountCDF.PAD + 8} text-anchor="middle" font-size="7" fill="var(--ch-violet)">median {liveStakeAmountCDF.median}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">CDF of stake amounts across live trades · purple S-curve · steep curve = most trades use similar stake · flat = highly variable position sizing</p>
		</section>
	{/if}
	{#if liveProfitBySide}
		<section class="rounded-lg border border-border bg-card p-3">
			<h3 class="mb-1 text-xs font-semibold text-muted-foreground">Avg Profit% by Trade Side</h3>
			<svg viewBox={`0 0 ${liveProfitBySide.W} ${liveProfitBySide.H}`} width="100%" style="height:70px">
				<line x1={liveProfitBySide.PAD} y1={liveProfitBySide.midY} x2={liveProfitBySide.W - liveProfitBySide.PAD} y2={liveProfitBySide.midY} stroke="var(--ch-axis-faint)" stroke-width="0.5" stroke-dasharray="2,2"/>
				{#each liveProfitBySide.bars as b, i}
					{@const bh = (Math.abs(b.avgProfit) / liveProfitBySide.maxAbsProfit) * (liveProfitBySide.midY - liveProfitBySide.PAD)}
					{@const x = liveProfitBySide.PAD + i * (liveProfitBySide.bw + 12)}
					{@const y = b.avgProfit >= 0 ? liveProfitBySide.midY - bh : liveProfitBySide.midY}
					{@const color = b.avgProfit >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect {x} {y} width={liveProfitBySide.bw} height={bh} fill={color} rx="2"/>
					<text x={x + liveProfitBySide.bw / 2} y={liveProfitBySide.H} text-anchor="middle" font-size="8" fill="var(--ch-axis-strong)">{b.side}</text>
					<text x={x + liveProfitBySide.bw / 2} y={b.avgProfit >= 0 ? y - 3 : y + bh + 9} text-anchor="middle" font-size="7" fill={color}>{b.avgProfit.toFixed(2)}%</text>
					<text x={x + liveProfitBySide.bw / 2} y={b.avgProfit >= 0 ? y - 9 : y + bh + 15} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">WR {b.wr.toFixed(0)}%</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg profit% and win rate by trade direction · long vs short performance comparison in live trading · imbalance reveals directional edge or market regime bias</p>
		</section>
	{/if}
	{#if liveTradeCountByHour}
		<section class="rounded-lg border border-border bg-card p-3">
			<h3 class="mb-1 text-xs font-semibold text-muted-foreground">Trade Open Count by Hour (UTC)</h3>
			<svg viewBox={`0 0 ${liveTradeCountByHour.W} ${liveTradeCountByHour.H}`} width="100%" style="height:65px">
				{#each liveTradeCountByHour.counts as cnt, i}
					{@const bh = Math.max(1, (cnt / liveTradeCountByHour.maxCnt) * (liveTradeCountByHour.H - liveTradeCountByHour.PAD * 2))}
					{@const x = liveTradeCountByHour.PAD + i * (liveTradeCountByHour.bw + 0.5)}
					{@const y = liveTradeCountByHour.H - liveTradeCountByHour.PAD - bh}
					<rect {x} {y} width={liveTradeCountByHour.bw} height={bh} fill="var(--ch-violet)" rx="0.5"/>
					{#if i % 6 === 0}
						<text x={x + liveTradeCountByHour.bw / 2} y={liveTradeCountByHour.H} text-anchor="middle" font-size="5.5" fill="var(--ch-axis-muted)">{i}h</text>
					{/if}
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Live trade open count by UTC hour · indigo bars · peaks show when the strategy is most active · reveals whether entries concentrate around market opens or specific sessions</p>
		</section>
	{/if}
	{#if liveSortinoCDF}
		<section class="rounded-lg border border-border bg-card p-3">
			<h3 class="mb-1 text-xs font-semibold text-muted-foreground">Monthly Sortino CDF (Live)</h3>
			<svg viewBox={`0 0 ${liveSortinoCDF.W} ${liveSortinoCDF.H}`} width="100%" style="height:65px">
				<line x1={liveSortinoCDF.PAD} y1={liveSortinoCDF.H - liveSortinoCDF.PAD} x2={liveSortinoCDF.W - liveSortinoCDF.PAD} y2={liveSortinoCDF.H - liveSortinoCDF.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.5"/>
				<line x1={liveSortinoCDF.toX(0)} y1={liveSortinoCDF.PAD} x2={liveSortinoCDF.toX(0)} y2={liveSortinoCDF.H - liveSortinoCDF.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.5" stroke-dasharray="2,2"/>
				<polyline points={liveSortinoCDF.polyline} fill="none" stroke="var(--ch-teal-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={liveSortinoCDF.PAD} y={liveSortinoCDF.H - 2} font-size="5.5" fill="var(--ch-axis-muted)">{liveSortinoCDF.minV}</text>
				<text x={liveSortinoCDF.W - liveSortinoCDF.PAD} y={liveSortinoCDF.H - 2} text-anchor="end" font-size="5.5" fill="var(--ch-axis-muted)">{liveSortinoCDF.maxV}</text>
				<text x={liveSortinoCDF.W / 2} y={liveSortinoCDF.PAD + 8} text-anchor="middle" font-size="7" fill="var(--ch-teal-strong)">median {liveSortinoCDF.median}</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">CDF of per-month Sortino across live trading · teal S-curve · dashed at 0 · majority above 0 = live strategy consistently delivers positive downside-adjusted returns</p>
		</section>
	{/if}
	{#if livePairProfitRanking}
		<section class="rounded-lg border border-border bg-card p-3">
			<h3 class="mb-1 text-xs font-semibold text-muted-foreground">Avg Profit% by Base Asset (Live)</h3>
			<svg viewBox={`0 0 ${livePairProfitRanking.W} ${livePairProfitRanking.H}`} width="100%" style="height:70px">
				<line x1={livePairProfitRanking.PAD} y1={livePairProfitRanking.midY} x2={livePairProfitRanking.W - livePairProfitRanking.PAD} y2={livePairProfitRanking.midY} stroke="var(--ch-axis-faint)" stroke-width="0.5" stroke-dasharray="2,2"/>
				{#each livePairProfitRanking.bars as b, i}
					{@const bh = (Math.abs(b.avg) / livePairProfitRanking.maxAbs) * (livePairProfitRanking.midY - livePairProfitRanking.PAD)}
					{@const x = livePairProfitRanking.PAD + i * (livePairProfitRanking.bw + 2)}
					{@const y = b.avg >= 0 ? livePairProfitRanking.midY - bh : livePairProfitRanking.midY}
					{@const color = b.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)'}
					<rect {x} {y} width={livePairProfitRanking.bw} height={bh} fill={color} rx="1"/>
					<text x={x + livePairProfitRanking.bw / 2} y={livePairProfitRanking.H} text-anchor="middle" font-size="5.5" fill="var(--ch-axis)">{b.base}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Avg live profit% by base asset · green=profitable · red=losing · top performers reveal which coins the strategy has strongest live edge on</p>
		</section>
	{/if}
	{#if liveWinRateCDF}
		<section class="rounded-lg border border-border bg-card p-3">
			<h3 class="mb-1 text-xs font-semibold text-muted-foreground">Per-Pair Win Rate% CDF (Live)</h3>
			<svg viewBox={`0 0 ${liveWinRateCDF.W} ${liveWinRateCDF.H}`} width="100%" style="height:65px">
				<line x1={liveWinRateCDF.x50} y1={liveWinRateCDF.PAD} x2={liveWinRateCDF.x50} y2={liveWinRateCDF.H - liveWinRateCDF.PAD} stroke="var(--ch-axis-faint)" stroke-width="0.5" stroke-dasharray="2,2"/>
				<polyline points={liveWinRateCDF.polyline} fill="none" stroke="var(--ch-profit-strong)" stroke-width="1.5" stroke-linejoin="round"/>
				<text x={liveWinRateCDF.PAD} y={liveWinRateCDF.H} font-size="5.5" fill="var(--ch-axis-muted)">{liveWinRateCDF.minV}%</text>
				<text x={liveWinRateCDF.W - liveWinRateCDF.PAD} y={liveWinRateCDF.H} text-anchor="end" font-size="5.5" fill="var(--ch-axis-muted)">{liveWinRateCDF.maxV}%</text>
				<text x={liveWinRateCDF.x50 + 3} y={liveWinRateCDF.PAD + 6} font-size="5" fill="var(--ch-axis-muted)">50%</text>
				<text x={liveWinRateCDF.W / 2} y={liveWinRateCDF.PAD + 13} text-anchor="middle" font-size="6" fill="var(--ch-profit)">med {liveWinRateCDF.median}%</text>
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">CDF of per-pair live win rate% · green S-curve · dashed at 50% · pairs to the right of 50% are net winners · steep rise = consistent win rate across pairs</p>
		</section>
	{/if}
	{#if liveSharpeByBot}
		<section class="rounded-lg border border-border bg-card p-3">
			<h3 class="mb-1 text-xs font-semibold text-muted-foreground">Approx Sharpe by Bot (trade returns)</h3>
			<svg viewBox={`0 0 ${liveSharpeByBot.W} ${liveSharpeByBot.H}`} width="100%" style="height:65px">
				<line x1={liveSharpeByBot.PAD} y1={liveSharpeByBot.midY} x2={liveSharpeByBot.W - liveSharpeByBot.PAD} y2={liveSharpeByBot.midY} stroke="var(--ch-axis-faint)" stroke-width="0.5"/>
				{#each liveSharpeByBot.bars as b, i}
					{@const bh = Math.max(1, (Math.abs(b.sharpe) / liveSharpeByBot.maxAbs) * (liveSharpeByBot.midY - liveSharpeByBot.PAD))}
					{@const x = liveSharpeByBot.PAD + i * (liveSharpeByBot.bw + 3)}
					{@const y = b.sharpe >= 0 ? liveSharpeByBot.midY - bh : liveSharpeByBot.midY}
					{@const color = b.sharpe >= 0.5 ? 'var(--ch-profit)' : b.sharpe >= 0 ? 'var(--ch-teal)' : 'var(--ch-loss)'}
					<rect {x} {y} width={liveSharpeByBot.bw} height={bh} fill={color} rx="1"/>
					<text x={x + liveSharpeByBot.bw / 2} y={liveSharpeByBot.H} text-anchor="middle" font-size="5" fill="var(--ch-axis-muted)">{b.bot}</text>
				{/each}
			</svg>
			<p class="mt-1 text-[9px] text-muted-foreground">Approx Sharpe (mean/std of trade returns) by bot · green≥0.5 · teal≥0 · red&lt;0 · identifies which bots have most consistent live return quality</p>
		</section>
	{/if}
</main>
