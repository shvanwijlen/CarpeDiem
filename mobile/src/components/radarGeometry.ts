// Radar plot geometry, kept free of React/RN imports so it can be unit-tested
// with plain Node. The SVG in gauges.tsx draws in a 300x300 viewBox with the
// outer ring at radius 138; this maps a vessel to on-screen pixels for any
// rendered size, and finds the vessel nearest a tap.
import type { Vessel } from '../data/types';

const VIEWBOX = 300;
const RING_RADIUS = 138;

export function blipPosition(v: Vessel, maxKm: number, size: number): { x: number; y: number } {
  const scale = size / VIEWBOX;
  const c = size / 2;
  const frac = maxKm > 0 ? Math.min(1, v.distance_km / maxKm) : 0;
  const theta = (v.bearing_deg * Math.PI) / 180;
  const r = RING_RADIUS * scale * frac;
  return { x: c + r * Math.sin(theta), y: c - r * Math.cos(theta) };
}

/** Nearest vessel within `hitRadiusPx` of the tap, or null (tap on empty space). */
export function nearestVessel(
  vessels: Vessel[], maxKm: number, size: number, tapX: number, tapY: number, hitRadiusPx = 26,
): Vessel | null {
  let best: Vessel | null = null;
  let bestDist = hitRadiusPx;
  for (const v of vessels) {
    const p = blipPosition(v, maxKm, size);
    const d = Math.hypot(tapX - p.x, tapY - p.y);
    if (d <= bestDist) {
      best = v;
      bestDist = d;
    }
  }
  return best;
}
