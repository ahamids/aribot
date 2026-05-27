import type { PositionsResponse } from "@/lib/api/aribot";

export function PositionsCard({
  positions,
}: {
  positions: PositionsResponse | null;
}) {
  return (
    <div className="outline-plum rounded-[18px] bg-paper p-5 sticker">
      <div className="flex items-baseline justify-between gap-4">
        <div className="t-section-label text-plum-mid">Open positions</div>
        {positions && (
          <div className="text-xs text-plum-soft">
            {positions.positions.length} open
          </div>
        )}
      </div>

      {!positions && (
        <p className="mt-3 text-sm text-plum-mid">
          Backend unreachable for positions.
        </p>
      )}

      {positions && positions.positions.length === 0 && (
        <p className="mt-3 text-sm text-plum-mid">
          No open positions. The bot opens trades when its strategy
          conditions are met; in PAPER or SHADOW mode no real orders
          are placed.
        </p>
      )}

      {positions && positions.positions.length > 0 && (
        <div className="mt-3 -mx-2 overflow-x-auto">
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-plum-soft">
                <th className="px-2 py-1.5 font-bold">Symbol</th>
                <th className="px-2 py-1.5 font-bold">Side</th>
                <th className="px-2 py-1.5 font-bold text-right">Entry</th>
                <th className="px-2 py-1.5 font-bold text-right">Mark</th>
                <th className="px-2 py-1.5 font-bold text-right">Size</th>
                <th className="px-2 py-1.5 font-bold text-right">PnL</th>
              </tr>
            </thead>
            <tbody>
              {positions.positions.map((p, i) => (
                <tr
                  key={`${p.symbol}-${i}`}
                  className="border-t border-plum/15"
                >
                  <td className="px-2 py-2 font-bold text-plum">{p.symbol}</td>
                  <td className="px-2 py-2">
                    <span
                      className={`outline-plum rounded-[6px] px-1.5 py-0.5 text-xs font-bold ${
                        p.side === "LONG"
                          ? "bg-pnl-green-soft text-pnl-green"
                          : "bg-pnl-red-soft text-pnl-red"
                      }`}
                    >
                      {p.side}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-right text-plum-mid">
                    {fmtPrice(p.entry)}
                  </td>
                  <td className="px-2 py-2 text-right text-plum-mid">
                    {p.mark != null ? fmtPrice(p.mark) : "—"}
                  </td>
                  <td className="px-2 py-2 text-right text-plum-mid">
                    {p.size}
                  </td>
                  <td
                    className={`px-2 py-2 text-right font-bold ${
                      p.pnl > 0
                        ? "text-pnl-green"
                        : p.pnl < 0
                          ? "text-pnl-red"
                          : "text-plum-mid"
                    }`}
                  >
                    {fmtSignedPnl(p.pnl)}
                    {p.pnlPercent != null && (
                      <span className="ml-1 text-xs font-normal text-plum-soft">
                        ({(p.pnlPercent * 100).toFixed(1)}%)
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function fmtPrice(n: number): string {
  if (n >= 1000) return n.toFixed(2);
  if (n >= 1) return n.toFixed(3);
  return n.toPrecision(4);
}

function fmtSignedPnl(n: number): string {
  const s = Math.abs(n).toFixed(2);
  if (n > 0) return `+$${s}`;
  if (n < 0) return `-$${s}`;
  return `$${s}`;
}
