// Auth context. Reads Supabase session, exposes signIn/signUp/signOut, gates
// routing so signed-out users always land on the splash and signed-in users
// who haven't finished onboarding land on the carousel.

import React, {
  createContext,
  ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import type { Session, User } from '@supabase/supabase-js';
import { hasSupabaseCreds, requireSupabase, supabase } from './supabase';
import AsyncStorage from '@react-native-async-storage/async-storage';

const ONBOARDING_DONE_KEY = 'aribot.onboarding.done';

type AuthResult = { ok: true } | { ok: false; error: string };

type AuthState = {
  ready: boolean;
  user: User | null;
  session: Session | null;
  onboardingDone: boolean;
  configured: boolean; // false if Supabase env is missing
  signIn: (email: string, password: string) => Promise<AuthResult>;
  signUp: (email: string, password: string) => Promise<AuthResult>;
  // Magic-link via 6-digit OTP code. Step 1: signInWithOtp sends the email.
  // Step 2: verifyOtp with the code finishes the session.
  requestOtp: (email: string) => Promise<AuthResult>;
  verifyOtp: (email: string, token: string) => Promise<AuthResult>;
  signOut: () => Promise<void>;
  setOnboardingDone: (done: boolean) => Promise<void>;
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [onboardingDone, setOnboarding] = useState(false);

  useEffect(() => {
    let mounted = true;

    (async () => {
      const flag = await AsyncStorage.getItem(ONBOARDING_DONE_KEY);
      if (mounted) setOnboarding(flag === '1');

      if (hasSupabaseCreds) {
        const { data } = await supabase.auth.getSession();
        if (mounted) setSession(data.session ?? null);
      }
      if (mounted) setReady(true);
    })();

    if (!hasSupabaseCreds) return () => { mounted = false; };

    const { data: sub } = supabase.auth.onAuthStateChange((_evt, s) => {
      if (mounted) setSession(s ?? null);
    });
    return () => {
      mounted = false;
      sub.subscription.unsubscribe();
    };
  }, []);

  const value = useMemo<AuthState>(() => ({
    ready,
    user: session?.user ?? null,
    session,
    onboardingDone,
    configured: hasSupabaseCreds,
    async signIn(email, password) {
      try {
        const sb = requireSupabase();
        const { error } = await sb.auth.signInWithPassword({ email, password });
        if (error) return { ok: false, error: error.message };
        return { ok: true };
      } catch (e) {
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    },
    async signUp(email, password) {
      try {
        const sb = requireSupabase();
        const { error } = await sb.auth.signUp({ email, password });
        if (error) return { ok: false, error: error.message };
        return { ok: true };
      } catch (e) {
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    },
    async requestOtp(email) {
      try {
        const sb = requireSupabase();
        // shouldCreateUser:true so this works for first-time sign-ins via OTP
        // too (matches the "Send me a magic link" affordance shown on both
        // sign-in and sign-up screens in the design).
        const { error } = await sb.auth.signInWithOtp({
          email,
          options: { shouldCreateUser: true },
        });
        if (error) return { ok: false, error: error.message };
        return { ok: true };
      } catch (e) {
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    },
    async verifyOtp(email, token) {
      try {
        const sb = requireSupabase();
        const { error } = await sb.auth.verifyOtp({ email, token, type: 'email' });
        if (error) return { ok: false, error: error.message };
        return { ok: true };
      } catch (e) {
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    },
    async signOut() {
      if (hasSupabaseCreds) await supabase.auth.signOut();
      await AsyncStorage.removeItem(ONBOARDING_DONE_KEY);
      setOnboarding(false);
    },
    async setOnboardingDone(done) {
      setOnboarding(done);
      if (done) await AsyncStorage.setItem(ONBOARDING_DONE_KEY, '1');
      else await AsyncStorage.removeItem(ONBOARDING_DONE_KEY);
    },
  }), [ready, session, onboardingDone]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
