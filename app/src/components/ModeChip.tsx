// ModeChip — PAPER / SHADOW / LIVE pill. LIVE uses pure red (allowed under
// the PnL/direction/kill-switch/LIVE-warning reservation rule).

import React from 'react';
import { Pressable, Text } from 'react-native';
import { AT, stickerShadow } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

export type Mode = 'PAPER' | 'SHADOW' | 'LIVE';

const COLORS: Record<Mode, { bg: string; fg: string }> = {
  PAPER:  { bg: AT.peri,    fg: '#fff' },
  SHADOW: { bg: AT.yellow,  fg: AT.plum },
  LIVE:   { bg: AT.pnlRed,  fg: '#fff' },
};

export function ModeChip({
  mode,
  active = true,
  onPress,
}: {
  mode: Mode;
  active?: boolean;
  onPress?: () => void;
}) {
  const c = COLORS[mode];
  const theme = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole={onPress ? 'button' : undefined}
      accessibilityLabel={`Mode ${mode}`}
      style={[
        {
          paddingHorizontal: 12,
          paddingVertical: 6,
          borderRadius: AT.rPill,
          backgroundColor: active ? c.bg : theme.card,
          borderWidth: AT.ol2,
          borderColor: theme.outline,
        },
        active && stickerShadow(theme.shadowHard),
      ]}
    >
      <Text
        style={{
          // Active chip uses the accent's own fg color (white on peri/red,
          // plum on yellow) — those are designed to read against the hue
          // regardless of theme. Inactive chip flips with the theme.
          color: active ? c.fg : theme.text,
          fontWeight: '800',
          fontSize: 12,
          letterSpacing: 0.6,
        }}
      >
        {mode}
      </Text>
    </Pressable>
  );
}
