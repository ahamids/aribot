// EmptyPositionsCard — shown on Positions and Dashboard preview when the bot
// has no open positions. Ported from screens-states.jsx (`kind="no-positions"`).
//
// Visual recipe from the design:
//   - napping mascot pose (bear with closed eyes + Zzz extras)
//   - cream-tone slot
//   - "Wake the bot" CTA implicitly hints at the dashboard's start button
//
// The CTA is optional — on the Dashboard preview a "Wake" button would be
// redundant (the start button is right above it), so the dashboard renders
// this card without a CTA. On the Positions tab the CTA navigates back to
// the Dashboard.

import React from 'react';
import { Text } from 'react-native';
import { useRouter } from 'expo-router';
import { Card } from '@/components/Card';
import { Btn } from '@/components/Btn';
import { Icon } from '@/components/Icon';
import { MascotSlot } from '@/mascot/MascotSlot';
import { useTheme } from '@/theme/useTheme';

type Props = {
  // When true, render the "Wake the bot" CTA that navigates to Home.
  // Default false because Dashboard's preview already shows the start button.
  showCta?: boolean;
};

export function EmptyPositionsCard({ showCta = false }: Props) {
  const router = useRouter();
  const theme = useTheme();
  return (
    <Card padding={20} style={{ alignItems: 'center', gap: 14 }}>
      <MascotSlot size={130} pose="napping" tone="cream" />
      <Text style={{ fontSize: 20, fontWeight: '900', color: theme.text, textAlign: 'center', letterSpacing: -0.3 }}>
        No open positions
      </Text>
      <Text style={{ fontSize: 13, color: theme.textMid, textAlign: 'center', lineHeight: 19, paddingHorizontal: 8 }}>
        Pull down to refresh, or wait for the next 4-hour signal window. The bot only opens
        positions when the BTC regime gate agrees.
      </Text>
      {showCta ? (
        <Btn
          kind="primary"
          size="md"
          icon={<Icon name="bolt" size={18} color="#fff" />}
          onPress={() => router.push('/(app)/dashboard')}
          style={{ alignSelf: 'stretch' }}
        >
          Wake the bot
        </Btn>
      ) : null}
    </Card>
  );
}
