-- ============================================================================
-- M3 — Browser-native Bybit API key vault
--
-- Stores each user's encrypted Bybit credentials. Crypto model:
--
--   1. On vault creation, the browser generates an X25519 keypair (the
--      "vault keypair"). Its public key lives in `vault_public_key` (clear).
--      The secret key NEVER leaves the browser unwrapped.
--
--   2. The secret key is wrapped TWICE:
--        a. With a passphrase (PBKDF2 → AES-GCM). The wrapped result is
--           stored in IndexedDB on the device — NOT in this table.
--        b. With a one-time recovery code (PBKDF2 → AES-GCM). The wrapped
--           result lives here, so a user who clears their browser or
--           switches devices can recover with the code.
--
--   3. The user's Bybit API key + secret are encrypted with libsodium's
--      `crypto_box` against the vault keypair itself (self-encryption).
--      `credentials_nonce` + `credentials_ciphertext` are stored here.
--
--   4. After local decryption, the browser re-encrypts the Bybit creds
--      with libsodium's `crypto_box_seal` against the BOT's pubkey
--      (fetched from `/pubkey`) and POSTs to `/credentials`. The backend
--      decrypts and holds in RAM only — never written to disk.
--
-- Recovery model:
--   - Forgot passphrase + have recovery code: download `recovery_wrapped_sk`,
--     unwrap with the code, set a new passphrase, re-wrap to IndexedDB.
--   - Lost both: total loss. User wipes the row and re-creates the vault.
-- ============================================================================

create table if not exists public.api_key_vault (
    user_id                 uuid primary key
                              references auth.users(id) on delete cascade,

    -- Curve25519 public key of the user's vault keypair (32 bytes,
    -- base64-encoded). Public; anyone can encrypt to it.
    vault_public_key        text not null,

    -- Vault SK wrapped with PBKDF2(recovery_code) → AES-GCM. Decryption
    -- needs the user's recovery code (32 hex chars they wrote down).
    recovery_wrapped_sk     text not null,
    recovery_salt           text not null,
    recovery_iv             text not null,

    -- Bybit creds encrypted with libsodium crypto_box(plaintext, nonce,
    -- vault_public_key, vault_secret_key). Self-encryption: anyone with
    -- the vault SK can decrypt.
    credentials_nonce       text not null,
    credentials_ciphertext  text not null,

    -- Fingerprint of the bot pubkey we last successfully pushed creds to.
    -- Used to detect "you need to re-push because the bot rotated its
    -- identity" — e.g. after a disaster-recovery rebuild.
    bot_pubkey_fingerprint  text,

    -- Last successful push to /credentials.
    pushed_at               timestamptz,

    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now()
);

-- Auto-bump updated_at on any row update.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists api_key_vault_updated_at on public.api_key_vault;
create trigger api_key_vault_updated_at
    before update on public.api_key_vault
    for each row
    execute function public.set_updated_at();

-- ============================================================================
-- Row Level Security: each user can only access their own row.
-- ============================================================================
alter table public.api_key_vault enable row level security;

drop policy if exists "vault owner read"   on public.api_key_vault;
drop policy if exists "vault owner write"  on public.api_key_vault;
drop policy if exists "vault owner insert" on public.api_key_vault;
drop policy if exists "vault owner delete" on public.api_key_vault;

create policy "vault owner read" on public.api_key_vault
    for select using (auth.uid() = user_id);

create policy "vault owner insert" on public.api_key_vault
    for insert with check (auth.uid() = user_id);

create policy "vault owner write" on public.api_key_vault
    for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "vault owner delete" on public.api_key_vault
    for delete using (auth.uid() = user_id);
