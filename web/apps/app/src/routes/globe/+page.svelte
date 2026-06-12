<script lang="ts">
	import { onMount } from 'svelte';
	import type { PageData } from './$types';
	import type { Lang } from '$lib/i18n';
	import type { NewsItem } from '$lib/types';
	import MarketGlobe from '$lib/components/market-globe.svelte';
	import { EXCHANGES, isOpen, localClock, SOURCE_HQ, type NewsCity } from '$lib/globe-data';

	let { data }: { data: PageData } = $props();
	const lang = $derived<Lang>((data as { lang?: Lang }).lang ?? 'zh');
	const tr = (zh: string, en: string) => (lang === 'zh' ? zh : en);

	const news = $derived<NewsItem[]>(data.news ?? []);

	// Tick once a minute so open/closed chips + local clocks stay current.
	let now = $state(new Date());
	onMount(() => {
		const t = setInterval(() => (now = new Date()), 60_000);
		return () => clearInterval(t);
	});

	let selectedCity = $state<NewsCity | null>(null);
	const cityNews = $derived.by(() => {
		const c = selectedCity;
		if (!c) return [];
		return news.filter((n) => SOURCE_HQ[n.source] === c.city).slice(0, 12);
	});

	function newsAgo(iso: string): string {
		const t = new Date(iso).getTime();
		if (!Number.isFinite(t)) return iso?.slice(0, 10) ?? '';
		const mins = Math.floor((Date.now() - t) / 60_000);
		if (mins < 1) return tr('刚刚', 'just now');
		if (mins < 60) return tr(`${mins} 分钟前`, `${mins}m ago`);
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return tr(`${hrs} 小时前`, `${hrs}h ago`);
		return iso.slice(0, 10);
	}
</script>

<svelte:head>
	<title>{tr('全球市场 · 交易时段与快讯地球', 'Global Markets · trading hours & news globe')}</title
	>
	<meta
		name="description"
		content={tr(
			'3D 地球实时显示全球主要交易所开闭市状态,快讯按来源总部城市标注。',
			'Interactive 3D globe with live exchange open/closed status and news headlines pinned to source HQ cities.'
		)}
	/>
</svelte:head>

<main class="mx-auto w-full max-w-[1600px] px-4 py-8 sm:px-6">
	<header class="mb-6">
		<h1 class="text-2xl font-semibold tracking-tight">
			🌍 {tr('全球市场', 'Global Markets')}
		</h1>
		<p class="mt-1 text-sm text-muted-foreground">
			{tr(
				'交易所开闭市实时状态 + 市场快讯按来源总部城市标注。拖动旋转,点击琥珀色标记查看该城市快讯。',
				'Live exchange open/closed status + market-wire headlines pinned to source HQ cities. Drag to rotate; click an amber pin for that city’s headlines.'
			)}
		</p>
	</header>

	<div class="grid gap-6 lg:grid-cols-[1fr_360px]">
		<!-- Globe. min-w-0 + overflow-hidden: a grid item defaults to min-width:auto, so the
		     WebGL canvas (inserted at window.innerWidth before being resized) would otherwise
		     blow the 1fr column past the viewport and push the side panel off-screen. -->
		<div
			class="h-[420px] min-w-0 overflow-hidden rounded-xl border border-border bg-card sm:h-[560px]"
		>
			<MarketGlobe {news} {lang} onselectcity={(c) => (selectedCity = c)} />
		</div>

		<!-- Side panel -->
		<aside class="flex flex-col gap-4">
			<section class="rounded-xl border border-border bg-card p-4">
				<h2 class="mb-3 text-sm font-semibold">{tr('交易时段', 'Trading sessions')}</h2>
				<ul class="divide-y divide-border/60">
					{#each EXCHANGES as ex (ex.id)}
						{@const open = isOpen(ex, now)}
						{@const clock = localClock(ex.tz, now)}
						<li class="flex items-center gap-3 py-2 text-sm">
							<span
								class="inline-block h-2 w-2 shrink-0 rounded-full {open
									? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,.6)]'
									: 'bg-slate-500'}"
								aria-hidden="true"
							></span>
							<span class="min-w-0 flex-1">
								<span class="font-medium text-foreground">{lang === 'zh' ? ex.zh : ex.name}</span>
								<span class="ml-1 text-[11px] text-muted-foreground">{ex.hours}</span>
								{#if ex.note}
									<span class="block text-[10px] text-muted-foreground/80"
										>{lang === 'zh' ? ex.note.zh : ex.note.en}</span
									>
								{/if}
							</span>
							<span class="shrink-0 font-mono text-[11px] text-muted-foreground tabular-nums"
								>{clock.hhmm}</span
							>
							<span
								class="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold {open
									? 'bg-emerald-500/10 text-emerald-400'
									: 'bg-secondary text-muted-foreground'}"
								>{open ? tr('开市', 'Open') : tr('休市', 'Closed')}</span
							>
						</li>
					{/each}
					<!-- Crypto trades 24/7 with no single venue/HQ — shown here, never pinned on the globe. -->
					<li class="flex items-center gap-3 py-2 text-sm">
						<span
							class="inline-block h-2 w-2 shrink-0 animate-pulse rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,.6)]"
							aria-hidden="true"
						></span>
						<span class="min-w-0 flex-1">
							<span class="font-medium text-foreground">{tr('加密市场', 'Crypto')}</span>
							<span class="ml-1 text-[11px] text-muted-foreground">24/7</span>
						</span>
						<span
							class="shrink-0 rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-400"
							>{tr('全天开市', 'Always on')}</span
						>
					</li>
				</ul>
			</section>

			{#if selectedCity}
				<section class="rounded-xl border border-amber-900/40 bg-card p-4">
					<div class="mb-2 flex items-center justify-between gap-2">
						<h2 class="text-sm font-semibold">
							📰 {lang === 'zh' ? selectedCity.cityZh : selectedCity.city}
							<span class="ml-1 text-[10px] font-normal text-muted-foreground"
								>{selectedCity.sources.join(' · ')}</span
							>
						</h2>
						<button
							type="button"
							class="rounded px-1.5 text-xs text-muted-foreground hover:text-foreground"
							onclick={() => (selectedCity = null)}
							aria-label={tr('关闭', 'Close')}>✕</button
						>
					</div>
					{#if cityNews.length === 0}
						<p class="text-xs text-muted-foreground">
							{tr('该城市暂无最近快讯。', 'No recent headlines from this city.')}
						</p>
					{:else}
						<ul class="divide-y divide-border/60">
							{#each cityNews as n (n.link)}
								<li class="py-2 text-sm">
									<a
										href={n.link}
										target="_blank"
										rel="noopener"
										class="leading-snug text-foreground/90 hover:text-primary hover:underline"
										>{n.title} <span class="text-[10px] text-muted-foreground">↗</span></a
									>
									<div class="mt-0.5 text-[10px] text-muted-foreground">
										{n.source} · {newsAgo(n.published_at)}
									</div>
								</li>
							{/each}
						</ul>
					{/if}
				</section>
			{:else}
				<section
					class="rounded-xl border border-dashed border-border bg-card p-4 text-xs text-muted-foreground"
				>
					{tr(
						'点击地球上的琥珀色标记,查看该城市来源的最新快讯。',
						'Click an amber pin on the globe to see the latest headlines from that city’s sources.'
					)}
				</section>
			{/if}
		</aside>
	</div>

	<p class="mt-6 text-xs text-muted-foreground">
		{tr(
			'开闭市按常规交易时段计算,不含节假日。快讯标题原文转载。',
			'Open/closed is computed from regular trading sessions and ignores public holidays. Headlines are reposted verbatim.'
		)}
	</p>
</main>
