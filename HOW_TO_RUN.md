# How to run Aribot on your phone (end-to-end)

This is the runbook for your exact setup: Windows laptop, iPhone on the same
Wi-Fi, Expo Go for iOS, Supabase for auth, and the Python trading bot + status
sidecar running on the laptop.

When you finish this guide you'll be looking at the green
**"Connected · &lt;sha&gt; · Mode: …"** card on your phone, with real numbers
coming from the actual bot.

---

## What you're starting

Three processes run together. Each needs its own terminal window. Order
matters only loosely — the bot must start *before* the sidecar can serve real
data, but you can start them all at once and the sidecar will recover when
the snapshot file appears.

| Terminal | What runs | Why |
| --- | --- | --- |
| 1 | `usdt_paper_bot_v2.py` | The trading bot itself. Writes `aribot_status.json` every cycle. |
| 2 | `status_server.py` | FastAPI sidecar. Serves `GET /status` to the iOS app. |
| 3 | `npx expo start --host lan` | Metro bundler. Serves the JS bundle to Expo Go on your phone. |

---

## Step 1 — One-time setup (do these once, ever)

### 1a. Allow Metro through Windows Firewall (port 8081)

Open **PowerShell as Administrator** and run:

```powershell
New-NetFirewallRule -DisplayName "Expo Metro 8081" -Direction Inbound -Protocol TCP -LocalPort 8081 -Action Allow -Profile Private
New-NetFirewallRule -DisplayName "Aribot status 8787" -Direction Inbound -Protocol TCP -LocalPort 8787 -Action Allow -Profile Private
```

The first rule lets your phone download the JS bundle. The second lets the
phone reach the status sidecar. Both are scoped to `Private` profile only —
they do *not* open these ports on coffee-shop Wi-Fi.

### 1b. Install the sidecar Python dependencies

The sidecar now needs PyNaCl (for X25519 sealed-box decryption), `cryptography`
(for the self-signed TLS cert it presents to the iOS app), and `keyring` (so
the bot's secret key and TLS private key live in Windows Credential Manager,
not on disk).

```powershell
cd C:\git\aribot-og
pip install -r requirements-status-server.txt
```

> **Note — Supabase tables are no longer used.** Earlier builds uploaded
> sealed-box ciphertext to `api_key_vault` / `bot_connections`. The current
> flow pushes credentials directly from the iOS app to the bot over a
> TLS-pinned channel; nothing transits Supabase. If you ran the prior SQL
> setup, those tables are inert — you can leave them or drop them.

### 1c. Set up the iOS app's Supabase credentials

```powershell
cd C:\git\aribot-og\app
copy .env.example .env
notepad .env
```

Fill in your Supabase URL and anon key (from Supabase dashboard → Project
Settings → API). Save the file. You only do this once.

### 1c-mode. About mode-specific sqlite databases (one-time awareness)

As of 2026-05-13, the bot uses **per-mode sqlite files** so paper/shadow/live
trades never commingle:

- `usdt_bot_v2.paper.db`
- `usdt_bot_v2.shadow.db`
- `usdt_bot_v2.live.db`

**Auto-migration on first start.** If you're upgrading from a version that
used the unsuffixed `usdt_bot_v2.db`, the bot detects this on first start
and renames the legacy file to match the *current* `BOT_MODE` value. No
data is lost — your balance, positions, and closed trades carry over to
the renamed file.

**Switching modes empties the dashboard.** When you switch from LIVE to
PAPER, the bot opens `usdt_bot_v2.paper.db` — a fresh file if you've never
run PAPER on this machine before. The iOS app shows "no positions" and
"no closed trades." That's correct — those numbers belong to LIVE and
they're waiting in `usdt_bot_v2.live.db`. Switching back restores them.

**The sidecar follows.** It reads the bot's snapshot to learn which file
to query, so `/positions`, `/trades`, and `/equity` always reflect the
mode the bot is currently using.

### 1d. Install Expo Go on your iPhone

App Store → search "Expo Go" → install. Currently SDK 54 (the version this
project is on). You don't need to sign in.

---

## Step 2 — Find your laptop's Wi-Fi IP (every time, it can change)

**Your IP changes** when your router hands out a new DHCP lease, when you
swap networks, when you reconnect after sleep. Don't hardcode it. Find it
fresh each session.

In PowerShell:

```powershell
Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Wi-Fi' | Select-Object IPAddress
```

Write that IP down — you'll use it twice in the next steps. For the rest of
this guide I'll refer to it as **`$LAPTOP_IP`**. Today it's
`10.55.31.243`; tomorrow it might be `192.168.0.110`. Always check.

> **If you have a VPN running** (Tailscale, corporate, NordVPN, etc.) the
> result above might not be the one your phone can reach. Disconnect the VPN
> first, or use the tunnel fallback at the end of this doc.

---

## Step 3 — Start the trading bot (Terminal 1)

```powershell
cd C:\git\aribot-og
python usdt_paper_bot_v2.py --symbols-file symbol_focus.example.json --emojis
```

Within a few seconds you should see lines like:

```
2026-XX-XX HH:MM:SS - 🚀 Starting paper_bot_v2...
2026-XX-XX HH:MM:SS - 🧭 Environment: mode=live, testnet=False, ...
2026-XX-XX HH:MM:SS - 🔄 Cycle 1 @ ...
```

Verify the bot is writing the snapshot file (in a *new* PowerShell window,
keep Terminal 1 running):

```powershell
Test-Path C:\git\aribot-og\aribot_status.json
Get-Content C:\git\aribot-og\aribot_status.json -Raw | ConvertFrom-Json | Select-Object mode, cycle_count, open_positions, current_balance
```

If `cycle_count` is going up every minute, the bot's healthy.

---

## Step 4 — Start the status sidecar (Terminal 2)

In a *new* PowerShell window:

```powershell
cd C:\git\aribot-og
python status_server.py --host 0.0.0.0 --port 8787
```

The `--host 0.0.0.0` matters — by default the sidecar binds `127.0.0.1`
(loopback only), which means your phone can't reach it. `0.0.0.0` makes it
listen on every interface, including the Wi-Fi one.

You should see something like:

```
[status_server] TLS cert SHA-256: 6E:1F:…(32 bytes)…
[aribot] bot identity generated. pubkey fingerprint: 9c0a3b8f2e7d4a16
[aribot] When iOS first connects it will TOFU-pin this fingerprint.
[status_server] version=<git-sha> bind=https://0.0.0.0:8787 snapshot=... auth=token (mandatory) host_pubkey_fp=9c0a3b8f2e7d4a16
INFO:     Uvicorn running on https://0.0.0.0:8787 (Press CTRL+C to quit)
```

Note the URL is `https://` now — the sidecar generates a self-signed cert
on first boot. The two fingerprints printed above (TLS cert SHA-256 and
X25519 pubkey fingerprint) are what the iOS app TOFU-pins on first connect.
Keep this terminal in view during the first iOS pairing so you can spot a
mismatch if anything's wrong.

> **Skipping TLS for local-only dev.** You can pass `--no-tls` to bind plain
> HTTP — bearer tokens travel cleartext, the iOS app will refuse the
> connection. Not recommended.

Verify from *the laptop* first (proves the sidecar itself works). The
`-SkipCertificateCheck` flag is needed because we're using a self-signed
cert — that's the whole point; iOS will pin the fingerprint instead of
trusting a public CA.

```powershell
Invoke-WebRequest -Uri https://127.0.0.1:8787/healthz -SkipCertificateCheck | Select-Object -ExpandProperty Content
```

Now verify from your **phone**. Open Safari on the iPhone and go to:

```
https://$LAPTOP_IP:8787/healthz
```

Safari will warn about the self-signed cert. Tap "Show Details" → "Visit
this website" → enter your phone passcode. You should then see
`{"ok":true,"version":"..."}`.
**If you don't see that in Safari, no amount of iOS-app debugging will help
you** — fix this first:

- Did you run the firewall command in step 1a?
- Is your VPN off?
- Are the phone and laptop on the same Wi-Fi SSID?

---

## Step 5 — Start Metro (Terminal 3)

In a *third* new PowerShell window:

```powershell
cd C:\git\aribot-og\app
$env:REACT_NATIVE_PACKAGER_HOSTNAME = "<paste $LAPTOP_IP here>"
npx expo start --host lan
```

The `REACT_NATIVE_PACKAGER_HOSTNAME` env var forces Metro to use your Wi-Fi
IP rather than auto-picking the wrong adapter (you have several — Hyper-V,
WSL, VPN, Wi-Fi — and Metro can guess wrong).

You'll see a QR code and a line like:

```
Metro waiting on exp://10.55.31.243:8081
```

The URL must start with `exp://<your Wi-Fi IP>:` — **not** `127.0.0.1`. If it
still says `127.0.0.1`, stop Metro (Ctrl+C), confirm the env var was set in
the *same* terminal window, and retry.

---

## Step 6 — Open the app on your phone

1. On the iPhone, open the **Camera** app and point it at the QR code in
   Terminal 3.
2. A notification appears: "Open in Expo Go". Tap it.
3. Expo Go opens, downloads the JS bundle (you'll see a progress bar — this
   is what the firewall rule from step 1a unblocks), and the cream-and-peach
   **Aribot** splash appears.

If you get *"Could not connect to the server"*, the JS bundle download
failed. Most likely: firewall rule missing (step 1a), VPN active, or wrong
IP in `REACT_NATIVE_PACKAGER_HOSTNAME`.

---

## Step 7 — Sign in, then connect the bot

In the app:

1. **Create account** (or sign in if you already did).
2. After sign-up you'll land on the 3-card onboarding carousel. Swipe
   through, tap **Let's go**.
3. On the **Connect bot** screen, fill in:
   - **HOST URL:** `https://$LAPTOP_IP:8787` (no trailing slash). Use the IP
     from step 2. Note the `https://` — the sidecar now serves TLS.
   - **BEARER TOKEN:** the value you set as `ARIBOT_API_TOKEN` in `.env`.
     Required: the sidecar refuses protected endpoints if it's empty.
4. Tap **Test connection**. Mascot gives a thumbs-up; you see a green card.
5. Tap **Continue**. The app:
   - persists the host + token to iOS Keychain;
   - calls `GET /pubkey` and **TOFU-pins** the bot's X25519 fingerprint;
   - advances to the API key vault.
6. On the **Bybit keys** screen, paste your read keypair and trade keypair.
   Tap **Encrypt & save**. The app:
   - generates an ephemeral X25519 keypair on the device;
   - sealed-box-encrypts your keys to the bot's pinned pubkey;
   - POSTs `{ciphertext, nonce, senderPublicKey, timestamp, counter}` to
     `POST /credentials`;
   - the sidecar decrypts, calls Bybit's `/v5/user/query-api` to verify the
     keys are valid + withdraw-disabled, and stores them in RAM.

> **Bot identity verification (optional).** Compare the X25519 fingerprint
> the sidecar printed in Terminal 2 (`host_pubkey_fp=…`) with the one shown
> in the iOS app's **Settings → Bot identity** screen. They must match. If
> they don't, your network is between you and the bot and you should
> investigate before pushing keys.

From here the app has a live, end-to-end-encrypted channel to the bot, and
the bot has the credentials it needs to run in LIVE mode. Starting LIVE
without a successful credential push will be refused with HTTP 412.

---

## Daily operation (after the one-time setup)

In multi-tenant mode (the default), the sidecar launches each user's bot
on demand when they tap "start" in the iOS app. You no longer need a
dedicated bot terminal.

Open **two PowerShell windows**, run one command in each:

```powershell
# Terminal 1 — the sidecar (spawns per-tenant bots on POST /start)
cd C:\git\aribot-og; python status_server.py --host 0.0.0.0 --port 8787

# Terminal 2 — Metro (only needed during iOS app development)
cd C:\git\aribot-og\app; $env:REACT_NATIVE_PACKAGER_HOSTNAME = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Wi-Fi').IPAddress; npx expo start --host lan
```

The sidecar requires `SUPABASE_URL` and `SUPABASE_JWT_SECRET` in the
environment — set them in `.env` (see `.env.example`). Without those,
the sidecar refuses to boot in multi-tenant mode and exits with a
clear error.

Scan Metro's QR with the iPhone Camera app. Sign in with your Supabase
account in the iOS app, push your Bybit keys via the Vault screen, and
tap "start". The sidecar spawns *your* bot under
`<ARIBOT_ARTIFACT_DIR>/tenants/<your-uuid>/`. Two users can do this
simultaneously without their data, logs, or bots colliding.

**For production**, you only need Terminal 1 (the sidecar). The iOS
app is the operator UI for end users; Metro is a developer-only tool.

---

## When things break — diagnostic decision tree

### "Could not connect to the server" in Expo Go

The phone can't reach Metro on port 8081. In order of likelihood:

1. **Metro is advertising `127.0.0.1`** instead of your Wi-Fi IP. Check the
   `Metro waiting on …` line in Terminal 3. Stop, set
   `REACT_NATIVE_PACKAGER_HOSTNAME`, restart.
2. **Firewall blocks 8081.** Re-run the `New-NetFirewallRule` command in
   step 1a from an Admin PowerShell.
3. **VPN is rewriting the LAN.** Disconnect any VPN; try again.
4. **Phone and laptop are on different SSIDs.** Confirm both are on the same
   Wi-Fi network (2.4 GHz and 5 GHz on the same router count as the same
   network).

### "Couldn't reach host" / "NetworkError" on the bot-setup screen

The app can't reach the sidecar at 8787.

1. **Verify in Safari first**: `http://$LAPTOP_IP:8787/healthz`. If Safari
   can't reach it either, it's not an app problem.
2. **Sidecar is bound to 127.0.0.1, not 0.0.0.0.** Stop and restart Terminal
   2 with `--host 0.0.0.0`.
3. **Firewall blocks 8787.** Re-run the firewall command in step 1a.

### "permission denied for table bot_connections" after Test connection succeeds

The Supabase RLS policies didn't land. Re-run step 1b's SQL block. The
verification query should show `rowsecurity = true` and `policy_count = 1`
for both tables.

### "Project is incompatible with this version of Expo Go"

Your Expo Go app updated past the SDK this repo is on. Either:

- Update the repo: see the SDK 54 upgrade we did — bump `package.json` pins,
  `npm install`, then `npx expo install --fix`.
- Or downgrade Expo Go on the phone (only possible on Android; iOS App
  Store always serves the latest).

### `_ExpoSecureStore.default.getValueWithKeyAsync is not a function`

You're running on `npm run web`, not Expo Go on the phone. The web fallback
in [`app/src/lib/crypto.ts`](app/src/lib/crypto.ts) already handles this —
make sure the bundler refreshed (Ctrl+Shift+R in the browser).

---

## When LAN absolutely won't work — tunnel mode fallback

Different network at the phone and laptop? Corporate Wi-Fi with client
isolation? VPN you can't disable? Use Expo's tunnel through their cloud:

```powershell
cd C:\git\aribot-og\app
npx expo start --host tunnel
```

First time, it asks to install `@expo/ngrok` — say yes. The QR will point at
`tunnel.exp.direct` instead of your LAN IP. Slower (~2-3s page loads vs
instant on LAN), but works through anything.

**Caveat:** in tunnel mode, your phone reaches the *Metro bundler* through
the cloud, but it does **not** reach your sidecar at `8787` through the
cloud. You'd need to expose 8787 separately — easiest via Tailscale
(install on both phone and laptop, use the Tailscale hostname like
`http://your-laptop.tailnet:8787` in the bot-setup field).

---

## Stopping cleanly

- **Terminal 3 (Metro):** Ctrl+C.
- **Terminal 2 (sidecar):** Ctrl+C.
- **Terminal 1 (bot):** Ctrl+C *once*, then wait — the bot finishes its
  current cycle, persists state, and exits cleanly. Forcing it (Ctrl+C
  twice, or closing the window) can leave open positions un-reconciled in
  the local SQLite mirror. Not catastrophic, but the next startup will need
  to reconcile against Bybit.

To stop the bot from doing anything new without killing the process,
`type nul > kill_switch.flag` in the repo root. The bot detects that on the
next cycle, market-closes everything, and shuts down. The sidecar will then
report `status: killed` to the iOS app.

---

## Quick reference — the only things you'll need most days

```powershell
# Find your IP (it changes!)
(Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Wi-Fi').IPAddress

# In the iOS app, paste this in HOST URL (no trailing slash)
http://<that IP>:8787

# Health-check the sidecar from your phone's Safari before opening the app
http://<that IP>:8787/healthz
```

That's the whole game.

---

## Multi-tenant architecture (the model in use)

Every artifact a bot writes lives under one tenant directory:

```
<ARIBOT_ARTIFACT_DIR>/                # defaults to <repo>/.aribot
  meta.db                             # cross-tenant audit + run history (sidecar-only)
  host_keypair.json, tls_cert.pem     # operator-side identity
  tenants/<supabase-uuid>/
    usdt_bot_v2.{paper,shadow,live}.db   # per-tenant trade state
    bot.log, bot.launcher.log            # per-tenant logs
    bot.pid, status.json, kill_switch.flag
    config.json                          # per-tenant BOT_MODE, BYBIT_TESTNET
    observability.jsonl                  # per-tenant structured events
```

A second user's data lives under a different `tenants/<other-uuid>/`
subtree — different SQLite files, different log files, different
process. There is no shared writer.

**Auth.** Every endpoint requires a Supabase JWT. The `sub` claim
becomes the `user_id` everywhere downstream. `POST /credentials*` is
JWT-only — even a leaked legacy ops token cannot push or wipe a
tenant's keys.

**Sidecar restart safety.** On boot, the sidecar walks
`tenants/*/bot.pid`, validates each PID with psutil, and rebuilds its
in-memory running-bot registry. Stale pid files are unlinked.

**Required env** (in `.env`):

```
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_JWT_SECRET=…             # Supabase Dashboard → API → JWT Settings
ARIBOT_ARTIFACT_DIR=              # optional; defaults to <repo>/.aribot
```

Without these, the sidecar refuses to boot in multi-tenant mode and
exits with code 2.

---

## Legacy single-tenant mode (deprecated)

For ops emergencies during the multi-tenant migration window, the
sidecar can fall back to the original single-tenant behavior:

```powershell
# Operator-only fallback. Prints a deprecation warning.
cd C:\git\aribot-og; python status_server.py --host 0.0.0.0 --port 8787 --legacy-single-user
```

In this mode endpoints accept ONLY the legacy `ARIBOT_API_TOKEN` bearer
and operate on the original CWD-relative paths
(`usdt_bot_v2.{mode}.db`, `aribot_status.json`, `kill_switch.flag`,
`usdt_trading_log.txt`). The bot must be started in its own terminal as
in the pre-migration days:

```powershell
# Legacy three-terminal flow (deprecated; do not use for new deployments)
# Terminal 1 — bot
cd C:\git\aribot-og; python usdt_paper_bot_v2.py --symbols-file symbol_focus.example.json --emojis

# Terminal 2 — sidecar (legacy)
cd C:\git\aribot-og; python status_server.py --host 0.0.0.0 --port 8787 --legacy-single-user

# Terminal 3 — Metro
cd C:\git\aribot-og\app; npx expo start --host lan
```

**`--legacy-single-user` will be removed in a future release.** It exists
solely to give operators a safety valve during the cut-over. New
deployments should always use multi-tenant mode.

