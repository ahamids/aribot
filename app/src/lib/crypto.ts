// Cryptographic primitives for the iOS → bot credential vault.
//
// Flow:
//   1. iOS fetches the bot's long-lived X25519 public key from GET /pubkey.
//      That pubkey is TOFU-pinned in SecureStore on first connect, alongside
//      the TLS cert fingerprint.
//   2. For each push, iOS generates a FRESH ephemeral X25519 keypair (no
//      long-term storage needed), seals the credentials with
//      nacl.box(plaintext, nonce, BOT_PK, EPHEMERAL_iOS_SK), and POSTs
//      {ciphertext, nonce, senderPublicKey: EPHEMERAL_iOS_PK, timestampIso,
//       counter} to POST /credentials.
//   3. The bot's CredentialStore enforces replay protection per ephemeral
//      sender pubkey (counter must increase; ±60s timestamp skew accepted).
//
// Why ephemeral senders: a fresh keypair per push means the iOS app holds
// no long-term private key for this flow. Combined with TLS pinning and
// the bot-pubkey TOFU pin, this gets us secrecy + integrity without
// requiring users to manage a long-term signing identity in v1.
//
// What stays from the prior Supabase-backed flow:
//   - SecureStore is still used for: the pinned bot pubkey fingerprint,
//     the pinned TLS cert fingerprint, and the per-bot monotonic counter.
//   - wipeKeypair() is kept as a migration helper to clear the legacy
//     long-term keypair from a prior install of the app.

import 'react-native-get-random-values';
import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import nacl from 'tweetnacl';
import naclUtil from 'tweetnacl-util';

const LEGACY_SK_KEY = 'aribot.vault.secretKey';
const PINNED_BOT_PUBKEY_KEY = 'aribot.bot.pubkey';
const PINNED_BOT_FINGERPRINT_KEY = 'aribot.bot.pubkeyFingerprint';
const PINNED_TLS_FINGERPRINT_KEY = 'aribot.bot.tlsCertSha256';
const COUNTER_PREFIX = 'aribot.bot.counter.'; // suffixed by bot fingerprint

export type Sealed = {
  senderPublicKey: string;
  nonce: string;
  ciphertext: string;
};

function toB64(u: Uint8Array): string {
  return naclUtil.encodeBase64(u);
}

function fromB64(s: string): Uint8Array {
  return naclUtil.decodeBase64(s);
}

// ─────────────────────────────────────────────────────────────────────────────
// SecureStore helpers (web fallback uses localStorage for dev only — the
// production iOS target hits Keychain via expo-secure-store).
// ─────────────────────────────────────────────────────────────────────────────

let warnedAboutWeb = false;

function warnWebOnce(): void {
  if (warnedAboutWeb) return;
  warnedAboutWeb = true;
  // eslint-disable-next-line no-console
  console.warn(
    '[aribot/crypto] Running under web — pinning state is stored in localStorage. ' +
      'The trust-on-screen copy applies to native iOS only.',
  );
}

async function storeGet(key: string): Promise<string | null> {
  if (Platform.OS === 'web') {
    warnWebOnce();
    try {
      return globalThis.localStorage?.getItem(key) ?? null;
    } catch {
      return null;
    }
  }
  return SecureStore.getItemAsync(key);
}

async function storeSet(key: string, value: string): Promise<void> {
  if (Platform.OS === 'web') {
    warnWebOnce();
    try {
      globalThis.localStorage?.setItem(key, value);
    } catch {
      throw new Error('Browser refused to store pinning state.');
    }
    return;
  }
  await SecureStore.setItemAsync(key, value, {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
}

async function storeDelete(key: string): Promise<void> {
  if (Platform.OS === 'web') {
    try {
      globalThis.localStorage?.removeItem(key);
    } catch {
      // ignore
    }
    return;
  }
  await SecureStore.deleteItemAsync(key);
}

// ─────────────────────────────────────────────────────────────────────────────
// Ephemeral sealed-box to a recipient pubkey
// ─────────────────────────────────────────────────────────────────────────────

export function sealForRecipient(recipientPubKeyB64: string, plaintext: string): Sealed {
  const recipientPk = fromB64(recipientPubKeyB64);
  if (recipientPk.length !== nacl.box.publicKeyLength) {
    throw new Error(
      `recipient pubkey has wrong length ${recipientPk.length}, expected ${nacl.box.publicKeyLength}`,
    );
  }
  const ephemeral = nacl.box.keyPair();
  const nonce = nacl.randomBytes(nacl.box.nonceLength);
  const msg = naclUtil.decodeUTF8(plaintext);
  const ct = nacl.box(msg, nonce, recipientPk, ephemeral.secretKey);
  // Note: tweetnacl's nacl.box.keyPair() returns the secret in a temporary
  // Uint8Array. JavaScript can't reliably zero it, but it's gc-eligible
  // immediately after this function returns since no caller retains a
  // reference. Acceptable for v1.
  return {
    senderPublicKey: toB64(ephemeral.publicKey),
    nonce: toB64(nonce),
    ciphertext: toB64(ct),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Bot identity pinning (TOFU)
// ─────────────────────────────────────────────────────────────────────────────

export type PinnedBot = {
  pubkeyB64: string;
  fingerprint: string;
  tlsCertSha256?: string | null;
};

export async function getPinnedBot(): Promise<PinnedBot | null> {
  const pub = await storeGet(PINNED_BOT_PUBKEY_KEY);
  const fp = await storeGet(PINNED_BOT_FINGERPRINT_KEY);
  if (!pub || !fp) return null;
  const tls = await storeGet(PINNED_TLS_FINGERPRINT_KEY);
  return { pubkeyB64: pub, fingerprint: fp, tlsCertSha256: tls };
}

export async function pinBot(
  pubkeyB64: string,
  fingerprint: string,
  tlsCertSha256?: string,
): Promise<void> {
  await storeSet(PINNED_BOT_PUBKEY_KEY, pubkeyB64);
  await storeSet(PINNED_BOT_FINGERPRINT_KEY, fingerprint);
  if (tlsCertSha256) {
    await storeSet(PINNED_TLS_FINGERPRINT_KEY, tlsCertSha256);
  }
}

export async function unpinBot(): Promise<void> {
  await storeDelete(PINNED_BOT_PUBKEY_KEY);
  await storeDelete(PINNED_BOT_FINGERPRINT_KEY);
  await storeDelete(PINNED_TLS_FINGERPRINT_KEY);
}

// ─────────────────────────────────────────────────────────────────────────────
// Per-bot push counter (monotonic, never reused — drives bot-side replay
// rejection). Uses Date.now() floor as the initial value so even across
// reinstalls counters move forward in wall-clock time.
// ─────────────────────────────────────────────────────────────────────────────

export async function nextCounter(botFingerprint: string): Promise<number> {
  const key = COUNTER_PREFIX + botFingerprint;
  const stored = await storeGet(key);
  const now = Date.now();
  const last = stored ? Number.parseInt(stored, 10) : 0;
  const next = Math.max(last + 1, now);
  await storeSet(key, String(next));
  return next;
}

// ─────────────────────────────────────────────────────────────────────────────
// Legacy migration: clear long-term keypair from older app builds. Safe to
// call at any time. No-op if no legacy key exists.
// ─────────────────────────────────────────────────────────────────────────────

export async function wipeLegacyKeypair(): Promise<void> {
  await storeDelete(LEGACY_SK_KEY);
}
