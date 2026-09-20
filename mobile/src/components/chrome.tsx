import { MaterialCommunityIcons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { LinearGradient } from 'expo-linear-gradient';
import React, { useEffect, useRef, useState } from 'react';
import { Animated, Platform, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import Svg, { Line } from 'react-native-svg';

import { ago } from '../data/format';
import { useCarpe } from '../data/store';
import type { CarpeData, ConnectionStatus } from '../data/types';
import { colors, fonts } from '../theme';
import { IconName, Led, LedState, NATIVE_DRIVER } from './ui';

// --- Backdrop: near-black gradient with a faint HUD grid ---------------------

export function Backdrop() {
  const { width, height } = useWindowDimensions();
  const step = 34;
  const lines = [];
  for (let x = 0; x <= width; x += step) lines.push(<Line key={`v${x}`} x1={x} y1={0} x2={x} y2={height} stroke={colors.secondary} strokeOpacity={0.045} />);
  for (let y = 0; y <= height; y += step) lines.push(<Line key={`h${y}`} x1={0} y1={y} x2={width} y2={y} stroke={colors.secondary} strokeOpacity={0.045} />);
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      <LinearGradient colors={[colors.bgHi, colors.bg, '#02040a']} style={StyleSheet.absoluteFill} />
      <Svg width={width} height={height}>{lines}</Svg>
      <View style={[styles.orb, { top: -120, left: -80, backgroundColor: colors.accent }]} />
      <View style={[styles.orb, { bottom: 60, right: -140, backgroundColor: colors.secondary, opacity: 0.05 }]} />
    </View>
  );
}

// --- Header ------------------------------------------------------------------

const STATUS_LOOK: Record<ConnectionStatus, { text: string; color: string; led: LedState }> = {
  live: { text: 'LIVE', color: colors.ok, led: 'ok' },
  demo: { text: 'DEMO', color: colors.accent, led: 'warn' },
  offline: { text: 'OFFLINE', color: colors.danger, led: 'bad' },
  connecting: { text: 'LINKING', color: colors.secondary, led: 'warn' },
};

export function Header({ title, onSettings }: { title: string; onSettings: () => void }) {
  const { status, lastUpdated } = useCarpe();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 5000);
    return () => clearInterval(id);
  }, []);
  const look = STATUS_LOOK[status];
  const time = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
  return (
    <View style={styles.header}>
      <View style={{ flex: 1 }}>
        <Text style={styles.brand}>CARPE DIEM</Text>
        <Text style={styles.screenTitle}>{title}</Text>
      </View>
      <View style={{ alignItems: 'flex-end', gap: 6 }}>
        <Text style={styles.clock}>{time}</Text>
        <View style={styles.pillRow}>
          <View style={[styles.pill, { borderColor: look.color + '88' }]}>
            <Led state={look.led} size={8} />
            <Text style={[styles.pillText, { color: look.color }]}>{look.text}</Text>
            {status === 'live' && lastUpdated ? <UpdatedAgo since={lastUpdated} /> : null}
          </View>
          <Pressable onPress={onSettings} hitSlop={12} style={styles.gear}>
            <MaterialCommunityIcons name="cog-outline" size={18} color={colors.textDim} />
          </Pressable>
        </View>
      </View>
    </View>
  );
}

function UpdatedAgo({ since }: { since: number }) {
  const [, force] = useState(0);
  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
  return <Text style={styles.pillAgo}>{ago(Date.now() - since)}</Text>;
}

// --- Status strip: same 8 lamps as the Pi's top bar ---------------------------

// [caption, display_data label]. The 8th lamp is the app's own link to the Pi.
const INDICATORS: [string, string | null][] = [
  ['WIFI', 'WiFi'], ['AIS', 'AIS'], ['MQTT', 'MQTT'], ['MDB', 'MODBUS'],
  ['BLE', 'BLE'], ['WX', 'Weather'], ['RING', 'Cam'], ['LINK', null],
];

function ledFor(data: CarpeData, label: string | null, status: ConnectionStatus): LedState {
  if (label === null) return status === 'live' ? 'ok' : status === 'demo' ? 'warn' : 'bad';
  const v = data[label];
  if (v === null || v === undefined) return 'off';
  return v === 1 ? 'ok' : 'bad';
}

export function StatusStrip() {
  const { data, status } = useCarpe();
  return (
    <View style={styles.strip}>
      {INDICATORS.map(([caption, label]) => (
        <View key={caption} style={styles.stripItem}>
          <Led state={ledFor(data, label, status)} size={10} />
          <Text style={styles.stripText}>{caption}</Text>
        </View>
      ))}
    </View>
  );
}

// --- Tab bar -------------------------------------------------------------------

export interface TabDef {
  id: string;
  caption: string;
  icon: IconName;
}

function TabButton({ tab, active, onPress }: { tab: TabDef; active: boolean; onPress: () => void }) {
  const scale = useRef(new Animated.Value(active ? 1 : 0)).current;
  useEffect(() => {
    Animated.spring(scale, { toValue: active ? 1 : 0, friction: 6, tension: 140, useNativeDriver: NATIVE_DRIVER }).start();
  }, [active, scale]);
  const color = active ? colors.accent : colors.textDim;
  return (
    <Pressable
      style={styles.tabPress}
      onPress={() => {
        if (Platform.OS !== 'web') Haptics.selectionAsync().catch(() => {});
        onPress();
      }}
    >
      <Animated.View
        style={[
          styles.tabInner,
          active && styles.tabInnerActive,
          { transform: [{ scale: scale.interpolate({ inputRange: [0, 1], outputRange: [1, 1.06] }) }] },
        ]}
      >
        <MaterialCommunityIcons name={tab.icon} size={active ? 25 : 22} color={color} />
        <Text style={[styles.tabText, { color, fontFamily: active ? fonts.labelBold : fonts.label }]}>{tab.caption}</Text>
      </Animated.View>
    </Pressable>
  );
}

export function TabBar({ tabs, active, onChange, bottomInset }: {
  tabs: TabDef[]; active: string; onChange: (id: string) => void; bottomInset: number;
}) {
  return (
    <View style={[styles.tabBar, { paddingBottom: Math.max(bottomInset, 8) }]}>
      <LinearGradient colors={['#03050900', colors.bg + 'F2', colors.bg]} style={StyleSheet.absoluteFill} />
      <View style={styles.tabRail}>
        {tabs.map((t) => (
          <TabButton key={t.id} tab={t} active={t.id === active} onPress={() => onChange(t.id)} />
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  orb: { position: 'absolute', width: 320, height: 320, borderRadius: 160, opacity: 0.06 },
  header: { flexDirection: 'row', alignItems: 'flex-end', paddingHorizontal: 16, paddingTop: 6, paddingBottom: 8 },
  brand: {
    fontFamily: fonts.displayBlack, fontSize: 22, letterSpacing: 4, color: colors.accent,
    textShadowColor: colors.accent, textShadowOffset: { width: 0, height: 0 }, textShadowRadius: 14,
  },
  screenTitle: { fontFamily: fonts.labelBold, fontSize: 13, letterSpacing: 5, color: colors.textDim, marginTop: 1 },
  clock: {
    fontFamily: fonts.display, fontSize: 24, color: colors.text,
    textShadowColor: colors.secondary, textShadowOffset: { width: 0, height: 0 }, textShadowRadius: 10,
  },
  pillRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  pill: {
    flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 999, borderWidth: 1, backgroundColor: colors.panel,
  },
  pillText: { fontFamily: fonts.labelBold, fontSize: 12, letterSpacing: 2 },
  pillAgo: { fontFamily: fonts.body, fontSize: 11, color: colors.textDim },
  gear: {
    width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.panel,
  },
  strip: {
    flexDirection: 'row', marginHorizontal: 12, paddingVertical: 8, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.panel + 'DD',
  },
  stripItem: { flex: 1, alignItems: 'center', gap: 4 },
  stripText: { fontFamily: fonts.labelBold, fontSize: 9.5, letterSpacing: 1.2, color: colors.textDim },
  tabBar: { position: 'absolute', left: 0, right: 0, bottom: 0, paddingTop: 26, paddingHorizontal: 8 },
  tabRail: {
    flexDirection: 'row', borderRadius: 26, padding: 4, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.panel + 'F5',
    shadowColor: '#000', shadowOpacity: 0.6, shadowRadius: 16, shadowOffset: { width: 0, height: 6 },
  },
  tabPress: { flex: 1 },
  tabInner: { alignItems: 'center', justifyContent: 'center', paddingVertical: 8, borderRadius: 22, gap: 2, borderWidth: 1, borderColor: 'transparent' },
  tabInnerActive: {
    backgroundColor: colors.panelHi, borderColor: colors.accent,
    shadowColor: colors.accent, shadowOpacity: 0.7, shadowRadius: 12, shadowOffset: { width: 0, height: 0 },
  },
  tabText: { fontSize: 10, letterSpacing: 1.4 },
});
