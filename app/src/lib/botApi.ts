// Bot HTTP API client. Calls the FastAPI sidecar in status_server.py.
// The contract is documented in status_server.py — this file is the iOS
// counterpart of the Pydantic response models defined there.
//
// TLS pinning note (v1 limitation): the bot ships with a self-signed cert
// whose SHA-256 fingerprint is recorded on first connect via
// crypto.pinBot(). React Native's stock fetch can't pin TLS certs from
// JS-land — that needs a native module (react-native-ssl-pinning) which
// requires a custom dev client. For v1 we document the pinned fingerprint
// in the UI so the user can verify it manually against the sidecar's
// stdout output; v2 will enforce pinning cryptographically.

import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import { sealForRecipient, getPinnedBot, pinBot, nextCounter } from './crypto';

const CONNECTION_KEY = 'aribot.bot.connection';

async function persistConnection(conn: { hostUrl: string; bearerToken: string } | null): Promise<void> {
  // Persistence so the bot connection survives app restart. SecureStore on
  // iOS = Keychain (the bearer token is sensitive). Web falls back to
  // localStorage with the same dev-only caveat as the rest of crypto.ts.
  if (Platform.OS === 'web') {
    try {
      if (conn) {
        globalThis.localStorage?.setItem(CONNECTION_KEY, JSON.stringify(conn));
      } else {
        globalThis.localStorage?.removeItem(CONNECTION_KEY);
      }
    } catch {
      // ignore localStorage quota/private-mode errors — in-memory cache still works
    }
    return;
  }
  try {
    if (conn) {
      await SecureStore.setItemAsync(CONNECTION_KEY, JSON.stringify(conn), {
        keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
      });
    } else {
      await SecureStore.deleteItemAsync(CONNECTION_KEY);
    }
  } catch {
    // SecureStore errors are surfaced via the next read — the in-memory
    // cache still serves the current session.
  }
}

export type BotStatus = {
  version: string;
  mode: 'PAPER' | 'SHADOW' | 'LIVE';
  status: 'running' | 'stopped' | 'error' | 'killed';
  uptimeSeconds: number;
  lastCycleIso: string;
  openPositions: number;
  currentBalance: number;
  todaysPnl: number;
  testnet?: boolean;
  cycleCount?: number;
  runId?: string;
  reason?: string | null;
};

export type Position = {
  symbol: string;
  side: 'LONG' | 'SHORT';
  size: number;
  entry: number;
  mark?: number | null;
  pnl: number;
  pnlPercent?: number | null;
  leverage?: number | null;
  liquidationPrice?: number | null;
  openedAtIso?: string | null;
};

export type PositionsResponse = {
  positions: Position[];
  asOfIso: string;
};

export type EquityPoint = { t: string; equity: number };
export type EquityStats = {
  winRate: number | null;
  tradeCount: number;
  avgWin: number | null;
  avgLoss: number | null;
  bestWin: number | null;
  worstLoss: number | null;
  pnlAbs: number;
  pnlPercent: number | null;
};
export type EquityResponse = {
  points: EquityPoint[];
  todaysPnl: number;
  rangeHours: number;
  stats: EquityStats;
  note?: string;
};

export type ClosedTrade = {
  symbol: string;
  side: 'LONG' | 'SHORT';
  pnl: number;
  pnlPercent?: number | null;
  entryPrice?: number | null;
  exitPrice?: number | null;
  quantity?: number | null;
  reason?: string | null;
  openedAtIso?: string | null;
  closedAtIso: string;
};
export type TradesResponse = {
  trades: ClosedTrade[];
  asOfIso: string;
  note?: string;
};

export type ControlResponse = {
  ok: boolean;
  action: 'start' | 'stop' | 'kill' | 'clear_kill';
  pid?: number | null;
  detail: string;
};

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string; status?: number };

// Best-effort classifier for the iOS app to choose between rendering the
// HostDownCard (network failure: bot unreachable) vs. an inline error
// (HTTP-level failure: 401 token wrong, 500 sidecar bug). Heuristic: if we
// have an HTTP status code, it's NOT host-down. Otherwise it's transport.
export function isHostDownError(r: { error: string; status?: number }): boolean {
  if (r.status != null) return false;
  // Special-case the "no connection saved" sentinel from getBotConnection.
  if (r.error.startsWith('No bot connection saved')) return false;
  return true;
}

// ─────────────────────────────────────────────────────────────────────────────
// Connection resolution — pulls hostUrl + bearer token from local storage of
// the bot connection saved during onboarding (see lib/vault.ts).
// ─────────────────────────────────────────────────────────────────────────────

export type BotConnection = { hostUrl: string; bearerToken: string };

let _cachedConnection: BotConnection | null = null;
let _hydrationAttempted = false;

export function setBotConnection(conn: BotConnection): void {
  _cachedConnection = conn;
  // Fire-and-forget persistence; callers can also await persistBotConnection
  // if they need durability before navigating.
  void persistConnection(conn);
}

export async function persistBotConnection(conn: BotConnection): Promise<void> {
  _cachedConnection = conn;
  await persistConnection(conn);
}

export async function clearBotConnection(): Promise<void> {
  _cachedConnection = null;
  await persistConnection(null);
}

async function hydrateFromSecureStore(): Promise<BotConnection | null> {
  if (Platform.OS === 'web') {
    try {
      const raw = globalThis.localStorage?.getItem(CONNECTION_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed.hostUrl === 'string' && typeof parsed.bearerToken === 'string') {
        return parsed;
      }
      return null;
    } catch {
      return null;
    }
  }
  try {
    const raw = await SecureStore.getItemAsync(CONNECTION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.hostUrl === 'string' && typeof parsed.bearerToken === 'string') {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}

export async function getBotConnection(): Promise<BotConnection | null> {
  if (_cachedConnection) return _cachedConnection;
  if (!_hydrationAttempted) {
    _hydrationAttempted = true;
    const hydrated = await hydrateFromSecureStore();
    if (hydrated) _cachedConnection = hydrated;
  }
  return _cachedConnection;
}

function trimHost(h: string): string {
  return h.replace(/\/+$/, '');
}

async function callBot<T>(
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<ApiResult<T>> {
  const conn = await getBotConnection();
  if (!conn) return { ok: false, error: 'No bot connection saved. Reconnect in Settings.' };

  const url = `${trimHost(conn.hostUrl)}${path}`;
  if (!/^https?:\/\//i.test(url)) {
    return { ok: false, error: 'Host URL must start with http:// or https://' };
  }

  try {
    const res = await fetch(url, {
      ...init,
      headers: {
        Authorization: `Bearer ${conn.bearerToken}`,
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
      signal,
    });
    if (!res.ok) {
      // Surface the sidecar's JSON detail when present — it's the most useful
      // diagnostic for users (e.g. "bot already running (pid 1234)").
      let detail = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        if (body && typeof body.detail === 'string') detail = body.detail;
        else if (body && typeof body.error === 'string') detail = body.error;
      } catch {
        // ignore non-JSON bodies
      }
      return { ok: false, error: detail, status: res.status };
    }
    const data = (await res.json()) as T;
    return { ok: true, data };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, error: msg };
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Endpoints
// ─────────────────────────────────────────────────────────────────────────────

export function fetchStatus(signal?: AbortSignal): Promise<ApiResult<BotStatus>> {
  return callBot<BotStatus>('/status', {}, signal);
}

export function fetchPositions(signal?: AbortSignal): Promise<ApiResult<PositionsResponse>> {
  return callBot<PositionsResponse>('/positions', {}, signal);
}

export function fetchEquity(
  days: number = 1,
  signal?: AbortSignal,
): Promise<ApiResult<EquityResponse>> {
  const d = Math.max(1, Math.min(30, Math.round(days)));
  return callBot<EquityResponse>(`/equity?days=${d}`, {}, signal);
}

export function fetchTrades(
  days: number = 7,
  signal?: AbortSignal,
): Promise<ApiResult<TradesResponse>> {
  const d = Math.max(1, Math.min(30, Math.round(days)));
  return callBot<TradesResponse>(`/trades?days=${d}`, {}, signal);
}

export function startBot(): Promise<ApiResult<ControlResponse>> {
  return callBot<ControlResponse>('/start', { method: 'POST' });
}

export function stopBot(): Promise<ApiResult<ControlResponse>> {
  return callBot<ControlResponse>('/stop', { method: 'POST' });
}

// Emergency kill switch — same kill_switch.flag file as /stop, but the
// sidecar writes a different intent line so post-mortem can distinguish.
// The bot itself treats both identically (exits at next cycle).
export function tripKill(): Promise<ApiResult<ControlResponse>> {
  return callBot<ControlResponse>('/kill', { method: 'POST' });
}

// Clears the kill switch flag. Idempotent — succeeds even if the flag
// wasn't present, so the UI can call this without first checking.
export function clearKill(): Promise<ApiResult<ControlResponse>> {
  return callBot<ControlResponse>('/kill', { method: 'DELETE' });
}

// Mode change. The sidecar refuses (409) if the bot is currently running.
// Caller should stop the bot first and retry.
export type SetModeResponse = {
  ok: boolean;
  mode?: 'PAPER' | 'SHADOW' | 'LIVE' | null;
  detail: string;
  runningPid?: number | null;
};

export function setBotMode(
  mode: 'PAPER' | 'SHADOW' | 'LIVE',
): Promise<ApiResult<SetModeResponse>> {
  return callBot<SetModeResponse>('/mode', {
    method: 'POST',
    body: JSON.stringify({ mode }),
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// One-shot ping used by the bot-setup screen (no saved connection yet, so we
// take host + token directly rather than going through callBot).
// ─────────────────────────────────────────────────────────────────────────────

export async function pingStatus(
  hostUrl: string,
  bearerToken: string,
  signal?: AbortSignal,
): Promise<ApiResult<BotStatus>> {
  const url = `${trimHost(hostUrl)}/status`;
  if (!/^https?:\/\//i.test(url)) {
    return { ok: false, error: 'Host URL must start with http:// or https://' };
  }
  try {
    const res = await fetch(url, {
      method: 'GET',
      headers: { Authorization: `Bearer ${bearerToken}`, Accept: 'application/json' },
      signal,
    });
    if (!res.ok) return { ok: false, error: `HTTP ${res.status} — token or path rejected`, status: res.status };
    const data = (await res.json()) as BotStatus;
    if (typeof data.status !== 'string') {
      return { ok: false, error: 'Bot replied without a "status" field.' };
    }
    return { ok: true, data };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Credential vault — paired with status_server's /pubkey + /credentials*
// endpoints. The host bearer token is reused as the vault token until the
// operator deploys a separate ARIBOT_API_TOKEN_VAULT.
// ─────────────────────────────────────────────────────────────────────────────

export type BotPubkey = {
  publicKey: string;
  fingerprint: string;
  algo: 'x25519-nacl-box';
};

export type CredentialsStatus = {
  loaded: boolean;
  fingerprint?: string | null;
  source?: string | null;
  validatedAtIso?: string | null;
};

export type CredentialsAck = {
  ok: boolean;
  detail: string;
  fingerprint?: string | null;
};

export type ApiKeyPayload = {
  readKey: string;
  readSecret: string;
  tradeKey: string;
  tradeSecret: string;
};

// Used during onboarding/Settings before TOFU pinning has completed.
// Takes hostUrl explicitly so the caller doesn't depend on a saved
// connection. NO bearer auth — /pubkey is intentionally unauthenticated.
export async function fetchBotPubkey(
  hostUrl: string,
  signal?: AbortSignal,
): Promise<ApiResult<BotPubkey>> {
  const url = `${trimHost(hostUrl)}/pubkey`;
  if (!/^https?:\/\//i.test(url)) {
    return { ok: false, error: 'Host URL must start with http:// or https://' };
  }
  try {
    const res = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal,
    });
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status} — pubkey endpoint rejected`, status: res.status };
    }
    const data = (await res.json()) as BotPubkey;
    if (typeof data.publicKey !== 'string' || typeof data.fingerprint !== 'string') {
      return { ok: false, error: 'Bot pubkey response missing fields' };
    }
    return { ok: true, data };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

// Pushes the user's Bybit credentials to the bot. Steps:
//   1. Reads the pinned bot pubkey (caller must have called pinBot before).
//   2. Generates a fresh ephemeral keypair and seals the payload.
//   3. Generates a monotonic counter for this bot.
//   4. POSTs the envelope. Returns the bot's ack (or the HTTP detail on
//      failure — wrong keys produce 422 with the Bybit message inline).
export async function pushCredentialsToBot(
  payload: ApiKeyPayload,
): Promise<ApiResult<CredentialsAck>> {
  const pinned = await getPinnedBot();
  if (!pinned) {
    return {
      ok: false,
      error: 'Bot identity not pinned. Reconnect in Settings → Bot identity.',
    };
  }
  const conn = await getBotConnection();
  if (!conn) {
    return { ok: false, error: 'No bot connection saved. Reconnect in Settings.' };
  }

  let sealed;
  try {
    sealed = sealForRecipient(pinned.pubkeyB64, JSON.stringify(payload));
  } catch (e) {
    return { ok: false, error: `seal failed: ${e instanceof Error ? e.message : String(e)}` };
  }

  const counter = await nextCounter(pinned.fingerprint);
  const body = JSON.stringify({
    ciphertext: sealed.ciphertext,
    nonce: sealed.nonce,
    senderPublicKey: sealed.senderPublicKey,
    timestampIso: new Date().toISOString(),
    counter,
  });

  return callBot<CredentialsAck>('/credentials', { method: 'POST', body });
}

export function fetchCredentialsStatus(
  signal?: AbortSignal,
): Promise<ApiResult<CredentialsStatus>> {
  return callBot<CredentialsStatus>('/credentials/status', {}, signal);
}

export function forgetCredentialsOnBot(): Promise<ApiResult<CredentialsAck>> {
  return callBot<CredentialsAck>('/credentials', { method: 'DELETE' });
}

// First-time pin: fetch the bot's pubkey and pin it (TOFU). Returns the
// fetched identity so the UI can show the fingerprint to the operator.
// If a different pubkey is already pinned for this host, returns an error
// (the caller must explicitly unpinBot() then retry, surfacing a warning
// in the UI per the security plan).
export async function pinBotFromHost(
  hostUrl: string,
  signal?: AbortSignal,
): Promise<ApiResult<BotPubkey>> {
  const fetched = await fetchBotPubkey(hostUrl, signal);
  if (!fetched.ok) return fetched;
  const existing = await getPinnedBot();
  if (existing && existing.fingerprint !== fetched.data.fingerprint) {
    return {
      ok: false,
      error:
        `Bot identity changed. Pinned ${existing.fingerprint}, host now offers ${fetched.data.fingerprint}. ` +
        'Unpin in Settings → Bot identity to re-trust.',
    };
  }
  await pinBot(fetched.data.publicKey, fetched.data.fingerprint);
  return fetched;
}

