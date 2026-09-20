import React, { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, StyleSheet, Switch, Text, TextInput, View } from 'react-native';

import { Panel } from '../components/ui';
import { normalizeBaseUrl, useCarpe } from '../data/store';
import { colors, fonts } from '../theme';

export function SettingsModal({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const { settings, saveSettings } = useCarpe();
  const [url, setUrl] = useState(settings.baseUrl);
  const [demo, setDemo] = useState(settings.demo);
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (visible) {
      setUrl(settings.baseUrl);
      setDemo(settings.demo);
      setTest(null);
    }
  }, [visible, settings]);

  const runTest = async () => {
    setTest({ ok: true, text: 'Testing...' });
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const res = await fetch(`${normalizeBaseUrl(url)}/api/data`, { signal: controller.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setTest({ ok: true, text: `Connected - ${Object.keys(json).length} fields` });
    } catch (e) {
      setTest({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      clearTimeout(timer);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />
        <Panel glow={colors.accent} title="CONNECTION" style={styles.sheet}>
          <View style={{ gap: 14 }}>
            <View style={styles.rowBetween}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>DEMO MODE</Text>
                <Text style={styles.hint}>Built-in sample data, no Pi needed</Text>
              </View>
              <Switch value={demo} onValueChange={setDemo} trackColor={{ true: colors.accent, false: colors.border }} thumbColor="#fff" />
            </View>

            <View style={{ opacity: demo ? 0.4 : 1 }}>
              <Text style={styles.label}>PI ADDRESS</Text>
              <TextInput
                value={url}
                onChangeText={setUrl}
                editable={!demo}
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="url"
                placeholder="http://192.168.1.50:8080"
                placeholderTextColor={colors.textDim}
                style={styles.input}
              />
              <Text style={styles.hint}>Boat LAN IP, or the Pi's NordVPN Meshnet 100.x address when away</Text>
            </View>

            {test ? <Text style={[styles.test, { color: test.ok ? colors.ok : colors.danger }]}>{test.text}</Text> : null}

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
                  saveSettings({ baseUrl: url, demo });
                  onClose();
                }}
              >
                <Text style={[styles.buttonText, { color: '#000' }]}>SAVE</Text>
              </Pressable>
            </View>
          </View>
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
  test: { fontFamily: fonts.labelBold, fontSize: 13, letterSpacing: 0.6 },
  button: { flex: 1, alignItems: 'center', paddingVertical: 11, borderRadius: 12 },
  buttonGhost: { borderWidth: 1, borderColor: colors.border, backgroundColor: colors.panel },
  buttonText: { fontFamily: fonts.labelBold, fontSize: 13, letterSpacing: 2 },
});
