/**
 * API & WebSocket client for the Sales Copilot React Native companion app.
 * Connects to the same FastAPI backend (/api/auth/*, /ws/live, /api/twilio/call, /api/calls/*).
 */

const DEFAULT_BASE_URL = 'http://127.0.0.1:8000';

export function normalizeBaseUrl(url) {
  const trimmed = String(url || DEFAULT_BASE_URL).trim().replace(/\/+$/, '');
  return trimmed || DEFAULT_BASE_URL;
}

export function toWebSocketUrl(baseUrl, path = '/ws/live') {
  const clean = normalizeBaseUrl(baseUrl);
  const wsBase = clean.replace(/^http:/i, 'ws:').replace(/^https:/i, 'wss:');
  return `${wsBase}${path}`;
}

export class SalesCopilotMobileClient {
  constructor({ baseUrl = DEFAULT_BASE_URL, token = null } = {}) {
    this.baseUrl = normalizeBaseUrl(baseUrl);
    this.token = token;
  }

  setBaseUrl(url) {
    this.baseUrl = normalizeBaseUrl(url);
  }

  setToken(token) {
    this.token = token;
  }

  async request(path, options = {}) {
    const headers = {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    };
    if (this.token) {
      headers.Authorization = `Bearer ${this.token}`;
    }
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const msg = typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`;
      throw new Error(msg);
    }
    return data;
  }

  async checkHealth() {
    return this.request('/api/health', { method: 'GET' });
  }

  async login(email, password) {
    const session = await this.request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email: email.trim(), password }),
    });
    this.token = session.token;
    return session;
  }

  async signup({ organizationName, name, email, password }) {
    const session = await this.request('/api/auth/signup', {
      method: 'POST',
      body: JSON.stringify({
        organization_name: organizationName.trim(),
        name: name.trim(),
        email: email.trim(),
        password,
      }),
    });
    this.token = session.token;
    return session;
  }

  async getMe() {
    return this.request('/api/auth/me', { method: 'GET' });
  }

  async updateWhatsAppPrefs({ whatsappNumber, whatsappRecapEnabled }) {
    return this.request('/api/auth/me/whatsapp', {
      method: 'PATCH',
      body: JSON.stringify({
        whatsapp_number: whatsappNumber ? whatsappNumber.trim() : null,
        whatsapp_recap_enabled: !!whatsappRecapEnabled,
      }),
    });
  }

  async getTeam() {
    return this.request('/api/auth/team', { method: 'GET' });
  }

  async inviteTeammate({ name, email, password, role = 'rep' }) {
    return this.request('/api/auth/invite', {
      method: 'POST',
      body: JSON.stringify({ name, email, password, role }),
    });
  }

  async startTwilioCall({ to, dial = null, consentConfirmed = true }) {
    return this.request('/api/twilio/call', {
      method: 'POST',
      body: JSON.stringify({
        to,
        dial,
        consent_confirmed: !!consentConfirmed,
      }),
    });
  }

  async logMobileCall({ toNumber = null, consentConfirmed = false, turns = [] }) {
    return this.request('/api/calls/log-mobile', {
      method: 'POST',
      body: JSON.stringify({
        to_number: toNumber,
        consent_confirmed: !!consentConfirmed,
        turns,
      }),
    });
  }

  async listCalls({ disposition = '', channel = '', q = '' } = {}) {
    const params = new URLSearchParams();
    if (disposition) params.set('disposition', disposition);
    if (channel) params.set('channel', channel);
    if (q) params.set('q', q);
    const qs = params.toString();
    return this.request(`/api/calls${qs ? `?${qs}` : ''}`, { method: 'GET' });
  }

  async getCallDetail(callId) {
    return this.request(`/api/calls/${encodeURIComponent(callId)}`, { method: 'GET' });
  }

  async getAnalytics() {
    return this.request('/api/calls/analytics', { method: 'GET' });
  }

  async regenerateSummary(callId) {
    return this.request(`/api/calls/${encodeURIComponent(callId)}/summarize`, { method: 'POST' });
  }

  /**
   * Opens an authenticated /ws/live WebSocket session using subprotocol ['copilot-v1', 'auth.<token>'].
   */
  connectLiveSocket({ consentConfirmed = true, onReady, onTranscriptInterim, onTranscriptFinal, onHint, onSignals, onStatus, onError, onClose } = {}) {
    if (!this.token) {
      throw new Error('Log in before starting a live session.');
    }
    const wsUrl = toWebSocketUrl(this.baseUrl, '/ws/live');
    const ws = new WebSocket(wsUrl, ['copilot-v1', `auth.${this.token}`]);

    ws.onopen = () => {
      if (consentConfirmed) {
        ws.send(JSON.stringify({ type: 'confirm_consent' }));
      }
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      switch (msg.type) {
        case 'ready':
          onReady?.(msg);
          break;
        case 'transcript_interim':
          onTranscriptInterim?.(msg.text);
          break;
        case 'transcript_final':
          onTranscriptFinal?.(msg);
          break;
        case 'hint':
          onHint?.(msg);
          break;
        case 'signals':
          onSignals?.(msg);
          break;
        case 'status':
          onStatus?.(msg.message);
          break;
        case 'error':
          onError?.(msg.message);
          break;
        default:
          break;
      }
    };

    ws.onerror = () => {
      onError?.('WebSocket connection error. Verify server URL and ALLOWED_ORIGINS.');
    };

    ws.onclose = (event) => {
      onClose?.(event.code);
    };

    return {
      sendUtterance(text, speaker = 'customer') {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'simulate_utterance', text, speaker }));
        }
      },
      sendAudioFrame(pcm16Buffer) {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(pcm16Buffer);
        }
      },
      endAudio() {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'end_audio' }));
        }
      },
      close() {
        try {
          ws.close(1000, 'Mobile session ended');
        } catch {
          // ignore
        }
      },
    };
  }
}
