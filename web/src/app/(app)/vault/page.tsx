import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { VaultWizard } from "./wizard";

export const dynamic = "force-dynamic";

export default async function VaultPage() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getUser();
  if (!data.user) redirect("/sign-in");

  // We do NOT load the api_key_vault row here, even though we could —
  // the client component will refetch via the browser Supabase client
  // anyway (it needs to do the same after recovery / setup). Two reads
  // is fine, and keeping all vault state on the client makes the
  // wizard logic much simpler.

  return (
    <main className="flex-1 flex flex-col">
      <header className="px-6 py-6 sm:px-12 flex items-center justify-between">
        <Link href="/" className="text-2xl font-black tracking-tight text-plum">
          aribot
        </Link>
        <Link
          href="/dashboard"
          className="outline-plum rounded-[12px] bg-paper text-plum px-4 py-2 text-sm font-bold hover:bg-cream-deep"
        >
          Back to dashboard
        </Link>
      </header>

      <section className="flex-1 px-6 py-8 sm:px-12">
        <div className="mx-auto w-full max-w-2xl">
          <VaultWizard userId={data.user.id} />
        </div>
      </section>
    </main>
  );
}
