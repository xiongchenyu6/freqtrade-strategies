<script lang="ts">
	// Self-service backtest playground (Phase 1 MVP). Auth-gated: a logged-in user picks a
	// predefined strategy + params, submits a job (PostgREST insert, RLS-scoped), and the
	// game-box runner executes it and writes results we poll for. See PLAYGROUND_PLAN.md.
	import { page } from '$app/stores';
	import { user } from '$lib/auth';
	import { type Lang } from '$lib/i18n';
	import {
		STRATEGIES,
		submitBacktest,
		myJobs,
		jobResult,
		type Strategy,
		type BacktestJob,
		type BacktestResult
	} from '$lib/backtests';
	import { createSignal, signalsVersion, type NewSignal } from '$lib/signals';
	import { onMount, onDestroy } from 'svelte';
	import AlertSubscribe from '$lib/components/alert-subscribe.svelte';
	import MySignals from '$lib/components/my-signals.svelte';
	import { track } from '$lib/track';

	const lang = $derived<Lang>($page.data.lang ?? 'zh');
	const en = $derived(lang === 'en');

	// ── Dynamic per-strategy form state ──────────────────────────────────────
	// We keep one bag of param values keyed by the param name; switching strategy
	// re-seeds it from that strategy's defaults so the inputs always render valid.
	type StratKey = keyof typeof STRATEGIES;
	type NumParam = { min: number; max: number; default: number; step?: number };
	type ChoiceParam = { choices: readonly string[]; default: string };
	type AnyParam = NumParam | ChoiceParam;

	const isChoice = (p: AnyParam): p is ChoiceParam => 'choices' in p;

	let strategy = $state<StratKey>('honest_trend');
	const cfg = $derived(STRATEGIES[strategy]);

	let asset = $state<string>(STRATEGIES.honest_trend.assets[0]);
	let tf = $state<string>(STRATEGIES.honest_trend.timeframes[0]);
	let params = $state<Record<string, number | string>>(seedParams('honest_trend'));

	// honest_trend accepts ANY US ticker (runner validates against its ~9.5k-symbol list
	// server-side); the suggested trio additionally has hourly bars, everything else is 1d.
	const HONEST_SUGGESTED = STRATEGIES.honest_trend.assets as readonly string[];
	const isCatalogAsset = $derived(strategy !== 'honest_trend' || HONEST_SUGGESTED.includes(asset));
	const tfChoices = $derived<readonly string[]>(isCatalogAsset ? cfg.timeframes : ['1d']);
	// Force tf back into range when a non-catalog ticker (1d only) is typed.
	$effect(() => {
		if (!tfChoices.includes(tf)) tf = tfChoices[0];
	});

	function seedParams(s: StratKey): Record<string, number | string> {
		const out: Record<string, number | string> = {};
		const ps = STRATEGIES[s].params as Record<string, AnyParam>;
		for (const [k, p] of Object.entries(ps)) out[k] = p.default;
		return out;
	}

	// Re-seed asset/tf/params whenever the selected strategy changes.
	function onStrategyChange(s: StratKey) {
		strategy = s;
		const c = STRATEGIES[s];
		asset = c.assets[0];
		tf = c.timeframes[0];
		params = seedParams(s);
		err = '';
	}

	// Friendly labels for param keys (fallback: prettified key).
	const PARAM_LABELS: Record<string, [zh: string, en: string]> = {
		ema_fast: ['快线 EMA', 'EMA fast'],
		ema_slow: ['慢线 EMA', 'EMA slow'],
		entry_lb: ['入场回看', 'Entry lookback'],
		exit_lb: ['离场回看', 'Exit lookback'],
		risk_frac: ['风险比例', 'Risk fraction'],
		base_buy_usd: ['每次买入 (USD)', 'Base buy (USD)'],
		interval_bars: ['间隔 (天)', 'Interval (days)'],
		mode: ['模式', 'Mode']
	};
	function paramLabel(k: string): string {
		const l = PARAM_LABELS[k];
		if (l) return en ? l[1] : l[0];
		return k.replace(/_/g, ' ');
	}

	let busy = $state(false);
	let err = $state('');
	let jobs = $state<BacktestJob[]>([]);
	let results = $state<Record<string, BacktestResult>>({});
	let openId = $state<string | null>(null);

	// Build SVG polyline points for a compact equity sparkline (normalized min→max).
	function spark(curve: number[] | null, w = 96, h = 24): string {
		if (!curve || curve.length < 2) return '';
		const lo = Math.min(...curve);
		const hi = Math.max(...curve);
		const span = hi - lo || 1;
		const dx = w / (curve.length - 1);
		return curve.map((v, i) => `${(i * dx).toFixed(1)},${(h - ((v - lo) / span) * h).toFixed(1)}`).join(' ');
	}

	// Larger equity chart geometry for the expanded detail panel: a baseline at the
	// starting equity, min/max gridlines, and the value polyline. Reuses spark()'s
	// normalization but exposes coordinates so we can place labels + the baseline.
	function bigChart(curve: number[] | null, w = 480, h = 140, pad = 8) {
		if (!curve || curve.length < 2) return null;
		const lo = Math.min(...curve);
		const hi = Math.max(...curve);
		const span = hi - lo || 1;
		const start = curve[0];
		const toX = (i: number) => pad + (i / (curve.length - 1)) * (w - pad * 2);
		const toY = (v: number) => pad + (1 - (v - lo) / span) * (h - pad * 2);
		const poly = curve.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');
		// Area under the line, closed to the bottom of the plot box.
		const area = `${pad},${(h - pad).toFixed(1)} ${poly} ${(w - pad).toFixed(1)},${(h - pad).toFixed(1)}`;
		return { w, h, pad, lo, hi, start, poly, area, baselineY: toY(start), up: curve[curve.length - 1] >= start };
	}

	// Hardcoded teaser for logged-out visitors. The METRICS are real — HonestTrend NVDA 1d
	// EMA 20/50 from our logged backtest (public via api.nautilus_backtests: +33.98%,
	// DD -29.31%, Sharpe 2.59, 2 trades, 2023-06→2026-06). The curve SHAPE is illustrative
	// (labelled 示意曲线): 100k start, ~-29% dip mid-way, 133,980 finish.
	const SAMPLE_CURVE = [
		100000, 100400, 101900, 104100, 107600, 111800, 115900, 119400, 122300, 124100, 124600,
		121800, 117200, 111300, 104600, 97900, 92400, 89100, 88100, 90600, 94800, 99700, 105200,
		110900, 116500, 121600, 126000, 129600, 132300, 133980
	];
	const sampleChart = bigChart(SAMPLE_CURVE);

	async function refresh() {
		if (!$user) return;
		try {
			jobs = await myJobs();
			for (const j of jobs) {
				if (j.status === 'done' && !results[j.id]) {
					const r = await jobResult(j.id);
					if (r) results = { ...results, [j.id]: r };
				}
			}
		} catch (e) {
			err = (e as Error).message;
		}
	}

	// Per-strategy client-side validation (the runner re-validates server-side).
	function validate(): string | null {
		if (strategy === 'honest_trend') {
			if (!/^[A-Z0-9]{1,6}$/.test(asset))
				return en
					? 'Ticker must be 1-6 letters/digits, e.g. TSLA.'
					: '股票代码须为 1-6 位字母/数字，如 TSLA。';
			if (!((params.ema_fast as number) < (params.ema_slow as number)))
				return en ? 'Fast EMA must be < slow EMA.' : '快线 EMA 必须小于慢线。';
		}
		if (strategy === 'donchian') {
			if (!((params.exit_lb as number) <= (params.entry_lb as number)))
				return en ? 'Exit lookback must be ≤ entry lookback.' : '离场回看必须 ≤ 入场回看。';
		}
		return null;
	}

	async function submit() {
		if (!$user?.sub) return;
		const v = validate();
		if (v) {
			err = v;
			return;
		}
		busy = true;
		err = '';
		try {
			await submitBacktest(strategy as Strategy, { asset, tf, ...params }, $user.sub);
			track('backtest_submit');
			await refresh();
		} catch (e) {
			err = (e as Error).message;
		} finally {
			busy = false;
		}
	}

	// One-click presets: seed the form through the normal strategy-change path (so all
	// inputs render valid), apply the preset's asset/tf/param overrides, then submit.
	type Preset = {
		zh: string;
		en: string;
		strategy: StratKey;
		asset: string;
		tf: string;
		overrides?: Record<string, number | string>;
	};
	const PRESETS: Preset[] = [
		{ zh: 'BTC 智能定投 (推荐新手)', en: 'BTC smart DCA (beginner pick)', strategy: 'accumulator', asset: 'BTC', tf: '1d' },
		{ zh: 'NVDA 趋势跟随', en: 'NVDA trend following', strategy: 'honest_trend', asset: 'NVDA', tf: '1d', overrides: { ema_fast: 20, ema_slow: 50 } },
		{ zh: 'ETH 突破策略', en: 'ETH breakout', strategy: 'donchian', asset: 'ETH', tf: '1h' }
	];

	async function runPreset(p: Preset) {
		onStrategyChange(p.strategy);
		asset = p.asset;
		tf = p.tf;
		if (p.overrides) params = { ...params, ...p.overrides };
		await submit();
	}

	function badge(s: BacktestJob['status']): string {
		return (
			{
				queued: 'border-muted-foreground/40 text-muted-foreground',
				running: 'border-amber-500/50 text-amber-600',
				done: 'border-emerald-500/50 text-emerald-600',
				error: 'border-red-500/50 text-red-600'
			}[s] ?? ''
		);
	}

	// Short one-line summary of a job's params for the collapsed row.
	function jobSummary(j: BacktestJob): string {
		const p = j.params;
		const head = `${p.asset ?? '?'} · ${p.tf ?? '?'}`;
		const rest = Object.entries(p)
			.filter(([k]) => k !== 'asset' && k !== 'tf')
			.map(([k, v]) => `${k}=${v}`)
			.join(' ');
		return rest ? `${head} · ${rest}` : head;
	}

	// Format a possibly-null metric (crypto accumulator has null DD/Sharpe/Calmar).
	function num(v: unknown, suffix = ''): string {
		if (v == null || (typeof v === 'number' && !isFinite(v))) return '—';
		return `${v}${suffix}`;
	}

	function toggle(id: string) {
		openId = openId === id ? null : id;
	}

	// ── One-click "turn this backtest into a live signal" ─────────────────────
	// Maps a completed job's config onto a user signal: honest_trend → ema_cross
	// (both crossings), donchian → donchian_breakout (both sides), accumulator →
	// market-wide fng_threshold below 25 (its fear-buy trigger).
	let sigBusy = $state<string | null>(null);
	let sigMsg = $state<Record<string, { ok: boolean; text: string }>>({});

	function mapJobToSignal(j: BacktestJob, userId: string): NewSignal {
		const p = j.params as Record<string, string | number>;
		const asset = String(p.asset ?? 'BTC');
		const tf = String(p.tf ?? '1d');
		if (j.strategy === 'honest_trend') {
			const f = Number(p.ema_fast);
			const s = Number(p.ema_slow);
			const sigTf = '1d'; // honest_trend assets are all US equity — equity signals are 1d-only
			return {
				user_id: userId,
				name: `${asset} ${sigTf} EMA${f}/${s} ${en ? 'cross' : '金叉死叉'}`,
				kind: 'ema_cross',
				asset,
				timeframe: sigTf,
				params: { ema_fast: f, ema_slow: s, direction: 'both' }
			};
		}
		if (j.strategy === 'donchian') {
			const e = Number(p.entry_lb);
			const x = Number(p.exit_lb);
			return {
				user_id: userId,
				name: `${asset} ${tf} ${en ? 'Donchian' : '唐奇安'}${e}/${x} ${en ? 'breakout' : '突破'}`,
				kind: 'donchian_breakout',
				asset,
				timeframe: tf,
				params: { entry_lb: e, exit_lb: x, side: 'both' }
			};
		}
		// accumulator — fear-driven DCA; the live equivalent is a market-wide FNG alert,
		// so don't embed the backtest's asset/tf in the name (the signal isn't per-asset).
		return {
			user_id: userId,
			name: en ? 'FNG<25 market fear alert' : 'FNG<25 全市场恐慌提醒',
			kind: 'fng_threshold',
			asset: '*',
			timeframe: '1d',
			params: { below: 25 }
		};
	}

	async function toSignal(j: BacktestJob) {
		const sub = $user?.sub;
		if (!sub || sigBusy) return;
		sigBusy = j.id;
		try {
			await createSignal(mapJobToSignal(j, sub));
			signalsVersion.update((n) => n + 1); // <MySignals /> below re-fetches
			sigMsg = { ...sigMsg, [j.id]: { ok: true, text: en ? 'Created — manage it below.' : '已创建,在下方管理' } };
		} catch (e) {
			sigMsg = { ...sigMsg, [j.id]: { ok: false, text: (e as Error).message } };
		} finally {
			sigBusy = null;
		}
	}

	let timer: ReturnType<typeof setInterval>;
	onMount(() => {
		refresh();
		timer = setInterval(refresh, 4000); // poll while jobs are queued/running
	});
	onDestroy(() => clearInterval(timer));
</script>

<svelte:head><title>{en ? 'Backtest playground' : '回测实验室'} · Crypto Quant</title></svelte:head>

<main class="mx-auto mt-12 max-w-2xl px-5">
	<h1 class="text-2xl font-semibold tracking-tight">{en ? 'Backtest playground' : '回测实验室'}</h1>
	<p class="mt-2 text-sm text-muted-foreground">
		{en
			? 'Run your own backtest of a strategy with your own parameters. Results are private to your account.'
			: '用你自己的参数跑策略回测，结果只属于你的账号。'}
	</p>

	{#if !$user}
		<div class="mt-6 rounded-md border border-primary/50 bg-primary/5 p-4 text-sm">
			<div class="font-medium text-foreground">{en ? 'Sign in to run your own backtests' : '登录后即可跑你自己的回测'}</div>
			<p class="mt-1 text-muted-foreground">
				{en
					? 'Pick a strategy below, set your own parameters, and we run a real backtest on historical data. Results are private to your account.'
					: '选下面任意一个策略，设你自己的参数，我们用历史数据跑一次真实回测。结果只属于你的账号。'}
			</p>
			<p class="mt-2 text-xs font-medium text-primary">
				{en ? 'Instant signup — no email verification, running in 10 seconds.' : '注册即用 —— 无需邮箱验证，10 秒开跑'}
			</p>
			<a href="/login?next=/backtest" class="mt-3 inline-block rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">
				{en ? 'Sign in' : '登录'}
			</a>
		</div>

		<!-- Read-only strategy preview so logged-out visitors see what's on offer. -->
		<div class="mt-4 grid gap-3 sm:grid-cols-3">
			{#each Object.keys(STRATEGIES) as s}
				{@const c = STRATEGIES[s as StratKey]}
				<div class="rounded-md border border-border p-4">
					<div class="text-sm font-medium text-foreground">{c.label}</div>
					<p class="mt-1.5 text-xs text-muted-foreground">{en ? c.blurb[1] : c.blurb[0]}</p>
					<div class="mt-2 flex flex-wrap gap-1">
						{#each c.assets.slice(0, 4) as a}
							<span class="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{a}</span>
						{/each}
						{#if c.assets.length > 4}
							<span class="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">+{c.assets.length - 4}</span>
						{/if}
					</div>
				</div>
			{/each}
		</div>

		<!-- Fully-rendered sample result so visitors see the payoff before the login wall.
		     Metrics are real (logged backtest); the curve shape is illustrative (示意曲线). -->
		<div class="mt-4 rounded-md border border-border p-4">
			<div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
				<span class="text-sm font-medium text-foreground">{en ? 'Sample result' : '示例结果'}</span>
				<span class="text-xs text-muted-foreground">{en ? '— sign up to run your own' : '— 注册后用你自己的参数跑'}</span>
			</div>
			<div class="mt-1 font-mono text-xs text-muted-foreground">HonestTrend · NVDA · 1d · ema_fast=20 ema_slow=50</div>

			{#if sampleChart}
				<svg viewBox="0 0 {sampleChart.w} {sampleChart.h}" width="100%" height={sampleChart.h} class="mt-3 max-w-[480px]" role="img"
					aria-label={en ? 'Sample equity curve (illustrative)' : '示例权益曲线（示意）'}>
					<!-- plot border -->
					<rect x={sampleChart.pad} y={sampleChart.pad} width={sampleChart.w - sampleChart.pad * 2} height={sampleChart.h - sampleChart.pad * 2}
						fill="none" class="stroke-border" stroke-width="1" />
					<!-- baseline at starting equity -->
					<line x1={sampleChart.pad} x2={sampleChart.w - sampleChart.pad} y1={sampleChart.baselineY} y2={sampleChart.baselineY}
						class="stroke-muted-foreground/40" stroke-width="1" stroke-dasharray="3 3" />
					<!-- area + line -->
					<polygon points={sampleChart.area} class="fill-emerald-500/10" />
					<polyline points={sampleChart.poly} fill="none" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"
						class="stroke-emerald-500" />
					<!-- honesty label: the shape is illustrative, the metrics below are real -->
					<text x={sampleChart.pad + 3} y={sampleChart.pad + 12} class="fill-muted-foreground" font-size="10">{en ? 'illustrative curve' : '示意曲线'}</text>
					<!-- min/max + start labels -->
					<text x={sampleChart.w - sampleChart.pad - 2} y={sampleChart.pad + 10} text-anchor="end" class="fill-muted-foreground" font-size="10">{sampleChart.hi.toFixed(0)}</text>
					<text x={sampleChart.w - sampleChart.pad - 2} y={sampleChart.h - sampleChart.pad - 3} text-anchor="end" class="fill-muted-foreground" font-size="10">{sampleChart.lo.toFixed(0)}</text>
					<text x={sampleChart.pad + 3} y={sampleChart.baselineY - 3} class="fill-muted-foreground" font-size="10">{en ? 'start' : '起点'} {sampleChart.start.toFixed(0)}</text>
				</svg>
			{/if}

			<dl class="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
				<div>
					<dt class="text-muted-foreground">{en ? 'Return' : '收益'}</dt>
					<dd class="font-mono text-emerald-600">+33.98%</dd>
				</div>
				<div>
					<dt class="text-muted-foreground">{en ? 'Max drawdown' : '最大回撤'}</dt>
					<dd class="font-mono">-29.31%</dd>
				</div>
				<div>
					<dt class="text-muted-foreground">Sharpe</dt>
					<dd class="font-mono">2.59</dd>
				</div>
				<div>
					<dt class="text-muted-foreground">{en ? 'Trades' : '成交笔数'}</dt>
					<dd class="font-mono">2</dd>
				</div>
				<div class="col-span-2">
					<dt class="text-muted-foreground">{en ? 'Period' : '区间'}</dt>
					<dd class="font-mono">2023-06 → 2026-06</dd>
				</div>
			</dl>
			<p class="mt-3 text-[11px] text-muted-foreground">
				{en
					? 'Backtest on real historical data · backtest ≠ live trading · 2 trades is a small sample — demo only'
					: '真实历史数据回测 · 回测 ≠ 实盘 · 2 笔交易样本量小，仅供体验'}
			</p>
		</div>
	{:else}
		<!-- One-click presets: fill the form with a recommended config and submit immediately. -->
		<div class="mt-6">
			<div class="text-xs font-medium text-muted-foreground">{en ? 'Recommended configs — one-click backtest' : '推荐配置 一键回测'}</div>
			<div class="mt-2 grid gap-2 sm:grid-cols-3">
				{#each PRESETS as p}
					<button type="button" onclick={() => runPreset(p)} disabled={busy}
						class="rounded-md border border-border p-3 text-left hover:border-primary/50 hover:bg-primary/5 disabled:opacity-50">
						<div class="text-sm font-medium text-foreground">{en ? p.en : p.zh}</div>
						<div class="mt-1 text-xs text-muted-foreground">{en ? '~30s to results' : '~30 秒出结果'}</div>
					</button>
				{/each}
			</div>
		</div>

		<!-- Form -->
		<div class="mt-4 grid grid-cols-2 gap-4 rounded-md border border-border p-4 sm:grid-cols-4">
			<label class="text-xs">
				<span class="text-muted-foreground">{en ? 'Strategy' : '策略'}</span>
				<select
					value={strategy}
					onchange={(e) => onStrategyChange((e.currentTarget as HTMLSelectElement).value as StratKey)}
					class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm">
					{#each Object.keys(STRATEGIES) as s}
						<option value={s}>{STRATEGIES[s as StratKey].label}</option>
					{/each}
				</select>
			</label>
			<label class="text-xs">
				<span class="text-muted-foreground">{en ? 'Asset' : '标的'}</span>
				{#if strategy === 'honest_trend'}
					<!-- Combo: free-text US ticker + suggested trio via datalist (uppercase-normalized). -->
					<input
						type="text"
						list="honest-trend-assets"
						value={asset}
						oninput={(e) => (asset = (e.currentTarget as HTMLInputElement).value.toUpperCase().trim())}
						placeholder={en ? 'Any US ticker e.g. TSLA' : '任意美股代码，如 TSLA'}
						maxlength="6"
						autocomplete="off"
						spellcheck="false"
						class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm" />
					<datalist id="honest-trend-assets">
						{#each STRATEGIES.honest_trend.assets as a}<option value={a}></option>{/each}
					</datalist>
					{#if asset && !isCatalogAsset}
						<p class="mt-1 text-[11px] text-muted-foreground">
							{en ? STRATEGIES.honest_trend.note[1] : STRATEGIES.honest_trend.note[0]}
						</p>
					{/if}
				{:else}
					<select bind:value={asset} class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm">
						{#each cfg.assets as a}<option value={a}>{a}</option>{/each}
					</select>
				{/if}
			</label>
			<label class="text-xs">
				<span class="text-muted-foreground">{en ? 'Timeframe' : '周期'}</span>
				<select bind:value={tf} class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm">
					{#each tfChoices as f}<option value={f}>{f}</option>{/each}
				</select>
			</label>
			{#each Object.entries(cfg.params as Record<string, AnyParam>) as [k, p]}
				<label class="text-xs">
					<span class="text-muted-foreground">{paramLabel(k)}</span>
					{#if isChoice(p)}
						<select bind:value={params[k]} class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm">
							{#each p.choices as c}<option value={c}>{c}</option>{/each}
						</select>
					{:else}
						<input type="number" bind:value={params[k]} min={p.min} max={p.max} step={p.step ?? 1}
							class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm" />
					{/if}
				</label>
			{/each}
		</div>

		<button type="button" onclick={submit} disabled={busy}
			class="mt-4 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50">
			{busy ? (en ? 'Submitting…' : '提交中…') : en ? 'Run backtest' : '跑回测'}
		</button>

		{#if err}<p class="mt-3 text-xs text-red-600">{err}</p>{/if}

		<!-- My jobs -->
		<h2 class="mt-8 text-sm font-medium">{en ? 'My backtests' : '我的回测'}</h2>
		{#if jobs.length === 0}
			<p class="mt-2 text-xs text-muted-foreground">{en ? 'No backtests yet — submit one above.' : '还没有回测，上面提交一个。'}</p>
		{:else}
			<div class="mt-2 divide-y divide-border rounded-md border border-border text-sm">
				{#each jobs as j (j.id)}
					{@const r = results[j.id]}
					{@const done = j.status === 'done' && r}
					<div>
						<!-- Collapsed row -->
						<button type="button" onclick={() => done && toggle(j.id)}
							class="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 text-left {done ? 'cursor-pointer hover:bg-muted/30' : 'cursor-default'}">
							<span class="font-mono text-xs">{j.strategy} · {jobSummary(j)}</span>
							<span class="rounded border px-1.5 py-0.5 text-[10px] {badge(j.status)}">{j.status}</span>
							{#if done}
								{@const m = r.metrics}
								<span class="text-xs {m.return_pct >= 0 ? 'text-emerald-600' : 'text-red-600'}">{m.return_pct >= 0 ? '+' : ''}{m.return_pct}%</span>
								<span class="text-xs text-muted-foreground">DD {num(m.max_dd_pct, '%')} · Sharpe {num(m.sharpe)} · {m.trades} {en ? 'trades' : '笔'}</span>
								{#if r.equity_curve}
									<svg viewBox="0 0 96 24" width="96" height="24" class="ml-auto {m.return_pct >= 0 ? 'text-emerald-500' : 'text-red-500'}" aria-hidden="true">
										<polyline points={spark(r.equity_curve)} fill="none" stroke="currentColor" stroke-width="1" stroke-linejoin="round" />
									</svg>
								{/if}
								<span class="text-xs text-muted-foreground {r.equity_curve ? '' : 'ml-auto'}">{openId === j.id ? '▲' : '▼'}</span>
							{:else if j.status === 'error'}
								<span class="text-xs text-red-600">{j.error}</span>
							{/if}
						</button>

						<!-- Expanded detail panel -->
						{#if done && openId === j.id}
							{@const m = r.metrics}
							{@const chart = bigChart(r.equity_curve)}
							<div class="border-t border-border bg-muted/20 px-3 py-4">
								{#if chart}
									<svg viewBox="0 0 {chart.w} {chart.h}" width="100%" height={chart.h} class="max-w-[480px]" role="img"
										aria-label={en ? 'Equity curve' : '权益曲线'}>
										<!-- plot border -->
										<rect x={chart.pad} y={chart.pad} width={chart.w - chart.pad * 2} height={chart.h - chart.pad * 2}
											fill="none" class="stroke-border" stroke-width="1" />
										<!-- baseline at starting equity -->
										<line x1={chart.pad} x2={chart.w - chart.pad} y1={chart.baselineY} y2={chart.baselineY}
											class="stroke-muted-foreground/40" stroke-width="1" stroke-dasharray="3 3" />
										<!-- area + line -->
										<polygon points={chart.area} class={chart.up ? 'fill-emerald-500/10' : 'fill-red-500/10'} />
										<polyline points={chart.poly} fill="none" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"
											class={chart.up ? 'stroke-emerald-500' : 'stroke-red-500'} />
										<!-- min/max + start labels -->
										<text x={chart.w - chart.pad - 2} y={chart.pad + 10} text-anchor="end" class="fill-muted-foreground" font-size="10">{chart.hi.toFixed(0)}</text>
										<text x={chart.w - chart.pad - 2} y={chart.h - chart.pad - 3} text-anchor="end" class="fill-muted-foreground" font-size="10">{chart.lo.toFixed(0)}</text>
										<text x={chart.pad + 3} y={chart.baselineY - 3} class="fill-muted-foreground" font-size="10">{en ? 'start' : '起点'} {chart.start.toFixed(0)}</text>
									</svg>
								{:else}
									<p class="text-xs text-muted-foreground">{en ? 'No equity curve for this run.' : '本次回测无权益曲线。'}</p>
								{/if}

								<!-- Metrics -->
								<dl class="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
									<div>
										<dt class="text-muted-foreground">{en ? 'Return' : '收益'}</dt>
										<dd class="font-mono {m.return_pct >= 0 ? 'text-emerald-600' : 'text-red-600'}">{m.return_pct >= 0 ? '+' : ''}{m.return_pct}%</dd>
									</div>
									<div>
										<dt class="text-muted-foreground">{en ? 'Max drawdown' : '最大回撤'}</dt>
										<dd class="font-mono">{num(m.max_dd_pct, '%')}</dd>
									</div>
									<div>
										<dt class="text-muted-foreground">Sharpe</dt>
										<dd class="font-mono">{num(m.sharpe)}</dd>
									</div>
									<div>
										<dt class="text-muted-foreground">Calmar</dt>
										<dd class="font-mono">{num(m.calmar)}</dd>
									</div>
									<div>
										<dt class="text-muted-foreground">{en ? 'Trades' : '成交笔数'}</dt>
										<dd class="font-mono">{num(m.trades)}</dd>
									</div>
									{#if m.win_rate != null}
										<div>
											<dt class="text-muted-foreground">{en ? 'Win rate' : '胜率'}</dt>
											<dd class="font-mono">{num(m.win_rate, '%')}</dd>
										</div>
									{/if}
									{#if m.period != null}
										<div class="col-span-2">
											<dt class="text-muted-foreground">{en ? 'Period' : '区间'}</dt>
											<dd class="font-mono">{m.period}</dd>
										</div>
									{/if}
								</dl>

								<!-- Full config -->
								<div class="mt-4">
									<div class="text-xs font-medium text-muted-foreground">{en ? 'Config' : '配置'}</div>
									<dl class="mt-1 grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
										<div>
											<dt class="text-muted-foreground">{en ? 'Strategy' : '策略'}</dt>
											<dd class="font-mono">{j.strategy}</dd>
										</div>
										{#each Object.entries(j.params) as [k, v]}
											<div>
												<dt class="text-muted-foreground">{k}</dt>
												<dd class="font-mono">{v}</dd>
											</div>
										{/each}
									</dl>
								</div>

								<!-- Turn this exact config into a live signal alert -->
								<div class="mt-4 flex flex-wrap items-center gap-3">
									<button type="button" onclick={() => toSignal(j)} disabled={sigBusy === j.id}
										class="rounded-md border border-border px-3 py-1.5 text-xs text-foreground hover:bg-muted/30 disabled:opacity-50">
										🔔 {en ? 'Turn into a live signal' : '变成实时信号'}
									</button>
									{#if sigMsg[j.id]}
										<span class="text-xs {sigMsg[j.id].ok ? 'text-emerald-600' : 'text-red-600'}">{sigMsg[j.id].text}</span>
									{/if}
								</div>
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}

		<!-- Post-aha moment: they've just seen real results — offer Telegram alerts. -->
		<div class="mt-8">
			<AlertSubscribe />
		</div>

		<!-- Manage user-defined signals: list/pause/delete, create new, recent fires. -->
		<div class="mt-4">
			<MySignals />
		</div>
	{/if}
</main>
