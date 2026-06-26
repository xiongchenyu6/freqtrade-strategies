<script lang="ts">
	import { page } from '$app/stores';
	import { realtimeStatus } from '$lib/realtime';
	import { t, type Lang } from '$lib/i18n';
	import bearMark from '$lib/assets/bear-mark.svg';
	import {
		Home,
		Compass,
		Radio,
		Cpu,
		Boxes,
		Coins,
		Globe,
		LineChart,
		Layers,
		Archive,
		Wallet,
		CandlestickChart,
		Repeat2,
		Sparkles,
		Network,
		FileText,
		FlaskConical,
		Skull,
		BookOpen
	} from 'lucide-svelte';
	import type { ComponentType } from 'svelte';

	let {
		open = $bindable(false),
		collapsed = false,
		onclose
	}: { open?: boolean; collapsed?: boolean; onclose?: () => void } = $props();

	const lang = $derived<Lang>($page.data.lang ?? 'zh');

	type NavItem = {
		href: string;
		labelKey: string;
		icon?: ComponentType;
		external?: boolean;
	};

	// Single flat nav, primary group then secondary group, separated by a divider.
	// `nav.live` deliberately has no icon — its dot doubles as a connection
	// status indicator and would conflict with a static glyph.
	const PRIMARY_NAV = $derived<NavItem[]>([
		{ href: '/', labelKey: 'nav.home', icon: Home },
		{ href: '/start', labelKey: 'nav.start', icon: Compass },
		{ href: '/live', labelKey: 'nav.live' },
		{ href: '/nautilus', labelKey: 'nav.nautilus', icon: Cpu },
		{ href: '/signals', labelKey: 'nav.signals', icon: Radio },
		{ href: '/market', labelKey: 'nav.market', icon: LineChart },
		{ href: '/semis', labelKey: 'nav.semis', icon: Boxes },
		{ href: '/commodities', labelKey: 'nav.commodities', icon: Coins },
		{ href: '/globe', labelKey: 'nav.globe', icon: Globe },
		{ href: '/strategies', labelKey: 'nav.strategies', icon: Layers },
		{ href: '/backtest', labelKey: 'nav.backtest', icon: FlaskConical },
		{ href: '/quant-lab', labelKey: 'nav.quantLab', icon: Sparkles },
		{ href: '/archive', labelKey: 'nav.archive', icon: Archive }
	]);
	const SECONDARY_NAV = $derived<NavItem[]>([
		{ href: '/dca', labelKey: 'nav.dca', icon: Wallet },
		{ href: '/chart', labelKey: 'nav.chart', icon: CandlestickChart },
		{ href: '/wf', labelKey: 'nav.wf', icon: Repeat2 },
		{ href: '/hyperopt', labelKey: 'nav.hyperopt', icon: Sparkles },
		{ href: '/factors', labelKey: 'nav.factors', icon: Network },
		{ href: '/reports', labelKey: 'nav.reports', icon: FileText },
		{ href: '/graveyard', labelKey: 'nav.graveyard', icon: Skull },
		{
			href: lang === 'en' ? '/docs/en/' : '/docs/',
			labelKey: 'nav.docs',
			icon: BookOpen,
			external: true
		}
	]);

	const liveDotCls = $derived(
		$realtimeStatus === 'open'
			? 'bg-[var(--profit)] shadow-[0_0_8px_color-mix(in_oklab,var(--profit)_50%,transparent)]'
			: 'bg-muted-foreground/40'
	);
	const liveDotPulse = $derived($realtimeStatus === 'open' ? 'animate-pulse' : '');
	const liveLabel = $derived(
		$realtimeStatus === 'open'
			? 'Realtime · Connected'
			: lang === 'en'
				? 'Data · Scheduled'
				: '数据 · 定时更新'
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

<!-- `collapsed` only applies at md+ (icon rail); the mobile drawer always renders full width. -->
<aside
	class="bdv-sidebar fixed inset-y-0 left-0 z-50 flex w-[240px] flex-col border-r border-border bg-card transition-[transform,width] duration-200 md:sticky md:top-0 md:h-screen md:translate-x-0 {collapsed
		? 'md:w-16'
		: 'md:w-[240px]'}"
	class:translate-x-0={open}
	class:-translate-x-full={!open}
	aria-label="Primary navigation"
>
	<!-- Brand block -->
	<a
		href="/"
		class="group flex items-center gap-2.5 border-b border-border px-4 py-4 {collapsed
			? 'md:justify-center md:px-0'
			: ''}"
		onclick={() => onclose?.()}
	>
		<span
			class="grid h-9 w-9 shrink-0 place-items-center rounded-md shadow-[0_0_14px_color-mix(in_oklab,var(--dawn-500)_18%,transparent)] ring-1 ring-[color-mix(in_oklab,var(--dawn-500)_30%,transparent)] transition-shadow group-hover:shadow-[0_0_18px_color-mix(in_oklab,var(--dawn-500)_32%,transparent)]"
		>
			<img src={bearMark} alt="" class="h-7 w-7" />
		</span>
		<span class="flex min-w-0 flex-col leading-none {collapsed ? 'md:hidden' : ''}">
			<span class="bdv-display text-[14px] font-bold tracking-tight">
				<span class="text-foreground">BearDawn</span><span class="bdv-grad-text">Verse</span>
			</span>
			<span class="bdv-eyebrow mt-1 text-[8px]">QUANT · v1.0</span>
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
						class="bdv-side-item flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground {collapsed
							? 'md:justify-center md:px-0'
							: ''}"
						class:bdv-side-active={active}
						aria-current={active ? 'page' : undefined}
						title={collapsed ? t(lang, n.labelKey) : undefined}
						onclick={() => onclose?.()}
					>
						<span class="bdv-side-icon grid h-4 w-4 shrink-0 place-items-center" aria-hidden="true">
							{#if n.labelKey === 'nav.live'}
								<span class="inline-block h-2 w-2 rounded-full {liveDotCls} {liveDotPulse}"></span>
							{:else if n.icon}
								<svelte:component this={n.icon} size={16} strokeWidth={1.75} />
							{/if}
						</span>
						<span class={collapsed ? 'md:hidden' : ''}>{t(lang, n.labelKey)}</span>
					</a>
				</li>
			{/each}
		</ul>

		<div class="px-3 pt-5 pb-2 {collapsed ? 'md:px-0 md:pt-3 md:pb-3' : ''}">
			<div class="bdv-eyebrow text-[9px] {collapsed ? 'md:hidden' : ''}">More</div>
			{#if collapsed}
				<div class="mx-auto hidden w-6 border-t border-border md:block"></div>
			{/if}
		</div>

		<ul class="flex flex-col gap-0.5">
			{#each SECONDARY_NAV as n (n.href)}
				{@const active = isActive(n.href, $page.url.pathname)}
				<li>
					<a
						href={n.href}
						data-sveltekit-reload={n.external ? '' : undefined}
						class="bdv-side-item flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground {collapsed
							? 'md:justify-center md:px-0'
							: ''}"
						class:bdv-side-active={active}
						aria-current={active ? 'page' : undefined}
						title={collapsed ? t(lang, n.labelKey) : undefined}
						onclick={() => onclose?.()}
					>
						<span class="bdv-side-icon grid h-4 w-4 shrink-0 place-items-center" aria-hidden="true">
							{#if n.icon}
								<svelte:component this={n.icon} size={16} strokeWidth={1.75} />
							{/if}
						</span>
						<span class="flex-1 {collapsed ? 'md:hidden' : ''}">{t(lang, n.labelKey)}</span>
						{#if n.external}
							<span class="text-[10px] text-muted-foreground/70 {collapsed ? 'md:hidden' : ''}"
								>↗</span
							>
						{/if}
					</a>
				</li>
			{/each}
		</ul>
	</nav>

	<!-- Footer: realtime status -->
	<div class="border-t border-border px-4 py-3 {collapsed ? 'md:px-0' : ''}">
		<div
			class="flex items-center gap-2 {collapsed ? 'md:justify-center' : ''}"
			title={collapsed ? liveLabel : undefined}
		>
			<span
				class="inline-block h-1.5 w-1.5 rounded-full {liveDotCls} {liveDotPulse}"
				aria-hidden="true"
			></span>
			<span class="bdv-eyebrow text-[9px] text-muted-foreground {collapsed ? 'md:hidden' : ''}"
				>{liveLabel}</span
			>
		</div>
	</div>
</aside>

<style>
	:global(.bdv-side-icon) {
		color: color-mix(in oklab, var(--muted-foreground) 80%, transparent);
		transition: color 120ms ease-out;
	}
	:global(.bdv-side-item:hover .bdv-side-icon) {
		color: var(--foreground);
	}
	:global(.bdv-side-item.bdv-side-active) {
		background: linear-gradient(
			90deg,
			color-mix(in oklab, var(--dawn-500) 14%, transparent),
			color-mix(in oklab, var(--dawn-500) 3%, transparent)
		);
		color: var(--foreground);
		box-shadow: inset 2px 0 0 var(--dawn-500);
	}
	:global(.bdv-side-item.bdv-side-active .bdv-side-icon) {
		color: var(--dawn-500);
	}
</style>
