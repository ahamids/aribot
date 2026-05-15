// Accessories the mascot holds. Mostly used by error/empty states.
// Ported from mascot.jsx <MProp>. Only the four kinds the design ships.

import React from 'react';
import Svg, { Circle, G, Path, Rect } from 'react-native-svg';
import { View } from 'react-native';
import { AT } from '@/theme/tokens';

type Kind = 'flag' | 'cable' | 'chart' | 'vault';

export function MProp({ kind }: { kind: Kind }) {
  const O = AT.plum;

  if (kind === 'flag') {
    return (
      <View style={{ position: 'absolute', inset: 0 as unknown as number }} pointerEvents="none">
        <Svg viewBox="0 0 200 200" width="100%" height="100%">
          <Rect x={175} y={20} width={5} height={110} rx={2} fill={O} />
          <Path
            d="M180 24 L218 30 L210 50 L218 70 L180 76 Z"
            fill={AT.pnlRed}
            stroke={O}
            strokeWidth={3}
            strokeLinejoin="round"
          />
        </Svg>
      </View>
    );
  }

  if (kind === 'cable') {
    return (
      <View style={{ position: 'absolute', inset: 0 as unknown as number }} pointerEvents="none">
        <Svg viewBox="0 0 200 200" width="100%" height="100%">
          <Path
            d="M30 150 Q10 130 22 110 Q34 90 18 70"
            fill="none"
            stroke={O}
            strokeWidth={6}
            strokeLinecap="round"
          />
          <Rect x={12} y={60} width={14} height={18} rx={3} fill={AT.peri} stroke={O} strokeWidth={3} />
          <Path
            d="M170 150 Q190 130 178 110 Q166 90 182 70"
            fill="none"
            stroke={O}
            strokeWidth={6}
            strokeLinecap="round"
          />
          <Rect x={174} y={60} width={14} height={18} rx={3} fill={AT.coral} stroke={O} strokeWidth={3} />
          <G fill={AT.yellow} stroke={O} strokeWidth={2}>
            <Path d="M100 50 L95 38 L107 42 L102 30 L114 36" strokeLinejoin="round" />
          </G>
        </Svg>
      </View>
    );
  }

  if (kind === 'chart') {
    return (
      <View
        style={{ position: 'absolute', bottom: -20, left: 30, width: '60%', height: '40%' }}
        pointerEvents="none"
      >
        <Svg viewBox="0 0 200 200" width="100%" height="100%">
          <Rect x={10} y={10} width={180} height={120} rx={14} fill={AT.paper} stroke={O} strokeWidth={3.5} />
          <Path
            d="M22 100 L60 80 L92 92 L130 50 L178 64"
            fill="none"
            stroke={AT.coral}
            strokeWidth={5}
            strokeLinecap="round"
            strokeLinejoin="round"
            transform="rotate(180 100 70)"
          />
        </Svg>
      </View>
    );
  }

  if (kind === 'vault') {
    return (
      <View style={{ position: 'absolute', inset: 0 as unknown as number }} pointerEvents="none">
        <Svg viewBox="0 0 200 200" width="100%" height="100%">
          <Rect x={18} y={148} width={32} height={42} rx={7} fill={AT.yellow} stroke={O} strokeWidth={3} />
          <Circle cx={34} cy={160} r={4} fill="none" stroke={O} strokeWidth={2.5} />
          <Path d="M34 160 V172" stroke={O} strokeWidth={2.5} strokeLinecap="round" />
        </Svg>
      </View>
    );
  }

  return null;
}
