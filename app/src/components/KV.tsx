// KV — small label-over-value cell used in position cards and history stats.
// `danger=true` colors the value pure red (PnL/direction/kill-switch rule).

import React from 'react';
import { Text, View } from 'react-native';
import { AT } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

type Props = {
  label: string;
  value: string;
  danger?: boolean;
};

export function KV({ label, value, danger }: Props) {
  const theme = useTheme();
  return (
    <View>
      <Text style={{ fontSize: 10, fontWeight: '800', letterSpacing: 0.7, color: theme.textMid }}>
        {label}
      </Text>
      <Text
        style={{
          fontSize: 14,
          fontWeight: '800',
          color: danger ? AT.pnlRed : theme.text,
        }}
      >
        {value}
      </Text>
    </View>
  );
}
