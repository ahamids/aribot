import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import {
  aribotApi,
  ApiError,
  type TradesResponse,
} from "@/lib/api/aribot";
import { AppNav } from "../nav";
import { HistoryClient } from "./history-client";

export const dynamic = "force-dynamic";

// Backend caps `days` at 30 — see GET /trades in status_server.py.
// Anything bigger is silently clamped, so we cap on this side too so
// the user knows what to expect.
const MAX_DAYS = 30;

interface HistoryPageProps {
  searchParams: Promise<{ days?: string }>;
}

export default async function HistoryPage({ searchParams }: HistoryPageProps) {
  const supabase = await createClient();
  const { data } = await supabase.auth.getUser();
  if (!data.user) redirect("/sign-in");

  const params = await searchParams;
  const requestedDays = Number.parseInt(params.days ?? "30", 10);
  const days = Number.isFinite(requestedDays)
    ? Math.max(1, Math.min(requestedDays, MAX_DAYS))
    : 30;

  let trades: TradesResponse | null = null;
  let backendError: string | null = null;
  try {
    trades = await aribotApi.trades(days);
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
      <AppNav email={data.user.email ?? ""} active="history" />

      <section className="flex-1 px-4 py-6 sm:px-12 sm:py-8">
        <div className="mx-auto w-full max-w-4xl flex flex-col gap-4 sm:gap-6">
          <div>
            <h1 className="text-2xl sm:text-3xl font-black text-plum">Trade history</h1>
            <p className="mt-2 text-plum-mid">
              Closed trades — newest first. Backend caps at the last{" "}
              <strong>{MAX_DAYS} days</strong>; longer windows coming in M7.
            </p>
          </div>

          {backendError && (
            <div className="outline-plum rounded-[14px] bg-pnl-red-soft p-4 text-sm">
              <p className="font-bold text-plum">Backend unreachable</p>
              <p className="mt-1 text-plum-mid">{backendError}</p>
            </div>
          )}

          {trades && (
            <HistoryClient
              initialDays={days}
              trades={trades.trades}
              maxDays={MAX_DAYS}
            />
          )}
        </div>
      </section>
    </main>
  );
}
