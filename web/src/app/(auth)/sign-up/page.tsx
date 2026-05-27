import Link from "next/link";
import { SignUpForm } from "./form";
import { Mascot } from "@/components/mascot";

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
          <div className="flex justify-center">
            <Mascot pose="waving" tone="mint" size={130} />
          </div>
          <h1 className="mt-6 t-page-title text-plum text-center">
            Make an account
          </h1>
          <p className="mt-3 t-body text-plum-mid text-center">
            Aribot encrypts your Bybit keys on your device. Pick a strong
            password — losing it means losing access to your vault.
          </p>

          <div className="mt-8">
            <SignUpForm />
          </div>

          <p className="mt-8 t-detail text-plum-mid text-center">
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
