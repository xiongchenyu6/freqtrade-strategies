<script lang="ts">
	import '../app.css';
	import favicon from '$lib/assets/favicon.svg';
	import { ModeWatcher } from 'mode-watcher';
	import Topbar from '$lib/components/topbar.svelte';
	import Sidebar from '$lib/components/sidebar.svelte';

	let { children } = $props();
	let sidebarOpen = $state(false);
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
