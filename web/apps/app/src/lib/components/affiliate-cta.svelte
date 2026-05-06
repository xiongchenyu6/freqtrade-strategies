<script lang="ts">
	import { page } from '$app/stores';
	import { t, type Lang } from '$lib/i18n';
	import { AFFILIATE } from '$lib/config';

	let { variant = 'card' }: { variant?: 'card' | 'inline' } = $props();

	const lang = $derived<Lang>($page.data.lang ?? 'zh');
	const hasAny = $derived(!!(AFFILIATE.BINANCE_REF_URL || AFFILIATE.OKX_REF_URL));
</script>

{#if hasAny}
	{#if variant === 'card'}
		<section class="mb-6 rounded-xl border border-dashed bg-card p-5">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div>
					<div class="text-sm font-semibold">{t(lang, 'affiliate.title')}</div>
					<p class="mt-1 max-w-lg text-xs text-muted-foreground">{t(lang, 'affiliate.body')}</p>
				</div>
				<div class="flex flex-wrap gap-2">
					{#if AFFILIATE.BINANCE_REF_URL}
						<a
							href={AFFILIATE.BINANCE_REF_URL}
							target="_blank"
							rel="noopener nofollow sponsored"
							class="rounded-md bg-[#f3ba2f] px-4 py-2 text-sm font-medium text-black hover:opacity-90"
						>
							Binance ↗
						</a>
					{/if}
					{#if AFFILIATE.OKX_REF_URL}
						<a
							href={AFFILIATE.OKX_REF_URL}
							target="_blank"
							rel="noopener nofollow sponsored"
							class="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90"
						>
							OKX ↗
						</a>
					{/if}
				</div>
			</div>
			<p class="mt-3 text-[10px] text-muted-foreground">{t(lang, 'affiliate.disclosure')}</p>
		</section>
	{:else}
		<div class="mt-4 rounded-md border border-dashed bg-background/40 p-3 text-xs">
			<span class="text-muted-foreground">{t(lang, 'affiliate.inline')}</span>
			<span class="ml-2 inline-flex gap-2">
				{#if AFFILIATE.BINANCE_REF_URL}
					<a
						href={AFFILIATE.BINANCE_REF_URL}
						target="_blank"
						rel="noopener nofollow sponsored"
						class="text-primary hover:underline"
					>
						Binance ↗
					</a>
				{/if}
				{#if AFFILIATE.OKX_REF_URL}
					<a
						href={AFFILIATE.OKX_REF_URL}
						target="_blank"
						rel="noopener nofollow sponsored"
						class="text-primary hover:underline"
					>
						OKX ↗
					</a>
				{/if}
			</span>
		</div>
	{/if}
{/if}
