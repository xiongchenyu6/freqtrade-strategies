// GoTrue client — minimal wrapper over https://auth.panda.qzz.io
//
// Storage: localStorage keys `qt_access`, `qt_refresh`, `qt_expires`.
// JWT from GoTrue passes RLS checks on api.panda.qzz.io natively (shared JWT_SECRET).
//
// Usage:
//   import { auth } from './auth.js';
//   await auth.init();           // restores session from localStorage, refreshes if needed
//   await auth.signup(email, pw); // or signupMagicLink(email)
//   await auth.login(email, pw);
//   await auth.logout();
//   auth.token()                 // Bearer JWT or null
//   auth.user                    // decoded JWT payload or null
//   auth.on(evt, cb)             // 'login' | 'logout' | 'refresh'
import { CONFIG } from './config.js';

const STORE = {
  access:  'qt_access',
  refresh: 'qt_refresh',
  expires: 'qt_expires',
};

function b64urlDecode(s) {
  s = s.replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4) s += '=';
  try { return JSON.parse(atob(s)); } catch { return null; }
}

function decodeJWT(token) {
  if (!token) return null;
  const [, payload] = token.split('.');
  return b64urlDecode(payload);
}

class Auth extends EventTarget {
  constructor() {
    super();
    this.user = null;
    this._refreshTimer = null;
  }

  token() { return localStorage.getItem(STORE.access); }
  refreshToken() { return localStorage.getItem(STORE.refresh); }

  on(evt, cb) { this.addEventListener(evt, e => cb(e.detail)); }

  async init() {
    const acc = this.token();
    if (!acc) return;
    this.user = decodeJWT(acc);
    const expMs = parseInt(localStorage.getItem(STORE.expires) || '0');
    if (Date.now() > expMs - 60_000) {
      await this._refresh();
    } else {
      this._scheduleRefresh(expMs);
    }
  }

  async signup(email, password) {
    const r = await fetch(`${CONFIG.AUTH_BASE}/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.msg || d.error || `signup ${r.status}`);
    if (d.access_token) this._persist(d);
    return d;
  }

  async signupMagicLink(email) {
    const r = await fetch(`${CONFIG.AUTH_BASE}/magiclink`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    if (!r.ok) throw new Error(`magic link ${r.status}`);
    return true;
  }

  async login(email, password) {
    const r = await fetch(`${CONFIG.AUTH_BASE}/token?grant_type=password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error_description || d.msg || `login ${r.status}`);
    this._persist(d);
    this.dispatchEvent(new CustomEvent('login', { detail: this.user }));
    return d;
  }

  async _refresh() {
    const rt = this.refreshToken();
    if (!rt) { this.logout(); return; }
    const r = await fetch(`${CONFIG.AUTH_BASE}/token?grant_type=refresh_token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    });
    if (!r.ok) { this.logout(); return; }
    const d = await r.json();
    this._persist(d);
    this.dispatchEvent(new CustomEvent('refresh', { detail: this.user }));
  }

  _persist(tokenResp) {
    const { access_token, refresh_token, expires_in } = tokenResp;
    const expMs = Date.now() + (expires_in ?? 3600) * 1000;
    localStorage.setItem(STORE.access,  access_token);
    if (refresh_token) localStorage.setItem(STORE.refresh, refresh_token);
    localStorage.setItem(STORE.expires, String(expMs));
    this.user = decodeJWT(access_token);
    this._scheduleRefresh(expMs);
  }

  _scheduleRefresh(expMs) {
    clearTimeout(this._refreshTimer);
    // Refresh 1 min before expiry
    const delay = Math.max(5_000, (expMs - Date.now()) - 60_000);
    this._refreshTimer = setTimeout(() => this._refresh(), delay);
  }

  logout() {
    clearTimeout(this._refreshTimer);
    Object.values(STORE).forEach(k => localStorage.removeItem(k));
    this.user = null;
    this.dispatchEvent(new CustomEvent('logout', { detail: null }));
  }
}

export const auth = new Auth();
