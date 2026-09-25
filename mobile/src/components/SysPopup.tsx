import React from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import { useCarpe } from '../data/store';
import type { SysLevel } from '../data/types';
import { colors, fonts } from '../theme';
import { Meter, Panel } from './ui';

const LEVEL_COLOR: Record<SysLevel, string> = { ok: colors.ok, warn: colors.warn, crit: colors.danger };
const STATUS_TEXT: Record<SysLevel, string> = { ok: 'ALL SYSTEMS OK', warn: 'WARNING', crit: 'CRITICAL' };

// What you get when you tap the SYS lamp: CPU / memory / disk usage and the
// Pi's own temperature - the same rows the Pi's touch display shows (they
// arrive pre-formatted from the Pi, inside the store's state). Tap anywhere to close.
export function SysPopup({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const { system, status } = useCarpe();
  const rows = system?.status ? system.rows : undefined;
  const tint = system?.status ? LEVEL_COLOR[system.status] : colors.neutral;

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="Close system details">
        <Panel glow={tint} title="SYSTEM" style={styles.card}
          right={<Text style={[styles.status, { color: tint }]}>{system?.status ? STATUS_TEXT[system.status] : 'NO DATA'}</Text>}>
          {rows ? (
            <View style={{ gap: 16 }}>
              {rows.map((r) => (
                <View key={r.label}>
                  <View style={styles.line}>
                    <Text style={styles.label}>{r.label}</Text>
                    <Text style={[styles.value, { color: LEVEL_COLOR[r.level] }]}>{r.value}</Text>
                  </View>
                  {r.fraction !== null ? <Meter value={r.fraction} color={LEVEL_COLOR[r.level]} height={7} /> : null}
                </View>
              ))}
            </View>
          ) : (
            <Text style={styles.empty}>
              {status === 'live' || status === 'stale'
                ? "The Pi didn't report system stats. Update the Pi software, or check that CARPEDIEM_CHECK_SYSMETRICS is on."
                : 'No connection to the data store.'}
            </Text>
          )}
          <Text style={styles.hint}>TAP ANYWHERE TO CLOSE</Text>
        </Panel>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: '#000000B0', justifyContent: 'center', padding: 24 },
  card: { alignSelf: 'center', width: '100%', maxWidth: 420 },
  status: { fontFamily: fonts.labelBold, fontSize: 12, letterSpacing: 2 },
  line: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  label: { fontFamily: fonts.labelBold, fontSize: 12, letterSpacing: 2.2, color: colors.textDim },
  value: { fontFamily: fonts.display, fontSize: 16 },
  empty: { fontFamily: fonts.body, fontSize: 14, lineHeight: 20, color: colors.textDim },
  hint: { fontFamily: fonts.labelBold, fontSize: 10.5, letterSpacing: 2, color: colors.textDim, textAlign: 'center', marginTop: 18 },
});
