import type { CarpeData } from './types';

export function num(d: CarpeData, key: string): number | null {
  const v = d[key];
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

export function str(d: CarpeData, key: string): string | null {
  const v = d[key];
  return typeof v === 'string' && v.length > 0 ? v : null;
}

export function fmt(v: number | null, digits = 0): string {
  return v === null ? '--' : v.toFixed(digits);
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

export function norm360(deg: number): number {
  return ((deg % 360) + 360) % 360;
}

// House battery voltage -> fill level, same span the Pi's main page uses
// (hmi_qt/icons.py HOUSE_BATTERY_EMPTY_V/FULL_V).
export const HOUSE_EMPTY_V = 12.2;
export const HOUSE_FULL_V = 14.2;

export function houseFillPercent(v: number | null): number | null {
  if (v === null) return null;
  return clamp(((v - HOUSE_EMPTY_V) / (HOUSE_FULL_V - HOUSE_EMPTY_V)) * 100, 0, 100);
}

const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
export function compassName(deg: number | null): string {
  if (deg === null) return '--';
  return COMPASS[Math.round(norm360(deg) / 22.5) % 16];
}

// display_data's "Active input source" (Victron Cerbo GX).
export function inputSourceName(v: number | null): string {
  switch (v) {
    case 0: return 'UNKNOWN';
    case 1: return 'GRID';
    case 2: return 'GENERATOR';
    case 3: return 'SHORE POWER';
    case 240: return 'NOT CONNECTED';
    default: return '--';
  }
}

export function ago(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h`;
}
