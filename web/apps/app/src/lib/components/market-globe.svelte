<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import type { NewsItem } from '$lib/types';
	import {
		EXCHANGES,
		isOpen,
		newsCities,
		type ExchangeVenue,
		type NewsCity
	} from '$lib/globe-data';
	import type { GlobeInstance } from 'globe.gl';

	let {
		news = [],
		lang = 'zh',
		onselectcity
	}: {
		news?: NewsItem[];
		lang?: 'zh' | 'en';
		onselectcity?: (city: NewsCity | null) => void;
	} = $props();

	let container = $state<HTMLDivElement>();
	let globe: GlobeInstance | null = null;
	let failed = $state(false);
	let ready = $state(false);

	type Marker =
		| ({ kind: 'exchange'; open: boolean } & ExchangeVenue)
		| ({ kind: 'news'; fresh: boolean } & NewsCity);

	const cities = $derived(newsCities(news.map((n) => n.source)));

	/** Cities with at least one headline newer than 24h get a pulsing ring. */
	const freshCities = $derived.by(() => {
		const cutoff = Date.now() - 24 * 3600_000;
		const fresh = new Set<string>();
		for (const n of news) {
			if (new Date(n.published_at).getTime() > cutoff) fresh.add(n.source);
		}
		return new Set(cities.filter((c) => c.sources.some((s) => fresh.has(s))).map((c) => c.city));
	});

	const OPEN = '#34d399'; // emerald-400
	const CLOSED = '#64748b'; // slate-500
	const NEWS = '#fbbf24'; // amber-400

	function buildMarkers(now: Date): Marker[] {
		return [
			...EXCHANGES.map((ex) => ({ kind: 'exchange' as const, open: isOpen(ex, now), ...ex })),
			...cities.map((c) => ({ kind: 'news' as const, fresh: freshCities.has(c.city), ...c }))
		];
	}

	function markerLabel(m: Marker): string {
		if (m.kind === 'exchange') {
			const status = m.open
				? lang === 'zh'
					? '开市'
					: 'Open'
				: lang === 'zh'
					? '休市'
					: 'Closed';
			return `<div style="font:12px system-ui;background:rgba(10,12,16,.9);border:1px solid rgba(148,163,184,.3);border-radius:6px;padding:4px 8px;color:#e2e8f0">
				<b>${lang === 'zh' ? m.zh : m.name}</b> · <span style="color:${m.open ? OPEN : CLOSED}">${status}</span><br/>${m.hours}</div>`;
		}
		return `<div style="font:12px system-ui;background:rgba(10,12,16,.9);border:1px solid rgba(251,191,36,.35);border-radius:6px;padding:4px 8px;color:#e2e8f0">
			<b>📰 ${lang === 'zh' ? m.cityZh : m.city}</b><br/>${m.sources.join(' · ')}</div>`;
	}

	function refresh() {
		if (!globe) return;
		const markers = buildMarkers(new Date());
		globe.pointsData(markers).ringsData(markers.filter((m) => m.kind === 'news' && m.fresh));
	}

	onMount(() => {
		if (!browser || !container) return;
		const el = container;
		let disposed = false;
		let ro: ResizeObserver | null = null;
		let timer: ReturnType<typeof setInterval> | null = null;

		(async () => {
			try {
				const { default: Globe } = await import('globe.gl');
				if (disposed) return;
				const g = new Globe(el)
					.globeImageUrl('/globe/earth-night.jpg')
					.bumpImageUrl('/globe/earth-topology.png')
					.backgroundColor('rgba(0,0,0,0)')
					.showAtmosphere(true)
					.atmosphereColor('#3b82f6')
					.atmosphereAltitude(0.18)
					.width(el.clientWidth)
					.height(el.clientHeight)
					.pointAltitude((d) => ((d as Marker).kind === 'exchange' ? 0.02 : 0.015))
					.pointRadius((d) => {
						const m = d as Marker;
						return m.kind === 'exchange' ? 0.45 + m.weight * 0.35 : 0.55;
					})
					.pointColor((d) => {
						const m = d as Marker;
						return m.kind === 'exchange' ? (m.open ? OPEN : CLOSED) : NEWS;
					})
					.pointLabel((d) => markerLabel(d as Marker))
					.onPointClick((d) => {
						const m = d as Marker;
						if (m.kind === 'news') {
							onselectcity?.({
								city: m.city,
								cityZh: m.cityZh,
								lat: m.lat,
								lng: m.lng,
								sources: m.sources
							});
						}
					})
					.ringColor(() => (t: number) => `rgba(251,191,36,${1 - t})`)
					.ringMaxRadius(3.5)
					.ringPropagationSpeed(1.4)
					.ringRepeatPeriod(1600);
				g.controls().autoRotate = true;
				g.controls().autoRotateSpeed = 0.45;
				g.pointOfView({ lat: 25, lng: 60, altitude: 2.2 }, 0);
				globe = g;
				refresh();
				ready = true;

				ro = new ResizeObserver(() => {
					if (globe) globe.width(el.clientWidth).height(el.clientHeight);
				});
				ro.observe(el);
				// Re-evaluate open/closed once a minute.
				timer = setInterval(refresh, 60_000);
			} catch {
				failed = true;
			}
		})();

		return () => {
			disposed = true;
			ro?.disconnect();
			if (timer) clearInterval(timer);
			globe?._destructor();
			globe = null;
		};
	});
</script>

{#if failed}
	<div
		class="grid h-full place-items-center rounded-xl border border-dashed border-border bg-card p-8 text-center text-sm text-muted-foreground"
	>
		{lang === 'zh'
			? '当前环境不支持 WebGL,请查看右侧交易时段列表。'
			: 'WebGL unavailable — see the trading-hours list instead.'}
	</div>
{:else}
	<div bind:this={container} class="relative h-full w-full overflow-hidden">
		{#if !ready}
			<div class="absolute inset-0 grid place-items-center text-sm text-muted-foreground">
				{lang === 'zh' ? '地球加载中…' : 'Loading globe…'}
			</div>
		{/if}
	</div>
{/if}
