import adapter from '@sveltejs/adapter-cloudflare';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	compilerOptions: {
		runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
	},
	kit: {
		adapter: adapter({
			platformProxy: { configPath: 'wrangler.jsonc' },
			routes: {
				include: ['/*'],
				// Don't exclude /reports/* — we want SvelteKit SSR route `/reports` (no slash)
				// to be served by Worker. Static reports/ subfolders work via CF static fallback.
				exclude: ['/_app/*', '/docs/*', '/favicon.svg', '/_headers']
			}
		}),
		prerender: {
			// During prerender, crawler follows links to /docs/* and /reports/*/
			// which aren't SvelteKit routes (Starlight + Plotly static files).
			// Skip them instead of erroring.
			handleHttpError: ({ path, referrer }) => {
				if (path.startsWith('/docs/') || path.startsWith('/reports/')) return;
				throw new Error(`404 ${path} (from ${referrer})`);
			}
		}
	}
};

export default config;
