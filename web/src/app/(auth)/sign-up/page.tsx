import Link from "next/link";
import { SignUpForm } from "./form";

export default function SignUpPage() {
  return (
    <main className="flex-1 flex flex-col">
      <header className="px-6 py-6 sm:px-12">
        <Link href="/" className="text-2xl font-black tracking-tight text-plum">
          aribot
        </Link>
      </header>

      <section className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md">
          <h1 className="text-4xl font-black tracking-tight text-plum">
            Create your account
          </h1>
          <p className="mt-3 text-plum-mid">
            Aribot encrypts your Bybit keys client-side. Pick a strong
            password — losing it means losing access to your vault.
          </p>

          <div className="mt-8">
            <SignUpForm />
          </div>

          <p className="mt-8 text-sm text-plum-mid">
            Already have an account?{" "}
            <Link href="/sign-in" className="font-bold text-plum underline">
              Sign in
            </Link>
          </p>
        </div>
      </section>
    </main>
  );
}
