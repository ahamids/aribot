import Link from "next/link";
import { SignInForm } from "./form";

export default function SignInPage() {
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
            Welcome back
          </h1>
          <p className="mt-3 text-plum-mid">
            Sign in to manage your bot, vault, and positions.
          </p>

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
