import AsyncStorage from '@react-native-async-storage/async-storage';
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import { demoData, demoSystem, demoVessels } from './demo';
import { Candidate, firstReachable, Slot } from './failover';
import { fetchJson } from './http';
import { loadApiKey, saveApiKey } from './secure';
import type { CarpeData, ConnectionStatus, Settings, SystemMetrics, VesselsPayload } from './types';

const STORAGE_KEY = 'carpediem.settings.v1';
const LIVE_POLL_MS = 3000;
const DEMO_POLL_MS = 1000;

// Starts in demo mode so the very first launch already shows something
// (and so App Store review, which can't reach a private boat, can use it).
const DEFAULT_SETTINGS: Settings = { baseUrl: 'http://cdpi1.local:8080', altUrl: '', apiKey: '', appLock: true, demo: true };
const EMPTY_VESSELS: VesselsPayload = { max_range_km: 5, vessels: [] };

interface CarpeContext {
  data: CarpeData;
  vessels: VesselsPayload;
  system: SystemMetrics | null;
  status: ConnectionStatus;
  lastUpdated: number | null;
  error: string | null;
  activeSlot: Slot | null; // which address is currently answering (live mode)
  ready: boolean; // saved settings have been loaded
  settings: Settings;
  saveSettings: (s: Settings) => void;
}

const Ctx = createContext<CarpeContext | null>(null);

export function normalizeBaseUrl(raw: string): string {
  let url = raw.trim().replace(/\/+$/, '');
  if (url && !/^https?:\/\//i.test(url)) url = `http://${url}`;
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
  const [activeSlot, setActiveSlot] = useState<Slot | null>(null);
  const lastSlot = useRef<Slot | null>(null);

  useEffect(() => {
    Promise.all([AsyncStorage.getItem(STORAGE_KEY).catch(() => null), loadApiKey()])
      .then(([raw, apiKey]) => {
        const saved = raw ? JSON.parse(raw) : {};
        delete saved.apiKey; // never read a key from the plain settings JSON
        setSettings({ ...DEFAULT_SETTINGS, ...saved, apiKey });
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  const saveSettings = useCallback((s: Settings) => {
    const next = { ...s, baseUrl: normalizeBaseUrl(s.baseUrl), altUrl: normalizeBaseUrl(s.altUrl), apiKey: s.apiKey.trim() };
    lastSlot.current = null;
    setActiveSlot(null);
    setSettings(next);
    setStatus('connecting');
    setError(null);
    const { apiKey, ...plain } = next; // the key goes to the Keychain, the rest to plain storage
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(plain)).catch(() => {});
    saveApiKey(apiKey);
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
        const result = await firstReachable(candidates, lastSlot.current, (url) => fetchJson<CarpeData>(`${url}/api/data`, settings.apiKey));
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
          const v = await fetchJson<VesselsPayload>(`${result.url}/api/vessels`, settings.apiKey);
          if (!cancelled) setVessels(v);
        } catch {
          /* optional endpoint */
        }
        try {
          const sys = await fetchJson<SystemMetrics>(`${result.url}/api/system`, settings.apiKey);
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
  }, [loaded, settings.demo, settings.baseUrl, settings.altUrl, settings.apiKey]);

  const value = useMemo(
    () => ({ data, vessels, system, status, lastUpdated, error, activeSlot, ready: loaded, settings, saveSettings }),
    [data, vessels, system, status, lastUpdated, error, activeSlot, loaded, settings, saveSettings],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCarpe(): CarpeContext {
  const v = useContext(Ctx);
  if (!v) throw new Error('useCarpe must be used inside <CarpeProvider>');
  return v;
}
