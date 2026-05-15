// Sparkline — tiny line+area chart. Color follows the same PnL rule (green
// if last >= first, red otherwise). Built directly on react-native-svg.

import React from 'react';
import Svg, { Circle, Path, Polyline } from 'react-native-svg';
import { AT } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

type Props = {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
};

export function Sparkline({ data, width = 240, height = 56, color }: Props) {
  const theme = useTheme();
  if (!data || data.length < 2) {
    // Degenerate input — render a flat baseline so the layout doesn't jump
    // while equity history is loading.
    return (
      <Svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <Path d={`M 0 ${height / 2} L ${width} ${height / 2}`} stroke={theme.textSoft} strokeWidth={2} strokeDasharray="4 4" fill="none" />
      </Svg>
    );
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const stepX = width / (data.length - 1);

  const points = data.map((v, i) => {
    const x = i * stepX;
    const y = height - 6 - ((v - min) / span) * (height - 14);
    return { x, y };
  });

  const polyline = points.map(p => `${p.x},${p.y}`).join(' ');
  const last = points[points.length - 1];
  const areaPath =
    `M0,${height} ` +
    points.map(p => `L${p.x},${p.y}`).join(' ') +
    ` L${width},${height} Z`;
  const c = color ?? (data[data.length - 1] >= data[0] ? AT.pnlGreen : AT.pnlRed);

  return (
    <Svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <Path d={areaPath} fill={c} opacity={0.12} />
      <Polyline
        points={polyline}
        fill="none"
        stroke={c}
        strokeWidth={3}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Endpoint halo: use the surface color so the dot reads against
          whatever the chart sits on top of. Card surface in both modes. */}
      <Circle cx={last.x} cy={last.y} r={5} fill={c} stroke={theme.card} strokeWidth={2.5} />
    </Svg>
  );
}
