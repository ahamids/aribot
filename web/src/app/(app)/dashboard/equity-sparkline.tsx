import type { EquityPoint } from "@/lib/api/aribot";

/**
 * Tiny SVG sparkline of equity over time. No chart library — just a
 * stroked path. Colored by net direction (green if last >= first,
 * red otherwise). Rendered as a Server Component since the data is
 * already on the server.
 */
export function EquitySparkline({ points }: { points: EquityPoint[] }) {
  if (points.length < 2) return null;

  const width = 600;
  const height = 60;
  const pad = 2;

  const xs = points.map((_, i) => i);
  const ys = points.map((p) => p.equity);
  const xMin = 0;
  const xMax = xs.length - 1;
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const ySpan = yMax - yMin || 1;

  const sx = (x: number) =>
    pad + ((x - xMin) / (xMax - xMin)) * (width - pad * 2);
  const sy = (y: number) =>
    pad + (1 - (y - yMin) / ySpan) * (height - pad * 2);

  const d =
    `M ${sx(xs[0]).toFixed(1)} ${sy(ys[0]).toFixed(1)}` +
    xs
      .slice(1)
      .map((x, i) => ` L ${sx(x).toFixed(1)} ${sy(ys[i + 1]).toFixed(1)}`)
      .join("");

  const net = ys[ys.length - 1] - ys[0];
  const stroke =
    net > 0
      ? "var(--color-pnl-green)"
      : net < 0
        ? "var(--color-pnl-red)"
        : "var(--color-plum-mid)";

  // Fill area below the line for visual weight.
  const dFill =
    d +
    ` L ${sx(xs[xs.length - 1]).toFixed(1)} ${(height - pad).toFixed(1)}` +
    ` L ${sx(xs[0]).toFixed(1)} ${(height - pad).toFixed(1)} Z`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-12 outline-plum rounded-[10px] bg-cream"
      preserveAspectRatio="none"
    >
      <path
        d={dFill}
        fill={stroke}
        fillOpacity={0.18}
        stroke="none"
      />
      <path
        d={d}
        fill="none"
        stroke={stroke}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
