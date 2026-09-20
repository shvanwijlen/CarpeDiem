import { MaterialCommunityIcons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import React, { useEffect, useRef } from 'react';
import { Animated, Easing, Platform, StyleProp, StyleSheet, Text, View, ViewStyle } from 'react-native';

import { colors, fonts, radius } from '../theme';

export const NATIVE_DRIVER = Platform.OS !== 'web';

export type IconName = React.ComponentProps<typeof MaterialCommunityIcons>['name'];

// --- Panel: gradient card with a hairline border and optional neon glow -----

export function Panel({
  children, style, glow, title, right, padded = true,
}: {
  children?: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  glow?: string;
  title?: string;
  right?: React.ReactNode;
  padded?: boolean;
}) {
  return (
    <View
      style={[
        styles.panelOuter,
        glow ? { shadowColor: glow, shadowOpacity: 0.55, shadowRadius: 16, shadowOffset: { width: 0, height: 0 } } : null,
        style,
      ]}
    >
      <View style={[styles.panelInner, glow ? { borderColor: glow + '88' } : null]}>
        <LinearGradient colors={[colors.panelHi, colors.panel]} style={StyleSheet.absoluteFill} />
        {title ? (
          <View style={styles.titleRow}>
            <View style={[styles.titleBar, glow ? { backgroundColor: glow } : null]} />
            <Text style={styles.titleText}>{title}</Text>
            <View style={{ flex: 1 }} />
            {right}
          </View>
        ) : null}
        <View style={padded ? styles.padded : null}>{children}</View>
      </View>
    </View>
  );
}

// --- Led: status lamp with a soft pulsing halo -----------------------------

export type LedState = 'ok' | 'warn' | 'bad' | 'off';

const LED_COLOR: Record<LedState, string> = {
  ok: colors.ok, warn: colors.warn, bad: colors.danger, off: colors.neutral,
};

export function Led({ state, size = 12 }: { state: LedState; size?: number }) {
  const pulse = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (state === 'off') return;
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: state === 'bad' ? 450 : 1400, easing: Easing.inOut(Easing.quad), useNativeDriver: NATIVE_DRIVER }),
        Animated.timing(pulse, { toValue: 0, duration: state === 'bad' ? 450 : 1400, easing: Easing.inOut(Easing.quad), useNativeDriver: NATIVE_DRIVER }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [state, pulse]);

  const c = LED_COLOR[state];
  const halo = size * 2.2;
  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
      {state !== 'off' && (
        <Animated.View
          style={{
            position: 'absolute', width: halo, height: halo, borderRadius: halo / 2, backgroundColor: c,
            opacity: pulse.interpolate({ inputRange: [0, 1], outputRange: [0.05, 0.32] }),
          }}
        />
      )}
      <View
        style={{
          width: size, height: size, borderRadius: size / 2, backgroundColor: c,
          opacity: state === 'off' ? 0.35 : 1,
          shadowColor: c, shadowOpacity: state === 'off' ? 0 : 0.9, shadowRadius: 6, shadowOffset: { width: 0, height: 0 },
        }}
      />
    </View>
  );
}

// --- Tile: icon + caption + big number, optional level bar -----------------

export function Tile({
  icon, label, value, unit, color = colors.secondary, sub, bar, style,
}: {
  icon: IconName;
  label: string;
  value: string;
  unit?: string;
  color?: string;
  sub?: string;
  bar?: number | null; // 0..1
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <Panel style={[{ flex: 1 }, style]} glow={color}>
      <View style={styles.tileHead}>
        <MaterialCommunityIcons name={icon} size={16} color={color} />
        <Text style={[styles.tileLabel, { color: colors.textDim }]} numberOfLines={1}>{label}</Text>
      </View>
      <View style={styles.tileValueRow}>
        <Text style={[styles.tileValue, { color: colors.text, textShadowColor: color }]} numberOfLines={1} adjustsFontSizeToFit>
          {value}
        </Text>
        {unit ? <Text style={[styles.tileUnit, { color }]}>{unit}</Text> : null}
      </View>
      {sub ? <Text style={styles.tileSub} numberOfLines={1}>{sub}</Text> : null}
      {bar !== undefined ? <Meter value={bar} color={color} /> : null}
    </Panel>
  );
}

// --- Meter: thin glowing level bar -----------------------------------------

export function Meter({ value, color, height = 6 }: { value: number | null; color: string; height?: number }) {
  const pct = value === null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  return (
    <View style={{ height, borderRadius: height / 2, backgroundColor: '#ffffff12', marginTop: 8, overflow: 'visible' }}>
      <View
        style={{
          width: `${pct}%`, height, borderRadius: height / 2, backgroundColor: color,
          shadowColor: color, shadowOpacity: 0.9, shadowRadius: 6, shadowOffset: { width: 0, height: 0 },
        }}
      />
    </View>
  );
}

// --- Chip: small legend/pill ------------------------------------------------

export function Chip({ color, text, count }: { color: string; text: string; count?: number | string }) {
  return (
    <View style={[styles.chip, { borderColor: color + '66' }]}>
      <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: color, shadowColor: color, shadowOpacity: 1, shadowRadius: 4, shadowOffset: { width: 0, height: 0 } }} />
      <Text style={styles.chipText}>{text}</Text>
      {count !== undefined ? <Text style={[styles.chipCount, { color }]}>{count}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  panelOuter: { borderRadius: radius.card, backgroundColor: colors.panel },
  panelInner: { borderRadius: radius.card, borderWidth: 1, borderColor: colors.border, overflow: 'hidden', flexGrow: 1 },
  padded: { padding: 12 },
  titleRow: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 12, paddingTop: 10, gap: 8 },
  titleBar: { width: 4, height: 14, borderRadius: 2, backgroundColor: colors.accent },
  titleText: { fontFamily: fonts.labelBold, fontSize: 13, letterSpacing: 2.2, color: colors.textDim },
  tileHead: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  tileLabel: { fontFamily: fonts.labelBold, fontSize: 12, letterSpacing: 1.6, flexShrink: 1 },
  tileValueRow: { flexDirection: 'row', alignItems: 'baseline', gap: 5, marginTop: 4 },
  tileValue: {
    fontFamily: fonts.display, fontSize: 24, flexShrink: 1,
    textShadowOffset: { width: 0, height: 0 }, textShadowRadius: 10,
  },
  tileUnit: { fontFamily: fonts.labelBold, fontSize: 13, letterSpacing: 1 },
  tileSub: { fontFamily: fonts.body, fontSize: 12, color: colors.textDim, marginTop: 2, letterSpacing: 0.5 },
  chip: {
    flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: 999, borderWidth: 1, backgroundColor: colors.panel,
  },
  chipText: { fontFamily: fonts.labelBold, fontSize: 11, letterSpacing: 1.4, color: colors.textDim },
  chipCount: { fontFamily: fonts.display, fontSize: 12 },
});
