import { getSession, setSession, readError, bindPasswordToggle, setButtonLoading, setNotice } from '/assets/api.js';

const $ = (id) => document.getElementById(id);

if (getSession()) window.location.href = '/';

bindPasswordToggle('toggle-password', 'password');

$('signup-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const notice = $('notice');
  const submitBtn = $('submit-btn');
  setNotice(notice, 'Creating your organization…');
  setButtonLoading(submitBtn, true, 'Creating…');
  try {
    const response = await fetch('/api/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        organization_name: $('organization-name').value.trim(),
        name: $('name').value.trim(),
        email: $('email').value.trim(),
        password: $('password').value,
      }),
    });
    if (!response.ok) throw new Error(await readError(response));
    setSession(await response.json());
    window.location.href = '/';
  } catch (error) {
    setNotice(notice, error.message || 'Could not create your organization.', 'error');
    setButtonLoading(submitBtn, false);
  }
});
