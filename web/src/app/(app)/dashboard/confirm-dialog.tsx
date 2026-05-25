"use client";

import { useEffect, useRef } from "react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  body: React.ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  tone?: "neutral" | "danger";
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Native <dialog> + showModal() — gives us ESC-to-close, focus trap,
 * backdrop, and a11y semantics (role=dialog, aria-modal=true) without
 * any extra library.
 *
 * Caller owns open/close state. We only push showModal/close to the
 * DOM when `open` changes, and we wire onClose so backdrop/ESC routes
 * back through onCancel.
 */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "neutral",
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  // Native ::backdrop click closes the dialog via ESC-style cancel.
  // We listen for the close event and route it through onCancel so
  // controlled state stays in sync.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const handleClose = () => {
      if (open) onCancel();
    };
    el.addEventListener("close", handleClose);
    return () => el.removeEventListener("close", handleClose);
  }, [open, onCancel]);

  // Click on the ::backdrop pseudo-element fires a click on the dialog
  // itself (target === dialog). Anywhere inside the panel won't bubble
  // back to the dialog as target.
  function onDialogClick(e: React.MouseEvent<HTMLDialogElement>) {
    if (busy) return;
    if (e.target === e.currentTarget) onCancel();
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
        <h2 className="text-xl font-black text-plum">{title}</h2>
        <div className="mt-3 text-sm text-plum-mid">{body}</div>
        <div className="mt-6 flex gap-3 justify-end">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="outline-plum rounded-[12px] bg-paper text-plum px-4 py-2 font-bold hover:bg-cream-deep disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            autoFocus
            className={`outline-plum-thick rounded-[12px] px-4 py-2 font-black sticker disabled:opacity-50 disabled:translate-y-0 transition hover:translate-y-[-2px] ${
              tone === "danger"
                ? "bg-pnl-red-soft text-plum"
                : "bg-coral text-plum"
            }`}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  );
}
