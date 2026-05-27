"use client";

/**
 * <TypedConfirmDialog> — confirm dialog gated by typing a word.
 *
 * Ported from the design package's LIVE-mode confirm sheet
 * (`screens-main.jsx:243-285`). Spec safety contract: starting in LIVE
 * mode requires the operator to literally type "LIVE" before the
 * destructive button enables. A modal alone isn't enough — the typed
 * gate is what distinguishes "accidental click" from "deliberate
 * commitment".
 *
 * Reused for any high-stakes confirmation. Currently:
 *   - Starting the bot in LIVE mode
 *   - Switching the configured mode to LIVE (from the mode picker)
 *
 * Built on the native <dialog> + showModal() — same a11y guarantees as
 * the existing ConfirmDialog (focus trap, ESC, backdrop) — with an
 * additional input + match check + mascot slot above the title.
 */

import { useEffect, useRef, useState } from "react";
import { Mascot, type MascotPose, type MascotTone } from "@/components/mascot";

export interface TypedConfirmDialogProps {
  open: boolean;
  title: React.ReactNode;
  body: React.ReactNode;
  confirmWord: string;
  confirmLabel: string;
  cancelLabel?: string;
  busy?: boolean;
  mascotPose?: MascotPose;
  mascotTone?: MascotTone;
  /** Hint shown above the input. Defaults to: TYPE {confirmWord} TO CONFIRM. */
  inputLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function TypedConfirmDialog({
  open,
  title,
  body,
  confirmWord,
  confirmLabel,
  cancelLabel = "Cancel",
  busy = false,
  mascotPose = "serious",
  mascotTone = "coral",
  inputLabel,
  onConfirm,
  onCancel,
}: TypedConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement | null>(null);
  const [typed, setTyped] = useState("");

  // Open / close the native dialog in sync with the prop. Reset the typed
  // value every time the dialog opens so a previous attempt's text doesn't
  // pre-arm a fresh confirmation.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) {
      el.showModal();
      setTyped("");
    }
    if (!open && el.open) el.close();
  }, [open]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const handleClose = () => {
      if (open) onCancel();
    };
    el.addEventListener("close", handleClose);
    return () => el.removeEventListener("close", handleClose);
  }, [open, onCancel]);

  function onDialogClick(e: React.MouseEvent<HTMLDialogElement>) {
    if (busy) return;
    if (e.target === e.currentTarget) onCancel();
  }

  const matches = typed === confirmWord;
  const armed = matches && !busy;

  function tryConfirm() {
    if (armed) onConfirm();
  }

  return (
    <dialog
      ref={ref}
      onClick={onDialogClick}
      className="
        backdrop:bg-plum/40 backdrop:backdrop-blur-[1px]
        outline-plum-thick rounded-[20px] bg-paper text-plum
        p-0 max-w-md w-[calc(100vw-2rem)]
        sticker
      "
    >
      <div className="p-6">
        <div className="flex justify-center mb-3">
          <Mascot pose={mascotPose} tone={mascotTone} size={92} />
        </div>
        <h2 className="t-section-h2 text-plum text-center">{title}</h2>
        <div className="mt-3 t-detail text-plum-mid text-center">{body}</div>

        <label className="block mt-5">
          <span className="t-section-label text-plum-mid block mb-1.5">
            {inputLabel ?? `Type ${confirmWord} to confirm`}
          </span>
          <input
            type="text"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            autoCapitalize="characters"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                tryConfirm();
              }
            }}
            disabled={busy}
            className="w-full outline-plum rounded-[12px] bg-paper text-plum px-4 py-3 t-body tabular-nums focus:outline-none focus:ring-2 focus:ring-coral focus:border-transparent disabled:opacity-50"
            placeholder={confirmWord}
          />
        </label>

        <div className="mt-5 flex gap-3 justify-end">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="outline-plum rounded-[12px] bg-paper text-plum px-4 py-2.5 font-bold hover:bg-cream-deep disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={tryConfirm}
            disabled={!armed}
            className="outline-plum-thick rounded-[12px] bg-pnl-red text-paper px-5 py-2.5 font-black sticker disabled:opacity-50 disabled:translate-y-0 transition hover:translate-y-[-2px]"
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  );
}
