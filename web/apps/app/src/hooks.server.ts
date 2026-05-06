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
	console.error('[ssr-error]', {
		path: event.url.pathname,
		status,
		errorName: err?.name,
		errorMessage: err?.message,
		stackHead: err?.stack?.split('\n').slice(0, 4).join(' | ')
	});
	return { message: message ?? 'Internal Error' };
};
