import { MaterialCommunityIcons } from '@expo/vector-icons';
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Led, Meter, Panel } from '../components/ui';
import { num, str } from '../data/format';
import { useCarpe } from '../data/store';
import { colors, fonts } from '../theme';
import { batteryColor, ScreenScroll, useCardWidth } from './common';

// Ring camera names/fields match ring_client.py's camera_field_map.
const CAMERAS = [
  { name: 'SALON', key: 'Salon', wired: false },
  { name: 'BAKBOORD', key: 'Bakboord', wired: false },
  { name: 'STUURBOORD', key: 'Stuurboord', wired: false },
  { name: 'CONSOLE', key: 'Console', wired: true }, // wired cam - Ring pins battery at 100
];

export function CamScreen() {
  const { data } = useCarpe();
  const cardW = useCardWidth();
  const w = (cardW - 12) / 2;

  return (
    <ScreenScroll>
      <View style={styles.grid}>
        {CAMERAS.map((c) => {
          const battery = num(data, `RingBattery${c.key}`);
          const conn = str(data, `RingConnection${c.key}`);
          const online = conn === 'online';
          const accent = conn === null ? colors.neutral : online ? colors.ok : colors.danger;
          return (
            <View key={c.key} style={{ width: w }}>
              <Panel glow={accent}>
                <View style={styles.thumb}>
                  <MaterialCommunityIcons name={online ? 'cctv' : 'cctv-off'} size={44} color={accent} />
                </View>
                <View style={styles.headRow}>
                  <Text style={styles.name}>{c.name}</Text>
                  <Led state={conn === null ? 'off' : online ? 'ok' : 'bad'} size={10} />
                </View>
                <Text style={[styles.conn, { color: accent }]}>{conn ? conn.toUpperCase() : 'NO DATA'}</Text>
                {c.wired ? (
                  <Text style={styles.wired}>WIRED</Text>
                ) : (
                  <>
                    <View style={styles.battRow}>
                      <MaterialCommunityIcons name="battery-70" size={14} color={batteryColor(battery)} />
                      <Text style={styles.battText}>{battery === null ? '--' : `${Math.round(battery)}%`}</Text>
                    </View>
                    <Meter value={battery === null ? null : battery / 100} color={batteryColor(battery)} height={4} />
                  </>
                )}
              </Panel>
            </View>
          );
        })}
      </View>

      <Panel title="LIVE VIEW">
        <Text style={styles.note}>
          Live video isn't in this first version - the phone shows camera status and battery only. Live streaming
          from the Pi's Ring cameras needs a video route on the API, which is a separate step.
        </Text>
      </Panel>
    </ScreenScroll>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  thumb: {
    height: 84, borderRadius: 12, alignItems: 'center', justifyContent: 'center', marginBottom: 10,
    backgroundColor: '#ffffff08', borderWidth: 1, borderColor: colors.border, borderStyle: 'dashed',
  },
  headRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  name: { fontFamily: fonts.display, fontSize: 13, letterSpacing: 1.4, color: colors.text },
  conn: { fontFamily: fonts.labelBold, fontSize: 11.5, letterSpacing: 2, marginTop: 2 },
  wired: { fontFamily: fonts.labelBold, fontSize: 11, letterSpacing: 2, color: colors.textDim, marginTop: 8 },
  battRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 8 },
  battText: { fontFamily: fonts.label, fontSize: 12, color: colors.textDim },
  note: { fontFamily: fonts.body, fontSize: 14, lineHeight: 20, color: colors.textDim },
});
