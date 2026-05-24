"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  encryptCredentialsPush,
  generateRecoveryCode,
  generateVaultKeypair,
  formatRecoveryCode,
  normalizeRecoveryCode,
  selfDecrypt,
  selfEncrypt,
  b64decode,
  b64encode,
  type VaultKeypair,
} from "@/lib/crypto/sodium";
import { wrapKey, unwrapKey } from "@/lib/crypto/wrap";
import {
  loadWrappedKey,
  saveWrappedKey,
  clearWrappedKey,
  hasWrappedKey,
} from "@/lib/crypto/storage";
import {
  loadVault,
  saveVault,
  type VaultRow,
} from "@/lib/vault/store";
import { getBotPubkey, pushCredentials } from "@/app/actions/vault";

type Flow = "loading" | "setup" | "unlock" | "recover";

interface BybitCredentials {
  readKey: string;
  readSecret: string;
  tradeKey: string;
  tradeSecret: string;
}

export function VaultWizard({ userId }: { userId: string }) {
  const router = useRouter();
  const [flow, setFlow] = useState<Flow>("loading");
  const [vaultRow, setVaultRow] = useState<VaultRow | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [row, hasLocal] = await Promise.all([
          loadVault(userId),
          hasWrappedKey(userId),
        ]);
        setVaultRow(row);

        if (!row && !hasLocal) {
          setFlow("setup");
        } else if (row && hasLocal) {
          setFlow("unlock");
        } else if (row && !hasLocal) {
          setFlow("recover");
        } else {
          // Orphan IndexedDB entry — clear and start fresh.
          await clearWrappedKey(userId);
          setFlow("setup");
        }
      } catch (e) {
        setError(`Could not check vault state: ${e instanceof Error ? e.message : String(e)}`);
        setFlow("setup");
      }
    })();
  }, [userId]);

  function onDone() {
    router.push("/dashboard");
    router.refresh();
  }

  if (flow === "loading") {
    return <div className="text-plum-mid">Loading vault…</div>;
  }
  if (error) {
    return (
      <div className="outline-plum rounded-[18px] bg-pnl-red-soft p-5">
        <p className="font-bold text-plum">Vault error</p>
        <p className="mt-2 text-sm text-plum-mid">{error}</p>
      </div>
    );
  }

  if (flow === "setup") return <SetupFlow userId={userId} onDone={onDone} />;
  if (flow === "unlock" && vaultRow)
    return (
      <UnlockFlow userId={userId} vaultRow={vaultRow} onDone={onDone} />
    );
  if (flow === "recover" && vaultRow)
    return (
      <RecoverFlow userId={userId} vaultRow={vaultRow} onDone={onDone} />
    );
  return null;
}

// ─────────────────────────────────────────────────────────────────────────
// SETUP FLOW: passphrase → recovery code → Bybit keys → submit
// ─────────────────────────────────────────────────────────────────────────

function SetupFlow({
  userId,
  onDone,
}: {
  userId: string;
  onDone: () => void;
}) {
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [passphrase, setPassphrase] = useState("");
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null);
  const [recoveryAcked, setRecoveryAcked] = useState(false);
  const [bybit, setBybit] = useState<BybitCredentials>({
    readKey: "",
    readSecret: "",
    tradeKey: "",
    tradeSecret: "",
  });
  const [useSameKey, setUseSameKey] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(
    null,
  );

  async function generateRecovery() {
    const code = await generateRecoveryCode();
    setRecoveryCode(code);
    setStep(2);
  }

  async function submit() {
    setSubmitting(true);
    setResult(null);
    try {
      // 1. Generate vault keypair.
      const keypair = await generateVaultKeypair();

      // 2. Wrap SK with passphrase → IndexedDB.
      const passphraseWrap = await wrapKey(keypair.secretKey, passphrase);
      await saveWrappedKey(userId, passphraseWrap);

      // 3. Wrap SK with recovery code → Supabase.
      const recoveryWrap = await wrapKey(
        keypair.secretKey,
        recoveryCode!,
      );

      // 4. Self-encrypt Bybit creds → Supabase.
      const creds: BybitCredentials = useSameKey
        ? {
            readKey: bybit.readKey.trim(),
            readSecret: bybit.readSecret.trim(),
            tradeKey: bybit.readKey.trim(),
            tradeSecret: bybit.readSecret.trim(),
          }
        : {
            readKey: bybit.readKey.trim(),
            readSecret: bybit.readSecret.trim(),
            tradeKey: bybit.tradeKey.trim(),
            tradeSecret: bybit.tradeSecret.trim(),
          };

      const credsJson = new TextEncoder().encode(JSON.stringify(creds));
      const selfEnc = await selfEncrypt(credsJson, keypair);

      // 5. Save the vault row.
      await saveVault(userId, {
        vault_public_key: await b64encode(keypair.publicKey),
        recovery_wrapped_sk: recoveryWrap.ciphertext,
        recovery_salt: recoveryWrap.salt,
        recovery_iv: recoveryWrap.iv,
        credentials_nonce: selfEnc.nonce,
        credentials_ciphertext: selfEnc.ciphertext,
      });

      // 6. Push to backend (fetch bot pubkey, encrypt, POST).
      const pushResult = await pushToBackend(creds);
      setResult(pushResult);

      // SK leaves scope here; the only persistent copies are the
      // passphrase-wrapped one in IndexedDB and the recovery-wrapped
      // one in Supabase.
      if (pushResult.ok) {
        setTimeout(onDone, 1500);
      }
    } catch (e) {
      setResult({
        ok: false,
        detail: `Setup failed: ${e instanceof Error ? e.message : String(e)}`,
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <SetupHeader step={step} />

      {step === 1 && (
        <PassphraseStep
          title="Set a vault passphrase"
          subtitle="This encrypts your Bybit API keys on your device. We can't recover it. Minimum 12 characters."
          onNext={generateRecovery}
          onPassphrase={setPassphrase}
          passphrase={passphrase}
          requireConfirm
        />
      )}

      {step === 2 && recoveryCode && (
        <RecoveryCodeStep
          code={recoveryCode}
          acked={recoveryAcked}
          setAcked={setRecoveryAcked}
          onNext={() => setStep(3)}
        />
      )}

      {step === 3 && (
        <BybitKeysStep
          bybit={bybit}
          setBybit={setBybit}
          useSameKey={useSameKey}
          setUseSameKey={setUseSameKey}
          onNext={() => {
            setStep(4);
            submit();
          }}
        />
      )}

      {step === 4 && (
        <SubmitStep submitting={submitting} result={result} onDone={onDone} />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// UNLOCK FLOW: enter passphrase → unwrap SK → decrypt creds → push
// ─────────────────────────────────────────────────────────────────────────

function UnlockFlow({
  userId,
  vaultRow,
  onDone,
}: {
  userId: string;
  vaultRow: VaultRow;
  onDone: () => void;
}) {
  const [passphrase, setPassphrase] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(
    null,
  );

  async function unlock() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const wrapped = await loadWrappedKey(userId);
      if (!wrapped) throw new Error("Wrapped key missing from IndexedDB");

      const secretKey = await unwrapKey(wrapped, passphrase);
      const keypair: VaultKeypair = {
        publicKey: await b64decode(vaultRow.vault_public_key),
        secretKey,
      };

      const plaintext = await selfDecrypt(
        vaultRow.credentials_ciphertext,
        vaultRow.credentials_nonce,
        keypair,
      );
      const creds: BybitCredentials = JSON.parse(
        new TextDecoder().decode(plaintext),
      );

      const r = await pushToBackend(creds);
      setResult(r);
      if (r.ok) setTimeout(onDone, 1500);
    } catch (e) {
      setError(
        e instanceof Error && e.name === "OperationError"
          ? "Wrong passphrase."
          : `Unlock failed: ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setBusy(false);
    }
  }

  async function startRecovery() {
    if (
      !window.confirm(
        "Use recovery code instead?\n\nYou'll need the 32-character code you saved when creating the vault. After recovery, this device will be re-paired with a new passphrase.",
      )
    )
      return;
    await clearWrappedKey(userId);
    location.reload();
  }

  async function resetVault() {
    if (
      !window.confirm(
        "Reset the vault and start over?\n\nThis ERASES your encrypted Bybit keys from Supabase and IndexedDB. You'll need to re-enter your Bybit API key and secret. Continue?",
      )
    )
      return;
    setBusy(true);
    try {
      const { deleteVault } = await import("@/lib/vault/store");
      await deleteVault(userId);
      await clearWrappedKey(userId);
      location.reload();
    } catch (e) {
      setError(`Reset failed: ${e instanceof Error ? e.message : String(e)}`);
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-3xl font-black text-plum">Unlock your vault</h1>
        <p className="mt-2 text-plum-mid">
          Enter your passphrase to decrypt your Bybit keys and push them to
          the bot.
        </p>
      </div>

      <div className="outline-plum rounded-[18px] bg-paper p-5">
        <label
          htmlFor="passphrase"
          className="text-xs uppercase font-bold tracking-wider text-plum-mid"
        >
          Passphrase
        </label>
        <input
          id="passphrase"
          type="password"
          autoComplete="current-password"
          autoFocus
          value={passphrase}
          onChange={(e) => setPassphrase(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && passphrase.length >= 12 && !busy) unlock();
          }}
          className="mt-2 w-full outline-plum rounded-[12px] bg-cream text-plum px-4 py-3 placeholder:text-plum-soft focus:outline-none focus:ring-2 focus:ring-coral"
        />

        {error && (
          <p className="mt-3 text-sm text-pnl-red font-bold">{error}</p>
        )}
        {result && (
          <p
            className={`mt-3 text-sm font-bold ${result.ok ? "text-pnl-green" : "text-pnl-red"}`}
          >
            {result.detail}
          </p>
        )}

        <div className="mt-4 flex flex-wrap gap-3">
          <button
            onClick={unlock}
            disabled={busy || passphrase.length < 12}
            className="sticker outline-plum-thick rounded-[14px] bg-coral text-plum px-5 py-2.5 font-black disabled:opacity-50 disabled:translate-y-0 transition hover:translate-y-[-2px]"
          >
            {busy ? "Unlocking…" : "Unlock & push"}
          </button>
          <button
            onClick={startRecovery}
            disabled={busy}
            className="outline-plum rounded-[14px] bg-paper text-plum px-5 py-2.5 font-bold hover:bg-cream-deep"
          >
            Use recovery code
          </button>
          <button
            onClick={resetVault}
            disabled={busy}
            className="outline-plum rounded-[14px] bg-pnl-red-soft text-plum px-5 py-2.5 font-bold hover:bg-pnl-red-soft"
          >
            Reset vault
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// RECOVERY FLOW: enter recovery code → set new passphrase → push
// ─────────────────────────────────────────────────────────────────────────

function RecoverFlow({
  userId,
  vaultRow,
  onDone,
}: {
  userId: string;
  vaultRow: VaultRow;
  onDone: () => void;
}) {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [code, setCode] = useState("");
  const [keypair, setKeypair] = useState<VaultKeypair | null>(null);
  const [creds, setCreds] = useState<BybitCredentials | null>(null);
  const [passphrase, setPassphrase] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(
    null,
  );

  async function recover() {
    setBusy(true);
    setError(null);
    try {
      const normalized = normalizeRecoveryCode(code);
      if (normalized.length !== 32) {
        throw new Error("Recovery code must be 32 hex characters.");
      }
      const secretKey = await unwrapKey(
        {
          ciphertext: vaultRow.recovery_wrapped_sk,
          iv: vaultRow.recovery_iv,
          salt: vaultRow.recovery_salt,
          iterations: 600_000,
        },
        normalized,
      );
      const kp: VaultKeypair = {
        publicKey: await b64decode(vaultRow.vault_public_key),
        secretKey,
      };
      const plaintext = await selfDecrypt(
        vaultRow.credentials_ciphertext,
        vaultRow.credentials_nonce,
        kp,
      );
      const decoded: BybitCredentials = JSON.parse(
        new TextDecoder().decode(plaintext),
      );
      setKeypair(kp);
      setCreds(decoded);
      setStep(2);
    } catch (e) {
      setError(
        e instanceof Error && e.name === "OperationError"
          ? "Wrong recovery code."
          : `Recovery failed: ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setBusy(false);
    }
  }

  async function setNewPassphraseAndPush() {
    if (!keypair || !creds) return;
    setBusy(true);
    setError(null);
    try {
      const wrap = await wrapKey(keypair.secretKey, passphrase);
      await saveWrappedKey(userId, wrap);
      const r = await pushToBackend(creds);
      setResult(r);
      if (r.ok) setTimeout(onDone, 1500);
    } catch (e) {
      setError(`Re-pair failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-3xl font-black text-plum">Recover vault</h1>
        <p className="mt-2 text-plum-mid">
          Use your 32-character recovery code to unlock the vault on this
          device. After recovery, set a new passphrase for future sign-ins.
        </p>
      </div>

      {step === 1 && (
        <div className="outline-plum rounded-[18px] bg-paper p-5">
          <label
            htmlFor="code"
            className="text-xs uppercase font-bold tracking-wider text-plum-mid"
          >
            Recovery code
          </label>
          <input
            id="code"
            type="text"
            autoFocus
            spellCheck={false}
            autoComplete="off"
            placeholder="abc12-3def4-…"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !busy) recover();
            }}
            className="mt-2 w-full outline-plum rounded-[12px] bg-cream text-plum px-4 py-3 font-mono placeholder:text-plum-soft focus:outline-none focus:ring-2 focus:ring-coral"
          />
          <p className="mt-2 text-xs text-plum-soft">
            Dashes and spaces are ignored. We just need the 32 hex characters.
          </p>
          {error && (
            <p className="mt-3 text-sm text-pnl-red font-bold">{error}</p>
          )}
          <button
            onClick={recover}
            disabled={busy}
            className="mt-4 sticker outline-plum-thick rounded-[14px] bg-coral text-plum px-5 py-2.5 font-black disabled:opacity-50 disabled:translate-y-0 transition hover:translate-y-[-2px]"
          >
            {busy ? "Verifying…" : "Recover"}
          </button>
        </div>
      )}

      {step === 2 && (
        <div className="outline-plum rounded-[18px] bg-paper p-5">
          <p className="font-black text-plum">
            Recovery code accepted.
          </p>
          <p className="mt-2 text-sm text-plum-mid">
            Set a new passphrase for this device. It replaces the one you
            forgot.
          </p>
          <label
            htmlFor="new-passphrase"
            className="mt-4 block text-xs uppercase font-bold tracking-wider text-plum-mid"
          >
            New passphrase (12+ chars)
          </label>
          <input
            id="new-passphrase"
            type="password"
            autoFocus
            autoComplete="new-password"
            value={passphrase}
            onChange={(e) => setPassphrase(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && passphrase.length >= 12 && !busy)
                setNewPassphraseAndPush();
            }}
            className="mt-2 w-full outline-plum rounded-[12px] bg-cream text-plum px-4 py-3 placeholder:text-plum-soft focus:outline-none focus:ring-2 focus:ring-coral"
          />
          {error && (
            <p className="mt-3 text-sm text-pnl-red font-bold">{error}</p>
          )}
          {result && (
            <p
              className={`mt-3 text-sm font-bold ${result.ok ? "text-pnl-green" : "text-pnl-red"}`}
            >
              {result.detail}
            </p>
          )}
          <button
            onClick={setNewPassphraseAndPush}
            disabled={busy || passphrase.length < 12}
            className="mt-4 sticker outline-plum-thick rounded-[14px] bg-coral text-plum px-5 py-2.5 font-black disabled:opacity-50 disabled:translate-y-0 transition hover:translate-y-[-2px]"
          >
            {busy ? "Pushing…" : "Set passphrase & push"}
          </button>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Shared step components
// ─────────────────────────────────────────────────────────────────────────

function SetupHeader({ step }: { step: 1 | 2 | 3 | 4 }) {
  const steps = ["Passphrase", "Recovery code", "Bybit keys", "Push"];
  return (
    <div>
      <h1 className="text-3xl font-black text-plum">Set up your vault</h1>
      <div className="mt-4 flex gap-2">
        {steps.map((label, i) => {
          const n = (i + 1) as 1 | 2 | 3 | 4;
          const active = n === step;
          const done = n < step;
          return (
            <div
              key={label}
              className={`outline-plum rounded-[10px] px-3 py-1.5 text-xs font-bold ${
                active
                  ? "sticker bg-coral text-plum"
                  : done
                    ? "bg-mint text-plum"
                    : "bg-paper text-plum-soft"
              }`}
            >
              {n}. {label}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PassphraseStep({
  title,
  subtitle,
  passphrase,
  onPassphrase,
  onNext,
  requireConfirm,
}: {
  title: string;
  subtitle: string;
  passphrase: string;
  onPassphrase: (s: string) => void;
  onNext: () => void;
  requireConfirm?: boolean;
}) {
  const [confirm, setConfirm] = useState("");
  const [showAck, setShowAck] = useState(false);
  const mismatch = requireConfirm && confirm.length > 0 && confirm !== passphrase;
  const tooShort = passphrase.length > 0 && passphrase.length < 12;
  const ready =
    passphrase.length >= 12 &&
    (!requireConfirm || passphrase === confirm) &&
    showAck;

  return (
    <div className="outline-plum rounded-[18px] bg-paper p-5">
      <h2 className="text-xl font-black text-plum">{title}</h2>
      <p className="mt-2 text-sm text-plum-mid">{subtitle}</p>

      <div className="mt-4 flex flex-col gap-3">
        <PasswordField
          id="vault-pass"
          label="Passphrase"
          value={passphrase}
          onChange={onPassphrase}
          autoComplete="new-password"
        />
        {tooShort && (
          <p className="-mt-1 text-sm text-pnl-red font-bold">
            At least 12 characters.
          </p>
        )}
        {requireConfirm && (
          <>
            <PasswordField
              id="vault-pass-confirm"
              label="Confirm"
              value={confirm}
              onChange={setConfirm}
              autoComplete="new-password"
            />
            {mismatch && (
              <p className="-mt-1 text-sm text-pnl-red font-bold">
                Passphrases don&apos;t match.
              </p>
            )}
          </>
        )}
      </div>

      <label className="mt-4 flex items-start gap-3 text-sm text-plum-mid cursor-pointer">
        <input
          type="checkbox"
          checked={showAck}
          onChange={(e) => setShowAck(e.target.checked)}
          className="mt-1 h-4 w-4 accent-coral"
        />
        <span>
          I understand that if I forget this passphrase AND lose the recovery
          code on the next step, my Bybit keys are unrecoverable.
        </span>
      </label>

      <button
        onClick={onNext}
        disabled={!ready}
        className="mt-5 sticker outline-plum-thick rounded-[14px] bg-coral text-plum px-5 py-2.5 font-black disabled:opacity-50 disabled:translate-y-0 transition hover:translate-y-[-2px]"
      >
        Continue
      </button>
    </div>
  );
}

function RecoveryCodeStep({
  code,
  acked,
  setAcked,
  onNext,
}: {
  code: string;
  acked: boolean;
  setAcked: (b: boolean) => void;
  onNext: () => void;
}) {
  const [copied, setCopied] = useState(false);
  function copy() {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  }
  return (
    <div className="outline-plum rounded-[18px] bg-paper p-5">
      <h2 className="text-xl font-black text-plum">
        Save your recovery code
      </h2>
      <p className="mt-2 text-sm text-plum-mid">
        This is shown <strong>once</strong>. Without it (and without your
        passphrase), you cannot recover your Bybit keys. Store it in a
        password manager.
      </p>

      <div className="mt-4 outline-plum rounded-[14px] bg-cream-deep p-4">
        <code className="block break-all font-mono text-lg font-bold text-plum tracking-wider">
          {formatRecoveryCode(code)}
        </code>
        <button
          onClick={copy}
          className="mt-3 outline-plum rounded-[10px] bg-paper text-plum px-3 py-1.5 text-sm font-bold hover:bg-cream"
        >
          {copied ? "Copied ✓" : "Copy"}
        </button>
      </div>

      <label className="mt-4 flex items-start gap-3 text-sm text-plum-mid cursor-pointer">
        <input
          type="checkbox"
          checked={acked}
          onChange={(e) => setAcked(e.target.checked)}
          className="mt-1 h-4 w-4 accent-coral"
        />
        <span>
          I&apos;ve saved this code somewhere safe (password manager, written
          down, etc.).
        </span>
      </label>

      <button
        onClick={onNext}
        disabled={!acked}
        className="mt-5 sticker outline-plum-thick rounded-[14px] bg-coral text-plum px-5 py-2.5 font-black disabled:opacity-50 disabled:translate-y-0 transition hover:translate-y-[-2px]"
      >
        Continue
      </button>
    </div>
  );
}

function BybitKeysStep({
  bybit,
  setBybit,
  useSameKey,
  setUseSameKey,
  onNext,
}: {
  bybit: BybitCredentials;
  setBybit: (b: BybitCredentials) => void;
  useSameKey: boolean;
  setUseSameKey: (b: boolean) => void;
  onNext: () => void;
}) {
  const ready =
    bybit.readKey.trim() &&
    bybit.readSecret.trim() &&
    (useSameKey ||
      (bybit.tradeKey.trim() &&
        bybit.tradeSecret.trim() &&
        bybit.tradeKey.trim() !== bybit.readKey.trim()));

  return (
    <div className="outline-plum rounded-[18px] bg-paper p-5">
      <h2 className="text-xl font-black text-plum">Your Bybit API keys</h2>
      <p className="mt-2 text-sm text-plum-mid">
        Create at{" "}
        <a
          href="https://testnet.bybit.com/app/user/api-management"
          target="_blank"
          rel="noreferrer"
          className="font-bold text-plum underline"
        >
          testnet.bybit.com → API
        </a>{" "}
        (or{" "}
        <a
          href="https://www.bybit.com/app/user/api-management"
          target="_blank"
          rel="noreferrer"
          className="font-bold text-plum underline"
        >
          mainnet
        </a>
        ). Permissions needed: <strong>Read</strong> +{" "}
        <strong>Derivatives Trade</strong>.
      </p>

      <div className="mt-4 flex flex-col gap-3">
        <TextField
          id="readKey"
          label={useSameKey ? "API Key" : "Read API Key"}
          value={bybit.readKey}
          onChange={(v) => setBybit({ ...bybit, readKey: v })}
        />
        <TextField
          id="readSecret"
          label={useSameKey ? "API Secret" : "Read API Secret"}
          value={bybit.readSecret}
          onChange={(v) => setBybit({ ...bybit, readSecret: v })}
          secret
        />
      </div>

      <label className="mt-4 flex items-start gap-3 text-sm text-plum-mid cursor-pointer">
        <input
          type="checkbox"
          checked={!useSameKey}
          onChange={(e) => setUseSameKey(!e.target.checked)}
          className="mt-1 h-4 w-4 accent-coral"
        />
        <span>
          <strong>Advanced (recommended):</strong> use separate Bybit API
          keys for read vs. trade. Limits blast radius if either key leaks.
        </span>
      </label>

      {!useSameKey && (
        <div className="mt-4 flex flex-col gap-3">
          <TextField
            id="tradeKey"
            label="Trade API Key"
            value={bybit.tradeKey}
            onChange={(v) => setBybit({ ...bybit, tradeKey: v })}
          />
          <TextField
            id="tradeSecret"
            label="Trade API Secret"
            value={bybit.tradeSecret}
            onChange={(v) => setBybit({ ...bybit, tradeSecret: v })}
            secret
          />
          {bybit.tradeKey.trim() &&
            bybit.readKey.trim() === bybit.tradeKey.trim() && (
              <p className="text-sm text-pnl-red font-bold">
                Trade key must be different from the read key.
              </p>
            )}
        </div>
      )}

      <button
        onClick={onNext}
        disabled={!ready}
        className="mt-5 sticker outline-plum-thick rounded-[14px] bg-coral text-plum px-5 py-2.5 font-black disabled:opacity-50 disabled:translate-y-0 transition hover:translate-y-[-2px]"
      >
        Encrypt &amp; push
      </button>
    </div>
  );
}

function SubmitStep({
  submitting,
  result,
  onDone,
}: {
  submitting: boolean;
  result: { ok: boolean; detail: string } | null;
  onDone: () => void;
}) {
  return (
    <div
      className={`outline-plum rounded-[18px] p-5 sticker ${
        result?.ok ? "bg-mint" : result ? "bg-pnl-red-soft" : "bg-paper"
      }`}
    >
      <h2 className="text-xl font-black text-plum">
        {submitting
          ? "Encrypting + pushing…"
          : result?.ok
            ? "Vault ready"
            : result
              ? "Push failed"
              : "Ready"}
      </h2>
      {submitting && (
        <p className="mt-2 text-sm text-plum-mid">
          Wrapping your vault keypair, self-encrypting credentials, pushing
          to the bot. This takes a moment because of PBKDF2.
        </p>
      )}
      {result && (
        <p className="mt-2 text-sm font-bold text-plum">{result.detail}</p>
      )}
      {result?.ok && (
        <button
          onClick={onDone}
          className="mt-4 outline-plum rounded-[14px] bg-paper text-plum px-5 py-2.5 font-bold hover:bg-cream-deep"
        >
          Back to dashboard
        </button>
      )}
    </div>
  );
}

function PasswordField({
  id,
  label,
  value,
  onChange,
  autoComplete,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete?: string;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="text-xs uppercase font-bold tracking-wider text-plum-mid"
      >
        {label}
      </label>
      <input
        id={id}
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        className="mt-2 w-full outline-plum rounded-[12px] bg-cream text-plum px-4 py-3 placeholder:text-plum-soft focus:outline-none focus:ring-2 focus:ring-coral"
      />
    </div>
  );
}

function TextField({
  id,
  label,
  value,
  onChange,
  secret,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  secret?: boolean;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="text-xs uppercase font-bold tracking-wider text-plum-mid"
      >
        {label}
      </label>
      <input
        id={id}
        type={secret ? "password" : "text"}
        autoComplete="off"
        spellCheck={false}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-2 w-full outline-plum rounded-[12px] bg-cream text-plum px-4 py-3 font-mono placeholder:text-plum-soft focus:outline-none focus:ring-2 focus:ring-coral"
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Backend push helper (shared across setup/unlock/recover)
// ─────────────────────────────────────────────────────────────────────────

async function pushToBackend(
  creds: BybitCredentials,
): Promise<{ ok: boolean; detail: string }> {
  const pubkey = await getBotPubkey();
  if (!pubkey) {
    return {
      ok: false,
      detail: "Could not fetch bot pubkey from api.aribot.app.",
    };
  }
  const botPubBytes = await b64decode(pubkey.publicKey);
  const plaintext = new TextEncoder().encode(JSON.stringify(creds));
  const payload = await encryptCredentialsPush(plaintext, botPubBytes);
  const ack = await pushCredentials(payload);
  if (ack.ok) {
    return {
      ok: true,
      detail: `Pushed to bot (fingerprint ${ack.fingerprint}).`,
    };
  }
  return { ok: false, detail: `Backend rejected push: ${ack.detail}` };
}
