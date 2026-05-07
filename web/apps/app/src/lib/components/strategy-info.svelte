<script lang="ts">
	import { getStrategy } from '$lib/charts/strategies';
	import type { Lang } from '$lib/i18n';

	let {
		strategy,
		lang,
		size = 'sm'
	}: {
		// Strategy ID — looked up in $lib/charts/strategies. Missing IDs render
		// a yellow "no entry" warning so gaps are visible during rollout.
		strategy: string;
		lang: Lang;
		size?: 'xs' | 'sm';
	} = $props();

	let open = $state(false);
	let popover: HTMLDivElement | undefined;
	let trigger: HTMLButtonElement | undefined;
	// Computed (top, left) for the popover when open. Rendered with
	// `position: fixed` so it escapes any ancestor overflow:hidden / clipping
	// (e.g. sticky filter bars, table cells with truncate).
	let popoverPos = $state<{ top: number; left: number } | null>(null);

	const copy = $derived(getStrategy(strategy, lang));
	const POPOVER_W = 420;

	function computePosition() {
		if (!trigger) return;
		const r = trigger.getBoundingClientRect();
		const margin = 8;
		const vw = window.innerWidth;
		const vh = window.innerHeight;
		const wantBelow = r.bottom + margin + 260 < vh || r.top - margin - 260 < 0;
		const top = wantBelow ? r.bottom + margin : Math.max(margin, r.top - margin - 320);
		let left = r.left;
		if (left + POPOVER_W + margin > vw) left = Math.max(margin, vw - POPOVER_W - margin);
		popoverPos = { top, left };
	}

	function toggle(e: MouseEvent) {
		e.stopPropagation();
		if (!open) computePosition();
		open = !open;
	}

	function close() {
		open = false;
		trigger?.focus();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape' && open) {
			e.preventDefault();
			close();
		}
	}

	function handleDocClick(e: MouseEvent) {
		if (!open) return;
		const t = e.target as Node;
		if (popover?.contains(t)) return;
		if (trigger?.contains(t)) return;
		open = false;
	}

	function handleReposition() {
		if (open) computePosition();
	}

	// $effect runs client-only and its cleanup callback handles both
	// dependency changes and unmount — so document/window references here
	// are always safe. The previous onDestroy block touched `document`
	// unconditionally and crashed SSR with "document is not defined".
	$effect(() => {
		if (!open) return;
		document.addEventListener('click', handleDocClick, true);
		document.addEventListener('keydown', handleKeydown);
		window.addEventListener('scroll', handleReposition, true);
		window.addEventListener('resize', handleReposition);
		return () => {
			document.removeEventListener('click', handleDocClick, true);
			document.removeEventListener('keydown', handleKeydown);
			window.removeEventListener('scroll', handleReposition, true);
			window.removeEventListener('resize', handleReposition);
		};
	});

	const btnSize = $derived(size === 'xs' ? 'h-3.5 w-3.5 text-[9px]' : 'h-4 w-4 text-[10px]');
</script>

<span class="relative inline-block align-middle">
	<button
		type="button"
		bind:this={trigger}
		onclick={toggle}
		aria-label={lang === 'zh' ? '查看策略说明' : 'About this strategy'}
		aria-expanded={open}
		class="inline-grid {btnSize} place-items-center rounded-full border border-border bg-card text-muted-foreground transition-colors hover:border-primary hover:text-primary"
	>
		i
	</button>

	{#if open && copy && popoverPos}
		<div
			bind:this={popover}
			role="dialog"
			aria-modal="false"
			style="top: {popoverPos.top}px; left: {popoverPos.left}px;"
			class="fixed z-[1000] w-[360px] max-w-[calc(100vw-2rem)] rounded-lg border border-border bg-card p-4 text-left text-xs leading-relaxed shadow-2xl shadow-black/40 sm:w-[420px]"
		>
			<div class="mb-2 flex items-baseline justify-between gap-2">
				<h3 class="text-sm font-semibold text-foreground">{copy.name}</h3>
				<button
					type="button"
					onclick={close}
					aria-label={lang === 'zh' ? '关闭' : 'Close'}
					class="-mr-1 -mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded text-base text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
				>
					×
				</button>
			</div>

			<p class="mb-3 text-foreground italic">{copy.pitch}</p>

			<p class="mb-2 text-foreground">
				<span class="font-semibold text-muted-foreground">{lang === 'zh' ? '逻辑' : 'Philosophy'}</span>
				· {copy.philosophy}
			</p>

			{#if copy.factors && copy.factors.length > 0}
				<div class="mb-2">
					<span class="font-semibold text-muted-foreground">{lang === 'zh' ? '核心因子' : 'Factors'}</span>
					<div class="mt-1 flex flex-wrap gap-1">
						{#each copy.factors as f}
							<span class="rounded-full border border-border bg-secondary/60 px-2 py-0.5 font-mono text-[10px] text-foreground">{f}</span>
						{/each}
					</div>
				</div>
			{/if}

			{#if copy.bestFor}
				<p class="mb-1 text-foreground">
					<span class="font-semibold text-green-400">{lang === 'zh' ? '擅长' : 'Best for'}</span>
					· {copy.bestFor}
				</p>
			{/if}

			{#if copy.worstFor}
				<p class="mb-1 text-foreground">
					<span class="font-semibold text-red-400">{lang === 'zh' ? '不适合' : 'Worst for'}</span>
					· {copy.worstFor}
				</p>
			{/if}

			{#if copy.risk}
				<div class="mt-2 rounded border border-dashed border-border bg-secondary/40 px-2 py-1.5 text-[11px] text-muted-foreground">
					<span class="font-semibold">{lang === 'zh' ? '风险特征' : 'Risk profile'}:</span>
					{copy.risk}
				</div>
			{/if}
		</div>
	{:else if open && popoverPos}
		<div
			bind:this={popover}
			role="dialog"
			style="top: {popoverPos.top}px; left: {popoverPos.left}px;"
			class="fixed z-[1000] w-[260px] rounded-lg border border-yellow-700/50 bg-yellow-950/40 p-3 text-xs text-yellow-200 shadow-2xl"
		>
			<p>{lang === 'zh' ? '策略说明缺失' : 'No strategy entry'}: <code>{strategy}</code></p>
		</div>
	{/if}
</span>
