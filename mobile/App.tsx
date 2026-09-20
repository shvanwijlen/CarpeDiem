import { Orbitron_500Medium, Orbitron_700Bold, Orbitron_900Black } from '@expo-google-fonts/orbitron';
import { Rajdhani_500Medium, Rajdhani_600SemiBold, Rajdhani_700Bold } from '@expo-google-fonts/rajdhani';
import { useFonts } from 'expo-font';
import { StatusBar } from 'expo-status-bar';
import React, { useState } from 'react';
import { ActivityIndicator, Platform, View } from 'react-native';
import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context';

import { Backdrop, Header, StatusStrip, TabBar, TabDef } from './src/components/chrome';
import { LockGate } from './src/components/LockGate';
import { CarpeProvider } from './src/data/store';
import { AisScreen } from './src/screens/AisScreen';
import { CamScreen } from './src/screens/CamScreen';
import { MainScreen } from './src/screens/MainScreen';
import { PowerScreen } from './src/screens/PowerScreen';
import { SettingsModal } from './src/screens/SettingsModal';
import { TempsScreen } from './src/screens/TempsScreen';
import { WeatherScreen } from './src/screens/WeatherScreen';
import { colors } from './src/theme';

// Same six tabs, in the same order, as the Pi HMI's top bar.
const TABS: (TabDef & { title: string; screen: React.ComponentType })[] = [
  { id: 'main', caption: 'MAIN', icon: 'compass-outline', title: 'COMMAND DECK', screen: MainScreen },
  { id: 'ais', caption: 'AIS', icon: 'radar', title: 'TRAFFIC', screen: AisScreen },
  { id: 'weather', caption: 'WEATHER', icon: 'weather-partly-cloudy', title: 'WEATHER STATION', screen: WeatherScreen },
  { id: 'power', caption: 'POWER', icon: 'lightning-bolt', title: 'POWER SYSTEMS', screen: PowerScreen },
  { id: 'temps', caption: 'TEMPS', icon: 'thermometer', title: 'CLIMATE', screen: TempsScreen },
  { id: 'cam', caption: 'CAM', icon: 'cctv', title: 'CAMERAS', screen: CamScreen },
];

function Shell() {
  const insets = useSafeAreaInsets();
  // On web only, "#ais" etc. in the URL picks the starting tab (handy for
  // screenshots/testing); native always starts on Main.
  const [active, setActive] = useState(() =>
    Platform.OS === 'web' && typeof window !== 'undefined' ? window.location.hash.slice(1) || 'main' : 'main');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const tab = TABS.find((t) => t.id === active) ?? TABS[0];
  const Screen = tab.screen;

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <Backdrop />
      <View style={{ paddingTop: insets.top }}>
        <Header title={tab.title} onSettings={() => setSettingsOpen(true)} />
        <StatusStrip />
      </View>
      <View style={{ flex: 1 }}>
        <Screen />
      </View>
      <TabBar tabs={TABS} active={active} onChange={setActive} bottomInset={insets.bottom} />
      <SettingsModal visible={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <StatusBar style="light" />
    </View>
  );
}

export default function App() {
  const [fontsLoaded] = useFonts({
    Orbitron_500Medium, Orbitron_700Bold, Orbitron_900Black,
    Rajdhani_500Medium, Rajdhani_600SemiBold, Rajdhani_700Bold,
  });

  if (!fontsLoaded) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }
  return (
    <SafeAreaProvider>
      <CarpeProvider>
        <LockGate>
          <Shell />
        </LockGate>
      </CarpeProvider>
    </SafeAreaProvider>
  );
}
