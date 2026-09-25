import { MaterialCommunityIcons } from '@expo/vector-icons';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Image, Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import { Led, Meter, Panel } from '../components/ui';
import { createSource, ImageRequest } from '../data/source';
import { normalizeBaseUrl, useCarpe } from '../data/store';
import { num, str } from '../data/format';
import { colors, fonts } from '../theme';
import { batteryColor, ScreenScroll, useCardWidth } from './common';

// Ring camera names/fields match ring_client.py's camera_field_map. `key`
// is the Ring device name itself (ring_client.py's cam_name), also the
// path segment web_server.py's /api/cam/<name>/... routes expect.
const CAMERAS = [
  { name: 'SALON', key: 'Salon', wired: false },
  { name: 'BAKBOORD', key: 'Bakboord', wired: false },
  { name: 'STUURBOORD', key: 'Stuurboord', wired: false },
  { name: 'CONSOLE', key: 'Console', wired: true }, // wired cam - Ring pins battery at 100
];

// How often the full-screen live view re-requests a frame. Matches the
// Pi's own MIN_FRAME_INTERVAL_SECONDS cap in ring_live_view.py, so this
// isn't polling faster than the Pi could ever answer.
const LIVE_POLL_MS = 500;
// After this many polls with no successful frame, show a hint under the
// spinner - still keeps polling (a slow Ring wake-up can take a while).
const STALL_HINT_POLLS = 10;

export function CamScreen() {
  const { data, settings } = useCarpe();
  const cardW = useCardWidth();
  const w = (cardW - 12) / 2;
  // Stills come from the data store (the Pi pushes them there), so they work from anywhere.
  const source = useMemo(() => (settings.demo ? null : createSource(settings)), [settings]);
  // Live view streams straight from the Pi, so it needs the Pi's own address - reachable on the boat's WiFi only.
  const liveBase = !settings.demo && settings.piUrl ? normalizeBaseUrl(settings.piUrl, 'http') : null;
  const [liveCam, setLiveCam] = useState<string | null>(null);

  return (
    <ScreenScroll>
      <View style={styles.grid}>
        {CAMERAS.map((c) => {
          const battery = num(data, `RingBattery${c.key}`);
          const conn = str(data, `RingConnection${c.key}`);
          const online = conn === 'online';
          const accent = conn === null ? colors.neutral : online ? colors.ok : colors.danger;
          return (
            <View key={c.key} style={{ width: w }}>
              <Panel glow={accent}>
                <CamThumb name={c.name} snapshot={source?.snapshot(c.key) ?? null} canGoLive={liveBase !== null} accent={accent}
                          onPress={() => setLiveCam(c.key)} />
                <View style={styles.headRow}>
                  <Text style={styles.name}>{c.name}</Text>
                  <Led state={conn === null ? 'off' : online ? 'ok' : 'bad'} size={10} />
                </View>
                <Text style={[styles.conn, { color: accent }]}>{conn ? conn.toUpperCase() : 'NO DATA'}</Text>
                {c.wired ? (
                  <Text style={styles.wired}>WIRED</Text>
                ) : (
                  <>
                    <View style={styles.battRow}>
                      <MaterialCommunityIcons name="battery-70" size={14} color={batteryColor(battery)} />
                      <Text style={styles.battText}>{battery === null ? '--' : `${Math.round(battery)}%`}</Text>
                    </View>
                    <Meter value={battery === null ? null : battery / 100} color={batteryColor(battery)} height={4} />
                  </>
                )}
              </Panel>
            </View>
          );
        })}
      </View>

      <Panel title="LIVE VIEW">
        <Text style={styles.note}>
          {liveBase
            ? 'Tap a camera above to watch it live. Live view streams straight from the Pi, so it only works '
              + 'while your phone is on the boat’s WiFi, and it uses the Pi’s internet connection while it’s open, '
              + 'same as the boat’s own touch display.'
            : 'The pictures above are the latest snapshots the Pi sent to the data store. To watch a camera live '
              + '(on the boat’s WiFi only), add the Pi’s address under the gear icon.'}
        </Text>
      </Panel>

      {liveBase ? (
        <CamLiveModal visible={liveCam !== null} camKey={liveCam ?? ''}
                       name={CAMERAS.find((c) => c.key === liveCam)?.name ?? ''}
                       baseUrl={liveBase} apiKey={settings.piApiKey} onClose={() => setLiveCam(null)} />
      ) : null}
    </ScreenScroll>
  );
}

// --- Grid tile thumbnail: the Pi's latest snapshot (from the data store) if
// there is one, else a plain camera icon with a "tap to watch live" hint when
// live view is available (mirrors the Qt Cam page's own placeholder - see
// hmi_qt/pages/cam_page.py's _draw_snapshot).
function CamThumb({ name, snapshot, canGoLive, accent, onPress }: {
  name: string; snapshot: ImageRequest | null; canGoLive: boolean; accent: string; onPress: () => void;
}) {
  const [hasSnapshot, setHasSnapshot] = useState(false);
  const online = accent !== colors.neutral;

  return (
    <Pressable style={styles.thumb} onPress={onPress} disabled={!canGoLive} accessibilityLabel={`Watch ${name} live`}>
      {snapshot ? (
        <Image
          source={snapshot}
          style={StyleSheet.absoluteFill}
          resizeMode="cover"
          onLoad={() => setHasSnapshot(true)}
          onError={() => setHasSnapshot(false)}
        />
      ) : null}
      {!hasSnapshot ? (
        <View style={styles.thumbPlaceholder}>
          <MaterialCommunityIcons name={online ? 'cctv' : 'cctv-off'} size={40} color={accent} />
          {canGoLive ? <Text style={styles.thumbHint}>TAP TO WATCH LIVE</Text> : null}
        </View>
      ) : canGoLive ? (
        <View style={styles.thumbBadge}>
          <MaterialCommunityIcons name="play-circle" size={18} color={colors.text} />
        </View>
      ) : null}
    </Pressable>
  );
}

// --- Full-screen live view: polls /api/cam/<name>/live.jpg a couple of
// times a second (the Pi starts/keeps a WebRTC Live View session alive for
// as long as polls keep coming - see web_server.py's _cam_idle_reaper).
// Tap anywhere to close, same convention as SysPopup/the AIS radar popup.
function CamLiveModal({ visible, camKey, name, baseUrl, apiKey, onClose }: {
  visible: boolean; camKey: string; name: string; baseUrl: string; apiKey: string; onClose: () => void;
}) {
  const [tick, setTick] = useState(0);
  const [connected, setConnected] = useState(false);
  const failStreak = useRef(0);
  const [stalled, setStalled] = useState(false);

  useEffect(() => {
    if (!visible) return;
    setConnected(false);
    setStalled(false);
    failStreak.current = 0;
    const id = setInterval(() => setTick((t) => t + 1), LIVE_POLL_MS);
    return () => clearInterval(id);
  }, [visible, camKey]);

  const onFrame = () => {
    failStreak.current = 0;
    setConnected(true);
    setStalled(false);
  };
  const onFail = () => {
    failStreak.current += 1;
    if (failStreak.current >= STALL_HINT_POLLS) setStalled(true);
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.liveBackdrop} onPress={onClose} accessibilityLabel="Close live view">
        <View style={styles.liveHeader}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <View style={[styles.liveDot, { backgroundColor: connected ? colors.danger : colors.textDim }]} />
            <Text style={styles.liveTitle}>{name.toUpperCase()}</Text>
          </View>
          <Text style={styles.liveBadge}>{connected ? 'LIVE' : 'CONNECTING…'}</Text>
        </View>

        <View style={styles.liveVideoWrap}>
          {visible ? (
            <Image
              key={tick}
              source={{ uri: `${baseUrl}/api/cam/${camKey}/live.jpg?t=${tick}`, headers: apiKey ? { 'X-API-Key': apiKey } : undefined }}
              style={StyleSheet.absoluteFill}
              resizeMode="contain"
              onLoad={onFrame}
              onError={onFail}
            />
          ) : null}
          {!connected ? (
            <View style={styles.liveOverlay}>
              <MaterialCommunityIcons name="cctv" size={48} color={colors.secondary} />
              <Text style={styles.liveConnecting}>CONNECTING…</Text>
              {stalled ? (
                <Text style={styles.liveStallHint}>
                  Taking a while - the camera may be asleep, offline, or the Pi may be missing aiortc/Pillow
                  for Live View. Keep waiting, or check the CAM tile’s battery/connection status.
                </Text>
              ) : null}
            </View>
          ) : null}
        </View>

        <Text style={styles.liveHint}>TAP ANYWHERE TO CLOSE</Text>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  thumb: {
    height: 84, borderRadius: 12, alignItems: 'center', justifyContent: 'center', marginBottom: 10,
    backgroundColor: '#ffffff08', borderWidth: 1, borderColor: colors.border, borderStyle: 'dashed', overflow: 'hidden',
  },
  thumbPlaceholder: { alignItems: 'center', justifyContent: 'center', gap: 4 },
  thumbHint: { fontFamily: fonts.labelBold, fontSize: 9.5, letterSpacing: 1.4, color: colors.textDim },
  thumbBadge: {
    position: 'absolute', right: 6, bottom: 6, backgroundColor: '#03050988', borderRadius: 10, padding: 3,
  },
  headRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  name: { fontFamily: fonts.display, fontSize: 13, letterSpacing: 1.4, color: colors.text },
  conn: { fontFamily: fonts.labelBold, fontSize: 11.5, letterSpacing: 2, marginTop: 2 },
  wired: { fontFamily: fonts.labelBold, fontSize: 11, letterSpacing: 2, color: colors.textDim, marginTop: 8 },
  battRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 8 },
  battText: { fontFamily: fonts.label, fontSize: 12, color: colors.textDim },
  note: { fontFamily: fonts.body, fontSize: 14, lineHeight: 20, color: colors.textDim },

  liveBackdrop: { flex: 1, backgroundColor: '#000000E6', padding: 16, paddingTop: 56 },
  liveHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 },
  liveDot: { width: 10, height: 10, borderRadius: 5 },
  liveTitle: { fontFamily: fonts.display, fontSize: 16, letterSpacing: 2, color: colors.text },
  liveBadge: { fontFamily: fonts.labelBold, fontSize: 12, letterSpacing: 2, color: colors.secondary },
  liveVideoWrap: {
    flex: 1, borderRadius: 16, overflow: 'hidden', backgroundColor: colors.bgHi,
    borderWidth: 1, borderColor: colors.border, alignItems: 'center', justifyContent: 'center',
  },
  liveOverlay: { alignItems: 'center', justifyContent: 'center', gap: 10, padding: 24 },
  liveConnecting: { fontFamily: fonts.labelBold, fontSize: 13, letterSpacing: 2, color: colors.textDim },
  liveStallHint: { fontFamily: fonts.body, fontSize: 12.5, lineHeight: 18, color: colors.textDim, textAlign: 'center', maxWidth: 320 },
  liveHint: {
    fontFamily: fonts.labelBold, fontSize: 10.5, letterSpacing: 2, color: colors.textDim, textAlign: 'center', marginTop: 16,
  },
});
