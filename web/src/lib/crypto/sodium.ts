"use client";

import sodium from "libsodium-wrappers";

/**
 * libsodium initializes asynchronously (WASM load). All callers MUST
 * `await ready()` before touching any sodium function. Cached after the
 * first call so subsequent ones are zero-cost.
 */
let _ready: Promise<typeof sodium> | null = null;
export function ready(): Promise<typeof sodium> {
  if (!_ready) {
    _ready = sodium.ready.then(() => sodium);
  }
  return _ready;
}

export const KEYPAIR_BYTES = 32;
export const BOX_NONCE_BYTES = 24;
export const SEAL_BYTES = 48; // ephemeralPubkey(32) + auth tag(16)

export interface VaultKeypair {
  publicKey: Uint8Array;
  secretKey: Uint8Array;
}

/**
 * Generate a fresh X25519 keypair for use with crypto_box / crypto_box_seal.
 * Both keys are 32 bytes.
 */
export async function generateVaultKeypair(): Promise<VaultKeypair> {
  const s = await ready();
  const kp = s.crypto_box_keypair();
  return { publicKey: kp.publicKey, secretKey: kp.privateKey };
}

/**
 * Self-encrypt: encrypts plaintext using crypto_box with the vault's own
 * keypair. Anyone holding the vault SK (which never leaves the browser
 * unwrapped) can decrypt. Used to store Bybit credentials in Supabase.
 *
 * Returns {nonce, ciphertext} both base64-encoded.
 */
export async function selfEncrypt(
  plaintext: Uint8Array,
  keypair: VaultKeypair,
): Promise<{ nonce: string; ciphertext: string }> {
  const s = await ready();
  const nonce = s.randombytes_buf(BOX_NONCE_BYTES);
  const ct = s.crypto_box_easy(
    plaintext,
    nonce,
    keypair.publicKey,
    keypair.secretKey,
  );
  return {
    nonce: s.to_base64(nonce, s.base64_variants.ORIGINAL),
    ciphertext: s.to_base64(ct, s.base64_variants.ORIGINAL),
  };
}

export async function selfDecrypt(
  ciphertextB64: string,
  nonceB64: string,
  keypair: VaultKeypair,
): Promise<Uint8Array> {
  const s = await ready();
  const ct = s.from_base64(ciphertextB64, s.base64_variants.ORIGINAL);
  const nonce = s.from_base64(nonceB64, s.base64_variants.ORIGINAL);
  return s.crypto_box_open_easy(
    ct,
    nonce,
    keypair.publicKey,
    keypair.secretKey,
  );
}

/**
 * Push-encrypt for POST /credentials: generates an ephemeral X25519
 * keypair, encrypts `plaintext` to the bot's pubkey, returns everything
 * the backend needs to decrypt + replay-check.
 *
 * The backend's accept_sealed_push expects:
 *   { ciphertext, nonce, senderPublicKey, timestampIso, counter }
 *
 * Counter is per-senderPublicKey. Since we always generate a fresh
 * ephemeral keypair per push, counter can always be 1 — the backend's
 * replay ledger is indexed by sender_pubkey_b64, and a new keypair has
 * no prior entry.
 */
export interface CredentialsPushPayload {
  ciphertext: string;
  nonce: string;
  senderPublicKey: string;
  timestampIso: string;
  counter: number;
}

export async function encryptCredentialsPush(
  plaintext: Uint8Array,
  botPublicKey: Uint8Array,
): Promise<CredentialsPushPayload> {
  const s = await ready();
  const ephemeral = s.crypto_box_keypair();
  const nonce = s.randombytes_buf(BOX_NONCE_BYTES);
  const ct = s.crypto_box_easy(
    plaintext,
    nonce,
    botPublicKey,
    ephemeral.privateKey,
  );
  return {
    ciphertext: s.to_base64(ct, s.base64_variants.ORIGINAL),
    nonce: s.to_base64(nonce, s.base64_variants.ORIGINAL),
    senderPublicKey: s.to_base64(
      ephemeral.publicKey,
      s.base64_variants.ORIGINAL,
    ),
    timestampIso: new Date().toISOString(),
    counter: 1,
  };
}

export async function b64encode(bytes: Uint8Array): Promise<string> {
  const s = await ready();
  return s.to_base64(bytes, s.base64_variants.ORIGINAL);
}

export async function b64decode(text: string): Promise<Uint8Array> {
  const s = await ready();
  return s.from_base64(text, s.base64_variants.ORIGINAL);
}

/**
 * Generate a one-time recovery code: 32 hex chars (128 bits of entropy).
 * Shown to the user once at vault creation; never persisted unwrapped.
 *
 * Format: lowercase hex, no separators. Stripping whitespace + dashes on
 * recovery so users can paste in any format.
 */
export async function generateRecoveryCode(): Promise<string> {
  const s = await ready();
  const bytes = s.randombytes_buf(16);
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Display-friendly grouping (5 chars × 6 groups + 2 trailing).
 * Returns "abc12-3def4-5..." for readability.
 */
export function formatRecoveryCode(raw: string): string {
  const clean = raw.toLowerCase().replace(/[^0-9a-f]/g, "");
  return clean.match(/.{1,5}/g)?.join("-") ?? clean;
}

export function normalizeRecoveryCode(input: string): string {
  return input.toLowerCase().replace(/[^0-9a-f]/g, "");
}
