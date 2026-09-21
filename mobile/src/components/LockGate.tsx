import { MaterialCommunityIcons } from '@expo/vector-icons';
import * as LocalAuthentication from 'expo-local-authentication';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Modal, Platform, Pressable, StyleSheet, Text, View } from 'react-native';

import { opensAnyway, shouldRelock } from '../data/lockPolicy';
import { useCarpe } from '../data/store';
import { colors, fonts } from '../theme';
import { Backdrop } from './chrome';

// Dev-only: EXPO_PUBLIC_LOCK_PREVIEW=1 forces the lock screen on, so it can
// be looked at in a browser (where Face ID doesn't exist). Unset in real builds.
const PREVIEW = process.env.EXPO_PUBLIC_LOCK_PREVIEW === '1';

/**
 * Face ID / passcode lock. Wraps the whole app:
 *  - locked on every cold start, and again after the app has been in the
 *    background for LOCK_GRACE_MS or more;
 *  - while the app is inactive or in the background (the app-switcher preview)
 *    the content is covered, so the snapshot doesn't show boat data;
 *  - only in live mode: demo mode shows nothing sensitive (and App Store
 *    reviewers, who can only use demo mode, never meet a lock).
 * The lock screen is a Modal so it also stacks above the settings sheet.
 */
export function LockGate({ children }: { children: React.ReactNode }) {
  const { settings, ready } = useCarpe();
  const enabled = PREVIEW || (Platform.OS !== 'web' && settings.appLock && !settings.demo);

  const [locked, setLocked] = useState(true); // every launch starts locked
  const [covered, setCovered] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const backgroundedAt = useRef<number | null>(null);
  const authenticating = useRef(false);

  const unlock = useCallback(async () => {
    if (PREVIEW || authenticating.current) return; // preview: just show the screen, never authenticate
    authenticating.current = true;
    setMessage(null);
    try {
      const result = await LocalAuthentication.authenticateAsync({ promptMessage: 'Unlock Carpe Diem', cancelLabel: 'Cancel' });
      if (result.success || opensAnyway(result.error)) {
        setLocked(false); // (a phone with no passcode can't authenticate at all - don't lock them out)
      } else if (result.error !== 'user_cancel') {
        setMessage("Couldn't verify it's you - try again");
      }
    } catch {
      setMessage('Face ID / passcode is unavailable here');
    } finally {
      authenticating.current = false;
    }
  }, []);

  // Lock switched off (or demo mode): nothing to unlock. Waits for `ready` so
  // the not-yet-loaded default settings can't unlock a cold start.
  useEffect(() => {
    if (ready && !enabled) setLocked(false);
  }, [ready, enabled]);

  // Ask straight away whenever the app becomes locked.
  useEffect(() => {
    if (ready && enabled && locked) void unlock();
  }, [ready, enabled, locked, unlock]);

  useEffect(() => {
    if (!enabled) return;
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') {
        setCovered(false);
        if (shouldRelock(backgroundedAt.current, Date.now())) setLocked(true);
        backgroundedAt.current = null;
      } else {
        setCovered(true);
        // 'inactive' also happens while the Face ID sheet is up, so only a
        // real 'background' starts the relock clock.
        if (state === 'background' && backgroundedAt.current === null) backgroundedAt.current = Date.now();
      }
    });
    return () => sub.remove();
  }, [enabled]);

  const showLock = ready && enabled && locked;
  return (
    <>
      {children}
      <Modal visible={ready && enabled && (locked || covered)} animationType="none" statusBarTranslucent onRequestClose={() => {}}>
        <LockScreen interactive={showLock} message={message} onUnlock={unlock} onSkip={__DEV__ ? () => setLocked(false) : undefined} />
      </Modal>
    </>
  );
}

function LockScreen({ interactive, message, onUnlock, onSkip }: {
  interactive: boolean;
  message: string | null;
  onUnlock: () => void;
  onSkip?: () => void;
}) {
  return (
    <View style={styles.screen}>
      <Backdrop />
      <View style={styles.ring}>
        <MaterialCommunityIcons name={interactive ? 'face-recognition' : 'lock-outline'} size={54} color={colors.accent} />
      </View>
      <Text style={styles.brand}>CARPE DIEM</Text>
      <Text style={styles.sub}>{interactive ? 'LOCKED' : 'PRIVATE'}</Text>

      {interactive ? (
        <View style={{ alignItems: 'center', gap: 14, marginTop: 34 }}>
          <Pressable style={styles.button} onPress={onUnlock} accessibilityLabel="Unlock">
            <MaterialCommunityIcons name="lock-open-variant-outline" size={18} color="#000" />
            <Text style={styles.buttonText}>UNLOCK</Text>
          </Pressable>
          {message ? <Text style={styles.message}>{message}</Text> : null}
          {onSkip ? (
            <Pressable onPress={onSkip} hitSlop={12}>
              <Text style={styles.skip}>SKIP (DEVELOPMENT BUILDS ONLY)</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg, alignItems: 'center', justifyContent: 'center', padding: 24 },
  ring: {
    width: 124, height: 124, borderRadius: 62, alignItems: 'center', justifyContent: 'center', marginBottom: 26,
    borderWidth: 2, borderColor: colors.accent, backgroundColor: colors.panel,
    shadowColor: colors.accent, shadowOpacity: 0.8, shadowRadius: 26, shadowOffset: { width: 0, height: 0 },
  },
  brand: {
    fontFamily: fonts.displayBlack, fontSize: 28, letterSpacing: 5, color: colors.accent,
    textShadowColor: colors.accent, textShadowOffset: { width: 0, height: 0 }, textShadowRadius: 16,
  },
  sub: { fontFamily: fonts.labelBold, fontSize: 14, letterSpacing: 7, color: colors.textDim, marginTop: 6 },
  button: {
    flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: colors.accent, borderRadius: 14,
    paddingHorizontal: 34, paddingVertical: 14,
    shadowColor: colors.accent, shadowOpacity: 0.7, shadowRadius: 14, shadowOffset: { width: 0, height: 0 },
  },
  buttonText: { fontFamily: fonts.labelBold, fontSize: 15, letterSpacing: 3, color: '#000' },
  message: { fontFamily: fonts.body, fontSize: 14, color: colors.warn, textAlign: 'center' },
  skip: { fontFamily: fonts.labelBold, fontSize: 11, letterSpacing: 2, color: colors.textDim },
});
