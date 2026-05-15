// EmptyTradesCard — shown on History (Trades view) when /trades returns no
// closed trades in the 7-day window. Ported from screens-states.jsx
// (`kind="no-trades"`).
//
// Visual recipe from the design:
//   - questioning mascot pose
//   - mint-tone slot (the design uses mint; the prior inline state in
//     history.tsx used yellow — Pass 2 corrects this)
//   - body copy explaining the 7-day window
//   - no CTA — the bot opens trades on its own schedule, the user can't
//     force it from here

import React from 'react';
import { Text } from 'react-native';
import { Card } from '@/components/Card';
import { MascotSlot } from '@/mascot/MascotSlot';
import { useTheme } from '@/theme/useTheme';

export function EmptyTradesCard() {
  const theme = useTheme();
  return (
    <Card padding={20} style={{ alignItems: 'center', gap: 14 }}>
      <MascotSlot size={130} pose="questioning" tone="mint" />
      <Text style={{ fontSize: 20, fontWeight: '900', color: theme.text, textAlign: 'center', letterSpacing: -0.3 }}>
        No closed trades yet
      </Text>
      <Text style={{ fontSize: 13, color: theme.textMid, textAlign: 'center', lineHeight: 19, paddingHorizontal: 8 }}>
        Last 7 days. Trades land here as the bot closes them. The strategy can
        take a while to fire — 4-hour signal candles plus the BTC regime gate.
      </Text>
    </Card>
  );
}
