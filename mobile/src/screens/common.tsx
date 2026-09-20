import React from 'react';
import { ScrollView, StyleSheet, useWindowDimensions, View } from 'react-native';

import { colors } from '../theme';

export const MAX_CONTENT_WIDTH = 560;

export function ScreenScroll({ children }: { children: React.ReactNode }) {
  return (
    <ScrollView
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
      style={StyleSheet.absoluteFill}
    >
      {children}
    </ScrollView>
  );
}

/** Usable width of a full-width card (screen minus the 16px side padding). */
export function useCardWidth(): number {
  const { width } = useWindowDimensions();
  return Math.min(width, MAX_CONTENT_WIDTH) - 32;
}

export function Row({ children, gap = 12 }: { children: React.ReactNode; gap?: number }) {
  return <View style={{ flexDirection: 'row', gap }}>{children}</View>;
}

export function tempColor(t: number | null): string {
  if (t === null) return colors.neutral;
  if (t < 10) return colors.secondary;
  if (t < 24) return colors.ok;
  if (t < 30) return colors.warn;
  return colors.danger;
}

export function batteryColor(pct: number | null): string {
  if (pct === null) return colors.neutral;
  return pct > 50 ? colors.ok : pct > 20 ? colors.warn : colors.danger;
}

const styles = StyleSheet.create({
  content: {
    padding: 16, paddingBottom: 140, gap: 14, alignSelf: 'center', width: '100%', maxWidth: MAX_CONTENT_WIDTH,
  },
});
