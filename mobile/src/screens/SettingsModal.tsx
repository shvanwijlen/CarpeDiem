import React, { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';

import { Panel } from '../components/ui';
import { ago } from '../data/format';
import { fetchJson } from '../data/http';
import { StoreSource } from '../data/source';
import { normalizeBaseUrl, useCarpe } from '../data/store';
import { colors, fonts } from '../theme';

interface TestResult {
  ok: boolean;
  text: string;
}

async function testStore(rawUrl: string, readKey: string): Promise<TestResult> {
  try {
    const latest = await new StoreSource(normalizeBaseUrl(rawUrl, 'https'), readKey.trim()).fetchLatest();
    if (latest.ageSeconds === null) return { ok: false, text: 'Connected, but the store has no data yet - is the Pi pushing?' };
    return { ok: true, text: `Connected - boat data is ${ago(latest.ageSeconds * 1000)} old` };
  } catch (e) {
    return { ok: false, text: e instanceof Error ? e.message : String(e) };
  }
}

async function testPi(rawUrl: string, apiKey: string): Promise<TestResult> {
  try {
    const json = await fetchJson<Record<string, unknown>>(`${normalizeBaseUrl(rawUrl, 'http')}/api/data`, apiKey.trim(), 5000);
    return { ok: true, text: `Connected - ${Object.keys(json).length} fields` };
  } catch (e) {
    return { ok: false, text: e instanceof Error ? e.message : String(e) };
  }
}

function TextField({
  label, hint, value, onChange, placeholder, disabled, result, secret,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  disabled: boolean;
  result?: TestResult | null;
  secret?: boolean;
}) {
  return (
    <View style={{ opacity: disabled ? 0.4 : 1 }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChange}
        editable={!disabled}
        secureTextEntry={secret}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType={secret ? 'default' : 'url'}
        placeholder={placeholder}
        placeholderTextColor={colors.textDim}
        style={styles.input}
      />
      <Text style={styles.hint}>{hint}</Text>
      {result ? <Text style={[styles.test, { color: result.ok ? colors.ok : colors.danger }]}>{result.text}</Text> : null}
    </View>
  );
}

export function SettingsModal({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const { settings, saveSettings } = useCarpe();
  const [storeUrl, setStoreUrl] = useState(settings.storeUrl);
  const [readKey, setReadKey] = useState(settings.readKey);
  const [piUrl, setPiUrl] = useState(settings.piUrl);
  const [piApiKey, setPiApiKey] = useState(settings.piApiKey);
  const [appLock, setAppLock] = useState(settings.appLock);
  const [demo, setDemo] = useState(settings.demo);
  const [testStoreResult, setTestStoreResult] = useState<TestResult | null>(null);
  const [testPiResult, setTestPiResult] = useState<TestResult | null>(null);

  useEffect(() => {
    if (visible) {
      setStoreUrl(settings.storeUrl);
      setReadKey(settings.readKey);
      setPiUrl(settings.piUrl);
      setPiApiKey(settings.piApiKey);
      setAppLock(settings.appLock);
      setDemo(settings.demo);
      setTestStoreResult(null);
      setTestPiResult(null);
    }
  }, [visible, settings]);

  const runTest = async () => {
    setTestStoreResult(storeUrl.trim() ? { ok: true, text: 'Testing...' } : null);
    setTestPiResult(piUrl.trim() ? { ok: true, text: 'Testing...' } : null);
    await Promise.all([
      storeUrl.trim() ? testStore(storeUrl, readKey).then(setTestStoreResult) : Promise.resolve(),
      piUrl.trim() ? testPi(piUrl, piApiKey).then(setTestPiResult) : Promise.resolve(),
    ]);
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />
        <Panel glow={colors.accent} title="CONNECTION" style={styles.sheet}>
          <ScrollView style={{ maxHeight: 520 }} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
            <View style={{ gap: 16 }}>
              <View style={styles.rowBetween}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.label}>DEMO MODE</Text>
                  <Text style={styles.hint}>Built-in sample data, no data store needed</Text>
                </View>
                <Switch value={demo} onValueChange={setDemo} trackColor={{ true: colors.accent, false: colors.border }} thumbColor="#fff" />
              </View>

              <TextField
                label="DATA STORE ADDRESS"
                hint="Where the boat's Pi sends its data and this app reads it - your Synology, e.g. https://carpediem.example.com"
                value={storeUrl}
                onChange={setStoreUrl}
                placeholder="https://carpediem.example.com"
                disabled={demo}
                result={testStoreResult}
              />
              <TextField
                label="READ KEY"
                hint="The store's READ_API_KEY (not the write key the Pi uses). Stored in the iPhone's Keychain."
                value={readKey}
                onChange={setReadKey}
                placeholder="READ_API_KEY from the store's .env"
                disabled={demo}
                secret
              />
              <TextField
                label="PI ON BOAT WIFI - LIVE CAMERA ONLY"
                hint="Optional. Live camera views stream straight from the Pi, so they only work while you're on the boat's WiFi. Everything else comes from the data store."
                value={piUrl}
                onChange={setPiUrl}
                placeholder="http://cdpi1.local:8080"
                disabled={demo}
                result={testPiResult}
              />
              {piUrl.trim() ? (
                <TextField
                  label="PI API KEY - OPTIONAL"
                  hint="Only if the Pi has WEBSERVER_API_KEY set. Stored in the iPhone's Keychain."
                  value={piApiKey}
                  onChange={setPiApiKey}
                  placeholder="WEBSERVER_API_KEY"
                  disabled={demo}
                  secret
                />
              ) : null}

              {Platform.OS !== 'web' ? (
                <View style={[styles.rowBetween, { opacity: demo ? 0.4 : 1 }]}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.label}>LOCK WITH FACE ID</Text>
                    <Text style={styles.hint}>
                      Asks for Face ID or your passcode when you open the app or come back after 30 seconds. Live
                      mode only. Face ID itself doesn't work inside Expo Go - it does in the TestFlight/App Store build.
                    </Text>
                  </View>
                  <Switch value={appLock} onValueChange={setAppLock} disabled={demo} trackColor={{ true: colors.accent, false: colors.border }} thumbColor="#fff" />
                </View>
              ) : null}

              <View style={styles.rowBetween}>
                <Pressable style={[styles.button, styles.buttonGhost]} onPress={runTest} disabled={demo}>
                  <Text style={[styles.buttonText, { color: colors.secondary }]}>TEST</Text>
                </Pressable>
                <Pressable style={[styles.button, styles.buttonGhost]} onPress={onClose}>
                  <Text style={[styles.buttonText, { color: colors.textDim }]}>CANCEL</Text>
                </Pressable>
                <Pressable
                  style={[styles.button, { backgroundColor: colors.accent }]}
                  onPress={() => {
                    saveSettings({ storeUrl, readKey, piUrl, piApiKey, appLock, demo });
                    onClose();
                  }}
                >
                  <Text style={[styles.buttonText, { color: '#000' }]}>SAVE</Text>
                </Pressable>
              </View>
            </View>
          </ScrollView>
        </Panel>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: '#000000AA' },
  sheet: { margin: 12, marginBottom: 28 },
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  label: { fontFamily: fonts.labelBold, fontSize: 12, letterSpacing: 2.4, color: colors.text },
  hint: { fontFamily: fonts.body, fontSize: 12, color: colors.textDim, marginTop: 2 },
  input: {
    marginTop: 6, borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10,
    color: colors.text, fontFamily: fonts.body, fontSize: 16, backgroundColor: colors.bg,
  },
  test: { fontFamily: fonts.labelBold, fontSize: 13, letterSpacing: 0.6, marginTop: 4 },
  button: { flex: 1, alignItems: 'center', paddingVertical: 11, borderRadius: 12 },
  buttonGhost: { borderWidth: 1, borderColor: colors.border, backgroundColor: colors.panel },
  buttonText: { fontFamily: fonts.labelBold, fontSize: 13, letterSpacing: 2 },
});
