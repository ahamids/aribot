"use client";

/**
 * <Toggle> — 56x32 switch ported from design-pkg/components.jsx:290-307.
 *
 * Mint when ON, cream-deep when OFF. A 26px white knob with the sticker
 * shadow slides between left and right positions. Used in Settings →
 * Notifications and any future boolean preference surface.
 *
 * Built on top of a real <input type="checkbox"> kept sr-only inside
 * the label so FormData captures values automatically when used inside
 * a <form>. Keyboard (Space) and pointer interactions both work.
 */

import { useId } from "react";

export interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Accessible label for screen readers when the visual label is decorative. */
  ariaLabel?: string;
  /** Optional name for FormData capture. */
  name?: string;
  disabled?: boolean;
}

export function Toggle({
  checked,
  onChange,
  ariaLabel,
  name,
  disabled,
}: ToggleProps) {
  const id = useId();
  return (
    <label
      htmlFor={id}
      className={`relative inline-block w-14 h-8 ${
        disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
      }`}
    >
      <input
        id={id}
        type="checkbox"
        name={name}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        aria-label={ariaLabel}
        className="peer sr-only"
      />
      <span
        aria-hidden
        className={`
          absolute inset-0 rounded-full outline-plum transition-colors
          ${checked ? "bg-mint" : "bg-cream-deep"}
          peer-focus-visible:ring-2 peer-focus-visible:ring-coral
        `}
      />
      <span
        aria-hidden
        className={`
          absolute top-[1px] h-[26px] w-[26px] rounded-full
          bg-paper outline-plum sticker transition-[left]
          ${checked ? "left-[26px]" : "left-[1px]"}
        `}
      />
    </label>
  );
}
