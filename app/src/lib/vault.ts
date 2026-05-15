// API key vault — bot-direct flow.
//
// Per the locked-in security plan, Bybit credentials are pushed directly to
// the user's self-hosted bot over a TLS-pinned channel. There is no
// Supabase backup of the encrypted blob in this flow — see the design
// audit for the rationale (smaller attack surface; phone-loss recovery is
// handled by re-pasting from the Bybit dashboard).
//
// This module is a thin orchestration layer. The cryptography lives in
// crypto.ts and the HTTP plumbing in botApi.ts.

import type { ApiKeyPayload, CredentialsAck } from './botApi';
import { getPinnedBot, pinBot } from './crypto';
import {
  fetchBotPubkey,
  pushCredentialsToBot,
  forgetCredentialsOnBot,
  fetchCredentialsStatus,
} from './botApi';

export type { ApiKeyPayload };

export type SaveResult = { ok: true; fingerprint: string } | { ok: false; error: string };

export async function saveApiKeysToBot(
  payload: ApiKeyPayload,
  hostUrl?: string,
): Promise<SaveResult> {
  // If the bot pubkey hasn't been pinned yet, fetch it now (TOFU). This
  // path is hit when the vault screen is shown immediately after the
  // bot-setup screen, before any other authenticated call.
  const pinned = await getPinnedBot();
  if (!pinned) {
    if (!hostUrl) {
      return { ok: false, error: 'No bot connection — set up the bot host first.' };
    }
    const pub = await fetchBotPubkey(hostUrl);
    if (!pub.ok) {
      return { ok: false, error: `Could not reach bot for pubkey: ${pub.error}` };
    }
    await pinBot(pub.data.publicKey, pub.data.fingerprint);
  }

  const ack = await pushCredentialsToBot(payload);
  if (!ack.ok) {
    return { ok: false, error: ack.error };
  }
  const detail: CredentialsAck = ack.data;
  if (!detail.ok) {
    return { ok: false, error: detail.detail };
  }
  return { ok: true, fingerprint: detail.fingerprint ?? '' };
}

export async function wipeApiKeysOnBot(): Promise<SaveResult> {
  const ack = await forgetCredentialsOnBot();
  if (!ack.ok) {
    return { ok: false, error: ack.error };
  }
  return { ok: true, fingerprint: '' };
}

export async function loadedCredentialsStatus() {
  return fetchCredentialsStatus();
}
