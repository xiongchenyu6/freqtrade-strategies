<script lang="ts">
	type Status = 'running' | 'stopped' | 'paused' | 'error' | 'long' | 'short';
	let { status, label }: { status: Status; label?: string } = $props();
	const defaultLabel: Record<Status, string> = {
		running: 'RUNNING',
		stopped: 'STOPPED',
		paused: 'PAUSED',
		error: 'ERROR',
		long: 'LONG',
		short: 'SHORT'
	};
</script>

<span class="bdv-status-pill is-{status}">
	<span class="dot"></span>
	{label ?? defaultLabel[status]}
</span>
