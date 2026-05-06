<script lang="ts">
	import { page } from '$app/stores';
	import { realtimeStatus } from '$lib/realtime';
	import { t, type Lang } from '$lib/i18n';
	import bearMark from '$lib/assets/bear-mark.svg';

	let { open = $bindable(false), onclose }: { open?: boolean; onclose?: () => void } = $props();

	const lang = $derived<Lang>($page.data.lang ?? 'zh');

	type NavItem = { href: string; labelKey: string; external?: boolean };

	// Single flat nav, primary group then secondary group, separated by a divider.
	const PRIMARY_NAV = $derived<NavItem[]>([
		{ href: '/', labelKey: 'nav.home' },
		{ href: '/live', labelKey: 'nav.live' },
		{ href: '/signals', labelKey: 'nav.signals' },
		{ href: '/market', labelKey: 'nav.market' },
		{ href: '/strategies', labelKey: 'nav.strategies' },
		{ href: '/archive', labelKey: 'nav.archive' }
	]);
	const SECONDARY_NAV = $derived<NavItem[]>([
		{ href: '/dca', labelKey: 'nav.dca' },
		{ href: '/chart', labelKey: 'nav.chart' },
		{ href: '/wf', labelKey: 'nav.wf' },
		{ href: '/hyperopt', labelKey: 'nav.hyperopt' },
		{ href: '/factors', labelKey: 'nav.factors' },
		{ href: '/reports', labelKey: 'nav.reports' },
		{ href: lang === 'en' ? '/docs/en/' : '/docs/', labelKey: 'nav.docs', external: true }
	]);

	const liveDotCls = $derived(
		$realtimeStatus === 'open'
			? 'bg-[var(--profit)] shadow-[0_0_8px_color-mix(in_oklab,var(--profit)_50%,transparent)]'
			: $realtimeStatus === 'connecting'
				? 'bg-[var(--warn)]'
				: 'bg-muted-foreground/40'
	);
	const liveDotPulse = $derived(
		$realtimeStatus === 'open' || $realtimeStatus === 'connecting' ? 'animate-pulse' : ''
	);
	const liveLabel = $derived(
		$realtimeStatus === 'open'
			? 'CONNECTED'
			: $realtimeStatus === 'connecting'
				? 'CONNECTING'
				: 'OFFLINE'
	);

	function isActive(href: string, pathname: string): boolean {
		if (href === '/') return pathname === '/';
		return pathname === href || pathname.startsWith(href + '/');
	}
</script>

<!-- Mobile scrim -->
{#if open}
	<button
		type="button"
		aria-label="Close navigation"
		class="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm md:hidden"
		onclick={() => onclose?.()}
	></button>
{/if}

<aside
	class="bdv-sidebar fixed inset-y-0 left-0 z-50 flex w-[240px] flex-col border-r border-border bg-card transition-transform md:sticky md:top-0 md:h-screen md:translate-x-0"
	class:translate-x-0={open}
	class:-translate-x-full={!open}
	aria-label="Primary navigation"
>
	<!-- Brand block -->
	<a
		href="/"
		class="group flex items-center gap-2.5 px-4 py-4 border-b border-border"
		onclick={() => onclose?.()}
	>
		<span
			class="grid place-items-center w-9 h-9 rounded-md ring-1 ring-[color-mix(in_oklab,var(--dawn-500)_30%,transparent)] shadow-[0_0_14px_color-mix(in_oklab,var(--dawn-500)_18%,transparent)] transition-shadow group-hover:shadow-[0_0_18px_color-mix(in_oklab,var(--dawn-500)_32%,transparent)]"
		>
			<img src={bearMark} alt="" class="w-7 h-7" />
		</span>
		<span class="flex flex-col leading-none min-w-0">
			<span class="bdv-display text-[14px] font-bold tracking-tight">
				<span class="text-foreground">BearDawn</span><span class="bdv-grad-text">Verse</span>
			</span>
			<span class="bdv-eyebrow text-[8px] mt-1">QUANT · v1.0</span>
		</span>
	</a>

	<!-- Nav -->
	<nav class="flex-1 overflow-y-auto px-2 py-3">
		<ul class="flex flex-col gap-0.5">
			{#each PRIMARY_NAV as n (n.href)}
				{@const active = isActive(n.href, $page.url.pathname)}
				<li>
					<a
						href={n.href}
						class="bdv-side-item flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
						class:bdv-side-active={active}
						aria-current={active ? 'page' : undefined}
						onclick={() => onclose?.()}
					>
						{#if n.labelKey === 'nav.live'}
							<span class="inline-block h-2 w-2 shrink-0 rounded-full {liveDotCls} {liveDotPulse}" aria-hidden="true"></span>
						{/if}
						<span>{t(lang, n.labelKey)}</span>
					</a>
				</li>
			{/each}
		</ul>

		<div class="px-3 pt-5 pb-2">
			<div class="bdv-eyebrow text-[9px]">More</div>
		</div>

		<ul class="flex flex-col gap-0.5">
			{#each SECONDARY_NAV as n (n.href)}
				{@const active = isActive(n.href, $page.url.pathname)}
				<li>
					<a
						href={n.href}
						data-sveltekit-reload={n.external ? '' : undefined}
						class="bdv-side-item flex items-center justify-between rounded-md px-3 py-2 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
						class:bdv-side-active={active}
						aria-current={active ? 'page' : undefined}
						onclick={() => onclose?.()}
					>
						<span>{t(lang, n.labelKey)}</span>
						{#if n.external}
							<span class="text-[10px] text-muted-foreground/70">↗</span>
						{/if}
					</a>
				</li>
			{/each}
		</ul>
	</nav>

	<!-- Footer: realtime status -->
	<div class="border-t border-border px-4 py-3">
		<div class="flex items-center gap-2">
			<span class="inline-block h-1.5 w-1.5 rounded-full {liveDotCls} {liveDotPulse}" aria-hidden="true"></span>
			<span class="bdv-eyebrow text-[9px] text-muted-foreground">Realtime · {liveLabel}</span>
		</div>
	</div>
</aside>

<style>
	:global(.bdv-side-item.bdv-side-active) {
		background: linear-gradient(90deg, color-mix(in oklab, var(--dawn-500) 14%, transparent), color-mix(in oklab, var(--dawn-500) 3%, transparent));
		color: var(--foreground);
		box-shadow: inset 2px 0 0 var(--dawn-500);
	}
</style>
