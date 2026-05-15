// Sign in. Mascot peeks over a "fence" — the playful chrome of the design.

import React, { useState } from 'react';
import { Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Screen } from '@/components/Screen';
import { Btn } from '@/components/Btn';
import { Input } from '@/components/Input';
import { AuthErrorCard } from '@/components/states/AuthErrorCard';
import { MascotSlot } from '@/mascot/MascotSlot';
import { AT } from '@/theme/tokens';
import { useAuth } from '@/lib/auth';

export default function SignIn() {
  const router = useRouter();
  const { signIn, requestOtp } = useAuth();
  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [busy, setBusy] = useState(false);
  const [otpBusy, setOtpBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    const r = await signIn(email.trim(), pw);
    setBusy(false);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    // _layout's Gate effect will redirect into onboarding/main on session change.
    router.replace('/');
  }

  async function sendMagicLink() {
    const e = email.trim();
    if (!e.includes('@')) {
      setError('Enter your email first, then tap "Email me a 6-digit code".');
      return;
    }
    setOtpBusy(true);
    setError(null);
    const r = await requestOtp(e);
    setOtpBusy(false);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    router.push(`/(auth)/verify-code?email=${encodeURIComponent(e)}` as never);
  }

  return (
    <Screen showBack>
      {/* Peeking mascot — only the top half is visible above the "fence". */}
      <View style={{ alignItems: 'center', marginTop: 8, marginBottom: 16, height: 120, position: 'relative' }}>
        <View
          style={{
            position: 'absolute',
            top: 30,
            width: 140,
            height: 80,
            borderRadius: 80,
            overflow: 'hidden',
            alignItems: 'center',
          }}
        >
          <MascotSlot size={140} pose="wink" tone="peri" />
        </View>
        <View
          pointerEvents="none"
          style={{
            position: 'absolute',
            bottom: 0,
            left: 60,
            right: 60,
            height: 8,
            backgroundColor: AT.plum,
            borderRadius: 4,
          }}
        />
      </View>

      <Text style={{ fontSize: 30, fontWeight: '900', letterSpacing: -0.6, textAlign: 'center', color: AT.plum }}>
        Welcome back
      </Text>
      <Text style={{ fontSize: 14, color: AT.plumMid, textAlign: 'center', marginTop: 4, marginBottom: 22 }}>
        Quick check before you trade.
      </Text>

      <View style={{ gap: 14 }}>
        <Input
          label="EMAIL"
          value={email}
          onChangeText={setEmail}
          keyboardType="email-address"
          autoComplete="email"
          textContentType="username"
        />
        <Input
          label="PASSWORD"
          value={pw}
          onChangeText={setPw}
          secure
          textContentType="password"
        />
        {error ? (
          <AuthErrorCard message={error} onRetry={() => setError(null)} />
        ) : null}
        <Btn kind="primary" loading={busy} onPress={submit} disabled={!email.includes('@') || !pw}>
          Sign in
        </Btn>
        <Btn
          kind="soft"
          loading={otpBusy}
          disabled={otpBusy || busy}
          onPress={sendMagicLink}
        >
          Email me a 6-digit code
        </Btn>
        <Text style={{ fontSize: 13, color: AT.plumMid, textAlign: 'center', marginTop: 6 }}>
          Forgot your password?
        </Text>
      </View>
    </Screen>
  );
}
