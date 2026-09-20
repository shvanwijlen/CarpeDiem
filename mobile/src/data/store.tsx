import AsyncStorage from '@react-native-async-storage/async-storage';
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { demoData, demoVessels } from './demo';
import type { CarpeData, ConnectionStatus, Settings, VesselsPayload } from './types';

const STORAGE_KEY = 'carpediem.settings.v1';
const LIVE_POLL_MS = 3000;
const DEMO_POLL_MS = 1000;
const REQUEST_TIMEOUT_MS = 5000;

// Starts in demo mode so the very first launch already shows something
// (and so App Store review, which can't reach a private boat, can use it).
const DEFAULT_SETTINGS: Settings = { baseUrl: 'http://192.168.1.50:8080', demo: true };
const EMPTY_VESSELS: VesselsPayload = { max_range_km: 5, vessels: [] };

interface CarpeContext {
  data: CarpeData;
  vessels: VesselsPayload;
  status: ConnectionStatus;
  lastUpdated: number | null;
  error: string | null;
  settings: Settings;
  saveSettings: (s: Settings) => void;
}

const Ctx = createContext<CarpeContext | null>(null);

export function normalizeBaseUrl(raw: string): string {
  let url = raw.trim().replace(/\/+$/, '');
  if (url && !/^https?:\/\//i.test(url)) url = `http://${url}`;
  return url;
}

async function fetchJson<T>(url: string): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export function CarpeProvider({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [loaded, setLoaded] = useState(false);
  const [data, setData] = useState<CarpeData>({});
  const [vessels, setVessels] = useState<VesselsPayload>(EMPTY_VESSELS);
  const [status, setStatus] = useState<ConnectionStatus>('connecting');
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then((raw) => {
        if (raw) setSettings({ ...DEFAULT_SETTINGS, ...JSON.parse(raw) });
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  const saveSettings = useCallback((s: Settings) => {
    const next = { ...s, baseUrl: normalizeBaseUrl(s.baseUrl) };
    setSettings(next);
    setStatus('connecting');
    setError(null);
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(next)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!loaded) return;
    let cancelled = false;

    if (settings.demo) {
      const tick = () => {
        if (cancelled) return;
        setData(demoData(Date.now()));
        setVessels(demoVessels());
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

    const poll = async () => {
      try {
        const next = await fetchJson<CarpeData>(`${settings.baseUrl}/api/data`);
        if (cancelled) return;
        setData(next);
        setStatus('live');
        setLastUpdated(Date.now());
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setStatus('offline');
        setError(e instanceof Error ? e.message : String(e));
        return;
      }
      // Older Pi builds have no /api/vessels - the radar just stays empty.
      try {
        const v = await fetchJson<VesselsPayload>(`${settings.baseUrl}/api/vessels`);
        if (!cancelled) setVessels(v);
      } catch {
        /* optional endpoint */
      }
    };
    poll();
    const id = setInterval(poll, LIVE_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [loaded, settings.demo, settings.baseUrl]);

  const value = useMemo(
    () => ({ data, vessels, status, lastUpdated, error, settings, saveSettings }),
    [data, vessels, status, lastUpdated, error, settings, saveSettings],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCarpe(): CarpeContext {
  const v = useContext(Ctx);
  if (!v) throw new Error('useCarpe must be used inside <CarpeProvider>');
  return v;
}
