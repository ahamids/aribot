"use client";

/**
 * <HoldButton> — fires `onConfirm` only after the user holds for `holdMs`.
 *
 * Ported from the design package's KillButton (`screens-main.jsx:226-240`).
 * The spec's safety contract: a tap never trips the kill switch — you have
 * to hold for 1.5s, watch a fill animation, and commit. This component
 * encapsulates that mechanic so it can be reused for any "irreversible
 * action behind a fuse" — currently the kill switch, and a candidate
 * for any future destructive control.
 *
 * Interaction:
 *   - mousedown / touchstart starts a rAF-driven progress meter
 *   - progress reaches 1.0 at `holdMs` → fires onConfirm exactly once
 *   - mouseup / touchend / mouseleave / blur before completion cancels
 *     and resets the meter to 0
 *   - the danger fill scales left-to-right via CSS transform; the label
 *     swaps from `label` to `holdingLabel` while held
 *
 * Accessibility:
 *   - The button is keyboard-focusable; Space/Enter is intentionally NOT
 *     wired to hold (a single keypress shouldn't trip a kill switch).
 *     Operators who can't use a pointer get a separate confirm dialog
 *     fallback via the parent (TODO when an a11y issue surfaces).
 *   - `aria-label` describes the hold requirement.
 *   - During hold, aria-valuenow updates as the role=progressbar.
 */
import { useEffect, useRef, useState } from "react";

export interface HoldButtonProps {
  onConfirm: () => void;
  holdMs?: number;
  label?: string;
  holdingLabel?: string;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
  tone?: "danger" | "coral";
}

export function HoldButton({
  onConfirm,
  holdMs = 1500,
  label = "HOLD 1.5s",
  holdingLabel = "TRIPPING…",
  disabled = false,
  ariaLabel,
  className = "",
  tone = "danger",
}: HoldButtonProps) {
  const [progress, setProgress] = useState(0);
  const startRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);
  const firedRef = useRef(false);

  function clearRaf() {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }

  function reset() {
    clearRaf();
    startRef.current = null;
    firedRef.current = false;
    setProgress(0);
  }

  function tick(now: number) {
    if (startRef.current == null || firedRef.current) return;
    const elapsed = now - startRef.current;
    const p = Math.min(1, elapsed / holdMs);
    setProgress(p);
    if (p >= 1) {
      firedRef.current = true;
      onConfirm();
      // Hold the filled bar for a beat so the user sees commitment, then
      // reset. If the parent unmounts us (e.g., changes status), the
      // useEffect cleanup below handles it.
      setTimeout(() => reset(), 250);
      return;
    }
    rafRef.current = requestAnimationFrame(tick);
  }

  function begin() {
    if (disabled || firedRef.current) return;
    startRef.current = performance.now();
    rafRef.current = requestAnimationFrame(tick);
  }

  function end() {
    if (firedRef.current) return; // confirmation in flight; let it finish
    reset();
  }

  useEffect(() => () => clearRaf(), []);

  const fillColor =
    tone === "danger" ? "bg-pnl-red" : "bg-coral-deep";

  return (
    <button
      type="button"
      disabled={disabled}
      onPointerDown={begin}
      onPointerUp={end}
      onPointerLeave={end}
      onPointerCancel={end}
      onBlur={end}
      aria-label={ariaLabel ?? `${label}. Hold to confirm.`}
      role="button"
      aria-pressed={progress > 0}
      className={`
        relative isolate overflow-hidden
        outline-plum-thick rounded-[12px]
        ${tone === "danger" ? "bg-pnl-red-soft" : "bg-coral"}
        sticker
        px-5 py-2.5
        select-none touch-none
        disabled:opacity-50 disabled:cursor-not-allowed
        transition
        ${className}
      `}
    >
      {/* Animated fill — width scales L→R as the user holds. */}
      <span
        aria-hidden
        className={`absolute inset-0 origin-left ${fillColor} transition-transform`}
        style={{
          transform: `scaleX(${progress})`,
          transitionDuration: progress === 0 ? "120ms" : "0ms",
        }}
      />
      {/* Foreground label — sits above the fill via z-stacking on the
          fill (absolute) vs. label (default flow with z-10). Mix-blend
          stays plum-readable over both red-soft and red fills. */}
      <span
        className="relative z-10 font-black text-plum t-section-label tracking-[0.08em]"
      >
        {progress > 0 ? holdingLabel : label}
      </span>
    </button>
  );
}
