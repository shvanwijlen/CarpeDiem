export type DataValue = number | string | null;
export type CarpeData = Record<string, DataValue>;

export type VesselCategory = 'moored' | 'overtaking' | 'fast' | 'ok';

// GET /api/vessels - see carpediem/web_server.py
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

// GET /api/system - the Pi's own CPU/memory/disk health (the Pi HMI's SYS lamp).
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

export type ConnectionStatus = 'live' | 'demo' | 'offline' | 'connecting';

export interface Settings {
  baseUrl: string; // on the boat's LAN, e.g. http://cdpi1.local:8080
  altUrl: string; // optional second address (e.g. NordVPN Meshnet) tried if the first is unreachable
  demo: boolean;
}
