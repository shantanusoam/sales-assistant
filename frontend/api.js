const SESSION_KEY = 'copilot_session';

export function getSession() {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const session = JSON.parse(raw);
    if (!session?.token || Date.now() >= session.expiresAt) return null;
    return session;
  } catch {
    return null;
  }
}

export function setSession({ token, expires_in, user, organization, role }) {
  const session = { token, expiresAt: Date.now() + expires_in * 1000, user, organization, role };
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  return session;
}

export function clearSession() {
  localStorage.removeItem(SESSION_KEY);
}

export function requireSession() {
  const session = getSession();
  if (!session) {
    window.location.href = '/login';
    return null;
  }
  return session;
}

export async function apiFetch(path, options = {}) {
  const session = getSession();
  const headers = { ...(options.headers || {}) };
  if (session) headers['Authorization'] = `Bearer ${session.token}`;
  return fetch(path, { ...options, headers });
}

export async function readError(response) {
  const body = await response.json().catch(() => ({}));
  return typeof body.detail === 'string' ? body.detail : 'Request failed.';
}

const EYE_OPEN = '<svg class="icon" viewBox="0 0 24 24"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7Z"/><circle cx="12" cy="12" r="3"/></svg>';
const EYE_OFF = '<svg class="icon" viewBox="0 0 24 24"><path d="M1 12s4-7 11-7c2 0 3.7.4 5.1 1.1M23 12s-1.6 3.9-5.1 5.9c-1.3.8-2.9 1.1-5 1.1-7 0-11-7-11-7"/><path d="M9.5 9.5a3 3 0 0 0 4.2 4.2"/><path d="M1 1l22 22"/></svg>';

export function bindPasswordToggle(toggleId, inputId) {
  const toggle = document.getElementById(toggleId);
  const input = document.getElementById(inputId);
  if (!toggle || !input) return;
  toggle.addEventListener('click', () => {
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    toggle.innerHTML = show ? EYE_OFF : EYE_OPEN;
    toggle.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  });
}

export function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function setButtonLoading(btn, loading, loadingLabel) {
  if (!btn) return;
  if (loading) {
    if (!btn.dataset.originalHtml) btn.dataset.originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner" aria-hidden="true"></span> ${loadingLabel}`;
  } else {
    if (btn.dataset.originalHtml) {
      btn.innerHTML = btn.dataset.originalHtml;
      delete btn.dataset.originalHtml;
    }
    btn.disabled = false;
  }
}

const NOTICE_ICONS = {
  error: '<svg class="icon" viewBox="0 0 24 24"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>',
  success: '<svg class="icon" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>',
  '': '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 16v-5"/><path d="M12 8h.01"/></svg>',
};

export function setNotice(el, message, type = '') {
  el.className = 'notice' + (type ? ' ' + type : '');
  el.innerHTML = NOTICE_ICONS[type] || NOTICE_ICONS[''];
  el.append(document.createTextNode(message));
}

if (typeof window !== 'undefined' && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}
