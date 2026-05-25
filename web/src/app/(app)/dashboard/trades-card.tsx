import type { TradesResponse, Trade } from "@/lib/api/aribot";

export function TradesCard({ trades }: { trades: TradesResponse | null }) {
  const wins = trades?.trades.filter((t) => t.pnl > 0).length ?? 0;
  const losses = trades?.trades.filter((t) => t.pnl < 0).length ?? 0;
  const totalPnl =
    trades?.trades.reduce((acc, t) => acc + t.pnl, 0) ?? 0;

  return (
    <div className="outline-plum rounded-[18px] bg-paper p-5">
      <div className="flex items-baseline justify-between gap-4 flex-wrap">
        <div className="text-xs uppercase font-bold tracking-wider text-plum-mid">
          Recent trades · last 7 days
        </div>
        {trades && trades.trades.length > 0 && (
          <div className="text-xs text-plum-soft tabular-nums">
            {wins}W / {losses}L · net {fmtSignedPnl(totalPnl)}
          </div>
        )}
      </div>

      {!trades && (
        <p className="mt-3 text-sm text-plum-mid">
          Backend unreachable for trades.
        </p>
      )}

      {trades && trades.trades.length === 0 && (
        <p className="mt-3 text-sm text-plum-mid">
          No closed trades yet. Trades show up here as the bot closes
          positions (via take-profit, stop-loss, or manual exit).
        </p>
      )}

      {trades && trades.trades.length > 0 && (
        <ul className="mt-3 divide-y divide-plum/15">
          {trades.trades.slice(0, 20).map((t, i) => (
            <TradeRow key={`${t.symbol}-${t.closedAtIso}-${i}`} trade={t} />
          ))}
          {trades.trades.length > 20 && (
            <li className="pt-2 text-xs text-plum-soft">
              + {trades.trades.length - 20} more — full history coming in M6.
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

function TradeRow({ trade: t }: { trade: Trade }) {
  const closed = new Date(t.closedAtIso);
  const closedLabel = isNaN(closed.getTime())
    ? t.closedAtIso
    : `${closed.toLocaleDateString()} ${closed.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })}`;

  return (
    <li className="flex items-center justify-between gap-3 py-2 text-sm">
      <div className="flex items-center gap-2 min-w-0">
        <span
          className={`outline-plum rounded-[6px] px-1.5 py-0.5 text-xs font-bold ${
            t.side === "LONG"
              ? "bg-pnl-green-soft text-pnl-green"
              : "bg-pnl-red-soft text-pnl-red"
          }`}
        >
          {t.side}
        </span>
        <span className="font-bold text-plum truncate">{t.symbol}</span>
        {t.reason && (
          <span className="text-xs text-plum-soft truncate hidden sm:inline">
            · {t.reason}
          </span>
        )}
      </div>
      <div className="flex items-center gap-3 shrink-0 tabular-nums">
        <span className="text-xs text-plum-soft hidden sm:inline">
          {closedLabel}
        </span>
        <span
          className={`font-bold ${
            t.pnl > 0
              ? "text-pnl-green"
              : t.pnl < 0
                ? "text-pnl-red"
                : "text-plum-mid"
          }`}
        >
          {fmtSignedPnl(t.pnl)}
          {t.pnlPercent != null && (
            <span className="ml-1 text-xs font-normal text-plum-soft">
              ({(t.pnlPercent * 100).toFixed(1)}%)
            </span>
          )}
        </span>
      </div>
    </li>
  );
}

function fmtSignedPnl(n: number): string {
  const s = Math.abs(n).toFixed(2);
  if (n > 0) return `+$${s}`;
  if (n < 0) return `-$${s}`;
  return `$${s}`;
}
