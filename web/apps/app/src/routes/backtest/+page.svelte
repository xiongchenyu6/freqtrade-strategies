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
		type BacktestJob,
		type BacktestResult
	} from '$lib/backtests';
	import { onMount, onDestroy } from 'svelte';

	const lang = $derived<Lang>($page.data.lang ?? 'zh');
	const en = $derived(lang === 'en');

	const cfg = STRATEGIES.honest_trend;
	let asset = $state<string>(cfg.assets[0]);
	let tf = $state<string>(cfg.timeframes[0]);
	let emaFast = $state<number>(cfg.params.ema_fast.default);
	let emaSlow = $state<number>(cfg.params.ema_slow.default);
	let busy = $state(false);
	let err = $state('');
	let jobs = $state<BacktestJob[]>([]);
	let results = $state<Record<string, BacktestResult['metrics']>>({});

	async function refresh() {
		if (!$user) return;
		try {
			jobs = await myJobs();
			for (const j of jobs) {
				if (j.status === 'done' && !results[j.id]) {
					const r = await jobResult(j.id);
					if (r) results = { ...results, [j.id]: r.metrics };
				}
			}
		} catch (e) {
			err = (e as Error).message;
		}
	}

	async function submit() {
		if (!$user?.sub) return;
		if (!(emaFast < emaSlow)) {
			err = en ? 'Fast EMA must be < slow EMA.' : '快线 EMA 必须小于慢线。';
			return;
		}
		busy = true;
		err = '';
		try {
			await submitBacktest('honest_trend', { asset, tf, ema_fast: emaFast, ema_slow: emaSlow }, $user.sub);
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
				<div class="mt-1 rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">{cfg.label}</div>
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
			<label class="text-xs">
				<span class="text-muted-foreground">EMA fast</span>
				<input type="number" bind:value={emaFast} min={cfg.params.ema_fast.min} max={cfg.params.ema_fast.max}
					class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm" />
			</label>
			<label class="text-xs">
				<span class="text-muted-foreground">EMA slow</span>
				<input type="number" bind:value={emaSlow} min={cfg.params.ema_slow.min} max={cfg.params.ema_slow.max}
					class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm" />
			</label>
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
					<div class="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2">
						<span class="font-mono text-xs">{j.strategy} · {(j.params.asset as string) ?? '?'} · {(j.params.tf as string) ?? '?'} · {(j.params.ema_fast as number) ?? '?'}/{(j.params.ema_slow as number) ?? '?'}</span>
						<span class="rounded border px-1.5 py-0.5 text-[10px] {badge(j.status)}">{j.status}</span>
						{#if j.status === 'done' && results[j.id]}
							{@const m = results[j.id]}
							<span class="text-xs {m.return_pct >= 0 ? 'text-emerald-600' : 'text-red-600'}">{m.return_pct >= 0 ? '+' : ''}{m.return_pct}%</span>
							<span class="text-xs text-muted-foreground">DD {m.max_dd_pct}% · Sharpe {m.sharpe} · {m.trades} {en ? 'trades' : '笔'}</span>
						{:else if j.status === 'error'}
							<span class="text-xs text-red-600">{j.error}</span>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</main>
