import React, { useEffect, useRef, useState } from 'react';
import { ScrollView, StyleSheet, Switch, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { pushFloatingHintOverlay } from '../services/nativeCallBridge';
import { colors } from '../theme';

const SCENARIOS = [
  {
    label: 'Pricing (EN)',
    speaker: 'customer',
    text: 'Your solution seems expensive. We already manage customer inquiries using Excel.',
  },
  {
    label: 'Hinglish Budget',
    speaker: 'customer',
    text: 'आपका solution थोड़ा expensive लग रहा है, अभी हमारा budget tight है।',
  },
  {
    label: 'Rep Discovery',
    speaker: 'rep',
    text: 'How does your team currently track missed follow-ups, and what happens when a lead slips?',
  },
  {
    label: 'Buying Signal',
    speaker: 'customer',
    text: 'This sounds good and makes sense for our team — when can we start onboarding?',
  },
];

export default function LiveCallScreen({ client, onCallEnded }) {
  const [consent, setConsent] = useState(false);
  const [connected, setConnected] = useState(false);
  const [floatingOverlayEnabled, setFloatingOverlayEnabled] = useState(true);
  const [backgroundAudioEnabled, setBackgroundAudioEnabled] = useState(true);
  const [phoneNumber, setPhoneNumber] = useState('+917520850690');
  const [testSpeaker, setTestSpeaker] = useState('customer');
  const [testText, setTestText] = useState(SCENARIOS[1].text);
  const [statusMessage, setStatusMessage] = useState('Confirm participant consent to start a live call or field meeting.');
  const [floatingHint, setFloatingHint] = useState(null);
  const [turns, setTurns] = useState([]);
  const [signals, setSignals] = useState({
    sentiment: { positive: 0, neutral: 0, negative: 0 },
    intents: {},
    talk_time: { rep_pct: 0, customer_pct: 0 },
  });
  const wsRef = useRef(null);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
    };
  }, []);

  function startLiveSession() {
    if (!consent) {
      setStatusMessage('Please confirm participant consent before connecting.');
      return;
    }
    try {
      setTurns([]);
      const conn = client.connectLiveSocket({
        consentConfirmed: true,
        onReady: () => {
          setConnected(true);
          setStatusMessage(
            backgroundAudioEnabled
              ? 'Live session active · Background audio & screen wake-lock enabled.'
              : 'Live session active.'
          );
        },
        onTranscriptFinal: (msg) => {
          setTurns((prev) => [
            ...prev.slice(-30),
            {
              id: `${Date.now()}-${Math.random()}`,
              text: msg.text,
              source: msg.source,
              sentiment: msg.sentiment,
              intents: msg.intents || [],
            },
          ]);
        },
        onHint: async (msg) => {
          const overlay = await pushFloatingHintOverlay({
            hint: msg.text,
            method: msg.method,
            processingMs: msg.processing_ms,
            sources: msg.sources,
          });
          setFloatingHint(overlay);
        },
        onSignals: (msg) => {
          setSignals(msg);
        },
        onStatus: (text) => setStatusMessage(text),
        onError: (text) => setStatusMessage(`Error: ${text}`),
        onClose: () => {
          setConnected(false);
          wsRef.current = null;
        },
      });
      wsRef.current = conn;
    } catch (err) {
      setStatusMessage(err.message);
    }
  }

  function stopLiveSession() {
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
    setStatusMessage('Call session ended. Post-call summary generated.');
    onCallEnded?.();
  }

  function sendUtterance(customText = null, customSpeaker = null) {
    const textToSend = (customText ?? testText).trim();
    const speakerToSend = customSpeaker ?? testSpeaker;
    if (!connected || !wsRef.current || !textToSend) return;
    wsRef.current.sendUtterance(textToSend, speakerToSend);
  }

  async function dialTwilioPhone() {
    if (!consent) {
      setStatusMessage('Confirm participant consent before dialing.');
      return;
    }
    try {
      if (!connected) startLiveSession();
      setStatusMessage(`Dialing ${phoneNumber} via Twilio Media Streams…`);
      const res = await client.startTwilioCall({
        to: phoneNumber,
        consentConfirmed: true,
      });
      setStatusMessage(`Twilio call active (${res.call_sid}) — streaming live hints to your phone.`);
    } catch (err) {
      setStatusMessage(err.message);
    }
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {floatingOverlayEnabled && floatingHint && (
        <View style={styles.floatingHud} accessibilityRole="alert">
          <View style={styles.floatingHudHead}>
            <Text style={styles.floatingHudKicker}>FLOATING CALL OVERLAY · {floatingHint.badge}</Text>
            <Text style={styles.floatingHudMeta}>{floatingHint.latencyLabel}</Text>
          </View>
          <Text style={styles.floatingHudText}>{floatingHint.text}</Text>
          <Text style={styles.floatingHudSource}>Grounded in: {floatingHint.sourceTitle}</Text>
        </View>
      )}

      <View style={styles.panel}>
        <Text style={styles.heading}>In-Mobile Live Copilot</Text>
        <Text style={styles.sub}>
          Streams live playbook hints over phone calls and in-person field meetings.
        </Text>

        <View style={styles.switchRow}>
          <Text style={styles.switchLabel}>
            I have informed the other party and confirmed consent (DPDP Act 2023)
          </Text>
          <Switch
            value={consent}
            onValueChange={setConsent}
            trackColor={{ false: colors.panelEdge, true: colors.teal }}
          />
        </View>

        <View style={styles.switchRow}>
          <Text style={styles.switchLabel}>
            Floating Hint Overlay (Android Draw-Over-Apps / iOS Live Activity)
          </Text>
          <Switch
            value={floatingOverlayEnabled}
            onValueChange={setFloatingOverlayEnabled}
            trackColor={{ false: colors.panelEdge, true: colors.blue }}
          />
        </View>

        <View style={styles.switchRow}>
          <Text style={styles.switchLabel}>
            Background Field-Meeting Audio (keep streaming when screen locks)
          </Text>
          <Switch
            value={backgroundAudioEnabled}
            onValueChange={setBackgroundAudioEnabled}
            trackColor={{ false: colors.panelEdge, true: colors.blue }}
          />
        </View>

        <View style={styles.buttonRow}>
          {!connected ? (
            <TouchableOpacity
              style={[styles.primaryBtn, !consent && styles.disabledBtn]}
              disabled={!consent}
              onPress={startLiveSession}
            >
              <Text style={styles.primaryBtnText}>Start Live Copilot</Text>
            </TouchableOpacity>
          ) : (
            <TouchableOpacity style={styles.dangerBtn} onPress={stopLiveSession}>
              <Text style={styles.dangerBtnText}>End Session & Summarize</Text>
            </TouchableOpacity>
          )}
        </View>

        <Text style={styles.statusText}>{statusMessage}</Text>
      </View>

      <View style={styles.panel}>
        <Text style={styles.sectionTitle}>Two-Way Twilio Phone Call</Text>
        <View style={styles.dialRow}>
          <TextInput
            style={styles.input}
            value={phoneNumber}
            onChangeText={setPhoneNumber}
            placeholder="+917520850690"
            placeholderTextColor={colors.muted}
            keyboardType="phone-pad"
          />
          <TouchableOpacity
            style={[styles.secondaryBtn, !consent && styles.disabledBtn]}
            disabled={!consent}
            onPress={dialTwilioPhone}
          >
            <Text style={styles.secondaryBtnText}>Call Phone</Text>
          </TouchableOpacity>
        </View>
      </View>

      <View style={styles.panel}>
        <View style={styles.rowBetween}>
          <Text style={styles.sectionTitle}>Field / Call Utterance Simulator</Text>
          <View style={styles.speakerGroup}>
            {['customer', 'rep'].map((spk) => (
              <TouchableOpacity
                key={spk}
                style={[styles.speakerChip, testSpeaker === spk && styles.speakerChipActive]}
                onPress={() => setTestSpeaker(spk)}
              >
                <Text style={styles.speakerChipText}>{spk.toUpperCase()}</Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        <View style={styles.scenarioWrap}>
          {SCENARIOS.map((sc) => (
            <TouchableOpacity
              key={sc.label}
              style={styles.scenarioPill}
              onPress={() => {
                setTestSpeaker(sc.speaker);
                setTestText(sc.text);
                if (connected) sendUtterance(sc.text, sc.speaker);
              }}
            >
              <Text style={styles.scenarioPillText}>{sc.label}</Text>
            </TouchableOpacity>
          ))}
        </View>

        <TextInput
          style={[styles.input, styles.textArea]}
          value={testText}
          onChangeText={setTestText}
          multiline
        />
        <TouchableOpacity
          style={[styles.secondaryBtn, !connected && styles.disabledBtn, { marginTop: 10 }]}
          disabled={!connected}
          onPress={() => sendUtterance()}
        >
          <Text style={styles.secondaryBtnText}>Send Utterance for Live Hint</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.panel}>
        <Text style={styles.sectionTitle}>Live Conversation Signals</Text>
        <View style={styles.signalsRow}>
          <View style={styles.signalBox}>
            <Text style={styles.signalLabel}>TALK TIME</Text>
            <Text style={styles.signalValue}>
              Rep {signals.talk_time?.rep_pct ?? 0}% · Cust {signals.talk_time?.customer_pct ?? 0}%
            </Text>
          </View>
          <View style={styles.signalBox}>
            <Text style={styles.signalLabel}>SENTIMENT</Text>
            <Text style={styles.signalValue}>
              +{signals.sentiment?.positive ?? 0} / -{signals.sentiment?.negative ?? 0}
            </Text>
          </View>
          <View style={styles.signalBox}>
            <Text style={styles.signalLabel}>OBJECTIONS</Text>
            <Text style={[styles.signalValue, { color: colors.orange }]}>
              {signals.intents?.objection ?? 0}
            </Text>
          </View>
        </View>

        {turns.map((t) => (
          <View key={t.id} style={styles.turnItem}>
            <Text style={styles.turnMeta}>
              {t.source.toUpperCase()} · {t.sentiment}
              {t.intents.length ? ` · ${t.intents.join(', ')}` : ''}
            </Text>
            <Text style={styles.turnText}>{t.text}</Text>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, paddingBottom: 40, gap: 14 },
  floatingHud: {
    backgroundColor: '#123c42',
    borderColor: colors.teal,
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
  },
  floatingHudHead: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 6 },
  floatingHudKicker: { color: colors.teal, fontSize: 11, fontWeight: '800', letterSpacing: 0.6 },
  floatingHudMeta: { color: colors.textDim, fontSize: 11, fontWeight: '700' },
  floatingHudText: { color: colors.text, fontSize: 18, fontWeight: '700', lineHeight: 25 },
  floatingHudSource: { color: colors.secondary, fontSize: 12, marginTop: 8 },
  panel: {
    backgroundColor: colors.panel,
    borderColor: colors.panelEdge,
    borderWidth: 1,
    borderRadius: 16,
    padding: 16,
  },
  heading: { color: colors.text, fontSize: 20, fontWeight: '800', marginBottom: 4 },
  sub: { color: colors.secondary, fontSize: 13, marginBottom: 14 },
  sectionTitle: { color: colors.text, fontSize: 15, fontWeight: '700', marginBottom: 10 },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 8,
    borderTopColor: colors.line,
    borderTopWidth: 1,
    gap: 12,
  },
  switchLabel: { color: colors.textDim, fontSize: 13, flex: 1 },
  buttonRow: { marginTop: 12 },
  primaryBtn: {
    backgroundColor: colors.teal,
    borderRadius: 10,
    paddingVertical: 12,
    paddingHorizontal: 16,
    alignItems: 'center',
  },
  primaryBtnText: { color: colors.tealDark, fontWeight: '800', fontSize: 14 },
  secondaryBtn: {
    backgroundColor: '#244258',
    borderColor: '#3a6180',
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 11,
    paddingHorizontal: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  secondaryBtnText: { color: colors.text, fontWeight: '700', fontSize: 13 },
  dangerBtn: {
    borderColor: colors.danger,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
  },
  dangerBtnText: { color: colors.danger, fontWeight: '800', fontSize: 14 },
  disabledBtn: { opacity: 0.45 },
  statusText: { color: colors.secondary, fontSize: 12, marginTop: 10 },
  dialRow: { flexDirection: 'row', gap: 8 },
  input: {
    flex: 1,
    backgroundColor: colors.panel2,
    borderColor: colors.panelEdge,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.text,
    fontSize: 14,
  },
  textArea: { minHeight: 68, textAlignVertical: 'top' },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  speakerGroup: { flexDirection: 'row', gap: 6 },
  speakerChip: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 8,
    backgroundColor: colors.panel2,
  },
  speakerChipActive: { backgroundColor: '#244258' },
  speakerChipText: { color: colors.textDim, fontSize: 11, fontWeight: '800' },
  scenarioWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 10 },
  scenarioPill: {
    borderColor: colors.panelEdge,
    borderWidth: 1,
    backgroundColor: colors.panel2,
    borderRadius: 14,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  scenarioPillText: { color: colors.secondary, fontSize: 11, fontWeight: '700' },
  signalsRow: { flexDirection: 'row', gap: 10, marginBottom: 10 },
  signalBox: {
    flex: 1,
    backgroundColor: colors.panel2,
    borderRadius: 10,
    padding: 10,
  },
  signalLabel: { color: colors.muted, fontSize: 10, fontWeight: '800', marginBottom: 4 },
  signalValue: { color: colors.text, fontSize: 14, fontWeight: '800' },
  turnItem: {
    borderTopColor: colors.line,
    borderTopWidth: 1,
    paddingVertical: 8,
  },
  turnMeta: { color: colors.secondary, fontSize: 10, fontWeight: '800', marginBottom: 2 },
  turnText: { color: colors.text, fontSize: 13, lineHeight: 19 },
});
