<script lang="ts">
	import { page } from '$app/stores';
	import { session, logout } from '$lib/auth';
	import { goto } from '$app/navigation';
	import { t, type Lang } from '$lib/i18n';
	import LangToggle from './lang-toggle.svelte';
	import ThemeToggle from './theme-toggle.svelte';
	import { onMount, onDestroy } from 'svelte';

	let { onmenuToggle }: { onmenuToggle?: () => void } = $props();

	const lang = $derived<Lang>($page.data.lang ?? 'zh');

	let btcPrice = $state<number | null>(null);
	let btcPriceDir = $state<'up' | 'down' | 'flat'>('flat');
	let _btcInterval: ReturnType<typeof setInterval> | undefined;

	async function fetchBtcPrice() {
		try {
			const res = await fetch('https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT');
			if (!res.ok) return;
			const data = await res.json();
			const next = parseFloat(data.price);
			if (isNaN(next)) return;
			if (btcPrice === null) {
				btcPriceDir = 'flat';
			} else if (next > btcPrice) {
				btcPriceDir = 'up';
			} else if (next < btcPrice) {
				btcPriceDir = 'down';
			}
			btcPrice = next;
		} catch {
			// non-fatal — leave the price as-is
		}
	}

	onMount(() => {
		fetchBtcPrice();
		_btcInterval = setInterval(fetchBtcPrice, 30_000);
	});
	onDestroy(() => {
		if (_btcInterval) clearInterval(_btcInterval);
	});
</script>

<header
	class="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-border bg-card/80 px-4 backdrop-blur-md supports-[backdrop-filter]:bg-card/60"
>
	<div class="flex items-center gap-2 min-w-0">
		<!-- Mobile hamburger: opens the sidebar drawer -->
		<button
			type="button"
			aria-label="Toggle navigation menu"
			class="grid place-items-center h-9 w-9 rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground md:hidden"
			onclick={() => onmenuToggle?.()}
		>
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
				<path d="M4 6h16M4 12h16M4 18h16" />
			</svg>
		</button>

		<!-- Page eyebrow / breadcrumb on desktop -->
		<span class="bdv-eyebrow hidden md:inline text-[10px] tracking-[0.16em]">
			{$page.url.pathname === '/' ? 'Dashboard' : $page.url.pathname.replace(/^\//, '').toUpperCase()}
		</span>
	</div>

	<div class="flex items-center gap-2">
		{#if btcPrice !== null}
			<span class="inline-flex items-baseline gap-1.5 rounded-md border border-border/60 bg-secondary/40 px-2 py-1">
				<span class="bdv-eyebrow text-[9px]">BTC</span>
				<span
					class="bdv-num text-[12px] font-semibold tracking-tight"
					class:text-[var(--profit)]={btcPriceDir === 'up'}
					class:text-[var(--loss)]={btcPriceDir === 'down'}
					class:text-foreground={btcPriceDir === 'flat'}
				>{btcPriceDir === 'up' ? '▲' : btcPriceDir === 'down' ? '▼' : '·'} ${btcPrice.toLocaleString('en-US', { maximumFractionDigits: 0 })}</span>
			</span>
		{/if}
		<ThemeToggle />
		<LangToggle {lang} />
		{#if $session}
			<button
				type="button"
				class="rounded-md border border-border bg-secondary px-3 py-1 text-[12px] font-medium text-secondary-foreground transition-colors hover:bg-accent hover:border-border/80"
				onclick={() => { logout(); goto('/'); }}
			>{t(lang, 'topbar.logout')}</button>
		{:else}
			<a
				href="/login"
				class="rounded-md bg-gradient-to-br from-[var(--dawn-500)] to-[var(--dawn-700)] px-3 py-1 text-[12px] font-semibold text-[#0C0B1A] shadow-[0_0_0_1px_var(--dawn-glow),0_0_14px_color-mix(in_oklab,var(--dawn-500)_30%,transparent)] transition-shadow hover:shadow-[0_0_0_1px_var(--dawn-glow),0_0_22px_color-mix(in_oklab,var(--dawn-500)_50%,transparent)]"
			>{t(lang, 'topbar.login')}</a>
		{/if}
	</div>
</header>
