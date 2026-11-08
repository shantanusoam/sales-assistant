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
