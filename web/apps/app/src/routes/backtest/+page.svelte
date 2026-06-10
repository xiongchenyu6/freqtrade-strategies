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
	import { onMount, onDestroy } from 'svelte';

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
			await refresh();
		} catch (e) {
			err = (e as Error).message;
		} finally {
			busy = false;
		}
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
			<a href="/login?next=/backtest" class="mt-3 inline-block rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">
				{en ? 'Sign in' : '登录'}
			</a>
		</div>
	{:else}
		<!-- Form -->
		<div class="mt-6 grid grid-cols-2 gap-4 rounded-md border border-border p-4 sm:grid-cols-4">
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
				<select bind:value={asset} class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm">
					{#each cfg.assets as a}<option value={a}>{a}</option>{/each}
				</select>
			</label>
			<label class="text-xs">
				<span class="text-muted-foreground">{en ? 'Timeframe' : '周期'}</span>
				<select bind:value={tf} class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm">
					{#each cfg.timeframes as f}<option value={f}>{f}</option>{/each}
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
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</main>
