// MascotSlot — reusable circular frame the character drops into. Swap the
// <Bear> inside for a custom character later; every screen picks it up.

import React, { ReactNode } from 'react';
import { View, ViewStyle, AccessibilityProps } from 'react-native';
import { Bear, BearPose } from './Bear';
import { AT, stickerShadow, ambientShadow } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

export type MascotTone = 'yellow' | 'mint' | 'peri' | 'coral' | 'cream' | 'plum';

const TONE_BG: Record<MascotTone, string> = {
  yellow: AT.yellow,
  mint: AT.mint,
  peri: AT.peri,
  coral: AT.coral,
  cream: AT.creamDeep,
  plum: AT.plumMid,
};

type Props = {
  size?: number;
  pose?: BearPose;
  tone?: MascotTone;
  frame?: boolean;
  prop?: ReactNode;
  style?: ViewStyle;
} & AccessibilityProps;

export function MascotSlot({
  size = 120,
  pose = 'alert',
  tone = 'yellow',
  frame = true,
  prop,
  style,
  accessibilityLabel,
  ...a11y
}: Props) {
  const theme = useTheme();
  return (
    <View
      accessible
      accessibilityRole="image"
      accessibilityLabel={accessibilityLabel ?? `Mascot, ${pose}`}
      {...a11y}
      style={[
        {
          width: size,
          height: size,
          alignItems: 'center',
          justifyContent: 'center',
        },
        style,
      ]}
    >
      {frame && (
        <View
          style={[
            {
              position: 'absolute',
              width: size,
              height: size,
              borderRadius: size / 2,
              backgroundColor: TONE_BG[tone],
              borderWidth: AT.ol4,
              // Outline stays plum even in dark mode — the mascot frame is
              // a sticker against the surface, not a surface itself, and the
              // plum reads as the bear's "ink line" identity.
              borderColor: AT.plum,
            },
            // Hard shadow flips for visibility: plum-on-cream in light,
            // black-on-darkBg in dark.
            stickerShadow(theme.shadowHard),
            ambientShadow(),
          ]}
        />
      )}
      <View
        style={{
          width: size * 0.78,
          height: size * 0.78,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Bear pose={pose} />
        {prop}
      </View>
    </View>
  );
}
