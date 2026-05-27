"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { setBybitTestnet } from "@/app/actions/bot";
import { deleteCredentials } from "@/app/actions/vault";
import { createClient } from "@/lib/supabase/client";
import { clearWrappedKey } from "@/lib/crypto/storage";
import { deleteVault } from "@/lib/vault/store";
import { ConfirmDialog } from "../dashboard/confirm-dialog";
import { Toggle } from "@/components/toggle";

interface SettingsClientProps {
  userId: string;
  email: string;
  initialTestnet: boolean | null;
  initialMode: string | null;
  botRunning: boolean;
}

type DialogKind =
  | "testnet-to-mainnet"
  | "testnet-to-testnet"
  | "delete-vault"
  | "sign-out-everywhere"
  | null;

export function SettingsClient({
  userId,
  email,
  initialTestnet,
  initialMode,
  botRunning,
}: SettingsClientProps) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [dialog, setDialog] = useState<DialogKind>(null);
  const [feedback, setFeedback] = useState<{
    kind: "ok" | "err";
    text: string;
  } | null>(null);

  function runTestnetFlip(target: boolean) {
    setDialog(null);
    setFeedback(null);
    startTransition(async () => {
      const form = new FormData();
      form.set("testnet", target ? "true" : "false");
      const result = await setBybitTestnet(undefined, form);
      setFeedback(
        result?.ok
          ? { kind: "ok", text: result.message }
          : { kind: "err", text: result?.message ?? "Unknown error." },
      );
      router.refresh();
    });
  }

  async function runDeleteVault() {
    setDialog(null);
    setFeedback(null);
    startTransition(async () => {
      try {
        await deleteVault(userId);
        await clearWrappedKey(userId);
        // Tell the backend to drop the credentials it has in RAM. Non-
        // fatal if it fails — Supabase + IndexedDB are wiped, which is
        // the user-visible thing. Backend drops its RAM copy on next
        // restart regardless.
        await deleteCredentials().catch(() => null);
        setFeedback({
          kind: "ok",
          text: "Vault deleted. Set it up again to reconnect Bybit keys.",
        });
        router.refresh();
      } catch (e) {
        setFeedback({
          kind: "err",
          text: `Could not delete vault: ${e instanceof Error ? e.message : String(e)}`,
        });
      }
    });
  }

  async function runSignOutEverywhere() {
    setDialog(null);
    setFeedback(null);
    startTransition(async () => {
      try {
        const supabase = createClient();
        // scope: 'global' invalidates ALL sessions for this user across
        // every device / browser. Local cookie is also cleared.
        const { error } = await supabase.auth.signOut({ scope: "global" });
        if (error) {
          setFeedback({
            kind: "err",
            text: `Could not sign out everywhere: ${error.message}`,
          });
          return;
        }
        // After global sign-out the user has no session here either —
        // route to landing.
        router.push("/");
        router.refresh();
      } catch (e) {
        setFeedback({
          kind: "err",
          text: `Could not sign out: ${e instanceof Error ? e.message : String(e)}`,
        });
      }
    });
  }

  return (
    <>
      {/* Account */}
      <Section title="Account">
        <Row label="Signed in as" value={email} />
        <Row
          label="User ID"
          value={
            <code className="text-xs font-mono text-plum-mid">{userId}</code>
          }
        />
      </Section>

      {/* Bybit environment */}
      <Section title="Bybit environment">
        <p className="text-sm text-plum-mid">
          Testnet uses fake money against Bybit&apos;s simulated exchange
          (great for dry runs). Mainnet places real orders against your
          real Bybit account. Switching environments requires the bot to
          be stopped — and almost always requires a fresh API key from
          the other environment, since testnet/mainnet keys aren&apos;t
          interchangeable.
        </p>

        <div className="mt-4 outline-plum rounded-[14px] bg-paper p-4">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <div className="text-xs uppercase font-bold tracking-wider text-plum-mid">
                Current
              </div>
              <div className="mt-1 text-lg font-black text-plum">
                {initialTestnet == null
                  ? "(unknown — backend unreachable)"
                  : initialTestnet
                    ? "TESTNET"
                    : "MAINNET"}
              </div>
            </div>
            <div className="flex gap-2">
              <ToggleButton
                label="Use testnet"
                selected={initialTestnet === true}
                disabled={initialTestnet == null || botRunning || pending}
                onClick={() => setDialog("testnet-to-testnet")}
              />
              <ToggleButton
                label="Use mainnet"
                selected={initialTestnet === false}
                disabled={initialTestnet == null || botRunning || pending}
                onClick={() => setDialog("testnet-to-mainnet")}
                danger
              />
            </div>
          </div>
          {botRunning && (
            <p className="mt-3 text-sm text-pnl-red font-bold">
              Bot is currently running. Stop it before changing the
              environment.
            </p>
          )}
          {initialMode && (
            <p className="mt-2 text-xs text-plum-soft">
              Current mode: <span className="font-bold">{initialMode}</span> ·
              changing here doesn&apos;t affect mode.
            </p>
          )}
        </div>
      </Section>

      {/* Notifications — stubbed UI surface per design spec
          (design-pkg/screens-main.jsx:194-199). The backend doesn't have
          subscription/dispatch endpoints yet, so toggling these only
          persists locally in IndexedDB-flavored cookies; flip them when
          you're ready to wire to a real notifications service. */}
      <Section title="Notifications">
        <p className="t-detail text-plum-mid">
          What you&apos;d like Aribot to ping you about. Hooks aren&apos;t
          live yet — toggling here saves your preference so it&apos;s ready
          when the backend ships.
        </p>
        <div className="mt-3 flex flex-col divide-y divide-plum/10">
          <NotificationToggle
            id="notif-fill"
            label="Trade fills"
            body="A short note when the bot opens or closes a position."
            storageKey="aribot.notify.fills"
          />
          <NotificationToggle
            id="notif-error"
            label="Errors"
            body="If the bot crashes, loses Bybit, or trips the kill switch."
            storageKey="aribot.notify.errors"
            defaultOn
          />
          <NotificationToggle
            id="notif-daily"
            label="Daily summary"
            body="Once-a-day digest of yesterday's trades and PnL."
            storageKey="aribot.notify.daily"
          />
        </div>
      </Section>

      {/* Danger zone */}
      <Section title="Danger zone">
        <p className="text-sm text-plum-mid">
          Actions that can&apos;t be undone. Most users never need these.
        </p>

        <div className="mt-4 flex flex-col gap-3">
          <DangerRow
            title="Delete vault"
            body="Wipes the encrypted Bybit keys from Supabase, this browser's IndexedDB, and the backend's RAM. You'll need to re-create the vault and re-enter your Bybit keys to use the bot again."
            buttonLabel="Delete vault"
            disabled={pending}
            onClick={() => setDialog("delete-vault")}
          />
          <DangerRow
            title="Sign out everywhere"
            body="Invalidates all sessions for your account on every device. Useful if a device was lost or compromised."
            buttonLabel="Sign out everywhere"
            disabled={pending}
            onClick={() => setDialog("sign-out-everywhere")}
          />
        </div>
      </Section>

      {feedback && (
        <div
          className={`outline-plum rounded-[12px] p-3 t-detail ${
            feedback.kind === "ok"
              ? "bg-mint text-plum"
              : "bg-cream-deep text-plum"
          }`}
        >
          <span className="font-bold">
            {feedback.kind === "ok" ? "✓ " : "⚠ "}
          </span>
          {feedback.text}
        </div>
      )}

      <ConfirmDialog
        open={dialog === "testnet-to-mainnet"}
        title="Switch Bybit to MAINNET?"
        body={
          <>
            <p className="font-bold text-plum">
              Mainnet means real orders against real money.
            </p>
            <p className="mt-2">
              Your currently-loaded Bybit keys are testnet keys. After
              this switch, the bot will reject them and ask you to push
              fresh mainnet keys via the vault. You&apos;ll also want to
              double-check that mode is set to PAPER or SHADOW before
              starting the bot.
            </p>
          </>
        }
        confirmLabel="Switch to mainnet"
        tone="danger"
        busy={pending}
        onConfirm={() => runTestnetFlip(false)}
        onCancel={() => setDialog(null)}
      />

      <ConfirmDialog
        open={dialog === "testnet-to-testnet"}
        title="Switch Bybit to TESTNET?"
        body={
          <p>
            Testnet is the safe playground — no real money. Your
            currently-loaded mainnet keys will stop working; you&apos;ll
            push fresh testnet keys via the vault to keep going.
          </p>
        }
        confirmLabel="Switch to testnet"
        busy={pending}
        onConfirm={() => runTestnetFlip(true)}
        onCancel={() => setDialog(null)}
      />

      <ConfirmDialog
        open={dialog === "delete-vault"}
        title="Delete the vault?"
        body={
          <>
            <p className="font-bold text-plum">
              Your encrypted Bybit keys will be wiped from Supabase,
              this browser, and the backend&apos;s RAM.
            </p>
            <p className="mt-2">
              You&apos;ll need to set up the vault again and re-paste
              your Bybit API key + secret. This does NOT affect your
              Aribot account or trade history.
            </p>
          </>
        }
        confirmLabel="Delete vault"
        tone="danger"
        busy={pending}
        onConfirm={runDeleteVault}
        onCancel={() => setDialog(null)}
      />

      <ConfirmDialog
        open={dialog === "sign-out-everywhere"}
        title="Sign out everywhere?"
        body={
          <p>
            Signs you out on this device AND invalidates every other
            session for your account. Anyone with an active session
            (yourself on another device included) will be kicked back
            to the sign-in page on their next request.
          </p>
        }
        confirmLabel="Sign out everywhere"
        tone="danger"
        busy={pending}
        onConfirm={runSignOutEverywhere}
        onCancel={() => setDialog(null)}
      />

      <AboutFooter />
    </>
  );
}

/**
 * Single notification preference. Persists to localStorage on flip;
 * SSR-safe (defaults to the off / `defaultOn` value during the first
 * render, hydrates from storage after mount). When the backend
 * ships subscription endpoints, this component is the one place to
 * wire the POST.
 */
function NotificationToggle({
  id,
  label,
  body,
  storageKey,
  defaultOn = false,
}: {
  id: string;
  label: string;
  body: string;
  storageKey: string;
  defaultOn?: boolean;
}) {
  const [on, setOn] = useState(defaultOn);
  const [hydrated, setHydrated] = useState(false);

  // Read from localStorage once after mount so the initial server-
  // rendered markup matches the client (defaults), then hydrate to
  // the persisted value without a flicker beyond the "no-fade".
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw === "1") setOn(true);
      else if (raw === "0") setOn(false);
    } catch {
      // localStorage might be unavailable (private mode, SES). Keep default.
    }
    setHydrated(true);
  }, [storageKey]);

  function flip(next: boolean) {
    setOn(next);
    try {
      window.localStorage.setItem(storageKey, next ? "1" : "0");
    } catch {
      // Silently ignore — the toggle still works in the current session.
    }
  }

  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="min-w-0">
        <label
          htmlFor={id}
          className="t-row-symbol text-plum block cursor-pointer"
        >
          {label}
        </label>
        <p className="mt-1 t-detail text-plum-mid">{body}</p>
      </div>
      <Toggle
        checked={on}
        onChange={flip}
        ariaLabel={label}
        disabled={!hydrated}
      />
    </div>
  );
}

/**
 * Footer About block per design-pkg/screens-main.jsx:201-203. Lives
 * outside the <Section> stack so it reads as a "this is the end"
 * marker rather than another config row. The build ID is injected by
 * `npm run build` (scripts/write-build-id.mjs) — falls back to "dev"
 * locally so the layout doesn't shift in `next dev`.
 */
function AboutFooter() {
  const buildId = process.env.NEXT_PUBLIC_BUILD_ID ?? "dev";
  return (
    <div className="mt-2 pt-4 border-t-2 border-plum/10 text-center">
      <p className="t-section-label text-plum-mid">aribot</p>
      <p className="mt-1 t-detail text-plum-mid">
        web · build <span className="font-mono">{buildId}</span>
      </p>
      <p className="mt-2 t-detail text-plum-soft">
        Bring your own keys · Encrypted on your device
      </p>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="outline-plum rounded-[18px] bg-paper p-5 sticker">
      <h2 className="t-section-h2 text-plum">{title}</h2>
      <div className="mt-3">{children}</div>
    </div>
  );
}

function Row({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5 text-sm">
      <span className="text-plum-mid">{label}</span>
      <span className="text-plum font-bold truncate max-w-[60%] text-right">
        {value}
      </span>
    </div>
  );
}

function ToggleButton({
  label,
  selected,
  disabled,
  onClick,
  danger,
}: {
  label: string;
  selected: boolean;
  disabled: boolean;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || selected}
      className={`outline-plum rounded-[10px] px-3 py-2 text-sm font-bold transition disabled:opacity-50 disabled:cursor-default ${
        selected
          ? `sticker ${danger ? "bg-yellow" : "bg-mint"} text-plum cursor-default`
          : "bg-cream text-plum hover:bg-cream-deep"
      }`}
    >
      {label}
      {selected && (
        <span className="ml-1 text-xs font-bold uppercase tracking-wider text-plum-mid">
          ·current
        </span>
      )}
    </button>
  );
}

function DangerRow({
  title,
  body,
  buttonLabel,
  disabled,
  onClick,
}: {
  title: string;
  body: string;
  buttonLabel: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <div className="outline-plum rounded-[12px] bg-cream-deep p-3 flex items-start justify-between gap-3 flex-wrap">
      <div className="flex-1 min-w-[200px]">
        <p className="font-black text-plum">{title}</p>
        <p className="mt-1 text-sm text-plum-mid">{body}</p>
      </div>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className="outline-plum rounded-[10px] bg-cream text-plum px-4 py-2 text-sm font-bold hover:bg-cream-deep disabled:opacity-50 inline-flex items-center gap-1.5"
      >
        <span aria-hidden>⚠</span>
        {buttonLabel}
      </button>
    </div>
  );
}
