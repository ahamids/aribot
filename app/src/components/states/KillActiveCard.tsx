// KillActiveCard — shown when the bot's status reports `killed` (kill switch
// is on disk). Ported from screens-states.jsx (`kind="kill-active"`).
//
// Visual recipe from the design:
//   - serious mascot pose (bear with flat mouth, no smile — this is grave)
//   - cream-tone slot
//   - flag MProp (small red flag held up in the bear's right hand)
//   - Open Settings CTA so the user can clear the switch
//
// Per the locked-in scope decision, this is a Card inside whichever screen
// called it, not a full-screen takeover. Each screen that wants to surface
// the kill-active state renders this in place of its primary data.

import React from 'react';
import { Text } from 'react-native';
import { useRouter } from 'expo-router';
import { Card } from '@/components/Card';
import { Btn } from '@/components/Btn';
import { Icon } from '@/components/Icon';
import { MascotSlot } from '@/mascot/MascotSlot';
import { MProp } from '@/mascot/MProp';
import { useTheme } from '@/theme/useTheme';

export function KillActiveCard() {
  const router = useRouter();
  const theme = useTheme();
  return (
    <Card padding={20} style={{ alignItems: 'center', gap: 14 }}>
      <MascotSlot size={130} pose="serious" tone="cream" prop={<MProp kind="flag" />} />
      <Text style={{ fontSize: 20, fontWeight: '900', color: theme.text, textAlign: 'center', letterSpacing: -0.3 }}>
        Kill switch is tripped
      </Text>
      <Text style={{ fontSize: 13, color: theme.textMid, textAlign: 'center', lineHeight: 19, paddingHorizontal: 8 }}>
        The bot is refusing to take new orders. Clear the switch from Settings → Safety when
        you’re ready to resume.
      </Text>
      <Btn
        kind="primary"
        size="md"
        icon={<Icon name="settings" size={18} color="#fff" />}
        onPress={() => router.push('/(app)/settings')}
        style={{ alignSelf: 'stretch' }}
      >
        Open Settings
      </Btn>
    </Card>
  );
}
