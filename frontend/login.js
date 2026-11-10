import { getSession, setSession, readError, bindPasswordToggle, setButtonLoading, setNotice } from '/assets/api.js';

const $ = (id) => document.getElementById(id);

if (getSession()) window.location.href = '/';

bindPasswordToggle('toggle-password', 'password');

$('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const notice = $('notice');
  const submitBtn = $('submit-btn');
  setNotice(notice, 'Signing in…');
  setButtonLoading(submitBtn, true, 'Signing in…');
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: $('email').value.trim(), password: $('password').value }),
    });
    if (!response.ok) throw new Error(await readError(response));
    setSession(await response.json());
    window.location.href = '/';
  } catch (error) {
    setNotice(notice, error.message || 'Login failed.', 'error');
    setButtonLoading(submitBtn, false);
  }
});
