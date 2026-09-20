import React, { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';

import { Panel } from '../components/ui';
import { normalizeBaseUrl, useCarpe } from '../data/store';
import { colors, fonts } from '../theme';

interface TestResult {
  ok: boolean;
  text: string;
}

async function testAddress(rawUrl: string): Promise<TestResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const res = await fetch(`${normalizeBaseUrl(rawUrl)}/api/data`, { signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    return { ok: true, text: `Connected - ${Object.keys(json).length} fields` };
  } catch (e) {
    return { ok: false, text: e instanceof Error ? e.message : String(e) };
  } finally {
    clearTimeout(timer);
  }
}

function AddressField({
  label, hint, value, onChange, placeholder, disabled, result,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  disabled: boolean;
  result: TestResult | null;
}) {
  return (
    <View style={{ opacity: disabled ? 0.4 : 1 }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChange}
        editable={!disabled}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
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
  const { settings, saveSettings, status, activeSlot } = useCarpe();
  const [url, setUrl] = useState(settings.baseUrl);
  const [alt, setAlt] = useState(settings.altUrl);
  const [demo, setDemo] = useState(settings.demo);
  const [testPrimary, setTestPrimary] = useState<TestResult | null>(null);
  const [testAlt, setTestAlt] = useState<TestResult | null>(null);

  useEffect(() => {
    if (visible) {
      setUrl(settings.baseUrl);
      setAlt(settings.altUrl);
      setDemo(settings.demo);
      setTestPrimary(null);
      setTestAlt(null);
    }
  }, [visible, settings]);

  const runTest = async () => {
    setTestPrimary(url.trim() ? { ok: true, text: 'Testing...' } : null);
    setTestAlt(alt.trim() ? { ok: true, text: 'Testing...' } : null);
    await Promise.all([
      url.trim() ? testAddress(url).then(setTestPrimary) : Promise.resolve(),
      alt.trim() ? testAddress(alt).then(setTestAlt) : Promise.resolve(),
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
                  <Text style={styles.hint}>Built-in sample data, no Pi needed</Text>
                </View>
                <Switch value={demo} onValueChange={setDemo} trackColor={{ true: colors.accent, false: colors.border }} thumbColor="#fff" />
              </View>

              <AddressField
                label="ON THE BOAT (WIFI)"
                hint="The Pi's hostname or IP on the boat's network"
                value={url}
                onChange={setUrl}
                placeholder="http://cdpi1.local:8080"
                disabled={demo}
                result={testPrimary}
              />
              <AddressField
                label="AWAY (MESHNET) - OPTIONAL"
                hint="Tried automatically if the boat address doesn't answer, e.g. the Pi's NordVPN Meshnet name or 100.x address"
                value={alt}
                onChange={setAlt}
                placeholder="http://simon-gila1792.nord:8080"
                disabled={demo}
                result={testAlt}
              />

              {!demo && status === 'live' && activeSlot ? (
                <Text style={styles.hint}>Currently connected via the {activeSlot === 'alt' ? 'AWAY' : 'BOAT'} address</Text>
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
                    saveSettings({ baseUrl: url, altUrl: alt, demo });
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
