import Link from "next/link";

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

      <section className="flex-1 flex items-center px-6 sm:px-12">
        <div className="mx-auto w-full max-w-3xl py-12 sm:py-20">
          <h1 className="text-5xl sm:text-7xl font-black tracking-tight text-plum leading-[0.95]">
            Your bot.
            <br />
            Your keys.
            <br />
            <span className="text-coral-deep">Your rules.</span>
          </h1>

          <p className="mt-8 max-w-xl text-lg sm:text-xl text-plum-mid leading-relaxed">
            Aribot runs your USDT-perp trading strategy 24/7 on Bybit.
            Bring your own API keys — encrypted client-side, even we can&apos;t
            read them. Paper, shadow, or live, your call.
          </p>

          <div className="mt-10 flex flex-col sm:flex-row gap-4">
            <Link
              href="/sign-up"
              className="sticker outline-plum-thick rounded-[18px] bg-coral text-plum px-8 py-4 text-lg font-black inline-flex items-center justify-center transition hover:translate-y-[-2px]"
            >
              Get started
            </Link>
            <Link
              href="/sign-in"
              className="outline-plum rounded-[18px] bg-paper text-plum px-8 py-4 text-lg font-bold inline-flex items-center justify-center transition hover:bg-cream-deep"
            >
              Sign in
            </Link>
          </div>

          <p className="mt-12 text-sm text-plum-soft">
            Beta. Bybit testnet supported. Live mode requires you to
            re-confirm every API key.
          </p>
        </div>
      </section>

      <footer className="px-6 py-8 sm:px-12 text-sm text-plum-soft">
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
