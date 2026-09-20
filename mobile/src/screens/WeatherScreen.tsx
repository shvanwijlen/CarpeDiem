import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { WindDial } from '../components/gauges';
import { Chip, Panel, Tile } from '../components/ui';
import { fmt, num } from '../data/format';
import { useCarpe } from '../data/store';
import { colors, fonts } from '../theme';
import { Row, ScreenScroll, tempColor, useCardWidth } from './common';

export function WeatherScreen() {
  const { data } = useCarpe();
  const cardW = useCardWidth();
  const dialSize = Math.min((cardW - 12) / 2 - 12, 170);

  const temp = num(data, 'BresserTemperature');
  const hum = num(data, 'BresserHumidity');
  const avg = num(data, 'BresserWindAverageSpeed');
  const gust = num(data, 'BresserWindGustSpeed');
  const uv = num(data, 'BresserUVindex');
  const light = num(data, 'BresserLightIntensity');
  const tc = tempColor(temp);

  return (
    <ScreenScroll>
      <Panel glow={tc} title="OUTSIDE">
        <View style={styles.heroRow}>
          <Text style={[styles.heroTemp, { textShadowColor: tc }]}>{fmt(temp, 1)}</Text>
          <Text style={[styles.heroUnit, { color: tc }]}>°C</Text>
          <View style={{ flex: 1 }} />
          <View style={{ gap: 8, alignItems: 'flex-end' }}>
            <Chip color={colors.secondary} text="HUMIDITY" count={hum === null ? '--' : `${Math.round(hum)}%`} />
            <Chip color={colors.tertiary} text="GUST" count={gust === null ? '--' : gust.toFixed(0)} />
          </View>
        </View>
      </Panel>

      <Panel glow={colors.secondary} title="WIND">
        <Row>
          <View style={{ flex: 1, alignItems: 'center' }}>
            <WindDial size={dialSize} direction={num(data, 'WindspeedCalculatedAsExperienced')} speed={avg} color={colors.ok} caption="RELATIVE TO COURSE" />
          </View>
          <View style={{ flex: 1, alignItems: 'center' }}>
            <WindDial size={dialSize} direction={num(data, 'BresserWindDirection')} speed={avg} color={colors.tertiary} caption="AS DEVICE REPORTS" />
          </View>
        </Row>
      </Panel>

      <Row>
        <Tile icon="water-percent" label="HUMIDITY" value={fmt(hum, 0)} unit="%" color={colors.secondary} bar={hum === null ? null : hum / 100} />
        <Tile icon="gauge" label="BAROMETER" value={fmt(num(data, 'BME280-Barometer'), 0)} unit="hPa" color={colors.accent} />
      </Row>
      <Row>
        <Tile icon="weather-rainy" label="RAIN (CUM)" value={fmt(num(data, 'BresserRainfall'), 1)} unit="mm" color={colors.secondary} />
        <Tile icon="weather-windy" label="AVG WIND" value={fmt(avg, 1)} unit="km/h" color={colors.ok} bar={avg === null ? null : Math.min(1, avg / 50)} />
      </Row>
      <Row>
        <Tile icon="white-balance-sunny" label="UV INDEX" value={fmt(uv, 1)} color={uv !== null && uv >= 6 ? colors.danger : colors.warn} bar={uv === null ? null : Math.min(1, uv / 11)} />
        <Tile icon="brightness-5" label="LIGHT" value={light === null ? '--' : (light / 1000).toFixed(1)} unit="klx" color={colors.warn} />
      </Row>
    </ScreenScroll>
  );
}

const styles = StyleSheet.create({
  heroRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  heroTemp: {
    fontFamily: fonts.displayBlack, fontSize: 64, color: colors.text,
    textShadowOffset: { width: 0, height: 0 }, textShadowRadius: 18,
  },
  heroUnit: { fontFamily: fonts.display, fontSize: 22, marginTop: -18 },
});
