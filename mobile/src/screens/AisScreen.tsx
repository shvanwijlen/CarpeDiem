import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Radar } from '../components/gauges';
import { Chip, Led, LedState, Panel } from '../components/ui';
import { fmt, num } from '../data/format';
import { useCarpe } from '../data/store';
import type { Vessel } from '../data/types';
import { colors, fonts } from '../theme';
import { ScreenScroll, useCardWidth } from './common';

const CAT: Record<Vessel['category'], { color: string; label: string }> = {
  overtaking: { color: colors.danger, label: 'OVERTAKING' },
  fast: { color: colors.warn, label: 'FAST' },
  ok: { color: colors.ok, label: 'UNDERWAY' },
  moored: { color: colors.neutral, label: 'MOORED' },
};
const ORDER: Vessel['category'][] = ['overtaking', 'fast', 'ok', 'moored'];

function lamp(v: number | null): LedState {
  return v === null ? 'off' : v === 1 ? 'ok' : 'bad';
}

export function AisScreen() {
  const { data, vessels } = useCarpe();
  const cardW = useCardWidth();
  const list = vessels.vessels.filter((v) => v.distance_km <= vessels.max_range_km);
  const sorted = [...list].sort((a, b) => ORDER.indexOf(a.category) - ORDER.indexOf(b.category) || a.distance_km - b.distance_km);
  const count = (c: string) => list.filter((v) => v.category === c).length;

  return (
    <ScreenScroll>
      <Panel glow={colors.ok} title="RADAR" right={<Text style={styles.dim}>{vessels.max_range_km.toFixed(0)} KM · BOW UP</Text>}>
        <View style={{ alignItems: 'center', paddingVertical: 4 }}>
          <Radar size={Math.min(cardW - 24, 380)} maxKm={vessels.max_range_km} vessels={list} />
        </View>
        <View style={styles.legend}>
          <Chip color={colors.danger} text="OVERTAKING" count={count('overtaking')} />
          <Chip color={colors.warn} text="FAST" count={count('fast')} />
          <Chip color={colors.ok} text="UNDERWAY" count={count('ok')} />
          <Chip color={colors.neutral} text="MOORED" count={count('moored')} />
        </View>
      </Panel>

      <Panel title="RECEIVERS">
        <View style={styles.receivers}>
          {[['AIS (EM-TRAK)', 'AIS'], ['AISSTREAM', 'AISstream'], ['ANTENNA', 'AISAntenna']].map(([caption, key]) => (
            <View key={key} style={styles.receiver}>
              <Led state={lamp(num(data, key))} size={12} />
              <Text style={styles.receiverText}>{caption}</Text>
            </View>
          ))}
        </View>
        <View style={styles.legend}>
          <Chip color={colors.danger} text="BEHIND ME" count={fmt(num(data, 'VesselsBehindMe'))} />
          <Chip color={colors.warn} text=">10 KM/H" count={fmt(num(data, 'VesselsFasterThan10'))} />
          <Chip color={colors.ok} text="OTHER" count={fmt(num(data, 'VesselsOther'))} />
        </View>
      </Panel>

      <Panel title={`NEARBY VESSELS (${sorted.length})`} padded={false}>
        {sorted.length === 0 ? (
          <Text style={[styles.dim, { padding: 14 }]}>No vessel list from the Pi (needs the /api/vessels endpoint).</Text>
        ) : (
          sorted.slice(0, 14).map((v, i) => {
            const cat = CAT[v.category];
            const side = v.bearing_deg < 0 ? 'BB' : 'SB';
            return (
              <View key={v.mmsi} style={[styles.vessel, i > 0 && styles.vesselDivider]}>
                <View style={[styles.dot, { backgroundColor: cat.color, shadowColor: cat.color }]} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.vName} numberOfLines={1}>{v.name ?? `MMSI ${v.mmsi}`}</Text>
                  <Text style={[styles.vCat, { color: cat.color }]}>{cat.label}</Text>
                </View>
                <View style={{ alignItems: 'flex-end' }}>
                  <Text style={styles.vDist}>{v.distance_km.toFixed(1)} km</Text>
                  <Text style={styles.vSub}>{Math.abs(Math.round(v.bearing_deg))}° {side}{v.speed_knots ? ` · ${v.speed_knots.toFixed(1)} kn` : ''}</Text>
                </View>
              </View>
            );
          })
        )}
      </Panel>
    </ScreenScroll>
  );
}

const styles = StyleSheet.create({
  dim: { fontFamily: fonts.body, fontSize: 12, color: colors.textDim, letterSpacing: 0.6 },
  legend: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 8, marginTop: 8 },
  receivers: { flexDirection: 'row', justifyContent: 'space-around', paddingVertical: 4 },
  receiver: { alignItems: 'center', gap: 6 },
  receiverText: { fontFamily: fonts.labelBold, fontSize: 11, letterSpacing: 1.4, color: colors.textDim },
  vessel: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingVertical: 10 },
  vesselDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  dot: { width: 10, height: 10, borderRadius: 5, shadowOpacity: 1, shadowRadius: 6, shadowOffset: { width: 0, height: 0 } },
  vName: { fontFamily: fonts.display, fontSize: 13, color: colors.text, letterSpacing: 0.6 },
  vCat: { fontFamily: fonts.labelBold, fontSize: 10.5, letterSpacing: 1.6, marginTop: 1 },
  vDist: { fontFamily: fonts.display, fontSize: 14, color: colors.text },
  vSub: { fontFamily: fonts.body, fontSize: 12, color: colors.textDim },
});
