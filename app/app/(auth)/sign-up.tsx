// Sign up. Email + password + confirm + on-device encryption acknowledgment.
// Wired to Supabase via useAuth().signUp.

import React, { useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Screen } from '@/components/Screen';
import { Btn } from '@/components/Btn';
import { Input } from '@/components/Input';
import { AuthErrorCard } from '@/components/states/AuthErrorCard';
import { MascotSlot } from '@/mascot/MascotSlot';
import { Icon } from '@/components/Icon';
import { AT } from '@/theme/tokens';
import { useAuth } from '@/lib/auth';

export default function SignUp() {
  const router = useRouter();
  const { signUp, requestOtp } = useAuth();
  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [otpBusy, setOtpBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pwTooShort = pw.length > 0 && pw.length < 12;
  const pwMismatch = pw2.length > 0 && pw !== pw2;
  const canSubmit =
    email.includes('@') && pw.length >= 12 && pw === pw2 && ack && !busy;

  async function submit() {
    setBusy(true);
    setError(null);
    const r = await signUp(email.trim(), pw);
    setBusy(false);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    router.replace('/(onboarding)/welcome');
  }

  async function sendMagicLink() {
    const e = email.trim();
    if (!e.includes('@')) {
      setError('Enter your email first, then tap "email me a 6-digit code".');
      return;
    }
    if (!ack) {
      setError('Acknowledge the encryption notice first.');
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
      <View style={{ alignItems: 'center', marginTop: 8, marginBottom: 16 }}>
        <MascotSlot size={130} pose="waving" tone="mint" />
      </View>
      <Text style={{ fontSize: 30, fontWeight: '900', letterSpacing: -0.6, textAlign: 'center', color: AT.plum }}>
        Make an account
      </Text>
      <Text style={{ fontSize: 14, color: AT.plumMid, textAlign: 'center', marginTop: 4, marginBottom: 22 }}>
        So we can sync your settings across devices.
      </Text>

      <View style={{ gap: 14 }}>
        <Input
          label="EMAIL"
          value={email}
          onChangeText={setEmail}
          placeholder="alex@trader.co"
          keyboardType="email-address"
          autoComplete="email"
          textContentType="emailAddress"
        />
        <Input
          label="PASSWORD"
          value={pw}
          onChangeText={setPw}
          placeholder="At least 12 characters"
          secure
          hint={pwTooShort ? 'Needs at least 12 characters.' : 'At least 12 characters.'}
          error={pwTooShort}
          textContentType="newPassword"
        />
        <Input
          label="CONFIRM PASSWORD"
          value={pw2}
          onChangeText={setPw2}
          secure
          error={pwMismatch}
          hint={pwMismatch ? 'Passwords don’t match.' : undefined}
          textContentType="newPassword"
        />

        <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 10, marginTop: 4 }}>
          <Btn
            kind={ack ? 'primary' : 'soft'}
            size="sm"
            onPress={() => setAck(a => !a)}
            accessibilityLabel="I understand keys are encrypted on this device"
            style={{ width: 28, alignSelf: 'flex-start' }}
          >
            <Icon name="check" size={16} color={ack ? '#fff' : AT.plum} />
          </Btn>
          <Text style={{ flex: 1, fontSize: 12, color: AT.plumMid, lineHeight: 18 }}>
            I understand that my Bybit keys will be{' '}
            <Text style={{ color: AT.plum, fontWeight: '800' }}>encrypted on this device</Text>.
            Aribot never sees them.
          </Text>
        </View>

        {error ? (
          <AuthErrorCard message={error} onRetry={() => setError(null)} />
        ) : null}

        <Btn kind="primary" disabled={!canSubmit} loading={busy} onPress={submit}>
          Create account →
        </Btn>

        <Pressable
          onPress={sendMagicLink}
          disabled={otpBusy || busy}
          accessibilityRole="button"
          accessibilityLabel="Send me a magic link"
          hitSlop={8}
        >
          <Text style={{ fontSize: 13, color: AT.plumMid, textAlign: 'center', marginTop: 6 }}>
            Or{' '}
            <Text style={{ color: AT.coralDeep, fontWeight: '800' }}>
              {otpBusy ? 'sending…' : 'email me a 6-digit code'}
            </Text>
          </Text>
        </Pressable>
      </View>
    </Screen>
  );
}
