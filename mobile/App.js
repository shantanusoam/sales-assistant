import React, { useEffect, useMemo, useState } from 'react';
import { SafeAreaView, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { SalesCopilotMobileClient } from './src/api';
import HistoryScreen from './src/screens/HistoryScreen';
import LiveCallScreen from './src/screens/LiveCallScreen';
import PostCallLoggerScreen from './src/screens/PostCallLoggerScreen';
import SettingsScreen from './src/screens/SettingsScreen';
import { subscribeToCallEnded } from './src/services/nativeCallBridge';
import { colors } from './src/theme';

export default function App() {
  const [serverUrl, setServerUrl] = useState('http://127.0.0.1:8000');
  const [session, setSession] = useState(null);
  const [activeTab, setActiveTab] = useState('live');
  const [lastEndedPhone, setLastEndedPhone] = useState('');

  // Auth form state
  const [isSignup, setIsSignup] = useState(false);
  const [orgName, setOrgName] = useState('');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [authError, setAuthError] = useState('');

  const client = useMemo(
    () => new SalesCopilotMobileClient({ baseUrl: serverUrl, token: session?.token }),
    [serverUrl, session?.token]
  );

  useEffect(() => {
    // Truecaller-style hook: automatically jump to Post-Call Logger when an Android call ends
    const unsubscribe = subscribeToCallEnded(({ phoneNumber }) => {
      if (phoneNumber) setLastEndedPhone(phoneNumber);
      setActiveTab('postcall');
    });
    return unsubscribe;
  }, []);

  async function handleAuthSubmit() {
    setAuthError('');
    try {
      const data = isSignup
        ? await client.signup({ organizationName: orgName, name, email, password })
        : await client.login(email, password);
      setSession(data);
    } catch (err) {
      setAuthError(err.message || 'Authentication failed.');
    }
  }

  if (!session) {
    return (
      <SafeAreaView style={styles.shell}>
        <View style={styles.authWrap}>
          <Text style={styles.brand}>
            Sales<Text style={styles.brandLight}>Copilot</Text> Mobile
          </Text>
          <Text style={styles.authSub}>
            Real-time phone & field-meeting AI copilot (English, Hindi & Hinglish)
          </Text>

          <TextInput
            style={styles.input}
            value={serverUrl}
            onChangeText={setServerUrl}
            autoCapitalize="none"
            placeholder="Backend URL (e.g. http://192.168.1.10:8000)"
            placeholderTextColor={colors.muted}
          />
          {isSignup && (
            <>
              <TextInput
                style={styles.input}
                value={orgName}
                onChangeText={setOrgName}
                placeholder="Organization name"
                placeholderTextColor={colors.muted}
              />
              <TextInput
                style={styles.input}
                value={name}
                onChangeText={setName}
                placeholder="Your name"
                placeholderTextColor={colors.muted}
              />
            </>
          )}
          <TextInput
            style={styles.input}
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            keyboardType="email-address"
            placeholder="Work email"
            placeholderTextColor={colors.muted}
          />
          <TextInput
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            placeholder="Password"
            placeholderTextColor={colors.muted}
          />

          {!!authError && <Text style={styles.errorText}>{authError}</Text>}

          <TouchableOpacity style={styles.primaryBtn} onPress={handleAuthSubmit}>
            <Text style={styles.primaryBtnText}>
              {isSignup ? 'Create Organization' : 'Log In'}
            </Text>
          </TouchableOpacity>

          <TouchableOpacity onPress={() => setIsSignup(!isSignup)} style={{ marginTop: 14 }}>
            <Text style={styles.switchAuthText}>
              {isSignup ? 'Already have an account? Log in' : 'New team? Create organization'}
            </Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.shell}>
      <View style={styles.topbar}>
        <Text style={styles.brand}>
          Sales<Text style={styles.brandLight}>Copilot</Text>
        </Text>
        <Text style={styles.orgChip}>
          {session.organization?.name} · {session.user?.name}
        </Text>
      </View>

      <View style={{ flex: 1 }}>
        {activeTab === 'live' && (
          <LiveCallScreen
            client={client}
            onCallEnded={() => setActiveTab('history')}
          />
        )}
        {activeTab === 'postcall' && (
          <PostCallLoggerScreen
            client={client}
            initialPhoneNumber={lastEndedPhone}
          />
        )}
        {activeTab === 'history' && <HistoryScreen client={client} />}
        {activeTab === 'settings' && (
          <SettingsScreen
            client={client}
            session={session}
            onServerUrlChange={setServerUrl}
            onLogout={() => setSession(null)}
          />
        )}
      </View>

      <View style={styles.tabbar}>
        {[
          { id: 'live', label: 'Live Call' },
          { id: 'postcall', label: 'Post-Call Log' },
          { id: 'history', label: 'History' },
          { id: 'settings', label: 'Settings' },
        ].map((t) => (
          <TouchableOpacity
            key={t.id}
            style={[styles.tabItem, activeTab === t.id && styles.tabItemActive]}
            onPress={() => setActiveTab(t.id)}
          >
            <Text style={[styles.tabLabel, activeTab === t.id && styles.tabLabelActive]}>
              {t.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  shell: { flex: 1, backgroundColor: colors.bg },
  authWrap: { flex: 1, justifyContent: 'center', padding: 24, gap: 12 },
  brand: { color: colors.text, fontSize: 22, fontWeight: '800' },
  brandLight: { color: colors.textDim, fontWeight: '500' },
  authSub: { color: colors.secondary, fontSize: 13, marginBottom: 8 },
  input: {
    backgroundColor: colors.panel2,
    borderColor: colors.panelEdge,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: colors.text,
    fontSize: 14,
  },
  primaryBtn: {
    backgroundColor: colors.teal,
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 4,
  },
  primaryBtnText: { color: colors.tealDark, fontWeight: '800', fontSize: 14 },
  switchAuthText: { color: colors.blue, fontSize: 13, fontWeight: '700', textAlign: 'center' },
  errorText: { color: colors.danger, fontSize: 12 },
  topbar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomColor: colors.line,
    borderBottomWidth: 1,
  },
  orgChip: { color: colors.secondary, fontSize: 12, fontWeight: '700' },
  tabbar: {
    flexDirection: 'row',
    borderTopColor: colors.line,
    borderTopWidth: 1,
    backgroundColor: colors.panel2,
    paddingVertical: 8,
    paddingHorizontal: 8,
  },
  tabItem: {
    flex: 1,
    paddingVertical: 8,
    borderRadius: 8,
    alignItems: 'center',
  },
  tabItemActive: { backgroundColor: 'rgba(79, 168, 220, 0.14)' },
  tabLabel: { color: colors.secondary, fontSize: 12, fontWeight: '700' },
  tabLabelActive: { color: colors.text },
});
