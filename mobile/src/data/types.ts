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
export interface SystemMetrics {
  status: 'ok' | 'warn' | 'crit' | null;
  cpu_percent?: number;
  mem_percent?: number;
  disk_used_percent?: number;
}

export type ConnectionStatus = 'live' | 'demo' | 'offline' | 'connecting';

export interface Settings {
  baseUrl: string; // on the boat's LAN, e.g. http://cdpi1.local:8080
  altUrl: string; // optional second address (e.g. NordVPN Meshnet) tried if the first is unreachable
  demo: boolean;
}
