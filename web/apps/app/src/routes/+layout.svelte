<script lang="ts">
	import '../app.css';
	import favicon from '$lib/assets/favicon.svg';
	import { ModeWatcher } from 'mode-watcher';
	import { afterNavigate } from '$app/navigation';
	import Topbar from '$lib/components/topbar.svelte';
	import Sidebar from '$lib/components/sidebar.svelte';
	import OnboardingTour from '$lib/components/onboarding-tour.svelte';
	import { track } from '$lib/track';

	let { children } = $props();
	let sidebarOpen = $state(false);

	// First-party analytics: one page_view per navigation (de-duped in track()).
	afterNavigate((nav) => track('page_view', nav.to?.url.pathname));
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>
<ModeWatcher defaultMode="dark" />
<div class="min-h-screen bdv-app-bg text-foreground md:grid md:grid-cols-[240px_1fr]">
	<Sidebar bind:open={sidebarOpen} onclose={() => (sidebarOpen = false)} />
	<div class="flex min-w-0 flex-col">
		<Topbar onmenuToggle={() => (sidebarOpen = !sidebarOpen)} />
		{@render children()}
	</div>
</div>
<OnboardingTour />
