"use client";

/**
 * <ChunkyCheckbox> — 24×24 cartoon checkbox with the design's "sticker" feel.
 *
 * Replaces the native <input type="checkbox"> on the sign-up
 * encryption-acknowledgement field (and any future binary consent
 * surface). Ported from the design pkg's onboarding sheet's chunky
 * check: plum-bordered square, coral fill when checked, plum ✓ glyph.
 * Spec reference: `.design-pkg/aribot/project/screens-onboarding.jsx:60-66`.
 *
 * Form-submission compatible: keeps a real (sr-only) <input type="checkbox">
 * inside the label so FormData / Server Action handlers continue to read
 * the value the way they would any other checkbox. Visual state is
 * driven by local component state.
 */

import { useState, useId } from "react";

export interface ChunkyCheckboxProps {
  name: string;
  required?: boolean;
  defaultChecked?: boolean;
  children: React.ReactNode;
  /** Forwarded to the visible label wrapper. */
  className?: string;
  /** Optional callback when the value flips. */
  onChange?: (checked: boolean) => void;
}

export function ChunkyCheckbox({
  name,
  required,
  defaultChecked = false,
  children,
  className,
  onChange,
}: ChunkyCheckboxProps) {
  const id = useId();
  const [checked, setChecked] = useState(defaultChecked);

  return (
    <label
      htmlFor={id}
      className={`flex items-start gap-3 cursor-pointer select-none ${className ?? ""}`}
    >
      <input
        id={id}
        type="checkbox"
        name={name}
        required={required}
        checked={checked}
        onChange={(e) => {
          setChecked(e.target.checked);
          onChange?.(e.target.checked);
        }}
        className="peer sr-only"
      />
      <span
        aria-hidden
        className={`
          mt-0.5 inline-flex items-center justify-center
          h-6 w-6 rounded-[6px] outline-plum-thick shrink-0
          transition
          peer-focus-visible:ring-2 peer-focus-visible:ring-coral
          ${checked ? "bg-coral" : "bg-paper hover:bg-cream-deep"}
        `}
      >
        {checked && (
          <span className="text-plum font-black text-base leading-none">
            ✓
          </span>
        )}
      </span>
      <span className="t-body text-plum-mid">{children}</span>
    </label>
  );
}
