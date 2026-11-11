import { setSession, readError, bindPasswordToggle, setButtonLoading, setNotice } from '/assets/api.js';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(window.location.search);
const rawToken = params.get('token') || '';
const mode = params.get('type') === 'invite' || window.location.pathname === '/accept-invite' ? 'invite' : 'reset';

bindPasswordToggle('toggle-password', 'password');

if (!rawToken) {
  // No token: this is the "forgot password" entry point — ask for the email.
  $('form-title').textContent = 'Reset your password';
  $('form-sub').textContent = 'We\'ll email you a single-use link to set a new password.';
  $('pitch-copy').textContent = 'Forgot your password? It happens to everyone. One email, one link, done.';
  $('email-form').hidden = false;
} else {
  $('form-title').textContent = mode === 'invite' ? 'Join your team' : 'Set a new password';
  $('form-sub').textContent = mode === 'invite'
    ? 'Welcome aboard — pick the password you\'ll use to log in.'
    : 'Choose something strong — at least 8 characters.';
  $('password-form').hidden = false;
}

$('email-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const notice = $('notice');
  const btn = $('email-btn');
  setNotice(notice, 'Sending…');
  setButtonLoading(btn, true, 'Sending…');
  try {
    const res = await fetch('/api/auth/forgot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: $('email').value.trim() }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(await readError(res));
    if (data.reset_link_dev) {
      // Dev mode without SMTP: the backend hands the link back so the flow completes.
      window.location.href = data.reset_link_dev;
      return;
    }
    setNotice(notice, 'If that email has an account, a reset link is on its way.', 'success');
    setButtonLoading(btn, false);
  } catch (error) {
    setNotice(notice, error.message || 'Could not send the reset link.', 'error');
    setButtonLoading(btn, false);
  }
});

$('password-form')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const notice = $('notice');
  const btn = $('submit-btn');
  if ($('password').value !== $('password2').value) {
    setNotice(notice, 'The two passwords don\'t match.', 'error');
    return;
  }
  setNotice(notice, 'Saving…');
  setButtonLoading(btn, true, 'Saving…');
  try {
    const endpoint = mode === 'invite' ? '/api/auth/invite/accept' : '/api/auth/reset';
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: rawToken, password: $('password').value }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'That link is invalid, used, or expired.');
    setSession(data);
    window.location.href = '/';
  } catch (error) {
    setNotice(notice, error.message || 'Could not set your password.', 'error');
    setButtonLoading(btn, false);
  }
});
