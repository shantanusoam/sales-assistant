import { requireSession, clearSession, apiFetch } from '/assets/api.js';

const $ = (id) => document.getElementById(id);
const session = requireSession();
const state = {
  ws: null, microphoneEnabled: false, llmEnabled: false,
  stream: null, context: null, source: null, processor: null, sink: null,
  playbackCtx: null, nextPlayTime: 0,
  dropped: 0, hintCount: 0, startedAt: 0,
};
if (session) {
  $('org-label').textContent = `${session.organization.name} · ${session.user.name}`;
}

function notice(message, type = '') {
  const el = $('notice');
  el.textContent = message;
  el.className = 'notice' + (type ? ' ' + type : '');
}
function connected() { return state.ws && state.ws.readyState === WebSocket.OPEN; }
function setConnection(ok) {
  $('connection-pill').classList.toggle('connected', ok);
  $('connection-label').textContent = ok ? 'Connected' : 'Offline';
  $('disconnect-btn').disabled = !ok;
  $('connect-btn').disabled = ok;
  $('send-test').disabled = !ok;
  $('start-mic').disabled = !ok || !state.microphoneEnabled || !!state.stream;
  $('stop-mic').disabled = !state.stream;
}
function displayHealth(data) {
  state.microphoneEnabled = !!data.microphone_transcription_configured;
  state.llmEnabled = !!data.llm_configured;
  if (data.twilio_default_to && $('call-number') && !$('call-number').value) {
    $('call-number').value = data.twilio_default_to;
  }
  $('mode-indicator').textContent = (state.microphoneEnabled ? 'MIC READY' : 'TEXT TEST MODE') + ' / ' + (state.llmEnabled ? 'AI' : 'RULES DEMO');
  $('rag-mode').textContent = (data.retrieval_mode || 'lexical-demo').replace(/-/g, ' ').toUpperCase();
  if (!state.microphoneEnabled) notice('Text-test mode is ready. Add DEEPGRAM_API_KEY in .env for microphone transcription.');
  else notice('Microphone mode is available. Get consent from participants before processing any conversation.');
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
  const token = ensureToken();
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const address = `${protocol}//${location.host}/ws/live`;
  await new Promise((resolve, reject) => {
    const ws = new WebSocket(address, ['copilot-v1', `auth.${token}`]);
    let ready = false;
    ws.onopen = () => { ready = true; state.ws = ws; state.startedAt = Date.now(); setConnection(true); notice('Connected. You can test a conversation or enable the microphone.', 'success'); resolve(); };
    ws.onmessage = (event) => handleMessage(event.data);
    ws.onerror = () => { if (!ready) reject(new Error('WebSocket authentication or network connection failed.')); };
    ws.onclose = (event) => {
      if (!ready) reject(new Error('WebSocket rejected. Check the access code and ALLOWED_ORIGINS.'));
      if (state.ws === ws) { state.ws = null; stopMicrophone(false); setConnection(false); }
      if (ready) notice(`Connection closed${event.code ? ' (' + event.code + ')' : ''}.`, 'error');
    };
  });
}
function addTranscript(text, source) {
  $('transcript-empty')?.remove();
  const item = document.createElement('div'); item.className = 'transcript-item';
  const meta = document.createElement('div'); meta.className = 'transcript-meta';
  const dot = document.createElement('span'); meta.append(dot);
  const sourceLabels = {
    'manual-test': 'TEST INPUT',
    'twilio-customer': 'TWILIO CALLER',
    'twilio-rep': 'TWILIO REP',
  };
  const label = document.createTextNode(sourceLabels[source] || 'MICROPHONE');
  meta.append(label);
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
      addTranscript(message.text, message.source);
      break;
    case 'hint':
      $('hint-text').textContent = message.text;
      $('ai-badge').textContent = message.method === 'ai' ? 'AI GENERATED' : 'DEMO RULE';
      $('latency').textContent = `${message.processing_ms} ms backend processing`;
      state.hintCount++; $('hint-counter').textContent = `${state.hintCount} hint${state.hintCount === 1 ? '' : 's'}`;
      $('rag-mode').textContent = String(message.retrieval_mode || 'demo').replace(/-/g, ' ').toUpperCase();
      updateSources(message.sources);
      $('insight-area').animate([{opacity:.8, transform:'translateY(3px)'},{opacity:1,transform:'translateY(0)'}],{duration:220,easing:'ease-out'});
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
  if (!state.microphoneEnabled) throw new Error('Deepgram is not configured on the server.');
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
function sendTest() {
  if (!connected()) throw new Error('Connect before submitting a test utterance.');
  const text = $('test-text').value.trim();
  if (!text) throw new Error('Enter a test utterance first.');
  state.ws.send(JSON.stringify({type:'simulate_utterance',text}));
  notice('Test utterance submitted. Awaiting a grounded hint.', 'success');
}
function disconnect() {
  stopMicrophone(false);
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
  const btn = $('make-call-btn');
  if (btn) btn.disabled = true;
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
      body: JSON.stringify({to}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(typeof data.detail === 'string' ? data.detail : 'Failed to initiate Twilio call.');
    }
    notice(`Call initiated to ${data.to} (SID: ${data.call_sid}). Answer your phone and press 1!`, 'success');
  } finally {
    if (btn) btn.disabled = false;
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
setInterval(() => {
  if (!connected()) return;
  const elapsed = Math.floor((Date.now() - state.startedAt) / 1000);
  const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const s = String(elapsed % 60).padStart(2, '0');
  $('session-timer').textContent = m + ':' + s;
},1000);
window.addEventListener('pagehide',() => {
  state.stream?.getTracks().forEach(track => track.stop());
  state.ws?.close();
});
health();
