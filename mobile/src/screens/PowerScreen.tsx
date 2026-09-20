import { MaterialCommunityIcons } from '@expo/vector-icons';
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { RadialGauge } from '../components/gauges';
import { Chip, IconName, Meter, Panel, Tile } from '../components/ui';
import { clamp, fmt, houseFillPercent, inputSourceName, num } from '../data/format';
import { useCarpe } from '../data/store';
import { colors, fonts } from '../theme';
import { Row, ScreenScroll, useCardWidth } from './common';

const FLOW_MAX_W = 1200;

function FlowRow({ icon, label, watts, color, signed = false }: {
  icon: IconName; label: string; watts: number | null; color: string; signed?: boolean;
}) {
  const shown = watts === null ? '--' : `${signed && watts > 0 ? '+' : ''}${watts.toFixed(0)}`;
  return (
    <View style={styles.flowRow}>
      <MaterialCommunityIcons name={icon} size={20} color={color} style={{ width: 24 }} />
      <View style={{ flex: 1 }}>
        <View style={styles.flowHead}>
          <Text style={styles.flowLabel}>{label}</Text>
          <Text style={[styles.flowValue, { color }]}>{shown}<Text style={styles.flowUnit}> W</Text></Text>
        </View>
        <Meter value={watts === null ? null : clamp(Math.abs(watts) / FLOW_MAX_W, 0, 1)} color={color} height={7} />
      </View>
    </View>
  );
}

export function PowerScreen() {
  const { data } = useCarpe();
  const cardW = useCardWidth();
  const soc = num(data, 'Battery SOC (%)');
  const ttg = num(data, 'Battery Time to Go (System)') ?? num(data, 'Battery Time to Go (Batt)');
  const houseV = num(data, 'Battery0 Voltage (V)');
  const starterV = num(data, 'Starter battery (V)');
  const source = num(data, 'Active input source');
  const battW = num(data, 'Battery Power (W)') ?? num(data, 'Battery0 Power (W)');
  const houseFill = houseFillPercent(houseV);
  const starterFill = houseFillPercent(starterV);

  return (
    <ScreenScroll>
      <Panel glow={colors.ok} title="BATTERY">
        <View style={{ alignItems: 'center' }}>
          <RadialGauge size={Math.min(cardW - 60, 240)} value={soc} valueText={soc === null ? '--' : `${Math.round(soc)}%`} subText="CHARGE" />
        </View>
        <View style={styles.chips}>
          <Chip color={colors.secondary} text="TIME TO GO" count={ttg === null ? '--' : `${ttg.toFixed(1)} h`} />
          <Chip color={colors.accent} text="INPUT" count={inputSourceName(source)} />
        </View>
      </Panel>

      <Panel glow={colors.accent} title="POWER FLOW">
        <View style={{ gap: 14 }}>
          <FlowRow icon="power-plug" label="GRID / SHORE" watts={num(data, 'Grid (W)')} color={colors.secondary} />
          <FlowRow icon="solar-power" label="SOLAR" watts={num(data, 'PV Power (W)')} color={colors.ok} />
          <FlowRow icon="engine" label="ALTERNATOR (DC)" watts={num(data, 'DC Power (W)')} color={colors.accent} />
          <FlowRow icon="home-lightning-bolt" label="AC LOADS" watts={num(data, 'AC Loads (W)')} color={colors.tertiary} />
          <FlowRow icon="battery-charging" label="BATTERY" watts={battW} color={colors.warn} signed />
        </View>
      </Panel>

      <Row>
        <Tile icon="car-battery" label="HOUSE 12V" value={fmt(houseV, 2)} unit="V" color={colors.secondary} bar={houseFill === null ? null : houseFill / 100} sub={`${fmt(num(data, 'Battery0 Current (A)'), 1)} A`} />
        <Tile icon="engine" label="STARTER" value={fmt(starterV, 2)} unit="V" color={colors.tertiary} bar={starterFill === null ? null : starterFill / 100} />
      </Row>
      <Row>
        <Tile icon="battery-high" label="BATTERY 24V" value={fmt(num(data, 'Battery1 Voltage (V)'), 1)} unit="V" color={colors.ok} />
        <Tile icon="current-dc" label="DC CURRENT" value={fmt(num(data, 'DC Current (A)'), 1)} unit="A" color={colors.accent} />
      </Row>
    </ScreenScroll>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 8, marginTop: 6 },
  flowRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  flowHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  flowLabel: { fontFamily: fonts.labelBold, fontSize: 12, letterSpacing: 1.8, color: colors.textDim },
  flowValue: { fontFamily: fonts.display, fontSize: 16 },
  flowUnit: { fontFamily: fonts.labelBold, fontSize: 11, color: colors.textDim },
});
