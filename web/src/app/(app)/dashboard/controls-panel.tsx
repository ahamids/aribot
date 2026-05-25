"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  startBot,
  stopBot,
  killBot,
  clearKill,
  type ControlResult,
} from "@/app/actions/controls";
import { ConfirmDialog } from "./confirm-dialog";
import type { StatusResponse } from "@/lib/api/aribot";

type PendingAction = "start" | "stop" | "kill" | "clear" | null;
type ConfirmKind = "start-live" | "start-non-live" | "stop" | "kill" | "clear" | null;

export function ControlsPanel({
  status,
  credentialsLoaded,
}: {
  status: StatusResponse;
  credentialsLoaded: boolean;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [optimistic, setOptimistic] = useState<PendingAction>(null);
  const [confirm, setConfirm] = useState<ConfirmKind>(null);
  const [lastResult, setLastResult] = useState<ControlResult | null>(null);

  const killSwitchActive = status.status === "killed";
  const stopping = status.status === "stopping";
  const running = status.status === "running" || status.status === "starting";

  // Start is only sensible when stopped/stale/crashed AND credentials are
  // loaded AND no kill switch AND no graceful stop in progress. Backend
  // gates this too — we just disable the button so it's not visually
  // misleading.
  const canStart =
    credentialsLoaded && !killSwitchActive && !running && !stopping;
  // Stop is a no-op while already stopping; greying it out avoids
  // misleading the user into thinking a second click escalates the stop.
  // Kill stays available because it IS the escalation path.
  const canStop = running;
  const canKill = running || stopping;

  function runAction(
    kind: PendingAction,
    fn: () => Promise<ControlResult>,
  ) {
    setOptimistic(kind);
    setConfirm(null);
    setLastResult(null);
    startTransition(async () => {
      const result = await fn();
      setLastResult(result);
      // router.refresh() picks up the new /status; clear optimistic state.
      router.refresh();
      // Keep optimistic UI for a moment so the user sees the transition,
      // then drop it. The refreshed status will keep the right pill.
      setTimeout(() => setOptimistic(null), 800);
    });
  }

  function onStartClick() {
    setConfirm(status.mode === "LIVE" ? "start-live" : "start-non-live");
  }

  return (
    <div className="outline-plum rounded-[18px] bg-paper p-5">
      <div className="text-xs uppercase font-bold tracking-wider text-plum-mid">
        Controls
      </div>

      <div className="mt-3 flex flex-wrap gap-3">
        {killSwitchActive ? (
          <button
            type="button"
            onClick={() => setConfirm("clear")}
            disabled={pending}
            className="sticker outline-plum-thick rounded-[12px] bg-yellow text-plum px-5 py-2.5 font-black disabled:opacity-50 disabled:translate-y-0 transition hover:translate-y-[-2px]"
          >
            {optimistic === "clear" ? "Clearing…" : "Clear kill switch"}
          </button>
        ) : (
          <button
            type="button"
            onClick={onStartClick}
            disabled={!canStart || pending}
            title={
              !credentialsLoaded
                ? "Add Bybit keys first"
                : stopping
                  ? "Waiting for the bot to finish exiting…"
                  : running
                    ? "Bot already running"
                    : "Start the bot"
            }
            className="sticker outline-plum-thick rounded-[12px] bg-mint text-plum px-5 py-2.5 font-black disabled:opacity-50 disabled:translate-y-0 transition hover:translate-y-[-2px]"
          >
            {optimistic === "start"
              ? "Starting…"
              : stopping
                ? "Stopping…"
                : "Start"}
          </button>
        )}

        <button
          type="button"
          onClick={() => setConfirm("stop")}
          disabled={!canStop || pending}
          className="outline-plum rounded-[12px] bg-paper text-plum px-5 py-2.5 font-bold disabled:opacity-50 hover:bg-cream-deep"
        >
          {optimistic === "stop" ? "Stopping…" : "Stop"}
        </button>

        <button
          type="button"
          onClick={() => setConfirm("kill")}
          disabled={!canKill || pending}
          className="outline-plum rounded-[12px] bg-pnl-red-soft text-plum px-5 py-2.5 font-bold disabled:opacity-50"
        >
          {optimistic === "kill" ? "Killing…" : "Kill switch"}
        </button>
      </div>

      {lastResult && (
        <ResultLine result={lastResult} onClear={() => setLastResult(null)} />
      )}

      <p className="mt-3 text-xs text-plum-soft">
        Stop is graceful — the bot finishes its current cycle (up to 30s)
        before exiting. Kill is the emergency switch: closes all positions
        ASAP and refuses to restart until you clear it.
      </p>

      {/* Confirmation dialogs */}
      <ConfirmDialog
        open={confirm === "start-live"}
        title="Start in LIVE mode?"
        body={
          <>
            <p className="font-bold text-plum">
              This places real orders against your real Bybit account.
            </p>
            <p className="mt-2">
              Your Bybit keys are loaded, mode is LIVE, kill switch is
              clear. If the bot finds a setup, it will trade with your
              actual capital. Switch to PAPER or SHADOW first if you want
              to dry-run.
            </p>
          </>
        }
        confirmLabel="Start LIVE bot"
        tone="danger"
        busy={pending}
        onConfirm={() => runAction("start", startBot)}
        onCancel={() => setConfirm(null)}
      />

      <ConfirmDialog
        open={confirm === "start-non-live"}
        title={`Start in ${status.mode} mode?`}
        body={
          <p>
            {status.mode === "PAPER"
              ? "Simulated trades only — no real orders, no real PnL."
              : "Real market prices, paper PnL — no real orders are placed."}
          </p>
        }
        confirmLabel={`Start ${status.mode} bot`}
        busy={pending}
        onConfirm={() => runAction("start", startBot)}
        onCancel={() => setConfirm(null)}
      />

      <ConfirmDialog
        open={confirm === "stop"}
        title="Stop the bot?"
        body={
          <p>
            The bot finishes its current cycle (up to 30 seconds) and
            exits gracefully. Open positions stay open — they don&apos;t
            auto-close on stop.
          </p>
        }
        confirmLabel="Stop bot"
        busy={pending}
        onConfirm={() => runAction("stop", stopBot)}
        onCancel={() => setConfirm(null)}
      />

      <ConfirmDialog
        open={confirm === "kill"}
        title="Trip the kill switch?"
        body={
          <>
            <p className="font-bold text-plum">
              Emergency stop. Closes all open positions ASAP.
            </p>
            <p className="mt-2">
              The kill flag stays set until you explicitly clear it, so
              the bot can&apos;t auto-restart. Use this if the bot is
              misbehaving or you need to pull the plug fast.
            </p>
          </>
        }
        confirmLabel="Trip kill switch"
        tone="danger"
        busy={pending}
        onConfirm={() => runAction("kill", killBot)}
        onCancel={() => setConfirm(null)}
      />

      <ConfirmDialog
        open={confirm === "clear"}
        title="Clear the kill switch?"
        body={
          <p>
            The bot will be allowed to start again. Open positions
            (closed by the kill) are not re-opened — that&apos;s the
            strategy&apos;s call on the next cycle.
          </p>
        }
        confirmLabel="Clear kill switch"
        busy={pending}
        onConfirm={() => runAction("clear", clearKill)}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}

function ResultLine({
  result,
  onClear,
}: {
  result: ControlResult;
  onClear: () => void;
}) {
  if (result.ok) {
    return (
      <p className="mt-3 text-sm font-bold text-pnl-green">
        {result.detail}
        {result.pid != null && (
          <span className="ml-2 font-normal text-plum-mid">
            (pid {result.pid})
          </span>
        )}
      </p>
    );
  }
  return (
    <div className="mt-3 outline-plum rounded-[10px] bg-pnl-red-soft px-3 py-2 text-sm">
      <div className="flex items-start justify-between gap-3">
        <p className="font-bold text-plum">
          {result.detail}
          {result.status > 0 && (
            <span className="ml-1 font-normal text-plum-mid">
              ({result.status})
            </span>
          )}
        </p>
        <button
          type="button"
          onClick={onClear}
          className="text-xs font-bold text-plum-mid hover:text-plum"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
