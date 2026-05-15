// PositionRow — one row in a positions list. Symbol + side chip on top,
// size/entry on the left, mark on the right, PnL right-aligned and color-
// coded. Dashed divider beneath; the last row in a list should hide it.

import React from 'react';
import { Text, View } from 'react-native';
import { useTheme } from '@/theme/useTheme';
import { Money } from './Money';
import { SideChip, type Side } from './SideChip';

// Re-export for callers that imported `Side` from this module historically.
export type { Side };

export type PositionRowData = {
  symbol: string;
  side: Side;
  size: number | string;
  entry: number | string;
  mark?: number | string | null;
  pnl: number;
};

export function PositionRow({
  p,
  dense = false,
  hideDivider = false,
}: {
  p: PositionRowData;
  dense?: boolean;
  hideDivider?: boolean;
}) {
  const theme = useTheme();
  return (
    <View
      style={{
        paddingVertical: dense ? 12 : 14,
        borderBottomWidth: hideDivider ? 0 : 1.5,
        borderBottomColor: theme.divider,
        borderStyle: 'dashed',
      }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <Text style={{ fontSize: 17, fontWeight: '800', color: theme.text, letterSpacing: -0.2 }}>
            {p.symbol}
          </Text>
          <SideChip side={p.side} />
        </View>
        <Money value={p.pnl} size={17} />
      </View>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 2 }}>
        <Text style={{ fontSize: 12, color: theme.textMid }}>
          {p.size} @ ${p.entry}
        </Text>
        {p.mark != null ? (
          <Text style={{ fontSize: 12, color: theme.textMid }}>mark ${p.mark}</Text>
        ) : null}
      </View>
    </View>
  );
}
