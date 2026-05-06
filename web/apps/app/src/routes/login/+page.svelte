<script lang="ts">
	import { goto } from '$app/navigation';
	import { login, signup, loginWithGoogle } from '$lib/auth';
	import { page } from '$app/stores';
	import { t, type Lang } from '$lib/i18n';

	const lang = $derived<Lang>($page.data.lang ?? 'zh');
	const next = $derived($page.url.searchParams.get('next') ?? '/');
	// Only trust same-origin relative paths; reject absolute URLs to avoid open redirects.
	const safeNext = $derived(next.startsWith('/') && !next.startsWith('//') ? next : '/');

	let email = $state('');
	let password = $state('');
	let status = $state<{ msg: string; kind: 'idle' | 'ok' | 'err' | 'loading' }>({
		msg: '',
		kind: 'idle'
	});

	async function submit(mode: 'login' | 'signup') {
		status = { msg: t(lang, 'login.loading'), kind: 'loading' };
		try {
			const fn = mode === 'login' ? login : signup;
			await fn(email, password);
			status = { msg: lang === 'en' ? '✓ OK, redirecting…' : '✓ 成功，跳转中…', kind: 'ok' };
			setTimeout(() => goto(safeNext), 400);
		} catch (e) {
			status = { msg: (e as Error).message, kind: 'err' };
		}
	}

	function fmt(key: string, vars: Record<string, string>) {
		let s = t(lang, key);
		for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, v);
		return s;
	}
</script>

<svelte:head><title>{t(lang, 'login.title')} · Crypto Quant</title></svelte:head>

<main class="mx-auto mt-20 max-w-sm px-5">
	<h1 class="text-2xl font-semibold tracking-tight">{t(lang, 'login.title')} / {t(lang, 'login.signup')}</h1>
	<p class="mt-2 text-sm text-muted-foreground">
		{lang === 'en' ? 'Auth is hosted by ' : 'Auth 由 '}<code class="font-mono">auth.panda.qzz.io</code>{lang === 'en' ? ' (GoTrue).' : '（GoTrue）托管。'}
	</p>

	{#if safeNext !== '/'}
		<div class="mt-4 rounded-md border border-primary/50 bg-primary/5 p-3 text-xs">
			<div class="font-medium text-foreground">{fmt('login.why', { path: safeNext })}</div>
			<div class="mt-1 text-muted-foreground">{t(lang, 'login.publicHint')}</div>
		</div>
	{/if}

	<button
		type="button"
		onclick={() => loginWithGoogle(safeNext)}
		class="mt-6 flex w-full items-center justify-center gap-3 rounded-md border border-border bg-background px-4 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-accent"
	>
		<svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
			<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
			<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
			<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
			<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
		</svg>
		{t(lang, 'login.google')}
	</button>

	<div class="my-5 flex items-center gap-3 text-[10px] uppercase text-muted-foreground">
		<span class="h-px flex-1 bg-border"></span>
		<span>{t(lang, 'login.or')}</span>
		<span class="h-px flex-1 bg-border"></span>
	</div>

	<form
		class="flex flex-col gap-3 rounded-lg border bg-card p-5"
		onsubmit={(e) => {
			e.preventDefault();
			submit('login');
		}}
	>
		<label class="text-xs text-muted-foreground">
			{t(lang, 'login.email')}
			<input
				type="email"
				bind:value={email}
				required
				class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
			/>
		</label>
		<label class="text-xs text-muted-foreground">
			{t(lang, 'login.password')}{lang === 'en' ? ' (≥8)' : '（≥8 位）'}
			<input
				type="password"
				bind:value={password}
				minlength={8}
				required
				class="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
			/>
		</label>
		<div class="mt-2 flex gap-2">
			<button
				type="submit"
				class="flex-1 rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:opacity-90"
			>
				{t(lang, 'login.submit')}
			</button>
			<button
				type="button"
				onclick={() => submit('signup')}
				class="flex-1 rounded-md border bg-secondary px-4 py-2 text-sm text-secondary-foreground hover:bg-accent"
			>
				{t(lang, 'login.signup')}
			</button>
		</div>
		{#if status.msg}
			<div
				class="mt-2 text-xs"
				class:text-green-500={status.kind === 'ok'}
				class:text-red-500={status.kind === 'err'}
				class:text-muted-foreground={status.kind === 'loading' || status.kind === 'idle'}
			>
				{status.msg}
			</div>
		{/if}
	</form>

	<p class="mt-4 text-xs text-muted-foreground">
		{lang === 'en'
			? 'Most pages are browseable without login (anon role).'
			: '未登录也能浏览大多数内容（基于 anon 角色）。'}
	</p>
</main>
