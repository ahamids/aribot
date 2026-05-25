import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { signOut } from "@/app/actions/auth";
import {
  aribotApi,
  ApiError,
  type StatusResponse,
  type CredentialsStatusResponse,
  type PositionsResponse,
  type TradesResponse,
  type EquityResponse,
} from "@/lib/api/aribot";
import { ModePicker } from "./mode-picker";
import { AutoRefresh } from "./auto-refresh";
import { PositionsCard } from "./positions-card";
import { TradesCard } from "./trades-card";
import { EquitySparkline } from "./equity-sparkline";

export const dynamic = "force-dynamic";

interface BackendSnapshot {
  status: StatusResponse | null;
  credentials: CredentialsStatusResponse | null;
  positions: PositionsResponse | null;
  trades: TradesResponse | null;
  equity: EquityResponse | null;
  error: { code: number; message: string } | null;
}

async function getBackendSnapshot(): Promise<BackendSnapshot> {
  try {
    // Fetch in parallel. If credentials.loaded is false (no Bybit keys
    // pushed yet) the bot can't possibly have positions/trades/equity,
    // but the backend still returns empty arrays — no special-casing
    // needed on this end.
    const [status, credentials, positions, trades, equity] = await Promise.all(
      [
        aribotApi.status(),
        aribotApi.credentialsStatus(),
        aribotApi.positions().catch(() => null),
        aribotApi.trades(7).catch(() => null),
        aribotApi.equity(24).catch(() => null),
      ],
    );
    return { status, credentials, positions, trades, equity, error: null };
  } catch (e) {
    if (e instanceof ApiError) {
      // Surface FastAPI's HTTPException(detail=...) so JWT failures are
      // actionable. Falls back to the generic message if the body wasn't
      // a structured error.
      const detail =
        e.body &&
        typeof e.body === "object" &&
        "detail" in e.body &&
        typeof (e.body as { detail: unknown }).detail === "string"
          ? (e.body as { detail: string }).detail
          : null;
      return {
        status: null,
        credentials: null,
        positions: null,
        trades: null,
        equity: null,
        error: {
          code: e.status,
          message: detail ? `${e.message} — ${detail}` : e.message,
        },
      };
    }
    return {
      status: null,
      credentials: null,
      positions: null,
      trades: null,
      equity: null,
      error: { code: 0, message: String(e) },
    };
  }
}

export default async function DashboardPage() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getUser();
  if (!data.user) redirect("/sign-in");

  const snap = await getBackendSnapshot();

  return (
    <main className="flex-1 flex flex-col">
      <header className="px-6 py-6 sm:px-12 flex items-center justify-between">
        <Link href="/" className="text-2xl font-black tracking-tight text-plum">
          aribot
        </Link>
        <div className="flex items-center gap-3">
          <span className="hidden sm:inline text-sm text-plum-mid">
            {data.user.email}
          </span>
          <form action={signOut}>
            <button
              type="submit"
              className="outline-plum rounded-[12px] bg-paper text-plum px-4 py-2 text-sm font-bold hover:bg-cream-deep"
            >
              Sign out
            </button>
          </form>
        </div>
      </header>

      <section className="flex-1 px-6 py-8 sm:px-12">
        <div className="mx-auto w-full max-w-3xl flex flex-col gap-6">
          <ConnectionCard snap={snap} />

          {snap.status && (
            <>
              <StatusCard status={snap.status} equity={snap.equity} />
              <ModePicker currentMode={snap.status.mode} />
              <PositionsCard positions={snap.positions} />
              <TradesCard trades={snap.trades} />
              <CredentialsCard credentials={snap.credentials} />
              <ControlsCard
                status={snap.status}
                credentialsLoaded={snap.credentials?.loaded ?? false}
              />
            </>
          )}
        </div>
      </section>

      {/* Re-fetches the Server Component every 15s. Visible-tab only;
          pauses when the tab is hidden. */}
      <AutoRefresh intervalMs={15000} />
    </main>
  );
}

function ConnectionCard({ snap }: { snap: BackendSnapshot }) {
  const connected = snap.error === null;
  return (
    <div
      className={`outline-plum rounded-[18px] p-5 sticker ${
        connected ? "bg-mint" : "bg-pnl-red-soft"
      }`}
    >
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="text-xs uppercase font-bold tracking-wider text-plum-mid">
            Backend
          </div>
          <div className="mt-1 text-lg font-black text-plum">
            {connected
              ? `Connected — version ${snap.status?.version ?? "?"}`
              : `Disconnected (${snap.error?.code})`}
          </div>
          {snap.error && (
            <div className="mt-1 text-sm text-plum-mid">
              {snap.error.message}
            </div>
          )}
        </div>
        <code className="hidden sm:block text-xs text-plum-mid bg-paper outline-plum rounded-[8px] px-2 py-1">
          api.aribot.app
        </code>
      </div>
    </div>
  );
}

function StatusCard({
  status,
  equity,
}: {
  status: StatusResponse;
  equity: EquityResponse | null;
}) {
  const pill = {
    running: { label: "Running", bg: "bg-mint" },
    starting: { label: "Starting", bg: "bg-yellow" },
    stopped: { label: "Stopped", bg: "bg-paper" },
    stale: { label: "Stale", bg: "bg-yellow" },
    killed: { label: "Kill switch", bg: "bg-pnl-red-soft" },
    crashed: { label: "Crashed", bg: "bg-pnl-red-soft" },
  }[status.status] ?? { label: status.status, bg: "bg-paper" };

  return (
    <div className="outline-plum rounded-[18px] bg-paper p-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="text-xs uppercase font-bold tracking-wider text-plum-mid">
            Bot status
          </div>
          <div className="mt-1 flex items-center gap-3">
            <span
              className={`outline-plum rounded-[8px] ${pill.bg} px-2.5 py-1 text-sm font-bold`}
            >
              {pill.label}
            </span>
            <span className="text-sm text-plum-mid">
              mode <span className="font-bold text-plum">{status.mode}</span>
              {status.testnet && (
                <span className="ml-1 text-plum-soft">(testnet)</span>
              )}
            </span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs uppercase font-bold tracking-wider text-plum-mid">
            Open / cycles
          </div>
          <div className="mt-1 text-lg font-black text-plum">
            {status.openPositions} / {status.cycleCount}
          </div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4">
        <Stat
          label="Balance"
          value={`$${status.currentBalance.toFixed(2)}`}
        />
        <Stat
          label="Today's P&L"
          value={`${status.todaysPnl >= 0 ? "+" : ""}$${status.todaysPnl.toFixed(2)}`}
          tone={
            status.todaysPnl > 0
              ? "green"
              : status.todaysPnl < 0
                ? "red"
                : "neutral"
          }
        />
      </div>

      {equity && equity.points.length > 1 && (
        <div className="mt-4">
          <div className="text-xs uppercase font-bold tracking-wider text-plum-mid">
            Equity · last {equity.rangeHours}h
          </div>
          <div className="mt-2">
            <EquitySparkline points={equity.points} />
          </div>
        </div>
      )}

      {status.reason && (
        <p className="mt-3 text-sm text-plum-mid">{status.reason}</p>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "green" | "red";
}) {
  const color =
    tone === "green"
      ? "text-pnl-green"
      : tone === "red"
        ? "text-pnl-red"
        : "text-plum";
  return (
    <div>
      <div className="text-xs uppercase font-bold tracking-wider text-plum-mid">
        {label}
      </div>
      <div className={`mt-1 text-2xl font-black ${color} tabular-nums`}>
        {value}
      </div>
    </div>
  );
}

function CredentialsCard({
  credentials,
}: {
  credentials: CredentialsStatusResponse | null;
}) {
  if (!credentials) return null;
  return (
    <div
      className={`outline-plum rounded-[18px] p-5 ${
        credentials.loaded ? "bg-paper" : "bg-cream-deep"
      }`}
    >
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <div className="text-xs uppercase font-bold tracking-wider text-plum-mid">
            Bybit API keys
          </div>
          <div className="mt-1 text-lg font-black text-plum">
            {credentials.loaded ? "Loaded in memory" : "Not configured"}
          </div>
          {credentials.fingerprint && (
            <div className="mt-1 text-xs font-mono text-plum-mid">
              fp {credentials.fingerprint}
            </div>
          )}
          {!credentials.loaded && (
            <p className="mt-2 text-sm text-plum-mid max-w-md">
              Your keys are encrypted in your browser before they ever
              leave the device. Set a passphrase, save a recovery code,
              push the ciphertext to the bot.
            </p>
          )}
        </div>
        <Link
          href="/vault"
          className="sticker outline-plum-thick rounded-[14px] bg-coral text-plum px-5 py-2.5 font-black inline-flex items-center justify-center transition hover:translate-y-[-2px]"
        >
          {credentials.loaded ? "Manage vault" : "Set up vault"}
        </Link>
      </div>
    </div>
  );
}

function ControlsCard({
  status,
  credentialsLoaded,
}: {
  status: StatusResponse;
  credentialsLoaded: boolean;
}) {
  const canStart =
    credentialsLoaded && ["stopped", "stale", "crashed"].includes(status.status);
  const canStop = status.status === "running";

  return (
    <div className="outline-plum rounded-[18px] bg-paper p-5">
      <div className="text-xs uppercase font-bold tracking-wider text-plum-mid">
        Controls
      </div>
      <div className="mt-3 flex flex-wrap gap-3">
        <button
          disabled={!canStart}
          className="sticker outline-plum-thick rounded-[12px] bg-mint text-plum px-5 py-2.5 font-black disabled:opacity-50 disabled:translate-y-0 transition hover:translate-y-[-2px]"
          title={
            !credentialsLoaded
              ? "Add Bybit keys first (M3)"
              : !canStart
                ? "Bot already running"
                : "Start the bot"
          }
        >
          Start
        </button>
        <button
          disabled={!canStop}
          className="outline-plum rounded-[12px] bg-paper text-plum px-5 py-2.5 font-bold disabled:opacity-50 hover:bg-cream-deep"
        >
          Stop
        </button>
        <button
          disabled={status.status === "killed"}
          className="outline-plum rounded-[12px] bg-pnl-red-soft text-plum px-5 py-2.5 font-bold disabled:opacity-50"
        >
          Kill switch
        </button>
      </div>
      <p className="mt-3 text-xs text-plum-soft">
        Controls are wired to the backend but the M2 cut keeps them disabled
        until vault (M3) and the full control loop (M5) ship.
      </p>
    </div>
  );
}
