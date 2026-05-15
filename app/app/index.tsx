// Splash / welcome. Mascot front and center, app name, two CTAs.
// Ported visually from screens-onboarding.jsx <Splash/>.

import React from 'react';
import { Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Screen } from '@/components/Screen';
import { Btn } from '@/components/Btn';
import { MascotSlot } from '@/mascot/MascotSlot';
import { AT } from '@/theme/tokens';
import { useAuth } from '@/lib/auth';

export default function Splash() {
  const router = useRouter();
  const { configured } = useAuth();

  return (
    <Screen scroll={false}>
      <View
        style={{
          flex: 1,
          alignItems: 'center',
          justifyContent: 'center',
          gap: 28,
          paddingHorizontal: 14,
        }}
      >
        {/* Decorative blobs, matching the splash design. */}
        <View style={{ width: 200, height: 220, alignItems: 'center', justifyContent: 'center' }}>
          <Blob size={30} color={AT.coral} style={{ top: 8, left: 6 }} />
          <Blob size={22} color={AT.peri} style={{ top: 48, right: -6 }} />
          <Blob size={18} color={AT.mint} square style={{ bottom: 28, right: 12 }} />
          <MascotSlot size={200} pose="waving" tone="yellow" />
        </View>

        <View style={{ alignItems: 'center' }}>
          <Text style={{ fontSize: 56, fontWeight: '900', letterSpacing: -2, color: AT.plum, lineHeight: 60 }}>
            Ari<Text style={{ color: AT.coralDeep }}>bot</Text>
          </Text>
          <Text style={{ fontSize: 16, color: AT.plumMid, marginTop: 10, fontWeight: '600' }}>
            Your friendly trading bot — on your terms.
          </Text>
        </View>

        <View style={{ alignSelf: 'stretch', gap: 12 }}>
          <Btn kind="primary" onPress={() => router.push('/(auth)/sign-up')}>
            Create account
          </Btn>
          <Btn kind="soft" onPress={() => router.push('/(auth)/sign-in')}>
            I already have one
          </Btn>
        </View>

        <Text style={{ fontSize: 11, color: AT.plumMid, textAlign: 'center' }}>
          BYO server · keys encrypted on-device · v0.1
          {!configured ? '  ·  Supabase not configured' : ''}
        </Text>
      </View>
    </Screen>
  );
}

function Blob({
  size,
  color,
  square,
  style,
}: {
  size: number;
  color: string;
  square?: boolean;
  style: object;
}) {
  return (
    <View
      pointerEvents="none"
      style={[
        {
          position: 'absolute',
          width: size,
          height: size,
          borderRadius: square ? 6 : size / 2,
          backgroundColor: color,
          borderWidth: 2,
          borderColor: AT.plum,
        },
        style,
      ]}
    />
  );
}
