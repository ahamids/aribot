// SideChip — LONG / SHORT direction pill. Ported from the design's components.jsx:90-104.
// Pure-green and pure-red are used here intentionally: the design's color-
// reservation rule allows them on PnL, direction (this), kill switch, and
// LIVE warnings.
//
// Until now this chip was open-coded inline in three places (PositionRow,
// the Positions full screen, and the History trade row). Pass 2 extracts it
// as a primitive so future tweaks (touch target, dark mode in Pass 3) happen
// in one file.

import React from 'react';
import { Text, View } from 'react-native';
import { AT } from '@/theme/tokens';

export type Side = 'LONG' | 'SHORT';

type Props = {
  side: Side;
  // Compact form for dense rows (smaller padding, no arrow glyph).
  dense?: boolean;
};

export function SideChip({ side, dense }: Props) {
  const isLong = side === 'LONG';
  const bg = isLong ? AT.pnlGreenSoft : AT.pnlRedSoft;
  const fg = isLong ? AT.pnlGreen : AT.pnlRed;

  return (
    <View
      accessibilityLabel={`Direction ${side}`}
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
        paddingHorizontal: dense ? 8 : 9,
        paddingVertical: dense ? 2 : 3,
        borderRadius: AT.rS,
        backgroundColor: bg,
        borderWidth: 1.5,
        borderColor: fg,
      }}
    >
      <Text style={{ color: fg, fontSize: 11, fontWeight: '800', letterSpacing: 0.5 }}>
        {isLong ? '↑' : '↓'} {side}
      </Text>
    </View>
  );
}
