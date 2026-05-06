// Runtime config — populated from wrangler [vars] via Pages' `window.__ENV__`
// shim or hardcoded fallback for local dev.
export const CONFIG = {
  API_BASE:      (window.__ENV__?.API_BASE)      || 'https://api.panda.qzz.io',
  AUTH_BASE:     (window.__ENV__?.AUTH_BASE)     || 'https://auth.panda.qzz.io',
  SUPABASE_URL:  (window.__ENV__?.SUPABASE_URL)  || 'https://rhweqsxothaezsbxjwaj.supabase.co',
  SUPABASE_ANON: (window.__ENV__?.SUPABASE_ANON) || 'sb_publishable_RRSWxhXvvaUqk3S9nF7m9A_loMqoxxw',
};
