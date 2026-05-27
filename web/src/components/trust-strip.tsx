/**
 * <TrustStrip> — peri-blue band with a lock glyph, designed to dramatize
 * the "your secret never leaves the device" moment.
 *
 * Ported from `.design-pkg/aribot/project/screens-onboarding.jsx:237-307`
 * (the ApiVault trust moment). The reality-check audit called this out
 * specifically: "Wrap the BybitKeysStep in a peri-blue trust strip with
 * a lock icon (or the chunky padlock SVG from screens-onboarding.jsx:127-133)
 * and 'Encrypted on this device. Even we can't read these.' copy".
 *
 * Renders as a top-bar over the content it's wrapping (or as a standalone
 * banner above input fields). Background uses the peri brand color, which
 * is reserved in the palette for "trust / sealed-box" surfaces.
 */
export interface TrustStripProps {
  title: string;
  body: string;
  className?: string;
}

export function TrustStrip({ title, body, className }: TrustStripProps) {
  return (
    <div
      className={`outline-plum rounded-[14px] bg-peri text-paper p-4 flex items-start gap-3 ${className ?? ""}`}
    >
      <span
        aria-hidden
        className="inline-flex items-center justify-center h-10 w-10 rounded-[10px] bg-paper outline-plum text-plum shrink-0"
      >
        <LockGlyph />
      </span>
      <div className="min-w-0">
        <p className="t-section-label tracking-wider">{title}</p>
        <p className="mt-1 t-detail leading-snug opacity-95">{body}</p>
      </div>
    </div>
  );
}

/**
 * Chunky cartoon padlock — drawn inline as SVG so it inherits the
 * surrounding `text-plum` color without needing a separate asset file.
 * Matches the design pkg's padlock from screens-onboarding.jsx:127-133.
 */
function LockGlyph({ size = 22 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <rect
        x="4"
        y="11"
        width="16"
        height="11"
        rx="2.5"
        fill="currentColor"
        opacity="0.18"
        stroke="currentColor"
        strokeWidth="2.2"
      />
      <path
        d="M7.5 11V8.5 a4.5 4.5 0 0 1 9 0 V11"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        fill="none"
      />
      <circle cx="12" cy="16" r="1.6" fill="currentColor" />
      <path
        d="M12 16 V18.5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}
