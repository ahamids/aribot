import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import {
  aribotApi,
  ApiError,
  type PositionsResponse,
  type Position,
} from "@/lib/api/aribot";
import { AppNav } from "../nav";
import { AutoRefresh } from "../dashboard/auto-refresh";
import { Mascot } from "@/components/mascot";
import { RowSparkline } from "@/components/row-sparkline";

export const dynamic = "force-dynamic";

/**
 * Full-screen Positions view. Mirrors the design package's
 * `screens-main.jsx:3-50` layout: one card per position, KV grid for
 * size/mark/entry/liquidation, age + trajectory sparkline at the foot.
 *
 * The dashboard keeps its own compact `PositionsCard` for the at-a-
 * glance view; this route is the deep dive.
 *
 * Per-position price history isn't logged by the bot today, so the
 * sparkline is a 2-point entry→mark trajectory line: a real signal of
 * "direction since open" without inventing data the backend doesn't
 * have. If/when the bot starts persisting tick history, the same
 * <RowSparkline> renders the full series unchanged.
 */
export default async function PositionsPage() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getUser();
  if (!data.user) redirect("/sign-in");

  let positions: PositionsResponse | null = null;
  let backendError: string | null = null;
  try {
    positions = await aribotApi.positions();
  } catch (e) {
    backendError =
      e instanceof ApiError
        ? e.body &&
          typeof e.body === "object" &&
          "detail" in e.body &&
          typeof (e.body as { detail: unknown }).detail === "string"
          ? (e.body as { detail: string }).detail
          : e.message
        : String(e);
  }

  const list = positions?.positions ?? [];
  const openCount = list.length;

  return (
    <main className="flex-1 flex flex-col">
      <AppNav email={data.user.email ?? ""} active="positions" />

      <section className="flex-1 px-4 py-6 sm:px-12 sm:py-8">
        <div className="mx-auto w-full max-w-3xl flex flex-col gap-4 sm:gap-6">
          <header>
            <h1 className="t-page-title text-plum">Positions</h1>
            <p className="mt-2 t-body text-plum-mid">
              {openCount === 0
                ? "No open positions right now. The bot opens trades when its strategy conditions are met."
                : `${openCount} open · last refreshed just now.`}
            </p>
          </header>

          {backendError && (
            <div className="outline-plum rounded-[14px] bg-cream-deep p-4 t-detail sticker">
              <p className="font-black text-plum flex items-center gap-2">
                <span aria-hidden>⚠</span>
                Backend unreachable
              </p>
              <p className="mt-1 text-plum-mid">{backendError}</p>
            </div>
          )}

          {!backendError && openCount === 0 && <EmptyState />}

          {!backendError &&
            list.map((p, i) => (
              <PositionCard key={`${p.symbol}-${i}`} p={p} />
            ))}
        </div>
      </section>

      {/* 15s refresh — matches dashboard cadence. */}
      <AutoRefresh intervalMs={15000} />
    </main>
  );
}

function EmptyState() {
  return (
    <div className="outline-plum rounded-[18px] bg-paper p-8 sticker flex flex-col items-center text-center gap-3">
      <Mascot pose="napping" tone="cream" size={120} />
      <h2 className="t-section-h2 text-plum">All quiet</h2>
      <p className="t-body text-plum-mid max-w-md">
        Nothing open right now. The bot will let you know when a setup
        meets the strategy&apos;s entry conditions.
      </p>
    </div>
  );
}

function PositionCard({ p }: { p: Position }) {
  const pnlColor =
    p.pnl > 0 ? "text-pnl-green" : p.pnl < 0 ? "text-pnl-red" : "text-plum";
  const pnlSign = p.pnl >= 0 ? "+" : "-";
  const pnlAbs = Math.abs(p.pnl).toFixed(2);

  // 2-point trajectory: entry → mark. RowSparkline derives color from
  // direction (last >= first) so the signal matches the PnL number's
  // sign without us hardcoding side-vs-direction logic.
  const traj =
    p.mark != null && p.mark !== p.entry
      ? // Long position: trajectory tracks raw price. Short: invert so
        // a profitable move (price falling) reads as an up-sloping line.
        p.side === "LONG"
        ? [p.entry, p.mark]
        : [p.mark, p.entry]
      : null;

  return (
    <div className="outline-plum rounded-[18px] bg-paper p-5 sticker">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="t-row-symbol text-plum tracking-tight">
            {p.symbol}
          </span>
          <span
            className={`outline-plum rounded-[6px] px-1.5 py-0.5 text-xs font-bold ${
              p.side === "LONG"
                ? "bg-pnl-green-soft text-pnl-green"
                : "bg-pnl-red-soft text-pnl-red"
            }`}
          >
            {p.side}
          </span>
          {p.leverage != null && (
            <span className="t-section-label text-plum-mid bg-cream-deep outline-plum rounded-full px-2 py-0.5">
              {p.leverage}x
            </span>
          )}
        </div>
        <div className={`t-position-pnl ${pnlColor}`}>
          {pnlSign}${pnlAbs}
          {p.pnlPercent != null && (
            <span className="ml-2 t-detail text-plum-soft font-bold">
              ({(p.pnlPercent * 100).toFixed(1)}%)
            </span>
          )}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
        <KV label="Size" value={fmtSize(p.size)} />
        <KV
          label="Mark"
          value={p.mark != null ? `$${fmtPrice(p.mark)}` : "—"}
        />
        <KV label="Entry" value={`$${fmtPrice(p.entry)}`} />
        <KV
          label="Liq"
          value={
            p.liquidationPrice != null
              ? `$${fmtPrice(p.liquidationPrice)}`
              : "—"
          }
          danger={p.liquidationPrice != null}
        />
      </div>

      <div className="mt-4 pt-3 border-t border-dashed border-plum/20 flex items-center justify-between gap-3">
        <span className="t-section-label text-plum-mid">
          {fmtAge(p.openedAtIso)}
        </span>
        {traj && <RowSparkline data={traj} width={120} height={28} />}
      </div>
    </div>
  );
}

function KV({
  label,
  value,
  danger = false,
}: {
  label: string;
  value: string;
  danger?: boolean;
}) {
  return (
    <div>
      <div className="t-section-label text-plum-mid">{label}</div>
      <div className={`t-kv ${danger ? "text-pnl-red" : "text-plum"}`}>
        {value}
      </div>
    </div>
  );
}

function fmtPrice(n: number): string {
  if (n >= 1000) return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (n >= 1) return n.toFixed(3);
  return n.toPrecision(4);
}

function fmtSize(n: number): string {
  if (n >= 1000) return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (n >= 1) return n.toFixed(2);
  return n.toPrecision(3);
}

function fmtAge(openedAtIso?: string): string {
  if (!openedAtIso) return "OPEN";
  const opened = Date.parse(openedAtIso);
  if (Number.isNaN(opened)) return "OPEN";
  const diffMs = Date.now() - opened;
  if (diffMs < 0) return "OPEN";
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 60) return `OPEN ${mins}m`;
  const hrs = Math.floor(mins / 60);
  const rem = mins % 60;
  if (hrs < 24) return `OPEN ${hrs}h ${rem.toString().padStart(2, "0")}m`;
  const days = Math.floor(hrs / 24);
  return `OPEN ${days}d ${(hrs % 24).toString().padStart(2, "0")}h`;
}
