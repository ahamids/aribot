// EquityChart — 7-day equity curve with toon-styled axes. Ported from the
// design's <svg> in screens-main.jsx History/equity view. Coral fill + line.
//
// The bot persists equity changes per closed-trade, not per minute. So the
// curve has one point per trade plus an anchor at now — the spacing is
// uneven on purpose. We map points to X positions linearly across the
// rendered width, which preserves order but loses time-axis accuracy. The
// day labels at the bottom are a rough "last 7 days" hint, not a strict
// time axis.

import React from 'react';
import { View } from 'react-native';
import Svg, {
  Line,
  Polygon,
  Polyline,
  Text as SvgText,
} from 'react-native-svg';
import { AT } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

type Props = {
  data: number[];
  width?: number;
  height?: number;
  dayLabels?: string[];
};

const DEFAULT_DAYS_7 = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export function EquityChart({
  data,
  width = 320,
  height = 160,
  dayLabels = DEFAULT_DAYS_7,
}: Props) {
  const theme = useTheme();
  // Gridline rgba — dark mode needs a slightly stronger alpha to read against
  // darkPaper. Light keeps the original very-subtle plum.
  const gridStroke =
    theme.kind === 'dark' ? 'rgba(255,255,255,0.08)' : 'rgba(45,31,71,0.07)';
  if (!data || data.length < 2) {
    // Render an empty axis pair so the layout doesn't jump on initial load.
    return (
      <View style={{ height }}>
        <Svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
          <Line x1={22} y1={10}  x2={22}  y2={140} stroke={theme.textMid} strokeWidth={2.5} strokeLinecap="round" />
          <Line x1={22} y1={140} x2={width - 8} y2={140} stroke={theme.textMid} strokeWidth={2.5} strokeLinecap="round" />
        </Svg>
      </View>
    );
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;

  const left = 22;
  const right = width - 8;
  const top = 10;
  const bottom = 140;
  const innerW = right - left;
  const innerH = bottom - top - 5;

  const stepX = innerW / (data.length - 1);
  const pts = data.map((v, i) => {
    const x = left + i * stepX;
    const y = bottom - ((v - min) / span) * innerH;
    return { x, y };
  });
  const polyline = pts.map(p => `${p.x},${p.y}`).join(' ');
  const polygon = `${left},${bottom} ${polyline} ${right},${bottom}`;

  // Day labels evenly spaced across the inner width. Strictly decorative —
  // matches the design's "Mon Tue Wed..." labels even though our X axis is
  // sample-index-spaced, not time-spaced.
  const labelStepX = innerW / Math.max(1, dayLabels.length - 1);

  return (
    <View>
      <Svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        {/* axes */}
        <Line x1={left} y1={top}    x2={left}  y2={bottom} stroke={theme.textMid} strokeWidth={2.5} strokeLinecap="round" />
        <Line x1={left} y1={bottom} x2={right} y2={bottom} stroke={theme.textMid} strokeWidth={2.5} strokeLinecap="round" />

        {/* horizontal grid */}
        {[0, 1, 2, 3].map(i => (
          <Line
            key={i}
            x1={left}
            y1={bottom - i * 30 - 5}
            x2={right}
            y2={bottom - i * 30 - 5}
            stroke={gridStroke}
            strokeDasharray="3 4"
          />
        ))}

        {/* area + line */}
        <Polygon points={polygon} fill={AT.coral} opacity={0.18} />
        <Polyline
          points={polyline}
          fill="none"
          stroke={AT.coral}
          strokeWidth={3.5}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* day labels */}
        {dayLabels.map((d, i) => (
          <SvgText
            key={d + i}
            x={left + i * labelStepX}
            y={156}
            fontSize={10}
            fontWeight="700"
            fill={theme.textMid}
          >
            {d}
          </SvgText>
        ))}
      </Svg>
    </View>
  );
}
