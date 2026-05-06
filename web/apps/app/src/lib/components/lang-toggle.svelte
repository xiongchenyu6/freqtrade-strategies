<script lang="ts">
	import { invalidateAll } from '$app/navigation';
	import type { Lang } from '$lib/i18n';

	let { lang }: { lang: Lang } = $props();

	function setLang(next: Lang) {
		if (next === lang) return;
		// 1 year, site-wide; no Secure in dev but fine — this isn't sensitive.
		document.cookie = `lang=${next}; path=/; max-age=${60 * 60 * 24 * 365}; SameSite=Lax`;
		// Re-run all SSR loads so pages pick up the new cookie, without a hard nav.
		invalidateAll();
	}
</script>

<div class="flex items-center rounded-md border border-border bg-secondary p-0.5 text-[11px]">
	<button
		type="button"
		onclick={() => setLang('zh')}
		aria-pressed={lang === 'zh'}
		class="rounded px-2 py-0.5 transition-colors"
		class:bg-primary={lang === 'zh'}
		class:text-primary-foreground={lang === 'zh'}
		class:text-muted-foreground={lang !== 'zh'}>中</button
	>
	<button
		type="button"
		onclick={() => setLang('en')}
		aria-pressed={lang === 'en'}
		class="rounded px-2 py-0.5 transition-colors"
		class:bg-primary={lang === 'en'}
		class:text-primary-foreground={lang === 'en'}
		class:text-muted-foreground={lang !== 'en'}>EN</button
	>
</div>
