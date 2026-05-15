// Supabase client. Reads URL/anon key from Expo env so the codebase stays
// safe to commit. The anon key is intentionally public-by-design — RLS does
// the real protection on the server side.

import 'react-native-get-random-values';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { createClient } from '@supabase/supabase-js';
import Constants from 'expo-constants';

const env = (Constants.expoConfig?.extra ?? {}) as Record<string, string>;

const SUPABASE_URL =
  process.env.EXPO_PUBLIC_SUPABASE_URL ?? env.supabaseUrl ?? '';
const SUPABASE_ANON_KEY =
  process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY ?? env.supabaseAnonKey ?? '';

export const hasSupabaseCreds =
  SUPABASE_URL.startsWith('https://') && SUPABASE_ANON_KEY.length > 20;

// When creds aren't configured we still export a stub client so the UI can
// render. Calls will reject with a clear error — see authShim below.
export const supabase = hasSupabaseCreds
  ? createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: {
        storage: AsyncStorage,
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: false,
      },
    })
  : (null as never);

export function requireSupabase(): NonNullable<typeof supabase> {
  if (!hasSupabaseCreds) {
    throw new Error(
      'Supabase isn’t configured. Set EXPO_PUBLIC_SUPABASE_URL and EXPO_PUBLIC_SUPABASE_ANON_KEY in app/.env, then restart the bundler.',
    );
  }
  return supabase;
}
