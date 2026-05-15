# Aribot iOS — Expo app

React Native + Expo implementation of the Aribot iOS design package. Scope of
this pass: **Splash, Sign in/up, and the full onboarding flow** (3-card
carousel → bot connection setup → API key vault). The dashboard and main
tabbed app (positions / history / settings) are intentionally *not* in this
pass; they're scaffolded as routes but not implemented.

## What's wired up

| Surface | Status |
| --- | --- |
| Splash / Welcome | ✅ Static UI, navigates to sign-in / sign-up |
| Sign up | ✅ Real Supabase signUp — email + password + 12-char check + encryption ack |
| Sign in | ✅ Real Supabase signInWithPassword |
| Onboarding carousel (3 cards) | ✅ Swipeable, dot indicator, skip button |
| Bot connection setup | ✅ Real `fetch(host/status)` with bearer token; success/error states |
| API key vault | ✅ Real Curve25519 sealed-box encryption via tweetnacl before upload |
| Onboarding "done" terminus | ✅ Lands here after vault save (until dashboard ships) |
| Dashboard / positions / history / settings | ⬜ Not in this pass |

## Run it

Prereqs: Node 18+, npm. On Windows you'll want the Expo Go app on an iPhone
to test on a real device — the iOS Simulator is macOS-only.

```powershell
cd C:\git\aribot-og\app
copy .env.example .env
# Edit .env with your Supabase URL + anon key (see "Configure Supabase" below)
npm start
```

Then scan the QR code with Expo Go on your iPhone. The cream-and-coral splash
should appear within a couple seconds.

You can also run in a browser preview (less faithful — RN shadows + safe-area
are approximate on web) with `npm run web`.

## Configure Supabase

`.env` keys (both must be set or auth will throw a clear error):

```
EXPO_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
EXPO_PUBLIC_SUPABASE_ANON_KEY=your-anon-key-here
```

The anon key is public by design; RLS protects the data.

You'll also need two tables for the vault + bot-connection upserts to succeed.
Schema (run in Supabase SQL editor):

```sql
create table api_key_vault (
  user_id     uuid primary key references auth.users(id) on delete cascade,
  public_key  text not null,
  nonce       text not null,
  ciphertext  text not null,
  updated_at  timestamptz default now()
);
alter table api_key_vault enable row level security;
create policy "vault owner" on api_key_vault
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create table bot_connections (
  user_id     uuid primary key references auth.users(id) on delete cascade,
  host_url    text not null,
  token_enc   text not null,
  updated_at  timestamptz default now()
);
alter table bot_connections enable row level security;
create policy "bot owner" on bot_connections
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
```

Until those tables exist, the vault and bot-setup save steps will surface
the Supabase error in the red error card — which is also the design's intended
failure UX.

### Configure the email OTP template to send a 6-digit code (not a link)

The iOS app's "Email me a 6-digit code" button calls
`supabase.auth.signInWithOtp({email})`. By default Supabase emails a clickable
magic *link*, not a code — that mismatches the in-app verify screen which
expects the user to type a 6-digit value.

To switch your project to code-style OTP emails:

1. Supabase dashboard → **Authentication → Email Templates → Magic Link**.
2. Replace any `{{ .ConfirmationURL }}` reference with `{{ .Token }}`. A
   minimal template body:
   ```
   Your Aribot verification code is:

   {{ .Token }}

   This code expires in 60 minutes.
   ```
3. Save. The next OTP request will deliver a 6-digit code instead of a link.

Until you make that change, users will receive an email with a link they
can't use from inside the app.

## The encryption is real

The "even we can't read these" copy on the vault screen isn't aspirational.
The flow:

1. On first vault use, `src/lib/crypto.ts` generates a Curve25519 keypair via
   tweetnacl.
2. The **secret key** is stored in iOS Keychain via `expo-secure-store` with
   `WHEN_UNLOCKED_THIS_DEVICE_ONLY` — it never leaves the device, doesn't sync
   to iCloud, and isn't accessible while the phone is locked.
3. API keys are JSON-encoded, encrypted with `nacl.box(plaintext, nonce, pk, sk)`
   (self-encryption pattern), and the {publicKey, nonce, ciphertext} triple is
   uploaded to Supabase.
4. Without the device's secret key, the ciphertext is mathematically opaque —
   not just policy-protected.

Wiping the device or signing out + re-installing the app **loses access to the
ciphertext**. That's the trade-off for the trust property. A future
"recovery passphrase" flow could mitigate by wrapping the SK with a user-chosen
passphrase, but that's out of scope here.

## Bot HTTP API contract

The bot-setup screen calls `GET {host}/status` with an optional
`Bearer {token}` header and expects:

```json
{
  "version": "ef03d39",
  "mode": "PAPER",
  "status": "running",
  "uptimeSeconds": 8400,
  "lastCycleIso": "2026-05-11T15:00:00Z",
  "openPositions": 3,
  "currentBalance": 412.74,
  "todaysPnl": 12.74
}
```

This endpoint is implemented by [`status_server.py`](../status_server.py) — a
small FastAPI sidecar in the repo root. It reads `aribot_status.json`, which
the trading bot writes at the end of every loop cycle, and derives the
`status` enum from snapshot freshness, pid liveness, and the kill-switch flag.

Run it alongside the bot:

```bash
pip install -r ../requirements-status-server.txt
python ../status_server.py
```

By default the sidecar binds `127.0.0.1:8787`. Expose it to the iOS app via
Tailscale, an SSH tunnel, or a reverse proxy with TLS. If you need a bearer
token (e.g. when the endpoint isn't behind a tunnel), set
`ARIBOT_API_TOKEN=<random-hex>` in the sidecar's env and paste the same value
into the iOS app's bot-setup screen.

## Layout

```
app/
├─ app/                      Expo Router file-based routes
│  ├─ _layout.tsx            Root: providers + auth/onboarding gate
│  ├─ index.tsx              Splash / welcome
│  ├─ (auth)/
│  │  ├─ sign-in.tsx
│  │  └─ sign-up.tsx
│  └─ (onboarding)/
│     ├─ welcome.tsx         3-card carousel
│     ├─ bot-setup.tsx       Host URL + bearer token + /status ping
│     ├─ vault.tsx           Sealed-box encrypted Bybit keys
│     └─ done.tsx            Terminal — until dashboard ships
└─ src/
   ├─ theme/tokens.ts        Ported design tokens
   ├─ mascot/
   │  ├─ Bear.tsx            Placeholder character (swap later)
   │  ├─ MascotSlot.tsx      Reusable circular frame
   │  └─ MProp.tsx           Accessories (flag/cable/chart/vault)
   ├─ components/            Btn, Input, Card, Icon, StatusPill, Screen
   └─ lib/
      ├─ supabase.ts         Client + env loading
      ├─ auth.tsx            Session context
      ├─ crypto.ts           tweetnacl sealed-box helpers
      ├─ vault.ts            Supabase upserts (encrypted blobs only)
      └─ botApi.ts           Bot /status fetch helper
```

## Swap the mascot

The bear is a placeholder. `src/mascot/MascotSlot.tsx` is the slot every
screen renders into — replace the `<Bear />` inside with a custom character
component that takes the same `pose` prop and every screen picks it up. You
need 11 poses: `alert`, `sleeping`, `napping`, `panicked`, `sad`,
`questioning`, `serious`, `wink`, `happy`, `thumbsup`, `waving`.

## What didn't make this pass

- Dashboard, positions, history, settings, kill switch, LIVE confirm sheet,
  dark mode, empty/error states — all designed in the package, all out of scope
  per the user's "must-have" selection.
- Magic-link auth (Supabase `signInWithOtp`) — button is there, handler isn't.
- "How do I find these?" help drawer on bot-setup.
- Recovery passphrase for the vault secret key — see the encryption note above.
