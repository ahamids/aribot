// Onboarding done — bridge to the dashboard. Kept as a route so that
// `setOnboardingDone(true)` from vault.tsx has somewhere safe to land
// during the brief moment before the root layout's gate redirects to
// /(app)/dashboard.

import React, { useEffect } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { useRouter } from 'expo-router';
import { AT } from '@/theme/tokens';

export default function OnboardingDone() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/(app)/dashboard');
  }, [router]);
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: AT.cream }}>
      <ActivityIndicator color={AT.plum} />
    </View>
  );
}
