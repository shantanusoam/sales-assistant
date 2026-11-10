/**
 * Native bridge helpers for the 4 in-mobile capabilities:
 * 1. Background audio recording (Android Foreground Service + iOS UIBackgroundModes: audio)
 * 2. Floating Live Hint overlay (Android SYSTEM_ALERT_WINDOW / iOS ActivityKit Live Activity)
 * 3. Truecaller-style Call State Listener (Android PhoneStateListener -> post-call recap sheet)
 * 4. 1-Tap WhatsApp Recap Deep Link
 */
import { Linking, NativeEventEmitter, NativeModules, Platform } from 'react-native';

/**
 * Configure expo-av audio mode so microphone recording continues when the screen locks
 * during an in-person field sales meeting.
 */
export async function configureBackgroundAudio(AudioModule) {
  if (!AudioModule?.setAudioModeAsync) return false;
  const perm = await AudioModule.requestPermissionsAsync();
  if (!perm.granted) {
    throw new Error('Microphone permission is required for live field-meeting transcription.');
  }
  await AudioModule.setAudioModeAsync({
    allowsRecordingIOS: true,
    playsInSilentModeIOS: true,
    staysActiveInBackground: true,
    shouldDuckAndroid: true,
    playThroughEarpieceAndroid: false,
  });
  return true;
}

/**
 * Updates the native Floating Hint Bubble (Android SYSTEM_ALERT_WINDOW) or
 * iOS Lock-Screen Live Activity (ActivityKit) when the native module is linked,
 * and always returns the formatted overlay state for the in-app floating HUD.
 */
export async function pushFloatingHintOverlay({ hint, method, processingMs, sources = [] }) {
  const payload = {
    text: hint,
    badge: method === 'ai' ? 'AI GENERATED' : 'PLAYBOOK RULE',
    latencyLabel: typeof processingMs === 'number' ? `${processingMs} ms` : 'Live',
    sourceTitle: sources[0]?.title || 'Sales Playbook',
    updatedAt: Date.now(),
  };

  const nativeOverlay = NativeModules?.SalesCopilotOverlay;
  if (nativeOverlay?.updateHint) {
    try {
      await nativeOverlay.updateHint(payload);
    } catch {
      // Fallback to in-app floating HUD when overlay permission is not yet granted
    }
  }
  return payload;
}

/**
 * Subscribes to Android PHONE_STATE transitions (OFFHOOK -> IDLE) when a native
 * call-state module is present so the app can automatically pop up the Truecaller-style
 * post-call disposition & recap card as soon as a phone call ends.
 */
export function subscribeToCallEnded(onCallEnded) {
  const nativeCallMonitor = NativeModules?.SalesCopilotCallMonitor;
  if (!nativeCallMonitor) {
    return () => {};
  }
  const emitter = new NativeEventEmitter(nativeCallMonitor);
  const sub = emitter.addListener('SalesCopilotCallEnded', (event) => {
    onCallEnded?.({
      phoneNumber: event?.phoneNumber || '',
      durationSeconds: event?.durationSeconds || 0,
      platform: Platform.OS,
    });
  });
  return () => sub.remove();
}

/**
 * Opens WhatsApp directly with a pre-formatted post-call recap or follow-up message.
 */
export async function openWhatsAppRecap({ phoneNumber = '', disposition = '', score = null, summary = '', followUpEmail = '' }) {
  const cleanPhone = String(phoneNumber || '').replace(/[^\d+]/g, '');
  const lines = [
    `*Sales Copilot Call Recap*`,
    disposition ? `Outcome: *${disposition.replace(/_/g, ' ').toUpperCase()}*` : null,
    score !== null && score !== undefined ? `Coaching Score: *${score}/100*` : null,
    summary ? `\n${summary}` : null,
    followUpEmail ? `\n*Suggested Follow-Up:*\n${followUpEmail}` : null,
  ].filter(Boolean);

  const text = encodeURIComponent(lines.join('\n'));
  const url = cleanPhone
    ? `whatsapp://send?phone=${encodeURIComponent(cleanPhone)}&text=${text}`
    : `whatsapp://send?text=${text}`;

  const supported = await Linking.canOpenURL(url).catch(() => false);
  if (supported) {
    await Linking.openURL(url);
    return true;
  }
  const webUrl = `https://wa.me/${cleanPhone.replace(/^\+/, '')}?text=${text}`;
  await Linking.openURL(webUrl);
  return true;
}
