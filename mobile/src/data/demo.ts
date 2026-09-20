// Built-in sample data: lets the app run (and be reviewed - App Store
// review can't reach a private boat) without a Pi. Values follow
// carpediem/fake_data.py's real snapshot, plus a gentle live "wobble" so
// the compass/radar animate the way real data would.
import { norm360 } from './format';
import type { CarpeData, SystemMetrics, Vessel, VesselsPayload } from './types';

const WIND_CALIBRATION_COURSE_DEG = 259; // same constant as the Pi's wind_calibration.py

const BASE: CarpeData = {
  'Active input source': 1,
  'Grid (W)': 57,
  'AC Loads (W)': 48,
  'Battery SOC (%)': 100,
  'Battery0 Voltage (V)': 13.61,
  'Battery0 Power (W)': 5.44,
  'Battery0 Current (A)': 0.4,
  'Battery Power (W)': 4.08,
  'Battery1 Voltage (V)': 26.36,
  'Battery Time to Go (System)': 14.5,
  'DC Power (W)': 210,
  'DC Current (A)': 15.4,
  'PV Power (W)': 24,
  'Starter battery (V)': 12.9,
  'Electronics bay (C)': 29.41,
  'Engine room (C)': 20.12,
  Lat: 52.171967,
  Lng: 4.5158,
  Speed: 5.05,
  Course: 259,
  VesselsBehindMe: 5,
  VesselsFasterThan10: 3,
  VesselsOther: 32,
  NextObject: 'Schipholbrug - Lijnden',
  NextObjectStatus: 'CLOSED',
  NextObjectClearanceM: 2.9,
  'Master Bedroom Temp': 21.68,
  'Master Bedroom Humidity': 63,
  'Master Bedroom Battery': 91,
  'Engine Room Temp': 21.12,
  'Engine Room Humidity': 61,
  'Engine Room Battery': 84,
  'Watertank SB Temp': 20.43,
  'Watertank SB Humidity': 62,
  'Watertank SB Battery': 77,
  'Watertank PS Temp': 20.94,
  'Watertank PS Humidity': 60,
  'Watertank PS Battery': 88,
  RuuviConsoleTemp: 32.82,
  RuuviConsoleHumidity: 34.22,
  RuuviConsoleBatteryVoltage: 3.0,
  RuuviWatertankPSTemp: 26.89,
  RuuviWatertankPSHumidity: 45.8,
  RuuviWatertankPSBatteryVoltage: 2.87,
  'Toilet Temp': 19.73,
  'Toilet Humidity': 73,
  'Toilet Battery': 95,
  'P RHT 900F0A Temp': 24.08,
  'P RHT 900F0A Humidity': 52,
  'P RHT 900F0A Battery': 68,
  'Voorin Temp': 26.09,
  'Voorin Humidity': 53,
  'Voorin Battery': 82,
  'Kajuit Temp': 26.54,
  'Kajuit Humidity': 53,
  'Kajuit Battery': 90,
  BresserTemperature: 18.5,
  BresserHumidity: 64,
  BresserWindDirection: 126,
  BresserWindGustSpeed: 21.0,
  BresserWindAverageSpeed: 14.5,
  BresserRainfall: 1.2,
  BresserLightIntensity: 25816,
  BresserUVindex: 2.2,
  BresserSensorBatteryStatus: 1,
  'BME280-Barometer': 1013.2,
  sparkfun_elec_bay_humidity: 42.0,
  sparkfun_elec_bay_temperature: 29.8,
  RingBatterySalon: 76,
  RingBatteryBakboord: 90,
  RingBatteryStuurboord: 90,
  RingBatteryConsole: 100,
  RingConnectionSalon: 'online',
  RingConnectionBakboord: 'online',
  RingConnectionStuurboord: 'online',
  RingConnectionConsole: 'online',
  AIS: 1,
  MQTT: 1,
  MODBUS: 1,
  BLE: 1,
  Weather: 1,
  Cam: 1,
  WiFi: 1,
  AISstream: 1,
  AISAntenna: 1,
  WebServer: 1,
};

export function demoData(nowMs: number): CarpeData {
  const t = nowMs / 1000;
  const speed = 5.05 + 0.45 * Math.sin(t / 5);
  const course = norm360(259 + 38 * Math.sin(t / 14));
  const windDir = norm360(126 + 28 * Math.sin(t / 9));
  const windAvg = 14.5 + 2.5 * Math.sin(t / 6);
  const d: CarpeData = {
    ...BASE,
    Speed: speed,
    Course: course,
    BresserWindDirection: windDir,
    BresserWindAverageSpeed: windAvg,
    BresserWindGustSpeed: windAvg + 6.5 + 1.5 * Math.sin(t / 3),
    'PV Power (W)': 24 + 6 * Math.sin(t / 7),
    'DC Power (W)': 210 + 40 * Math.sin(t / 11),
  };
  // Same two derived fields the Pi's wind_calibration.py computes.
  const recal = norm360(windDir + course - WIND_CALIBRATION_COURSE_DEG);
  d.WindspeedCalculatedRecalibrated = recal;
  d.WindspeedCalculatedAsExperienced = norm360(recal - course);
  return d;
}

const V = (
  mmsi: number, name: string | null, bearing: number, km: number,
  knots: number | null, heading: number, category: Vessel['category'],
): Vessel => ({ mmsi, name, bearing_deg: bearing, distance_km: km, speed_knots: knots, heading_deg: heading, category });

const VESSELS: Vessel[] = [
  V(244009320, 'AMARONE', -62, 1.4, 0, 0, 'moored'),
  V(244060141, 'COCOSMACROON', 118, 2.1, 4.6, 96, 'overtaking'),
  V(244260467, 'SASKIA', 24, 3.2, 3.7, 340, 'fast'),
  V(244014995, 'HALO', -104, 2.6, 0, 0, 'moored'),
  V(244710596, 'CORMORAAN', -132, 3.9, 0, 0, 'moored'),
  V(244746863, null, 152, 1.1, 1.7, 12, 'ok'),
  V(244864056, null, 41, 4.4, 5.1, 200, 'overtaking'),
  V(244110037, 'BREAKWATER', 78, 4.7, 6.2, 60, 'fast'),
  V(244376276, 'LEIDSE KEIJZER', -28, 2.4, 4.8, 350, 'ok'),
  V(244026030, 'CYGNE', -8, 4.1, 0, 0, 'moored'),
  V(244131506, 'DE BEER', 12, 3.4, 0, 0, 'moored'),
  V(244615508, 'JOLLY ROGER', -151, 4.6, 0, 0, 'moored'),
  V(244393997, 'BONA SPES 4', -76, 4.9, 0, 0, 'moored'),
  V(244180300, null, 171, 0.8, 4.9, 20, 'overtaking'),
];

export function demoSystem(): SystemMetrics {
  return { status: 'ok', cpu_percent: 18, mem_percent: 41, disk_used_percent: 37 };
}

export function demoVessels(): VesselsPayload {
  return { max_range_km: 5, vessels: VESSELS };
}
