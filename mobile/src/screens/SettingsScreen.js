import React, { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, Switch, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { colors } from '../theme';

export default function SettingsScreen({ client, session, onServerUrlChange, onLogout }) {
  const [serverUrl, setServerUrl] = useState(client.baseUrl);
  const [whatsappNumber, setWhatsappNumber] = useState(session?.user?.whatsapp_number || '');
  const [whatsappEnabled, setWhatsappEnabled] = useState(!!session?.user?.whatsapp_recap_enabled);
  const [team, setTeam] = useState([]);
  const [notice, setNotice] = useState('');

  useEffect(() => {
    client
      .getMe()
      .then((me) => {
        setWhatsappNumber(me.user.whatsapp_number || '');
        setWhatsappEnabled(!!me.user.whatsapp_recap_enabled);
      })
      .catch(() => {});
    client
      .getTeam()
      .then((res) => setTeam(res.members || []))
      .catch(() => {});
  }, []);

  async function saveServerUrl() {
    client.setBaseUrl(serverUrl);
    onServerUrlChange?.(client.baseUrl);
    try {
      const health = await client.checkHealth();
      setNotice(`Connected to server (${health.stt_provider.toUpperCase()} STT · ${health.retrieval_mode}).`);
    } catch (err) {
      setNotice(`Server unreachable: ${err.message}`);
    }
  }

  async function saveWhatsApp() {
    try {
      const updated = await client.updateWhatsAppPrefs({
        whatsappNumber,
        whatsappRecapEnabled: whatsappEnabled,
      });
      setWhatsappNumber(updated.whatsapp_number || '');
      setWhatsappEnabled(!!updated.whatsapp_recap_enabled);
      setNotice('WhatsApp recap preferences saved.');
    } catch (err) {
      setNotice(err.message);
    }
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <View style={styles.panel}>
        <Text style={styles.heading}>Backend Server Connection</Text>
        <Text style={styles.sub}>
          Point to your FastAPI server LAN IP or HTTPS tunnel when running on a physical phone.
        </Text>
        <TextInput
          style={styles.input}
          value={serverUrl}
          onChangeText={setServerUrl}
          autoCapitalize="none"
          placeholder="http://192.168.1.10:8000"
          placeholderTextColor={colors.muted}
        />
        <TouchableOpacity style={styles.secondaryBtn} onPress={saveServerUrl}>
          <Text style={styles.secondaryBtnText}>Save & Test Server</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.panel}>
        <Text style={styles.heading}>WhatsApp Post-Call Recap</Text>
        <Text style={styles.sub}>
          Receive a templated WhatsApp message (disposition, score, summary) after every consented call.
        </Text>
        <TextInput
          style={styles.input}
          value={whatsappNumber}
          onChangeText={setWhatsappNumber}
          placeholder="+919876543210"
          placeholderTextColor={colors.muted}
          keyboardType="phone-pad"
        />
        <View style={styles.switchRow}>
          <Text style={styles.switchLabel}>Send me a WhatsApp recap after each call</Text>
          <Switch
            value={whatsappEnabled}
            onValueChange={setWhatsappEnabled}
            trackColor={{ false: colors.panelEdge, true: colors.teal }}
          />
        </View>
        <TouchableOpacity style={styles.primaryBtn} onPress={saveWhatsApp}>
          <Text style={styles.primaryBtnText}>Save WhatsApp Settings</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.panel}>
        <Text style={styles.heading}>Organization Team ({team.length})</Text>
        {team.map((m) => (
          <View key={m.id} style={styles.memberRow}>
            <View>
              <Text style={styles.memberName}>{m.name}</Text>
              <Text style={styles.memberEmail}>{m.email}</Text>
            </View>
            <Text style={styles.memberRole}>{m.role.toUpperCase()}</Text>
          </View>
        ))}
      </View>

      {!!notice && <Text style={styles.notice}>{notice}</Text>}

      <TouchableOpacity style={styles.logoutBtn} onPress={onLogout}>
        <Text style={styles.logoutBtnText}>Log Out</Text>
      </TouchableOpacity>
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
  heading: { color: colors.text, fontSize: 17, fontWeight: '800', marginBottom: 4 },
  sub: { color: colors.secondary, fontSize: 12, marginBottom: 10, lineHeight: 18 },
  input: {
    backgroundColor: colors.panel2,
    borderColor: colors.panelEdge,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.text,
    fontSize: 14,
    marginBottom: 10,
  },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 10,
  },
  switchLabel: { color: colors.textDim, fontSize: 13, flex: 1 },
  primaryBtn: {
    backgroundColor: colors.teal,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
  },
  primaryBtnText: { color: colors.tealDark, fontWeight: '800', fontSize: 14 },
  secondaryBtn: {
    backgroundColor: '#244258',
    borderColor: '#3a6180',
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 11,
    alignItems: 'center',
  },
  secondaryBtnText: { color: colors.text, fontWeight: '700', fontSize: 13 },
  memberRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 8,
    borderTopColor: colors.line,
    borderTopWidth: 1,
  },
  memberName: { color: colors.text, fontSize: 14, fontWeight: '700' },
  memberEmail: { color: colors.muted, fontSize: 12 },
  memberRole: { color: colors.teal, fontSize: 11, fontWeight: '800' },
  notice: { color: colors.teal, fontSize: 13, textAlign: 'center', marginVertical: 4 },
  logoutBtn: {
    borderColor: colors.danger,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
  },
  logoutBtnText: { color: colors.danger, fontWeight: '800', fontSize: 14 },
});
