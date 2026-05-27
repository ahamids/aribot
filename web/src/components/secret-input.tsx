"use client";

/**
 * <SecretInput> — text input with an eye-toggle for secrets.
 *
 * Ports the design package's Input pattern with `secure=true`
 * (`.design-pkg/aribot/project/components.jsx:117-146`). Spec mandates
 * an eye-toggle on every password/secret field so the operator can
 * spot a paste typo without sending the key over the network. The
 * trust-annotations callout in `screens-onboarding.jsx:300` calls this
 * out by name: "Eye toggle never logs key — show is local state only".
 *
 * Used by:
 *   - sign-in / sign-up password fields
 *   - vault wizard's passphrase (setup, unlock, recover)
 *   - vault wizard's Bybit key/secret fields
 *
 * The "show" state is purely local; the value never crosses an
 * effect boundary based on visibility, so toggling has zero side
 * effects beyond changing the rendered `type` attribute.
 */
import { useId, useState } from "react";

export interface SecretInputProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  /** DOM id; auto-generated if omitted. */
  id?: string;
  /** Same as the underlying input. */
  name?: string;
  autoComplete?: string;
  autoFocus?: boolean;
  required?: boolean;
  placeholder?: string;
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  /** Apply a monospace face — useful for Bybit key/secret strings. */
  monospace?: boolean;
  /** Background variant. Default cream; "paper" matches the sign-in form. */
  bg?: "cream" | "paper";
  /** Inline error message under the field. */
  error?: string;
  disabled?: boolean;
  className?: string;
}

export function SecretInput({
  label,
  value,
  onChange,
  id,
  name,
  autoComplete,
  autoFocus,
  required,
  placeholder,
  onKeyDown,
  monospace,
  bg = "cream",
  error,
  disabled,
  className,
}: SecretInputProps) {
  const generatedId = useId();
  const fieldId = id ?? `secret-${generatedId}`;
  const [shown, setShown] = useState(false);
  const bgClass = bg === "paper" ? "bg-paper" : "bg-cream";

  return (
    <div className={`flex flex-col gap-1.5 ${className ?? ""}`}>
      <label
        htmlFor={fieldId}
        className="t-section-label text-plum-mid"
      >
        {label}
      </label>
      <div className="relative">
        <input
          id={fieldId}
          name={name}
          type={shown ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          autoComplete={autoComplete}
          autoFocus={autoFocus}
          required={required}
          placeholder={placeholder}
          disabled={disabled}
          spellCheck={false}
          autoCorrect="off"
          className={`w-full outline-plum rounded-[12px] ${bgClass} text-plum px-4 py-3 pr-12 t-body placeholder:text-plum-soft focus:outline-none focus:ring-2 focus:ring-coral disabled:opacity-60 ${
            monospace ? "font-mono" : ""
          }`}
        />
        <button
          type="button"
          onClick={() => setShown((s) => !s)}
          disabled={disabled}
          aria-label={shown ? "Hide value" : "Show value"}
          aria-pressed={shown}
          tabIndex={0}
          className="absolute right-1.5 top-1/2 -translate-y-1/2 inline-flex items-center justify-center w-9 h-9 rounded-[10px] outline-plum bg-paper text-plum hover:bg-cream-deep transition disabled:opacity-50"
        >
          <span aria-hidden className="text-base font-black leading-none">
            {shown ? "◉" : "◎"}
          </span>
        </button>
      </div>
      {error && <p className="t-detail text-pnl-red font-bold">{error}</p>}
    </div>
  );
}
