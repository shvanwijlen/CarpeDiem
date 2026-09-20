// The Pi's API key lives in the iOS Keychain (expo-secure-store), not in the
// plain settings JSON in AsyncStorage. SecureStore doesn't exist on web, which
// is only used here for browser previews, so web falls back to AsyncStorage.
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

const KEY = 'carpediem.apikey'; // SecureStore keys: letters, digits, '.', '-', '_' only

export async function loadApiKey(): Promise<string> {
  try {
    if (Platform.OS === 'web') return (await AsyncStorage.getItem(KEY)) ?? '';
    return (await SecureStore.getItemAsync(KEY)) ?? '';
  } catch {
    return '';
  }
}

export async function saveApiKey(value: string): Promise<void> {
  try {
    if (Platform.OS === 'web') {
      if (value) await AsyncStorage.setItem(KEY, value);
      else await AsyncStorage.removeItem(KEY);
      return;
    }
    if (value) {
      // This device only: never included in iCloud/iTunes backups or restored onto another phone.
      await SecureStore.setItemAsync(KEY, value, { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY });
    } else {
      await SecureStore.deleteItemAsync(KEY);
    }
  } catch {
    /* nothing useful to do - the key just won't persist */
  }
}
