import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex-1 flex flex-col">
      <header className="px-6 py-6 sm:px-12">
        <Link href="/" className="text-2xl font-black tracking-tight text-plum">
          aribot
        </Link>
      </header>

      <section className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md text-center">
          <p className="text-7xl font-black tracking-tight text-coral">404</p>
          <h1 className="mt-4 text-3xl font-black text-plum">
            Page not found
          </h1>
          <p className="mt-3 text-plum-mid">
            The page you&apos;re looking for doesn&apos;t exist (or moved
            without telling us). Try the dashboard.
          </p>
          <div className="mt-8 flex gap-3 justify-center">
            <Link
              href="/dashboard"
              className="sticker outline-plum-thick rounded-[14px] bg-coral text-plum px-5 py-2.5 font-black inline-flex items-center justify-center transition hover:translate-y-[-2px]"
            >
              Dashboard
            </Link>
            <Link
              href="/"
              className="outline-plum rounded-[14px] bg-paper text-plum px-5 py-2.5 font-bold inline-flex items-center justify-center hover:bg-cream-deep"
            >
              Home
            </Link>
          </div>
        </div>
      </section>
    </main>
  );
}
