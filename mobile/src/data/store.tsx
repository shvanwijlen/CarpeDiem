import AsyncStorage from '@react-native-async-storage/async-storage';
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { demoData, demoSystem, demoVessels } from './demo';
import { loadSecret, saveSecret } from './secure';
import { createSource, isFresh } from './source';
import type { CarpeData, ConnectionStatus, Settings, SystemMetrics, VesselsPayload } from './types';

const STORAGE_KEY = 'carpediem.settings.v1';
// The Pi pushes to the store about every 10 s, so polling faster than this gains nothing.
const LIVE_POLL_MS = 5000;
const DEMO_POLL_MS = 1000;

// Starts in demo mode so the very first launch already shows something
// (and so App Store review, which can't reach a private boat, can use it).
const DEFAULT_SETTINGS: Settings = { storeUrl: '', readKey: '', piUrl: '', piApiKey: '', appLock: true, demo: true };
const EMPTY_VESSELS: VesselsPayload = { max_range_km: 5, vessels: [] };

interface CarpeContext {
  data: CarpeData;
  vessels: VesselsPayload;
  system: SystemMetrics | null;
  status: ConnectionStatus;
  lastUpdated: number | null; // when the boat last reported (not when this app last polled)
  error: string | null;
  ready: boolean; // saved settings have been loaded
  settings: Settings;
  saveSettings: (s: Settings) => void;
}

const Ctx = createContext<CarpeContext | null>(null);

// `defaultScheme` is used when the user typed a bare host: the data store is
// normally reached over HTTPS, the Pi (on the boat's LAN) over plain HTTP.
export function normalizeBaseUrl(raw: string, defaultScheme: 'http' | 'https' = 'https'): string {
  let url = raw.trim().replace(/\/+$/, '');
  if (url && !/^https?:\/\//i.test(url)) url = `${defaultScheme}://${url}`;
  return url;
}

export function CarpeProvider({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [loaded, setLoaded] = useState(false);
  const [data, setData] = useState<CarpeData>({});
  const [vessels, setVessels] = useState<VesselsPayload>(EMPTY_VESSELS);
  const [system, setSystem] = useState<SystemMetrics | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>('connecting');
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([AsyncStorage.getItem(STORAGE_KEY).catch(() => null), loadSecret('store'), loadSecret('pi')])
      .then(([raw, readKey, piApiKey]) => {
        const saved = raw ? JSON.parse(raw) : {};
        // Settings saved before the data store existed: the Pi's address (baseUrl) is still useful, as
        // the live-camera address. The old "away" address (altUrl) was a VPN address and has no use now.
        if (saved.piUrl === undefined && saved.baseUrl) saved.piUrl = saved.baseUrl;
        delete saved.baseUrl;
        delete saved.altUrl;
        delete saved.apiKey; // never read a key from the plain settings JSON
        setSettings({ ...DEFAULT_SETTINGS, ...saved, readKey, piApiKey });
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  const saveSettings = useCallback((s: Settings) => {
    const next = {
      ...s,
      storeUrl: normalizeBaseUrl(s.storeUrl, 'https'),
      piUrl: normalizeBaseUrl(s.piUrl, 'http'),
      readKey: s.readKey.trim(),
      piApiKey: s.piApiKey.trim(),
    };
    setSettings(next);
    setStatus('connecting');
    setError(null);
    const { readKey, piApiKey, ...plain } = next; // the keys go to the Keychain, the rest to plain storage
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(plain)).catch(() => {});
    saveSecret('store', readKey);
    saveSecret('pi', piApiKey);
  }, []);

  useEffect(() => {
    if (!loaded) return;
    let cancelled = false;

    if (settings.demo) {
      const tick = () => {
        if (cancelled) return;
        setData(demoData(Date.now()));
        setVessels(demoVessels());
        setSystem(demoSystem(Date.now()));
        setStatus('demo');
        setLastUpdated(Date.now());
        setError(null);
      };
      tick();
      const id = setInterval(tick, DEMO_POLL_MS);
      return () => {
        cancelled = true;
        clearInterval(id);
      };
    }

    const source = createSource(settings);
    let inFlight = false;
    const poll = async () => {
      if (inFlight) return; // a slow/failing request can outlast the poll interval
      inFlight = true;
      try {
        if (!source) {
          setStatus('offline');
          setError('no data store address set - open Settings');
          return;
        }
        const latest = await source.fetchLatest();
        if (cancelled) return;
        setData(latest.data);
        setVessels(latest.vessels ?? EMPTY_VESSELS);
        setSystem(latest.system);
        // Reached the store: green if the boat reported recently, orange if all we have is old data.
        setStatus(isFresh(latest.ageSeconds) ? 'live' : 'stale');
        setLastUpdated(latest.ageSeconds === null ? null : Date.now() - latest.ageSeconds * 1000);
        setError(latest.ageSeconds === null ? 'the store has no data yet' : null);
      } catch (e) {
        if (cancelled) return;
        // Can't reach the store: keep showing whatever we last had, but say so.
        setStatus('offline');
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        inFlight = false;
      }
    };
    poll();
    const id = setInterval(poll, LIVE_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [loaded, settings.demo, settings.storeUrl, settings.readKey]);

  const value = useMemo(
    () => ({ data, vessels, system, status, lastUpdated, error, ready: loaded, settings, saveSettings }),
    [data, vessels, system, status, lastUpdated, error, loaded, settings, saveSettings],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCarpe(): CarpeContext {
  const v = useContext(Ctx);
  if (!v) throw new Error('useCarpe must be used inside <CarpeProvider>');
  return v;
}
