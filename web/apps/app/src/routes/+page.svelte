<script lang="ts">
	import Kpi from '$lib/components/kpi.svelte';
	import FactorBadges from '$lib/components/factor-badges.svelte';
	import InfoTip from '$lib/components/info-tip.svelte';
	import GreetingBanner from '$lib/components/greeting-banner.svelte';
	import TrustIntro from '$lib/components/trust-intro.svelte';
	import AffiliateCta from '$lib/components/affiliate-cta.svelte';
	import { fmtPct, fmtTime } from '$lib/utils';
	import { t, type Lang } from '$lib/i18n';
	import type { PageData } from './$types';
	import { onMount } from 'svelte';
	import ChartInfo from '$lib/components/chart-info.svelte';

	let { data }: { data: PageData } = $props();
	const s = data.summary;
	const lang = $derived<Lang>(data.lang ?? 'zh');
	const recentRuns = $derived(data.recent_runs);
	const runs = $derived(data.recent_runs);

	let strategyFilter = $state<string | null>(null);
	let timeframeFilter = $state<string | null>(null);

	const filtered = $derived.by(() => {
		let rs = data.recent_runs;
		if (strategyFilter) rs = rs.filter((r) => r.strategy === strategyFilter);
		if (timeframeFilter) rs = rs.filter((r) => r.timeframe === timeframeFilter);
		return rs.slice(0, 25);
	});

	function fmt(key: string, vars: Record<string, string | number>) {
		let s = t(lang, key);
		for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v));
		return s;
	}

	// Backtest activity calendar (GitHub-style 52-week heatmap)
	const activityCalendar = $derived.by(() => {
		const today = new Date();
		today.setHours(0, 0, 0, 0);
		const WEEKS = 52;
		const startDate = new Date(today);
		startDate.setDate(today.getDate() - WEEKS * 7 + 1);
		// Align to Monday
		const dow = (startDate.getDay() + 6) % 7;
		startDate.setDate(startDate.getDate() - dow);

		const counts = new Map<string, number>();
		for (const r of data.recent_runs) {
			if (!r.started_at) continue;
			const day = r.started_at.slice(0, 10);
			counts.set(day, (counts.get(day) ?? 0) + 1);
		}
		const maxCount = Math.max(1, ...counts.values());

		const weeks: { date: string; count: number; intensity: number }[][] = [];
		let d = new Date(startDate);
		for (let w = 0; w < WEEKS; w++) {
			const week: { date: string; count: number; intensity: number }[] = [];
			for (let day = 0; day < 7; day++) {
				const key = d.toISOString().slice(0, 10);
				const count = counts.get(key) ?? 0;
				week.push({ date: key, count, intensity: count / maxCount });
				d.setDate(d.getDate() + 1);
			}
			weeks.push(week);
		}
		const total = [...counts.values()].reduce((a, b) => a + b, 0);
		return { weeks, total, maxCount };
	});

	// Strategy performance leaderboard — best recent run per strategy
	const stratLeaderboard = $derived.by(() => {
		if (data.recent_runs.length === 0) return null;
		const byStrat = new Map<string, typeof data.recent_runs[0]>();
		for (const r of data.recent_runs) {
			const cur = byStrat.get(r.strategy);
			if (!cur || (r.started_at ?? '') > (cur.started_at ?? '')) byStrat.set(r.strategy, r);
		}
		const entries = [...byStrat.values()]
			.filter(r => r.total_profit_pct != null)
			.sort((a, b) => b.total_profit_pct! - a.total_profit_pct!);
		const top = entries.slice(0, 3);
		const bottom = entries.slice(-3).reverse();
		return { top, bottom, total: entries.length };
	});

	// Recent DCA event timeline: last 8 triggers with kind, amount, age
	const recentEvents = $derived.by(() => {
		const sorted = [...data.triggers]
			.filter(e => e.ts)
			.sort((a, b) => b.ts.localeCompare(a.ts))
			.slice(0, 8);
		if (sorted.length === 0) return null;
		const now = Date.now();
		const KIND_COLOR: Record<string, string> = {
			FLASH: 'var(--ch-loss)', FAST: 'var(--ch-warn)',
			SUSTAIN: 'var(--ch-violet)', CAPITUL: 'var(--ch-violet-strong)',
		};
		return sorted.map(e => {
			const ms = now - new Date(e.ts).getTime();
			const ago = ms < 3600000 ? Math.round(ms / 60000) + 'm ago'
				: ms < 86400000 ? Math.round(ms / 3600000) + 'h ago'
				: Math.round(ms / 86400000) + 'd ago';
			return { kind: e.kind, amount: e.amount_usdt, severity: e.severity, ago, color: KIND_COLOR[e.kind] ?? 'var(--ch-axis-strong)' };
		});
	});

	// Per-strategy profit sparkline (last 5 runs, sorted by date)
	const stratSparklines = $derived.by(() => {
		if (data.recent_runs.length < 3) return null;
		const byStrat = new Map<string, typeof data.recent_runs>();
		for (const r of data.recent_runs) {
			if (r.total_profit_pct == null) continue;
			if (!byStrat.has(r.strategy)) byStrat.set(r.strategy, []);
			byStrat.get(r.strategy)!.push(r);
		}
		const rows = [...byStrat.entries()]
			.map(([strategy, runs]) => {
				const sorted = runs.sort((a, b) => (a.started_at ?? '') < (b.started_at ?? '') ? -1 : 1).slice(-5);
				const vals = sorted.map(r => r.total_profit_pct!);
				const mn = Math.min(...vals), mx = Math.max(0.001, ...vals);
				const W = 60, H = 24;
				const pts = vals.map((v, i) => {
					const x = vals.length === 1 ? W / 2 : (i / (vals.length - 1)) * W;
					const y = H - 2 - ((v - mn) / (mx - mn || 0.001)) * (H - 4);
					return `${x.toFixed(1)},${y.toFixed(1)}`;
				}).join(' ');
				const last = vals[vals.length - 1];
				const trend = vals.length >= 2 ? last - vals[0] : 0;
				return { strategy, vals, pts, W, H, last, trend };
			})
			.sort((a, b) => b.last - a.last)
			.slice(0, 8);
		if (rows.length < 2) return null;
		return rows;
	});

	// DCA capital deployment timeline (USDT per week from triggers)
	// Timeframe distribution of recent runs
	const tfRunDist = $derived.by(() => {
		const map = new Map<string, { count: number; avgProfit: number; profitSum: number }>();
		for (const r of data.recent_runs) {
			const tf = r.timeframe ?? 'unknown';
			if (!map.has(tf)) map.set(tf, { count: 0, avgProfit: 0, profitSum: 0 });
			const e = map.get(tf)!;
			e.count++;
			if (r.total_profit_pct != null) e.profitSum += r.total_profit_pct;
		}
		const rows = [...map.entries()]
			.map(([tf, v]) => ({ tf, count: v.count, avgProfit: v.profitSum / v.count }))
			.sort((a, b) => b.count - a.count);
		if (rows.length < 2) return null;
		const maxCount = Math.max(1, ...rows.map(r => r.count));
		return rows.map(r => ({ ...r, barPct: (r.count / maxCount) * 100 }));
	});

	// Top pairs across recent runs by frequency
	const recentRunPairFreq = $derived.by(() => {
		const map = new Map<string, number>();
		for (const r of data.recent_runs) {
			if (!r.pairs) continue;
			for (const p of r.pairs) map.set(p, (map.get(p) ?? 0) + 1);
		}
		const rows = [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
		if (rows.length < 3) return null;
		const maxCount = rows[0][1];
		return rows.map(([pair, count]) => ({ pair, count, barPct: (count / maxCount) * 100 }));
	});

	const dcaDeployment = $derived.by(() => {
		const trig = data.triggers.filter(e => e.ts && e.amount_usdt != null);
		if (trig.length < 3) return null;
		const weekMap = new Map<string, number>();
		for (const e of trig) {
			const d = new Date(e.ts);
			const jan4 = new Date(d.getFullYear(), 0, 4);
			const startOfWeek = new Date(jan4);
			startOfWeek.setDate(jan4.getDate() - ((jan4.getDay() + 6) % 7));
			const wn = Math.ceil(((d.getTime() - startOfWeek.getTime()) / 86400000 + 1) / 7);
			const key = `${d.getFullYear()}-W${String(wn).padStart(2, '0')}`;
			weekMap.set(key, (weekMap.get(key) ?? 0) + (e.amount_usdt ?? 0));
		}
		const weeks = [...weekMap.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(-16);
		if (weeks.length < 2) return null;
		const vals = weeks.map(w => w[1]);
		const maxVal = Math.max(1, ...vals);
		const total = vals.reduce((a, b) => a + b, 0);
		return weeks.map(([week, v]) => ({ week, v, barPct: (v / maxVal) * 100 })).concat().map((w, i) => ({ ...w, i }));
	});

	// Sharpe leaderboard: best Sharpe per strategy from recent runs
	const sharpeLeaderboard = $derived.by(() => {
		const byStrat = new Map<string, number>();
		for (const r of data.recent_runs) {
			if (r.sharpe == null) continue;
			const cur = byStrat.get(r.strategy);
			if (cur == null || r.sharpe > cur) byStrat.set(r.strategy, r.sharpe);
		}
		const rows = [...byStrat.entries()]
			.map(([strategy, sharpe]) => ({ strategy, sharpe }))
			.filter(r => r.sharpe > -100)
			.sort((a, b) => b.sharpe - a.sharpe)
			.slice(0, 10);
		if (rows.length < 3) return null;
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.sharpe)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.sharpe) / maxAbs) * 100 }));
	});

	// Composite quality ranking: normalize sharpe + profit - drawdown into a single score
	const compositeQualityRanking = $derived.by(() => {
		const runs = data.recent_runs.filter(r =>
			r.sharpe != null && r.total_profit_pct != null && r.max_drawdown_pct != null
		);
		if (runs.length < 5) return null;
		const byStrat = new Map<string, typeof runs[0]>();
		for (const r of runs) {
			const cur = byStrat.get(r.strategy);
			if (!cur || (r.sharpe ?? -999) > (cur.sharpe ?? -999)) byStrat.set(r.strategy, r);
		}
		const pts = [...byStrat.values()];
		const sharpes = pts.map(r => r.sharpe!);
		const profits = pts.map(r => r.total_profit_pct!);
		const dds = pts.map(r => r.max_drawdown_pct!);
		const norm = (v: number, mn: number, mx: number) => mx === mn ? 0.5 : (v - mn) / (mx - mn);
		const sMin = Math.min(...sharpes), sMax = Math.max(...sharpes);
		const pMin = Math.min(...profits), pMax = Math.max(...profits);
		const dMin = Math.min(...dds), dMax = Math.max(...dds);
		const scored = pts.map(r => ({
			strategy: r.strategy,
			score: norm(r.sharpe!, sMin, sMax) * 0.4 + norm(r.total_profit_pct!, pMin, pMax) * 0.4 + (1 - norm(r.max_drawdown_pct!, dMin, dMax)) * 0.2,
			sharpe: r.sharpe!, profit: r.total_profit_pct!, dd: r.max_drawdown_pct!,
		})).sort((a, b) => b.score - a.score).slice(0, 10);
		if (scored.length < 3) return null;
		return scored.map(r => ({ ...r, barPct: r.score * 100 }));
	});

	// Weekly run volume: last 12 weeks of backtest activity
	const weeklyRunVolume = $derived.by(() => {
		if (data.recent_runs.length < 5) return null;
		const now = Date.now();
		const MS_WEEK = 7 * 24 * 3600 * 1000;
		const weeks = Array.from({ length: 12 }, (_, i) => {
			const weekEnd = now - i * MS_WEEK;
			const weekStart = weekEnd - MS_WEEK;
			const label = new Date(weekStart).toLocaleDateString('en', { month: 'short', day: 'numeric' });
			return { label, start: weekStart, end: weekEnd, count: 0 };
		}).reverse();
		for (const r of data.recent_runs) {
			const ts = new Date(r.imported_at).getTime();
			const w = weeks.find(w => ts >= w.start && ts < w.end);
			if (w) w.count++;
		}
		const maxCount = Math.max(1, ...weeks.map(w => w.count));
		const trend = weeks[11].count - weeks[0].count;
		return { weeks, maxCount, trend };
	});

	// Hall of fame: top 8 individual runs by Sharpe
	const hallOfFame = $derived.by(() => {
		const valid = data.recent_runs.filter(r =>
			r.sharpe != null && r.total_profit_pct != null && r.max_drawdown_pct != null && Number.isFinite(r.sharpe)
		);
		if (valid.length < 3) return null;
		return [...valid]
			.sort((a, b) => b.sharpe! - a.sharpe!)
			.slice(0, 8)
			.map(r => ({
				strategy: r.strategy,
				tf: r.timeframe ?? '?',
				sharpe: r.sharpe!,
				profit: r.total_profit_pct!,
				dd: r.max_drawdown_pct!,
				trades: r.total_trades ?? 0,
			}));
	});

	// Top Calmar runs: best risk-adjusted return (return / max drawdown)
	const topCalmarRuns = $derived.by(() => {
		const valid = data.recent_runs.filter(r =>
			r.calmar != null && r.calmar > 0 && r.calmar < 200 &&
			r.total_profit_pct != null && r.max_drawdown_pct != null
		);
		if (valid.length < 3) return null;
		return [...valid]
			.sort((a, b) => b.calmar! - a.calmar!)
			.slice(0, 8)
			.map(r => ({
				strategy: r.strategy,
				tf: r.timeframe ?? '?',
				calmar: r.calmar!,
				profit: r.total_profit_pct!,
				dd: r.max_drawdown_pct!,
			}));
	});

	// Strategy consistency: % of runs with positive profit per strategy (min 5 runs)
	const strategyConsistency = $derived.by(() => {
		const byStrat = new Map<string, { pos: number; total: number }>();
		for (const r of data.recent_runs) {
			if (r.total_profit_pct == null) continue;
			if (!byStrat.has(r.strategy)) byStrat.set(r.strategy, { pos: 0, total: 0 });
			const e = byStrat.get(r.strategy)!;
			e.total++;
			if (r.total_profit_pct > 0) e.pos++;
		}
		const rows = [...byStrat.entries()]
			.filter(([, v]) => v.total >= 5)
			.map(([strategy, v]) => ({ strategy, consistency: v.pos / v.total, pos: v.pos, total: v.total }))
			.sort((a, b) => b.consistency - a.consistency)
			.slice(0, 10);
		if (rows.length < 3) return null;
		return rows;
	});

	// Profit factor leaderboard: best profit_factor per strategy from all recent runs
	const profitFactorLeaderboard = $derived.by(() => {
		const byStrat = new Map<string, number>();
		for (const r of data.recent_runs) {
			if (r.profit_factor == null || r.profit_factor <= 0 || r.profit_factor > 50) continue;
			const cur = byStrat.get(r.strategy);
			if (cur == null || r.profit_factor > cur) byStrat.set(r.strategy, r.profit_factor);
		}
		const rows = [...byStrat.entries()]
			.map(([strategy, pf]) => ({ strategy, pf }))
			.sort((a, b) => b.pf - a.pf)
			.slice(0, 10);
		if (rows.length < 3) return null;
		const maxPf = Math.max(0.01, ...rows.map(r => r.pf));
		return rows.map(r => ({ ...r, barPct: (r.pf / maxPf) * 100 }));
	});

	// Run profit histogram: distribution of total_profit_pct across all runs (10 equal buckets)
	const runProfitHistogram = $derived.by(() => {
		const vals = data.recent_runs
			.filter(r => r.total_profit_pct != null && isFinite(r.total_profit_pct) && Math.abs(r.total_profit_pct) < 5000)
			.map(r => r.total_profit_pct!);
		if (vals.length < 20) return null;
		const lo = Math.min(...vals), hi = Math.max(...vals);
		if (hi - lo < 0.01) return null;
		const step = (hi - lo) / 10;
		const buckets = Array.from({ length: 10 }, (_, i) => ({
			lo: lo + i * step,
			hi: lo + (i + 1) * step,
			count: 0,
			label: `${(lo + i * step).toFixed(0)}%`
		}));
		for (const v of vals) {
			const idx = Math.min(9, Math.floor((v - lo) / step));
			buckets[idx].count++;
		}
		const maxCount = Math.max(1, ...buckets.map(b => b.count));
		return buckets.map(b => ({ ...b, barPct: (b.count / maxCount) * 100, positive: b.lo >= 0 }));
	});

	// Avg max drawdown by timeframe: which timeframes carry least downside risk on average?
	const drawdownByTimeframe = $derived.by(() => {
		const TF_ORDER = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d','3d','1w'];
		const map = new Map<string, number[]>();
		for (const r of data.recent_runs) {
			if (!r.timeframe || r.max_drawdown_pct == null || !isFinite(r.max_drawdown_pct)) continue;
			if (!map.has(r.timeframe)) map.set(r.timeframe, []);
			map.get(r.timeframe)!.push(r.max_drawdown_pct);
		}
		const rows = [...map.entries()]
			.map(([tf, vals]) => ({ tf, avg: vals.reduce((a, b) => a + b, 0) / vals.length, count: vals.length }))
			.filter(r => r.count >= 3)
			.sort((a, b) => (TF_ORDER.indexOf(a.tf) === -1 ? 99 : TF_ORDER.indexOf(a.tf)) - (TF_ORDER.indexOf(b.tf) === -1 ? 99 : TF_ORDER.indexOf(b.tf)));
		if (rows.length < 2) return null;
		const maxAvg = Math.max(0.01, ...rows.map(r => r.avg));
		return rows.map(r => ({ ...r, barPct: (r.avg / maxAvg) * 100 }));
	});

	const recentRunCalmarVsProfit = $derived.by(() => {
		const pts = data.recent_runs.filter(r => r.calmar != null && isFinite(r.calmar) && r.calmar > -20 && r.calmar < 50 && r.total_profit_pct != null && isFinite(r.total_profit_pct));
		if (pts.length < 8) return null;
		const W = 560, H = 100, PAD = 10;
		const xs = pts.map(r => r.calmar!), ys = pts.map(r => r.total_profit_pct!);
		const xMin = Math.min(...xs), xMax = Math.max(...xs, xMin + 0.1);
		const yMin = Math.min(...ys), yMax = Math.max(...ys, yMin + 0.1);
		const toX = (v: number) => PAD + ((v - xMin) / (xMax - xMin)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - yMin) / (yMax - yMin)) * (H - PAD * 2);
		const zeroX = toX(0), zeroY = toY(0);
		const dots = pts.map(r => ({
			cx: toX(r.calmar!), cy: toY(r.total_profit_pct!),
			color: r.calmar! >= 1 && r.total_profit_pct! >= 0 ? 'var(--ch-profit)' : r.total_profit_pct! >= 0 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)',
			title: `${r.strategy} · calmar ${r.calmar!.toFixed(2)} · profit ${r.total_profit_pct! >= 0 ? '+' : ''}${r.total_profit_pct!.toFixed(1)}%`
		}));
		return { dots, W, H, PAD, xMin, xMax, yMin, yMax, zeroX, zeroY };
	});

	const recentRunSortinoLeaderboard = $derived.by(() => {
		const rows = data.recent_runs
			.filter(r => r.sortino != null && isFinite(r.sortino) && r.sortino > -50)
			.sort((a, b) => b.sortino! - a.sortino!)
			.slice(0, 10);
		if (rows.length < 3) return null;
		const maxSortino = Math.max(0.01, rows[0].sortino!);
		return rows.map(r => ({ strategy: r.strategy, sortino: r.sortino!, tf: r.timeframe ?? '?', barPct: (Math.max(0, r.sortino!) / maxSortino) * 100 }));
	});

	const bestRunByTimeframe = $derived.by(() => {
		const TF_ORDER = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d','3d','1w'];
		const map = new Map<string, number>();
		for (const r of data.recent_runs) {
			if (!r.timeframe || r.total_profit_pct == null || !isFinite(r.total_profit_pct)) continue;
			if (!map.has(r.timeframe) || r.total_profit_pct > map.get(r.timeframe)!) map.set(r.timeframe, r.total_profit_pct);
		}
		const rows = [...map.entries()]
			.map(([tf, best]) => ({ tf, best }))
			.sort((a, b) => (TF_ORDER.indexOf(a.tf) === -1 ? 99 : TF_ORDER.indexOf(a.tf)) - (TF_ORDER.indexOf(b.tf) === -1 ? 99 : TF_ORDER.indexOf(b.tf)));
		if (rows.length < 3) return null;
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.best)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.best) / maxAbs) * 100 }));
	});

	// Avg win_rate_pct per timeframe (distinct from drawdownByTimeframe, bestRunByTimeframe, tfRunDist)
	const timeframeWinRateRanking = $derived.by(() => {
		const TF_ORDER = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d','3d','1w'];
		const map = new Map<string, number[]>();
		for (const r of data.recent_runs) {
			if (!r.timeframe || r.win_rate_pct == null || !isFinite(r.win_rate_pct)) continue;
			if (!map.has(r.timeframe)) map.set(r.timeframe, []);
			map.get(r.timeframe)!.push(r.win_rate_pct);
		}
		const rows = [...map.entries()]
			.filter(([, vals]) => vals.length >= 2)
			.map(([tf, vals]) => ({ tf, avg: vals.reduce((a, b) => a + b, 0) / vals.length, count: vals.length }))
			.sort((a, b) => (TF_ORDER.indexOf(a.tf) === -1 ? 99 : TF_ORDER.indexOf(a.tf)) - (TF_ORDER.indexOf(b.tf) === -1 ? 99 : TF_ORDER.indexOf(b.tf)));
		if (rows.length < 3) return null;
		const maxAvg = Math.max(0.01, ...rows.map(r => r.avg));
		return rows.map(r => ({ ...r, barPct: (r.avg / maxAvg) * 100 }));
	});

	// Top 10 recent runs by profit_factor (distinct from profitFactorLeaderboard strategy-level aggregates, topCalmarRuns, recentRunSortinoLeaderboard)
	const recentRunTopProfitFactor = $derived.by(() => {
		const runs = data.recent_runs
			.filter(r => r.profit_factor != null && isFinite(r.profit_factor) && r.profit_factor >= 0 && r.profit_factor <= 20)
			.sort((a, b) => b.profit_factor! - a.profit_factor!)
			.slice(0, 10);
		if (runs.length < 3) return null;
		const maxPf = runs[0].profit_factor!;
		return runs.map(r => ({ strategy: r.strategy, tf: r.timeframe ?? '?', pf: r.profit_factor!, barPct: (r.profit_factor! / maxPf) * 100 }));
	});

	const topStrategyByCalmar = $derived.by(() => {
		const byStrat = new Map<string, number>();
		for (const r of data.recent_runs) {
			if (r.calmar == null || !isFinite(r.calmar) || r.calmar <= 0) continue;
			const cur = byStrat.get(r.strategy ?? '');
			if (cur == null || r.calmar > cur) byStrat.set(r.strategy ?? '', r.calmar);
		}
		const rows = [...byStrat.entries()].map(([s, c]) => ({ strategy: s, calmar: c })).sort((a, b) => b.calmar - a.calmar).slice(0, 10);
		if (rows.length < 3) return null;
		const maxC = rows[0].calmar;
		return rows.map(r => ({ ...r, barPct: (r.calmar / maxC) * 100 }));
	});

	const recentRunDrawdownVsProfit = $derived.by(() => {
		const pts = data.recent_runs.filter(r =>
			r.max_drawdown_pct != null && isFinite(r.max_drawdown_pct) &&
			r.total_profit_pct != null && isFinite(r.total_profit_pct)
		).map(r => ({ dd: r.max_drawdown_pct!, profit: r.total_profit_pct!, strategy: r.strategy ?? '' }));
		if (pts.length < 8) return null;
		const maxDd = Math.max(...pts.map(p => p.dd), 1);
		const minP = Math.min(...pts.map(p => p.profit));
		const maxP = Math.max(...pts.map(p => p.profit), 0.01);
		const rangeP = maxP - minP || 1;
		const W = 300, H = 80, PAD = 10;
		const mapped = pts.map(p => ({
			cx: PAD + (p.dd / maxDd) * (W - PAD * 2),
			cy: H - PAD - ((p.profit - minP) / rangeP) * (H - PAD * 2),
			profitable: p.profit > 0
		}));
		return { mapped, W, H, PAD, maxDd, minP, maxP };
	});

	const recentRunTimeframeProfit = $derived.by(() => {
		const map = new Map<string, { sum: number; count: number }>();
		for (const r of data.recent_runs) {
			if (!r.timeframe || r.total_profit_pct == null || !isFinite(r.total_profit_pct)) continue;
			if (!map.has(r.timeframe)) map.set(r.timeframe, { sum: 0, count: 0 });
			const e = map.get(r.timeframe)!;
			e.sum += r.total_profit_pct;
			e.count++;
		}
		if (map.size < 2) return null;
		const TF_ORDER = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d'];
		const rows = [...map.entries()]
			.map(([tf, v]) => ({ tf, avg: v.sum / v.count, count: v.count }))
			.sort((a, b) => TF_ORDER.indexOf(a.tf) - TF_ORDER.indexOf(b.tf));
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.avg)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.avg) / maxAbs) * 100 }));
	});

	const topStrategyByWinRate = $derived.by(() => {
		const map = new Map<string, { best: number; runs: number }>();
		for (const r of data.recent_runs) {
			if (!r.strategy || r.win_rate_pct == null || !isFinite(r.win_rate_pct)) continue;
			const e = map.get(r.strategy);
			if (!e) map.set(r.strategy, { best: r.win_rate_pct, runs: 1 });
			else { e.best = Math.max(e.best, r.win_rate_pct); e.runs++; }
		}
		if (map.size < 3) return null;
		const rows = [...map.entries()]
			.map(([name, v]) => ({ name, best: v.best, runs: v.runs }))
			.sort((a, b) => b.best - a.best)
			.slice(0, 10);
		const maxBest = Math.max(0.01, ...rows.map(r => r.best));
		return rows.map(r => ({ ...r, barPct: (r.best / maxBest) * 100 }));
	});

	const recentRunMonthlyAvgProfit = $derived.by(() => {
		const map = new Map<string, { sum: number; count: number }>();
		for (const r of data.recent_runs) {
			if (!r.imported_at || r.total_profit_pct == null || !isFinite(r.total_profit_pct)) continue;
			const ym = r.imported_at.slice(0, 7);
			if (!map.has(ym)) map.set(ym, { sum: 0, count: 0 });
			const e = map.get(ym)!;
			e.sum += r.total_profit_pct;
			e.count++;
		}
		if (map.size < 3) return null;
		const rows = [...map.entries()]
			.map(([ym, v]) => ({ ym, avg: v.sum / v.count, count: v.count }))
			.sort((a, b) => a.ym.localeCompare(b.ym));
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.avg)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.avg) / maxAbs) * 100 }));
	});

	const topStrategyBySortino = $derived.by(() => {
		const map = new Map<string, { best: number; runs: number }>();
		for (const r of data.recent_runs) {
			if (!r.strategy || r.sortino == null || !isFinite(r.sortino) || r.sortino < -50 || r.sortino > 500) continue;
			const e = map.get(r.strategy);
			if (!e) map.set(r.strategy, { best: r.sortino, runs: 1 });
			else { e.best = Math.max(e.best, r.sortino); e.runs++; }
		}
		if (map.size < 3) return null;
		const rows = [...map.entries()]
			.map(([name, v]) => ({ name, best: v.best, runs: v.runs }))
			.filter(r => r.best > 0)
			.sort((a, b) => b.best - a.best)
			.slice(0, 10);
		if (rows.length < 3) return null;
		const maxBest = Math.max(0.01, ...rows.map(r => r.best));
		return rows.map(r => ({ ...r, barPct: (r.best / maxBest) * 100 }));
	});

	const recentRunDrawdownDistribution = $derived.by(() => {
		const vals = data.recent_runs.filter(r => r.max_drawdown_pct != null && isFinite(r.max_drawdown_pct) && r.max_drawdown_pct >= 0 && r.max_drawdown_pct < 100).map(r => r.max_drawdown_pct!);
		if (vals.length < 8) return null;
		const mx = Math.max(...vals);
		const BINS = 8, step = mx / BINS;
		const buckets = Array.from({ length: BINS }, (_, i) => ({
			lo: i * step, hi: (i + 1) * step,
			label: `${(i * step).toFixed(0)}–${((i + 1) * step).toFixed(0)}%`,
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

	const recentRunSharpeDistribution = $derived.by(() => {
		const vals = data.recent_runs.filter(r => r.sharpe != null && isFinite(r.sharpe) && r.sharpe > -50 && r.sharpe < 200).map(r => r.sharpe!);
		if (vals.length < 8) return null;
		const mn = Math.min(...vals), mx = Math.max(...vals);
		const range = mx - mn || 1;
		const BINS = 8, step = range / BINS;
		const buckets = Array.from({ length: BINS }, (_, i) => ({
			lo: mn + i * step, hi: mn + (i + 1) * step,
			label: `${(mn + i * step).toFixed(1)}`,
			count: 0
		}));
		for (const v of vals) {
			const idx = Math.min(BINS - 1, Math.floor((v - mn) / step));
			buckets[idx].count++;
		}
		const maxCount = Math.max(1, ...buckets.map(b => b.count));
		const sorted = [...vals].sort((a, b) => a - b);
		const median = sorted[Math.floor(sorted.length / 2)];
		const positive = vals.filter(v => v > 0).length;
		return { buckets: buckets.map(b => ({ ...b, barPct: (b.count / maxCount) * 100, pos: b.lo >= 0 })), median, total: vals.length, positive };
	});

	const recentRunCalmarTimeline = $derived.by(() => {
		const sorted = data.recent_runs
			.filter(r => r.calmar != null && isFinite(r.calmar) && r.calmar > -50 && r.calmar < 200 && r.imported_at)
			.sort((a, b) => new Date(a.imported_at).getTime() - new Date(b.imported_at).getTime());
		if (sorted.length < 8) return null;
		let best = -Infinity;
		const pts = sorted.map(r => { if (r.calmar! > best) best = r.calmar!; return best; });
		const mn = pts[0], mx = pts[pts.length - 1];
		const range = mx - mn || 1;
		const W = 400, H = 56, PAD = 6;
		const toX = (i: number) => PAD + (i / Math.max(1, pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / range) * (H - PAD * 2);
		const poly = pts.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
		return { poly, W, H, PAD, mn, mx, positive: mx > 0, total: sorted.length };
	});

	const recentRunProfitFactorTimeline = $derived.by(() => {
		const sorted = data.recent_runs
			.filter(r => r.profit_factor != null && isFinite(r.profit_factor) && r.profit_factor >= 0 && r.profit_factor < 50 && r.imported_at)
			.sort((a, b) => new Date(a.imported_at).getTime() - new Date(b.imported_at).getTime());
		if (sorted.length < 8) return null;
		let best = 0;
		const pts = sorted.map(r => { if (r.profit_factor! > best) best = r.profit_factor!; return best; });
		const mn = pts[0], mx = pts[pts.length - 1];
		const range = mx - mn || 1;
		const W = 400, H = 56, PAD = 6;
		const toX = (i: number) => PAD + (i / Math.max(1, pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / range) * (H - PAD * 2);
		const poly = pts.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
		return { poly, W, H, PAD, mn, mx, total: sorted.length };
	});

	const recentRunPairsUsageFrequency = $derived.by(() => {
		const freq = new Map<string, number>();
		for (const r of data.recent_runs) {
			if (!r.pairs) continue;
			for (const p of r.pairs) {
				freq.set(p, (freq.get(p) ?? 0) + 1);
			}
		}
		const total = data.recent_runs.length;
		if (total < 5 || freq.size < 3) return null;
		const rows = [...freq.entries()]
			.map(([pair, count]) => ({ pair, count, pct: count / total }))
			.sort((a, b) => b.count - a.count)
			.slice(0, 15);
		if (rows.length < 3) return null;
		const maxCount = rows[0].count;
		return rows.map(r => ({ ...r, barPct: (r.count / maxCount) * 100, popular: r.pct >= 0.5 }));
	});

	const recentRunTimeframeCalmar = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of data.recent_runs) {
			if (!r.timeframe || r.calmar == null || !isFinite(r.calmar) || r.calmar < -10 || r.calmar > 100) continue;
			if (!map.has(r.timeframe)) map.set(r.timeframe, []);
			map.get(r.timeframe)!.push(r.calmar);
		}
		const TF_ORDER = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d'];
		const rows = [...map.entries()]
			.filter(([, vals]) => vals.length >= 3)
			.map(([tf, vals]) => {
				const sorted = [...vals].sort((a, b) => a - b);
				const mid = Math.floor(sorted.length / 2);
				const med = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
				return { tf, calmar: med, count: vals.length };
			})
			.sort((a, b) => (TF_ORDER.indexOf(a.tf) - TF_ORDER.indexOf(b.tf)) || b.calmar - a.calmar);
		if (rows.length < 2) return null;
		const absMax = Math.max(0.01, ...rows.map(r => Math.abs(r.calmar)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.calmar) / absMax) * 100, positive: r.calmar > 0 }));
	});

	const recentRunWinRateTimeline = $derived.by(() => {
		const sorted = data.recent_runs
			.filter(r => r.win_rate_pct != null && isFinite(r.win_rate_pct) && r.win_rate_pct >= 0 && r.win_rate_pct <= 100 && r.imported_at)
			.sort((a, b) => new Date(a.imported_at).getTime() - new Date(b.imported_at).getTime());
		if (sorted.length < 8) return null;
		let best = 0;
		const pts = sorted.map(r => { if (r.win_rate_pct! > best) best = r.win_rate_pct!; return best; });
		const mn = pts[0], mx = pts[pts.length - 1];
		const range = mx - mn || 1;
		const W = 400, H = 56, PAD = 6;
		const toX = (i: number) => PAD + (i / Math.max(1, pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mn) / range) * (H - PAD * 2);
		const poly = pts.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
		return { poly, W, H, PAD, mn, mx, total: sorted.length };
	});

	// Market regime mini-widget (client-side)
	let regimeBtc = $state<number | null>(null);
	let regimeFng = $state<{ value: number; label: string } | null>(null);
	let regimeLoading = $state(false);

	function regimeSignal(fng: number, btc: number | null): { label: string; color: string; desc: string } {
		if (fng <= 25) return { label: lang === 'en' ? 'BUY ZONE' : '抄底区', color: 'text-green-400', desc: lang === 'en' ? 'Extreme fear — historically best DCA window' : '极度恐慌 — 历史上最佳 DCA 时机' };
		if (fng >= 75) return { label: lang === 'en' ? 'CAUTION' : '谨慎区', color: 'text-red-400',   desc: lang === 'en' ? 'Extreme greed — reduce exposure, tighten stops' : '极度贪婪 — 减仓，收紧止损' };
		if (fng >= 55) return { label: lang === 'en' ? 'GREED'   : '贪婪',   color: 'text-yellow-400', desc: lang === 'en' ? 'Greed — trend-following strategies performing well' : '贪婪 — 趋势跟随表现良好' };
		return { label: lang === 'en' ? 'NEUTRAL' : '中性',  color: 'text-muted-foreground', desc: lang === 'en' ? 'Neutral — all strategies on equal footing' : '中性 — 各策略均势' };
	}

	onMount(async () => {
		regimeLoading = true;
		try {
			const [btcRes, fngRes] = await Promise.allSettled([
				fetch('https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT'),
				fetch('https://api.alternative.me/fng/?limit=1'),
			]);
			if (btcRes.status === 'fulfilled' && btcRes.value.ok) {
				const d = await btcRes.value.json();
				regimeBtc = parseFloat(d.price);
			}
			if (fngRes.status === 'fulfilled' && fngRes.value.ok) {
				const d = await fngRes.value.json();
				const v = parseInt(d.data?.[0]?.value ?? '50');
				regimeFng = { value: v, label: d.data?.[0]?.value_classification ?? '' };
			}
		} catch { /* silently ignore */ } finally {
			regimeLoading = false;
		}
	});

	// Avg profit per trade (total_profit_abs / total_trades) by strategy — efficiency metric
	const recentRunProfitPerTrade = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of data.recent_runs) {
			if (!r.strategy || r.total_profit_abs == null || r.total_trades == null || r.total_trades === 0) continue;
			if (!isFinite(r.total_profit_abs)) continue;
			const eff = r.total_profit_abs / r.total_trades;
			if (!isFinite(eff)) continue;
			if (!map.has(r.strategy)) map.set(r.strategy, []);
			map.get(r.strategy)!.push(eff);
		}
		const rows = [...map.entries()]
			.filter(([, vals]) => vals.length >= 2)
			.map(([strategy, vals]) => ({
				strategy,
				avg: vals.reduce((s, x) => s + x, 0) / vals.length,
				count: vals.length,
			}))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 12);
		if (rows.length < 3) return null;
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.avg)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.avg) / maxAbs) * 100 }));
	});

	// Median sharpe ratio per timeframe from recent runs
	const recentRunSharpeByTimeframe = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of data.recent_runs) {
			if (!r.timeframe || r.sharpe == null || !isFinite(r.sharpe) || r.sharpe < -10 || r.sharpe > 100) continue;
			if (!map.has(r.timeframe)) map.set(r.timeframe, []);
			map.get(r.timeframe)!.push(r.sharpe);
		}
		const TF_ORDER = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d'];
		const rows = [...map.entries()]
			.filter(([, vals]) => vals.length >= 3)
			.map(([tf, vals]) => {
				const sorted = [...vals].sort((a, b) => a - b);
				const mid = Math.floor(sorted.length / 2);
				const med = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
				return { tf, sharpe: med, count: vals.length };
			})
			.sort((a, b) => {
				const ai = TF_ORDER.indexOf(a.tf), bi = TF_ORDER.indexOf(b.tf);
				return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
			});
		if (rows.length < 2) return null;
		const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.sharpe)));
		return rows.map(r => ({ ...r, barPct: (Math.abs(r.sharpe) / maxAbs) * 100, positive: r.sharpe > 0 }));
	});

	const recentRunSortinoVsProfit = $derived.by(() => {
		const pts = data.recent_runs.filter(r => r.sortino != null && r.total_profit_pct != null && isFinite(r.sortino) && isFinite(r.total_profit_pct) && r.sortino > -50 && r.sortino < 200 && r.total_profit_pct > -500 && r.total_profit_pct < 2000);
		if (pts.length < 6) return null;
		const W = 360, H = 90, PAD = 10;
		const xs = pts.map(r => r.sortino!), ys = pts.map(r => r.total_profit_pct!);
		const xMin = Math.min(...xs), xMax = Math.max(...xs, xMin + 0.01);
		const yMin = Math.min(...ys), yMax = Math.max(...ys, yMin + 0.01);
		const toX = (v: number) => PAD + ((v - xMin) / (xMax - xMin)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - yMin) / (yMax - yMin)) * (H - PAD * 2);
		const zeroX = toX(0), zeroY = toY(0);
		const dots = pts.map(r => ({
			cx: toX(r.sortino!), cy: toY(r.total_profit_pct!),
			color: r.total_profit_pct! > 0 ? 'var(--ch-profit)' : 'var(--ch-loss-light)',
			strategy: r.strategy
		}));
		const n = pts.length;
		const mx = xs.reduce((a, b) => a + b, 0) / n, my = ys.reduce((a, b) => a + b, 0) / n;
		const num = xs.reduce((s, x, i) => s + (x - mx) * (ys[i] - my), 0);
		const den = Math.sqrt(xs.reduce((s, x) => s + (x - mx) ** 2, 0) * ys.reduce((s, y) => s + (y - my) ** 2, 0));
		const corr = den === 0 ? 0 : num / den;
		return { W, H, dots, zeroX, zeroY, corr, xMin: xMin.toFixed(1), xMax: xMax.toFixed(1), yMin: yMin.toFixed(0), yMax: yMax.toFixed(0) };
	});

	const recentRunWinLossRatioByTimeframe = $derived.by(() => {
		const valid = data.recent_runs.filter(r => r.timeframe && (r as any).wins != null && (r as any).losses != null);
		if (valid.length < 4) return null;
		const TF_ORDER = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d'];
		const map = new Map<string, { wins: number; losses: number; count: number }>();
		for (const r of valid) {
			if (!map.has(r.timeframe)) map.set(r.timeframe, { wins: 0, losses: 0, count: 0 });
			const e = map.get(r.timeframe)!;
			e.wins += (r as any).wins as number;
			e.losses += (r as any).losses as number;
			e.count++;
		}
		const rows = [...map.entries()]
			.map(([tf, v]) => ({ tf, ratio: v.losses > 0 ? v.wins / v.losses : v.wins, wins: v.wins, losses: v.losses, count: v.count }))
			.sort((a, b) => { const ai = TF_ORDER.indexOf(a.tf), bi = TF_ORDER.indexOf(b.tf); return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi); });
		if (rows.length < 2) return null;
		const maxRatio = Math.max(0.01, ...rows.map(r => r.ratio));
		return rows.map(r => ({ ...r, barPct: (r.ratio / maxRatio) * 100, good: r.ratio >= 1.5 }));
	});

	const recentRunExpectedReturnVsDD = $derived.by(() => {
		const pts = recentRuns.filter(r =>
			r.win_rate_pct != null && isFinite(r.win_rate_pct) &&
			r.total_profit_pct != null && isFinite(r.total_profit_pct) &&
			r.max_drawdown_pct != null && isFinite(r.max_drawdown_pct) && r.max_drawdown_pct > 0 &&
			r.total_trades != null && r.total_trades > 0
		).map(r => {
			const wr = r.win_rate_pct! / 100;
			const avgProfit = r.total_profit_pct! / r.total_trades!;
			const expectedReturn = wr * avgProfit;
			return { expectedReturn, dd: r.max_drawdown_pct!, tf: r.timeframe ?? '' };
		}).filter(p => isFinite(p.expectedReturn));
		if (pts.length < 6) return null;
		const erMin = Math.min(...pts.map(p => p.expectedReturn));
		const erMax = Math.max(...pts.map(p => p.expectedReturn), erMin + 0.01);
		const ddMin = Math.min(...pts.map(p => p.dd));
		const ddMax = Math.max(...pts.map(p => p.dd), ddMin + 0.01);
		const W = 560, H = 130, PAD = 10;
		const TF_COL: Record<string, string> = { '5m': 'var(--ch-violet)', '15m': 'var(--ch-profit)', '1h': 'var(--ch-warn)', '4h': 'var(--ch-loss)', '1d': 'var(--ch-teal)' };
		const toX = (d: number) => PAD + ((d - ddMin) / (ddMax - ddMin)) * (W - PAD * 2);
		const toY = (e: number) => H - PAD - ((e - erMin) / (erMax - erMin)) * (H - PAD * 2);
		const zeroY = erMin < 0 && erMax > 0 ? toY(0) : null;
		const dots = pts.map(p => ({ cx: toX(p.dd), cy: toY(p.expectedReturn), color: TF_COL[p.tf] ?? 'var(--ch-axis-muted)' }));
		const positive = pts.filter(p => p.expectedReturn > 0).length;
		return { W, H, dots, zeroY, ddMin: ddMin.toFixed(1), ddMax: ddMax.toFixed(1), erMin: erMin.toFixed(2), erMax: erMax.toFixed(2), total: pts.length, positive };
	});

	const recentRunProfitFactorVsSortino = $derived.by(() => {
		const pts = recentRuns.filter(r =>
			r.profit_factor != null && isFinite(r.profit_factor) && r.profit_factor > 0 && r.profit_factor < 30 &&
			r.sortino != null && isFinite(r.sortino) && r.sortino > -50 && r.sortino < 200
		).map(r => ({ pf: r.profit_factor!, sortino: r.sortino!, tf: r.timeframe ?? '' }));
		if (pts.length < 6) return null;
		const pfMin = Math.min(...pts.map(p => p.pf)), pfMax = Math.max(...pts.map(p => p.pf), pfMin + 0.01);
		const sMin = Math.min(...pts.map(p => p.sortino)), sMax = Math.max(...pts.map(p => p.sortino), sMin + 0.01);
		const W = 560, H = 130, PAD = 10;
		const TF_COL: Record<string, string> = { '5m': 'var(--ch-violet)', '15m': 'var(--ch-profit)', '1h': 'var(--ch-warn)', '4h': 'var(--ch-loss)', '1d': 'var(--ch-teal)' };
		const toX = (pf: number) => PAD + ((pf - pfMin) / (pfMax - pfMin)) * (W - PAD * 2);
		const toY = (s: number) => H - PAD - ((s - sMin) / (sMax - sMin)) * (H - PAD * 2);
		const zeroY = sMin < 0 && sMax > 0 ? toY(0) : null;
		const oneX = pfMin < 1 && pfMax > 1 ? toX(1) : null;
		const dots = pts.map(p => ({ cx: toX(p.pf), cy: toY(p.sortino), color: TF_COL[p.tf] ?? 'var(--ch-axis-muted)' }));
		return { W, H, dots, zeroY, oneX, pfMin: pfMin.toFixed(2), pfMax: pfMax.toFixed(2), sMin: sMin.toFixed(1), sMax: sMax.toFixed(1), total: pts.length };
	});

	const recentRunTopStrategyBySharpe = $derived.by(() => {
		const map: Record<string, number> = {};
		for (const r of recentRuns) {
			if (!r.strategy || r.sharpe == null || !isFinite(r.sharpe)) continue;
			if (map[r.strategy] == null || r.sharpe > map[r.strategy]) map[r.strategy] = r.sharpe;
		}
		const rows = Object.entries(map)
			.map(([strategy, sharpe]) => ({ strategy, sharpe }))
			.filter(r => r.sharpe > -20 && r.sharpe < 50)
			.sort((a, b) => b.sharpe - a.sharpe)
			.slice(0, 10);
		if (rows.length < 3) return null;
		const maxSharpe = Math.max(...rows.map(r => r.sharpe), 0.01);
		return { rows, maxSharpe };
	});

	const recentRunBestCalmarByStrategy = $derived.by(() => {
		const map: Record<string, number> = {};
		for (const r of recentRuns) {
			if (!r.strategy || r.calmar == null || !isFinite(r.calmar) || r.calmar < -50 || r.calmar > 200) continue;
			if (map[r.strategy] == null || r.calmar > map[r.strategy]) map[r.strategy] = r.calmar;
		}
		const rows = Object.entries(map)
			.map(([strategy, calmar]) => ({ strategy, calmar }))
			.sort((a, b) => b.calmar - a.calmar)
			.slice(0, 10);
		if (rows.length < 3) return null;
		const maxCalmar = Math.max(...rows.map(r => Math.max(0, r.calmar)), 0.01);
		return { rows, maxCalmar };
	});

	const recentRunSortinoByTimeframe = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const r of recentRuns) {
			if (!r.timeframe || r.sortino == null || !isFinite(r.sortino) || Math.abs(r.sortino) > 200) continue;
			if (!map[r.timeframe]) map[r.timeframe] = [];
			map[r.timeframe].push(r.sortino);
		}
		const TF_ORDER = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w'];
		const rows = Object.entries(map)
			.filter(([, v]) => v.length >= 1)
			.map(([tf, vals]) => ({
				tf,
				avg: vals.reduce((a, b) => a + b, 0) / vals.length,
				count: vals.length
			}))
			.sort((a, b) => {
				const ai = TF_ORDER.indexOf(a.tf), bi = TF_ORDER.indexOf(b.tf);
				return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
			});
		if (rows.length < 2) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		return { rows, maxAbs };
	});

	const recentRunImportTimeline = $derived.by(() => {
		const map: Record<string, number> = {};
		for (const r of recentRuns) {
			if (!r.imported_at) continue;
			const week = r.imported_at.slice(0, 10);
			// round to nearest Monday
			const d = new Date(week);
			const day = d.getUTCDay();
			const diff = (day === 0 ? -6 : 1 - day);
			d.setUTCDate(d.getUTCDate() + diff);
			const wk = d.toISOString().slice(0, 10);
			map[wk] = (map[wk] ?? 0) + 1;
		}
		const rows = Object.entries(map).sort((a, b) => a[0].localeCompare(b[0])).slice(-16);
		if (rows.length < 3) return null;
		const maxCount = Math.max(...rows.map(r => r[1]), 1);
		const W = 560, H = 72, PAD = 8;
		const barW = Math.max(2, ((W - PAD * 2) / rows.length) - 1);
		const bars = rows.map(([wk, count], i) => {
			const x = PAD + i * ((W - PAD * 2) / rows.length);
			const h = Math.max(2, (count / maxCount) * (H - PAD * 2));
			return { wk, count, x, y: H - PAD - h, h };
		});
		const total = rows.reduce((s, r) => s + r[1], 0);
		return { bars, barW, W, H, total, weeks: rows.length };
	});

	const recentRunWinRateBubble = $derived.by(() => {
		const pts = recentRuns.filter(r =>
			r.win_rate_pct != null && isFinite(r.win_rate_pct) &&
			r.total_profit_pct != null && isFinite(r.total_profit_pct) &&
			r.total_trades != null && r.total_trades > 0
		).map(r => ({ wr: r.win_rate_pct!, profit: r.total_profit_pct!, trades: r.total_trades!, tf: r.timeframe ?? '' }));
		if (pts.length < 6) return null;
		const wrMin = Math.min(...pts.map(p => p.wr)), wrMax = Math.max(...pts.map(p => p.wr), wrMin + 1);
		const pMin = Math.min(...pts.map(p => p.profit)), pMax = Math.max(...pts.map(p => p.profit), pMin + 0.01);
		const tMax = Math.max(...pts.map(p => p.trades), 1);
		const W = 560, H = 150, PAD = 12;
		const TF_COL: Record<string, string> = { '5m': 'var(--ch-violet-light)', '15m': 'var(--ch-profit-light)', '1h': 'var(--ch-warn)', '4h': 'var(--ch-loss-light)', '1d': 'var(--ch-teal-light)' };
		const toX = (w: number) => PAD + ((w - wrMin) / (wrMax - wrMin)) * (W - PAD * 2);
		const toY = (p: number) => H - PAD - ((p - pMin) / (pMax - pMin)) * (H - PAD * 2);
		const zeroY = pMin < 0 && pMax > 0 ? toY(0) : null;
		const bubbles = pts.map(p => ({
			cx: toX(p.wr), cy: toY(p.profit),
			r: Math.max(2, Math.sqrt(p.trades / tMax) * 10),
			color: TF_COL[p.tf] ?? 'var(--ch-axis-muted)'
		}));
		const ideal = pts.filter(p => p.wr > 55 && p.profit > 0).length;
		return { W, H, bubbles, zeroY, wrMin: wrMin.toFixed(0), wrMax: wrMax.toFixed(0), pMin: pMin.toFixed(1), pMax: pMax.toFixed(1), total: pts.length, ideal };
	});

	const recentRunProfitFactorRanking = $derived.by(() => {
		const map: Record<string, number> = {};
		for (const r of data.recent_runs) {
			if (!r.strategy || r.profit_factor == null || !isFinite(r.profit_factor) || r.profit_factor <= 0 || r.profit_factor > 30) continue;
			if (map[r.strategy] == null || r.profit_factor > map[r.strategy]) map[r.strategy] = r.profit_factor;
		}
		const rows = Object.entries(map)
			.map(([strategy, pf]) => ({ strategy, pf }))
			.sort((a, b) => b.pf - a.pf)
			.slice(0, 12);
		if (rows.length < 3) return null;
		const maxPf = Math.max(...rows.map(r => r.pf), 0.01);
		return { rows, maxPf };
	});

	const recentRunDrawdownByTimeframe = $derived.by(() => {
		const TF_ORDER = ['5m', '15m', '1h', '4h', '1d'];
		const map: Record<string, number[]> = {};
		for (const r of data.recent_runs) {
			if (!r.timeframe || r.max_drawdown_pct == null || !isFinite(r.max_drawdown_pct) || r.max_drawdown_pct < 0) continue;
			if (!map[r.timeframe]) map[r.timeframe] = [];
			map[r.timeframe].push(r.max_drawdown_pct);
		}
		const rows = Object.entries(map)
			.filter(([, v]) => v.length >= 3)
			.map(([tf, vals]) => {
				const sorted = [...vals].sort((a, b) => a - b);
				const mid = Math.floor(sorted.length / 2);
				const median = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
				return { tf, median, count: vals.length };
			})
			.sort((a, b) => (TF_ORDER.indexOf(a.tf) === -1 ? 99 : TF_ORDER.indexOf(a.tf)) - (TF_ORDER.indexOf(b.tf) === -1 ? 99 : TF_ORDER.indexOf(b.tf)));
		if (rows.length < 2) return null;
		const maxDD = Math.max(...rows.map(r => r.median), 0.01);
		const W = 400, H = 80, PAD = 8, BAR_W = Math.min(60, Math.floor((W - PAD * 2) / rows.length) - 4);
		return { rows, maxDD, W, H, PAD, BAR_W };
	});

	const recentRunSharpeCalmarsScatter = $derived.by(() => {
		const pts = data.recent_runs
			.filter(r => r.sharpe != null && isFinite(r.sharpe!) && r.calmar != null && isFinite(r.calmar!) && r.total_trades > 0)
			.map(r => ({ sharpe: r.sharpe!, calmar: r.calmar!, trades: r.total_trades, profit: r.total_profit_pct, tf: r.timeframe }));
		if (pts.length < 5) return null;
		const W = 520, H = 100, PAD = 12;
		const mnS = Math.min(...pts.map(p => p.sharpe)), mxS = Math.max(...pts.map(p => p.sharpe), mnS + 0.01);
		const mnC = Math.min(...pts.map(p => p.calmar)), mxC = Math.max(...pts.map(p => p.calmar), mnC + 0.01);
		const mxT = Math.max(...pts.map(p => p.trades));
		const toX = (v: number) => PAD + ((v - mnS) / (mxS - mnS)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mnC) / (mxC - mnC)) * (H - PAD * 2);
		const toR = (t: number) => 3 + (t / mxT) * 6;
		const dots = pts.map(p => ({
			cx: toX(p.sharpe), cy: toY(p.calmar), r: toR(p.trades),
			color: p.profit >= 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)'
		}));
		const zeroX = mnS <= 0 && mxS >= 0 ? toX(0) : null;
		const zeroY = mnC <= 0 && mxC >= 0 ? toY(0) : null;
		return { W, H, dots, zeroX, zeroY, count: pts.length };
	});

	const recentRunProfitFactorDistribution = $derived.by(() => {
		const vals = data.recent_runs
			.filter(r => r.profit_factor != null && isFinite(r.profit_factor!) && r.profit_factor! > 0 && r.profit_factor! < 20)
			.map(r => r.profit_factor!);
		if (vals.length < 6) return null;
		const BUCKETS = 12, mn = 0, mx = Math.min(8, Math.max(...vals));
		const step = (mx - mn) / BUCKETS;
		const counts = Array.from({ length: BUCKETS }, (_, i) => {
			const lo = mn + i * step, hi = lo + step;
			return { lo, hi, count: vals.filter(v => v >= lo && v < hi).length, label: (lo + step / 2).toFixed(1) };
		});
		const maxCount = Math.max(...counts.map(b => b.count), 1);
		const W = 480, H = 70, PAD = 8, barW = Math.floor((W - PAD * 2) / BUCKETS) - 1;
		return { counts, maxCount, W, H, PAD, barW };
	});

	const recentRunTimeframeCalmarTimeline = $derived.by(() => {
		const TFS = ['15m', '1h', '4h', '1d'];
		const TF_COLORS: Record<string, string> = { '15m': 'var(--ch-violet-strong)', '1h': 'var(--ch-profit-strong)', '4h': 'var(--ch-warn)', '1d': 'var(--ch-loss-strong)' };
		const byTF: Record<string, { ts: number; calmar: number }[]> = {};
		for (const r of data.recent_runs) {
			if (!r.timeframe || !TFS.includes(r.timeframe) || r.calmar == null || !isFinite(r.calmar) || r.imported_at == null) continue;
			if (!byTF[r.timeframe]) byTF[r.timeframe] = [];
			byTF[r.timeframe].push({ ts: new Date(r.imported_at).getTime(), calmar: r.calmar });
		}
		const series = TFS.filter(tf => (byTF[tf]?.length ?? 0) >= 3).map(tf => {
			const pts = [...byTF[tf]].sort((a, b) => a.ts - b.ts);
			return { tf, pts, color: TF_COLORS[tf] };
		});
		if (series.length < 2) return null;
		const allPts = series.flatMap(s => s.pts);
		const mnT = Math.min(...allPts.map(p => p.ts)), mxT = Math.max(...allPts.map(p => p.ts));
		const mnC = Math.min(...allPts.map(p => p.calmar)), mxC = Math.max(...allPts.map(p => p.calmar), mnC + 0.01);
		const W = 560, H = 80, PAD = 8;
		const toX = (t: number) => PAD + ((t - mnT) / Math.max(1, mxT - mnT)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - mnC) / (mxC - mnC)) * (H - PAD * 2);
		const polylines = series.map(s => ({ color: s.color, tf: s.tf, pts: s.pts.map(p => `${toX(p.ts).toFixed(1)},${toY(p.calmar).toFixed(1)}`).join(' ') }));
		const zeroY = mnC <= 0 && mxC >= 0 ? toY(0) : null;
		return { W, H, polylines, zeroY };
	});

	const recentRunTopStrategiesByWins = $derived.by(() => {
		const map: Record<string, { wins: number; losses: number; profit: number }> = {};
		for (const r of data.recent_runs) {
			if (!r.strategy || r.wins == null || r.losses == null) continue;
			if (!map[r.strategy]) map[r.strategy] = { wins: 0, losses: 0, profit: 0 };
			map[r.strategy].wins += r.wins ?? 0;
			map[r.strategy].losses += r.losses ?? 0;
			if (r.total_profit_pct != null && isFinite(r.total_profit_pct)) map[r.strategy].profit += r.total_profit_pct;
		}
		const rows = Object.entries(map)
			.filter(([, v]) => v.wins + v.losses >= 5)
			.map(([strategy, v]) => {
				const total = v.wins + v.losses;
				const wr = (v.wins / total) * 100;
				return { strategy: strategy.slice(0, 20), wins: v.wins, losses: v.losses, wr, profit: v.profit };
			})
			.sort((a, b) => b.wins - a.wins)
			.slice(0, 10);
		if (rows.length < 3) return null;
		const maxWins = Math.max(...rows.map(r => r.wins), 1);
		return { rows, maxWins };
	});

	const recentRunSortinoVsDrawdown = $derived.by(() => {
		const pts = recentRuns.filter(r => r.sortino != null && r.max_drawdown_pct != null && isFinite(r.sortino) && r.sortino > 0 && r.sortino < 30);
		if (pts.length < 5) return null;
		const W = 480, H = 130, PAD = 20;
		const maxS = Math.max(...pts.map(p => p.sortino!), 0.01);
		const maxDD = Math.max(...pts.map(p => Math.abs(p.max_drawdown_pct!)), 0.01);
		const toX = (v: number) => PAD + (v / maxS) * (W - PAD * 2);
		const toY = (v: number) => PAD + (Math.abs(v) / maxDD) * (H - PAD * 2);
		const maxTrades = Math.max(...pts.map(p => p.total_trades ?? 1), 1);
		const dots = pts.map(p => ({
			cx: toX(p.sortino!), cy: toY(p.max_drawdown_pct!),
			r: 2 + ((p.total_trades ?? 0) / maxTrades) * 5,
			color: p.sortino! >= 2 ? 'var(--ch-violet)' : p.sortino! >= 1 ? 'var(--ch-profit-light)' : 'var(--ch-warn-light)'
		}));
		return { dots, W, H, PAD, maxS, maxDD, count: pts.length };
	});

	const recentRunTotalTradesByTimeframe = $derived.by(() => {
		const map: Record<string, number[]> = {};
		for (const r of recentRuns) {
			if (!r.timeframe || r.total_trades == null) continue;
			if (!map[r.timeframe]) map[r.timeframe] = [];
			map[r.timeframe].push(r.total_trades);
		}
		const TF_ORD = ['1m','5m','15m','30m','1h','2h','4h','8h','1d'];
		const rows = Object.entries(map)
			.map(([tf, vals]) => ({ tf, avg: vals.reduce((a, b) => a + b, 0) / vals.length, count: vals.length }))
			.sort((a, b) => (TF_ORD.indexOf(a.tf) === -1 ? 99 : TF_ORD.indexOf(a.tf)) - (TF_ORD.indexOf(b.tf) === -1 ? 99 : TF_ORD.indexOf(b.tf)));
		if (rows.length < 2) return null;
		const maxAvg = Math.max(...rows.map(r => r.avg), 1);
		const W = 420, H = 80, PAD = 8, barW = Math.min(55, Math.floor((W - PAD * 2) / rows.length) - 3);
		return { rows, maxAvg, W, H, PAD, barW };
	});

	const recentRunImportFrequency = $derived.by(() => {
		const map: Record<string, number> = {};
		for (const r of recentRuns) {
			if (!r.imported_at) continue;
			const d = new Date(r.imported_at);
			const key = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
			map[key] = (map[key] ?? 0) + 1;
		}
		const months = Object.keys(map).sort().slice(-12);
		if (months.length < 3) return null;
		const rows = months.map(m => ({ label: m.slice(5), count: map[m] }));
		const maxCount = Math.max(...rows.map(r => r.count), 1);
		const W = 420, H = 70, PAD = 8, barW = Math.min(28, Math.floor((W - PAD * 2) / rows.length) - 2);
		return { rows, maxCount, W, H, PAD, barW };
	});

	const recentRunAvgProfitByPairCount = $derived.by(() => {
		const bins = [
			{ lo: 1, hi: 5, label: '1-5' },
			{ lo: 6, hi: 10, label: '6-10' },
			{ lo: 11, hi: 20, label: '11-20' },
			{ lo: 21, hi: 50, label: '21-50' },
			{ lo: 51, hi: 999, label: '51+' },
		];
		const groups = bins.map(b => {
			const rs = data.recent_runs.filter(r => r.pairs && r.pairs.length >= b.lo && r.pairs.length <= b.hi && r.total_profit_pct != null && isFinite(r.total_profit_pct!));
			const avg = rs.length > 0 ? rs.reduce((a, r) => a + r.total_profit_pct!, 0) / rs.length : 0;
			return { label: b.label, avg, count: rs.length };
		}).filter(g => g.count >= 2);
		if (groups.length < 2) return null;
		const maxAbs = Math.max(...groups.map(g => Math.abs(g.avg)), 0.01);
		const W = 320, H = 80, PAD = 10, barW = Math.max(30, Math.floor((W - PAD * 2) / groups.length) - 6), midY = H / 2;
		return { groups, maxAbs, W, H, PAD, barW, midY };
	});

	const recentRunDurationDistribution = $derived.by(() => {
		const vals = data.recent_runs
			.filter(r => r.duration_sec != null && r.duration_sec > 0 && isFinite(r.duration_sec))
			.map(r => r.duration_sec! / 60);
		if (vals.length < 5) return null;
		const mn = 0, mx = Math.min(Math.max(...vals), 1440);
		const bins = 12, step = (mx - mn) / bins || 1;
		const counts = Array.from({ length: bins }, (_, i) => {
			const lo = mn + i * step, hi = lo + step;
			return { lo, count: vals.filter(v => v >= lo && (i === bins - 1 ? v <= mx : v < hi)).length };
		});
		const maxCount = Math.max(...counts.map(c => c.count), 1);
		const W = 380, H = 68, PAD = 8, barW = Math.floor((W - PAD * 2) / bins) - 1;
		const avg = (vals.reduce((a, b) => a + b, 0) / vals.length);
		const avgLabel = avg >= 60 ? `${(avg / 60).toFixed(1)}h` : `${avg.toFixed(0)}m`;
		return { counts, maxCount, W, H, PAD, barW, mnLabel: '0', mxLabel: mx >= 60 ? `${(mx/60).toFixed(0)}h` : `${mx.toFixed(0)}m`, avgLabel, total: vals.length };
	});

	const recentRunStrategyActivityMap = $derived.by(() => {
		const map = new Map<string, { count: number; lastProfit: number | null; profitable: number }>();
		for (const r of data.recent_runs) {
			if (!r.strategy) continue;
			const strat = r.strategy.slice(0, 18);
			if (!map.has(strat)) map.set(strat, { count: 0, lastProfit: null, profitable: 0 });
			const e = map.get(strat)!;
			e.count++;
			if (r.total_profit_pct != null && isFinite(r.total_profit_pct)) {
				if (e.lastProfit === null) e.lastProfit = r.total_profit_pct;
				if (r.total_profit_pct > 0) e.profitable++;
			}
		}
		const rows = [...map.entries()]
			.map(([strat, e]) => ({ strat, count: e.count, lastProfit: e.lastProfit, passRate: e.count > 0 ? (e.profitable / e.count) * 100 : 0 }))
			.sort((a, b) => b.count - a.count)
			.slice(0, 14);
		if (rows.length < 3) return null;
		const maxCount = Math.max(...rows.map(r => r.count), 1);
		return { rows, maxCount };
	});

	const recentRunSortinoRanking = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of data.recent_runs) {
			if (!r.strategy || r.sortino == null || !isFinite(r.sortino) || r.sortino > 200) continue;
			if (!map.has(r.strategy)) map.set(r.strategy, []);
			map.get(r.strategy)!.push(r.sortino);
		}
		const rows = [...map.entries()]
			.filter(([, vals]) => vals.length >= 2)
			.map(([strat, vals]) => {
				const sorted = [...vals].sort((a, b) => a - b);
				const mid = Math.floor(sorted.length / 2);
				const med = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
				return { strat: strat.slice(0, 20), sortino: med, count: vals.length };
			})
			.sort((a, b) => b.sortino - a.sortino)
			.slice(0, 12);
		if (rows.length < 3) return null;
		const maxSortino = Math.max(...rows.map(r => r.sortino), 0.01);
		return { rows, maxSortino };
	});

	const recentRunCalmarVsWinRate = $derived.by(() => {
		const pts = data.recent_runs.filter(r =>
			r.calmar != null && isFinite(r.calmar) && r.calmar < 100 &&
			r.win_rate != null && isFinite(r.win_rate) &&
			r.trades_count != null && r.trades_count >= 5
		).map(r => ({ calmar: r.calmar!, win: r.win_rate! * 100, trades: r.trades_count! }));
		if (pts.length < 8) return null;
		const cMin = Math.min(...pts.map(p => p.calmar)), cMax = Math.max(...pts.map(p => p.calmar), cMin + 0.1);
		const wMin = Math.min(...pts.map(p => p.win)), wMax = Math.max(...pts.map(p => p.win), wMin + 0.1);
		const tMax = Math.max(...pts.map(p => p.trades), 1);
		const W = 380, H = 100, PAD = 12;
		const toX = (v: number) => PAD + ((v - wMin) / (wMax - wMin)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - (v - cMin) / (cMax - cMin)) * (H - PAD * 2);
		const toR = (t: number) => 2 + (t / tMax) * 5;
		const dots = pts.map(p => ({ cx: toX(p.win), cy: toY(p.calmar), r: toR(p.trades), color: p.calmar >= 1 ? 'var(--ch-profit-light)' : p.calmar >= 0 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)' }));
		return { dots, W, H, PAD, wMin: wMin.toFixed(0), wMax: wMax.toFixed(0), cMin: cMin.toFixed(1), cMax: cMax.toFixed(1), count: pts.length };
	});

	const recentRunProfitFactorVsCalmar = $derived.by(() => {
		const pts = data.recent_runs.filter(r =>
			r.profit_factor != null && isFinite(r.profit_factor) && r.profit_factor < 20 &&
			r.calmar != null && isFinite(r.calmar) && r.calmar < 50 && r.calmar > -20
		).map(r => ({ pf: r.profit_factor!, calmar: r.calmar!, profit: r.total_profit_pct ?? 0 }));
		if (pts.length < 8) return null;
		const pfMin = Math.min(...pts.map(p => p.pf)), pfMax = Math.max(...pts.map(p => p.pf), pfMin + 0.1);
		const cMin = Math.min(...pts.map(p => p.calmar)), cMax = Math.max(...pts.map(p => p.calmar), cMin + 0.1);
		const W = 380, H = 100, PAD = 12;
		const toX = (v: number) => PAD + ((v - pfMin) / (pfMax - pfMin)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - (v - cMin) / (cMax - cMin)) * (H - PAD * 2);
		const dots = pts.map(p => ({ cx: toX(p.pf), cy: toY(p.calmar), color: p.profit >= 10 ? 'var(--ch-profit)' : p.profit >= 0 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)' }));
		return { dots, W, H, PAD, pfMin: pfMin.toFixed(1), pfMax: pfMax.toFixed(1), cMin: cMin.toFixed(1), cMax: cMax.toFixed(1), count: pts.length };
	});

	const recentRunDurationVsCalmar = $derived.by(() => {
		const pts = data.recent_runs.filter(r =>
			r.avg_duration_minutes != null && isFinite(r.avg_duration_minutes) && r.avg_duration_minutes > 0 &&
			r.calmar != null && isFinite(r.calmar) && r.calmar < 50 && r.calmar > -20
		).map(r => ({ dur: r.avg_duration_minutes! / 60, calmar: r.calmar!, profit: r.total_profit_pct ?? 0 }));
		if (pts.length < 8) return null;
		const dMin = Math.min(...pts.map(p => p.dur)), dMax = Math.max(...pts.map(p => p.dur), dMin + 0.1);
		const cMin = Math.min(...pts.map(p => p.calmar)), cMax = Math.max(...pts.map(p => p.calmar), cMin + 0.1);
		const W = 380, H = 95, PAD = 12;
		const toX = (v: number) => PAD + ((v - dMin) / (dMax - dMin)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - (v - cMin) / (cMax - cMin)) * (H - PAD * 2);
		const zeroY = Math.max(PAD, Math.min(H - PAD, toY(0)));
		const dots = pts.map(p => ({ cx: toX(p.dur), cy: toY(p.calmar), color: p.calmar >= 1 ? 'var(--ch-profit-light)' : p.calmar >= 0 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)' }));
		return { dots, W, H, PAD, zeroY, dMin: dMin.toFixed(0), dMax: dMax.toFixed(0), cMin: cMin.toFixed(1), cMax: cMax.toFixed(1), count: pts.length };
	});

	const recentRunMonthlyProfitTrend = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of data.recent_runs) {
			if (!r.run_date || r.total_profit_pct == null || !isFinite(r.total_profit_pct)) continue;
			const mo = r.run_date.slice(0, 7);
			if (!map.has(mo)) map.set(mo, []);
			map.get(mo)!.push(r.total_profit_pct);
		}
		const months = [...map.keys()].sort();
		if (months.length < 3) return null;
		const pts = months.map((mo, i) => {
			const vals = map.get(mo)!;
			return { i, mo: mo.slice(5), avg: vals.reduce((a, v) => a + v, 0) / vals.length, count: vals.length };
		});
		const mn = Math.min(...pts.map(p => p.avg)), mx = Math.max(...pts.map(p => p.avg), mn + 0.1);
		const W = 380, H = 72, PAD = 10;
		const toX = (i: number) => PAD + (i / Math.max(pts.length - 1, 1)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - (v - mn) / (mx - mn)) * (H - PAD * 2);
		const zeroY = Math.max(PAD, Math.min(H - PAD, toY(0)));
		const poly = pts.map(p => `${toX(p.i).toFixed(1)},${toY(p.avg).toFixed(1)}`).join(' ');
		const area = poly + ` ${toX(pts.length - 1).toFixed(1)},${H - PAD} ${toX(0).toFixed(1)},${H - PAD}`;
		return { pts, poly, area, W, H, PAD, zeroY };
	});

	const recentRunTopPairsByFrequency = $derived.by(() => {
		const pairCount = new Map<string, { count: number; profits: number[] }>();
		for (const r of data.recent_runs) {
			if (!r.pairs || !Array.isArray(r.pairs)) continue;
			for (const pair of r.pairs as string[]) {
				if (!pairCount.has(pair)) pairCount.set(pair, { count: 0, profits: [] });
				const e = pairCount.get(pair)!;
				e.count++;
				if (r.total_profit_pct != null && isFinite(r.total_profit_pct)) e.profits.push(r.total_profit_pct);
			}
		}
		const rows = [...pairCount.entries()]
			.filter(([, e]) => e.count >= 2)
			.map(([pair, e]) => ({ pair: pair.slice(0, 12), count: e.count, avgProfit: e.profits.length ? e.profits.reduce((a, v) => a + v, 0) / e.profits.length : 0 }))
			.sort((a, b) => b.count - a.count)
			.slice(0, 10);
		if (rows.length < 3) return null;
		const maxCount = Math.max(...rows.map(r => r.count), 1);
		const W = 360, H = rows.length * 16 + 4, barMaxW = W - 110;
		return { rows, maxCount, W, H, barMaxW };
	});

	const recentRunSharpeVsSortino = $derived.by(() => {
		const pts = data.recent_runs.filter(r =>
			r.sharpe != null && isFinite(r.sharpe) && Math.abs(r.sharpe) < 50 &&
			r.sortino != null && isFinite(r.sortino) && Math.abs(r.sortino) < 100 &&
			r.total_profit_pct != null && isFinite(r.total_profit_pct)
		).map(r => ({ sharpe: r.sharpe!, sortino: r.sortino!, profit: r.total_profit_pct! }));
		if (pts.length < 8) return null;
		const sMin = Math.min(...pts.map(p => p.sharpe)), sMax = Math.max(...pts.map(p => p.sharpe), sMin + 0.1);
		const soMin = Math.min(...pts.map(p => p.sortino)), soMax = Math.max(...pts.map(p => p.sortino), soMin + 0.1);
		const W = 360, H = 92, PAD = 12;
		const toX = (v: number) => PAD + ((v - sMin) / (sMax - sMin)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - (v - soMin) / (soMax - soMin)) * (H - PAD * 2);
		const zeroX = Math.max(PAD, Math.min(W - PAD, toX(0)));
		const zeroY = Math.max(PAD, Math.min(H - PAD, toY(0)));
		const dots = pts.map(p => ({ cx: toX(p.sharpe), cy: toY(p.sortino), color: p.profit >= 10 ? 'var(--ch-profit-light)' : p.profit >= 0 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)' }));
		return { dots, W, H, PAD, zeroX, zeroY, sMin: sMin.toFixed(1), sMax: sMax.toFixed(1), soMin: soMin.toFixed(1), soMax: soMax.toFixed(1), count: pts.length };
	});

	const recentRunCalmarHistogram = $derived.by(() => {
		const vals = data.recent_runs.filter(r => r.calmar != null && isFinite(r.calmar) && r.calmar > -50 && r.calmar < 200).map(r => r.calmar!);
		if (vals.length < 8) return null;
		const mn = Math.min(...vals), mx = Math.max(...vals);
		const bins = 12;
		const binSize = (mx - mn) / bins || 1;
		const buckets = Array.from({ length: bins }, (_, i) => ({ lo: mn + i * binSize, hi: mn + (i + 1) * binSize, count: 0 }));
		for (const v of vals) {
			const bi = Math.min(bins - 1, Math.floor((v - mn) / binSize));
			buckets[bi].count++;
		}
		const maxC = Math.max(...buckets.map(b => b.count), 1);
		const W = 360, H = 72, PAD = 10;
		const bw = (W - PAD * 2) / bins - 2;
		const bars = buckets.map((b, i) => ({
			x: PAD + i * ((W - PAD * 2) / bins),
			h: Math.max(2, (b.count / maxC) * (H - PAD - 14)),
			count: b.count,
			lo: b.lo,
			color: b.lo >= 2 ? 'var(--ch-profit)' : b.lo >= 0 ? 'var(--ch-warn-light)' : 'var(--ch-loss-light)',
		}));
		const zeroX = PAD + Math.max(0, Math.min(bins - 1, Math.floor((0 - mn) / binSize))) * ((W - PAD * 2) / bins);
		return { bars, bw, W, H, PAD, maxC, zeroX, mn: mn.toFixed(1), mx: mx.toFixed(1), total: vals.length };
	});

	const recentRunTopStrategyCalmar = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of data.recent_runs) {
			if (!r.strategy || r.calmar == null || !isFinite(r.calmar) || r.calmar > 500) continue;
			const arr = map.get(r.strategy) ?? [];
			arr.push(r.calmar);
			map.set(r.strategy, arr);
		}
		if (map.size < 3) return null;
		const rows = [...map.entries()].map(([strat, calmars]) => ({
			strat: strat.slice(0, 18),
			best: Math.max(...calmars),
			count: calmars.length,
		})).sort((a, b) => b.best - a.best).slice(0, 8);
		const maxVal = Math.max(...rows.map(r => r.best), 0.01);
		const W = 340, H = rows.length * 16 + 6, PAD = 8, barMaxW = W - 100;
		return { rows, maxVal, W, H, PAD, barMaxW };
	});

	const recentRunProfitByDayOfWeek = $derived.by(() => {
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const map = new Map<number, number[]>();
		for (const r of data.recent_runs) {
			if (!r.imported_at || r.total_profit_pct == null || !isFinite(r.total_profit_pct)) continue;
			const dow = new Date(r.imported_at).getDay();
			const arr = map.get(dow) ?? [];
			arr.push(r.total_profit_pct);
			map.set(dow, arr);
		}
		if (map.size < 3) return null;
		const rows = [0, 1, 2, 3, 4, 5, 6].filter(d => map.has(d)).map(d => ({
			day: DAYS[d], avg: map.get(d)!.reduce((a, v) => a + v, 0) / map.get(d)!.length, count: map.get(d)!.length,
		}));
		if (rows.length < 3) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 360, H = 72, PAD = 10;
		const bw = Math.max(4, Math.floor((W - PAD * 2) / rows.length) - 3);
		const midY = H / 2;
		const bars = rows.map((r, i) => ({
			x: PAD + i * ((W - PAD * 2) / rows.length),
			h: Math.max(2, (Math.abs(r.avg) / maxAbs) * (midY - PAD - 4)),
			avg: r.avg, day: r.day, count: r.count,
			color: r.avg >= 0 ? 'var(--ch-profit)' : 'var(--ch-loss)',
		}));
		return { bars, bw, W, H, PAD, midY };
	});

	const recentRunDrawdownHistogram = $derived.by(() => {
		const vals = data.recent_runs.filter(r => r.max_drawdown_pct != null && isFinite(r.max_drawdown_pct) && r.max_drawdown_pct >= 0 && r.max_drawdown_pct <= 100)
			.map(r => r.max_drawdown_pct!);
		if (vals.length < 8) return null;
		const mx = Math.max(...vals);
		const bins = 12;
		const binSize = mx / bins || 1;
		const buckets = Array.from({ length: bins }, (_, i) => ({ lo: i * binSize, count: 0 }));
		for (const v of vals) {
			const bi = Math.min(bins - 1, Math.floor(v / binSize));
			buckets[bi].count++;
		}
		const maxC = Math.max(...buckets.map(b => b.count), 1);
		const W = 360, H = 68, PAD = 10;
		const bw = (W - PAD * 2) / bins - 1;
		const bars = buckets.map((b, i) => ({
			x: PAD + i * ((W - PAD * 2) / bins),
			h: Math.max(2, (b.count / maxC) * (H - PAD - 16)),
			color: b.lo <= 10 ? 'var(--ch-profit)' : b.lo <= 25 ? 'var(--ch-warn)' : 'var(--ch-loss)',
		}));
		return { bars, bw, W, H, PAD, mx: mx.toFixed(1), total: vals.length };
	});

	const recentRunMonthlyWinRateTrend = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of data.recent_runs) {
			if (!r.imported_at || r.win_rate_pct == null || !isFinite(r.win_rate_pct)) continue;
			const key = r.imported_at.slice(0, 7);
			const arr = map.get(key) ?? [];
			arr.push(r.win_rate_pct);
			map.set(key, arr);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const pts = months.map(m => ({ m, avg: map.get(m)!.reduce((a, v) => a + v, 0) / map.get(m)!.length }));
		const minY = Math.min(...pts.map(p => p.avg), 0), maxY = Math.max(...pts.map(p => p.avg), 100);
		const W = 360, H = 64, PAD = 8;
		const toX = (i: number) => PAD + (i / (pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - minY) / (maxY - minY)) * (H - PAD * 2);
		const points = pts.map((p, i) => `${toX(i)},${toY(p.avg)}`).join(' ');
		const area = `${toX(0)},${H - PAD} ` + points + ` ${toX(pts.length - 1)},${H - PAD}`;
		const baselineY = toY(50);
		return { pts, points, area, baselineY, W, H, PAD, toX, minY, maxY };
	});

	const recentRunSharpeTimeline = $derived.by(() => {
		const pts = data.recent_runs
			.filter(r => r.imported_at && r.sharpe_ratio != null && isFinite(r.sharpe_ratio))
			.sort((a, b) => a.imported_at!.localeCompare(b.imported_at!))
			.map(r => ({ t: r.imported_at!.slice(0, 10), s: r.sharpe_ratio! }));
		if (pts.length < 6) return null;
		const minS = Math.min(...pts.map(p => p.s));
		const maxS = Math.max(...pts.map(p => p.s));
		const range = maxS - minS || 1;
		const W = 360, H = 64, PAD = 10;
		const toX = (i: number) => PAD + (i / (pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => PAD + ((maxS - v) / range) * (H - PAD * 2);
		const polyline = pts.map((p, i) => `${toX(i)},${toY(p.s)}`).join(' ');
		const zeroY = toY(0);
		const area = `${toX(0)},${Math.min(H - PAD, Math.max(PAD, zeroY))} ` + pts.map((p, i) => `${toX(i)},${toY(p.s)}`).join(' ') + ` ${toX(pts.length - 1)},${Math.min(H - PAD, Math.max(PAD, zeroY))}`;
		const lastS = pts[pts.length - 1].s;
		const color = lastS >= 1 ? 'var(--ch-profit-strong)' : lastS >= 0 ? 'var(--ch-warn)' : 'var(--ch-loss-strong)';
		const fillColor = lastS >= 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)';
		return { polyline, area, W, H, PAD, color, fillColor, zeroY: Math.max(PAD, Math.min(H - PAD, zeroY)), minS: minS.toFixed(2), maxS: maxS.toFixed(2), lastS: lastS.toFixed(2), firstDate: pts[0].t, lastDate: pts[pts.length - 1].t };
	});

	const recentRunTopTimeframesByWinRate = $derived.by(() => {
		const map = new Map<string, number[]>();
		for (const r of data.recent_runs) {
			if (!r.timeframe || r.win_rate_pct == null || !isFinite(r.win_rate_pct)) continue;
			const arr = map.get(r.timeframe) ?? [];
			arr.push(r.win_rate_pct);
			map.set(r.timeframe, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([tf, vals]) => ({ tf, avg: vals.reduce((a, v) => a + v, 0) / vals.length, count: vals.length }))
			.sort((a, b) => b.avg - a.avg);
		const maxAvg = Math.max(...rows.map(r => r.avg), 0.01);
		const W = 300, H = rows.length * 18 + 8, PAD = 8, barMaxW = W - 80;
		return { rows, maxAvg, W, H, PAD, barMaxW };
	});

	const recentRunProfitVsDrawdownScatter = $derived.by(() => {
		if (!recentRuns || recentRuns.length < 8) return null;
		const pts = recentRuns
			.filter(r => r.profit_total_pct != null && r.max_drawdown_pct != null)
			.map(r => ({ x: r.max_drawdown_pct as number, y: r.profit_total_pct as number }));
		if (pts.length < 6) return null;
		const xMax = Math.max(...pts.map(p => p.x), 0.01);
		const yMin = Math.min(...pts.map(p => p.y), 0);
		const yMax = Math.max(...pts.map(p => p.y), 0.01);
		const W = 320, H = 110, PAD = 14;
		const toX = (v: number) => PAD + (v / xMax) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - yMin) / (yMax - yMin)) * (H - PAD * 2);
		const zeroY = toY(0);
		return { pts, W, H, PAD, toX, toY, zeroY, xMax: xMax.toFixed(1), yMax: yMax.toFixed(1), yMin: yMin.toFixed(1) };
	});

	const recentRunBestSharpeByTF = $derived.by(() => {
		if (!recentRuns || recentRuns.length < 6) return null;
		const map = new Map<string, number>();
		for (const r of recentRuns) {
			if (!r.timeframe || r.sharpe_ratio == null) continue;
			const cur = map.get(r.timeframe) ?? -Infinity;
			if ((r.sharpe_ratio as number) > cur) map.set(r.timeframe, r.sharpe_ratio as number);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([tf, best]) => ({ tf, best }))
			.sort((a, b) => b.best - a.best);
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.best)), 0.01);
		const W = 320, H = rows.length * 18 + 8, PAD = 8, barMaxW = W - 80;
		const zeroX = PAD + (maxAbs / (2 * maxAbs)) * barMaxW;
		return { rows, W, H, PAD, barMaxW, zeroX, maxAbs };
	});

	const recentRunCountByTFMonth = $derived.by(() => {
		if (!recentRuns || recentRuns.length < 8) return null;
		const tfs = [...new Set(recentRuns.filter(r => r.timeframe).map(r => r.timeframe as string))].sort();
		if (tfs.length < 2) return null;
		const months = [...new Set(recentRuns.filter(r => r.run_date).map(r => (r.run_date as string).slice(0, 7)))].sort().slice(-6);
		if (months.length < 2) return null;
		const grid = tfs.map(tf => months.map(mo => recentRuns.filter(r => r.timeframe === tf && (r.run_date as string)?.startsWith(mo)).length));
		const maxCount = Math.max(...grid.flat(), 1);
		const cellW = 28, cellH = 14, PAD = 8, labelW = 30;
		const W = labelW + months.length * cellW + PAD * 2;
		const H = tfs.length * cellH + PAD * 2 + 12;
		return { tfs, months: months.map(m => m.slice(5)), grid, W, H, PAD, cellW, cellH, labelW, maxCount };
	});

	const recentRunCalmarMonthly = $derived.by(() => {
		if (!recentRuns || recentRuns.length < 6) return null;
		const map = new Map<string, number[]>();
		for (const r of recentRuns) {
			if (!r.run_date || r.calmar_ratio == null) continue;
			const mo = (r.run_date as string).slice(0, 7);
			const arr = map.get(mo) ?? [];
			arr.push(r.calmar_ratio as number);
			map.set(mo, arr);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const pts = months.map(m => { const arr = map.get(m)!; return { m: m.slice(5), avg: arr.reduce((a, v) => a + v, 0) / arr.length }; });
		const maxV = Math.max(...pts.map(p => p.avg), 0.01);
		const minV = Math.min(...pts.map(p => p.avg), 0);
		const range = maxV - minV || 0.01;
		const W = 380, H = 68, PAD = 10;
		const toX = (i: number) => PAD + (i / (pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => PAD + ((maxV - v) / range) * (H - PAD * 2);
		const zeroY = Math.max(PAD, Math.min(H - PAD, toY(0)));
		const polyline = pts.map((p, i) => `${toX(i)},${toY(p.avg)}`).join(' ');
		const area = `${toX(0)},${zeroY} ${polyline} ${toX(pts.length - 1)},${zeroY}`;
		const last = pts[pts.length - 1].avg;
		const color = last >= 1 ? 'var(--ch-profit-strong)' : last >= 0 ? 'var(--ch-warn)' : 'var(--ch-loss-strong)';
		return { pts, polyline, area, W, H, PAD, toX, zeroY, color, fillColor: last >= 0 ? 'var(--ch-profit-light)' : 'var(--ch-loss-light)', last: last.toFixed(2), firstMo: pts[0].m, lastMo: pts[pts.length - 1].m };
	});

	const recentRunSortinoByTF = $derived.by(() => {
		if (!runs || runs.length < 6) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.timeframe || r.sortino_ratio == null) continue;
			const arr = map.get(r.timeframe as string) ?? [];
			arr.push(r.sortino_ratio as number);
			map.set(r.timeframe as string, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([tf, vals]) => ({ tf, avg: vals.reduce((a, v) => a + v, 0) / vals.length }))
			.sort((a, b) => b.avg - a.avg);
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 300, H = rows.length * 20 + 6, PAD = 8, barMaxW = W - 50;
		const zeroX = PAD + (barMaxW / 2);
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const recentRunProfitByStrategy = $derived.by(() => {
		if (!runs || runs.length < 6) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.strategy_name || r.profit_total_pct == null) continue;
			const arr = map.get(r.strategy_name as string) ?? [];
			arr.push(r.profit_total_pct as number);
			map.set(r.strategy_name as string, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([name, vals]) => ({ name: name.slice(0, 16), avg: vals.reduce((a, v) => a + v, 0) / vals.length, count: vals.length }))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 10);
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 320, H = rows.length * 16 + 6, PAD = 8, barMaxW = W - 100;
		const zeroX = PAD + (barMaxW / 2);
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const recentRunWinRateByMonth = $derived.by(() => {
		if (!runs || runs.length < 6) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.created_at || r.win_rate == null) continue;
			const mo = (r.created_at as string).slice(0, 7);
			const arr = map.get(mo) ?? [];
			arr.push((r.win_rate as number) * 100);
			map.set(mo, arr);
		}
		if (map.size < 3) return null;
		const months = [...map.keys()].sort();
		const pts = months.map(m => { const arr = map.get(m)!; return { m: m.slice(5), avg: arr.reduce((a, v) => a + v, 0) / arr.length }; });
		const W = 340, H = 68, PAD = 8;
		const bw = (W - PAD * 2) / pts.length - 1;
		const maxV = 100;
		const fiftyY = H - PAD - ((50 / maxV) * (H - PAD * 2));
		return { pts, W, H, PAD, bw, maxV, fiftyY };
	});

	const recentRunDrawdownByStrategy = $derived.by(() => {
		if (!runs || runs.length < 6) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.strategy_name || r.max_drawdown_pct == null) continue;
			const arr = map.get(r.strategy_name as string) ?? [];
			arr.push(r.max_drawdown_pct as number);
			map.set(r.strategy_name as string, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([name, vals]) => ({ name: name.slice(0, 16), avg: vals.reduce((a, v) => a + v, 0) / vals.length }))
			.sort((a, b) => a.avg - b.avg)
			.slice(0, 10);
		const maxDD = Math.max(...rows.map(r => r.avg), 0.01);
		const W = 320, H = rows.length * 16 + 6, PAD = 8, barMaxW = W - 100;
		return { rows, maxDD, W, H, PAD, barMaxW };
	});

	const recentRunCalmarByPairCount = $derived.by(() => {
		if (!runs || runs.length < 8) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (r.paircount == null || r.calmar_ratio == null) continue;
			const pc = r.paircount as number;
			const bucket = pc <= 5 ? '1-5' : pc <= 10 ? '6-10' : pc <= 20 ? '11-20' : '20+';
			const arr = map.get(bucket) ?? [];
			arr.push(r.calmar_ratio as number);
			map.set(bucket, arr);
		}
		if (map.size < 2) return null;
		const ORDER = ['1-5', '6-10', '11-20', '20+'];
		const rows = ORDER.filter(k => map.has(k)).map(k => {
			const vals = map.get(k)!;
			return { k, avg: vals.reduce((a, v) => a + v, 0) / vals.length };
		});
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 320, H = 64, PAD = 8;
		const bw = (W - PAD * 2) / rows.length - 2;
		const midY = H / 2;
		return { rows, maxAbs, W, H, PAD, bw, midY };
	});

	const recentRunProfitCDF = $derived.by(() => {
		if (!runs || runs.length < 15) return null;
		const profits = runs
			.filter(r => r.profit_total_pct != null)
			.map(r => r.profit_total_pct as number)
			.sort((a, b) => a - b);
		if (profits.length < 15) return null;
		const minP = profits[0], maxP = profits[profits.length - 1];
		const range = maxP - minP || 0.01;
		const W = 340, H = 80, PAD = 10;
		const toX = (p: number) => PAD + ((p - minP) / range) * (W - PAD * 2);
		const toY = (i: number) => H - PAD - (i / (profits.length - 1)) * (H - PAD * 2);
		const polyline = profits.map((p, i) => `${toX(p)},${toY(i)}`).join(' ');
		const zeroX = toX(0);
		const median = profits[Math.floor(profits.length * 0.5)];
		return { polyline, W, H, PAD, zeroX, minP: minP.toFixed(1), maxP: maxP.toFixed(1), median: median.toFixed(1) };
	});

	const recentRunSortinoVsCalmarScatter = $derived.by(() => {
		if (!runs || runs.length < 10) return null;
		const pts = runs
			.filter(r => r.sortino != null && r.calmar_ratio != null)
			.map(r => ({ sortino: r.sortino as number, calmar: r.calmar_ratio as number, profit: r.profit_total_pct as number ?? 0 }));
		if (pts.length < 8) return null;
		const soMin = Math.min(...pts.map(p => p.sortino));
		const soMax = Math.max(...pts.map(p => p.sortino), 0.01);
		const caMin = Math.min(...pts.map(p => p.calmar));
		const caMax = Math.max(...pts.map(p => p.calmar), 0.01);
		const soRange = soMax - soMin || 0.01;
		const caRange = caMax - caMin || 0.01;
		const W = 320, H = 80, PAD = 10;
		const toX = (s: number) => PAD + ((s - soMin) / soRange) * (W - PAD * 2);
		const toY = (c: number) => H - PAD - ((c - caMin) / caRange) * (H - PAD * 2);
		const zeroX = toX(0), zeroY = toY(0);
		return { pts, W, H, PAD, toX, toY, zeroX, zeroY };
	});

	const recentRunProfitByTimeframeBucket = $derived.by(() => {
		if (!runs || runs.length < 8) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.timeframe || r.profit_total_pct == null) continue;
			const arr = map.get(r.timeframe as string) ?? [];
			arr.push(r.profit_total_pct as number);
			map.set(r.timeframe as string, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([tf, vals]) => ({ tf, avg: vals.reduce((a, v) => a + v, 0) / vals.length, n: vals.length }))
			.sort((a, b) => b.avg - a.avg);
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 320, H = rows.length * 20 + 6, PAD = 8, barMaxW = W - 40;
		const zeroX = PAD + barMaxW / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const recentRunDrawdownVsTradeCount = $derived.by(() => {
		if (!runs || runs.length < 8) return null;
		const pts = runs
			.filter(r => r.max_drawdown_pct != null && r.trade_count != null)
			.map(r => ({ dd: r.max_drawdown_pct as number, tc: r.trade_count as number }));
		if (pts.length < 6) return null;
		const minDD = Math.min(...pts.map(p => p.dd)), maxDD = Math.max(...pts.map(p => p.dd), minDD + 1);
		const minTC = Math.min(...pts.map(p => p.tc)), maxTC = Math.max(...pts.map(p => p.tc), minTC + 1);
		const W = 300, H = 80, PAD = 10;
		const toX = (v: number) => PAD + ((v - minDD) / (maxDD - minDD)) * (W - PAD * 2);
		const toY = (v: number) => PAD + (1 - (v - minTC) / (maxTC - minTC)) * (H - PAD * 2);
		return { pts, toX, toY, W, H, PAD, minDD: minDD.toFixed(1), maxDD: maxDD.toFixed(1) };
	});

	const recentRunSortinoHistogram = $derived.by(() => {
		if (!runs || runs.length < 8) return null;
		const vals = runs.filter(r => r.sortino_ratio != null).map(r => r.sortino_ratio as number);
		if (vals.length < 5) return null;
		const minV = Math.min(...vals), maxV = Math.max(...vals, minV + 0.1);
		const BINS = 10;
		const step = (maxV - minV) / BINS;
		const counts = Array(BINS).fill(0);
		for (const v of vals) {
			const bi = Math.min(Math.floor((v - minV) / step), BINS - 1);
			counts[bi]++;
		}
		const maxCount = Math.max(...counts, 1);
		const W = 300, H = 60, PAD = 8;
		const bw = (W - PAD * 2) / BINS - 1;
		return { counts, maxCount, minV: minV.toFixed(2), maxV: maxV.toFixed(2), W, H, PAD, bw, step, BINS };
	});

	const recentRunTopCalmarLeaderboard = $derived.by(() => {
		if (!runs || runs.length < 5) return null;
		const map = new Map<string, number>();
		for (const r of runs) {
			if (!r.strategy || r.calmar_ratio == null) continue;
			const name = r.strategy as string;
			if (!map.has(name) || (r.calmar_ratio as number) > map.get(name)!) map.set(name, r.calmar_ratio as number);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()].map(([name, best]) => ({ name: name.slice(0, 20), best })).sort((a, b) => b.best - a.best).slice(0, 8);
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.best)), 0.01);
		const W = 300, H = rows.length * 18 + 10, PAD = 8, barMaxW = W - PAD * 2 - 80;
		const zeroX = PAD + 80 + barMaxW / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const recentRunProfitFactorByTF = $derived.by(() => {
		if (!runs || runs.length < 5) return null;
		const map = new Map<string, { wins: number[]; losses: number[] }>();
		for (const r of runs) {
			if (!r.timeframe || r.profit_total_pct == null) continue;
			const tf = r.timeframe as string;
			const s = map.get(tf) ?? { wins: [], losses: [] };
			const p = r.profit_total_pct as number;
			if (p > 0) s.wins.push(p); else s.losses.push(Math.abs(p));
			map.set(tf, s);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.filter(([, s]) => s.wins.length + s.losses.length >= 3)
			.map(([tf, s]) => {
				const grossWin = s.wins.reduce((a, v) => a + v, 0);
				const grossLoss = s.losses.reduce((a, v) => a + v, 0) || 0.001;
				return { tf, pf: grossWin / grossLoss };
			})
			.sort((a, b) => b.pf - a.pf);
		if (rows.length < 2) return null;
		const maxPF = Math.max(...rows.map(r => r.pf), 1);
		const W = 300, H = rows.length * 20 + 6, PAD = 8, barMaxW = W - PAD * 2 - 40;
		return { rows, maxPF, W, H, PAD, barMaxW };
	});

	const recentRunBestSortinoByStrategy = $derived.by(() => {
		if (!runs || runs.length < 5) return null;
		const map = new Map<string, number>();
		for (const r of runs) {
			if (!r.strategy || r.sortino_ratio == null) continue;
			const s = r.strategy as string;
			const prev = map.get(s) ?? -Infinity;
			if ((r.sortino_ratio as number) > prev) map.set(s, r.sortino_ratio as number);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([name, best]) => ({ name: name.slice(0, 18), best }))
			.sort((a, b) => b.best - a.best)
			.slice(0, 8);
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.best)), 0.01);
		const W = 320, H = rows.length * 18 + 10, PAD = 8, barMaxW = W - PAD * 2 - 80;
		const zeroX = PAD + 80 + barMaxW / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const recentRunTradeCountTrend = $derived.by(() => {
		if (!runs || runs.length < 5) return null;
		const byMonth = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.run_date || r.trade_count == null) continue;
			const mo = (r.run_date as string).slice(0, 7);
			const arr = byMonth.get(mo) ?? [];
			arr.push(r.trade_count as number);
			byMonth.set(mo, arr);
		}
		if (byMonth.size < 3) return null;
		const pts = [...byMonth.entries()]
			.sort(([a], [b]) => a.localeCompare(b))
			.map(([mo, arr]) => ({ mo: mo.slice(5), avg: arr.reduce((s, v) => s + v, 0) / arr.length }));
		const maxAvg = Math.max(...pts.map(p => p.avg), 1);
		const W = 300, H = 60, PAD = 10;
		const toX = (i: number) => PAD + (i / (pts.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - (v / maxAvg) * (H - PAD * 2);
		const polyline = pts.map((p, i) => `${toX(i).toFixed(1)},${toY(p.avg).toFixed(1)}`).join(' ');
		return { pts, polyline, toX, toY, W, H, PAD, maxAvg: maxAvg.toFixed(0) };
	});

	const recentRunSharpeByStrategy = $derived.by(() => {
		if (!runs || runs.length < 5) return null;
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.strategy || r.sharpe_ratio == null) continue;
			const arr = map.get(r.strategy as string) ?? [];
			arr.push(r.sharpe_ratio as number);
			map.set(r.strategy as string, arr);
		}
		if (map.size < 2) return null;
		const rows = [...map.entries()]
			.map(([name, vals]) => ({ name: name.slice(0, 18), avg: vals.reduce((s, v) => s + v, 0) / vals.length }))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 8);
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 320, H = rows.length * 18 + 10, PAD = 8, barMaxW = W - PAD * 2 - 80;
		const zeroX = PAD + 80 + barMaxW / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const recentRunWinRateTrend = $derived.by(() => {
		if (!runs || runs.length < 5) return null;
		const byMonth = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.run_date || r.win_rate == null) continue;
			const mo = (r.run_date as string).slice(0, 7);
			const arr = byMonth.get(mo) ?? [];
			arr.push((r.win_rate as number) * 100);
			byMonth.set(mo, arr);
		}
		if (byMonth.size < 3) return null;
		const pts = [...byMonth.entries()]
			.sort(([a], [b]) => a.localeCompare(b))
			.map(([mo, arr]) => ({ mo: mo.slice(5), avg: arr.reduce((s, v) => s + v, 0) / arr.length }));
		const minV = Math.min(...pts.map(p => p.avg)), maxV = Math.max(...pts.map(p => p.avg), minV + 1);
		const W = 300, H = 60, PAD = 10;
		const toX = (i: number) => PAD + (i / Math.max(pts.length - 1, 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - minV) / (maxV - minV)) * (H - PAD * 2);
		const polyline = pts.map((p, i) => `${toX(i).toFixed(1)},${toY(p.avg).toFixed(1)}`).join(' ');
		return { pts, polyline, toX, W, H, PAD, minV: minV.toFixed(1), maxV: maxV.toFixed(1) };
	});

	const recentRunCalmarCDF = $derived.by(() => {
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

	const recentRunProfitByDow = $derived.by(() => {
		if (!runs || runs.length < 7) return null;
		const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
		const map = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.run_date || r.profit_total_pct == null) continue;
			const dow = DAYS[new Date(r.run_date as string).getDay()];
			const arr = map.get(dow) ?? [];
			arr.push(r.profit_total_pct as number);
			map.set(dow, arr);
		}
		const rows = DAYS.filter(d => map.has(d)).map(d => {
			const arr = map.get(d)!;
			return { d, avg: arr.reduce((s, v) => s + v, 0) / arr.length };
		});
		if (rows.length < 3) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 300, H = 70, PAD = 10, midY = H / 2;
		const bw = (W - PAD * 2) / rows.length - 1;
		return { rows, maxAbs, bw, W, H, PAD, midY };
	});

	const recentRunTopSortinoLeaderboard = $derived.by(() => {
		if (!runs || runs.length < 5) return null;
		const byStrat = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.strategy || r.sortino_ratio == null) continue;
			const arr = byStrat.get(r.strategy as string) ?? [];
			arr.push(r.sortino_ratio as number);
			byStrat.set(r.strategy as string, arr);
		}
		if (byStrat.size < 2) return null;
		const rows = [...byStrat.entries()]
			.map(([name, vals]) => ({ name: (name as string).slice(0, 18), best: Math.max(...vals) }))
			.sort((a, b) => b.best - a.best)
			.slice(0, 6);
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.best)), 0.01);
		const W = 300, H = rows.length * 20 + 8, PAD = 10, barMaxW = W - PAD * 2 - 80;
		const zeroX = PAD + 80 + barMaxW / 2;
		return { rows, maxAbs, W, H, PAD, barMaxW, zeroX };
	});

	const recentRunMonthlyCalmarTrend = $derived.by(() => {
		if (!runs || runs.length < 5) return null;
		const byMonth = new Map<string, number[]>();
		for (const r of runs) {
			if (!r.run_date || r.calmar_ratio == null) continue;
			const mo = (r.run_date as string).slice(0, 7);
			const arr = byMonth.get(mo) ?? [];
			arr.push(r.calmar_ratio as number);
			byMonth.set(mo, arr);
		}
		if (byMonth.size < 3) return null;
		const pts = [...byMonth.entries()]
			.sort(([a], [b]) => a.localeCompare(b))
			.map(([mo, arr]) => ({ mo: mo.slice(5), avg: arr.reduce((s, v) => s + v, 0) / arr.length }));
		const minV = Math.min(...pts.map(p => p.avg));
		const maxV = Math.max(...pts.map(p => p.avg), minV + 0.01);
		const W = 300, H = 65, PAD = 10;
		const toX = (i: number) => PAD + (i / Math.max(pts.length - 1, 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - minV) / (maxV - minV)) * (H - PAD * 2);
		const polyline = pts.map((p, i) => `${toX(i).toFixed(1)},${toY(p.avg).toFixed(1)}`).join(' ');
		return { pts, polyline, toX, W, H, PAD, minV: minV.toFixed(2), maxV: maxV.toFixed(2) };
	});

	const recentRunProfitVolatilityScatter = $derived.by(() => {
		if (!recentRuns || recentRuns.length < 10) return null;
		const pts = recentRuns
			.filter(r => r.profit_factor != null && r.max_drawdown != null && r.win_rate != null)
			.map(r => ({
				x: (r.max_drawdown as number) * 100,
				y: (r.profit_factor as number),
				wr: (r.win_rate as number) * 100
			}))
			.filter(p => p.x > 0 && p.x < 100 && p.y > 0 && p.y < 20);
		if (pts.length < 8) return null;
		const maxX = Math.max(...pts.map(p => p.x), 1);
		const maxY = Math.max(...pts.map(p => p.y), 1);
		const W = 280, H = 100, PAD = 12;
		return { pts, maxX, maxY, W, H, PAD };
	});

	const recentRunSharpeByTFBars = $derived.by(() => {
		if (!recentRuns || recentRuns.length < 10) return null;
		const byTF = new Map<string, number[]>();
		for (const r of recentRuns) {
			if (r.timeframe == null || r.sharpe_ratio == null) continue;
			const arr = byTF.get(r.timeframe as string) ?? [];
			arr.push(r.sharpe_ratio as number);
			byTF.set(r.timeframe as string, arr);
		}
		if (byTF.size < 2) return null;
		const bars = [...byTF.entries()]
			.map(([tf, arr]) => ({ tf, avg: arr.reduce((s, v) => s + v, 0) / arr.length, n: arr.length }))
			.sort((a, b) => b.avg - a.avg);
		const maxAbs = Math.max(...bars.map(b => Math.abs(b.avg)), 0.01);
		const W = 300, H = 70, PAD = 8;
		const bh = Math.max(6, (H - PAD * 2) / bars.length - 2);
		const midX = W / 2;
		return { bars, maxAbs, W, H, PAD, bh, midX };
	});

	const recentRunPairCountHistogram = $derived.by(() => {
		if (!recentRuns || recentRuns.length < 10) return null;
		const counts = recentRuns
			.filter(r => r.pair_count != null && (r.pair_count as number) > 0)
			.map(r => r.pair_count as number)
			.sort((a, b) => a - b);
		if (counts.length < 8) return null;
		const minV = counts[0], maxV = counts[counts.length - 1];
		const bins = Math.min(12, maxV - minV + 1);
		const binW = (maxV - minV) / bins || 1;
		const buckets = Array(bins).fill(0);
		for (const v of counts) {
			const idx = Math.min(bins - 1, Math.floor((v - minV) / binW));
			buckets[idx]++;
		}
		const maxCnt = Math.max(...buckets, 1);
		const W = 300, H = 65, PAD = 8;
		const bw = (W - PAD * 2) / bins - 1;
		return { buckets, maxCnt, bins, binW, W, H, PAD, bw, minV, maxV };
	});

	const recentRunTopProfitByPair = $derived.by(() => {
		if (!recentRuns || recentRuns.length < 10) return null;
		const byPair = new Map<string, number[]>();
		for (const r of recentRuns) {
			if (r.pair == null || r.profit_total_pct == null) continue;
			const arr = byPair.get(r.pair as string) ?? [];
			arr.push(r.profit_total_pct as number);
			byPair.set(r.pair as string, arr);
		}
		if (byPair.size < 4) return null;
		const rows = [...byPair.entries()]
			.map(([pair, arr]) => ({ pair: (pair as string).split('/')[0], avg: arr.reduce((s, v) => s + v, 0) / arr.length, n: arr.length }))
			.filter(r => r.n >= 2)
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 10);
		if (rows.length < 4) return null;
		const maxAbs = Math.max(...rows.map(r => Math.abs(r.avg)), 0.01);
		const W = 300, H = rows.length * 16 + 10, PAD = 8, midX = W / 2;
		const bh = 10;
		return { rows, maxAbs, W, H, PAD, midX, bh };
	});

	const recentRunWinRateByPair = $derived.by(() => {
		if (!recentRuns || recentRuns.length < 10) return null;
		const byPair = new Map<string, { wins: number; total: number }>();
		for (const r of recentRuns) {
			if (r.pair == null || r.win_rate == null) continue;
			const base = (r.pair as string).split('/')[0];
			const prev = byPair.get(base) ?? { wins: 0, total: 0 };
			prev.total++;
			if ((r.win_rate as number) >= 0.5) prev.wins++;
			byPair.set(base, prev);
		}
		if (byPair.size < 4) return null;
		const bars = [...byPair.entries()]
			.filter(([, v]) => v.total >= 3)
			.map(([base, v]) => ({ base, wr: (v.wins / v.total) * 100, n: v.total }))
			.sort((a, b) => b.wr - a.wr)
			.slice(0, 12);
		if (bars.length < 4) return null;
		const W = 300, H = 65, PAD = 8;
		const bw = Math.max(5, (W - PAD * 2) / bars.length - 2);
		return { bars, W, H, PAD, bw };
	});

	const recentRunCalmarBySharpeQuartile = $derived.by(() => {
		if (!recentRuns || recentRuns.length < 12) return null;
		const valid = recentRuns.filter(r => r.sharpe_ratio != null && r.calmar_ratio != null);
		if (valid.length < 10) return null;
		const sharpes = valid.map(r => r.sharpe_ratio as number).sort((a, b) => a - b);
		const q1 = sharpes[Math.floor(sharpes.length * 0.25)];
		const q2 = sharpes[Math.floor(sharpes.length * 0.50)];
		const q3 = sharpes[Math.floor(sharpes.length * 0.75)];
		const buckets: Record<string, number[]> = { Q1: [], Q2: [], Q3: [], Q4: [] };
		for (const r of valid) {
			const s = r.sharpe_ratio as number;
			const k = s <= q1 ? 'Q1' : s <= q2 ? 'Q2' : s <= q3 ? 'Q3' : 'Q4';
			buckets[k].push(r.calmar_ratio as number);
		}
		const bars = (['Q1', 'Q2', 'Q3', 'Q4'] as const).map(k => ({
			label: k,
			avg: buckets[k].length ? buckets[k].reduce((s, v) => s + v, 0) / buckets[k].length : 0,
			n: buckets[k].length
		})).filter(b => b.n > 0);
		if (bars.length < 2) return null;
		const maxAbs = Math.max(...bars.map(b => Math.abs(b.avg)), 0.01);
		const W = 300, H = 65, PAD = 8, midY = H / 2;
		const bw = Math.max(28, (W - PAD * 2) / bars.length - 8);
		return { bars, maxAbs, W, H, PAD, midY, bw };
	});

	const recentRunProfitTrend = $derived.by(() => {
		if (!recentRuns || recentRuns.length < 15) return null;
		const sorted = [...recentRuns]
			.filter(r => r.start_date && r.profit_factor != null)
			.sort((a, b) => new Date(a.start_date as string).getTime() - new Date(b.start_date as string).getTime());
		if (sorted.length < 15) return null;
		const win = 8;
		const smoothed = sorted.slice(win - 1).map((_, i) => {
			const slice = sorted.slice(i, i + win);
			return slice.reduce((s, r) => s + ((r.profit_factor as number) - 1) * 100, 0) / slice.length;
		});
		const minV = Math.min(...smoothed), maxV = Math.max(...smoothed, minV + 0.01);
		const W = 300, H = 65, PAD = 8;
		const toX = (i: number) => PAD + (i / (smoothed.length - 1)) * (W - PAD * 2);
		const toY = (v: number) => H - PAD - ((v - minV) / (maxV - minV)) * (H - PAD * 2);
		const polyline = smoothed.map((v, i) => `${toX(i)},${toY(v)}`).join(' ');
		const y0 = toY(0);
		return { polyline, W, H, PAD, y0, minV: minV.toFixed(1), maxV: maxV.toFixed(1), n: smoothed.length };
	});

	const recentRunSortinoCDF = $derived.by(() => {
		if (!recentRuns || recentRuns.length < 10) return null;
		const vals = recentRuns
			.filter(r => r.sortino_ratio != null && Math.abs(r.sortino_ratio as number) < 50)
			.map(r => r.sortino_ratio as number)
			.sort((a, b) => a - b);
		if (vals.length < 8) return null;
		const minV = vals[0], maxV = vals[vals.length - 1], rng = maxV - minV || 1;
		const W = 300, H = 65, PAD = 10;
		const toX = (v: number) => PAD + ((v - minV) / rng) * (W - PAD * 2);
		const toY = (i: number) => H - PAD - (i / Math.max(vals.length - 1, 1)) * (H - PAD * 2);
		const polyline = vals.map((v, i) => `${toX(v).toFixed(1)},${toY(i).toFixed(1)}`).join(' ');
		const median = vals[Math.floor(vals.length / 2)];
		return { polyline, toX, W, H, PAD, minV: minV.toFixed(2), maxV: maxV.toFixed(2), median: median.toFixed(2) };
	});
</script>

<svelte:head>
	<title>{t(lang, 'home.title')}</title>
</svelte:head>

<main class="w-full max-w-[1600px] mx-auto px-4 sm:px-6 py-10">
	<GreetingBanner ohlcByCoin={data.ohlcByCoin} events={data.triggers} />

	<div class="mb-10">
		<div class="bdv-eyebrow mb-2 text-[var(--gold-500)]">BearDawnVerse · Quant</div>
		<h1 class="bdv-display text-[44px] font-bold leading-[1.05] tracking-[-0.02em]">
			{t(lang, 'home.title')}
		</h1>
		<p class="mt-3 max-w-2xl text-[14px] text-muted-foreground">{t(lang, 'home.subtitle')}</p>
	</div>

	<TrustIntro />
	<AffiliateCta variant="card" />

	<section class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
		<Kpi
			label={t(lang, 'home.kpi.apiStatus')}
			value={data.health.api ? t(lang, 'home.kpi.apiOnline') : t(lang, 'home.kpi.apiDown')}
			tone={data.health.api ? 'good' : 'bad'}
			sub={t(lang, 'home.kpi.apiSub')}
		/>
		<Kpi
			label={t(lang, 'home.kpi.totalRuns')}
			value={s.total_runs}
			sub={fmt('home.kpi.totalRunsSub', { n: s.distinct_strategies })}
		/>
		<Kpi
			label={t(lang, 'home.kpi.totalTrades')}
			value={s.total_trades.toLocaleString()}
			sub={t(lang, 'home.kpi.totalTradesSub')}
		/>
		<Kpi
			label={t(lang, 'home.kpi.dca')}
			value={s.dca_count}
			sub={t(lang, 'home.kpi.dcaSub')}
		/>
	</section>

	<section class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
		<Kpi
			label={t(lang, 'home.kpi.bestProfit')}
			value={fmtPct(s.best_profit_pct)}
			tone={(s.best_profit_pct ?? 0) > 0 ? 'good' : 'bad'}
			sub={t(lang, 'home.kpi.bestProfitSub')}
		/>
		<Kpi
			label={t(lang, 'home.kpi.bestCalmar')}
			value={s.best_calmar == null ? '—' : s.best_calmar.toFixed(2)}
			tone={(s.best_calmar ?? 0) > 1 ? 'good' : 'default'}
			sub={t(lang, 'home.kpi.bestCalmarSub')}
		/>
		<Kpi
			label={t(lang, 'home.kpi.bestSharpe')}
			value={s.best_sharpe == null ? '—' : s.best_sharpe.toFixed(2)}
			tone={(s.best_sharpe ?? 0) > 1 ? 'good' : 'default'}
			sub={t(lang, 'home.kpi.bestSharpeSub')}
		/>
		<Kpi
			label={t(lang, 'home.kpi.bestSortino')}
			value={s.best_sortino == null ? '—' : s.best_sortino.toFixed(2)}
			tone={(s.best_sortino ?? 0) > 1.5 ? 'good' : 'default'}
			sub={t(lang, 'home.kpi.bestSortinoSub')}
		/>
	</section>

	<section class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
		<Kpi
			label={t(lang, 'home.kpi.bestWinRate')}
			value={s.best_win_rate == null ? '—' : s.best_win_rate.toFixed(1) + '%'}
			tone="good"
			sub={t(lang, 'home.kpi.bestWinRateSub')}
		/>
		<Kpi
			label={t(lang, 'home.kpi.minMaxDd')}
			value={s.min_max_dd == null ? '—' : s.min_max_dd.toFixed(1) + '%'}
			tone={(s.min_max_dd ?? 100) < 20 ? 'good' : 'bad'}
			sub={t(lang, 'home.kpi.minMaxDdSub')}
		/>
		<Kpi
			label={t(lang, 'home.kpi.strategyCount')}
			value={s.distinct_strategies}
			sub={t(lang, 'home.kpi.strategyCountSub')}
		/>
		<Kpi
			label={t(lang, 'home.kpi.runCount')}
			value={s.total_runs}
			sub={t(lang, 'home.kpi.runCountSub')}
		/>
	</section>

	<section class="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
		<a
			href="/strategies"
			class="group rounded-xl border bg-card p-6 transition-colors hover:border-primary"
		>
			<div class="text-2xl">📚</div>
			<div class="mt-2 font-semibold">{t(lang, 'home.card.strategies.title')}</div>
			<p class="mt-1 text-sm text-muted-foreground">{fmt('home.card.strategies.desc', { n: s.distinct_strategies })}</p>
			<div class="mt-3 text-xs text-primary opacity-0 transition-opacity group-hover:opacity-100">
				{t(lang, 'common.enter')}
			</div>
		</a>
		<a
			href="/dca"
			class="group rounded-xl border bg-card p-6 transition-colors hover:border-primary"
		>
			<div class="text-2xl">💰</div>
			<div class="mt-2 font-semibold">{t(lang, 'home.card.dca.title')}</div>
			<p class="mt-1 text-sm text-muted-foreground">{t(lang, 'home.card.dca.desc')}</p>
			<div class="mt-3 text-xs text-primary opacity-0 transition-opacity group-hover:opacity-100">
				{t(lang, 'common.enter')}
			</div>
		</a>
		<a
			href="/chart"
			class="group rounded-xl border bg-card p-6 transition-colors hover:border-primary"
		>
			<div class="text-2xl">📉</div>
			<div class="mt-2 font-semibold">{t(lang, 'home.card.chart.title')}</div>
			<p class="mt-1 text-sm text-muted-foreground">{t(lang, 'home.card.chart.desc')}</p>
			<div class="mt-3 text-xs text-primary opacity-0 transition-opacity group-hover:opacity-100">
				{t(lang, 'common.enter')}
			</div>
		</a>
		<a
			href="/wf"
			class="group rounded-xl border bg-card p-6 transition-colors hover:border-primary"
		>
			<div class="text-2xl">🧭</div>
			<div class="mt-2 font-semibold">{t(lang, 'home.card.wf.title')}</div>
			<p class="mt-1 text-sm text-muted-foreground">{t(lang, 'home.card.wf.desc')}</p>
			<div class="mt-3 text-xs text-primary opacity-0 transition-opacity group-hover:opacity-100">
				{t(lang, 'common.enter')}
			</div>
		</a>
	</section>

	<!-- Market regime widget -->
	<section class="mt-6 rounded-xl border bg-card p-4">
		<div class="flex flex-wrap items-center justify-between gap-4">
			<h2 class="text-sm font-semibold">{lang === 'en' ? '🌡️ Market Regime' : '🌡️ 市场状态'}</h2>
			{#if regimeLoading}
				<span class="text-xs text-muted-foreground">{t(lang, 'common.loading')}</span>
			{:else if regimeFng}
				{@const sig = regimeSignal(regimeFng.value, regimeBtc)}
				<div class="flex flex-wrap items-center gap-6">
					{#if regimeBtc}
						<div class="text-center">
							<div class="text-[10px] uppercase text-muted-foreground">BTC</div>
							<div class="font-mono text-sm font-semibold">${regimeBtc.toLocaleString('en-US', { maximumFractionDigits: 0 })}</div>
						</div>
					{/if}
					<div class="text-center">
						<div class="text-[10px] uppercase text-muted-foreground">{lang === 'en' ? 'Fear & Greed' : '恐贪指数'}</div>
						<div class="font-mono text-sm font-semibold">{regimeFng.value} <span class="text-xs text-muted-foreground">{regimeFng.label}</span></div>
					</div>
					<!-- FnG gauge bar -->
					<div class="flex-1 min-w-32">
						<div class="relative h-3 rounded-full overflow-hidden" style="background: linear-gradient(to right, #ef4444, #f97316, #eab308, #22c55e)">
							<div class="absolute top-0 h-full w-1 rounded-full bg-white shadow" style="left: calc({regimeFng.value}% - 2px)"></div>
						</div>
						<div class="mt-0.5 flex justify-between text-[9px] text-muted-foreground"><span>Fear</span><span>Greed</span></div>
					</div>
					<div class="text-center">
						<div class="text-[10px] uppercase text-muted-foreground">{lang === 'en' ? 'Signal' : '信号'}</div>
						<div class="text-sm font-bold {sig.color}">{sig.label}</div>
					</div>
				</div>
				<p class="w-full text-xs text-muted-foreground">{sig.desc}</p>
			{:else}
				<span class="text-xs text-muted-foreground">{lang === 'en' ? 'Could not load market data' : '无法加载市场数据'}</span>
			{/if}
		</div>
	</section>

	{#if !data.isAuthed}
		<section class="mt-10 rounded-xl border-2 border-dashed border-primary/40 bg-gradient-to-br from-primary/5 to-transparent p-8 text-center">
			<h2 class="text-lg font-semibold">{t(lang, 'home.anonGate.title')}</h2>
			<p class="mt-2 text-sm text-muted-foreground">{t(lang, 'home.anonGate.body')}</p>
			<a
				href="/login?next=/"
				class="mt-4 inline-block rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
			>
				{t(lang, 'home.anonGate.cta')}
			</a>
		</section>
	{:else}
	{#if stratLeaderboard && stratLeaderboard.total >= 3}
		{@const lb = stratLeaderboard}
		<section class="mt-10">
			<div class="mb-3 flex items-baseline justify-between">
				<h2 class="text-lg font-semibold">Strategy Leaderboard <span class="ml-1 text-sm font-normal text-muted-foreground">(most recent run · {lb.total} strategies)</span> <ChartInfo metric="leaderboard" {lang} /></h2>
				<a href="/strategies" class="text-xs text-primary hover:underline">All strategies</a>
			</div>
			<div class="grid gap-3 sm:grid-cols-2">
				<div>
					<p class="mb-2 text-[11px] font-semibold uppercase tracking-wider text-green-400">Top Performers</p>
					<div class="space-y-1.5">
						{#each lb.top as r, i}
							<a href={`/strategies/${r.strategy}`} class="flex items-center gap-2 rounded-lg border border-green-800/30 bg-green-950/15 px-3 py-2 text-xs transition hover:border-green-600/50">
								<span class="w-4 shrink-0 font-bold text-green-400">#{i + 1}</span>
								<span class="flex-1 truncate font-semibold text-foreground">{r.strategy}</span>
								<span class="shrink-0 font-mono font-semibold text-green-400">+{r.total_profit_pct!.toFixed(1)}%</span>
								<span class="shrink-0 font-mono text-muted-foreground text-[10px]">S {r.sharpe == null ? '—' : r.sharpe.toFixed(1)}</span>
							</a>
						{/each}
					</div>
				</div>
				<div>
					<p class="mb-2 text-[11px] font-semibold uppercase tracking-wider text-red-400">Underperformers</p>
					<div class="space-y-1.5">
						{#each lb.bottom as r, i}
							<a href={`/strategies/${r.strategy}`} class="flex items-center gap-2 rounded-lg border border-red-800/30 bg-red-950/15 px-3 py-2 text-xs transition hover:border-red-600/50">
								<span class="w-4 shrink-0 font-bold text-red-400">#{lb.total - lb.bottom.length + i + 1}</span>
								<span class="flex-1 truncate font-semibold text-foreground">{r.strategy}</span>
								<span class="shrink-0 font-mono font-semibold {(r.total_profit_pct ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}">{(r.total_profit_pct ?? 0) >= 0 ? '+' : ''}{r.total_profit_pct!.toFixed(1)}%</span>
								<span class="shrink-0 font-mono text-muted-foreground text-[10px]">S {r.sharpe == null ? '—' : r.sharpe.toFixed(1)}</span>
							</a>
						{/each}
					</div>
				</div>
			</div>
		</section>
	{/if}

	<section class="mt-10">
		<div class="mb-3 flex items-baseline justify-between">
			<h2 class="text-lg font-semibold">{t(lang, 'home.recent.title')}</h2>
			<a href="/archive" class="text-xs text-primary hover:underline">{t(lang, 'common.viewAll')}</a>
		</div>

		<div class="mb-3 flex flex-wrap items-center gap-2 text-xs">
			<span class="text-muted-foreground">{t(lang, 'home.filter.strategy')}</span>
			<button
				type="button"
				onclick={() => (strategyFilter = null)}
				class="rounded-md border px-2 py-1 transition-colors hover:bg-accent"
				class:border-primary={strategyFilter === null}
				class:text-primary={strategyFilter === null}
			>
				{t(lang, 'common.all')}
			</button>
			{#each data.strategy_options as opt}
				<button
					type="button"
					onclick={() => (strategyFilter = strategyFilter === opt ? null : opt)}
					class="rounded-md border px-2 py-1 font-mono transition-colors hover:bg-accent"
					class:border-primary={strategyFilter === opt}
					class:text-primary={strategyFilter === opt}
				>
					{opt}
				</button>
			{/each}
		</div>

		<div class="mb-4 flex flex-wrap items-center gap-2 text-xs">
			<span class="text-muted-foreground">{t(lang, 'home.filter.tf')}</span>
			<button
				type="button"
				onclick={() => (timeframeFilter = null)}
				class="rounded-md border px-2 py-1 transition-colors hover:bg-accent"
				class:border-primary={timeframeFilter === null}
				class:text-primary={timeframeFilter === null}
			>
				{t(lang, 'common.all')}
			</button>
			{#each data.timeframe_options as opt}
				<button
					type="button"
					onclick={() => (timeframeFilter = timeframeFilter === opt ? null : opt)}
					class="rounded-md border px-2 py-1 font-mono transition-colors hover:bg-accent"
					class:border-primary={timeframeFilter === opt}
					class:text-primary={timeframeFilter === opt}
				>
					{opt}
				</button>
			{/each}
		</div>

		{#if activityCalendar.total > 0}
			<div class="mb-4 rounded-lg border bg-card p-4">
				<div class="mb-2 flex items-baseline justify-between">
					<span class="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Backtest Activity</span>
					<span class="font-mono text-[11px] text-muted-foreground">{activityCalendar.total} runs · last 52 weeks</span>
				</div>
				<div class="overflow-x-auto">
					<div class="flex gap-[3px]" style="min-width:max-content">
						{#each activityCalendar.weeks as week}
							<div class="flex flex-col gap-[3px]">
								{#each week as cell}
									<div
										class="h-[10px] w-[10px] rounded-sm {cell.count === 0 ? 'bg-muted/25' : cell.intensity > 0.7 ? 'bg-indigo-400' : cell.intensity > 0.4 ? 'bg-indigo-600/70' : 'bg-indigo-800/60'}"
										title="{cell.date}: {cell.count} run{cell.count !== 1 ? 's' : ''}"
									></div>
								{/each}
							</div>
						{/each}
					</div>
				</div>
				<div class="mt-2 flex items-center gap-3 text-[10px] text-muted-foreground">
					<span>Less</span>
					<span class="flex gap-1">
						<span class="h-3 w-3 rounded-sm bg-muted/25 inline-block"></span>
						<span class="h-3 w-3 rounded-sm bg-indigo-800/60 inline-block"></span>
						<span class="h-3 w-3 rounded-sm bg-indigo-600/70 inline-block"></span>
						<span class="h-3 w-3 rounded-sm bg-indigo-400 inline-block"></span>
					</span>
					<span>More</span>
				</div>
			</div>
		{/if}

		<div class="overflow-x-auto rounded-lg border bg-card">
			<table class="w-full text-sm">
				<thead class="bg-secondary text-left text-[11px] uppercase text-muted-foreground">
					<tr>
						<th class="px-3 py-2.5"><span class="inline-flex items-center">{t(lang, 'home.table.started')}<InfoTip text={t(lang, 'metric.tip.started')} /></span></th>
						<th class="px-3">{t(lang, 'home.table.strategy')}</th>
						<th class="px-3"><span class="inline-flex items-center">{t(lang, 'home.table.tf')}<InfoTip text={t(lang, 'metric.tip.tf')} /></span></th>
						<th class="px-3"><span class="inline-flex items-center">{t(lang, 'home.table.factors')}<InfoTip text={t(lang, 'metric.tip.factors')} /></span></th>
						<th class="px-3 text-right"><span class="inline-flex items-center">{t(lang, 'home.table.trades')}<InfoTip text={t(lang, 'metric.tip.trades')} /></span></th>
						<th class="px-3 text-right"><span class="inline-flex items-center">{t(lang, 'home.table.winRate')}<InfoTip text={t(lang, 'metric.tip.wr')} /></span></th>
						<th class="px-3 text-right"><span class="inline-flex items-center">{t(lang, 'home.table.profit')}<InfoTip text={t(lang, 'metric.tip.profit')} /></span></th>
						<th class="px-3 text-right"><span class="inline-flex items-center">{t(lang, 'home.table.maxDd')}<InfoTip text={t(lang, 'metric.tip.maxDd')} /></span></th>
						<th class="px-3 text-right"><span class="inline-flex items-center">{t(lang, 'home.table.calmar')}<InfoTip text={t(lang, 'metric.tip.calmar')} placement="top" /></span></th>
						<th class="px-3 text-right"><span class="inline-flex items-center">{t(lang, 'home.table.sharpe')}<InfoTip text={t(lang, 'metric.tip.sharpe')} placement="top" /></span></th>
					</tr>
				</thead>
				<tbody class="font-mono text-xs">
					{#each filtered as r (r.id)}
						<tr class="border-t border-border hover:bg-accent/50">
							<td class="px-3 py-2 text-muted-foreground">{fmtTime(r.started_at)}</td>
							<td class="px-3 font-semibold">
								<a href={`/strategies/${r.strategy}`} class="text-primary hover:underline">
									{r.strategy}
								</a>
							</td>
							<td class="px-3">{r.timeframe ?? '-'}</td>
							<td class="px-3">
								<FactorBadges factors={r.factors} size="xs" />
							</td>
							<td class="px-3 text-right">{r.total_trades ?? 0}</td>
							<td class="px-3 text-right">{r.win_rate_pct == null ? '—' : r.win_rate_pct.toFixed(1)}</td>
							<td
								class="px-3 text-right"
								class:text-green-500={(r.total_profit_pct ?? 0) > 0}
								class:text-red-500={(r.total_profit_pct ?? 0) < 0}
							>
								{fmtPct(r.total_profit_pct)}
							</td>
							<td class="px-3 text-right" class:text-red-500={(r.max_drawdown_pct ?? 0) > 20}>
								{(r.max_drawdown_pct ?? 0).toFixed(2)}%
							</td>
							<td class="px-3 text-right">{r.calmar == null ? '-' : r.calmar.toFixed(2)}</td>
							<td class="px-3 text-right">{r.sharpe == null ? '—' : r.sharpe.toFixed(2)}</td>
						</tr>
					{/each}
					{#if filtered.length === 0}
						<tr><td class="px-3 py-6 text-center text-muted-foreground" colspan="10">{t(lang, 'home.filter.empty')}</td></tr>
					{/if}
				</tbody>
			</table>
		</div>
	</section>
	{/if}

	<footer class="mt-16 border-t border-border pt-6 text-center text-xs text-muted-foreground">
		{t(lang, 'home.footer')}
	</footer>
</main>
