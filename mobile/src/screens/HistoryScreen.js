import React, { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { colors, DISPOSITION_META } from '../theme';

export default function HistoryScreen({ client }) {
  const [analytics, setAnalytics] = useState(null);
  const [calls, setCalls] = useState([]);
  const [selectedCall, setSelectedCall] = useState(null);
  const [dispositionFilter, setDispositionFilter] = useState('');
  const [loading, setLoading] = useState(false);

  async function loadAll(disp = dispositionFilter) {
    setLoading(true);
    try {
      const [stats, list] = await Promise.all([
        client.getAnalytics().catch(() => null),
        client.listCalls({ disposition: disp }),
      ]);
      if (stats) setAnalytics(stats);
      setCalls(list.calls || []);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll('');
  }, []);

  async function openDetail(callId) {
    try {
      const detail = await client.getCallDetail(callId);
      setSelectedCall(detail);
    } catch {
      // ignore
    }
  }

  if (selectedCall) {
    const disp = selectedCall.disposition ? DISPOSITION_META[selectedCall.disposition] : null;
    return (
      <ScrollView style={styles.container} contentContainerStyle={styles.content}>
        <TouchableOpacity onPress={() => setSelectedCall(null)} style={styles.backBtn}>
          <Text style={styles.backBtnText}>← Back to Call History</Text>
        </TouchableOpacity>
        <View style={styles.panel}>
          <Text style={styles.heading}>
            {selectedCall.channel === 'twilio'
              ? 'Phone Call'
              : selectedCall.channel === 'mobile'
              ? 'Mobile Field Call'
              : 'Live Mic Session'}
          </Text>
          <Text style={styles.sub}>
            {selectedCall.turn_count} turns · {selectedCall.hint_count} hints
            {selectedCall.rep_name ? ` · ${selectedCall.rep_name}` : ''}
          </Text>
          {disp && (
            <View style={[styles.dispPill, { backgroundColor: disp.bg, marginBottom: 10 }]}>
              <Text style={[styles.dispPillText, { color: disp.color }]}>{disp.label}</Text>
            </View>
          )}
          {selectedCall.summary && (
            <View style={styles.summaryBox}>
              <Text style={styles.scoreText}>
                Coaching Score: {selectedCall.summary.coaching_score}/100
              </Text>
              <Text style={styles.bodyText}>{selectedCall.summary.text}</Text>
              <Text style={styles.notesText}>{selectedCall.summary.coaching_notes}</Text>
            </View>
          )}
          {(selectedCall.turns || []).map((t) => (
            <View key={t.seq} style={styles.turnRow}>
              <Text style={styles.turnSource}>{t.source.toUpperCase()} · {t.sentiment}</Text>
              <Text style={styles.turnBody}>{t.text}</Text>
            </View>
          ))}
        </View>
      </ScrollView>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {analytics && (
        <View style={styles.overviewGrid}>
          <View style={styles.overviewItem}>
            <Text style={styles.overviewLabel}>TOTAL CALLS</Text>
            <Text style={styles.overviewValue}>{analytics.total_calls}</Text>
          </View>
          <View style={styles.overviewItem}>
            <Text style={styles.overviewLabel}>AVG SCORE</Text>
            <Text style={styles.overviewValue}>
              {analytics.avg_coaching_score !== null ? `${analytics.avg_coaching_score}/100` : '—'}
            </Text>
          </View>
          <View style={styles.overviewItem}>
            <Text style={styles.overviewLabel}>OBJECTIONS</Text>
            <Text style={[styles.overviewValue, { color: colors.orange }]}>
              {analytics.total_objections}
            </Text>
          </View>
        </View>
      )}

      <View style={styles.filterRow}>
        {[
          { key: '', label: 'All' },
          { key: 'interested', label: 'Interested' },
          { key: 'follow_up', label: 'Follow-up' },
          { key: 'not_interested', label: 'Not interested' },
        ].map((f) => (
          <TouchableOpacity
            key={f.key}
            style={[styles.filterChip, dispositionFilter === f.key && styles.filterChipActive]}
            onPress={() => {
              setDispositionFilter(f.key);
              loadAll(f.key);
            }}
          >
            <Text style={styles.filterChipText}>{f.label}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <View style={styles.panel}>
        <Text style={styles.heading}>Organization Call History</Text>
        {loading && <Text style={styles.sub}>Loading calls…</Text>}
        {!loading && calls.length === 0 && (
          <Text style={styles.sub}>No calls found for this filter.</Text>
        )}
        {calls.map((c) => {
          const disp = c.disposition ? DISPOSITION_META[c.disposition] : null;
          return (
            <TouchableOpacity
              key={c.id}
              style={styles.callRow}
              onPress={() => openDetail(c.id)}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.callTitle}>
                  {c.channel === 'twilio'
                    ? `Phone Call ${c.to_number || ''}`
                    : c.channel === 'mobile'
                    ? `Mobile Field Call ${c.to_number || ''}`
                    : 'Live Mic Session'}
                </Text>
                <Text style={styles.callMeta}>
                  {c.turn_count} turns · {c.hint_count} hints
                  {c.rep_name ? ` · ${c.rep_name}` : ''}
                </Text>
                {c.summary_preview && (
                  <Text style={styles.callPreview} numberOfLines={2}>
                    {c.summary_preview}
                  </Text>
                )}
              </View>
              <View style={styles.callRight}>
                {disp && (
                  <View style={[styles.dispPill, { backgroundColor: disp.bg }]}>
                    <Text style={[styles.dispPillText, { color: disp.color }]}>{disp.label}</Text>
                  </View>
                )}
                {c.coaching_score !== null && (
                  <Text style={styles.callScore}>{c.coaching_score}/100</Text>
                )}
              </View>
            </TouchableOpacity>
          );
        })}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, paddingBottom: 40, gap: 14 },
  overviewGrid: { flexDirection: 'row', gap: 10 },
  overviewItem: {
    flex: 1,
    backgroundColor: colors.panel,
    borderColor: colors.panelEdge,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
  },
  overviewLabel: { color: colors.muted, fontSize: 10, fontWeight: '800', marginBottom: 4 },
  overviewValue: { color: colors.text, fontSize: 18, fontWeight: '800' },
  filterRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  filterChip: {
    backgroundColor: colors.panel2,
    borderColor: colors.panelEdge,
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  filterChipActive: { backgroundColor: '#244258', borderColor: colors.blue },
  filterChipText: { color: colors.textDim, fontSize: 12, fontWeight: '700' },
  panel: {
    backgroundColor: colors.panel,
    borderColor: colors.panelEdge,
    borderWidth: 1,
    borderRadius: 16,
    padding: 16,
  },
  heading: { color: colors.text, fontSize: 18, fontWeight: '800', marginBottom: 6 },
  sub: { color: colors.secondary, fontSize: 12, marginBottom: 10 },
  callRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 12,
    borderTopColor: colors.line,
    borderTopWidth: 1,
    gap: 10,
  },
  callTitle: { color: colors.text, fontSize: 14, fontWeight: '700' },
  callMeta: { color: colors.muted, fontSize: 12, marginTop: 2 },
  callPreview: { color: colors.secondary, fontSize: 12, marginTop: 4 },
  callRight: { alignItems: 'flex-end', gap: 6 },
  dispPill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 10 },
  dispPillText: { fontSize: 11, fontWeight: '800' },
  callScore: { color: colors.success, fontSize: 12, fontWeight: '800' },
  backBtn: { marginBottom: 4 },
  backBtnText: { color: colors.blue, fontSize: 14, fontWeight: '700' },
  summaryBox: {
    backgroundColor: colors.panel2,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  scoreText: { color: colors.success, fontSize: 15, fontWeight: '800', marginBottom: 6 },
  bodyText: { color: colors.textDim, fontSize: 13, lineHeight: 19, marginBottom: 6 },
  notesText: { color: colors.secondary, fontSize: 12, fontStyle: 'italic' },
  turnRow: { borderTopColor: colors.line, borderTopWidth: 1, paddingVertical: 8 },
  turnSource: { color: colors.muted, fontSize: 10, fontWeight: '800', marginBottom: 2 },
  turnBody: { color: colors.text, fontSize: 13, lineHeight: 19 },
});
