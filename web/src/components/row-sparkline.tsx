/**
 * <RowSparkline> — compact per-row equity/price line.
 *
 * Ported from design-pkg/components.jsx:180-196 (Sparkline) sized to
 * the positions screen variant (design-pkg/screens-main.jsx:43,
 * width=120 height=28). Color derives from net direction: green if
 * last >= first, red if last < first. Used in:
 *   - Positions full-screen card (entry→mark trajectory)
 *
 * Per-position price-history isn't logged by the bot today, so callers
 * typically pass a 2-point series ([entry, mark]) for a "where the
 * price has gone since entry" signal. When real history becomes
 * available the same component renders the full series unchanged.
 */
export interface RowSparklineProps {
  data: number[];
  width?: number;
  height?: number;
  /** Force a stroke color; defaults to direction-based pnl-green / pnl-red. */
  color?: string;
}

export function RowSparkline({
  data,
  width = 120,
  height = 28,
  color,
}: RowSparklineProps) {
  if (data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const stepX = width / (data.length - 1);
  const pad = 4;

  const pts = data
    .map(
      (v, i) =>
        `${(i * stepX).toFixed(1)},${(
          pad + (1 - (v - min) / span) * (height - pad * 2)
        ).toFixed(1)}`,
    )
    .join(" ");

  const last = data[data.length - 1];
  const first = data[0];
  const stroke =
    color ??
    (last >= first
      ? "var(--color-pnl-green)"
      : "var(--color-pnl-red)");

  // End-dot position is the last point parsed back out of the joined string.
  const lastTuple = pts.split(" ").slice(-1)[0].split(",").map(Number);

  // Fill area beneath the path for visual weight (12% opacity per spec).
  const areaPath = `M0,${height} L${pts.split(" ").join(" L")} L${width},${height} Z`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
    >
      <path d={areaPath} fill={stroke} fillOpacity={0.12} />
      <polyline
        points={pts}
        fill="none"
        stroke={stroke}
        strokeWidth={3}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={lastTuple[0]}
        cy={lastTuple[1]}
        r={3.5}
        fill={stroke}
        stroke="var(--c-paper)"
        strokeWidth={2}
      />
    </svg>
  );
}
