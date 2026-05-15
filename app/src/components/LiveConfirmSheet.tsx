// LIVE-mode confirmation sheet. Modal that appears when the user taps START
// while the bot is configured for LIVE mode (i.e. real-money orders). The
// design's guardrail: serious mascot, summary of "what's about to happen",
// type-LIVE-to-confirm. Slide-to-confirm would be nicer but typing is more
// universally accessible and matches the design's annotated callout.

import React, { useState } from 'react';
import { Modal, Pressable, Text, View } from 'react-native';
import { Btn } from './Btn';
import { Input } from './Input';
import { Card } from './Card';
import { Icon } from './Icon';
import { MascotSlot } from '@/mascot/MascotSlot';
import { AT, stickerShadow } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

type Props = {
  visible: boolean;
  onDismiss: () => void;
  onConfirm: () => void;
  busy?: boolean;
};

export function LiveConfirmSheet({ visible, onDismiss, onConfirm, busy }: Props) {
  const [typed, setTyped] = useState('');
  const canConfirm = typed.trim().toUpperCase() === 'LIVE' && !busy;
  const theme = useTheme();

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onDismiss}>
      <View
        style={{
          flex: 1,
          // Scrim is intentionally always the same dark plum overlay — it
          // provides a consistent "lift" effect against either light or dark
          // mode underneath.
          backgroundColor: 'rgba(45,31,71,0.45)',
          justifyContent: 'flex-end',
        }}
      >
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Dismiss"
          onPress={onDismiss}
          style={{ flex: 1 }}
        />
        <View
          style={[
            {
              backgroundColor: theme.bg,
              borderTopLeftRadius: AT.rXL,
              borderTopRightRadius: AT.rXL,
              borderWidth: AT.ol3,
              borderColor: theme.outline,
              paddingHorizontal: 18,
              paddingTop: 14,
              paddingBottom: 30,
              gap: 14,
            },
            stickerShadow(theme.shadowHard),
          ]}
        >
          {/* Drag handle */}
          <View
            style={{
              alignSelf: 'center',
              width: 44,
              height: 5,
              borderRadius: 3,
              backgroundColor: theme.textSoft,
              marginBottom: 6,
            }}
          />

          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
            <MascotSlot size={84} pose="serious" tone="coral" />
            <View style={{ flex: 1 }}>
              <Text style={{ fontSize: 22, fontWeight: '900', color: theme.text, letterSpacing: -0.4 }}>
                Start in <Text style={{ color: AT.pnlRed }}>LIVE</Text> mode?
              </Text>
              <Text style={{ fontSize: 13, color: theme.textMid, lineHeight: 18, marginTop: 2 }}>
                Aribot will submit real orders on Bybit using your trade keys.
              </Text>
            </View>
          </View>

          <Card color={AT.pnlRedSoft} padding={14}>
            <View style={{ flexDirection: 'row', gap: 10, alignItems: 'flex-start' }}>
              <View
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: 14,
                  backgroundColor: AT.pnlRed,
                  borderWidth: AT.ol2,
                  borderColor: AT.plum,
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Icon name="bolt" size={16} color="#fff" />
              </View>
              {/* Text on pnlRedSoft bg stays plum in both modes. */}
              <Text style={{ flex: 1, fontSize: 12, color: AT.plum, lineHeight: 18 }}>
                Open positions can lose value. The kill switch on Settings stops the bot at the
                next cycle.
              </Text>
            </View>
          </Card>

          <Input
            label="TYPE LIVE TO CONFIRM"
            value={typed}
            onChangeText={setTyped}
            placeholder="LIVE"
            autoCapitalize="characters"
            monospace
          />

          <View style={{ flexDirection: 'row', gap: 10 }}>
            <View style={{ flex: 1 }}>
              <Btn kind="soft" size="md" onPress={onDismiss}>
                Cancel
              </Btn>
            </View>
            <View style={{ flex: 2 }}>
              <Btn kind="danger" size="md" onPress={onConfirm} disabled={!canConfirm} loading={busy}>
                Start LIVE
              </Btn>
            </View>
          </View>
        </View>
      </View>
    </Modal>
  );
}
