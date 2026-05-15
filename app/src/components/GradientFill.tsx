// GradientFill — a vertical fade behind any children. Uses react-native-svg's
// LinearGradient so we don't pull in a new native module (Reanimated-style
// gotchas are not worth it). Renders as an absolute layer; siblings stack on
// top via the same parent's `overflow: 'hidden'`.
//
// Design recipe from the original status card:
//   linear-gradient(180deg, <toneColor> 0%, <fadeTo> 70%)
//
// We honor that 70% stop so the bottom of the gradient settles into the card
// surface cleanly.

import React from 'react';
import { View, ViewStyle, StyleProp } from 'react-native';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';

type Props = {
  // Color at the top edge (full opacity).
  from: string;
  // Color at the 70% stop (where the fade lands). Should match the card
  // surface so the gradient appears to dissolve into the card.
  to: string;
  // Where the fade reaches `to`. 0..1; default 0.7 to match the design.
  fadeStop?: number;
  style?: StyleProp<ViewStyle>;
};

export function GradientFill({ from, to, fadeStop = 0.7, style }: Props) {
  return (
    <View
      pointerEvents="none"
      style={[
        {
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: 0,
          right: 0,
        },
        style,
      ]}
    >
      <Svg width="100%" height="100%" preserveAspectRatio="none">
        <Defs>
          <LinearGradient id="gf" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={from} stopOpacity="1" />
            <Stop offset={String(fadeStop)} stopColor={to} stopOpacity="1" />
            <Stop offset="1" stopColor={to} stopOpacity="1" />
          </LinearGradient>
        </Defs>
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#gf)" />
      </Svg>
    </View>
  );
}
