import React, { useEffect, useRef } from 'react';
import { Animated, Easing, StyleSheet, View } from 'react-native';
import Svg, { Circle, Line, Path, Polygon, Rect, Text as SvgText } from 'react-native-svg';

import { clamp } from '../data/format';
import { colors, fonts } from '../theme';
import { NATIVE_DRIVER } from './ui';

// ---------------------------------------------------------------------------
// TiltGauge: the Attitude tab's roll / pitch gauge - a hull silhouette that
// tilts against a fixed angle scale and waterline, the same drawing as the
// Pi's Attitude page (carpediem/hmi_qt/pages/attitude_page.py).
//
//   roll  = the boat seen from astern; positive = starboard side down, so the
//           hull turns clockwise.
//   pitch = the boat seen from its starboard side, bow to the right; positive
//           = bow up, so the hull turns counter-clockwise.
//
// The hull and the pointer are separate layers (square, centred on the pivot)
// rotated with Animated, so a new reading glides instead of jumping - the
// phone only gets a fresh value every few seconds.
// ---------------------------------------------------------------------------

// Rough "comfortable / uncomfortable / alarming" angles for a displacement
// motor yacht - the same numbers as the Pi's page, not a safety limit.
export const ROLL_LIMITS = { warn: 12, danger: 22 };
export const PITCH_LIMITS = { warn: 6, danger: 12 };

export function severityColor(value: number | null, limits: { warn: number; danger: number }): string {
  if (value === null) return colors.neutral;
  const a = Math.abs(value);
  return a >= limits.danger ? colors.danger : a >= limits.warn ? colors.warn : colors.ok;
}

const W = 260; // drawing space (viewBox units)
const H = 176;
const R = 96; // radius of the angle scale
const HULL = R * 0.62; // unit -> drawing space for the hull silhouettes
const LAYER = R * 2.3; // side of the square rotating layers

const rad = (d: number) => (d * Math.PI) / 180;
// Screen angles: 0 = straight up, increasing clockwise.
const polar = (cx: number, cy: number, r: number, deg: number) => ({
  x: cx + r * Math.sin(rad(deg)),
  y: cy - r * Math.cos(rad(deg)),
});

type Cmd = [string, ...number[]];
// SVG path from unit-hull commands, scaled by HULL.
const hullPath = (cmds: Cmd[]) => cmds.map(([c, ...n]) => `${c} ${n.map((v) => (v * HULL).toFixed(2)).join(' ')}`).join(' ');

const REAR = {
  hull: hullPath([['M', -0.95, -0.25], ['L', 0.95, -0.25], ['L', 0.62, 0.30], ['Q', 0, 0.62, -0.62, 0.30], ['Z']]),
  cabin: hullPath([['M', -0.62, -0.25], ['L', -0.46, -0.72], ['L', 0.46, -0.72], ['L', 0.62, -0.25], ['Z']]),
  mast: hullPath([['M', 0, -0.72], ['L', 0, -1.0]]),
};
const SIDE = {
  hull: hullPath([['M', -1.0, -0.22], ['L', 1.05, -0.38], ['L', 0.80, 0.30], ['L', -0.85, 0.30], ['Z']]),
  cabin: hullPath([['M', -0.55, -0.27], ['L', -0.55, -0.62], ['L', 0.10, -0.62], ['L', 0.40, -0.32], ['Z']]),
  mast: hullPath([['M', -0.15, -0.62], ['L', -0.15, -0.98]]),
};

function useAnimatedDegrees(target: number | null, duration = 900) {
  const anim = useRef(new Animated.Value(target ?? 0)).current;
  useEffect(() => {
    Animated.timing(anim, {
      toValue: target ?? 0, duration, easing: Easing.out(Easing.cubic), useNativeDriver: NATIVE_DRIVER,
    }).start();
  }, [target, anim, duration]);
  return anim.interpolate({ inputRange: [-180, 180], outputRange: ['-180deg', '180deg'] });
}

export function TiltGauge({ kind, angle, width }: { kind: 'roll' | 'pitch'; angle: number | null; width: number }) {
  const isRoll = kind === 'roll';
  const span = isRoll ? 30 : 20; // half-span of the scale, degrees
  const limits = isRoll ? ROLL_LIMITS : PITCH_LIMITS;
  const color = severityColor(angle, limits);
  const cx = isRoll ? W / 2 : 128;
  const cy = isRoll ? 112 : 88;
  const scale = width / W;

  // Scale values run clockwise from "up" for roll; for pitch they're centred on
  // "right" (the bow) and positive values go counter-clockwise (bow up).
  const centreDeg = isRoll ? 0 : 90;
  const sign = isRoll ? 1 : -1;
  const at = (v: number, r: number) => polar(cx, cy, r, centreDeg + sign * v);

  const hullDeg = angle === null ? 0 : clamp(angle, -span * 1.2, span * 1.2) * sign;
  const pointerDeg = angle === null ? 0 : clamp(angle, -span * 1.1, span * 1.1) * sign;
  const hullRotate = useAnimatedDegrees(angle === null ? null : hullDeg);
  const pointerRotate = useAnimatedDegrees(angle === null ? null : pointerDeg);
  const shape = isRoll ? REAR : SIDE;
  const outline = angle === null ? colors.neutral : colors.accent;

  let arc = `M ${at(-span, R).x} ${at(-span, R).y}`;
  for (let v = -span + 1; v <= span; v++) arc += ` L ${at(v, R).x} ${at(v, R).y}`;
  const ticks: React.ReactNode[] = [];
  for (let v = -span; v <= span; v += 5) {
    const major = v % 10 === 0;
    const a = at(v, R);
    const b = at(v, R * (major ? 0.88 : 0.94));
    ticks.push(
      <Line key={`t${v}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
        stroke={v === 0 ? colors.accent : colors.textDim} strokeWidth={major ? 2 : 1} opacity={v === 0 ? 1 : 0.8} />,
    );
    if (major && v !== 0) {
      const p = at(v, R * 0.78);
      ticks.push(
        <SvgText key={`l${v}`} x={p.x} y={p.y + 3.5} fill={colors.textDim} fontSize={10} fontFamily={fonts.label} textAnchor="middle">
          {Math.abs(v)}
        </SvgText>,
      );
    }
  }

  const layer = (children: React.ReactNode, rotate: Animated.AnimatedInterpolation<string>) => (
    <Animated.View
      pointerEvents="none"
      style={{
        position: 'absolute', left: (cx - LAYER / 2) * scale, top: (cy - LAYER / 2) * scale,
        width: LAYER * scale, height: LAYER * scale, transform: [{ rotate }],
      }}
    >
      <Svg width={LAYER * scale} height={LAYER * scale} viewBox={`${-LAYER / 2} ${-LAYER / 2} ${LAYER} ${LAYER}`}>
        {children}
      </Svg>
    </Animated.View>
  );

  return (
    <View
      style={{ width, height: (width * H) / W }}
      accessible
      accessibilityLabel={`${kind} ${angle === null ? 'no reading' : `${angle.toFixed(1)} degrees`}`}
    >
      <Svg width={width} height={(width * H) / W} viewBox={`0 0 ${W} ${H}`} style={StyleSheet.absoluteFill}>
        <Path d={arc} stroke={colors.border} strokeWidth={1.6} fill="none" />
        {ticks}
      </Svg>

      {layer(
        <>
          <Path d={shape.cabin} fill={colors.panelHi} stroke={outline} strokeWidth={2.4} strokeLinejoin="round" />
          <Path d={shape.hull} fill={colors.panelHi} stroke={outline} strokeWidth={2.4} strokeLinejoin="round" />
          <Path d={shape.mast} stroke={outline} strokeWidth={2.4} strokeLinecap="round" />
          {isRoll && (
            <>
              {/* navigation lights seen from astern: red = port (left), green = starboard (right) */}
              <Circle cx={-0.88 * HULL} cy={-0.25 * HULL} r={3.8} fill={angle === null ? colors.neutral : colors.danger} />
              <Circle cx={0.88 * HULL} cy={-0.25 * HULL} r={3.8} fill={angle === null ? colors.neutral : colors.ok} />
            </>
          )}
        </>,
        hullRotate,
      )}

      {angle !== null && layer(
        isRoll
          ? <Polygon points={`0,${-0.9 * R} -5.5,${-1.09 * R} 5.5,${-1.09 * R}`} fill={color} stroke={color} strokeWidth={1.2} />
          : <Polygon points={`${0.9 * R},0 ${1.09 * R},-5.5 ${1.09 * R},5.5`} fill={color} stroke={color} strokeWidth={1.2} />,
        pointerRotate,
      )}

      {/* fixed waterline, with a translucent band below it tinting the submerged part of the hull */}
      <Svg width={width} height={(width * H) / W} viewBox={`0 0 ${W} ${H}`} style={StyleSheet.absoluteFill} pointerEvents="none">
        <Rect x={cx - R * 0.92} y={cy} width={R * 1.84} height={R * 0.5} fill={colors.secondary} opacity={0.16} />
        <Line x1={cx - R * 0.92} y1={cy} x2={cx + R * 0.92} y2={cy} stroke={colors.secondary} strokeWidth={1.4} strokeDasharray="5 4" opacity={0.7} />
      </Svg>
    </View>
  );
}
