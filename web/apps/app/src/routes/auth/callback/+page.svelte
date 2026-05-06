<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { consumeOauthHash } from '$lib/auth';
	import { page } from '$app/stores';
	import { t, type Lang } from '$lib/i18n';

	const lang = $derived<Lang>($page.data.lang ?? 'zh');

	let status = $state<'loading' | 'error'>('loading');
	let errMsg = $state('');

	onMount(() => {
		try {
			const s = consumeOauthHash();
			if (s) {
				const rawNext = $page.url.searchParams.get('next') ?? '/';
				const next = rawNext.startsWith('/') && !rawNext.startsWith('//') ? rawNext : '/';
				setTimeout(() => goto(next), 300);
			} else {
				status = 'error';
				errMsg = 'no token in URL';
			}
		} catch (e) {
			status = 'error';
			errMsg = (e as Error).message;
		}
	});

	function fmt(key: string, vars: Record<string, string>) {
		let s = t(lang, key);
		for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, v);
		return s;
	}
</script>

<svelte:head>
	<title>{t(lang, 'login.cbTitle')} · Crypto Quant</title>
</svelte:head>

<main class="mx-auto mt-32 max-w-md px-5 text-center">
	{#if status === 'loading'}
		<div class="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-muted border-t-primary"></div>
		<h1 class="mt-6 text-xl font-semibold">{t(lang, 'login.cbTitle')}</h1>
		<p class="mt-2 text-sm text-muted-foreground">{t(lang, 'login.cbBody')}</p>
	{:else}
		<h1 class="text-xl font-semibold text-red-500">{fmt('login.cbError', { msg: errMsg })}</h1>
		<p class="mt-4 text-sm">
			<a href="/login" class="text-primary hover:underline">← {t(lang, 'login.title')}</a>
		</p>
	{/if}
</main>
