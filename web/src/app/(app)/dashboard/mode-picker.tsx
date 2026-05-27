"use client";

import { useActionState, useRef, useState } from "react";
import { setBotMode } from "@/app/actions/bot";
import { TypedConfirmDialog } from "@/components/typed-confirm-dialog";
import type { BotMode } from "@/lib/api/aribot";

// Mode descriptions tightened to the design pkg's terse one-liners
// (.design-pkg/aribot/project/screens-onboarding.jsx:149). The chip
// label itself is enough to carry "paper vs shadow vs live"; the body
// line just needs to answer "what does this actually do?" in seven
// words or fewer.
const MODES: { mode: BotMode; description: string }[] = [
  { mode: "PAPER", description: "Sim only." },
  { mode: "SHADOW", description: "Dry-run real auth." },
  { mode: "LIVE", description: "Real money." },
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
        <div className="outline-plum rounded-[18px] bg-paper p-5 sticker">
          <div className="t-section-label text-plum-mid">Mode</div>
          <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3">
            {MODES.map(({ mode, description }) => {
              const isCurrent = mode === currentMode;
              // Spec mandates a brand color per mode when active (design-pkg
              // /project/components.jsx:72-87 ModeChip):
              //   PAPER  → peri   (the "safe sim" brand)
              //   SHADOW → yellow (the "almost real" warning)
              //   LIVE   → pnl-red (the "real money" alarm)
              const activeBg =
                mode === "LIVE"
                  ? "bg-pnl-red text-paper"
                  : mode === "SHADOW"
                    ? "bg-yellow text-plum"
                    : "bg-peri text-paper";
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
                      ? `sticker ${activeBg} cursor-default`
                      : "bg-cream text-plum hover:bg-cream-deep"
                  } ${pending && !isCurrent ? "opacity-50" : ""}`}
                >
                  <div className="t-section-label flex items-center gap-2">
                    <span className="text-sm font-black tracking-tight">
                      {mode}
                    </span>
                    {isCurrent && (
                      <span className="t-section-label opacity-80">current</span>
                    )}
                  </div>
                  <div className="mt-1 t-detail opacity-90">
                    {description}
                  </div>
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
