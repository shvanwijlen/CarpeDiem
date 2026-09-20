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

export type ConnectionStatus = 'live' | 'demo' | 'offline' | 'connecting';

export interface Settings {
  baseUrl: string;
  demo: boolean;
}
