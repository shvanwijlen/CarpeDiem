// Where the app's boat data comes from. Free of React/RN imports so it can be
// tested with plain Node against the real store (server/).
//
// The boat's Pi pushes its data to a remote datastore and the app only ever
// reads from there (nothing here talks to the Pi). DataSource is the seam that
// keeps the datastore swappable: StoreSource below reads the HTTP API in
// server/ - the store on the Synology, or anything else that implements the
// same API, e.g. a Cloudflare Worker. A datastore with its own wire protocol
// (Supabase's REST API, ...) is one more DataSource, chosen in createSource().
import { fetchJson } from './http';
import type { CarpeData, Settings, SystemMetrics, VesselsPayload } from './types';

// Data older than this counts as "old": the app can reach the store, but the
// boat has stopped reporting (Pi off, boat offline, ...). The Pi pushes about
// every 10 s, so two minutes tolerates a few dropped pushes on a flaky
// marina/cellular link without crying wolf.
export const STALE_AFTER_SECONDS = 120;

export interface Latest {
  data: CarpeData;
  vessels: VesselsPayload | null;
  system: SystemMetrics | null;
  // Seconds since the Pi last reported, by the store's clock; null when the
  // store has never received anything.
  ageSeconds: number | null;
}

export interface ImageRequest {
  uri: string;
  headers?: Record<string, string>;
}

export interface DataSource {
  fetchLatest(): Promise<Latest>;
  /** Latest still image of a Ring camera (camKey like 'Salon'), or null if this source has none. */
  snapshot(camKey: string): ImageRequest | null;
}

export function isFresh(ageSeconds: number | null): boolean {
  return ageSeconds !== null && ageSeconds <= STALE_AFTER_SECONDS;
}

// GET /v1/state - see server/carpediem_store/app.py.
interface StoreState {
  age_seconds: number | null;
  data: CarpeData | null;
  vessels: VesselsPayload | null;
  system: SystemMetrics | null;
}

export class StoreSource implements DataSource {
  constructor(private baseUrl: string, private readKey: string) {}

  async fetchLatest(): Promise<Latest> {
    const s = await fetchJson<StoreState>(`${this.baseUrl}/v1/state`, this.readKey);
    return { data: s.data ?? {}, vessels: s.vessels ?? null, system: s.system ?? null, ageSeconds: s.age_seconds ?? null };
  }

  snapshot(camKey: string): ImageRequest {
    // The Pi names snapshots by the lower-cased camera key (ring_client.snapshot_key).
    // The 5-minute bucket makes the image reload as new snapshots arrive; the URL is otherwise unchanged.
    const bucket = Math.floor(Date.now() / 300_000);
    return {
      uri: `${this.baseUrl}/v1/cam/${camKey.toLowerCase()}/snapshot.jpg?t=${bucket}`,
      headers: this.readKey ? { 'X-API-Key': this.readKey } : undefined,
    };
  }
}

export function createSource(settings: Pick<Settings, 'storeUrl' | 'readKey'>): DataSource | null {
  return settings.storeUrl ? new StoreSource(settings.storeUrl, settings.readKey) : null;
}
