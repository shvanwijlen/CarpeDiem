export type DataValue = number | string | null;
export type CarpeData = Record<string, DataValue>;

export type VesselCategory = 'moored' | 'overtaking' | 'fast' | 'ok';

// The `vessels` part of the store's state (the Pi's GET /api/vessels) - see carpediem/api_payloads.py
export interface Vessel {
  mmsi: number;
  name: string | null;
  bearing_deg: number; // relative to our bow, -180..180
  distance_km: number;
  speed_knots: number | null;
  heading_deg: number; // vessel heading relative to our own course
  category: VesselCategory;
}

export interface VesselsPayload {
  max_range_km: number;
  vessels: Vessel[];
}

// The `system` part of the store's state (the Pi's GET /api/system) - the Pi's own CPU/memory/disk health (the Pi HMI's SYS lamp).
// status is null when the Pi's monitor is off or hasn't sampled yet.
export type SysLevel = 'ok' | 'warn' | 'crit';

// One line of the SYS popup, pre-formatted by the Pi (carpediem/
// sysmetrics_monitor.py summary_rows) so the phone shows exactly what the
// Pi's own display does, thresholds included.
export interface SysRow {
  label: string;
  value: string;
  level: SysLevel;
  fraction: number | null; // 0..1 for a bar
}

export interface SystemMetrics {
  status: SysLevel | null;
  cpu_temp_c?: number | null;
  rows?: SysRow[];
}

// live: reached the store and the boat reported recently (green)
// stale: reached the store, but its newest data is old - the boat stopped reporting (orange)
// offline: can't reach the store at all (red)
export type ConnectionStatus = 'live' | 'stale' | 'demo' | 'offline' | 'connecting';

export interface Settings {
  storeUrl: string; // the data store the Pi pushes to, e.g. https://carpediem.example.com
  readKey: string; // the store's READ_API_KEY - kept in the Keychain, not in the settings JSON
  piUrl: string; // optional: the Pi on the boat's WiFi, only for the live camera view
  piApiKey: string; // the Pi's WEBSERVER_API_KEY, if it has one (live camera only) - Keychain too
  appLock: boolean; // ask for Face ID / passcode to open the app (live mode only)
  demo: boolean;
}
