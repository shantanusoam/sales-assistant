import { requireSession, clearSession, apiFetch, escapeHtml, setButtonLoading, setNotice } from '/assets/api.js';

const $ = (id) => document.getElementById(id);
const session = requireSession();
const isAdmin = session?.role === 'admin';

if (session) {
  const chip = $('org-chip');
  const org = document.createElement('strong'); org.textContent = session.organization.name;
  const user = document.createElement('span'); user.textContent = session.user.name;
  chip.append(org, user);
}

$('logout-btn').addEventListener('click', () => {
  clearSession();
  window.location.href = '/login';
});

const ICON_TRASH = '<svg class="icon" viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>';
const ICON_LINK = '<svg class="icon" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1.5 1.5"/><path d="M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1.5-1.5"/></svg>';
const ICON_SEND = '<svg class="icon" viewBox="0 0 24 24"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4 20-7Z"/></svg>';
const ICON_USER = '<svg class="icon" viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
const ICON_BOOK = '<svg class="icon" viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/></svg>';

function fmtDate(iso) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/* ===== WhatsApp recap (per-rep opt-in) ===== */

async function loadWhatsApp() {
  try {
    const res = await apiFetch('/api/auth/me');
    if (res.ok) {
      const me = await res.json();
      session.user = { ...session.user, ...me.user };
    }
  } catch { /* use cached session user */ }
  renderWhatsApp();
}

function renderWhatsApp() {
  const user = session.user || {};
  $('whatsapp-status-tag').textContent = user.whatsapp_recap_enabled ? 'ON' : 'OFF';
  $('whatsapp-content').innerHTML = `
    <div class="field">
      <label for="whatsapp-number">Your WhatsApp number</label>
      <input id="whatsapp-number" type="tel" placeholder="+91..." value="${escapeHtml(user.whatsapp_number || '')}">
      <span class="field-hint">E.164 format, e.g. +919876543210. Your own number — recaps are sent to you, not shared.</span>
    </div>
    <label style="display:flex;align-items:center;gap:10px;font-weight:700;font-size:0.8125rem;margin:18px 0;cursor:pointer;">
      <input type="checkbox" id="whatsapp-toggle" ${user.whatsapp_recap_enabled ? 'checked' : ''} style="width:16px;height:16px;">
      Send me a WhatsApp recap (disposition, score, summary) after every call
    </label>
    <button class="button primary" type="button" id="whatsapp-save">Save</button>
    <div id="whatsapp-notice" class="notice" role="status" style="margin-top:16px;"></div>
  `;
  $('whatsapp-save').addEventListener('click', async () => {
    const notice = $('whatsapp-notice');
    const btn = $('whatsapp-save');
    const enabled = $('whatsapp-toggle').checked;
    const number = $('whatsapp-number').value.trim();
    setButtonLoading(btn, true, 'Saving…');
    try {
      const res = await apiFetch('/api/auth/me/whatsapp', {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ whatsapp_number: number || null, whatsapp_recap_enabled: enabled }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Could not save.');
      session.user.whatsapp_number = data.whatsapp_number;
      session.user.whatsapp_recap_enabled = data.whatsapp_recap_enabled;
      setNotice(notice, 'Saved.', 'success');
      $('whatsapp-status-tag').textContent = data.whatsapp_recap_enabled ? 'ON' : 'OFF';
    } catch (error) {
      setNotice(notice, error.message, 'error');
    } finally {
      setButtonLoading(btn, false);
    }
  });
}

/* ===== CRM ===== */

function renderCrmConnected(status) {
  $('crm-status-tag').textContent = 'CONNECTED';
  const providerLabel = status.provider === 'hubspot' ? 'HubSpot' : escapeHtml(status.provider);
  $('crm-content').innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:18px;">
      <span class="chip chip-positive">${providerLabel}</span>
      <span class="field-hint">Connected ${escapeHtml(fmtDate(status.connected_at))}</span>
    </div>
    <label style="display:flex;align-items:center;gap:10px;font-weight:700;font-size:0.8125rem;margin-bottom:20px;cursor:${isAdmin ? 'pointer' : 'default'};">
      <input type="checkbox" id="crm-auto-push-toggle" ${status.auto_push ? 'checked' : ''} ${isAdmin ? '' : 'disabled'} style="width:16px;height:16px;">
      Automatically push a summary to ${providerLabel} after every consented call
    </label>
    <div id="crm-notice" class="notice" role="status"></div>
    ${isAdmin ? '<button class="button danger" id="crm-disconnect-btn" type="button">Disconnect</button>' : '<p class="field-hint">Only an org admin can change this.</p>'}
  `;
  if (isAdmin) {
    $('crm-auto-push-toggle').addEventListener('change', async (e) => {
      const notice = $('crm-notice');
      try {
        const res = await apiFetch('/api/crm/settings', {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ auto_push: e.target.checked }),
        });
        if (!res.ok) throw new Error((await res.json()).detail || 'Could not update setting.');
        setNotice(notice, 'Saved.', 'success');
      } catch (error) {
        e.target.checked = !e.target.checked;
        setNotice(notice, error.message, 'error');
      }
    });
    $('crm-disconnect-btn').addEventListener('click', async () => {
      const btn = $('crm-disconnect-btn');
      setButtonLoading(btn, true, 'Disconnecting…');
      try {
        const res = await apiFetch('/api/crm/disconnect', { method: 'POST' });
        if (!res.ok) throw new Error('Could not disconnect.');
        await loadCrm();
      } catch (error) {
        setNotice($('crm-notice'), error.message, 'error');
        setButtonLoading(btn, false);
      }
    });
  }
}

function renderCrmDisconnected(status) {
  $('crm-status-tag').textContent = 'NOT CONNECTED';
  if (!isAdmin) {
    $('crm-content').innerHTML = '<p class="field-hint">No CRM is connected yet. Ask an org admin to connect one from this page.</p>';
    return;
  }
  $('crm-content').innerHTML = `
    <form id="crm-connect-form">
      <div class="field">
        <label for="crm-provider">CRM provider</label>
        <select id="crm-provider" class="settings-select">
          ${status.providers.map(p => `<option value="${escapeHtml(p)}">${p === 'hubspot' ? 'HubSpot' : escapeHtml(p)}</option>`).join('')}
        </select>
      </div>
      <div class="field" style="margin-top:14px;">
        <label for="crm-token">Private App access token</label>
        <input id="crm-token" type="password" autocomplete="off" placeholder="pat-na1-...">
        <span class="field-hint">HubSpot &rarr; Settings &rarr; Integrations &rarr; Private Apps. Needs the crm.objects.notes.write scope.</span>
      </div>
      <button class="button primary" type="submit" id="crm-connect-submit" style="margin-top:16px;">Connect &amp; test</button>
    </form>
    <div id="crm-notice" class="notice" role="status" style="margin:16px 0 0;"></div>
  `;
  $('crm-connect-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const notice = $('crm-notice');
    const btn = $('crm-connect-submit');
    setNotice(notice, 'Testing connection…');
    setButtonLoading(btn, true, 'Connecting…');
    try {
      const res = await apiFetch('/api/crm/connect', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: $('crm-provider').value, token: $('crm-token').value }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Could not connect.');
      await loadCrm();
    } catch (error) {
      setNotice(notice, error.message, 'error');
      setButtonLoading(btn, false);
    }
  });
}

async function loadCrm() {
  $('crm-status-tag').textContent = 'CHECKING';
  $('crm-content').innerHTML = '<p class="field-hint">Loading…</p>';
  try {
    const res = await apiFetch('/api/crm/status');
    if (!res.ok) throw new Error('Could not load CRM status.');
    const status = await res.json();
    if (status.connected) renderCrmConnected(status);
    else renderCrmDisconnected(status);
  } catch (error) {
    $('crm-status-tag').textContent = 'ERROR';
    $('crm-content').innerHTML = `<p class="field-hint">${escapeHtml(error.message)}</p>`;
  }
}

/* ===== Webhook nodes ===== */

function renderWebhooks(webhooks) {
  const list = webhooks.length ? `
    <div class="history-list" style="margin-bottom:18px;">
      ${webhooks.map(w => `
        <div class="history-row" style="cursor:default;flex-wrap:wrap;" data-id="${escapeHtml(w.id)}">
          <span class="channel-icon" style="${w.enabled ? '' : 'opacity:.4;'}">${ICON_LINK}</span>
          <div class="history-meta">
            <strong style="word-break:break-all;">${escapeHtml(w.url)}</strong>
            <span>Secret: <code style="user-select:all;">${escapeHtml(w.secret)}</code></span>
          </div>
          <div class="history-stats" style="gap:10px;align-items:center;">
            <label style="display:flex;align-items:center;gap:6px;cursor:${isAdmin ? 'pointer' : 'default'};">
              <input type="checkbox" class="webhook-enabled-toggle" data-id="${escapeHtml(w.id)}" ${w.enabled ? 'checked' : ''} ${isAdmin ? '' : 'disabled'} style="width:15px;height:15px;">
              Enabled
            </label>
            ${isAdmin ? `<button class="copy-btn webhook-test" type="button" data-id="${escapeHtml(w.id)}">${ICON_SEND} Test</button>` : ''}
            ${isAdmin ? `<button class="copy-btn webhook-delete" type="button" data-id="${escapeHtml(w.id)}">${ICON_TRASH} Remove</button>` : ''}
          </div>
        </div>
      `).join('')}
    </div>` : '<p class="field-hint" style="margin-bottom:18px;">No webhook nodes yet.</p>';

  $('webhook-content').innerHTML = list + (isAdmin ? `
    <form id="webhook-form" style="display:flex;gap:8px;flex-wrap:wrap;">
      <input id="webhook-url" type="url" aria-label="Webhook endpoint URL" placeholder="https://your-endpoint.example.com/sales-copilot" style="flex:1 1 260px;padding:11px 13px;border-radius:9px;border:1px solid #2c4258;background:var(--panel-2);color:var(--text);font-size:0.875rem;">
      <button class="button secondary" type="submit" id="webhook-add-btn">Add webhook</button>
    </form>
    <div id="webhook-notice" class="notice" role="status" style="margin-top:14px;"></div>
  ` : '');

  if (!isAdmin) return;

  document.querySelectorAll('.webhook-enabled-toggle').forEach(el => {
    el.addEventListener('change', async (e) => {
      const id = e.target.dataset.id;
      try {
        const res = await apiFetch(`/api/webhooks/${id}`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: e.target.checked }),
        });
        if (!res.ok) throw new Error('Could not update webhook.');
      } catch (error) {
        e.target.checked = !e.target.checked;
        setNotice($('webhook-notice'), error.message, 'error');
      }
    });
  });
  document.querySelectorAll('.webhook-test').forEach(el => {
    el.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const id = btn.dataset.id;
      setButtonLoading(btn, true, 'Sending…');
      try {
        const res = await apiFetch(`/api/webhooks/${id}/test`, { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Webhook test failed.');
        setNotice($('webhook-notice'), `Test payload delivered (HTTP ${data.status_code}).`, 'success');
      } catch (error) {
        setNotice($('webhook-notice'), error.message, 'error');
      } finally {
        setButtonLoading(btn, false);
      }
    });
  });
  document.querySelectorAll('.webhook-delete').forEach(el => {
    el.addEventListener('click', async (e) => {
      const id = e.currentTarget.dataset.id;
      try {
        const res = await apiFetch(`/api/webhooks/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Could not remove webhook.');
        await loadWebhooks();
      } catch (error) {
        setNotice($('webhook-notice'), error.message, 'error');
      }
    });
  });
  $('webhook-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const notice = $('webhook-notice');
    const btn = $('webhook-add-btn');
    setButtonLoading(btn, true, 'Adding…');
    try {
      const res = await apiFetch('/api/webhooks', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: $('webhook-url').value.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Could not add webhook.');
      await loadWebhooks();
    } catch (error) {
      setNotice(notice, error.message, 'error');
      setButtonLoading(btn, false);
    }
  });
}

async function loadWebhookDeliveries() {
  const container = $('webhook-deliveries');
  if (!container || !isAdmin) return;
  try {
    const res = await apiFetch('/api/webhooks/deliveries');
    if (!res.ok) return; // non-admins never see the container
    const { deliveries } = await res.json();
    if (!deliveries.length) {
      container.innerHTML = '<p class="field-hint">No webhook deliveries yet — rows appear here after the first consented call.</p>';
      return;
    }
    container.innerHTML = `
      <div class="field-hint-row" style="margin-bottom:8px;"><span class="label-xs">Recent deliveries</span></div>
      <div class="history-list">
        ${deliveries.slice(0, 10).map(d => `
          <div class="history-row" style="cursor:default;padding:10px 14px;">
            <span class="chip ${d.delivered ? 'chip-positive' : 'chip-negative'}">${d.delivered ? 'Delivered' : 'Failed'}</span>
            <div class="history-meta">
              <strong style="word-break:break-all;font-size:0.75rem;">${escapeHtml(d.url || 'removed webhook')} · ${escapeHtml(d.event)}</strong>
              <span>${escapeHtml(fmtDate(d.created_at))} · attempt ${d.attempts}${d.next_retry_at && !d.delivered ? ` · retry scheduled` : ''}${d.error ? ` · ${escapeHtml(d.error)}` : ''}</span>
            </div>
            ${d.status_code ? `<span class="head-tag">${d.status_code}</span>` : ''}
          </div>
        `).join('')}
      </div>
    `;
  } catch { /* deliveries are supplementary; never break the panel */ }
}

async function loadWebhooks() {
  $('webhook-content').innerHTML = '<p class="field-hint">Loading…</p>';
  try {
    const res = await apiFetch('/api/webhooks');
    if (!res.ok) throw new Error('Could not load webhooks.');
    const { webhooks } = await res.json();
    renderWebhooks(webhooks);
    await loadWebhookDeliveries();
  } catch (error) {
    $('webhook-content').innerHTML = `<p class="field-hint">${escapeHtml(error.message)}</p>`;
  }
}

/* ===== Team members & invites ===== */

function renderTeam(members) {
  $('team-status-tag').textContent = `${members.length} ${members.length === 1 ? 'MEMBER' : 'MEMBERS'}`;
  const listHtml = `
    <div class="history-list" style="margin-bottom:18px;">
      ${members.map(m => `
        <div class="history-row" style="cursor:default;">
          <span class="channel-icon">${ICON_USER}</span>
          <div class="history-meta">
            <strong>${escapeHtml(m.name)}</strong>
            <span>${escapeHtml(m.email)}</span>
          </div>
          <div class="history-stats">
            <span class="chip ${m.role === 'admin' ? 'chip-positive' : 'chip-neutral'}">${escapeHtml(m.role)}</span>
          </div>
        </div>
      `).join('')}
    </div>
  `;
  const inviteHtml = isAdmin ? `
    <form id="team-invite-form" class="settings-subform">
      <div class="field">
        <label for="invite-name">Teammate name</label>
        <input id="invite-name" type="text" placeholder="Priya Sharma" required>
      </div>
      <div class="field">
        <label for="invite-email">Work email</label>
        <input id="invite-email" type="email" placeholder="priya@company.com" required>
      </div>
      <div class="settings-row-2">
        <div class="field">
          <label for="invite-role">Role</label>
          <select id="invite-role" class="settings-select">
            <option value="rep">Rep</option>
            <option value="manager">Manager</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <div class="field">
          <label for="invite-password">Temporary password</label>
          <input id="invite-password" type="password" minlength="8" placeholder="At least 8 characters" required>
        </div>
      </div>
      <button class="button secondary" type="submit" id="invite-submit-btn">Add teammate</button>
    </form>
    <div id="team-notice" class="notice" role="status" style="margin-top:14px;"></div>
  ` : '<p class="field-hint">Only an org admin can invite new teammates.</p>';

  $('team-content').innerHTML = listHtml + inviteHtml;
  if (!isAdmin) return;

  $('team-invite-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('invite-submit-btn');
    const notice = $('team-notice');
    setButtonLoading(btn, true, 'Adding…');
    try {
      const res = await apiFetch('/api/auth/invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: $('invite-name').value.trim(),
          email: $('invite-email').value.trim(),
          role: $('invite-role').value,
          password: $('invite-password').value,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || 'Could not invite teammate.');
      await loadTeam();
      setNotice($('team-notice'), `Added ${data.user.name} (${data.role}).`, 'success');
    } catch (error) {
      setNotice(notice, error.message, 'error');
      setButtonLoading(btn, false);
    }
  });
}

async function loadTeam() {
  $('team-content').innerHTML = '<p class="field-hint">Loading…</p>';
  try {
    const res = await apiFetch('/api/auth/team');
    if (!res.ok) throw new Error('Could not load team members.');
    const { members } = await res.json();
    renderTeam(members);
  } catch (error) {
    $('team-status-tag').textContent = 'ERROR';
    $('team-content').innerHTML = `<p class="field-hint">${escapeHtml(error.message)}</p>`;
  }
}

/* ===== Sales playbooks ===== */

function renderPlaybooks(data) {
  const { playbooks, total_chunks: totalChunks } = data;
  $('playbook-status-tag').textContent = `${playbooks.length} DOCS · ${totalChunks} CHUNKS`;
  const listHtml = playbooks.length ? `
    <div class="history-list" style="margin-bottom:18px;">
      ${playbooks.map(p => `
        <details class="playbook-item" data-slug="${escapeHtml(p.slug)}">
          <summary class="playbook-summary">
            <span class="channel-icon">${ICON_BOOK}</span>
            <div class="history-meta">
              <strong>${escapeHtml(p.title)}</strong>
              <span>${escapeHtml(p.filename)} &middot; ${Math.max(1, Math.round(p.size_bytes / 100) / 10)} KB</span>
            </div>
            ${isAdmin && playbooks.length > 1 ? `<button class="copy-btn playbook-delete" type="button" data-slug="${escapeHtml(p.slug)}">${ICON_TRASH} Delete</button>` : ''}
          </summary>
          <pre class="playbook-pre">${escapeHtml(p.content)}</pre>
        </details>
      `).join('')}
    </div>
  ` : '<p class="field-hint" style="margin-bottom:18px;">No playbooks found.</p>';

  const formHtml = isAdmin ? `
    <form id="playbook-form" class="settings-subform">
      <div class="field">
        <label for="playbook-title">New or updated playbook title</label>
        <input id="playbook-title" type="text" placeholder="03 Pricing & Enterprise Tiers" required>
      </div>
      <div class="field">
        <label for="playbook-body">Playbook content (Markdown)</label>
        <textarea id="playbook-body" rows="4" placeholder="## Enterprise objection handling&#10;When a prospect raises budget concerns, first quantify missed follow-up cost..." required></textarea>
      </div>
      <button class="button secondary" type="submit" id="playbook-save-btn">Save &amp; reload index</button>
    </form>
    <div id="playbook-notice" class="notice" role="status" style="margin-top:14px;"></div>
  ` : '<p class="field-hint">Only an org admin can add or edit sales playbooks.</p>';

  $('playbook-content').innerHTML = listHtml + formHtml;
  if (!isAdmin) return;

  document.querySelectorAll('.playbook-delete').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const slug = btn.dataset.slug;
      try {
        const res = await apiFetch(`/api/playbooks/${encodeURIComponent(slug)}`, { method: 'DELETE' });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(body.detail || 'Could not delete playbook.');
        await loadPlaybooks();
      } catch (error) {
        setNotice($('playbook-notice'), error.message, 'error');
      }
    });
  });

  $('playbook-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('playbook-save-btn');
    const notice = $('playbook-notice');
    setButtonLoading(btn, true, 'Saving…');
    try {
      const res = await apiFetch('/api/playbooks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: $('playbook-title').value.trim(),
          content: $('playbook-body').value.trim(),
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || 'Could not save playbook.');
      await loadPlaybooks();
      setNotice($('playbook-notice'), `Saved "${body.playbook.title}" (${body.total_chunks} active chunks).`, 'success');
    } catch (error) {
      setNotice(notice, error.message, 'error');
      setButtonLoading(btn, false);
    }
  });
}

async function loadPlaybooks() {
  $('playbook-content').innerHTML = '<p class="field-hint">Loading…</p>';
  try {
    const res = await apiFetch('/api/playbooks');
    if (!res.ok) throw new Error('Could not load playbooks.');
    renderPlaybooks(await res.json());
  } catch (error) {
    $('playbook-status-tag').textContent = 'ERROR';
    $('playbook-content').innerHTML = `<p class="field-hint">${escapeHtml(error.message)}</p>`;
  }
}

/* ===== Billing & usage ===== */

async function loadBilling() {
  $('billing-content').innerHTML = '<p class="field-hint">Loading…</p>';
  try {
    const res = await apiFetch('/api/billing/status');
    if (!res.ok) throw new Error('Could not load billing status.');
    const status = await res.json();
    $('billing-status-tag').textContent = status.plan.toUpperCase();
    const limitText = status.monthly_call_limit === null ? 'No limit' : `${status.calls_used_this_month} / ${status.monthly_call_limit}`;
    const pct = status.monthly_call_limit ? Math.min(100, Math.round(100 * status.calls_used_this_month / status.monthly_call_limit)) : 0;
    const planRows = Object.entries(status.plans).map(([key, meta]) => `
      <div class="history-row" style="cursor:default;padding:12px 16px;">
        <div class="history-meta">
          <strong>${escapeHtml(meta.label)}${key === status.plan ? ' <span class="chip chip-positive">Current</span>' : ''}</strong>
          <span>${meta.monthly_calls === null ? 'Unlimited calls / month' : `${meta.monthly_calls} calls / month`} &middot; ${escapeHtml(meta.price_note)}</span>
        </div>
        ${isAdmin && key !== status.plan ? `<button class="copy-btn billing-plan-btn" type="button" data-plan="${escapeHtml(key)}">Switch</button>` : ''}
      </div>
    `).join('');
    $('billing-content').innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">
        <strong style="font-size:0.875rem;">Calls this month</strong>
        <span style="font-variant-numeric:tabular-nums;font-weight:800;">${escapeHtml(limitText)}</span>
      </div>
      <div style="height:10px;border-radius:6px;background:var(--orange);overflow:hidden;margin-bottom:18px;">
        <div style="height:100%;width:${pct}%;background:var(--blue);"></div>
      </div>
      <div class="history-list">${planRows}</div>
      ${isAdmin ? '<div id="billing-notice" class="notice" role="status" style="margin-top:14px;"></div>' : '<p class="field-hint" style="margin-top:14px;">Only an org admin can change the plan.</p>'}
    `;
    if (!isAdmin) return;
    document.querySelectorAll('.billing-plan-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        setButtonLoading(btn, true, 'Switching…');
        try {
          const res = await apiFetch('/api/billing/plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plan: btn.dataset.plan }),
          });
          const body = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(body.detail || 'Could not switch plan.');
          await loadBilling();
        } catch (error) {
          setNotice($('billing-notice'), error.message, 'error');
          setButtonLoading(btn, false);
        }
      });
    });
  } catch (error) {
    $('billing-status-tag').textContent = 'ERROR';
    $('billing-content').innerHTML = `<p class="field-hint">${escapeHtml(error.message)}</p>`;
  }
}

if (session) {
  loadBilling();
  loadWhatsApp();
  loadCrm();
  loadWebhooks();
  loadTeam();
  loadPlaybooks();
}
