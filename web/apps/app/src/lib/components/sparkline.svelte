<script lang="ts">
	const {
		values = [],
		color = '#7b5fff',
		height = 48
	}: { values?: number[]; color?: string; height?: number } = $props();

	// values are expected to already be normalized 0–1
	const W = 120;

	const points = $derived(() => {
		if (values.length < 2) return '';
		const step = W / (values.length - 1);
		return values
			.map((v, i) => {
				const x = i * step;
				// Flip y: 0 = bottom, 1 = top
				const y = height - v * (height - 4) - 2;
				return `${x.toFixed(1)},${y.toFixed(1)}`;
			})
			.join(' ');
	});
</script>

<svg
	viewBox="0 0 {W} {height}"
	width="100%"
	{height}
	preserveAspectRatio="none"
	aria-hidden="true"
	style="display:block;"
>
	{#if points()}
		<polyline
			points={points()}
			fill="none"
			stroke={color}
			stroke-width="1.5"
			stroke-linejoin="round"
			stroke-linecap="round"
		/>
	{/if}
</svg>
