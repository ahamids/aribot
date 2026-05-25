"use client";

/**
 * Passphrase-wrapping using WebCrypto (PBKDF2-SHA256 → AES-GCM-256).
 *
 * Used to protect the vault secret key on disk (IndexedDB for the
 * passphrase wrap, Supabase row for the recovery-code wrap). Both
 * wrap/unwrap operations use the same primitive — different inputs
 * (passphrase vs recovery code), different stored salts/IVs.
 *
 * Parameters chosen per OWASP 2023 guidance:
 *   - PBKDF2-SHA256
 *   - 600,000 iterations
 *   - 16-byte random salt
 *   - 12-byte random IV for AES-GCM
 *   - 256-bit derived key
 *
 * Time on a 2024 laptop: ~250ms per derive. Slow enough to deter brute
 * force, fast enough that vault unlock feels instant.
 */
export const PBKDF2_ITERATIONS = 600_000;
const SALT_BYTES = 16;
const IV_BYTES = 12;
const KEY_BITS = 256;

export interface WrappedKey {
  ciphertext: string; // base64
  iv: string; // base64
  salt: string; // base64
  iterations: number;
}

async function deriveKey(
  password: string,
  salt: Uint8Array,
  iterations: number,
): Promise<CryptoKey> {
  const passwordBytes = new TextEncoder().encode(password);
  const baseKey = await crypto.subtle.importKey(
    "raw",
    passwordBytes,
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  return crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: salt as BufferSource,
      iterations,
      hash: "SHA-256",
    },
    baseKey,
    { name: "AES-GCM", length: KEY_BITS },
    false,
    ["encrypt", "decrypt"],
  );
}

function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function fromBase64(text: string): Uint8Array {
  const binary = atob(text);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    out[i] = binary.charCodeAt(i);
  }
  return out;
}

/**
 * Wrap `plaintextKey` (typically a 32-byte X25519 secret key) with a
 * passphrase. Returns the ciphertext + the salt + the IV + the iter
 * count so the wrap is fully self-describing and can be unwrapped
 * with just the passphrase later.
 */
export async function wrapKey(
  plaintextKey: Uint8Array,
  passphrase: string,
): Promise<WrappedKey> {
  const salt = crypto.getRandomValues(new Uint8Array(SALT_BYTES));
  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
  const key = await deriveKey(passphrase, salt, PBKDF2_ITERATIONS);

  const ct = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: iv as BufferSource },
    key,
    plaintextKey as BufferSource,
  );

  return {
    ciphertext: toBase64(new Uint8Array(ct)),
    iv: toBase64(iv),
    salt: toBase64(salt),
    iterations: PBKDF2_ITERATIONS,
  };
}

/**
 * Unwrap `wrapped` with the supplied passphrase. Throws on any failure
 * (bad passphrase, tampered ciphertext, unsupported iter count).
 */
export async function unwrapKey(
  wrapped: WrappedKey,
  passphrase: string,
): Promise<Uint8Array> {
  if (wrapped.iterations < 100_000) {
    throw new Error("wrap iter count below minimum (rejected)");
  }
  const salt = fromBase64(wrapped.salt);
  const iv = fromBase64(wrapped.iv);
  const ct = fromBase64(wrapped.ciphertext);
  const key = await deriveKey(passphrase, salt, wrapped.iterations);

  const pt = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: iv as BufferSource },
    key,
    ct as BufferSource,
  );
  return new Uint8Array(pt);
}
