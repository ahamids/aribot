// Root layout — owns providers + the auth/onboarding gate. Renders the right
// route group based on session + onboarding flag, so screens don't need to
// know about routing logic themselves.

import React, { useEffect } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import { Stack, useRouter, useSegments } from 'expo-router';
import { AuthProvider, useAuth } from '@/lib/auth';
import { useTheme } from '@/theme/useTheme';

function Gate() {
  const { ready, user, onboardingDone, configured } = useAuth();
  const segments = useSegments();
  const router = useRouter();
  const theme = useTheme();

  useEffect(() => {
    if (!ready) return;

    const top = segments[0] ?? '';
    // Unauthenticated → must be on (auth) group; default to splash.
    if (!user) {
      if (top !== '(auth)') router.replace('/');
      return;
    }
    // Authenticated but not onboarded → onboarding carousel + setup screens.
    if (user && !onboardingDone) {
      if (top !== '(onboarding)') router.replace('/(onboarding)/welcome');
      return;
    }
    // Onboarded → land on the dashboard (main tabbed app). Settings can send
    // the user back to onboarding via setOnboardingDone(false).
    if (user && onboardingDone) {
      if (top !== '(app)') router.replace('/(app)/dashboard');
    }
  }, [ready, user, onboardingDone, segments]);

  if (!ready) {
    return (
      <View style={{ flex: 1, backgroundColor: theme.bg, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator color={theme.text} />
      </View>
    );
  }

  return (
    <Stack
      screenOptions={{
        headerShown: false,
        animation: 'slide_from_right',
        contentStyle: { backgroundColor: theme.bg },
      }}
    />
  );
}

export default function RootLayout() {
  const theme = useTheme();
  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: theme.bg }}>
      <SafeAreaProvider>
        {/* `style="auto"` lets iOS choose dark text on light bg and light
            text on dark bg. Hard-coding "dark" reversed the status bar text
            against our cream bg in light mode (correct) but broke dark mode. */}
        <StatusBar style="auto" />
        <AuthProvider>
          <Gate />
        </AuthProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
