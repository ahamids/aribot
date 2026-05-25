"use server";

import { revalidatePath } from "next/cache";
import { aribotApi, ApiError } from "@/lib/api/aribot";

/**
 * Discriminated union the client uses to render success / error states.
 * `status` is the HTTP code from the backend so the UI can branch (409 =
 * "already running", 412 = "no credentials", etc.).
 */
export type ControlResult =
  | { ok: true; action: string; pid: number | null; detail: string }
  | { ok: false; status: number; detail: string };

interface ControlResponseBody {
  ok: boolean;
  action: string;
  pid: number | null;
  detail: string;
}

async function runControl(
  fn: () => Promise<unknown>,
): Promise<ControlResult> {
  try {
    const res = (await fn()) as ControlResponseBody;
    revalidatePath("/dashboard");
    if (res.ok) {
      return {
        ok: true,
        action: res.action,
        pid: res.pid ?? null,
        detail: res.detail,
      };
    }
    // Backend returned a structured "ok: false" — surface its detail.
    return { ok: false, status: 500, detail: res.detail };
  } catch (e) {
    if (e instanceof ApiError) {
      // FastAPI HTTPException body is { detail: string } per our backend
      // contract; surface it directly so the user sees the same message
      // the sidecar logged.
      const detail =
        e.body &&
        typeof e.body === "object" &&
        "detail" in e.body &&
        typeof (e.body as { detail: unknown }).detail === "string"
          ? (e.body as { detail: string }).detail
          : e.message;
      // For 409/412/etc the ApiError body shape matches ControlOut, so
      // extract `detail` if present, otherwise fall back to whatever we
      // got back.
      if (
        e.body &&
        typeof e.body === "object" &&
        "detail" in e.body
      ) {
        return {
          ok: false,
          status: e.status,
          detail: (e.body as { detail: string }).detail,
        };
      }
      return { ok: false, status: e.status, detail };
    }
    return { ok: false, status: 0, detail: String(e) };
  }
}

export async function startBot(): Promise<ControlResult> {
  return runControl(() => aribotApi.start());
}

export async function stopBot(): Promise<ControlResult> {
  return runControl(() => aribotApi.stop());
}

export async function killBot(): Promise<ControlResult> {
  return runControl(() => aribotApi.kill());
}

export async function clearKill(): Promise<ControlResult> {
  return runControl(() => aribotApi.clearKill());
}
