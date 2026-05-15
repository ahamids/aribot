// Verify magic-link OTP code. Lands here after sign-in or sign-up tapped
// "Send me a magic link" — Supabase emailed a 6-digit code, user types it
// in, we call verifyOtp to complete the session.
//
// Per the Pass 2 scope decision, we use the OTP code path (not a deep-link
// redirect). Simpler routing; small friction cost (user types 6 digits) vs.
// "tap the link in the email." Easy to swap to deep links later by adding
// a redirect URL allow-list in Supabase + an app/auth-callback.tsx route.

import React, { useEffect, useState } from 'react';
import { Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Screen } from '@/components/Screen';
import { Btn } from '@/components/Btn';
import { Input } from '@/components/Input';
import { Card } from '@/components/Card';
import { MascotSlot } from '@/mascot/MascotSlot';
import { AT } from '@/theme/tokens';
import { useAuth } from '@/lib/auth';

const RESEND_COOLDOWN_SECS = 60;

export default function VerifyCode() {
  const router = useRouter();
  const params = useLocalSearchParams<{ email?: string }>();
  const email = (params.email ?? '').trim();
  const { verifyOtp, requestOtp } = useAuth();

  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [resendBusy, setResendBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(RESEND_COOLDOWN_SECS);

  // Resend rate-limit countdown — Supabase enforces ~60s between OTP requests
  // per email. Show the user when they can re-request rather than letting
  // them spam it.
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setInterval(() => setCooldown(c => Math.max(0, c - 1)), 1000);
    return () => clearInterval(t);
  }, [cooldown]);

  async function submit() {
    const t = code.trim();
    if (t.length !== 6 || !/^\d+$/.test(t)) {
      setError('Enter the 6-digit code from the email.');
      return;
    }
    setBusy(true);
    setError(null);
    const r = await verifyOtp(email, t);
    setBusy(false);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    // Gate in app/_layout.tsx will redirect to onboarding/dashboard.
    router.replace('/');
  }

  async function resend() {
    if (cooldown > 0) return;
    setResendBusy(true);
    setError(null);
    const r = await requestOtp(email);
    setResendBusy(false);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    setCooldown(RESEND_COOLDOWN_SECS);
  }

  if (!email) {
    // Defensive: user landed here without an email param. Bounce back.
    return (
      <Screen showBack>
        <Text style={{ color: AT.plumMid, textAlign: 'center', marginTop: 40 }}>
          Missing email. Go back and try again.
        </Text>
      </Screen>
    );
  }

  return (
    <Screen showBack>
      <View style={{ alignItems: 'center', marginTop: 8, marginBottom: 16 }}>
        <MascotSlot size={130} pose="alert" tone="mint" />
      </View>
      <Text style={{ fontSize: 28, fontWeight: '900', letterSpacing: -0.6, textAlign: 'center', color: AT.plum }}>
        Check your email
      </Text>
      <Text style={{ fontSize: 14, color: AT.plumMid, textAlign: 'center', marginTop: 4, marginBottom: 22, paddingHorizontal: 16, lineHeight: 19 }}>
        We sent a 6-digit code to{'\n'}
        <Text style={{ color: AT.plum, fontWeight: '700' }}>{email}</Text>
      </Text>

      <View style={{ gap: 14 }}>
        <Input
          label="6-DIGIT CODE"
          value={code}
          onChangeText={setCode}
          placeholder="123456"
          keyboardType="number-pad"
          autoComplete="one-time-code"
          textContentType="oneTimeCode"
          monospace
        />

        {error ? (
          <Card color={AT.pnlRedSoft} padding={12}>
            <Text style={{ color: AT.plum, fontWeight: '700', fontSize: 13 }}>Couldn’t verify</Text>
            <Text style={{ color: AT.plumMid, fontSize: 12, marginTop: 2 }}>{error}</Text>
          </Card>
        ) : null}

        <Btn
          kind="primary"
          loading={busy}
          onPress={submit}
          disabled={code.trim().length !== 6}
        >
          Verify &amp; sign in
        </Btn>

        <Btn
          kind="soft"
          size="md"
          onPress={resend}
          disabled={cooldown > 0 || resendBusy}
          loading={resendBusy}
        >
          {cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend code'}
        </Btn>
      </View>
    </Screen>
  );
}
