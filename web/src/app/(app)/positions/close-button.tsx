"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { closePosition, type CloseResult } from "@/app/actions/controls";
import { ConfirmDialog } from "../dashboard/confirm-dialog";

/**
 * Per-position "Close" control. Opens a danger-tone confirm (closing is a
 * real-money action in LIVE/SHADOW) and calls the closePosition server
 * action, which has the backend place a reduce-only market order directly
 * against Bybit. On success the action revalidates /positions so the card
 * drops on the next render; we also router.refresh() to pull the fresh
 * server component immediately.
 */
export function ClosePositionButton({
  symbol,
  side,
  pnl,
}: {
  symbol: string;
  side: "LONG" | "SHORT";
  pnl: number;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [confirm, setConfirm] = useState(false);
  const [result, setResult] = useState<CloseResult | null>(null);

  function onConfirm() {
    setConfirm(false);
    setResult(null);
    startTransition(async () => {
      const r = await closePosition(symbol);
      setResult(r);
      if (r.ok) router.refresh();
    });
  }

  const pnlNote =
    pnl >= 0
      ? `Locks in roughly +$${pnl.toFixed(2)}.`
      : `Realizes a loss of about -$${Math.abs(pnl).toFixed(2)}.`;

  return (
    <>
      <button
        type="button"
        onClick={() => setConfirm(true)}
        disabled={pending}
        className="outline-plum rounded-[10px] bg-cream text-plum px-3 py-1.5 text-sm font-bold hover:bg-cream-deep disabled:opacity-50 inline-flex items-center gap-1.5"
      >
        {pending ? "Closing…" : "Close"}
      </button>

      {result && (
        <p
          className={`mt-2 t-detail font-bold ${
            result.ok ? "text-pnl-green" : "text-pnl-red"
          }`}
        >
          {result.ok ? "✓ " : "⚠ "}
          {result.detail}
        </p>
      )}

      <ConfirmDialog
        open={confirm}
        title={`Close ${symbol}?`}
        body={
          <>
            <p className="font-bold text-plum">
              Closes your {side} position now at market.
            </p>
            <p className="mt-2">
              {pnlNote} A reduce-only market order goes straight to Bybit —
              this happens whether or not the bot is running. The bot
              reconciles its own books on the next cycle.
            </p>
          </>
        }
        confirmLabel={`Close ${side}`}
        tone="danger"
        busy={pending}
        onConfirm={onConfirm}
        onCancel={() => setConfirm(false)}
      />
    </>
  );
}
