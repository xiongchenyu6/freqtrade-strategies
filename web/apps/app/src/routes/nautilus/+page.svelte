<script lang="ts">
	import type { PageData } from './$types';
	import type { NautilusTrade } from '$lib/types';
	import { fmtPct, fmtTime, fmtUSD } from '$lib/utils';
	import type { Lang } from '$lib/i18n';

	let { data }: { data: PageData } = $props();
	const lang = $derived<Lang>((data as { lang?: Lang }).lang ?? 'zh');
	const trades = $derived<NautilusTrade[]>(data.trades ?? []);
	const open = $derived(trades.filter((t) => !t.close_date));
	const closed = $derived(trades.filter((t) => t.close_date));

	const tr = (zh: string, en: string) => (lang === 'zh' ? zh : en);

	function pnlClass(v: number | null | undefined) {
		if (v == null) return 'text-muted-foreground';
		return v > 0 ? 'text-green-400' : v < 0 ? 'text-red-400' : 'text-muted-foreground';
	}
</script>

<svelte:head><title>{tr('Nautilus 执行引擎', 'Nautilus engine')}</title></svelte:head>

<div class="mx-auto max-w-5xl px-4 py-6">
	<div class="mb-4 flex items-center gap-3">
		<h1 class="text-xl font-semibold text-foreground">{tr('Nautilus 执行引擎', 'Nautilus engine')}</h1>
		{#if trades.length}
			{@const envs = [...new Set(trades.map((t) => t.environment))]}
			{#each envs as e}
				<span class="rounded-full border px-2 py-0.5 text-[11px] font-mono uppercase {e === 'live' ? 'border-red-700/50 bg-red-950/40 text-red-300' : 'border-yellow-700/50 bg-yellow-950/40 text-yellow-300'}">{e}</span>
			{/each}
		{/if}
	</div>
	<p class="mb-6 text-xs text-muted-foreground">
		{tr(
			'NautilusTrader 实时持仓(累积器 + Donchian 趋势),独立于 freqtrade 的成交流。',
			'Live positions from the NautilusTrader engine (accumulator + Donchian trend), separate from the freqtrade feed.'
		)}
	</p>

	{#if trades.length === 0}
		<div class="rounded-lg border border-dashed border-border bg-card p-8 text-center text-sm text-muted-foreground">
			{tr('暂无持仓 — 策略暖机中,通道填满后开始建仓。', 'No positions yet — strategies are warming up; trades appear once the channel fills.')}
		</div>
	{:else}
		<!-- Open positions -->
		<h2 class="mb-2 text-sm font-semibold text-foreground">{tr('当前持仓', 'Open')} ({open.length})</h2>
		<div class="mb-6 overflow-x-auto rounded-lg border border-border">
			<table class="w-full text-left text-xs">
				<thead class="bg-secondary/50 text-muted-foreground">
					<tr>
						<th class="px-3 py-2">{tr('标的', 'Instrument')}</th>
						<th class="px-3 py-2">{tr('策略', 'Strategy')}</th>
						<th class="px-3 py-2 text-right">{tr('数量', 'Qty')}</th>
						<th class="px-3 py-2 text-right">{tr('开仓价', 'Open')}</th>
						<th class="px-3 py-2 text-right">{tr('开仓时间', 'Opened')}</th>
					</tr>
				</thead>
				<tbody>
					{#each open as t}
						<tr class="border-t border-border">
							<td class="px-3 py-2 font-mono text-foreground">{t.instrument}</td>
							<td class="px-3 py-2 text-muted-foreground">{t.strategy}</td>
							<td class="px-3 py-2 text-right font-mono">{t.quantity ?? '—'}</td>
							<td class="px-3 py-2 text-right font-mono">{t.open_rate != null ? fmtUSD(t.open_rate) : '—'}</td>
							<td class="px-3 py-2 text-right text-muted-foreground">{fmtTime(t.open_date)}</td>
						</tr>
					{:else}
						<tr><td colspan="5" class="px-3 py-4 text-center text-muted-foreground">{tr('无', 'none')}</td></tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- Closed positions -->
		<h2 class="mb-2 text-sm font-semibold text-foreground">{tr('已平仓', 'Closed')} ({closed.length})</h2>
		<div class="overflow-x-auto rounded-lg border border-border">
			<table class="w-full text-left text-xs">
				<thead class="bg-secondary/50 text-muted-foreground">
					<tr>
						<th class="px-3 py-2">{tr('标的', 'Instrument')}</th>
						<th class="px-3 py-2">{tr('策略', 'Strategy')}</th>
						<th class="px-3 py-2 text-right">{tr('开/平', 'Open/Close')}</th>
						<th class="px-3 py-2 text-right">{tr('盈亏', 'PnL')}</th>
						<th class="px-3 py-2 text-right">{tr('收益率', 'Return')}</th>
						<th class="px-3 py-2 text-right">{tr('平仓时间', 'Closed')}</th>
					</tr>
				</thead>
				<tbody>
					{#each closed as t}
						<tr class="border-t border-border">
							<td class="px-3 py-2 font-mono text-foreground">{t.instrument}</td>
							<td class="px-3 py-2 text-muted-foreground">{t.strategy}</td>
							<td class="px-3 py-2 text-right font-mono text-muted-foreground">
								{t.open_rate != null ? fmtUSD(t.open_rate) : '—'} → {t.close_rate != null ? fmtUSD(t.close_rate) : '—'}
							</td>
							<td class="px-3 py-2 text-right font-mono {pnlClass(t.realized_pnl)}">{t.realized_pnl != null ? fmtUSD(t.realized_pnl) : '—'}</td>
							<td class="px-3 py-2 text-right font-mono {pnlClass(t.profit_pct)}">{t.profit_pct != null ? fmtPct(t.profit_pct) : '—'}</td>
							<td class="px-3 py-2 text-right text-muted-foreground">{t.close_date ? fmtTime(t.close_date) : '—'}</td>
						</tr>
					{:else}
						<tr><td colspan="6" class="px-3 py-4 text-center text-muted-foreground">{tr('无', 'none')}</td></tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
