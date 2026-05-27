"use client";

/**
 * 3-card onboarding carousel. Ported from
 * design-pkg/screens-onboarding.jsx:104-185.
 *
 * Each slide gets a mascot + an illustrative SVG/component + title +
 * body. The dot strip below shrinks inactive dots to 8x8 and stretches
 * the active one to 26x8 (per components.jsx 170-178). Next button
 * advances; on the last slide it routes to /vault to start setup.
 *
 * Skip link in the top-right jumps straight to /dashboard for users
 * who already know the drill (e.g. they reset and started over).
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Mascot, type MascotPose, type MascotTone } from "@/components/mascot";

interface Slide {
  pose: MascotPose;
  tone: MascotTone;
  title: string;
  body: string;
  art: React.ReactNode;
}

const SLIDES: Slide[] = [
  {
    pose: "thumbsup",
    tone: "mint",
    title: "Hello there",
    body: "Aribot runs your USDT-perp strategy on Bybit 24/7. You stay in control: keys, mode, kill switch, all yours.",
    art: <HelloArt />,
  },
  {
    pose: "serious",
    tone: "yellow",
    title: "Bring your Bybit keys",
    body: "Sealed with libsodium on this device before they ever cross the network. Even we can’t read them.",
    art: <VaultArt />,
  },
  {
    pose: "wink",
    tone: "coral",
    title: "Pick a mode",
    body: "Start in PAPER. Step up to SHADOW for real prices, paper PnL. LIVE is real money — opt in when ready.",
    art: <ModeArt />,
  },
];

export function OnboardingCarousel() {
  const router = useRouter();
  const [idx, setIdx] = useState(0);
  const total = SLIDES.length;
  const slide = SLIDES[idx];
  const isLast = idx === total - 1;

  function next() {
    if (!isLast) {
      setIdx((i) => i + 1);
      return;
    }
    router.push("/vault");
  }

  return (
    <main className="flex-1 flex flex-col">
      <header className="px-6 py-4 sm:px-12 flex items-center justify-between">
        <Link
          href="/dashboard"
          className="text-xl font-black tracking-tight text-plum"
        >
          aribot
        </Link>
        <Link
          href="/dashboard"
          className="t-section-label text-plum-mid hover:text-plum"
        >
          Skip
        </Link>
      </header>

      <section className="flex-1 px-6 sm:px-12 flex flex-col items-center justify-center text-center">
        <div className="w-full max-w-md flex flex-col items-center gap-5">
          <Mascot pose={slide.pose} tone={slide.tone} size={150} />
          <div className="min-h-[130px] flex items-center">{slide.art}</div>
          <h2 className="t-section-h2 text-plum">{slide.title}</h2>
          <p className="t-body text-plum-mid max-w-sm">{slide.body}</p>
        </div>
      </section>

      <footer className="px-6 py-6 sm:px-12 flex flex-col items-center gap-4">
        {/* Step indicator: active dot stretches to a pill per spec. */}
        <div className="flex items-center justify-center gap-2">
          {Array.from({ length: total }).map((_, i) => (
            <button
              key={i}
              type="button"
              onClick={() => setIdx(i)}
              aria-label={`Step ${i + 1} of ${total}`}
              aria-current={i === idx ? "step" : undefined}
              className={`h-2 outline-plum rounded-full transition-all ${
                i === idx ? "w-7 bg-coral" : "w-2 bg-cream-deep hover:bg-cream"
              }`}
            />
          ))}
        </div>

        <button
          type="button"
          onClick={next}
          className="sticker outline-plum-thick rounded-[18px] bg-coral text-plum px-6 py-3.5 text-lg font-black w-full max-w-sm transition hover:translate-y-[-2px]"
        >
          {isLast ? "Let’s go →" : "Next →"}
        </button>
      </footer>
    </main>
  );
}

function HelloArt() {
  // Cartoon "your bot ↔ Bybit" link diagram. Coral box (you) connected
  // via a dashed line to a peri box (Bybit). Pure SVG, no Image deps.
  return (
    <svg
      width="280"
      height="120"
      viewBox="0 0 280 120"
      aria-hidden="true"
      role="presentation"
    >
      <rect
        x="10"
        y="30"
        width="80"
        height="60"
        rx="14"
        fill="var(--color-coral)"
        stroke="var(--c-plum)"
        strokeWidth="3"
      />
      <text
        x="50"
        y="62"
        textAnchor="middle"
        fontSize="11"
        fontWeight="800"
        fill="var(--c-plum)"
      >
        YOU
      </text>
      <text
        x="50"
        y="76"
        textAnchor="middle"
        fontSize="9"
        fill="var(--c-plum)"
      >
        aribot.app
      </text>
      <path
        d="M95 60 Q140 30 185 60"
        fill="none"
        stroke="var(--c-plum)"
        strokeWidth="3"
        strokeDasharray="6 4"
      />
      <polygon points="178,55 192,60 178,65" fill="var(--c-plum)" />
      <rect
        x="190"
        y="30"
        width="80"
        height="60"
        rx="14"
        fill="var(--color-peri)"
        stroke="var(--c-plum)"
        strokeWidth="3"
      />
      <text
        x="230"
        y="62"
        textAnchor="middle"
        fontSize="11"
        fontWeight="800"
        fill="var(--c-paper)"
      >
        BYBIT
      </text>
      <text
        x="230"
        y="76"
        textAnchor="middle"
        fontSize="9"
        fill="var(--c-paper)"
      >
        usdt-perp
      </text>
    </svg>
  );
}

function VaultArt() {
  // Chunky padlock over a sealed-box silhouette. Spec art is the same
  // shape — a yellow box with a U-arch padlock and the "SEALED-BOX" tag.
  return (
    <svg
      width="200"
      height="120"
      viewBox="0 0 200 120"
      aria-hidden="true"
      role="presentation"
    >
      <rect
        x="40"
        y="40"
        width="120"
        height="70"
        rx="14"
        fill="var(--color-yellow)"
        stroke="var(--c-plum)"
        strokeWidth="3.5"
      />
      <path
        d="M70 40 V28 a30 30 0 0 1 60 0 V40"
        fill="none"
        stroke="var(--c-plum)"
        strokeWidth="3.5"
        strokeLinecap="round"
      />
      <circle cx="100" cy="72" r="10" fill="var(--c-plum)" />
      <rect x="96" y="78" width="8" height="16" rx="2" fill="var(--c-plum)" />
      <text
        x="100"
        y="106"
        textAnchor="middle"
        fontSize="9"
        fontWeight="800"
        fill="var(--c-plum)"
      >
        SEALED-BOX
      </text>
    </svg>
  );
}

function ModeArt() {
  // The three mode pills laid out side-by-side: PAPER (peri),
  // SHADOW (yellow), LIVE (red). Matches the mode chip color map used
  // on the dashboard so the user sees the same affordance again later.
  const modes = [
    { name: "PAPER", bg: "var(--color-peri)", fg: "var(--c-paper)", note: "Sim only." },
    { name: "SHADOW", bg: "var(--color-yellow)", fg: "var(--c-plum)", note: "Real prices." },
    { name: "LIVE", bg: "var(--color-pnl-red)", fg: "var(--c-paper)", note: "Real money." },
  ];
  return (
    <div className="flex gap-2">
      {modes.map((m) => (
        <div
          key={m.name}
          className="outline-plum rounded-[14px] sticker px-3 py-3 text-center min-w-[78px]"
          style={{ background: m.bg, color: m.fg }}
        >
          <div className="t-section-label tracking-wider">{m.name}</div>
          <div className="mt-1 t-detail opacity-90">{m.note}</div>
        </div>
      ))}
    </div>
  );
}
