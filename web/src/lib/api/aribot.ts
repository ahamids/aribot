import "server-only";

import { createClient } from "@/lib/supabase/server";

/**
 * Server-only fetch wrapper around the Aribot backend.
 *
 * Pulls the user's Supabase access token from cookies, sends it as a
 * Bearer in the Authorization header. All calls are server-to-server
 * (Next.js → api.aribot.app), so the access token never reaches browser
 * JS and we don't need CORS on the backend.
 */

const API_BASE = process.env.NEXT_PUBLIC_ARIBOT_API_URL ?? "https://api.aribot.app";

export type BotMode = "PAPER" | "SHADOW" | "LIVE";

export type BotStatus =
  | "running"
  | "stopped"
  | "stopping"
  | "stale"
  | "killed"
  | "starting"
  | "crashed"
  | "error";

export interface StatusResponse {
  version: string;
  mode: BotMode;
  status: BotStatus;
  uptimeSeconds: number;
  lastCycleIso: string;
  openPositions: number;
  currentBalance: number;
  todaysPnl: number;
  testnet: boolean;
  cycleCount: number;
  runId: string;
  reason?: string;
  // Latest BTC regime gate while the bot is running:
  //   'BUY'         -> longs only this window
  //   'SELL'        -> shorts only this window
  //   'UNAVAILABLE' -> regime fetch failed this cycle
  //   'UNKNOWN'     -> no cycle has computed it yet
  //   null/undefined -> bot not running (snap not authoritative)
  btcRegime?: string | null;
  // Consecutive-loss cooldown: the bot pauses new entries after a loss
  // streak. cooldownActive is true while paused; cooldownUntilIso is the
  // UTC ISO time the pause lifts. Both reflect the running bot only.
  cooldownActive?: boolean;
  cooldownUntilIso?: string | null;
}

export interface ModeResponse {
  ok: boolean;
  mode: BotMode | null;
  detail: string;
  runningPid?: number | null;
}

export interface TestnetResponse {
  ok: boolean;
  testnet: boolean | null;
  detail: string;
  runningPid?: number | null;
}

export interface CredentialsStatusResponse {
  loaded: boolean;
  fingerprint?: string;
  source?: string;
  validatedAtIso?: string;
}

export type PositionSide = "LONG" | "SHORT";

export interface Position {
  symbol: string;
  side: PositionSide;
  size: number;
  entry: number;
  mark?: number;
  pnl: number;
  pnlPercent?: number;
  leverage?: number;
  liquidationPrice?: number;
  openedAtIso?: string;
}

export interface PositionsResponse {
  positions: Position[];
  asOfIso: string;
}

export interface ClosePositionResponse {
  ok: boolean;
  detail: string;
  symbol?: string;
  orderId?: string | null;
  closedQty?: number | null;
}

export interface Trade {
  symbol: string;
  side: PositionSide;
  pnl: number;
  pnlPercent?: number;
  entryPrice?: number;
  exitPrice?: number;
  quantity?: number;
  reason?: string;
  openedAtIso?: string;
  closedAtIso: string;
}

export interface TradesResponse {
  trades: Trade[];
  asOfIso: string;
  note: string;
}

export interface EquityPoint {
  t: string;
  equity: number;
}

export interface EquityStats {
  winRate?: number;
  tradeCount: number;
  avgWin?: number;
  avgLoss?: number;
  bestWin?: number;
  worstLoss?: number;
  pnlAbs: number;
  pnlPercent?: number;
}

export interface EquityResponse {
  points: EquityPoint[];
  todaysPnl: number;
  rangeHours: number;
  stats: EquityStats;
  note: string;
}

export interface PubkeyResponse {
  publicKey: string;
  fingerprint: string;
  algo: string;
}

export interface CredentialsAckResponse {
  ok: boolean;
  detail: string;
  fingerprint?: string;
}

export interface CredentialsPushBody {
  ciphertext: string;
  nonce: string;
  senderPublicKey: string;
  timestampIso: string;
  counter: number;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message?: string,
  ) {
    super(message ?? `Aribot API ${status}`);
    this.name = "ApiError";
  }
}

async function getAccessToken(): Promise<string> {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.getSession();
  if (error || !data.session?.access_token) {
    throw new ApiError(401, null, "Not signed in");
  }
  return data.session.access_token;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const token = await getAccessToken();
  const url = `${API_BASE}${path}`;

  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
      cache: "no-store",
    });
  } catch (e) {
    throw new ApiError(
      0,
      null,
      `Network error talking to Aribot backend (${url}): ${
        e instanceof Error ? e.message : String(e)
      }`,
    );
  }

  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!res.ok) {
    throw new ApiError(res.status, body, `Aribot API ${res.status}: ${path}`);
  }

  return body as T;
}

export const aribotApi = {
  status: () => request<StatusResponse>("/status"),
  positions: () => request<PositionsResponse>("/positions"),
  closePosition: (symbol: string) =>
    request<ClosePositionResponse>("/positions/close", {
      method: "POST",
      body: JSON.stringify({ symbol }),
    }),
  trades: (days = 7) => request<TradesResponse>(`/trades?days=${days}`),
  equity: (days = 1) => request<EquityResponse>(`/equity?days=${days}`),
  setMode: (mode: BotMode) =>
    request<ModeResponse>("/mode", {
      method: "POST",
      body: JSON.stringify({ mode }),
    }),
  setTestnet: (testnet: boolean) =>
    request<TestnetResponse>("/testnet", {
      method: "POST",
      body: JSON.stringify({ testnet }),
    }),
  start: () => request("/start", { method: "POST" }),
  stop: () => request("/stop", { method: "POST" }),
  kill: () => request("/kill", { method: "POST" }),
  clearKill: () => request("/kill", { method: "DELETE" }),
  credentialsStatus: () =>
    request<CredentialsStatusResponse>("/credentials/status"),
  pubkey: () => request<PubkeyResponse>("/pubkey"),
  pushCredentials: (body: CredentialsPushBody) =>
    request<CredentialsAckResponse>("/credentials", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteCredentials: () =>
    request<CredentialsAckResponse>("/credentials", { method: "DELETE" }),
};
