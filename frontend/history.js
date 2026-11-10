import { requireSession, clearSession, apiFetch, escapeHtml, setButtonLoading } from '/assets/api.js';

const $ = (id) => document.getElementById(id);
const session = requireSession();
if (!session) { /* requireSession already redirected */ }
else {
  const chip = $('org-chip');
  const org = document.createElement('strong'); org.textContent = session.organization.name;
  const user = document.createElement('span'); user.textContent = session.user.name;
  chip.append(org, user);
}

$('logout-btn').addEventListener('click', () => {
  clearSession();
  window.location.href = '/login';
});

const ICONS = {
  mic: '<svg class="icon" viewBox="0 0 24 24"><path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Z"/><path d="M19 11a7 7 0 0 1-14 0"/><path d="M12 18v3"/><path d="M8 21h8"/></svg>',
  phone: '<svg class="icon" viewBox="0 0 24 24"><path d="M5 4h4l2 5-2.5 2.5a11 11 0 0 0 5 5L14 14l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2Z"/></svg>',
  back: '<svg class="icon" viewBox="0 0 24 24"><path d="M19 12H5"/><path d="M11 18l-6-6 6-6"/></svg>',
  empty: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  error: '<svg class="icon" viewBox="0 0 24 24"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>',
  clock: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  copy: '<svg class="icon" viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
  refresh: '<svg class="icon" viewBox="0 0 24 24"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>',
};

function scoreTier(score) {
  if (score >= 75) return 'high';
  if (score >= 50) return 'mid';
  return 'low';
}

const DISPOSITIONS = {
  interested: { label: 'Interested', cls: 'chip-positive' },
  not_interested: { label: 'Not interested', cls: 'chip-negative' },
  follow_up: { label: 'Follow-up', cls: 'chip-neutral' },
  no_decision: { label: 'No decision', cls: 'chip-neutral' },
  do_not_contact: { label: 'Do not contact', cls: 'chip-negative' },
};
function dispositionChip(disposition) {
  if (!disposition) return '';
  const meta = DISPOSITIONS[disposition] || { label: disposition, cls: 'chip-neutral' };
  return `<span class="chip ${meta.cls}">${escapeHtml(meta.label)}</span>`;
}

function fmtDate(iso) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}
function fmtDuration(startIso, endIso) {
  if (!endIso) return 'In progress';
  const seconds = Math.max(0, Math.round((new Date(endIso) - new Date(startIso)) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}
const SOURCE_LABELS = {
  'manual-test': 'Rep (test)',
  'customer-test': 'Customer (test)',
  microphone: 'Microphone',
  'twilio-customer': 'Customer',
  'twilio-rep': 'Rep',
};

function renderOverview(analytics) {
  const el = $('history-overview');
  if (!el || !analytics || !analytics.total_calls) {
    if (el) el.hidden = true;
    return;
  }
  const positiveOutcomes = (analytics.dispositions?.interested || 0) + (analytics.dispositions?.follow_up || 0);
  const avgScore = analytics.avg_coaching_score !== null && analytics.avg_coaching_score !== undefined
    ? `${analytics.avg_coaching_score}/100`
    : '—';
  el.hidden = false;
  el.innerHTML = `
    <div class="overview-strip">
      <div class="overview-item">
        <span class="signal-label">Total calls</span>
        <strong>${analytics.total_calls}</strong>
        <small>${analytics.completed_calls} completed &middot; ${analytics.consented_calls} consented</small>
      </div>
      <div class="overview-item">
        <span class="signal-label">Avg coaching score</span>
        <strong>${escapeHtml(avgScore)}</strong>
        <small>${analytics.total_hints} hints delivered across ${analytics.total_turns} turns</small>
      </div>
      <div class="overview-item">
        <span class="signal-label">Positive outcomes</span>
        <strong>${positiveOutcomes}</strong>
        <small>${analytics.dispositions?.interested || 0} interested &middot; ${analytics.dispositions?.follow_up || 0} follow-up</small>
      </div>
      <div class="overview-item">
        <span class="signal-label">Objections surfaced</span>
        <strong>${analytics.total_objections}</strong>
        <small>Flagged live across team calls</small>
      </div>
    </div>
  `;
}

async function loadAnalytics() {
  try {
    const res = await apiFetch('/api/calls/analytics');
    if (res.ok) renderOverview(await res.json());
  } catch { /* non-blocking */ }
}

function renderLoading() {
  $('content').innerHTML = '<div class="empty-state"><div class="empty-art"><span class="spinner" style="width:20px;height:20px;"></span></div><h3>Loading call history…</h3></div>';
}

function renderError(message) {
  $('content').innerHTML = `<div class="empty-state"><div class="empty-art">${ICONS.error}</div><h3>Couldn't load call history</h3><p>${escapeHtml(message)}</p></div>`;
}

function renderEmpty(hasFilters = false) {
  if (hasFilters) {
    $('content').innerHTML = `<div class="empty-state"><div class="empty-art">${ICONS.empty}</div><div><h3>No matching calls</h3><p>Try clearing the search query or outcome/channel filters above.</p></div></div>`;
    return;
  }
  $('content').innerHTML = `<div class="empty-state"><div class="empty-art">${ICONS.empty}</div><div><h3>No calls yet</h3><p>Connect on the live call page or place a Twilio call &mdash; it will show up here once it ends.</p></div></div>`;
}

function channelLabel(call) {
  if (call.channel === 'twilio') return `Phone call${call.to_number ? ' · ' + escapeHtml(call.to_number) : ''}`;
  if (call.channel === 'mobile') return `Mobile field call${call.to_number ? ' · ' + escapeHtml(call.to_number) : ''}`;
  return 'Live mic session';
}

function renderList(calls, hasFilters = false) {
  if (!calls.length) return renderEmpty(hasFilters);
  const list = document.createElement('div');
  list.className = 'history-list';
  for (const call of calls) {
    const row = document.createElement('div');
    row.className = `history-row channel-${call.channel}`;
    const titleText = channelLabel(call);
    const repBit = call.rep_name ? ` &middot; ${escapeHtml(call.rep_name)}` : '';
    const previewBit = call.summary_preview
      ? `<p class="history-preview">${escapeHtml(call.summary_preview)}</p>`
      : '';
    row.innerHTML = `
      <span class="channel-icon">${call.channel === 'twilio' || call.channel === 'mobile' ? ICONS.phone : ICONS.mic}</span>
      <div class="history-meta">
        <strong>${titleText}</strong>
        <span>${escapeHtml(fmtDate(call.started_at))} &middot; ${escapeHtml(fmtDuration(call.started_at, call.ended_at))}${repBit}</span>
        ${previewBit}
      </div>
      <div class="history-stats">
        <span><b>${call.turn_count}</b> turns</span>
        <span><b>${call.hint_count}</b> hints</span>
        ${call.objection_count > 0 ? `<span><b>${call.objection_count}</b> obj</span>` : ''}
        ${dispositionChip(call.disposition)}
        ${call.coaching_score !== null ? `<span class="score-pill score-${scoreTier(call.coaching_score)}">${call.coaching_score}/100</span>` : ''}
      </div>`;
    row.addEventListener('click', () => loadDetail(call.id));
    list.append(row);
  }
  $('content').replaceChildren(list);
}

async function loadDetail(callId) {
  if ($('history-toolbar')) $('history-toolbar').hidden = true;
  renderLoading();
  try {
    const res = await apiFetch(`/api/calls/${callId}`);
    if (!res.ok) throw new Error('Call not found.');
    const call = await res.json();
    renderDetail(call);
  } catch (error) {
    renderError(error.message || 'Something went wrong.');
  }
}

function renderDetail(call) {
  const wrap = document.createElement('div');
  const back = document.createElement('a');
  back.className = 'back-link'; back.href = '#';
  back.innerHTML = `${ICONS.back} Back to call history`;
  back.addEventListener('click', (e) => { e.preventDefault(); loadList(); });

  const phoneMeta = call.to_number ? ` &middot; To ${escapeHtml(call.to_number)}` : '';
  const repMeta = call.rep_name ? ` &middot; Rep: ${escapeHtml(call.rep_name)}` : '';
  const heading = document.createElement('div');
  heading.innerHTML = `<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:space-between;">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <strong style="font-size:1rem;">${channelLabel(call)}</strong>
        ${dispositionChip(call.disposition)}
        ${!call.consent_confirmed ? '<span class="chip chip-neutral">Consent not confirmed &mdash; not distributed externally</span>' : '<span class="chip chip-positive">Consent confirmed</span>'}
      </div>
      <button class="copy-btn" type="button" id="regenerate-summary-btn">${ICONS.refresh} ${call.summary ? 'Refresh summary' : 'Generate summary'}</button>
    </div>
    <p style="color:var(--secondary);font-size:0.8125rem;margin:6px 0 20px;">${escapeHtml(fmtDate(call.started_at))} &middot; ${escapeHtml(fmtDuration(call.started_at, call.ended_at))}${repMeta}${phoneMeta} &middot; ${call.turn_count} turns &middot; ${call.hint_count} hints</p>`;

  const summaryBlock = document.createElement('div');
  if (call.summary) {
    const s = call.summary;
    const tier = scoreTier(s.coaching_score);
    summaryBlock.className = 'summary-card';
    summaryBlock.innerHTML = `
      <div class="summary-card-head">
        <h3>Post-call summary <span class="head-tag" style="margin-left:8px;">${s.method === 'ai' ? 'AI' : 'RULES DEMO'}</span></h3>
        <div class="coaching-score score-${tier}"><b>${s.coaching_score}</b><span>/ 100</span></div>
      </div>
      <p>${escapeHtml(s.text)}</p>
      <p class="coaching-notes">${escapeHtml(s.coaching_notes)}</p>
      <div class="follow-up-box">
        <div class="follow-up-box-head">
          <span>Follow-up email draft</span>
          <button class="copy-btn" type="button" id="copy-followup">${ICONS.copy} Copy</button>
        </div>
        <pre id="followup-text">${escapeHtml(s.follow_up_email)}</pre>
      </div>`;
  } else if (call.ended_at) {
    summaryBlock.className = 'summary-pending';
    summaryBlock.innerHTML = `${ICONS.clock} No summary was generated automatically (click "Generate summary" above to analyze this call).`;
  } else {
    summaryBlock.className = 'summary-pending';
    summaryBlock.innerHTML = `${ICONS.clock} Summary will be generated once the call ends (or click "Generate summary" above).`;
  }

  const detail = document.createElement('div');
  detail.className = 'history-detail';
  const hintsByTime = call.hints.slice();
  const items = [...call.turns.map(t => ({ ...t, kind: 'turn' })), ...hintsByTime.map(h => ({ ...h, kind: 'hint' }))]
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  if (!items.length) {
    detail.innerHTML = '<p style="color:var(--muted);font-size:0.8125rem;">No turns were recorded for this call.</p>';
  }
  for (const item of items) {
    const row = document.createElement('div');
    row.className = 'detail-turn';
    if (item.kind === 'turn') {
      const sentPill = item.sentiment && item.sentiment !== 'neutral'
        ? `<span class="turn-pill turn-pill-${escapeHtml(item.sentiment)}">${escapeHtml(item.sentiment)}</span>`
        : '';
      const intentPills = (item.intents || [])
        .map(intent => `<span class="turn-pill turn-pill-intent">${escapeHtml(String(intent).replace(/_/g, ' '))}</span>`)
        .join('');
      row.innerHTML = `
        <span class="tag">${escapeHtml(SOURCE_LABELS[item.source] || item.source)}</span>
        <div style="flex:1;">
          <p>${escapeHtml(item.text)}</p>
          ${(sentPill || intentPills) ? `<div class="turn-tags-row">${sentPill}${intentPills}</div>` : ''}
        </div>`;
    } else {
      const sourceTitles = (item.sources || []).map(s => s.title).filter(Boolean).join(', ');
      const metaLine = [
        typeof item.processing_ms === 'number' ? `${item.processing_ms} ms` : '',
        sourceTitles ? `Playbook: ${sourceTitles}` : '',
      ].filter(Boolean).join(' · ');
      row.innerHTML = `<span class="tag">Hint &middot; ${item.method === 'ai' ? 'AI' : 'Rules'}</span>
        <div class="detail-hint" style="flex:1;">
          <p>${escapeHtml(item.text)}</p>
          ${metaLine ? `<small class="detail-hint-meta">${escapeHtml(metaLine)}</small>` : ''}
        </div>`;
    }
    detail.append(row);
  }

  wrap.append(back, heading, summaryBlock, detail);
  $('content').replaceChildren(wrap);

  const copyBtn = document.getElementById('copy-followup');
  copyBtn?.addEventListener('click', async () => {
    const text = document.getElementById('followup-text').textContent;
    try {
      await navigator.clipboard.writeText(text);
      copyBtn.innerHTML = `${ICONS.copy} Copied`;
      setTimeout(() => { copyBtn.innerHTML = `${ICONS.copy} Copy`; }, 1500);
    } catch { /* clipboard permission denied; silently ignore */ }
  });

  const regenBtn = document.getElementById('regenerate-summary-btn');
  regenBtn?.addEventListener('click', async () => {
    setButtonLoading(regenBtn, true, 'Analyzing…');
    try {
      const res = await apiFetch(`/api/calls/${call.id}/summarize`, { method: 'POST' });
      if (!res.ok) throw new Error('Could not generate summary.');
      await loadAnalytics();
      await loadDetail(call.id);
    } catch {
      setButtonLoading(regenBtn, false);
    }
  });
}

async function loadList() {
  if ($('history-toolbar')) $('history-toolbar').hidden = false;
  const q = $('history-search')?.value.trim() || '';
  const disposition = $('filter-disposition')?.value || '';
  const channel = $('filter-channel')?.value || '';
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (disposition) params.set('disposition', disposition);
  if (channel) params.set('channel', channel);
  const hasFilters = !!(q || disposition || channel);
  renderLoading();
  try {
    const qs = params.toString();
    const res = await apiFetch(`/api/calls${qs ? '?' + qs : ''}`);
    if (!res.ok) throw new Error('Could not load call history.');
    const { calls } = await res.json();
    renderList(calls, hasFilters);
  } catch (error) {
    renderError(error.message || 'Something went wrong.');
  }
}

let searchTimer = null;
$('history-search')?.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadList, 200);
});
$('filter-disposition')?.addEventListener('change', loadList);
$('filter-channel')?.addEventListener('change', loadList);

if (session) {
  loadAnalytics();
  loadList();
}
