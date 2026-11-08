import { getSession, setSession, readError } from '/assets/api.js';

const $ = (id) => document.getElementById(id);

if (getSession()) window.location.href = '/';

$('signup-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const notice = $('notice');
  notice.className = 'notice';
  notice.textContent = 'Creating your organization…';
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
    notice.className = 'notice error';
    notice.textContent = error.message || 'Could not create your organization.';
  }
});
