import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { signOut } from "@/app/actions/auth";

export default async function DashboardPage() {
  // Server-side belt-and-braces check. The proxy already redirects unauth'd
  // users, but Server Components shouldn't trust that — always call getUser()
  // (or getClaims for cheaper) before rendering sensitive data.
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/sign-in");
  }

  return (
    <main className="flex-1 flex flex-col">
      <header className="px-6 py-6 sm:px-12 flex items-center justify-between">
        <Link href="/" className="text-2xl font-black tracking-tight text-plum">
          aribot
        </Link>
        <form action={signOut}>
          <button
            type="submit"
            className="outline-plum rounded-[12px] bg-paper text-plum px-4 py-2 text-sm font-bold hover:bg-cream-deep"
          >
            Sign out
          </button>
        </form>
      </header>

      <section className="flex-1 px-6 py-12 sm:px-12">
        <div className="mx-auto w-full max-w-3xl">
          <h1 className="text-4xl font-black tracking-tight text-plum">
            You&apos;re signed in.
          </h1>
          <p className="mt-3 text-plum-mid">
            Welcome, <span className="font-bold text-plum">{user.email}</span>.
          </p>

          <div className="mt-10 outline-plum rounded-[18px] bg-paper p-6 sticker">
            <h2 className="text-xl font-black text-plum">Coming next</h2>
            <ul className="mt-3 flex flex-col gap-2 text-plum-mid">
              <li>
                <span className="font-bold text-plum">M2</span> — Bot
                connection setup (host URL + bearer token)
              </li>
              <li>
                <span className="font-bold text-plum">M3</span> — Encrypted
                Bybit API key vault (browser-native crypto)
              </li>
              <li>
                <span className="font-bold text-plum">M4</span> — Live
                dashboard (positions, equity, today&apos;s P&amp;L)
              </li>
              <li>
                <span className="font-bold text-plum">M5</span> — Start /
                stop / kill switch controls
              </li>
            </ul>
            <p className="mt-4 text-sm text-plum-soft">
              This dashboard is M1&apos;s placeholder. Auth works end-to-end:
              sign-up, sign-in, sign-out, protected route.
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
