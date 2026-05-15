// ChartEmptyCard — shown on History → Equity view during the initial load
// before the sidecar response arrives, OR when equity data is so sparse that
// rendering a curve would be misleading. Ported from screens-states.jsx
// (`kind="chart-empty"`).
//
// Visual recipe from the design:
//   - alert mascot pose
//   - yellow-tone slot
//   - chart MProp (bear holding an upside-down chart)
//   - quiet "warming up" copy
//   - no CTA — the user can't do anything but wait

import React from 'react';
import { Text } from 'react-native';
import { Card } from '@/components/Card';
import { MascotSlot } from '@/mascot/MascotSlot';
import { MProp } from '@/mascot/MProp';
import { useTheme } from '@/theme/useTheme';

export function ChartEmptyCard() {
  const theme = useTheme();
  return (
    <Card padding={20} style={{ alignItems: 'center', gap: 14 }}>
      <MascotSlot size={120} pose="alert" tone="yellow" prop={<MProp kind="chart" />} />
      <Text
        style={{
          fontSize: 18,
          fontWeight: '900',
          color: theme.text,
          textAlign: 'center',
          letterSpacing: -0.3,
        }}
      >
        Warming up
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
        Equity curve appears here as the bot closes trades. With fewer than two
        data points there isn’t a meaningful line to draw yet.
      </Text>
    </Card>
  );
}
