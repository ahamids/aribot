"use client";

import { useMemo, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import type { Trade } from "@/lib/api/aribot";
import { Mascot } from "@/components/mascot";

type WinFilter = "all" | "wins" | "losses";
type SideFilter = "all" | "LONG" | "SHORT";

interface HistoryClientProps {
  initialDays: number;
  trades: Trade[];
  maxDays: number;
}

export function HistoryClient({
  initialDays,
  trades,
  maxDays,
}: HistoryClientProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [symbolQuery, setSymbolQuery] = useState("");
  const [winFilter, setWinFilter] = useState<WinFilter>("all");
  const [sideFilter, setSideFilter] = useState<SideFilter>("all");

  // The `days` filter is a URL param so the server fetch can use it.
  // The other filters are client-side because they don't change which
  // rows the backend returns — just which we render.
  function setDays(days: number) {
    const clamped = Math.max(1, Math.min(days, maxDays));
    const params = new URLSearchParams();
    params.set("days", String(clamped));
    router.push(`${pathname}?${params.toString()}`);
  }

  const filtered = useMemo(() => {
    const q = symbolQuery.trim().toUpperCase();
    return trades.filter((t) => {
      if (q && !t.symbol.toUpperCase().includes(q)) return false;
      if (sideFilter !== "all" && t.side !== sideFilter) return false;
      if (winFilter === "wins" && t.pnl <= 0) return false;
      if (winFilter === "losses" && t.pnl >= 0) return false;
      return true;
    });
  }, [trades, symbolQuery, sideFilter, winFilter]);

  const wins = filtered.filter((t) => t.pnl > 0).length;
  const losses = filtered.filter((t) => t.pnl < 0).length;
  const flats = filtered.filter((t) => t.pnl === 0).length;
  const total = filtered.reduce((acc, t) => acc + t.pnl, 0);
  const winRate =
    filtered.length > 0 ? ((wins / filtered.length) * 100).toFixed(0) : "—";

  function downloadCsv() {
    const csv = tradesToCsv(filtered);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const ymd = new Date().toISOString().slice(0, 10);
    a.download = `aribot-trades-${ymd}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      {/* Filters */}
      <div className="outline-plum rounded-[18px] bg-paper p-5 sticker flex flex-col gap-4">
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
          <Field label="Window">
            <select
              value={initialDays}
              onChange={(e) => setDays(Number.parseInt(e.target.value, 10))}
              className="w-full outline-plum rounded-[10px] bg-cream text-plum px-3 py-2 text-sm font-bold"
            >
              <option value={1}>Last 24h</option>
              <option value={7}>Last 7 days</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
            </select>
          </Field>

          <Field label="Symbol">
            <input
              type="text"
              placeholder="BTC, ADA, …"
              value={symbolQuery}
              onChange={(e) => setSymbolQuery(e.target.value)}
              className="w-full outline-plum rounded-[10px] bg-cream text-plum px-3 py-2 text-sm font-mono uppercase placeholder:text-plum-soft"
            />
          </Field>

          <Field label="Side">
            <Segmented
              options={[
                ["all", "All"],
                ["LONG", "Long"],
                ["SHORT", "Short"],
              ]}
              value={sideFilter}
              onChange={(v) => setSideFilter(v as SideFilter)}
            />
          </Field>

          <Field label="Outcome">
            <Segmented
              options={[
                ["all", "All"],
                ["wins", "Wins"],
                ["losses", "Losses"],
              ]}
              value={winFilter}
              onChange={(v) => setWinFilter(v as WinFilter)}
            />
          </Field>
        </div>
      </div>

      {/* Summary */}
      <div className="outline-plum rounded-[18px] bg-paper p-5 sticker">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 tabular-nums">
          <Stat label="Trades" value={String(filtered.length)} />
          <Stat
            label="Win rate"
            value={`${winRate}%`}
            tone={
              filtered.length === 0
                ? "neutral"
                : wins > losses
                  ? "green"
                  : wins < losses
                    ? "red"
                    : "neutral"
            }
          />
          <Stat label="W / L / Flat" value={`${wins} / ${losses} / ${flats}`} />
          <Stat
            label="Net PnL"
            value={fmtSignedPnl(total)}
            tone={total > 0 ? "green" : total < 0 ? "red" : "neutral"}
          />
        </div>
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={downloadCsv}
            disabled={filtered.length === 0}
            className="outline-plum rounded-[10px] bg-cream text-plum px-3 py-1.5 text-sm font-bold hover:bg-cream-deep disabled:opacity-50"
          >
            Export CSV ({filtered.length})
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="outline-plum rounded-[18px] bg-paper p-5 sticker">
        {filtered.length === 0 ? (
          <div className="flex flex-col sm:flex-row items-center gap-4 sm:gap-6 py-2">
            <Mascot pose="napping" tone="cream" size={96} />
            <div className="flex-1 text-center sm:text-left">
              <p className="t-row-symbol text-plum">No trades to show</p>
              <p className="mt-1 t-detail text-plum-mid">
                Either the bot hasn&apos;t closed any trades in this
                window, or the filters above hide them all.
              </p>
            </div>
          </div>
        ) : (
          <div className="-mx-2 overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider text-plum-soft">
                  <th className="px-2 py-1.5 font-bold">Closed</th>
                  <th className="px-2 py-1.5 font-bold">Symbol</th>
                  <th className="px-2 py-1.5 font-bold">Side</th>
                  <th className="px-2 py-1.5 font-bold text-right">Qty</th>
                  <th className="px-2 py-1.5 font-bold text-right">Entry</th>
                  <th className="px-2 py-1.5 font-bold text-right">Exit</th>
                  <th className="px-2 py-1.5 font-bold text-right">PnL</th>
                  <th className="px-2 py-1.5 font-bold">Reason</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((t, i) => (
                  <TradeRow
                    key={`${t.symbol}-${t.closedAtIso}-${i}`}
                    trade={t}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
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
    <tr className="border-t border-plum/15">
      <td className="px-2 py-2 text-xs text-plum-mid whitespace-nowrap">
        {closedLabel}
      </td>
      <td className="px-2 py-2 font-bold text-plum">{t.symbol}</td>
      <td className="px-2 py-2">
        <span
          className={`outline-plum rounded-[6px] px-1.5 py-0.5 text-xs font-bold ${
            t.side === "LONG"
              ? "bg-pnl-green-soft text-pnl-green"
              : "bg-pnl-red-soft text-pnl-red"
          }`}
        >
          {t.side}
        </span>
      </td>
      <td className="px-2 py-2 text-right text-plum-mid">
        {t.quantity != null ? t.quantity : "—"}
      </td>
      <td className="px-2 py-2 text-right text-plum-mid">
        {t.entryPrice != null ? fmtPrice(t.entryPrice) : "—"}
      </td>
      <td className="px-2 py-2 text-right text-plum-mid">
        {t.exitPrice != null ? fmtPrice(t.exitPrice) : "—"}
      </td>
      <td
        className={`px-2 py-2 text-right font-bold ${
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
      </td>
      <td className="px-2 py-2 text-xs text-plum-mid">{t.reason ?? "—"}</td>
    </tr>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs uppercase font-bold tracking-wider text-plum-mid">
        {label}
      </span>
      {children}
    </div>
  );
}

function Segmented({
  options,
  value,
  onChange,
}: {
  options: [string, string][];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex outline-plum rounded-[10px] bg-cream p-0.5">
      {options.map(([v, label]) => {
        const selected = v === value;
        return (
          <button
            key={v}
            type="button"
            onClick={() => onChange(v)}
            className={`flex-1 px-2 py-1 text-xs font-bold rounded-[8px] transition ${
              selected
                ? "bg-coral text-plum"
                : "text-plum-mid hover:text-plum"
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "green" | "red";
}) {
  const color =
    tone === "green"
      ? "text-pnl-green"
      : tone === "red"
        ? "text-pnl-red"
        : "text-plum";
  return (
    <div>
      <div className="text-xs uppercase font-bold tracking-wider text-plum-mid">
        {label}
      </div>
      <div className={`mt-1 text-xl font-black ${color}`}>{value}</div>
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

function tradesToCsv(trades: Trade[]): string {
  // RFC 4180-ish: quote everything, double-up embedded quotes. Safe for
  // CSVs that get opened in Excel/Numbers/Sheets.
  const escape = (v: string | number | null | undefined): string => {
    if (v == null) return "";
    const s = String(v).replace(/"/g, '""');
    return `"${s}"`;
  };
  const header = [
    "closed_at_iso",
    "opened_at_iso",
    "symbol",
    "side",
    "quantity",
    "entry_price",
    "exit_price",
    "pnl_usd",
    "pnl_percent",
    "reason",
  ].map(escape).join(",");
  const rows = trades.map((t) =>
    [
      t.closedAtIso,
      t.openedAtIso ?? "",
      t.symbol,
      t.side,
      t.quantity ?? "",
      t.entryPrice ?? "",
      t.exitPrice ?? "",
      t.pnl,
      t.pnlPercent != null ? (t.pnlPercent * 100).toFixed(4) : "",
      t.reason ?? "",
    ]
      .map(escape)
      .join(","),
  );
  return [header, ...rows].join("\r\n");
}
