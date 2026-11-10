import { requireSession, clearSession, apiFetch, setButtonLoading, setNotice } from '/assets/api.js';

const $ = (id) => document.getElementById(id);
const session = requireSession();
const state = {
  ws: null, microphoneEnabled: false, llmEnabled: false, sttProvider: 'deepgram',
  testSpeaker: 'customer', wakeLock: null,
  stream: null, context: null, source: null, processor: null, sink: null,
  playbackCtx: null, nextPlayTime: 0,
  dropped: 0, hintCount: 0, startedAt: 0, lastHint: null,
};

async function acquireWakeLock() {
  if (!('wakeLock' in navigator) || state.wakeLock) return;
  try {
    state.wakeLock = await navigator.wakeLock.request('screen');
    if ($('session-timer-label')) $('session-timer-label').textContent = 'Session time · Screen awake';
    state.wakeLock.addEventListener('release', () => {
      state.wakeLock = null;
      if ($('session-timer-label')) $('session-timer-label').textContent = 'Session time';
    });
  } catch { /* Wake Lock not permitted or unsupported on this device */ }
}

async function releaseWakeLock() {
  if (!state.wakeLock) return;
  try { await state.wakeLock.release(); } catch { /* ignore */ }
  state.wakeLock = null;
  if ($('session-timer-label')) $('session-timer-label').textContent = 'Session time';
}
if (session) {
  const chip = $('org-chip');
  chip.innerHTML = '';
  const org = document.createElement('strong'); org.textContent = session.organization.name;
  const user = document.createElement('span'); user.textContent = session.user.name;
  chip.append(org, user);
}

function notice(message, type = '') {
  setNotice($('notice'), message, type);
}
function connected() { return state.ws && state.ws.readyState === WebSocket.OPEN; }
function hasConsent() { return !!$('consent-checkbox')?.checked; }
function setConnection(ok) {
  $('connection-pill').classList.toggle('connected', ok);
  $('connection-pill').classList.remove('connecting');
  $('connection-label').textContent = ok ? 'Connected' : 'Offline';
  $('disconnect-btn').disabled = !ok;
  $('connect-btn').disabled = ok || !hasConsent();
  $('make-call-btn').disabled = !hasConsent();
  $('send-test').disabled = !ok;
  $('start-mic').disabled = !ok || !state.microphoneEnabled || !!state.stream;
  $('stop-mic').disabled = !state.stream;
}
function sttLabel(provider) {
  return provider === 'sarvam' ? 'Sarvam AI (Hindi/Hinglish)' : 'Deepgram';
}
function displayHealth(data) {
  state.microphoneEnabled = !!data.microphone_transcription_configured;
  state.llmEnabled = !!data.llm_configured;
  state.sttProvider = data.stt_provider || 'deepgram';
  const providerName = sttLabel(state.sttProvider);
  if (data.twilio_default_to && $('call-number') && !$('call-number').value) {
    $('call-number').value = data.twilio_default_to;
  }
  $('mode-indicator').textContent = (state.microphoneEnabled ? `MIC READY (${state.sttProvider.toUpperCase()})` : 'TEXT TEST MODE') + ' / ' + (state.llmEnabled ? 'AI' : 'RULES DEMO');
  $('rag-mode').textContent = (data.retrieval_mode || 'lexical-demo').replace(/-/g, ' ').toUpperCase();
  if ($('mic-helper')) $('mic-helper').textContent = `Requires ${providerName} and microphone permission.`;
  if ($('call-helper')) $('call-helper').textContent = `Streams two-way phone audio into ${providerName} & Copilot hints.`;
  const keyName = state.sttProvider === 'sarvam' ? 'SARVAM_API_KEY' : 'DEEPGRAM_API_KEY';
  if (!state.microphoneEnabled) notice(`Text-test mode is ready. Add ${keyName} in .env for microphone transcription.`);
  else notice(`Microphone mode (${providerName}) is available. Get consent from participants before processing any conversation.`);
  setConnection(connected());
}
async function health() {
  try {
    const res = await fetch('/api/health', {cache: 'no-store'});
    if (!res.ok) throw new Error('Cannot read backend health');
    displayHealth(await res.json());
  } catch (error) { notice('Cannot reach the backend. Start FastAPI first.', 'error'); }
}
function ensureToken() {
  const current = requireSession();
  if (!current) throw new Error('Your session expired. Log in again.');
  return current.token;
}
async function connect() {
  if (connected()) return;
  if (!hasConsent()) throw new Error("Please confirm you've informed the other party and have their consent first.");
  const token = ensureToken();
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const address = `${protocol}//${location.host}/ws/live`;
  $('connection-pill').classList.add('connecting');
  setButtonLoading($('connect-btn'), true, 'Connecting…');
  try {
    await new Promise((resolve, reject) => {
      const ws = new WebSocket(address, ['copilot-v1', `auth.${token}`]);
      let ready = false;
      ws.onopen = () => {
        ready = true; state.ws = ws; state.startedAt = Date.now(); resetSessionUI(); setConnection(true);
        acquireWakeLock();
        ws.send(JSON.stringify({type: 'confirm_consent'}));
        notice('Connected. You can test a conversation or enable the microphone.', 'success'); resolve();
      };
      ws.onmessage = (event) => handleMessage(event.data);
      ws.onerror = () => { if (!ready) reject(new Error('WebSocket authentication or network connection failed.')); };
      ws.onclose = (event) => {
        if (!ready) reject(new Error('WebSocket rejected. Check the access code and ALLOWED_ORIGINS.'));
        if (state.ws === ws) { state.ws = null; stopMicrophone(false); releaseWakeLock(); setConnection(false); }
        if (ready) notice(`Connection closed${event.code ? ' (' + event.code + ')' : ''}.`, 'error');
      };
    });
  } finally {
    setButtonLoading($('connect-btn'), false);
    $('connection-pill').classList.remove('connecting');
  }
}
function addTranscript(text, source, sentiment = 'neutral', intents = []) {
  $('transcript-empty')?.remove();
  const item = document.createElement('div'); item.className = 'transcript-item';
  const meta = document.createElement('div'); meta.className = 'transcript-meta'; meta.dataset.source = source;
  const dot = document.createElement('span'); dot.className = 'dot'; meta.append(dot);
  const sourceLabels = {
    'manual-test': 'REP (TEST)',
    'customer-test': 'CUSTOMER (TEST)',
    'twilio-customer': 'TWILIO CALLER',
    'twilio-rep': 'TWILIO REP',
  };
  const label = document.createTextNode(sourceLabels[source] || 'MICROPHONE');
  meta.append(label);
  if (sentiment && sentiment !== 'neutral') {
    const sentBadge = document.createElement('span');
    sentBadge.className = `turn-pill turn-pill-${sentiment}`;
    sentBadge.textContent = sentiment;
    meta.append(sentBadge);
  }
  if (Array.isArray(intents)) {
    for (const intent of intents) {
      const intentBadge = document.createElement('span');
      intentBadge.className = `turn-pill turn-pill-intent`;
      intentBadge.textContent = String(intent).replace(/_/g, ' ');
      meta.append(intentBadge);
    }
  }
  const textEl = document.createElement('p'); textEl.textContent = text;
  item.append(meta, textEl); $('transcript-feed').append(item);
  $('transcript-feed').scrollTop = $('transcript-feed').scrollHeight;
  while ($('transcript-feed').children.length > 35) $('transcript-feed').firstChild.remove();
}
function updateSources(sources) {
  const container = $('source-list'); container.replaceChildren();
  if (!sources?.length) {
    const empty = document.createElement('div'); empty.className = 'source-placeholder';
    empty.textContent = 'No directly matching playbook excerpt was found.'; container.append(empty); return;
  }
  for (const source of sources) {
    const article = document.createElement('article'); article.className = 'source-item';
    const title = document.createElement('strong'); title.textContent = source.title || 'Playbook';
    const desc = document.createElement('p'); desc.textContent = source.excerpt || '';
    article.append(title, desc); container.append(article);
  }
}
function pushHintHistory(hint) {
  const list = $('hint-history');
  const item = document.createElement('div');
  item.className = 'hint-history-item';
  const badge = document.createElement('b');
  badge.textContent = hint.method === 'ai' ? 'AI' : 'RULE';
  item.append(badge, document.createTextNode(' ' + hint.text));
  list.prepend(item);
  while (list.children.length > 5) list.lastChild.remove();
  $('hint-history-head').hidden = false;
}
function resetSessionUI() {
  state.hintCount = 0; state.lastHint = null;
  $('hint-history').replaceChildren();
  $('hint-history-head').hidden = true;
  updateSignals({ sentiment: { positive: 0, neutral: 0, negative: 0 }, intents: {}, talk_time: { rep_pct: 0, customer_pct: 0 } });
}
function updateSignals(message) {
  const { sentiment, intents, talk_time: talkTime } = message;
  $('talk-bar-rep').style.width = `${talkTime.rep_pct}%`;
  $('talk-rep-pct').textContent = `${talkTime.rep_pct}%`;
  $('talk-customer-pct').textContent = `${talkTime.customer_pct}%`;
  $('sent-positive').textContent = sentiment.positive;
  $('sent-neutral').textContent = sentiment.neutral;
  $('sent-negative').textContent = sentiment.negative;
  const objections = intents.objection || 0;
  const objectionEl = $('objection-count');
  objectionEl.textContent = objections;
  objectionEl.classList.toggle('has-objections', objections > 0);
}
function playPhoneAudio(pcm16B64, rms) {
  if (typeof rms === 'number') updateLevels(rms);
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return;
  if (!state.playbackCtx) {
    state.playbackCtx = new AudioContextClass({sampleRate: 16000});
  }
  if (state.playbackCtx.state === 'suspended') {
    state.playbackCtx.resume().catch(() => {});
  }
  const binary = atob(pcm16B64);
  const sampleCount = binary.length >> 1;
  if (!sampleCount) return;
  const audioBuf = state.playbackCtx.createBuffer(1, sampleCount, 16000);
  const channel = audioBuf.getChannelData(0);
  for (let i = 0; i < sampleCount; i++) {
    let val = binary.charCodeAt(i * 2) | (binary.charCodeAt(i * 2 + 1) << 8);
    if (val >= 0x8000) val -= 0x10000;
    channel[i] = val / 32768;
  }
  const src = state.playbackCtx.createBufferSource();
  src.buffer = audioBuf;
  src.connect(state.playbackCtx.destination);
  const now = state.playbackCtx.currentTime;
  if (state.nextPlayTime < now || state.nextPlayTime > now + 0.4) {
    state.nextPlayTime = now + 0.04;
  }
  src.start(state.nextPlayTime);
  state.nextPlayTime += audioBuf.duration;
}
function handleMessage(raw) {
  let message; try { message = JSON.parse(raw); } catch { return; }
  switch (message.type) {
    case 'ready':
      state.microphoneEnabled = !!message.microphone_enabled;
      if (message.stt_provider) state.sttProvider = message.stt_provider;
      setConnection(true);
      break;
    case 'phone_audio':
      playPhoneAudio(message.pcm16_b64, message.rms);
      break;
    case 'status': notice(message.message, 'success'); break;
    case 'error': notice(message.message, 'error'); break;
    case 'transcript_interim': $('interim').textContent = '… ' + message.text; break;
    case 'transcript_final':
      $('interim').textContent = '';
      addTranscript(message.text, message.source, message.sentiment, message.intents);
      break;
    case 'hint':
      if (state.lastHint) pushHintHistory(state.lastHint);
      state.lastHint = { text: message.text, method: message.method };
      $('hint-text').textContent = message.text;
      $('ai-badge').textContent = message.method === 'ai' ? 'AI GENERATED' : 'DEMO RULE';
      $('latency').textContent = `${message.processing_ms} ms backend processing`;
      state.hintCount++; $('hint-counter').textContent = `${state.hintCount} hint${state.hintCount === 1 ? '' : 's'}`;
      $('rag-mode').textContent = String(message.retrieval_mode || 'demo').replace(/-/g, ' ').toUpperCase();
      updateSources(message.sources);
      $('insight-area').classList.remove('flash');
      requestAnimationFrame(() => {
        $('insight-area').classList.add('flash');
        setTimeout(() => $('insight-area').classList.remove('flash'), 600);
      });
      break;
    case 'signals':
      updateSignals(message);
      break;
  }
}
function updateLevels(rms) {
  const level = Math.max(0, Math.min(1, rms * 10));
  const bars = document.querySelectorAll('.levels i');
  bars.forEach((bar, i) => {
    const intensity = Math.max(.1, (Math.sin(i * 1.7) * .4 + .6) * level);
    bar.style.height = `${6 + intensity * 22}px`;
    bar.classList.toggle('active', intensity > .18);
  });
}
async function startMicrophone() {
  if (!state.microphoneEnabled) throw new Error(`${sttLabel(state.sttProvider)} is not configured on the server.`);
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw new Error('Mic needs localhost or HTTPS and a compatible browser.');
  if (!connected()) await connect();
  if (state.stream) return;
  let stream = null; let context = null;
  try {
    stream = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    context = new AudioContextClass({latencyHint:'interactive'});
    if (context.sampleRate < 16000) throw new Error("Audio sample rate below 16 kHz is not supported.");
    await context.audioWorklet.addModule('/assets/pcm-worklet.js');
    const source = context.createMediaStreamSource(stream);
    const processor = new AudioWorkletNode(context,'pcm16-capture',{
      numberOfInputs:1,numberOfOutputs:1,outputChannelCount:[1],
    });
    const sink = context.createGain(); sink.gain.value = 0;
    processor.port.onmessage = ({data}) => {
      if (data.type === 'meter') return updateLevels(data.rms);
      if (data.type !== 'audio' || !connected()) return;
      if (state.ws.bufferedAmount > 256000) { state.dropped++; if (state.dropped % 10 === 1) notice('Slow connection: audio chunks are being dropped. Check your network.', 'error'); return; }
      state.ws.send(data.buffer);
    };
    source.connect(processor); processor.connect(sink); sink.connect(context.destination);
    await context.resume();
    Object.assign(state,{stream,context,source,processor,sink});
    $('audio-state').textContent = 'Microphone active — listening';
    $('transcript-mode').textContent = 'LIVE MIC';
    setConnection(true);
    notice('Microphone is streaming to the backend. Speak a sentence and pause.', 'success');
  } catch (error) {
    stream?.getTracks().forEach(t=>t.stop());
    if (context) await context.close().catch(()=>{});
    throw error;
  }
}
async function stopMicrophone(sendFinalize = true) {
  if (!state.stream) return;
  state.stream.getTracks().forEach(track => track.stop());
  state.source?.disconnect(); state.processor?.disconnect(); state.sink?.disconnect();
  state.processor?.port.close();
  await state.context?.close().catch(() => {});
  Object.assign(state,{stream:null,context:null,source:null,processor:null,sink:null});
  $('audio-state').textContent = 'Microphone stopped';
  $('transcript-mode').textContent = 'MIC / TEST INPUT';
  updateLevels(0);
  if (sendFinalize && connected()) state.ws.send(JSON.stringify({type:'end_audio'}));
  setConnection(connected());
}
function setTestSpeaker(speaker) {
  state.testSpeaker = speaker === 'rep' ? 'rep' : 'customer';
  document.querySelectorAll('.speaker-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.speaker === state.testSpeaker);
  });
}
function sendTest() {
  if (!connected()) throw new Error('Connect before submitting a test utterance.');
  const text = $('test-text').value.trim();
  if (!text) throw new Error('Enter a test utterance first.');
  state.ws.send(JSON.stringify({type:'simulate_utterance', text, speaker: state.testSpeaker}));
  notice(`Test utterance (${state.testSpeaker}) submitted. Awaiting a grounded hint.`, 'success');
}
function disconnect() {
  stopMicrophone(false);
  releaseWakeLock();
  state.ws?.close(1000, 'Session ended');
  state.ws = null;
  setConnection(false);
}
function logout() {
  disconnect();
  clearSession();
  window.location.href = '/login';
}
async function makeCall() {
  const input = $('call-number');
  const to = input ? input.value.trim() : '';
  if (!to) throw new Error('Enter a phone number to call (e.g. +917520850690).');
  if (!hasConsent()) throw new Error("Please confirm you've informed the other party and have their consent first.");
  const btn = $('make-call-btn');
  setButtonLoading(btn, true, 'Dialing…');
  try {
    if (!connected()) {
      await connect();
    }
    if (connected() && state.microphoneEnabled && !state.stream) {
      await startMicrophone().catch(() => {});
    }
    notice(`Dialing ${to} via Twilio...`, 'success');
    const res = await apiFetch('/api/twilio/call', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({to, consent_confirmed: true}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(typeof data.detail === 'string' ? data.detail : 'Failed to initiate Twilio call.');
    }
    notice(`Call initiated to ${data.to} (SID: ${data.call_sid}). Answer your phone and press 1!`, 'success');
  } finally {
    setButtonLoading(btn, false);
  }
}
function bind(id, action) {
  const el = $(id);
  if (!el) return;
  el.addEventListener('click', async () => {
    try { await action(); } catch(error) { notice(error?.message || 'Unexpected error', 'error'); }
  });
}
bind('connect-btn', connect);
bind('disconnect-btn', disconnect);
bind('start-mic', startMicrophone);
bind('stop-mic', stopMicrophone);
bind('send-test', sendTest);
bind('make-call-btn', makeCall);
bind('logout-btn', logout);
document.querySelectorAll('.speaker-btn').forEach((btn) => {
  btn.addEventListener('click', () => setTestSpeaker(btn.dataset.speaker));
});
document.querySelectorAll('.scenario-chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    if (chip.dataset.speaker) setTestSpeaker(chip.dataset.speaker);
    if (chip.dataset.text && $('test-text')) $('test-text').value = chip.dataset.text;
    if (connected()) {
      try { sendTest(); } catch (err) { notice(err?.message || 'Error', 'error'); }
    }
  });
});
$('consent-checkbox')?.addEventListener('change', () => setConnection(connected()));
setInterval(() => {
  if (!connected()) return;
  const elapsed = Math.floor((Date.now() - state.startedAt) / 1000);
  const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const s = String(elapsed % 60).padStart(2, '0');
  $('session-timer').textContent = m + ':' + s;
},1000);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && connected()) {
    acquireWakeLock();
  }
});
window.addEventListener('pagehide',() => {
  releaseWakeLock();
  state.stream?.getTracks().forEach(track => track.stop());
  state.ws?.close();
});
health();
