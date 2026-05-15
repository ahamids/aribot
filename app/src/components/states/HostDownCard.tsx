// HostDownCard — the screen the user sees when the iOS app can't reach the
// bot's sidecar over the network. Ported from screens-states.jsx (`kind="host-down"`).
//
// Visual recipe from the design:
//   - panicked mascot pose
//   - peri-tone slot
//   - cable MProp (the bear holding two unplugged cable ends with a yellow spark)
//   - body copy explaining the host is unreachable
//   - Retry CTA — caller wires the actual retry action
//
// Renders as a Card inside whichever screen called it. Per the locked-in
// scope decision in PASSES.md, this is NOT a full-screen takeover.

import React from 'react';
import { Text, View } from 'react-native';
import { Card } from '@/components/Card';
import { Btn } from '@/components/Btn';
import { Icon } from '@/components/Icon';
import { MascotSlot } from '@/mascot/MascotSlot';
import { MProp } from '@/mascot/MProp';
import { AT } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

type Props = {
  onRetry?: () => void;
  detail?: string | null;
};

export function HostDownCard({ onRetry, detail }: Props) {
  const theme = useTheme();
  return (
    <Card padding={20} style={{ alignItems: 'center', gap: 14 }}>
      <MascotSlot size={130} pose="panicked" tone="peri" prop={<MProp kind="cable" />} />
      <Text style={{ fontSize: 20, fontWeight: '900', color: theme.text, textAlign: 'center', letterSpacing: -0.3 }}>
        Can’t reach the bot
      </Text>
      <Text style={{ fontSize: 13, color: theme.textMid, textAlign: 'center', lineHeight: 19, paddingHorizontal: 8 }}>
        The bot’s sidecar isn’t answering. Check Wi-Fi, the bot host URL in Settings, and that the
        sidecar process is still running.
      </Text>
      {detail ? (
        <View
          style={{
            backgroundColor: AT.pnlRedSoft,
            borderRadius: AT.rM,
            paddingHorizontal: 10,
            paddingVertical: 6,
            alignSelf: 'stretch',
          }}
        >
          {/* detail text on pnlRedSoft bg: AT.plum reads correctly in both modes. */}
          <Text style={{ fontSize: 11, color: AT.plum, fontWeight: '600' }}>{detail}</Text>
        </View>
      ) : null}
      {onRetry ? (
        <Btn
          kind="primary"
          size="md"
          icon={<Icon name="refresh" size={18} color="#fff" />}
          onPress={onRetry}
          style={{ alignSelf: 'stretch' }}
        >
          Retry
        </Btn>
      ) : null}
    </Card>
  );
}
