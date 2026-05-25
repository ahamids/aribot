import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { aribotApi, ApiError } from "@/lib/api/aribot";
import { readTheme } from "@/lib/theme";
import { AppNav } from "../nav";
import { SettingsClient } from "./settings-client";
import { ThemeToggle } from "./theme-toggle";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getUser();
  if (!data.user) redirect("/sign-in");

  const theme = await readTheme();

  // We only need a few server-resolved facts here — the actual toggle
  // state and danger-zone actions live client-side so we can show
  // confirmation dialogs and surface errors inline.
  let initialTestnet: boolean | null = null;
  let initialMode: string | null = null;
  let botRunning = false;
  let backendError: string | null = null;
  try {
    const status = await aribotApi.status();
    initialTestnet = status.testnet;
    initialMode = status.mode;
    botRunning = status.status === "running" || status.status === "starting";
  } catch (e) {
    backendError =
      e instanceof ApiError
        ? e.body &&
          typeof e.body === "object" &&
          "detail" in e.body &&
          typeof (e.body as { detail: unknown }).detail === "string"
          ? (e.body as { detail: string }).detail
          : e.message
        : String(e);
  }

  return (
    <main className="flex-1 flex flex-col">
      <AppNav email={data.user.email ?? ""} active="settings" />

      <section className="flex-1 px-4 py-6 sm:px-12 sm:py-8">
        <div className="mx-auto w-full max-w-2xl flex flex-col gap-4 sm:gap-6">
          <h1 className="text-2xl sm:text-3xl font-black text-plum">Settings</h1>

          {backendError && (
            <div className="outline-plum rounded-[14px] bg-pnl-red-soft p-4 text-sm">
              <p className="font-bold text-plum">Backend unreachable</p>
              <p className="mt-1 text-plum-mid">{backendError}</p>
              <p className="mt-2 text-plum-mid">
                Settings that require the backend are disabled until it&apos;s
                reachable.
              </p>
            </div>
          )}

          <SettingsClient
            userId={data.user.id}
            email={data.user.email ?? ""}
            initialTestnet={initialTestnet}
            initialMode={initialMode}
            botRunning={botRunning}
          />

          <div className="outline-plum rounded-[18px] bg-paper p-5">
            <h2 className="text-xl font-black text-plum">Appearance</h2>
            <p className="mt-2 text-sm text-plum-mid">
              Theme preference, stored in a cookie so it&apos;s applied
              server-side on the next paint (no flash of unstyled
              content).
            </p>
            <div className="mt-4">
              <ThemeToggle initialTheme={theme} />
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
