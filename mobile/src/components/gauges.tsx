import * as Haptics from 'expo-haptics';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Easing, GestureResponderEvent, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, G, Line, Path, Polygon, Text as SvgText } from 'react-native-svg';

import { compassName, norm360 } from '../data/format';
import type { Vessel } from '../data/types';
import { colors, fonts } from '../theme';
import { blipPosition, nearestVessel } from './radarGeometry';
import { NATIVE_DRIVER } from './ui';

const rad = (d: number) => (d * Math.PI) / 180;
// Compass convention: 0 = up, increasing clockwise.
const polar = (cx: number, cy: number, r: number, deg: number) => ({
  x: cx + r * Math.sin(rad(deg)),
  y: cy - r * Math.cos(rad(deg)),
});
function arcPath(cx: number, cy: number, r: number, startDeg: number, endDeg: number): string {
  const end = Math.min(endDeg, startDeg + 359.9);
  const s = polar(cx, cy, r, startDeg);
  const e = polar(cx, cy, r, end);
  return `M ${s.x} ${s.y} A ${r} ${r} 0 ${end - startDeg > 180 ? 1 : 0} 1 ${e.x} ${e.y}`;
}

const abs = StyleSheet.absoluteFill;

// Rotates smoothly to `target` degrees the short way round (359 -> 1 is a
// 2 degree turn, not 358), returning a value to feed into `rotate`.
function useSmoothRotation(target: number | null, sign: 1 | -1, duration = 900) {
  const anim = useRef(new Animated.Value(0)).current;
  const cumulative = useRef(0);
  const previous = useRef<number | null>(null);
  useEffect(() => {
    if (target === null) return;
    if (previous.current === null) {
      cumulative.current = target;
      anim.setValue(sign * target);
    } else {
      const delta = ((target - previous.current + 540) % 360) - 180;
      cumulative.current += delta;
      Animated.timing(anim, {
        toValue: sign * cumulative.current, duration, easing: Easing.out(Easing.cubic), useNativeDriver: NATIVE_DRIVER,
      }).start();
    }
    previous.current = target;
  }, [target, anim, sign, duration]);
  return anim.interpolate({ inputRange: [0, 360], outputRange: ['0deg', '360deg'] });
}

// ---------------------------------------------------------------------------
// Compass: heading-up compass card (like a game HUD). The dial rotates so the
// boat's course is always at the top; true wind sits on the rotating dial (it
// has a compass bearing), while wind-relative-to-bow rides an inner fixed ring.
// ---------------------------------------------------------------------------

export function Compass({
  size, course, speed, trueWind, relWind,
}: {
  size: number;
  course: number | null;
  speed: number | null;
  trueWind: number | null;
  relWind: number | null;
}) {
  const rotate = useSmoothRotation(course, -1);
  const S = 300;
  const C = 150;

  const dial = useMemo(() => {
    const ticks: React.ReactNode[] = [];
    for (let deg = 0; deg < 360; deg += 5) {
      const major = deg % 30 === 0;
      const medium = deg % 10 === 0;
      const len = major ? 15 : medium ? 9 : 5;
      const a = polar(C, C, 136, deg);
      const b = polar(C, C, 136 - len, deg);
      ticks.push(
        <Line key={deg} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
          stroke={major ? colors.text : colors.textDim} strokeWidth={major ? 2.2 : 1} opacity={major ? 0.95 : 0.6} />,
      );
    }
    const labels: React.ReactNode[] = [];
    for (let deg = 0; deg < 360; deg += 30) {
      const cardinal = deg % 90 === 0;
      const p = polar(C, C, cardinal ? 104 : 108, deg);
      const text = cardinal ? ['N', 'E', 'S', 'W'][deg / 90] : String(deg);
      labels.push(
        <SvgText key={deg} x={p.x} y={p.y + (cardinal ? 7 : 3.5)} rotation={deg} origin={`${p.x}, ${p.y}`}
          fill={deg === 0 ? colors.accent : cardinal ? colors.text : colors.textDim}
          fontSize={cardinal ? 22 : 10} fontFamily={fonts.display} textAnchor="middle">
          {text}
        </SvgText>,
      );
    }
    return { ticks, labels };
  }, []);

  const centerText = speed === null ? '--' : speed.toFixed(1);
  return (
    <View style={{ width: size, height: size }}>
      {/* Static neon rings */}
      <Svg width={size} height={size} viewBox={`0 0 ${S} ${S}`} style={abs}>
        <Circle cx={C} cy={C} r={143} stroke={colors.accent} strokeWidth={9} opacity={0.07} fill="none" />
        <Circle cx={C} cy={C} r={141} stroke={colors.accent} strokeWidth={4} opacity={0.16} fill="none" />
        <Circle cx={C} cy={C} r={140} stroke={colors.accent} strokeWidth={1.5} opacity={0.9} fill="none" />
        <Circle cx={C} cy={C} r={84} stroke={colors.secondary} strokeWidth={1} strokeDasharray="3 5" opacity={0.55} fill="none" />
        <Circle cx={C} cy={C} r={70} stroke={colors.border} strokeWidth={1} opacity={0.5} fill="none" />
      </Svg>

      {/* Rotating card */}
      <Animated.View style={[abs, { transform: [{ rotate }] }]}>
        <Svg width={size} height={size} viewBox={`0 0 ${S} ${S}`}>
          {dial.ticks}
          {dial.labels}
          {trueWind !== null && (
            <G rotation={trueWind} origin={`${C}, ${C}`}>
              <Polygon points="138,4 162,4 150,30" fill={colors.tertiary} opacity={0.18} stroke={colors.tertiary} strokeWidth={8} strokeOpacity={0.15} />
              <Polygon points="141,6 159,6 150,26" fill={colors.tertiary} stroke={colors.tertiary} strokeWidth={1.5} />
            </G>
          )}
        </Svg>
      </Animated.View>

      {/* Fixed overlay: lubber line (heading) + wind relative to bow */}
      <Svg width={size} height={size} viewBox={`0 0 ${S} ${S}`} style={abs}>
        <Polygon points="136,-2 164,-2 150,22" fill={colors.secondary} opacity={0.2} stroke={colors.secondary} strokeWidth={8} strokeOpacity={0.18} />
        <Polygon points="141,0 159,0 150,17" fill={colors.secondary} stroke={colors.secondary} strokeWidth={1.5} />
        {relWind !== null && (
          <G rotation={relWind} origin={`${C}, ${C}`}>
            <Polygon points="141,40 159,40 150,62" fill={colors.ok} opacity={0.2} stroke={colors.ok} strokeWidth={7} strokeOpacity={0.18} />
            <Polygon points="143,44 157,44 150,60" fill={colors.ok} stroke={colors.ok} strokeWidth={1.5} />
          </G>
        )}
      </Svg>

      <View style={[abs, styles.center]} pointerEvents="none">
        <Text style={[styles.speed, { fontSize: size * 0.17 }]}>{centerText}</Text>
        <Text style={[styles.unit, { fontSize: size * 0.045 }]}>KM/H</Text>
        <View style={styles.courseChip}>
          <Text style={[styles.courseText, { fontSize: size * 0.05 }]}>
            {course === null ? '--' : `${Math.round(norm360(course))}°`} {compassName(course)}
          </Text>
        </View>
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// RadialGauge: 270 degree arc with glow, end cap and lit tick marks.
// ---------------------------------------------------------------------------

export function RadialGauge({
  size, value, color, valueText, subText,
}: {
  size: number;
  value: number | null; // 0..100
  color?: string;
  valueText: string;
  subText: string;
}) {
  const S = 200;
  const C = 100;
  const r = 76;
  const start = 225;
  const sweep = 270;
  const frac = value === null ? 0 : Math.max(0, Math.min(1, value / 100));
  const tint = color ?? (value === null ? colors.neutral : value > 50 ? colors.ok : value > 25 ? colors.warn : colors.danger);
  const endDeg = start + sweep * frac;
  const end = polar(C, C, r, endDeg);

  const ticks = [];
  for (let i = 0; i <= 10; i++) {
    const a = start + (sweep * i) / 10;
    const p1 = polar(C, C, r + 13, a);
    const p2 = polar(C, C, r + 19, a);
    ticks.push(
      <Line key={i} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke={i / 10 <= frac ? tint : colors.textDim}
        strokeWidth={i % 5 === 0 ? 2.4 : 1.4} opacity={i / 10 <= frac ? 1 : 0.5} />,
    );
  }

  return (
    <View style={{ width: size, height: size }}>
      <Svg width={size} height={size} viewBox={`0 0 ${S} ${S}`}>
        <Path d={arcPath(C, C, r, start, start + sweep)} stroke="#ffffff12" strokeWidth={15} strokeLinecap="round" fill="none" />
        {frac > 0 && (
          <>
            <Path d={arcPath(C, C, r, start, endDeg)} stroke={tint} strokeWidth={30} strokeLinecap="round" fill="none" opacity={0.09} />
            <Path d={arcPath(C, C, r, start, endDeg)} stroke={tint} strokeWidth={22} strokeLinecap="round" fill="none" opacity={0.16} />
            <Path d={arcPath(C, C, r, start, endDeg)} stroke={tint} strokeWidth={15} strokeLinecap="round" fill="none" />
            <Circle cx={end.x} cy={end.y} r={4.5} fill="#fff" opacity={0.95} />
          </>
        )}
        {ticks}
      </Svg>
      <View style={[abs, styles.center]} pointerEvents="none">
        <Text style={[styles.gaugeValue, { fontSize: size * 0.2, textShadowColor: tint }]}>{valueText}</Text>
        <Text style={[styles.gaugeSub, { fontSize: size * 0.065, color: tint }]}>{subText}</Text>
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Radar: bow-up AIS plot (deliberately static - a sweeping beam was tried and
// found distracting).
// ---------------------------------------------------------------------------

const CATEGORY_COLOR: Record<Vessel['category'], string> = {
  overtaking: colors.danger,
  fast: colors.warn,
  ok: colors.ok,
  moored: colors.neutral,
};

export function Radar({ size, maxKm, vessels }: { size: number; maxKm: number; vessels: Vessel[] }) {
  const S = 300;
  const C = 150;
  const R = 138;
  const inRange = vessels.filter((v) => v.distance_km <= maxKm);

  // Selection is tracked by MMSI, not by the vessel object: the parent hands
  // us a freshly built list on every data refresh, so a stored object would
  // stop matching within a second - same reasoning as the Pi's RadarView.
  const [selectedMmsi, setSelectedMmsi] = useState<number | null>(null);
  const selected = inRange.find((v) => v.mmsi === selectedMmsi) ?? null;
  const onTap = (e: GestureResponderEvent) => {
    // iOS/Android give locationX/Y; on web the press carries a browser
    // MouseEvent, which has offsetX/Y (both relative to this full-size layer).
    const ne = e.nativeEvent as { locationX?: number; locationY?: number; offsetX?: number; offsetY?: number };
    const x = ne.locationX ?? ne.offsetX;
    const y = ne.locationY ?? ne.offsetY;
    if (x === undefined || y === undefined) return;
    const hit = nearestVessel(inRange, maxKm, size, x, y);
    setSelectedMmsi(hit ? hit.mmsi : null); // tapping empty space closes the popup
    if (hit && Platform.OS !== 'web') Haptics.selectionAsync().catch(() => {});
  };

  return (
    <View style={{ width: size, height: size }}>
      <Svg width={size} height={size} viewBox={`0 0 ${S} ${S}`} style={abs}>
        <Circle cx={C} cy={C} r={R} fill="#03110a" opacity={0.75} />
        {[1, 2, 3].map((i) => (
          <Circle key={i} cx={C} cy={C} r={(R * i) / 3} stroke={colors.ok} strokeOpacity={i === 3 ? 0.7 : 0.3} strokeWidth={i === 3 ? 1.6 : 1} fill="none" />
        ))}
        <Line x1={C} y1={C - R} x2={C} y2={C + R} stroke={colors.ok} strokeOpacity={0.25} />
        <Line x1={C - R} y1={C} x2={C + R} y2={C} stroke={colors.ok} strokeOpacity={0.25} />
        {[1, 2, 3].map((i) => {
          const p = polar(C, C, (R * i) / 3, 45);
          return (
            <SvgText key={i} x={p.x + 3} y={p.y - 2} fill={colors.ok} opacity={0.75} fontSize={9} fontFamily={fonts.label}>
              {`${((maxKm * i) / 3).toFixed(1)}km`}
            </SvgText>
          );
        })}
      </Svg>

      <Svg width={size} height={size} viewBox={`0 0 ${S} ${S}`} style={abs}>
        {inRange.map((v) => {
          const p = polar(C, C, (v.distance_km / maxKm) * R, v.bearing_deg);
          const c = CATEGORY_COLOR[v.category];
          const moored = v.category === 'moored';
          const head = moored ? null : polar(p.x, p.y, 13, v.heading_deg);
          return (
            <G key={v.mmsi}>
              {head && <Line x1={p.x} y1={p.y} x2={head.x} y2={head.y} stroke={c} strokeWidth={1.6} opacity={0.9} />}
              {v.category === 'overtaking' && <Circle cx={p.x} cy={p.y} r={10} stroke={c} strokeWidth={1.4} fill="none" opacity={0.7} />}
              <Circle cx={p.x} cy={p.y} r={moored ? 6 : 9} fill={c} opacity={0.18} />
              <Circle cx={p.x} cy={p.y} r={moored ? 2.6 : 4.2} fill={c} />
            </G>
          );
        })}
        {selected && (() => {
          const p = blipPosition(selected, maxKm, S);
          return (
            <>
              <Circle cx={p.x} cy={p.y} r={17} stroke="#fff" strokeWidth={1.6} fill="none" opacity={0.9} />
              <Circle cx={p.x} cy={p.y} r={21} stroke={CATEGORY_COLOR[selected.category]} strokeWidth={5} fill="none" opacity={0.25} />
            </>
          );
        })()}
        {/* Own ship */}
        <Polygon points={`${C},${C - 9} ${C - 6},${C + 6} ${C + 6},${C + 6}`} fill={colors.secondary} stroke="#fff" strokeWidth={0.8} />
        <Circle cx={C} cy={C} r={R} stroke={colors.ok} strokeWidth={5} strokeOpacity={0.08} fill="none" />
      </Svg>

      <Pressable style={abs} onPress={onTap} accessibilityLabel="Radar - tap a vessel for details" />
      {selected ? <VesselPopup vessel={selected} maxKm={maxKm} size={size} /> : null}
    </View>
  );
}

// Same content as the Pi's radar popup (hmi_qt/widgets.py _draw_vessel_popup):
// name or MMSI, speed, the vessel's own heading and its bearing relative to
// our course. A near-stationary vessel has no real heading, so it shows
// "--" rather than a misleading 0.
const POPUP_W = 214;
const POPUP_H = 104;

function VesselPopup({ vessel, maxKm, size }: { vessel: Vessel; maxKm: number; size: number }) {
  const p = blipPosition(vessel, maxKm, size);
  const color = CATEGORY_COLOR[vessel.category];
  const moored = vessel.category === 'moored';
  let left = p.x + 20;
  if (left + POPUP_W > size - 4) left = p.x - 20 - POPUP_W;
  left = Math.max(4, Math.min(left, size - POPUP_W - 4));
  let top = p.y - POPUP_H - 12;
  if (top < 4) top = p.y + 16;
  top = Math.max(4, Math.min(top, size - POPUP_H - 4));

  const title = vessel.name ?? `MMSI ${vessel.mmsi}`;
  const speed = vessel.speed_knots === null ? '--' : vessel.speed_knots.toFixed(1);
  const heading = moored ? '--' : `${Math.round(norm360(vessel.heading_deg))}`;
  const bearing = `${vessel.bearing_deg >= 0 ? '+' : ''}${Math.round(vessel.bearing_deg)}`;

  return (
    <View pointerEvents="none" style={[styles.popup, { left, top, width: POPUP_W, height: POPUP_H, borderColor: color + 'AA', shadowColor: color }]}>
      <View style={[styles.popupBar, { backgroundColor: color }]} />
      <View style={{ flex: 1, paddingLeft: 10 }}>
        <Text style={styles.popupTitle} numberOfLines={1}>{title}</Text>
        <Text style={styles.popupLine}>SPEED <Text style={styles.popupVal}>{speed} kn</Text>   HDG <Text style={styles.popupVal}>{heading}°</Text></Text>
        <Text style={styles.popupLine}>BRG <Text style={styles.popupVal}>{bearing}°</Text> <Text style={styles.popupDim}>rel. to your course</Text></Text>
        <Text style={styles.popupLine}>DIST <Text style={styles.popupVal}>{vessel.distance_km.toFixed(2)} km</Text></Text>
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// WindDial: small dial with an arrow showing where the wind comes FROM.
// ---------------------------------------------------------------------------

export function WindDial({
  size, direction, speed, color, caption,
}: {
  size: number;
  direction: number | null;
  speed: number | null;
  color: string;
  caption: string;
}) {
  const S = 200;
  const C = 100;
  const ticks = [];
  for (let deg = 0; deg < 360; deg += 15) {
    const major = deg % 90 === 0;
    const a = polar(C, C, 92, deg);
    const b = polar(C, C, major ? 78 : 85, deg);
    ticks.push(<Line key={deg} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={major ? colors.text : colors.textDim} strokeWidth={major ? 2 : 1} opacity={major ? 0.9 : 0.55} />);
  }
  return (
    <View style={{ alignItems: 'center' }}>
      <View style={{ width: size, height: size }}>
        <Svg width={size} height={size} viewBox={`0 0 ${S} ${S}`}>
          <Circle cx={C} cy={C} r={97} stroke={color} strokeWidth={8} opacity={0.08} fill="none" />
          <Circle cx={C} cy={C} r={95} stroke={color} strokeWidth={1.4} opacity={0.85} fill="none" />
          {ticks}
          <SvgText x={C} y={30} fill={colors.accent} fontSize={13} fontFamily={fonts.display} textAnchor="middle">N</SvgText>
          {direction !== null && (
            <G rotation={direction} origin={`${C}, ${C}`}>
              <Polygon points="88,8 112,8 100,40" fill={color} opacity={0.2} stroke={color} strokeWidth={8} strokeOpacity={0.15} />
              <Polygon points="91,10 109,10 100,36" fill={color} stroke={color} strokeWidth={1.5} />
              <Line x1={C} y1={36} x2={C} y2={62} stroke={color} strokeWidth={2} opacity={0.6} strokeDasharray="2 4" />
            </G>
          )}
        </Svg>
        <View style={[abs, styles.center]} pointerEvents="none">
          <Text style={[styles.windSpeed, { fontSize: size * 0.2 }]}>{speed === null ? '--' : speed.toFixed(1)}</Text>
          <Text style={[styles.unit, { fontSize: size * 0.06 }]}>KM/H</Text>
          <Text style={[styles.windDeg, { fontSize: size * 0.075, color }]}>
            {direction === null ? '--' : `${Math.round(norm360(direction))}° ${compassName(direction)}`}
          </Text>
        </View>
      </View>
      <Text style={[styles.windCaption, { color }]}>{caption}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  popup: {
    position: 'absolute', flexDirection: 'row', alignItems: 'center', paddingVertical: 8, paddingRight: 10, paddingLeft: 8,
    borderRadius: 12, borderWidth: 1, backgroundColor: '#050B14F2',
    shadowOpacity: 0.7, shadowRadius: 12, shadowOffset: { width: 0, height: 0 },
  },
  popupBar: { width: 4, alignSelf: 'stretch', borderRadius: 2 },
  popupTitle: { fontFamily: fonts.display, fontSize: 14, color: colors.text, letterSpacing: 0.6, marginBottom: 3 },
  popupLine: { fontFamily: fonts.labelBold, fontSize: 11.5, letterSpacing: 1.2, color: colors.textDim, marginTop: 1 },
  popupVal: { fontFamily: fonts.display, fontSize: 12, color: colors.text, letterSpacing: 0.4 },
  popupDim: { fontFamily: fonts.body, fontSize: 11, letterSpacing: 0.3, color: colors.textDim },
  center: { alignItems: 'center', justifyContent: 'center' },
  speed: {
    fontFamily: fonts.displayBlack, color: colors.text,
    textShadowColor: colors.accent, textShadowOffset: { width: 0, height: 0 }, textShadowRadius: 14,
  },
  unit: { fontFamily: fonts.labelBold, color: colors.textDim, letterSpacing: 3, marginTop: -2 },
  courseChip: {
    marginTop: 6, paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999,
    borderWidth: 1, borderColor: colors.secondary + '99', backgroundColor: '#66CCFF14',
  },
  courseText: { fontFamily: fonts.display, color: colors.secondary, letterSpacing: 1 },
  gaugeValue: {
    fontFamily: fonts.displayBlack, color: colors.text,
    textShadowOffset: { width: 0, height: 0 }, textShadowRadius: 12,
  },
  gaugeSub: { fontFamily: fonts.labelBold, letterSpacing: 3, marginTop: 0 },
  windSpeed: {
    fontFamily: fonts.displayBlack, color: colors.text,
    textShadowColor: colors.secondary, textShadowOffset: { width: 0, height: 0 }, textShadowRadius: 10,
  },
  windDeg: { fontFamily: fonts.display, marginTop: 2 },
  windCaption: { fontFamily: fonts.labelBold, letterSpacing: 2, fontSize: 12, marginTop: 6 },
});
