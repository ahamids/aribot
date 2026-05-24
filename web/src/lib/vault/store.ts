"use client";

import { createClient } from "@/lib/supabase/client";

export interface VaultRow {
  user_id: string;
  vault_public_key: string;
  recovery_wrapped_sk: string;
  recovery_salt: string;
  recovery_iv: string;
  credentials_nonce: string;
  credentials_ciphertext: string;
  bot_pubkey_fingerprint: string | null;
  pushed_at: string | null;
  created_at: string;
  updated_at: string;
}

export type VaultUpsertInput = Pick<
  VaultRow,
  | "vault_public_key"
  | "recovery_wrapped_sk"
  | "recovery_salt"
  | "recovery_iv"
  | "credentials_nonce"
  | "credentials_ciphertext"
>;

export async function loadVault(userId: string): Promise<VaultRow | null> {
  const supabase = createClient();
  const { data, error } = await supabase
    .from("api_key_vault")
    .select("*")
    .eq("user_id", userId)
    .maybeSingle();

  if (error) {
    throw new Error(`Could not load vault: ${error.message}`);
  }
  return (data as VaultRow | null) ?? null;
}

export async function saveVault(
  userId: string,
  input: VaultUpsertInput,
): Promise<void> {
  const supabase = createClient();
  const { error } = await supabase.from("api_key_vault").upsert({
    user_id: userId,
    ...input,
  });
  if (error) {
    throw new Error(`Could not save vault: ${error.message}`);
  }
}

export async function markPushed(
  userId: string,
  botFingerprint: string,
): Promise<void> {
  const supabase = createClient();
  const { error } = await supabase
    .from("api_key_vault")
    .update({
      bot_pubkey_fingerprint: botFingerprint,
      pushed_at: new Date().toISOString(),
    })
    .eq("user_id", userId);
  if (error) {
    throw new Error(`Could not mark pushed: ${error.message}`);
  }
}

export async function deleteVault(userId: string): Promise<void> {
  const supabase = createClient();
  const { error } = await supabase
    .from("api_key_vault")
    .delete()
    .eq("user_id", userId);
  if (error) {
    throw new Error(`Could not delete vault: ${error.message}`);
  }
}
