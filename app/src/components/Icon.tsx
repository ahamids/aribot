// Icon set — chunky stroked glyphs, no library. Ported from components.jsx.

import React from 'react';
import Svg, { Circle, G, Path, Rect } from 'react-native-svg';

export type IconName =
  | 'home'
  | 'positions'
  | 'history'
  | 'settings'
  | 'lock'
  | 'check'
  | 'x'
  | 'server'
  | 'plug'
  | 'bolt'
  | 'refresh'
  | 'chart'
  | 'eye'
  | 'eyeOff'
  | 'chevron'
  | 'bell'
  | 'back';

type Props = { name: IconName; size?: number; color?: string };

export function Icon({ name, size = 22, color = '#2D1F47' }: Props) {
  const common = {
    stroke: color,
    strokeWidth: 2.5,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    fill: 'none' as const,
  };

  switch (name) {
    case 'home':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <Path
            {...common}
            d="M3 11 L12 3 L21 11 V20 a1 1 0 0 1-1 1 h-5 v-7 h-4 v7 H4 a1 1 0 0 1-1 -1 Z"
          />
        </Svg>
      );
    case 'positions':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <G {...common}>
            <Rect x={3} y={4} width={18} height={6} rx={2} />
            <Rect x={3} y={14} width={13} height={6} rx={2} />
          </G>
        </Svg>
      );
    case 'history':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <G {...common}>
            <Circle cx={12} cy={12} r={9} />
            <Path d="M12 7 v5 l3 2" />
          </G>
        </Svg>
      );
    case 'settings':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <G {...common}>
            <Circle cx={12} cy={12} r={3} />
            <Path d="M19 12 a7 7 0 0 0 -.2 -1.7 l2-1.5 -2-3.4 -2.3 1 a7 7 0 0 0 -2.9 -1.7 L13 2 h-2 l-.6 2.7 a7 7 0 0 0 -2.9 1.7 l-2.3-1 -2 3.4 2 1.5 A7 7 0 0 0 5 12 l-2 1.5 2 3.4 2.3-1 a7 7 0 0 0 2.9 1.7 L11 22 h2 l.6-2.4 a7 7 0 0 0 2.9-1.7 l2.3 1 2-3.4 -2-1.5z" />
          </G>
        </Svg>
      );
    case 'lock':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <G {...common}>
            <Rect x={5} y={11} width={14} height={10} rx={2} />
            <Path d="M8 11 V7 a4 4 0 0 1 8 0 v4" />
          </G>
        </Svg>
      );
    case 'check':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <Path {...common} d="M5 12 l5 5 L20 7" />
        </Svg>
      );
    case 'x':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <Path {...common} d="M6 6 l12 12 M18 6 l-12 12" />
        </Svg>
      );
    case 'server':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <G {...common}>
            <Rect x={4} y={3} width={16} height={7} rx={2} />
            <Rect x={4} y={13} width={16} height={7} rx={2} />
            <Circle cx={8} cy={6.5} r={0.8} fill={color} stroke={color} />
            <Circle cx={8} cy={16.5} r={0.8} fill={color} stroke={color} />
          </G>
        </Svg>
      );
    case 'plug':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <G {...common}>
            <Path d="M9 4 V8 M15 4 V8" />
            <Path d="M6 8 h12 v4 a4 4 0 0 1-4 4 h-4 a4 4 0 0 1-4 -4 z" />
            <Path d="M12 16 v4" />
          </G>
        </Svg>
      );
    case 'bolt':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <Path {...common} d="M13 2 L5 14 h6 l-2 8 8-12 h-6 l2-8z" />
        </Svg>
      );
    case 'refresh':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <G {...common}>
            <Path d="M3 12 a9 9 0 0 1 15-6.7 L21 8" />
            <Path d="M21 3 V8 H16" />
            <Path d="M21 12 a9 9 0 0 1 -15 6.7 L3 16" />
            <Path d="M3 21 V16 H8" />
          </G>
        </Svg>
      );
    case 'chart':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <G {...common}>
            <Path d="M3 20 V4" />
            <Path d="M3 20 H21" />
            <Path d="M7 16 L11 11 L14 13 L19 7" />
          </G>
        </Svg>
      );
    case 'eye':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <G {...common}>
            <Path d="M2 12 s4-7 10-7 10 7 10 7 -4 7-10 7-10-7-10-7z" />
            <Circle cx={12} cy={12} r={3} />
          </G>
        </Svg>
      );
    case 'eyeOff':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <G {...common}>
            <Path d="M3 3 L21 21" />
            <Path d="M10.5 6.3 A11 11 0 0 1 12 6 c6 0 10 6 10 6 a14.5 14.5 0 0 1-3 3.8 M6 6.6 C3.6 8.3 2 12 2 12 s4 7 10 7 a11 11 0 0 0 4.4-1" />
            <Circle cx={12} cy={12} r={3} />
          </G>
        </Svg>
      );
    case 'chevron':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <Path {...common} d="M9 6 l6 6 -6 6" />
        </Svg>
      );
    case 'back':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <Path {...common} d="M15 6 l-6 6 6 6" />
        </Svg>
      );
    case 'bell':
      return (
        <Svg width={size} height={size} viewBox="0 0 24 24">
          <G {...common}>
            <Path d="M6 8 a6 6 0 0 1 12 0 v5 l2 3 H4 l2-3 z" />
            <Path d="M10 19 a2 2 0 0 0 4 0" />
          </G>
        </Svg>
      );
  }
}
