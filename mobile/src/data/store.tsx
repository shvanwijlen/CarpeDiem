import AsyncStorage from '@react-native-async-storage/async-storage';
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import { demoData, demoSystem, demoVessels } from './demo';
import { Candidate, firstReachable, Slot } from './failover';
import type { CarpeData, ConnectionStatus, Settings, SystemMetrics, VesselsPayload } from './types';

const STORAGE_KEY = 'carpediem.settings.v1';
const LIVE_POLL_MS = 3000;
const DEMO_POLL_MS = 1000;
const REQUEST_TIMEOUT_MS = 4000;

// Starts in demo mode so the very first launch already shows something
// (and so App Store review, which can't reach a private boat, can use it).
const DEFAULT_SETTINGS: Settings = { baseUrl: 'http://cdpi1.local:8080', altUrl: '', demo: true };
const EMPTY_VESSELS: VesselsPayload = { max_range_km: 5, vessels: [] };

interface CarpeContext {
  data: CarpeData;
  vessels: VesselsPayload;
  system: SystemMetrics | null;
  status: ConnectionStatus;
  lastUpdated: number | null;
  error: string | null;
  activeSlot: Slot | null; // which address is currently answering (live mode)
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
  const [system, setSystem] = useState<SystemMetrics | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>('connecting');
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeSlot, setActiveSlot] = useState<Slot | null>(null);
  const lastSlot = useRef<Slot | null>(null);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then((raw) => {
        if (raw) setSettings({ ...DEFAULT_SETTINGS, ...JSON.parse(raw) });
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  const saveSettings = useCallback((s: Settings) => {
    const next = { ...s, baseUrl: normalizeBaseUrl(s.baseUrl), altUrl: normalizeBaseUrl(s.altUrl) };
    lastSlot.current = null;
    setActiveSlot(null);
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

    let inFlight = false;
    const poll = async () => {
      if (inFlight) return; // a slow/failing address can outlast the 3s interval
      inFlight = true;
      try {
        const candidates: Candidate[] = [
          { slot: 'primary' as const, url: settings.baseUrl },
          { slot: 'alt' as const, url: settings.altUrl },
        ].filter((c) => c.url);
        const result = await firstReachable(candidates, lastSlot.current, (url) => fetchJson<CarpeData>(`${url}/api/data`));
        if (cancelled) return;
        if (!result.ok) {
          setStatus('offline');
          setError(result.error);
          return;
        }
        lastSlot.current = result.slot;
        setActiveSlot(result.slot);
        setData(result.value);
        setStatus('live');
        setLastUpdated(Date.now());
        setError(null);
        // Older Pi builds have no /api/vessels - the radar just stays empty.
        try {
          const v = await fetchJson<VesselsPayload>(`${result.url}/api/vessels`);
          if (!cancelled) setVessels(v);
        } catch {
          /* optional endpoint */
        }
        try {
          const sys = await fetchJson<SystemMetrics>(`${result.url}/api/system`);
          if (!cancelled) setSystem(sys);
        } catch {
          if (!cancelled) setSystem(null); // older Pi build without /api/system
        }
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
  }, [loaded, settings.demo, settings.baseUrl, settings.altUrl]);

  const value = useMemo(
    () => ({ data, vessels, system, status, lastUpdated, error, activeSlot, settings, saveSettings }),
    [data, vessels, system, status, lastUpdated, error, activeSlot, settings, saveSettings],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCarpe(): CarpeContext {
  const v = useContext(Ctx);
  if (!v) throw new Error('useCarpe must be used inside <CarpeProvider>');
  return v;
}
