// Money — tabular numeric display with PnL-color rule baked in. Reserve red
// (#E5484D) and green (#30A46C) for PnL/direction/kill switch — this is the
// only place those colors should be applied to text.
//
// Ported from the design's components.jsx <Money>. Uses tabular figures
// on the iOS side via the SF Pro Rounded face (RN doesn't expose
// fontVariant tabular-nums universally; iOS rounded already has tabular
// digits by default).

import React from 'react';
import { StyleProp, Text, TextStyle } from 'react-native';
import { AT } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

type Props = {
  value: number;
  size?: number;
  weight?: TextStyle['fontWeight'];
  prefix?: string;
  signed?: boolean;
  style?: StyleProp<TextStyle>;
};

export function Money({
  value,
  size = 40,
  weight = '800',
  prefix = '$',
  signed = true,
  style,
}: Props) {
  const theme = useTheme();
  const v = Number.isFinite(value) ? value : 0;
  const isPos = v >= 0;
  // PnL colors don't change in dark mode (reservation rule). Only the
  // unsigned `text` variant follows the theme.
  const color = signed ? (isPos ? AT.pnlGreen : AT.pnlRed) : theme.text;
  const sign = signed ? (isPos ? '+' : '−') : '';
  const abs = Math.abs(v).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return (
    <Text
      style={[
        {
          color,
          fontSize: size,
          fontWeight: weight,
          letterSpacing: -0.5,
        },
        style,
      ]}
      accessibilityLabel={`${signed ? (isPos ? 'positive ' : 'negative ') : ''}${prefix}${abs}`}
    >
      {sign}
      {prefix}
      {abs}
    </Text>
  );
}
