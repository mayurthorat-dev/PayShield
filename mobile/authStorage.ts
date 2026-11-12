/**
 * PayShield Mobile - Session and Secure Storage Manager
 * Uses expo-secure-store for native platforms (iOS/Android)
 * with graceful in-memory/localStorage fallback for web and dev environments.
 */

import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

export interface PayShieldUserProfile {
  id: number;
  full_name?: string;
  phone_number: string;
  is_phone_verified: boolean;
  has_active_device?: boolean;
  linked_accounts_count?: number;
}

const STORAGE_KEYS = {
  TOKEN: "payshield_access_token",
  USER: "payshield_user_profile",
  DEVICE_ID: "payshield_device_id",
};

let activeToken: string | null = null;
let activeUser: PayShieldUserProfile | null = null;
let activeDeviceId: string | null = null;
let onAuthExpiredCallback: (() => void) | null = null;

function generateUUID(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

async function isSecureStoreAvailable(): Promise<boolean> {
  try {
    if (Platform.OS === "web") return false;
    return await SecureStore.isAvailableAsync();
  } catch {
    return false;
  }
}

async function secureSave(key: string, value: string): Promise<void> {
  try {
    const available = await isSecureStoreAvailable();
    if (available) {
      await SecureStore.setItemAsync(key, value);
    } else if (typeof localStorage !== "undefined") {
      localStorage.setItem(key, value);
    }
  } catch (err) {
    console.warn("SecureStore write error:", err);
  }
}

async function secureGet(key: string): Promise<string | null> {
  try {
    const available = await isSecureStoreAvailable();
    if (available) {
      return await SecureStore.getItemAsync(key);
    } else if (typeof localStorage !== "undefined") {
      return localStorage.getItem(key);
    }
  } catch (err) {
    console.warn("SecureStore read error:", err);
  }
  return null;
}

async function secureDelete(key: string): Promise<void> {
  try {
    const available = await isSecureStoreAvailable();
    if (available) {
      await SecureStore.deleteItemAsync(key);
    } else if (typeof localStorage !== "undefined") {
      localStorage.removeItem(key);
    }
  } catch (err) {
    console.warn("SecureStore delete error:", err);
  }
}

export const authStorage = {
  /**
   * Initializes the session by restoring any saved credentials and device ID.
   */
  initSession: async (): Promise<{
    token: string | null;
    user: PayShieldUserProfile | null;
    deviceId: string;
  }> => {
    // 1. Initialize or load device ID
    let deviceId = await secureGet(STORAGE_KEYS.DEVICE_ID);
    if (!deviceId) {
      deviceId = generateUUID();
      await secureSave(STORAGE_KEYS.DEVICE_ID, deviceId);
    }
    activeDeviceId = deviceId;

    // 2. Load stored session
    try {
      const savedToken = await secureGet(STORAGE_KEYS.TOKEN);
      const savedUserJson = await secureGet(STORAGE_KEYS.USER);

      if (savedToken && savedUserJson) {
        activeToken = savedToken;
        activeUser = JSON.parse(savedUserJson) as PayShieldUserProfile;
        return { token: activeToken, user: activeUser, deviceId: activeDeviceId };
      }
    } catch {
      activeToken = null;
      activeUser = null;
    }
    return { token: null, user: null, deviceId: activeDeviceId };
  },

  /**
   * Synchronously retrieves the device ID, generating a fallback UUID if not yet loaded.
   */
  getDeviceId: (): string => {
    if (!activeDeviceId) {
      activeDeviceId = generateUUID();
    }
    return activeDeviceId;
  },

  /**
   * Saves the active token and user profile in memory and persistent secure storage.
   */
  setSession: (token: string, user: PayShieldUserProfile) => {
    activeToken = token;
    activeUser = user;
    secureSave(STORAGE_KEYS.TOKEN, token);
    secureSave(STORAGE_KEYS.USER, JSON.stringify(user));
  },

  /**
   * Synchronously retrieves the active bearer token for immediate API header injection.
   */
  getToken: (): string | null => {
    return activeToken;
  },

  /**
   * Synchronously retrieves the active user profile.
   */
  getUser: (): PayShieldUserProfile | null => {
    return activeUser;
  },

  /**
   * Clears the user authentication session but PRESERVES the device registration ID.
   * Standard logout does not unbind the phone from the account.
   */
  clearSession: () => {
    activeToken = null;
    activeUser = null;
    secureDelete(STORAGE_KEYS.TOKEN);
    secureDelete(STORAGE_KEYS.USER);
    // Note: STORAGE_KEYS.DEVICE_ID is deliberately retained
  },

  isAuthenticated: (): boolean => {
    return activeToken !== null;
  },

  registerAuthExpiredHandler: (callback: () => void) => {
    onAuthExpiredCallback = callback;
  },

  notifyAuthExpired: () => {
    authStorage.clearSession();
    if (onAuthExpiredCallback) {
      onAuthExpiredCallback();
    }
  },
};
