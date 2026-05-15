// Notification preferences. Persisted to AsyncStorage.
//
// IMPORTANT: this file ONLY manages the user's stated preference. It does NOT
// register for push notifications or emit them. APNs registration requires a
// dev client (Expo Go can't do it), and we don't have a notification-emitting
// service yet. Toggles persist; effects are future work.
//
// Scoped per-Supabase-user via a key suffix so multi-account sign-in on the
// same device doesn't cross prefs. If the caller doesn't pass userId, we fall
// back to a shared "device" namespace.

import AsyncStorage from '@react-native-async-storage/async-storage';

export type NotificationPrefs = {
  fillAlerts: boolean;
  errorAlerts: boolean;
  dailySummary: boolean;
};

export const DEFAULT_PREFS: NotificationPrefs = {
  fillAlerts: true,
  errorAlerts: true,
  dailySummary: false,
};

function keyFor(userId?: string | null): string {
  return `aribot.notif.prefs.${userId ?? 'device'}`;
}

export async function loadNotificationPrefs(userId?: string | null): Promise<NotificationPrefs> {
  try {
    const raw = await AsyncStorage.getItem(keyFor(userId));
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw) as Partial<NotificationPrefs>;
    return {
      fillAlerts: parsed.fillAlerts ?? DEFAULT_PREFS.fillAlerts,
      errorAlerts: parsed.errorAlerts ?? DEFAULT_PREFS.errorAlerts,
      dailySummary: parsed.dailySummary ?? DEFAULT_PREFS.dailySummary,
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

export async function saveNotificationPrefs(
  prefs: NotificationPrefs,
  userId?: string | null,
): Promise<void> {
  try {
    await AsyncStorage.setItem(keyFor(userId), JSON.stringify(prefs));
  } catch {
    // Storage write failures are silently swallowed — the UI keeps the new
    // in-memory state so users still see the toggle they flipped.
  }
}
