// API keys live in the iOS Keychain (expo-secure-store), not in the plain
// settings JSON in AsyncStorage. SecureStore doesn't exist on web, which is
// only used here for browser previews, so web falls back to AsyncStorage.
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

// SecureStore keys: letters, digits, '.', '-', '_' only. 'pi' keeps the key name
// the app used before the data store existed (it was the Pi's API key then too).
const KEYS = { pi: 'carpediem.apikey', store: 'carpediem.storekey' } as const;
export type SecretName = keyof typeof KEYS;

export async function loadSecret(name: SecretName): Promise<string> {
  try {
    if (Platform.OS === 'web') return (await AsyncStorage.getItem(KEYS[name])) ?? '';
    return (await SecureStore.getItemAsync(KEYS[name])) ?? '';
  } catch {
    return '';
  }
}

export async function saveSecret(name: SecretName, value: string): Promise<void> {
  try {
    if (Platform.OS === 'web') {
      if (value) await AsyncStorage.setItem(KEYS[name], value);
      else await AsyncStorage.removeItem(KEYS[name]);
      return;
    }
    if (value) {
      // This device only: never included in iCloud/iTunes backups or restored onto another phone.
      await SecureStore.setItemAsync(KEYS[name], value, { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY });
    } else {
      await SecureStore.deleteItemAsync(KEYS[name]);
    }
  } catch {
    /* nothing useful to do - the key just won't persist */
  }
}
