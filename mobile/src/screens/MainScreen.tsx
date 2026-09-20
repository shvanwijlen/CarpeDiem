import { MaterialCommunityIcons } from '@expo/vector-icons';
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Compass, RadialGauge, Radar } from '../components/gauges';
import { Chip, Panel, Tile } from '../components/ui';
import { clamp, fmt, houseFillPercent, num, str } from '../data/format';
import { useCarpe } from '../data/store';
import { colors, fonts } from '../theme';
import { Row, ScreenScroll, useCardWidth } from './common';

const FLOW_MAX_W = 1200; // same full-scale the Pi's power page uses for its flow bars

// Same status -> color mapping as the Pi's main page banner
// (hmi_qt/pages/main_page.py: _next_object_color).
function objectStatusColor(status: string | null): string | null {
  if (!status) return null;
  const s = status.toUpperCase();
  if (s === 'OPEN') return colors.ok;
  if (s === 'BLOCKED') return colors.danger;
  if (s === 'CLOSED') return null;
  if (s.includes('OPENING') || s.includes('CLOSING') || s.includes('LOCKING')) return colors.warn;
  return null;
}

export function MainScreen() {
  const { data, vessels } = useCarpe();
  const cardW = useCardWidth();
  const compassSize = Math.min(cardW - 24, 340);

  const course = num(data, 'Course');
  const speed = num(data, 'Speed');
  const trueWind = num(data, 'WindspeedCalculatedRecalibrated');
  const relWind = num(data, 'WindspeedCalculatedAsExperienced');

  const nextObject = str(data, 'NextObject');
  const objStatus = str(data, 'NextObjectStatus');
  const clearance = num(data, 'NextObjectClearanceM');
  const dot = objectStatusColor(objStatus);

  const soc = num(data, 'Battery SOC (%)');
  const houseV = num(data, 'Battery0 Voltage (V)');
  const starterV = num(data, 'Starter battery (V)');
  const dcW = num(data, 'DC Power (W)');
  const pvW = num(data, 'PV Power (W)');

  const list = vessels.vessels;
  const count = (c: string) => list.filter((v) => v.category === c).length;
  const gaugeSize = Math.min((cardW - 12) / 2 - 8, 190);

  return (
    <ScreenScroll>
      {/* Navigation: compass card + wind legend */}
      <Panel glow={colors.accent} title="NAVIGATION" right={<Text style={styles.coords}>{fmt(num(data, 'Lat'), 4)}, {fmt(num(data, 'Lng'), 4)}</Text>}>
        <View style={{ alignItems: 'center', paddingVertical: 6 }}>
          <Compass size={compassSize} course={course} speed={speed} trueWind={trueWind} relWind={relWind} />
        </View>
        <View style={styles.legend}>
          <Chip color={colors.secondary} text="HEADING" count={course === null ? '--' : `${Math.round(course)}°`} />
          <Chip color={colors.tertiary} text="TRUE WIND" count={trueWind === null ? '--' : `${Math.round(trueWind)}°`} />
          <Chip color={colors.ok} text="REL WIND" count={relWind === null ? '--' : `${Math.round(relWind)}°`} />
        </View>
      </Panel>

      {/* Next bridge / lock banner */}
      <Panel glow={dot ?? colors.border} padded={false}>
        <View style={styles.banner}>
          <MaterialCommunityIcons name="bridge" size={26} color={nextObject ? colors.accent : colors.textDim} />
          <View style={{ flex: 1 }}>
            <Text style={styles.bannerLabel}>NEXT BRIDGE / LOCK</Text>
            <Text style={[styles.bannerText, { color: nextObject ? colors.text : colors.textDim }]} numberOfLines={2}>
              {nextObject ? nextObject.toUpperCase() : 'NO UPCOMING BRIDGE / LOCK'}
            </Text>
          </View>
          {nextObject ? (
            <View style={{ alignItems: 'flex-end', gap: 4 }}>
              <View style={styles.statusRow}>
                <View style={[styles.statusDot, { backgroundColor: dot ?? colors.neutral, shadowColor: dot ?? colors.neutral }]} />
                <Text style={[styles.statusText, { color: dot ?? colors.textDim }]}>{objStatus?.toUpperCase() ?? '--'}</Text>
              </View>
              {clearance !== null ? <Text style={styles.clearance}>▲ {clearance.toFixed(1)} m</Text> : null}
            </View>
          ) : null}
        </View>
      </Panel>

      {/* Power cluster: SOC + house/starter voltages + alternator/solar */}
      <Row>
        <Panel style={{ flex: 1 }} glow={colors.ok}>
          <View style={{ alignItems: 'center' }}>
            <RadialGauge size={gaugeSize} value={soc} valueText={soc === null ? '--' : `${Math.round(soc)}%`} subText="BATTERY" />
          </View>
        </Panel>
        <View style={{ flex: 1, gap: 12 }}>
          <Tile icon="car-battery" label="HOUSE 12V" value={fmt(houseV, 1)} unit="V" color={colors.secondary}
            bar={houseFillPercent(houseV) === null ? null : houseFillPercent(houseV)! / 100} />
          <Tile icon="engine" label="STARTER" value={fmt(starterV, 1)} unit="V" color={colors.tertiary}
            bar={houseFillPercent(starterV) === null ? null : houseFillPercent(starterV)! / 100} />
        </View>
      </Row>
      <Row>
        <Tile icon="flash" label="DC ALT" value={fmt(dcW, 0)} unit="W" color={colors.accent} bar={dcW === null ? null : clamp(dcW / FLOW_MAX_W, 0, 1)} />
        <Tile icon="solar-power" label="SOLAR" value={fmt(pvW, 0)} unit="W" color={colors.ok} bar={pvW === null ? null : clamp(pvW / 400, 0, 1)} />
      </Row>

      {/* Vessel radar */}
      <Panel glow={colors.ok} title="AIS RADAR" right={<Text style={styles.coords}>{vessels.max_range_km.toFixed(0)} KM</Text>}>
        <View style={{ alignItems: 'center', paddingVertical: 4 }}>
          <Radar size={Math.min(cardW - 24, 340)} maxKm={vessels.max_range_km} vessels={list} />
        </View>
        <View style={styles.legend}>
          {list.length > 0 ? (
            <>
              <Chip color={colors.danger} text="OVERTAKING" count={count('overtaking')} />
              <Chip color={colors.warn} text="FAST" count={count('fast')} />
              <Chip color={colors.ok} text="OK" count={count('ok')} />
              <Chip color={colors.neutral} text="MOORED" count={count('moored')} />
            </>
          ) : (
            <>
              <Chip color={colors.danger} text="BEHIND ME" count={fmt(num(data, 'VesselsBehindMe'))} />
              <Chip color={colors.warn} text=">10 KM/H" count={fmt(num(data, 'VesselsFasterThan10'))} />
              <Chip color={colors.ok} text="OTHER" count={fmt(num(data, 'VesselsOther'))} />
            </>
          )}
        </View>
      </Panel>
    </ScreenScroll>
  );
}

const styles = StyleSheet.create({
  coords: { fontFamily: fonts.body, fontSize: 12, color: colors.textDim, letterSpacing: 0.6 },
  legend: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 8, marginTop: 8 },
  banner: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingVertical: 12 },
  bannerLabel: { fontFamily: fonts.labelBold, fontSize: 10.5, letterSpacing: 2.4, color: colors.textDim },
  bannerText: { fontFamily: fonts.display, fontSize: 15, letterSpacing: 0.8, marginTop: 2 },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  statusDot: { width: 10, height: 10, borderRadius: 5, shadowOpacity: 1, shadowRadius: 6, shadowOffset: { width: 0, height: 0 } },
  statusText: { fontFamily: fonts.labelBold, fontSize: 12, letterSpacing: 1.6 },
  clearance: { fontFamily: fonts.display, fontSize: 12, color: colors.secondary },
});
