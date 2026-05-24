"use server";

import { revalidatePath } from "next/cache";
import {
  aribotApi,
  ApiError,
  type CredentialsPushBody,
  type PubkeyResponse,
} from "@/lib/api/aribot";

export type VaultActionResult =
  | { ok: true; fingerprint: string; detail: string }
  | { ok: false; status: number; detail: string };

/**
 * Server-side proxy: returns the bot's pubkey + fingerprint so the
 * browser can encrypt against it. Doing it through a server action
 * (rather than the browser fetching api.aribot.app directly) keeps
 * the JWT in cookies and avoids needing CORS on the backend.
 */
export async function getBotPubkey(): Promise<PubkeyResponse | null> {
  try {
    return await aribotApi.pubkey();
  } catch {
    return null;
  }
}

/**
 * Server-side proxy: forwards the ciphertext payload to POST /credentials.
 * The plaintext (Bybit API key + secret) NEVER touches this server —
 * the browser encrypted it against the bot's pubkey before invoking
 * this action.
 */
export async function pushCredentials(
  body: CredentialsPushBody,
): Promise<VaultActionResult> {
  try {
    const ack = await aribotApi.pushCredentials(body);
    revalidatePath("/dashboard");
    if (ack.ok) {
      return {
        ok: true,
        fingerprint: ack.fingerprint ?? "",
        detail: ack.detail,
      };
    }
    return { ok: false, status: 400, detail: ack.detail };
  } catch (e) {
    if (e instanceof ApiError) {
      const detail =
        e.body &&
        typeof e.body === "object" &&
        "detail" in e.body &&
        typeof (e.body as { detail: unknown }).detail === "string"
          ? (e.body as { detail: string }).detail
          : e.message;
      return { ok: false, status: e.status, detail };
    }
    return { ok: false, status: 0, detail: String(e) };
  }
}

export async function deleteCredentials(): Promise<VaultActionResult> {
  try {
    const ack = await aribotApi.deleteCredentials();
    revalidatePath("/dashboard");
    if (ack.ok) {
      return {
        ok: true,
        fingerprint: ack.fingerprint ?? "",
        detail: ack.detail,
      };
    }
    return { ok: false, status: 400, detail: ack.detail };
  } catch (e) {
    if (e instanceof ApiError) {
      return { ok: false, status: e.status, detail: e.message };
    }
    return { ok: false, status: 0, detail: String(e) };
  }
}
