import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
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
import { ControlsPanel } from "./controls-panel";
import { AppNav } from "../nav";
import { Mascot, type MascotPose, type MascotTone } from "@/components/mascot";

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
      <AppNav email={data.user.email ?? ""} active="dashboard" />

      <section className="flex-1 px-4 py-6 sm:px-12 sm:py-8">
        <div className="mx-auto w-full max-w-3xl flex flex-col gap-4 sm:gap-6">
          <ConnectionCard snap={snap} />

          {snap.status?.status === "killed" && <KillSwitchBanner />}

          {snap.status && (
            <>
              <StatusCard status={snap.status} equity={snap.equity} />
              <ControlsPanel
                status={snap.status}
                credentialsLoaded={snap.credentials?.loaded ?? false}
              />
              <ModePicker currentMode={snap.status.mode} />
              <PositionsCard positions={snap.positions} />
              <TradesCard trades={snap.trades} />
              <CredentialsCard
                credentials={snap.credentials}
                mode={snap.status.mode}
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
  // Spec rule (design-pkg/screens-sheets.jsx:195): red/green reserved for
  // PnL, direction chips, kill switch, and LIVE confirm. A backend that's
  // unreachable is not a PnL signal — degrade to the cream-deep "attention"
  // surface and let the ⚠ glyph + text carry the alarm.
  return (
    <div
      className={`outline-plum rounded-[18px] p-5 sticker ${
        connected ? "bg-mint" : "bg-cream-deep"
      }`}
    >
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          {!connected && (
            <span
              aria-hidden
              className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-yellow outline-plum font-black text-plum shrink-0"
            >
              !
            </span>
          )}
          <div className="min-w-0">
            <div className="t-section-label text-plum-mid">Backend</div>
            <div className="mt-1 t-row-symbol text-plum">
              {connected
                ? `Connected — version ${snap.status?.version ?? "?"}`
                : `Disconnected (${snap.error?.code})`}
            </div>
            {snap.error && (
              <div className="mt-1 t-detail text-plum-mid break-words">
                {snap.error.message}
              </div>
            )}
          </div>
        </div>
        <code className="hidden sm:block t-detail text-plum-mid bg-paper outline-plum rounded-[8px] px-2 py-1 shrink-0">
          api.aribot.app
        </code>
      </div>
    </div>
  );
}

/**
 * Maps backend status → mascot pose + tone. Spec's mascot lives in the
 * StatusCard with its pose tied to bot state so a glance tells you what's
 * happening before reading any text. Matches the design package's intent
 * at `.design-pkg/aribot/project/screens-dashboard.jsx:36`.
 */
function mascotForStatus(
  s: StatusResponse["status"],
): { pose: MascotPose; tone: MascotTone } {
  switch (s) {
    case "running":
      return { pose: "happy", tone: "mint" };
    case "starting":
      return { pose: "alert", tone: "yellow" };
    case "stopping":
      return { pose: "alert", tone: "yellow" };
    case "stale":
      return { pose: "questioning", tone: "yellow" };
    case "stopped":
      return { pose: "napping", tone: "cream" };
    case "killed":
      return { pose: "serious", tone: "coral" };
    case "crashed":
      return { pose: "sad", tone: "coral" };
    case "error":
    default:
      return { pose: "questioning", tone: "yellow" };
  }
}

function StatusCard({
  status,
  equity,
}: {
  status: StatusResponse;
  equity: EquityResponse | null;
}) {
  // Pill: each status pairs a label with a glyph so the signal isn't
  // carried by color alone (the spec's color-blind rule, design-pkg
  // chats/chat1.md:178-181). Glyphs match the design's circular dots:
  //   ▶ running · ⏵ starting · ⏸ stopping · ■ stopped · … stale ·
  //   ⚑ killed · ! crashed/error
  const pill = {
    running:  { label: "Running",     bg: "bg-mint",         glyph: "▶" },
    starting: { label: "Starting",    bg: "bg-yellow",       glyph: "…" },
    stopping: { label: "Stopping",    bg: "bg-yellow",       glyph: "…" },
    stopped:  { label: "Stopped",     bg: "bg-paper",        glyph: "■" },
    stale:    { label: "Stale",       bg: "bg-yellow",       glyph: "?" },
    killed:   { label: "Kill switch", bg: "bg-pnl-red-soft", glyph: "⚑" },
    crashed:  { label: "Crashed",     bg: "bg-pnl-red-soft", glyph: "!" },
    error:    { label: "Error",       bg: "bg-pnl-red-soft", glyph: "!" },
  }[status.status] ?? { label: status.status, bg: "bg-paper", glyph: "?" };

  const { pose, tone } = mascotForStatus(status.status);
  const pnlSign = status.todaysPnl >= 0 ? "+" : "";
  const pnlColor =
    status.todaysPnl > 0
      ? "text-pnl-green"
      : status.todaysPnl < 0
        ? "text-pnl-red"
        : "text-plum";

  return (
    <div className="outline-plum rounded-[18px] bg-paper p-5 sticker">
      <div className="flex items-center gap-4 flex-wrap">
        <Mascot pose={pose} tone={tone} size={96} />
        <div className="min-w-0 flex-1">
          <div className="t-section-label text-plum-mid">Bot status</div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <span
              className={`outline-plum rounded-[8px] ${pill.bg} px-2.5 py-1 text-sm font-bold inline-flex items-center gap-1.5`}
            >
              <span aria-hidden className="text-xs font-black leading-none">
                {pill.glyph}
              </span>
              {pill.label}
            </span>
            <span className="t-detail text-plum-mid">
              mode <span className="font-bold text-plum">{status.mode}</span>
              {status.testnet && (
                <span className="ml-1 text-plum-soft">(testnet)</span>
              )}
            </span>
            <RegimePill regime={status.btcRegime} />
          </div>
          <div className="mt-2 t-detail text-plum-mid">
            {status.openPositions} open ·{" "}
            <span className="tabular-nums">{status.cycleCount}</span> cycles
          </div>
        </div>
      </div>

      {/* Today's PnL hero — the spec's headline number for the dashboard. */}
      <div className="mt-5 border-t-2 border-plum/10 pt-5">
        <div className="t-section-label text-plum-mid">Today&apos;s P&amp;L</div>
        <div className={`mt-1 t-hero ${pnlColor}`}>
          {pnlSign}${status.todaysPnl.toFixed(2)}
        </div>
        <div className="mt-1 t-detail text-plum-mid">
          Balance{" "}
          <span className="tabular-nums font-bold text-plum">
            ${status.currentBalance.toFixed(2)}
          </span>
        </div>
      </div>

      {equity && equity.points.length > 1 && (
        <div className="mt-4">
          <div className="t-section-label text-plum-mid">
            Equity · last {equity.rangeHours}h
          </div>
          <div className="mt-2">
            <EquitySparkline points={equity.points} />
          </div>
        </div>
      )}

      {status.reason && (
        <p className="mt-3 t-detail text-plum-mid">{status.reason}</p>
      )}
    </div>
  );
}

/**
 * BTC regime gate pill: shown next to mode when the bot is running and
 * has computed a recent regime. The bot only takes entries in the
 * direction of the regime (BUY = longs only, SELL = shorts only), so
 * the operator wants this visible at a glance. Returns null for null
 * (bot not running) or UNKNOWN (no cycle has computed it yet).
 */
function RegimePill({ regime }: { regime?: string | null }) {
  if (!regime || regime === "UNKNOWN") return null;
  const config: Record<string, { label: string; bg: string; fg: string }> = {
    BUY: { label: "↑ BUY-only", bg: "bg-pnl-green-soft", fg: "text-pnl-green" },
    SELL: { label: "↓ SELL-only", bg: "bg-pnl-red-soft", fg: "text-pnl-red" },
    UNAVAILABLE: {
      label: "regime offline",
      bg: "bg-cream-deep",
      fg: "text-plum-mid",
    },
  };
  const c = config[regime] ?? {
    label: regime.toLowerCase(),
    bg: "bg-cream-deep",
    fg: "text-plum-mid",
  };
  return (
    <span
      className={`outline-plum rounded-[6px] px-1.5 py-0.5 text-xs font-bold ${c.bg} ${c.fg}`}
      title="Latest BTC regime gate; only entries in this direction are taken."
    >
      {c.label}
    </span>
  );
}

function CredentialsCard({
  credentials,
  mode,
}: {
  credentials: CredentialsStatusResponse | null;
  mode: StatusResponse["mode"];
}) {
  if (!credentials) return null;
  // PAPER mode trades are simulated — no real Bybit calls — so the
  // vault is genuinely optional. Soften the messaging so a PAPER-mode
  // user doesn't feel funnelled toward a flow they don't need.
  const isOptional = mode === "PAPER" && !credentials.loaded;
  return (
    <div
      className={`outline-plum rounded-[18px] p-5 sticker ${
        credentials.loaded
          ? "bg-paper"
          : isOptional
            ? "bg-paper"
            : "bg-cream-deep"
      }`}
    >
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <div className="text-xs uppercase font-bold tracking-wider text-plum-mid">
            Bybit API keys
          </div>
          <div className="mt-1 text-lg font-black text-plum">
            {credentials.loaded
              ? "Loaded in memory"
              : isOptional
                ? "Optional for PAPER mode"
                : "Not configured"}
          </div>
          {credentials.fingerprint && (
            <div className="mt-1 text-xs font-mono text-plum-mid">
              fp {credentials.fingerprint}
            </div>
          )}
          {!credentials.loaded && (
            <p className="mt-2 text-sm text-plum-mid max-w-md">
              {isOptional ? (
                <>
                  PAPER mode simulates trades locally, no real orders are
                  placed. Set up the vault when you&apos;re ready to flip
                  to SHADOW (real prices, paper PnL) or LIVE.
                </>
              ) : (
                <>
                  Your keys are encrypted in your browser before they ever
                  leave the device. Set a passphrase, save a recovery code,
                  push the ciphertext to the bot.
                </>
              )}
            </p>
          )}
        </div>
        <Link
          href="/vault"
          className={
            isOptional
              ? "outline-plum rounded-[14px] bg-paper text-plum px-5 py-2.5 font-bold inline-flex items-center justify-center hover:bg-cream-deep"
              : "sticker outline-plum-thick rounded-[14px] bg-coral text-plum px-5 py-2.5 font-black inline-flex items-center justify-center transition hover:translate-y-[-2px]"
          }
        >
          {credentials.loaded ? "Manage vault" : "Set up vault"}
        </Link>
      </div>
    </div>
  );
}

function KillSwitchBanner() {
  return (
    <div className="outline-plum-thick rounded-[18px] bg-pnl-red-soft p-4 sticker flex items-center gap-3">
      <span
        aria-hidden
        className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-pnl-red text-paper font-black text-lg shrink-0"
      >
        !
      </span>
      <div className="flex-1">
        <p className="font-black text-plum">Kill switch is active.</p>
        <p className="mt-0.5 text-sm text-plum-mid">
          The bot is stopped and refuses to restart until you clear the
          switch in the Controls panel below.
        </p>
      </div>
    </div>
  );
}
