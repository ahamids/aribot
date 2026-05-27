"use client";

import { useActionState, useRef, useState } from "react";
import { setBotMode } from "@/app/actions/bot";
import { TypedConfirmDialog } from "@/components/typed-confirm-dialog";
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
  const [confirmLive, setConfirmLive] = useState(false);

  function onModeClick(
    e: React.MouseEvent<HTMLButtonElement>,
    mode: BotMode,
  ) {
    if (mode !== "LIVE") return;
    // Hold the form submit until the user types LIVE.
    e.preventDefault();
    setConfirmLive(true);
  }

  function confirmSwitchToLive() {
    setConfirmLive(false);
    // Programmatically submit with mode=LIVE. Append a synthetic hidden
    // field because requestSubmit doesn't know which button was clicked.
    const form = formRef.current;
    if (!form) return;
    const hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = "mode";
    hidden.value = "LIVE";
    form.appendChild(hidden);
    form.requestSubmit();
    // Clean up so a subsequent submit doesn't pile on duplicates.
    queueMicrotask(() => hidden.remove());
  }

  return (
    <>
      <form ref={formRef} action={action}>
        <div className="outline-plum rounded-[18px] bg-paper p-5">
          <div className="t-section-label text-plum-mid">Mode</div>
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
                  onClick={(e) => onModeClick(e, mode)}
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
                  <div className="mt-1 t-detail text-plum-mid">{description}</div>
                </button>
              );
            })}
          </div>

          {state && (
            <p
              className={`mt-3 t-detail ${state.ok ? "text-pnl-green" : "text-pnl-red"}`}
            >
              {state.message}
            </p>
          )}
        </div>
      </form>

      <TypedConfirmDialog
        open={confirmLive}
        title={
          <>
            Switch to <span className="text-pnl-red">LIVE</span> mode?
          </>
        }
        body="The bot is configured for LIVE only after this. Real orders happen at Start — you'll be asked to confirm again then."
        confirmWord="LIVE"
        confirmLabel="Switch to LIVE"
        mascotPose="serious"
        mascotTone="coral"
        busy={pending}
        onConfirm={confirmSwitchToLive}
        onCancel={() => setConfirmLive(false)}
      />
    </>
  );
}
