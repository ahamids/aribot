"use client";

import { useActionState, useRef } from "react";
import { setBotMode } from "@/app/actions/bot";
import type { BotMode } from "@/lib/api/aribot";

const MODES: { mode: BotMode; label: string; description: string }[] = [
  {
    mode: "PAPER",
    label: "Paper",
    description: "Simulated trades. No real money. Safe default.",
  },
  {
    mode: "SHADOW",
    label: "Shadow",
    description: "Real-time market, paper PnL. Use to validate a strategy.",
  },
  {
    mode: "LIVE",
    label: "Live",
    description: "Real orders, real money. Requires Bybit keys.",
  },
];

export function ModePicker({ currentMode }: { currentMode: BotMode }) {
  const [state, action, pending] = useActionState(setBotMode, undefined);
  const formRef = useRef<HTMLFormElement>(null);

  function handleClick(e: React.MouseEvent<HTMLButtonElement>, mode: BotMode) {
    if (mode === "LIVE") {
      const confirmed = window.confirm(
        "LIVE mode places REAL orders against your Bybit account.\n\n" +
          "Confirm: you are about to risk real money. Continue?",
      );
      if (!confirmed) {
        e.preventDefault();
      }
    }
  }

  return (
    <form ref={formRef} action={action}>
      <div className="outline-plum rounded-[18px] bg-paper p-5">
        <div className="text-xs uppercase font-bold tracking-wider text-plum-mid">
          Mode
        </div>
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3">
          {MODES.map(({ mode, label, description }) => {
            const isCurrent = mode === currentMode;
            const isLive = mode === "LIVE";
            return (
              <button
                key={mode}
                type="submit"
                name="mode"
                value={mode}
                disabled={pending || isCurrent}
                onClick={(e) => handleClick(e, mode)}
                className={`outline-plum rounded-[12px] p-3 text-left transition ${
                  isCurrent
                    ? `sticker ${isLive ? "bg-pnl-red-soft" : "bg-mint"} cursor-default`
                    : "bg-cream hover:bg-cream-deep"
                } ${pending && !isCurrent ? "opacity-50" : ""}`}
              >
                <div className="font-black text-plum flex items-center gap-2">
                  {label}
                  {isCurrent && (
                    <span className="text-xs font-bold uppercase tracking-wider text-plum-mid">
                      current
                    </span>
                  )}
                </div>
                <div className="mt-1 text-xs text-plum-mid">{description}</div>
              </button>
            );
          })}
        </div>

        {state && (
          <p
            className={`mt-3 text-sm ${state.ok ? "text-pnl-green" : "text-pnl-red"}`}
          >
            {state.message}
          </p>
        )}
      </div>
    </form>
  );
}
