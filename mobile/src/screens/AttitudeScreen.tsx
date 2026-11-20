import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { PITCH_LIMITS, ROLL_LIMITS, severityColor, TiltGauge } from '../components/tilt';
import { Chip, Panel } from '../components/ui';
import { num } from '../data/format';
import { useCarpe } from '../data/store';
import { colors, fonts } from '../theme';
import { Row, ScreenScroll, useCardWidth } from './common';

// Roll positive = starboard side down, pitch positive = bow up (the Pi's sign
// convention - see carpediem/sensors/bno055_sensor.py).
function Readout({ value, positive, negative, color }: { value: number | null; positive: string; negative: string; color: string }) {
  const word = value === null ? '' : Math.abs(value) < 0.05 ? 'LEVEL' : value > 0 ? positive : negative;
  return (
    <View style={styles.readout}>
      <Text style={[styles.number, { textShadowColor: color }]}>{value === null ? '--' : `${Math.abs(value).toFixed(1)}°`}</Text>
      <Text style={[styles.word, { color: value === null ? colors.textDim : color }]}>{word}</Text>
    </View>
  );
}

export function AttitudeScreen() {
  const { data } = useCarpe();
  const cardW = useCardWidth();
  const roll = num(data, 'Roll');
  const pitch = num(data, 'Pitch');
  const cal = num(data, 'ImuCalibration');
  const gaugeW = Math.min(cardW - 24, 360);
  const rollColor = severityColor(roll, ROLL_LIMITS);
  const pitchColor = severityColor(pitch, PITCH_LIMITS);

  // The Pi blanks Roll/Pitch when there's no sensor or no valid reading.
  const noSensor = roll === null && pitch === null;

  return (
    <ScreenScroll>
      <Row>
        {noSensor
          ? <Chip color={colors.warn} text="NO SENSOR READING" />
          : <Chip color={cal !== null && cal >= 3 ? colors.ok : colors.warn} text="IMU CALIBRATION" count={cal === null ? '--' : `${cal}/3`} />}
      </Row>

      <Panel glow={rollColor} title="ROLL" right={<Text style={styles.sub}>VIEW FROM ASTERN</Text>}>
        <View style={styles.center}>
          <TiltGauge kind="roll" angle={roll} width={gaugeW} />
          <Readout value={roll} positive="STARBOARD" negative="PORT" color={rollColor} />
        </View>
      </Panel>

      <Panel glow={pitchColor} title="PITCH" right={<Text style={styles.sub}>VIEW FROM STARBOARD</Text>}>
        <View style={styles.center}>
          <TiltGauge kind="pitch" angle={pitch} width={gaugeW} />
          <Readout value={pitch} positive="BOW UP" negative="BOW DOWN" color={pitchColor} />
        </View>
      </Panel>

      <Text style={styles.note}>Latest reading the boat sent to the store - it updates every few seconds, so it shows heel and trim, not the individual waves.</Text>
    </ScreenScroll>
  );
}

const styles = StyleSheet.create({
  center: { alignItems: 'center', gap: 4 },
  sub: { fontFamily: fonts.label, fontSize: 11, letterSpacing: 1.6, color: colors.textDim, paddingRight: 2 },
  readout: { alignItems: 'center' },
  number: {
    fontFamily: fonts.displayBlack, fontSize: 46, color: colors.text,
    textShadowOffset: { width: 0, height: 0 }, textShadowRadius: 14,
  },
  word: { fontFamily: fonts.labelBold, fontSize: 15, letterSpacing: 4, marginTop: -2 },
  note: { fontFamily: fonts.body, fontSize: 12, letterSpacing: 0.4, color: colors.textDim, textAlign: 'center', paddingHorizontal: 12 },
});
