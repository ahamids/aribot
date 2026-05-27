import Link from "next/link";
import { Mascot } from "@/components/mascot";

/**
 * Splash / Welcome screen. Ported pattern from
 * design-pkg/screens-onboarding.jsx:3-33: big waving mascot framed by
 * decorative blobs, "Aribot" wordmark with the coral-deep "bot" pop,
 * tagline, then two stacked CTAs (primary coral / soft cream). The
 * decorative blobs are absolutely positioned around the mascot so they
 * read as confetti rather than UI chrome.
 */
export default function Home() {
  return (
    <main className="flex-1 flex flex-col">
      <header className="px-6 py-6 sm:px-12">
        <Link
          href="/"
          className="text-2xl font-black tracking-tight text-plum"
        >
          aribot
        </Link>
      </header>

      <section className="flex-1 flex items-center justify-center px-6 sm:px-12">
        <div className="w-full max-w-md py-12 flex flex-col items-center gap-8 sm:gap-10">
          {/* Mascot + decorative blobs */}
          <div className="relative">
            <span
              aria-hidden
              className="absolute -top-2 -left-6 h-8 w-8 rounded-full bg-coral outline-plum -rotate-12"
            />
            <span
              aria-hidden
              className="absolute top-8 -right-8 h-6 w-6 rounded-full bg-peri outline-plum"
            />
            <span
              aria-hidden
              className="absolute bottom-2 -right-2 h-5 w-5 rounded-[6px] bg-mint outline-plum rotate-12"
            />
            <Mascot pose="waving" tone="yellow" size={200} />
          </div>

          <div className="text-center">
            <h1 className="text-6xl sm:text-7xl font-black tracking-tighter text-plum leading-none">
              Ari<span className="text-coral-deep">bot</span>
            </h1>
            <p className="mt-3 t-body text-plum-mid">
              Your friendly trading bot — on your terms.
            </p>
          </div>

          <div className="flex flex-col gap-3 w-full">
            <Link
              href="/sign-up"
              className="sticker outline-plum-thick rounded-[18px] bg-coral text-plum px-6 py-3.5 text-lg font-black inline-flex items-center justify-center transition hover:translate-y-[-2px]"
            >
              Create account
            </Link>
            <Link
              href="/sign-in"
              className="outline-plum rounded-[18px] bg-paper text-plum px-6 py-3.5 text-lg font-bold inline-flex items-center justify-center transition hover:bg-cream-deep"
            >
              I already have one
            </Link>
          </div>

          <p className="t-detail text-plum-soft text-center">
            BYO keys · encrypted on your device · beta
          </p>
        </div>
      </section>

      <footer className="px-6 py-8 sm:px-12 t-detail text-plum-soft">
        <div className="mx-auto max-w-3xl flex flex-col sm:flex-row gap-2 sm:gap-6">
          <span>© 2026 Aribot</span>
          <a
            href="https://api.aribot.app/healthz"
            className="hover:text-plum-mid"
            target="_blank"
            rel="noreferrer"
          >
            API status
          </a>
        </div>
      </footer>
    </main>
  );
}
