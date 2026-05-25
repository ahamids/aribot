"use server";

import { revalidatePath } from "next/cache";
import { aribotApi, ApiError, type BotMode } from "@/lib/api/aribot";

export type BotActionState =
  | { ok: true; message: string }
  | { ok: false; message: string }
  | undefined;

export async function setBotMode(
  _state: BotActionState,
  formData: FormData,
): Promise<BotActionState> {
  const mode = formData.get("mode") as BotMode | null;
  if (!mode || !["PAPER", "SHADOW", "LIVE"].includes(mode)) {
    return { ok: false, message: "Invalid mode." };
  }

  try {
    const res = await aribotApi.setMode(mode);
    if (!res.ok) {
      return {
        ok: false,
        message: res.detail || `Could not switch to ${mode}.`,
      };
    }
    revalidatePath("/dashboard");
    return { ok: true, message: `Mode set to ${res.mode}.` };
  } catch (e) {
    return {
      ok: false,
      message:
        e instanceof ApiError
          ? `${e.message}${e.body && typeof e.body === "object" && "detail" in e.body ? ` — ${(e.body as { detail: string }).detail}` : ""}`
          : "Unexpected error talking to backend.",
    };
  }
}

export async function setBybitTestnet(
  _state: BotActionState,
  formData: FormData,
): Promise<BotActionState> {
  const raw = formData.get("testnet");
  if (raw !== "true" && raw !== "false") {
    return { ok: false, message: "Invalid testnet value." };
  }
  const testnet = raw === "true";

  try {
    const res = await aribotApi.setTestnet(testnet);
    if (!res.ok) {
      return {
        ok: false,
        message:
          res.detail || `Could not switch to ${testnet ? "testnet" : "mainnet"}.`,
      };
    }
    revalidatePath("/dashboard");
    revalidatePath("/settings");
    return {
      ok: true,
      message: `Bybit environment set to ${res.testnet ? "TESTNET" : "MAINNET"}.`,
    };
  } catch (e) {
    return {
      ok: false,
      message:
        e instanceof ApiError
          ? `${e.message}${e.body && typeof e.body === "object" && "detail" in e.body ? ` — ${(e.body as { detail: string }).detail}` : ""}`
          : "Unexpected error talking to backend.",
    };
  }
}
