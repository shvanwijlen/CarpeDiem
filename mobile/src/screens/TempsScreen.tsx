import { MaterialCommunityIcons } from '@expo/vector-icons';
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Meter, Panel } from '../components/ui';
import { fmt, num } from '../data/format';
import { useCarpe } from '../data/store';
import type { CarpeData } from '../data/types';
import { colors, fonts } from '../theme';
import { batteryColor, ScreenScroll, tempColor, useCardWidth } from './common';

interface Sensor {
  name: string;
  temp: string;
  humidity?: string;
  battery?: string; // percentage field
  batteryVolts?: string; // Ruuvi tags report volts instead
}

// Teltonika Blue Pucks (BLE) - field names are "<name> Temp|Humidity|Battery".
const puck = (label: string, key = label): Sensor => ({
  name: label, temp: `${key} Temp`, humidity: `${key} Humidity`, battery: `${key} Battery`,
});

const CABIN: Sensor[] = [
  puck('MASTER BEDROOM', 'Master Bedroom'),
  puck('KAJUIT', 'Kajuit'),
  puck('VOORIN', 'Voorin'),
  puck('WASHCABIN', 'P RHT 900F0A'),
  puck('TOILET', 'Toilet'),
];

const TECHNICAL: Sensor[] = [
  puck('ENGINE ROOM', 'Engine Room'),
  puck('WATERTANK SB', 'Watertank SB'),
  puck('WATERTANK PS', 'Watertank PS'),
  { name: 'RUUVI CONSOLE', temp: 'RuuviConsoleTemp', humidity: 'RuuviConsoleHumidity', batteryVolts: 'RuuviConsoleBatteryVoltage' },
  { name: 'RUUVI TANK PS', temp: 'RuuviWatertankPSTemp', humidity: 'RuuviWatertankPSHumidity', batteryVolts: 'RuuviWatertankPSBatteryVoltage' },
  { name: 'ELEC BAY (BME280)', temp: 'sparkfun_elec_bay_temperature', humidity: 'sparkfun_elec_bay_humidity' },
  { name: 'ELEC BAY PROBE', temp: 'Electronics bay (C)' },
  { name: 'ENGINE ROOM PROBE', temp: 'Engine room (C)' },
];

function SensorCard({ s, data, width }: { s: Sensor; data: CarpeData; width: number }) {
  const t = num(data, s.temp);
  const h = s.humidity ? num(data, s.humidity) : null;
  const pct = s.battery ? num(data, s.battery) : null;
  const volts = s.batteryVolts ? num(data, s.batteryVolts) : null;
  const c = tempColor(t);
  return (
    <View style={{ width }}>
      <Panel glow={c} style={{ flex: 1 }}>
        <Text style={styles.name} numberOfLines={1}>{s.name}</Text>
        <View style={styles.tempRow}>
          <Text style={[styles.temp, { textShadowColor: c }]}>{fmt(t, 1)}</Text>
          <Text style={[styles.tempUnit, { color: c }]}>°C</Text>
        </View>
        {s.humidity ? (
          <>
            <View style={styles.humRow}>
              <MaterialCommunityIcons name="water-percent" size={16} color={colors.secondary} />
              <Text style={styles.humText}>{h === null ? '--' : `${Math.round(h)}%`}</Text>
            </View>
            <Meter value={h === null ? null : h / 100} color={colors.secondary} height={4} />
          </>
        ) : null}
        {pct !== null || volts !== null ? (
          <View style={styles.batt}>
            <MaterialCommunityIcons name={pct !== null && pct < 20 ? 'battery-10' : 'battery-70'} size={14} color={batteryColor(pct ?? (volts! > 2.7 ? 80 : 15))} />
            <Text style={styles.battText}>{pct !== null ? `${Math.round(pct)}%` : `${volts!.toFixed(2)} V`}</Text>
          </View>
        ) : null}
      </Panel>
    </View>
  );
}

function Group({ title, sensors, data, cardW }: { title: string; sensors: Sensor[]; data: CarpeData; cardW: number }) {
  const w = (cardW - 12) / 2;
  return (
    <View style={{ gap: 10 }}>
      <View style={styles.groupHead}>
        <View style={styles.groupBar} />
        <Text style={styles.groupTitle}>{title}</Text>
      </View>
      <View style={styles.grid}>
        {sensors.map((s) => <SensorCard key={s.name} s={s} data={data} width={w} />)}
      </View>
    </View>
  );
}

export function TempsScreen() {
  const { data } = useCarpe();
  const cardW = useCardWidth();
  return (
    <ScreenScroll>
      <Group title="CABIN" sensors={CABIN} data={data} cardW={cardW} />
      <Group title="TECHNICAL" sensors={TECHNICAL} data={data} cardW={cardW} />
    </ScreenScroll>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  groupHead: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 2 },
  groupBar: { width: 4, height: 16, borderRadius: 2, backgroundColor: colors.accent },
  groupTitle: { fontFamily: fonts.displayMedium, fontSize: 13, letterSpacing: 3, color: colors.text },
  name: { fontFamily: fonts.labelBold, fontSize: 11.5, letterSpacing: 1.6, color: colors.textDim },
  tempRow: { flexDirection: 'row', alignItems: 'baseline', gap: 3, marginTop: 4 },
  temp: {
    fontFamily: fonts.displayBlack, fontSize: 28, color: colors.text,
    textShadowOffset: { width: 0, height: 0 }, textShadowRadius: 10,
  },
  tempUnit: { fontFamily: fonts.display, fontSize: 12 },
  humRow: { flexDirection: 'row', alignItems: 'center', gap: 2, marginTop: 6 },
  humText: { fontFamily: fonts.display, fontSize: 13, color: colors.text },
  batt: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 8 },
  battText: { fontFamily: fonts.label, fontSize: 12, color: colors.textDim },
});
