import Link from "next/link";
import { SignInForm } from "./form";
import { Mascot } from "@/components/mascot";

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  const errorMessage =
    error === "invalid_link"
      ? "That confirmation link is missing required parameters. Try requesting a new one by signing up again."
      : error
        ? `Confirmation failed: ${error}`
        : null;

  return (
    <main className="flex-1 flex flex-col">
      <header className="px-6 py-6 sm:px-12">
        <Link href="/" className="text-2xl font-black tracking-tight text-plum">
          aribot
        </Link>
      </header>

      <section className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md">
          <div className="flex justify-center">
            <Mascot pose="wink" tone="peri" size={120} />
          </div>
          <h1 className="mt-6 t-page-title text-plum text-center">
            Welcome back
          </h1>
          <p className="mt-3 t-body text-plum-mid text-center">
            Quick check before you trade — sign in to your vault.
          </p>

          {errorMessage && (
            <div className="mt-6 outline-plum rounded-[12px] bg-pnl-red-soft text-plum px-4 py-3 text-sm">
              {errorMessage}
            </div>
          )}

          <div className="mt-8">
            <SignInForm />
          </div>

          <p className="mt-8 text-sm text-plum-mid">
            New here?{" "}
            <Link href="/sign-up" className="font-bold text-plum underline">
              Create an account
            </Link>
          </p>
        </div>
      </section>
    </main>
  );
}
