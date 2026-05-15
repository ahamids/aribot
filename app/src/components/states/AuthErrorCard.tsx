// AuthErrorCard — shown when sign-in or sign-up rejects the user's
// credentials. Ported from screens-states.jsx (`kind="auth-error"`).
//
// Visual recipe from the design:
//   - questioning mascot pose
//   - yellow-tone slot
//   - body copy explaining the failure
//   - Try-again CTA — caller wires the actual retry action
//
// Per Pass 4 scope: this card is only wired to sign-in/sign-up. verify-code
// already has a proper error card and stays as-is.

import React from 'react';
import { Text } from 'react-native';
import { Card } from '@/components/Card';
import { Btn } from '@/components/Btn';
import { MascotSlot } from '@/mascot/MascotSlot';
import { useTheme } from '@/theme/useTheme';

type Props = {
  message: string;
  onRetry?: () => void;
};

export function AuthErrorCard({ message, onRetry }: Props) {
  const theme = useTheme();
  return (
    <Card padding={20} style={{ alignItems: 'center', gap: 14 }}>
      <MascotSlot size={110} pose="questioning" tone="yellow" />
      <Text
        style={{
          fontSize: 18,
          fontWeight: '900',
          color: theme.text,
          textAlign: 'center',
          letterSpacing: -0.3,
        }}
      >
        Couldn’t sign you in
      </Text>
      <Text
        style={{
          fontSize: 13,
          color: theme.textMid,
          textAlign: 'center',
          lineHeight: 19,
          paddingHorizontal: 8,
        }}
      >
        {message}
      </Text>
      {onRetry ? (
        <Btn kind="primary" size="md" onPress={onRetry} style={{ alignSelf: 'stretch' }}>
          Try again
        </Btn>
      ) : null}
    </Card>
  );
}
