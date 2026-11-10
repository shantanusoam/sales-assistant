import React, { useState } from 'react';
import { ScrollView, StyleSheet, Switch, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { openWhatsAppRecap } from '../services/nativeCallBridge';
import { colors, DISPOSITION_META } from '../theme';

/**
 * Truecaller-Style Post-Call Card & Field-Meeting Logger:
 * Pops up automatically when an Android call ends (via subscribeToCallEnded)
 * or when a rep taps "Post-Call Log" after an in-person client visit.
 */
export default function PostCallLoggerScreen({ client, initialPhoneNumber = '' }) {
  const [toNumber, setToNumber] = useState(initialPhoneNumber || '+919876543210');
  const [consent, setConsent] = useState(true);
  const [customerNotes, setCustomerNotes] = useState(
    'आपका solution अच्छा है पर थोड़ा expensive लग रहा है। अगर HubSpot sync हो जाए तो अगले हफ्ते शुरू कर सकते हैं।'
  );
  const [repNotes, setRepNotes] = useState(
    'How many inquiries does your team handle weekly, and which HubSpot fields need two-way sync on day one?'
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  async function submitPostCallLog() {
    setLoading(true);
    setError('');
    try {
      const turns = [];
      if (customerNotes.trim()) {
        turns.push({ speaker: 'customer', text: customerNotes.trim() });
      }
      if (repNotes.trim()) {
        turns.push({ speaker: 'rep', text: repNotes.trim() });
      }
      const data = await client.logMobileCall({
        toNumber,
        consentConfirmed: consent,
        turns,
      });
      setResult(data);
    } catch (err) {
      setError(err.message || 'Could not log mobile call.');
    } finally {
      setLoading(false);
    }
  }

  const dispMeta = result?.summary?.disposition
    ? DISPOSITION_META[result.summary.disposition] || DISPOSITION_META.no_decision
    : null;

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <View style={styles.panel}>
        <Text style={styles.heading}>Post-Call & Field Meeting Logger</Text>
        <Text style={styles.sub}>
          Truecaller-style post-call card: capture what happened on a SIM call or field visit,
          classify disposition, score the call, and push to WhatsApp, HubSpot CRM, and Webhooks.
        </Text>

        <Text style={styles.label}>Prospect Phone Number</Text>
        <TextInput
          style={styles.input}
          value={toNumber}
          onChangeText={setToNumber}
          placeholder="+919876543210"
          placeholderTextColor={colors.muted}
          keyboardType="phone-pad"
        />

        <Text style={styles.label}>What the Customer Said (English / Hindi / Hinglish)</Text>
        <TextInput
          style={[styles.input, styles.textArea]}
          value={customerNotes}
          onChangeText={setCustomerNotes}
          multiline
        />

        <Text style={styles.label}>How You Responded / Discovery Asked</Text>
        <TextInput
          style={[styles.input, styles.textArea]}
          value={repNotes}
          onChangeText={setRepNotes}
          multiline
        />

        <View style={styles.switchRow}>
          <Text style={styles.switchLabel}>
            Participant consented to coaching & CRM/WhatsApp distribution
          </Text>
          <Switch
            value={consent}
            onValueChange={setConsent}
            trackColor={{ false: colors.panelEdge, true: colors.teal }}
          />
        </View>

        <TouchableOpacity
          style={[styles.primaryBtn, loading && styles.disabledBtn]}
          disabled={loading}
          onPress={submitPostCallLog}
        >
          <Text style={styles.primaryBtnText}>
            {loading ? 'Analyzing & Distributing…' : 'Analyze Call & Distribute Notes'}
          </Text>
        </TouchableOpacity>

        {!!error && <Text style={styles.errorText}>{error}</Text>}
      </View>

      {result && result.summary && (
        <View style={styles.panel}>
          <View style={styles.resultHead}>
            <View>
              <Text style={styles.sectionTitle}>AI Post-Call Intelligence</Text>
              {dispMeta && (
                <View style={[styles.dispPill, { backgroundColor: dispMeta.bg }]}>
                  <Text style={[styles.dispPillText, { color: dispMeta.color }]}>
                    {dispMeta.label}
                  </Text>
                </View>
              )}
            </View>
            <View style={styles.scoreBox}>
              <Text style={styles.scoreVal}>{result.summary.coaching_score}</Text>
              <Text style={styles.scoreMax}>/ 100</Text>
            </View>
          </View>

          <Text style={styles.bodyText}>{result.summary.text}</Text>
          <Text style={styles.coachingNotes}>{result.summary.coaching_notes}</Text>

          {result.hint?.text && (
            <View style={styles.hintCard}>
              <Text style={styles.hintLabel}>RECOMMENDED NEXT PLAYBOOK MOVE</Text>
              <Text style={styles.hintText}>{result.hint.text}</Text>
            </View>
          )}

          <View style={styles.followUpCard}>
            <Text style={styles.hintLabel}>FOLLOW-UP EMAIL / MESSAGE DRAFT</Text>
            <Text style={styles.followUpText}>{result.summary.follow_up_email}</Text>
          </View>

          <TouchableOpacity
            style={[styles.secondaryBtn, { marginTop: 14 }]}
            onPress={() =>
              openWhatsAppRecap({
                phoneNumber: '',
                disposition: result.summary.disposition,
                score: result.summary.coaching_score,
                summary: result.summary.text,
                followUpEmail: result.summary.follow_up_email,
              })
            }
          >
            <Text style={styles.secondaryBtnText}>Share Recap to WhatsApp</Text>
          </TouchableOpacity>
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, paddingBottom: 40, gap: 14 },
  panel: {
    backgroundColor: colors.panel,
    borderColor: colors.panelEdge,
    borderWidth: 1,
    borderRadius: 16,
    padding: 16,
  },
  heading: { color: colors.text, fontSize: 20, fontWeight: '800', marginBottom: 4 },
  sub: { color: colors.secondary, fontSize: 13, lineHeight: 19, marginBottom: 14 },
  label: { color: colors.textDim, fontSize: 12, fontWeight: '700', marginBottom: 6, marginTop: 10 },
  input: {
    backgroundColor: colors.panel2,
    borderColor: colors.panelEdge,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.text,
    fontSize: 14,
  },
  textArea: { minHeight: 72, textAlignVertical: 'top' },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 12,
    marginTop: 8,
    gap: 12,
  },
  switchLabel: { color: colors.textDim, fontSize: 13, flex: 1 },
  primaryBtn: {
    backgroundColor: colors.teal,
    borderRadius: 10,
    paddingVertical: 13,
    alignItems: 'center',
    marginTop: 6,
  },
  primaryBtnText: { color: colors.tealDark, fontWeight: '800', fontSize: 14 },
  secondaryBtn: {
    backgroundColor: '#244258',
    borderColor: '#3a6180',
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
  },
  secondaryBtnText: { color: colors.text, fontWeight: '700', fontSize: 13 },
  disabledBtn: { opacity: 0.5 },
  errorText: { color: colors.danger, fontSize: 12, marginTop: 10 },
  resultHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  sectionTitle: { color: colors.text, fontSize: 16, fontWeight: '800', marginBottom: 6 },
  dispPill: { alignSelf: 'flex-start', paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12 },
  dispPillText: { fontSize: 12, fontWeight: '800' },
  scoreBox: { flexDirection: 'row', alignItems: 'baseline', gap: 4 },
  scoreVal: { color: colors.success, fontSize: 26, fontWeight: '800' },
  scoreMax: { color: colors.muted, fontSize: 12, fontWeight: '700' },
  bodyText: { color: colors.textDim, fontSize: 14, lineHeight: 21, marginBottom: 8 },
  coachingNotes: { color: colors.secondary, fontSize: 13, fontStyle: 'italic', marginBottom: 12 },
  hintCard: {
    backgroundColor: '#123c42',
    borderColor: '#2f5f5e',
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    marginBottom: 10,
  },
  hintLabel: { color: colors.muted, fontSize: 10, fontWeight: '800', letterSpacing: 0.5, marginBottom: 4 },
  hintText: { color: colors.text, fontSize: 14, fontWeight: '700', lineHeight: 20 },
  followUpCard: {
    backgroundColor: colors.panel2,
    borderColor: colors.panelEdge,
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
  },
  followUpText: { color: colors.textDim, fontSize: 13, lineHeight: 19 },
});
