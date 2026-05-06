// Public runtime config.
// On Cloudflare Pages these would come from `[vars]` at build time via Vite's
// import.meta.env. Vite requires VITE_ prefix for client exposure.

export const CONFIG = {
	API_BASE: import.meta.env.VITE_API_BASE ?? 'https://api.panda.qzz.io',
	AUTH_BASE: import.meta.env.VITE_AUTH_BASE ?? 'https://auth.panda.qzz.io',
	SUPABASE_URL: import.meta.env.VITE_SUPABASE_URL ?? 'https://rhweqsxothaezsbxjwaj.supabase.co',
	SUPABASE_ANON:
		import.meta.env.VITE_SUPABASE_ANON ?? 'sb_publishable_RRSWxhXvvaUqk3S9nF7m9A_loMqoxxw',
	// Base URL without /websocket — RealtimeClient appends it itself.
	REALTIME_URL:
		import.meta.env.VITE_REALTIME_URL ?? 'wss://quant.realtime.panda.qzz.io/socket',
	REALTIME_ANON_JWT:
		import.meta.env.VITE_REALTIME_ANON_JWT ??
		'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIiwiYXVkIjoiYXV0aGVudGljYXRlZCIsInJlZiI6InF1YW50IiwiaWF0IjoxNzc2OTM2NDk1LCJleHAiOjIwOTIyOTY0OTV9.rAObAeT1xqGAJncGoyVD_6GqGwjFVSUSE48dC-gWTSU'
};

export const DEFAULT_PAIRS = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT', 'DOGE/USDT'];

// Affiliate links — empty string hides the CTA. Override per-deploy via
// VITE_BINANCE_REF / VITE_OKX_REF in wrangler.jsonc → vars.
export const AFFILIATE = {
	BINANCE_REF_URL: import.meta.env.VITE_BINANCE_REF ?? '',
	OKX_REF_URL: import.meta.env.VITE_OKX_REF ?? '',
	GITHUB_URL: 'https://github.com/xiongchenyu6/freqtrade-strategies'
};
