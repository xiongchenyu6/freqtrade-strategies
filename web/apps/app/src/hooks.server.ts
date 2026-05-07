import type { Handle, HandleServerError } from '@sveltejs/kit';
import { normalizeLang } from '$lib/i18n';

export const handle: Handle = async ({ event, resolve }) => {
	const cookie = event.cookies.get('lang');
	event.locals.lang = normalizeLang(cookie);
	const htmlLang = event.locals.lang === 'en' ? 'en' : 'zh-CN';
	return resolve(event, {
		transformPageChunk: ({ html }) => html.replace('%lang%', htmlLang)
	});
};

// Surface SSR errors to wrangler tail so unexpected page failures show up
// with context (path, error name, stack head) without dumping full traces.
export const handleError: HandleServerError = ({ error, event, status, message }) => {
	const err = error as Error;
	const cookieKeys = event.cookies.getAll().map((c) => c.name);
	console.error('[ssr-error]', JSON.stringify({
		path: event.url.pathname,
		status,
		cookieKeys,
		errorName: err?.name,
		errorMessage: err?.message,
		stack: err?.stack
	}));
	return { message: message ?? 'Internal Error' };
};
