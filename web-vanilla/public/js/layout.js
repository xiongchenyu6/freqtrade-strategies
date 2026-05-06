// Shared top-bar that renders auth status + nav across all pages.
import { auth } from './auth.js';

const NAV = [
  { href: '/',         label: '🏠 主页' },
  { href: '/chart',    label: '📉 Chart' },
  { href: '/archive',  label: '📦 Archive' },
  { href: '/activity', label: '📡 Activity' },
];

export function mountTopbar(currentPath) {
  const bar = document.createElement('div');
  bar.className = 'topbar';
  bar.innerHTML = `
    <div class="nav">
      ${NAV.map(n => `<a href="${n.href}" ${n.href === currentPath ? 'style="color:#f0f6fc"' : ''}>${n.label}</a>`).join('')}
    </div>
    <div class="auth-box" id="auth-box"></div>
  `;
  document.body.prepend(bar);
  renderAuth();
  auth.on('login',  renderAuth);
  auth.on('logout', renderAuth);
  auth.on('refresh', renderAuth);
}

function renderAuth() {
  const el = document.getElementById('auth-box');
  if (!el) return;
  if (auth.user?.email) {
    el.innerHTML = `
      <span class="who">${auth.user.email}</span>
      <button class="btn" onclick="window.__logout()">Logout</button>
    `;
  } else {
    el.innerHTML = `<a href="/login" class="btn primary">登录</a>`;
  }
}

window.__logout = () => auth.logout();
