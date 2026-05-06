<script lang="ts">
	import { onDestroy } from 'svelte';
	import { getMetric } from '$lib/charts/glossary';
	import type { Lang } from '$lib/i18n';

	let {
		metric,
		lang,
		note,
		extraTitle,
		size = 'sm'
	}: {
		// Glossary key from $lib/charts/glossary. Missing keys silently render
		// the button as "?" so we don't ship broken UI when a key is added late.
		metric: string;
		lang: Lang;
		// Optional one-liner specific to *this* chart instance (e.g. "x = Sortino,
		// y = profit% — top-right is the sweet spot"). Appears below the rules.
		note?: string;
		// Override the popover title (defaults to the glossary entry's name).
		extraTitle?: string;
		size?: 'xs' | 'sm';
	} = $props();

	let open = $state(false);
	let popover: HTMLDivElement | undefined;
	let trigger: HTMLButtonElement | undefined;

	const copy = $derived(getMetric(metric, lang));

	function toggle(e: MouseEvent) {
		e.stopPropagation();
		open = !open;
	}

	function close() {
		open = false;
		// Return focus to the trigger so keyboard users don't lose their place.
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

	$effect(() => {
		if (open) {
			document.addEventListener('click', handleDocClick, true);
			document.addEventListener('keydown', handleKeydown);
		} else {
			document.removeEventListener('click', handleDocClick, true);
			document.removeEventListener('keydown', handleKeydown);
		}
	});

	onDestroy(() => {
		document.removeEventListener('click', handleDocClick, true);
		document.removeEventListener('keydown', handleKeydown);
	});

	const btnSize = $derived(size === 'xs' ? 'h-3.5 w-3.5 text-[9px]' : 'h-4 w-4 text-[10px]');
</script>

<span class="relative inline-block align-middle">
	<button
		type="button"
		bind:this={trigger}
		onclick={toggle}
		aria-label={lang === 'zh' ? '查看说明' : 'What is this?'}
		aria-expanded={open}
		class="inline-grid {btnSize} place-items-center rounded-full border border-border bg-card text-muted-foreground transition-colors hover:border-primary hover:text-primary"
	>
		i
	</button>

	{#if open && copy}
		<div
			bind:this={popover}
			role="dialog"
			aria-modal="false"
			class="absolute left-0 top-full z-[60] mt-1.5 w-[320px] max-w-[calc(100vw-2rem)] rounded-lg border border-border bg-card p-3.5 text-left text-xs leading-relaxed shadow-2xl shadow-black/40 sm:w-[360px]"
		>
			<div class="mb-2 flex items-baseline justify-between gap-2">
				<h3 class="text-sm font-semibold text-foreground">{extraTitle ?? copy.name}</h3>
				<button
					type="button"
					onclick={close}
					aria-label={lang === 'zh' ? '关闭' : 'Close'}
					class="-mr-1 -mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded text-base text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
				>
					×
				</button>
			</div>

			<p class="mb-2 text-foreground">
				<span class="font-semibold text-muted-foreground">{lang === 'zh' ? '是什么' : 'What'}</span>
				· {copy.plain}
			</p>

			<p class="mb-2 text-foreground">
				<span class="font-semibold text-muted-foreground">{lang === 'zh' ? '为何重要' : 'Why'}</span>
				· {copy.why}
			</p>

			{#if note}
				<p class="mb-2 text-foreground">
					<span class="font-semibold text-muted-foreground">{lang === 'zh' ? '怎么读这张图' : 'How to read'}</span>
					· {note}
				</p>
			{/if}

			{#if copy.rules && copy.rules.length > 0}
				<div class="mb-2">
					<div class="mb-1 font-semibold text-muted-foreground">{lang === 'zh' ? '经验阈值' : 'Rules of thumb'}</div>
					<ul class="ml-3 list-disc space-y-0.5 text-muted-foreground">
						{#each copy.rules as r}
							<li>{r}</li>
						{/each}
					</ul>
				</div>
			{/if}

			{#if copy.formula}
				<div class="mt-2 rounded border border-dashed border-border bg-secondary/40 px-2 py-1 font-mono text-[10px] text-muted-foreground">
					{copy.formula}
				</div>
			{/if}
		</div>
	{:else if open}
		<!-- Glossary entry missing — silently surface in dev console only. -->
		<div
			bind:this={popover}
			role="dialog"
			class="absolute left-0 top-full z-[60] mt-1.5 w-[260px] rounded-lg border border-yellow-700/50 bg-yellow-950/40 p-3 text-xs text-yellow-200 shadow-2xl"
		>
			<p>{lang === 'zh' ? '说明缺失' : 'No glossary entry'}: <code>{metric}</code></p>
			{#if note}<p class="mt-1 text-yellow-100/80">{note}</p>{/if}
		</div>
	{/if}
</span>
