# Aribot Production Deployment Runbook

> Hetzner Cloud → Ubuntu 24.04 → Caddy + Let's Encrypt → multi-tenant
> sidecar via systemd → Backblaze B2 backups → UptimeRobot monitoring.
>
> This is the canonical doc for taking a blank Hetzner account to a
> production iOS-app-talks-to-prod-sidecar deployment in ~2 hours.
> Every step is copy-pasteable.

**Architecture**

```
                    Internet
                        │
                        ▼
              ┌────────────────────┐
              │ Cloudflare proxy   │  free tier; DDoS + WAF
              └────────┬───────────┘
                       │
                       ▼  (HTTPS, port 443)
              ┌────────────────────┐
              │ Hetzner CPX11 SG   │
              │                    │
              │  ┌──────────────┐  │
              │  │   Caddy      │  │  reverse proxy + LE cert
              │  └──────┬───────┘  │
              │         │ 127.0.0.1:8787 (HTTP)
              │  ┌──────▼───────┐  │
              │  │  Sidecar     │  │  systemd: aribot-sidecar.service
              │  │ (FastAPI)    │  │  user: aribot
              │  └──────┬───────┘  │
              │         │ Popen + IPC
              │  ┌──────▼───────────────┐
              │  │ Per-tenant bot       │  one Python process per
              │  │ subprocesses         │  active user_id
              │  │  (usdt_paper_bot_v2) │
              │  └──────────────────────┘
              │                    │
              │  /var/lib/aribot/.aribot/
              │     meta.db                ← cross-tenant audit
              │     tenants/<uuid>/        ← per-tenant SQLite + logs
              │                    │
              └────────────────────┘
                       │
                       ▼  (nightly cron)
              ┌────────────────────┐
              │ Backblaze B2       │  encrypted (gpg AES-256), 14-day retention
              └────────────────────┘
```

---

## Prerequisites — sign-up checklist

Complete every item BEFORE Phase 1. Capture URLs/keys/secrets in a
password manager (1Password, Bitwarden, KeePass — pick one). Never
in chat, repo, or plain text on disk.

### Hetzner Cloud
- Sign up: https://accounts.hetzner.com/signUp
- Verify email + phone, add payment method
- Create project: `aribot-prod`
- Generate Ed25519 SSH key on your Windows machine:

  ```powershell
  # PowerShell (Windows local)
  ssh-keygen -t ed25519 -C "aribot-deploy@$env:USERNAME" -f $env:USERPROFILE\.ssh\aribot_ed25519
  Get-Content $env:USERPROFILE\.ssh\aribot_ed25519.pub | clip
  ```

- In Hetzner Cloud Console → Security → SSH Keys → paste, name
  `aribot-deploy-windows`.

### Domain registration (Namecheap, Porkbun, etc.)
You picked a non-Cloudflare registrar. Steps:
1. Register a domain at your registrar of choice (~$10/yr `.com`).
2. Sign up at https://dash.cloudflare.com → **Add a Site** → enter
   your domain → choose **Free** plan.
3. Cloudflare lists two nameservers (e.g. `fred.ns.cloudflare.com`,
   `mary.ns.cloudflare.com`). **Capture them.**
4. In your registrar's control panel → DNS / Nameservers → switch from
   the registrar's default NS to the two Cloudflare NS values above.
5. Cloudflare emails you when the change propagates (usually 5-30 min,
   sometimes up to 24h). Confirm the zone goes "active" (green
   checkmark on the Cloudflare Overview page).

### Cloudflare account + zone
- Already created above.
- Note the Zone ID (Overview page, right column).
- Optional: API token scoped to `Zone:DNS:Edit` (Profile → API Tokens
  → Edit zone DNS template) for future automation. Manual edits work
  fine for now.

### Supabase production project
- https://supabase.com → New Project → name `aribot-prod`.
- Region: **Southeast Asia (Singapore)** (colocated with the Hetzner box).
- Database password: generate, save in password manager.
- Once provisioned, Project Settings → API:
  - Capture: Project URL (`https://<ref>.supabase.co`)
  - Capture: `anon` public key (used in the iOS app)
  - Capture: `service_role` key (treat as root credential — only
    needed if you add server-side admin endpoints later)
- Project Settings → API → JWT Settings:
  - Capture: JWT secret (HS256). This is what `status_server.py`
    validates tokens against in production.
- Recreate auth/RLS schema from your dev project. If you have
  migrations, run them. Otherwise dump dev schema with the Supabase
  CLI: `supabase db dump --schema public`, apply to prod.

### Backblaze B2
- Sign up: https://www.backblaze.com/sign-up/cloud-storage
- Create private bucket: `aribot-prod-backups` (region: any US — egress
  to Hetzner is free up to 3× stored data, plenty for restores).
- Generate Application Key:
  - Name: `aribot-prod-backup-write`
  - Allowed bucket: `aribot-prod-backups` (RESTRICT scope)
  - Capabilities: `listFiles, readFiles, shareFiles, writeFiles, deleteFiles`
- Capture: `keyID`, `applicationKey`, bucket name.
- Generate strong passphrase (32+ chars, password manager). Capture as
  `aribot-backup-gpg-passphrase`. **Losing this means losing backups.**

### Bybit testnet API
- https://testnet.bybit.com → register → API Management.
- Create key with Read + Trade permissions.
- IP-restrict to your Hetzner box's IPv4 (you'll have it after
  Phase 1; come back to add the restriction).
- Capture: API key, API secret. Used to validate end-to-end after
  the deploy completes.

### UptimeRobot
- https://uptimerobot.com → free account.
- (You'll add the monitor in Phase 5.)

---

## Phase 1 — Server provisioning + base hardening

**Goal:** CPX11 in Singapore, Ubuntu 24.04, locked-down SSH, UFW open
only on 22/80/443.

**Time:** ~30 min

In Hetzner Console → Servers → Add Server:
- Location: **Singapore (hil)**
- Image: **Ubuntu 24.04**
- Type: **CPX11**
- Networking: IPv4 + IPv6
- SSH Key: `aribot-deploy-windows`
- Name: `aribot-prod-sg-1`
- Create & Buy Now. **Capture the public IPv4.**

```powershell
# PowerShell (Windows local) — first SSH as root
ssh -i $env:USERPROFILE\.ssh\aribot_ed25519 root@{SERVER_IPV4}
```

On the server:

```bash
# bash (server)
set -euo pipefail

timedatectl set-timezone UTC
apt-get update && apt-get upgrade -y
apt-get install -y ufw fail2ban unattended-upgrades sudo curl ca-certificates

# Non-root admin user
adduser --disabled-password --gecos "" aribot-admin
usermod -aG sudo aribot-admin
echo "aribot-admin ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-aribot-admin
chmod 440 /etc/sudoers.d/90-aribot-admin
mkdir -p /home/aribot-admin/.ssh
cp /root/.ssh/authorized_keys /home/aribot-admin/.ssh/authorized_keys
chown -R aribot-admin:aribot-admin /home/aribot-admin/.ssh
chmod 700 /home/aribot-admin/.ssh
chmod 600 /home/aribot-admin/.ssh/authorized_keys

# Lock SSH down
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?KbdInteractiveAuthentication.*/KbdInteractiveAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

# Firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# fail2ban for SSH (default jail covers it)
systemctl enable --now fail2ban

# Security upgrades on autopilot
dpkg-reconfigure -f noninteractive unattended-upgrades
```

Exit, reconnect as the new user:

```powershell
# PowerShell — verify lockdown
ssh -i $env:USERPROFILE\.ssh\aribot_ed25519 aribot-admin@{SERVER_IPV4}
```

**Validate:**
- `ssh root@{SERVER_IPV4}` from PowerShell must FAIL with `Permission denied (publickey)`.
- `sudo ufw status verbose` shows 22, 80, 443 ALLOW; everything else deny.
- `sudo systemctl is-active fail2ban unattended-upgrades` returns `active` for both.

**Rollback:** Hetzner Console → Servers → `aribot-prod-sg-1` → Rescue, mount disk, restore `/etc/ssh/sshd_config.bak`. Or just delete the server (90s) and recreate.

> 🛑 **PAUSE for review.** Do not proceed to Phase 2 until validation passes.

---

## Phase 2 — App deployment (no public access yet)

**Goal:** Repo cloned to `/opt/aribot`, venv with deps, env file at `/etc/aribot/aribot.env`, sidecar foreground smoke-test on `127.0.0.1:8787`.

**Time:** ~20 min

**Prerequisite:** `main` on GitHub must be up to date — it contains the
multi-tenant migration AND the deploy/ artifacts.

```bash
# bash (server)
sudo apt-get install -y git
sudo bash <(curl -fsSL https://raw.githubusercontent.com/ahamids/aribot/main/deploy/install.sh)

# OR if you want to inspect first:
# sudo git clone --branch main https://github.com/ahamids/aribot.git /opt/aribot
# sudo bash /opt/aribot/deploy/install.sh
```

`install.sh` is idempotent. Re-run safely. It:
- installs Python 3.13 (deadsnakes; 3.12 fallback), git, build deps
- creates `aribot` system user + group
- clones the repo (or fetches if already cloned)
- creates the venv + installs `requirements-status-server.txt`
- creates `/var/lib/aribot/.aribot`, `/var/log/aribot`, `/etc/aribot`
- installs logrotate config
- does NOT start any service or write any secret

Hand-write the env file. Mode 640, owned `root:aribot` — root writes, the
aribot service user reads via group membership. systemd reads the file
as root before dropping privileges, but the manual smoke test and any
`sudo -u aribot` debugging needs group-read access.

```bash
# bash (server)
sudo install -m 640 -o root -g aribot \
    /opt/aribot/deploy/.env.production.example \
    /etc/aribot/aribot.env
sudo nano /etc/aribot/aribot.env
# Fill in:
#   SUPABASE_URL=https://<your-prod-ref>.supabase.co
#   SUPABASE_JWT_SECRET=<from Supabase Dashboard → API → JWT>
#   ARIBOT_API_TOKEN=<openssl rand -hex 32>
#   ARIBOT_ARTIFACT_DIR=/var/lib/aribot/.aribot
```

Smoke-test in foreground:

```bash
# bash (server) — terminal 1
sudo -u aribot bash -c '
  set -a; source /etc/aribot/aribot.env; set +a
  cd /opt/aribot
  /opt/aribot/.venv/bin/python status_server.py --host 127.0.0.1 --port 8787 --no-tls
'
```

```bash
# bash (server) — terminal 2 (second SSH)
curl -fsS http://127.0.0.1:8787/healthz
```

**Validate:** healthz returns `{"ok":true,...,"multiTenant":true}`. Sidecar logs show no traceback. Ctrl+C the foreground process before continuing.

**Rollback:** `sudo rm -rf /opt/aribot /var/lib/aribot /var/log/aribot /etc/aribot && sudo userdel aribot && sudo groupdel aribot`. Re-run `install.sh`.

> 🛑 **PAUSE for review.**

---

## Phase 3 — TLS + reverse proxy

**Goal:** `https://api.{YOUR_DOMAIN}/healthz` returns 200 from the open internet.

**Time:** ~25 min

In Cloudflare → DNS → Records → Add record:
- Type: A, Name: `api`, IPv4: `{SERVER_IPV4}`
- Proxy status: **DNS only (grey cloud)** ← important for Let's Encrypt's HTTP-01 challenge
- TTL: Auto

```bash
# bash (server) — install Caddy from the official repo
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update && sudo apt-get install -y caddy

# Drop the Caddyfile and the env vars it reads
sudo cp /opt/aribot/deploy/Caddyfile /etc/caddy/Caddyfile
sudo tee /etc/default/caddy >/dev/null <<EOF
SITE_ADDRESS=api.{YOUR_DOMAIN}
EMAIL={YOUR_EMAIL}
EOF

# Caddy needs its own log dir
sudo install -d -o caddy -g caddy -m 0755 /var/log/caddy

# CRITICAL: the apt-installed caddy.service does NOT load /etc/default/caddy
# by default. Install a systemd drop-in so the env vars above are visible
# to Caddy at startup.
sudo install -d -m 0755 /etc/systemd/system/caddy.service.d
sudo cp /opt/aribot/deploy/caddy-systemd-override.conf \
    /etc/systemd/system/caddy.service.d/override.conf
sudo systemctl daemon-reload

# Restart the sidecar in background for this test (Phase 4 makes it permanent)
sudo -u aribot bash -c '
  set -a; source /etc/aribot/aribot.env; set +a
  cd /opt/aribot
  nohup /opt/aribot/.venv/bin/python status_server.py \
    --host 127.0.0.1 --port 8787 --no-tls > /tmp/sidecar.log 2>&1 &
'

sudo systemctl restart caddy   # restart (not reload) so EnvironmentFile applies
```

Wait ~30 sec for cert issuance, then from your Windows machine:

```powershell
# PowerShell (Windows local)
curl.exe -fsS https://api.{YOUR_DOMAIN}/healthz
```

If 200 OK, flip Cloudflare proxy to **Proxied (orange cloud)**. Wait 60 sec, re-curl.

**Validate:**
- `curl https://api.{YOUR_DOMAIN}/healthz` returns 200 from outside.
- `curl -I https://api.{YOUR_DOMAIN}/healthz` shows `Strict-Transport-Security` and (after the proxy flip) `cf-ray` header.
- `sudo journalctl -u caddy -n 50` shows `certificate obtained successfully`.

**Rollback:** Cloudflare DNS back to grey cloud. `sudo systemctl stop caddy && sudo apt-get purge -y caddy`. Sidecar still on loopback — safe.

> 🛑 **PAUSE for review.**

---

## Phase 4 — systemd + autostart

**Goal:** Sidecar managed by systemd, restarts on crash, comes back after reboot.

**Time:** ~15 min

```bash
# bash (server)
# Stop the manual sidecar from Phase 3
sudo pkill -f 'status_server.py' || true

# Install the unit
sudo cp /opt/aribot/deploy/aribot-sidecar.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aribot-sidecar.service
sudo systemctl status aribot-sidecar.service --no-pager
```

Crash-recovery test:

```bash
# bash (server)
sudo pkill -9 -f 'status_server.py'
sleep 7
sudo systemctl status aribot-sidecar.service --no-pager  # expect: active (running)
curl -fsS http://127.0.0.1:8787/healthz
```

Reboot test:

```bash
# bash (server)
sudo systemctl reboot
```

Reconnect after ~60 sec:

```bash
# bash (server)
sudo systemctl is-active aribot-sidecar caddy
curl -fsS https://api.{YOUR_DOMAIN}/healthz
```

**Validate:** Both services `active`. Public HTTPS healthz returns 200. `journalctl -u aribot-sidecar -n 100` shows clean startup, no `Permission denied` from the systemd hardening.

**Rollback:** `sudo systemctl disable --now aribot-sidecar && sudo rm /etc/systemd/system/aribot-sidecar.service && sudo systemctl daemon-reload`. Phase 3 manual launch still works.

> 🛑 **PAUSE for review.**

---

## Phase 5 — Backups + monitoring

**Goal:** Nightly encrypted B2 backups with 14-day retention; UptimeRobot 5-min HTTPS check.

**Time:** ~30 min including restore drill

```bash
# bash (server) — install B2 CLI from the official binary
sudo curl -fsSL -o /usr/local/bin/b2 \
    https://github.com/Backblaze/B2_Command_Line_Tool/releases/latest/download/b2-linux
sudo chmod +x /usr/local/bin/b2

# Drop secrets into /etc/aribot/ (root-only)
sudo tee /etc/aribot/b2.env >/dev/null <<EOF
B2_APPLICATION_KEY_ID={KEY_ID}
B2_APPLICATION_KEY={APPLICATION_KEY}
B2_BUCKET=aribot-prod-backups
EOF
sudo chmod 600 /etc/aribot/b2.env

sudo tee /etc/aribot/backup-passphrase >/dev/null <<EOF
{GPG_PASSPHRASE}
EOF
sudo chmod 600 /etc/aribot/backup-passphrase

# Install the script
sudo install -m 750 -o root -g root /opt/aribot/deploy/backup.sh /usr/local/sbin/aribot-backup

# First run (manual)
sudo /usr/local/sbin/aribot-backup
echo "exit=$?"   # expect: exit=0

# Schedule nightly at 03:17 UTC (off-the-hour)
sudo tee /etc/cron.d/aribot-backup >/dev/null <<'EOF'
MAILTO=root
17 3 * * * root /usr/local/sbin/aribot-backup
EOF
sudo chmod 644 /etc/cron.d/aribot-backup
```

**Restore drill** (verifies the backup is actually restorable):

```bash
# bash (server)
sudo mkdir -p /tmp/restore-test && cd /tmp/restore-test
set -a; source /etc/aribot/b2.env; set +a
b2 account authorize "$B2_APPLICATION_KEY_ID" "$B2_APPLICATION_KEY"
LATEST=$(b2 ls --recursive "b2://$B2_BUCKET" | awk '{print $NF}' | grep -E '^aribot-backup-.*\.tar\.gz\.gpg$' | sort | tail -1)
sudo b2 file download "b2://$B2_BUCKET/$LATEST" backup.tar.gz.gpg
sudo gpg --batch --passphrase-file /etc/aribot/backup-passphrase --decrypt backup.tar.gz.gpg | tar -xz
sudo ls -la .aribot/
sudo rm -rf /tmp/restore-test
```

**UptimeRobot:** https://uptimerobot.com → New Monitor → HTTPS → URL `https://api.{YOUR_DOMAIN}/healthz` → 5-min interval → alert contact: your email.

**Validate:**
- `sudo /usr/local/sbin/aribot-backup` exits 0; B2 console shows the file.
- Restore drill reproduces a working `.aribot/` tree.
- UptimeRobot dashboard turns `Up` after first poll.

**Rollback:** `sudo rm /etc/cron.d/aribot-backup /usr/local/sbin/aribot-backup /etc/aribot/b2.env /etc/aribot/backup-passphrase`.

> 🛑 **PAUSE for review.**

---

## Phase 6 — Web frontend (aribot.app)

**Goal:** Next.js 16 web app at `https://aribot.app` (and `https://www.aribot.app` → redirect to apex). Same Hetzner box, separate systemd service alongside `aribot-sidecar`. Caddy handles both apex + api on shared TLS infrastructure.

**Time:** ~20 min (mostly the `npm ci` + `next build`)

**Prerequisite:** Phase 1-4 done. The sidecar at `api.aribot.app` should be live before bringing up the web app — Server Actions proxy to it.

```bash
# bash (server)

# 1. Hand-write the web env file. NEXT_PUBLIC_SUPABASE_URL must match
# SUPABASE_URL in /etc/aribot/aribot.env or the JWT the web app mints
# won't be accepted by the sidecar.
sudo install -m 640 -o root -g aribot \
    /opt/aribot/deploy/web.env.example \
    /etc/aribot/web.env
sudo nano /etc/aribot/web.env

# 2. Run the bootstrap script. Installs Node 22, adds 1GB swap, builds
# the standalone Next.js bundle, installs the systemd unit, starts it.
sudo bash /opt/aribot/deploy/install-web.sh

# 3. Reload Caddy so it picks up the new aribot.app block from the
# updated /etc/caddy/Caddyfile (committed in /opt/aribot/deploy/Caddyfile).
sudo cp /opt/aribot/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

In Cloudflare → DNS → Records → Add records:
- `A aribot.app` → `{SERVER_IPV4}` — **Proxied (orange cloud)**, TTL Auto
- `CNAME www.aribot.app` → `aribot.app` — **Proxied (orange cloud)**, TTL Auto

(Both can be orange-cloud from the start — Caddy already has a valid LE account from Phase 3, and the cert acquisition for new hostnames flows through the same account without needing grey-cloud.)

**Validate:**
- `sudo systemctl is-active aribot-web` returns `active`.
- `curl -fsS http://127.0.0.1:3000/` returns the landing HTML.
- `curl -fsS https://aribot.app/` returns 200 from your local machine.
- `curl -I https://aribot.app/` shows `Strict-Transport-Security` + `cf-ray`.
- `curl -I https://www.aribot.app/` shows `Location: https://aribot.app/` + 301.
- Visit `https://aribot.app` in a browser, sign in, verify the dashboard loads with backend data (proves Supabase JWT validation works across the prod domain).

**Rollback:** `sudo systemctl disable --now aribot-web && sudo rm /etc/systemd/system/aribot-web.service`. Revert the Caddyfile to the previous version (without the aribot.app block) and reload. Domain returns to "site not configured" on the LE check.

> 🛑 **PAUSE for review.**

---

## Pre-launch gate (open to public users)

Before changing the iOS app's `ARIBOT_BASE_URL` to `https://api.{YOUR_DOMAIN}`:

- [ ] All 5 phases complete; UptimeRobot green for 24+ hours.
- [ ] `https://api.{YOUR_DOMAIN}/healthz` returns 200 from cellular (not your home wifi).
- [ ] SSL Labs (https://www.ssllabs.com/ssltest/) → grade A or A+.
- [ ] Operator's own tenant (Bybit testnet keys) successfully placed at least one paper trade end-to-end through the prod sidecar.
- [ ] One full backup-and-restore cycle drilled. File counts and SQLite row counts match the live tree.
- [ ] `journalctl -u aribot-sidecar --since '24 hours ago' | grep -iE 'error|traceback|critical'` returns nothing alarming.
- [ ] `/etc/aribot/aribot.env` is mode 640, owned `root:aribot` (group-readable so the aribot service user can source it). `/etc/aribot/b2.env` and `/etc/aribot/backup-passphrase` stay mode 600, owned `root:root` (only root via cron needs them).
- [ ] `sudo ufw status` confirms only 22, 80, 443 are open.
- [ ] `sudo ss -tlnp | grep -v 127.0.0.1` confirms ONLY caddy and ssh listen on public interfaces; sidecar (`:8787`) and web (`:3000`) are loopback only.
- [ ] `https://aribot.app/` returns the landing in a fresh incognito window. Sign-up → email confirm → sign-in → dashboard works end-to-end on the prod domain.
- [ ] `aribot-web` survives a reboot (`sudo systemctl reboot`, wait 60s, `curl https://aribot.app/` returns 200).
- [ ] Supabase prod project's `auth.users` table has only the operator's account.
- [ ] B2 bucket contains 1+ encrypted backup; download + decrypt drill verified.
- [ ] Hetzner snapshot of the server taken (one-click; ~$0.011/GB/mo) — manual rollback insurance for the first week.
- [ ] Cloudflare WAF: Security level **Medium**, Bot Fight Mode **ON**, "Under Attack Mode" toggle bookmarked for incidents.
- [ ] Phone has SSH key access (Termius / Blink Shell with the Ed25519 key imported). For 3am pages.

---

## Day-2 operations

### Deploy a new backend version
```bash
# bash (server)
cd /opt/aribot
sudo -u aribot git fetch
sudo -u aribot git checkout {NEW_REF}
sudo -u aribot /opt/aribot/.venv/bin/pip install -r requirements-status-server.txt
sudo systemctl restart aribot-sidecar
sudo journalctl -u aribot-sidecar -f
```

### Deploy a new web version
```bash
# bash (server)
cd /opt/aribot
sudo -u aribot git fetch
sudo -u aribot git checkout {NEW_REF}
# Rebuild + restart in one shot via the install-web.sh script.
# It's idempotent: npm ci, next build (~3 min), copy static+public,
# restart aribot-web.service. ~4 min of downtime on the web app
# during the build (sidecar at api.aribot.app is unaffected).
sudo bash /opt/aribot/deploy/install-web.sh
```

### Tail logs
```bash
# Sidecar
sudo journalctl -u aribot-sidecar -f
sudo tail -f /var/log/aribot/sidecar.log

# Web frontend
sudo journalctl -u aribot-web -f
sudo tail -f /var/log/aribot/web.log

# A specific tenant's bot
sudo tail -f /var/lib/aribot/.aribot/tenants/<UUID>/bot.log

# Caddy (TLS / proxy errors)
sudo journalctl -u caddy -f
sudo tail -f /var/log/caddy/access.log
```

### Add a tenant
The iOS app handles this end-to-end: user signs in via Supabase, the
JWT they get back is what the sidecar uses as `user_id`. No server-side
manual step needed.

### Kill a stuck bot
```bash
sudo pgrep -af 'usdt_paper_bot_v2.py'   # find PID
sudo kill <PID>                          # graceful (waits for current cycle)
sudo kill -9 <PID>                       # last resort
```
The sidecar respawns the bot on the next user `/start` call.

### Rotate ARIBOT_API_TOKEN
```bash
sudo nano /etc/aribot/aribot.env   # change ARIBOT_API_TOKEN
sudo systemctl restart aribot-sidecar
# Update the iOS app's stored token (Settings → Connection)
```

### Force a backup right now
```bash
sudo /usr/local/sbin/aribot-backup
```

---

## Disaster recovery — restore from B2

Server gone, blank Hetzner box, need to restore:

```bash
# bash (new server, after Phase 1 hardening + Phase 2 install.sh)
set -a; source /etc/aribot/b2.env; set +a    # populate first per Phase 5
b2 account authorize "$B2_APPLICATION_KEY_ID" "$B2_APPLICATION_KEY"
LATEST=$(b2 ls --recursive "b2://$B2_BUCKET" | awk '{print $NF}' | grep -E '^aribot-backup-.*\.tar\.gz\.gpg$' | sort | tail -1)
sudo systemctl stop aribot-sidecar
sudo rm -rf /var/lib/aribot/.aribot
sudo b2 file download "b2://$B2_BUCKET/$LATEST" /tmp/restore.tar.gz.gpg
sudo gpg --batch --passphrase-file /etc/aribot/backup-passphrase \
    --decrypt /tmp/restore.tar.gz.gpg \
    | sudo tar -xz --directory=/var/lib/aribot
sudo chown -R aribot:aribot /var/lib/aribot/.aribot
sudo systemctl start aribot-sidecar
```

**Recovery point:** ≤24h (last nightly backup). **Recovery time:** ~30
min for a fresh Hetzner box + Phase 1-4 + restore. Document this RPO/RTO
for your own peace of mind.

---

## Cost (USD/month, approximate)

| Tenants | Hetzner | IPv4 | Domain | B2 | UptimeRobot | Cloudflare | Supabase | **Total** |
|---|---|---|---|---|---|---|---|---|
| 0-10 | $5.50 (CPX11) | $0.60 | $0.85 | $0.05 | Free | Free | Free | **~$7** |
| 50 | $9.00 (CPX21) | $0.60 | $0.85 | $0.20 | Free | Free | Free | **~$11** |
| 100 | $17.00 (CPX31) | $0.60 | $0.85 | $0.50 | Free | Free | $25 (Pro likely) | **~$44** |

CPX21 = 4 vCPU / 4 GB / 80 GB. CPX31 = 4 vCPU / 8 GB / 160 GB. Bumping
is a 60-second action in the Hetzner console. Plan to scale up when
sustained CPU > 60% or memory headroom < 300 MB.

---

## Troubleshooting

### Sidecar won't start
```bash
sudo journalctl -u aribot-sidecar -n 200 --no-pager
```
Common causes:
- `/etc/aribot/aribot.env` not readable (`Permission denied`) → `sudo chmod 600 /etc/aribot/aribot.env && sudo chown root:root /etc/aribot/aribot.env`
- Port 8787 in use (Phase 3 manual sidecar still running) → `sudo pkill -f status_server.py` then `sudo systemctl restart aribot-sidecar`
- venv corrupted (after a Python upgrade) → `sudo -u aribot rm -rf /opt/aribot/.venv && sudo bash /opt/aribot/deploy/install.sh`
- Missing SUPABASE_* env → sidecar exits with code 2 and a clear stderr line. Add the env vars or use `--legacy-single-user` (deprecated).

### Caddy can't get a Let's Encrypt cert
- Cloudflare proxy is ON (orange cloud) → flip to grey, wait 60s, `sudo systemctl reload caddy`. Once issued, you can flip back to orange.
- DNS not propagated yet → `dig api.{YOUR_DOMAIN}` should show your server IP.
- LE rate limit hit (5 failures/hour, 50 certs/week per domain) → wait it out; check `sudo journalctl -u caddy | grep -i 'rate limit'`.

### B2 upload failing
- Application key scope wrong → re-create with the exact capabilities listed in the prerequisites, restricted to this one bucket.
- Bucket name mismatch → confirm `B2_BUCKET` in `/etc/aribot/b2.env` matches exactly (case-sensitive).
- Quota / payment issue → check Backblaze account billing.

### `OS keyring is unreachable: No recommended backend was available`
The `keyring` Python package can't find a usable backend. On headless
Linux there's no desktop session for SecretService (gnome-keyring), so
we use `keyrings.alt`'s file-based backend. install.sh sets this up
automatically for new deploys. If you upgraded an old box, run on the
server:
```bash
sudo -u aribot /opt/aribot/.venv/bin/pip install --quiet 'keyrings.alt>=4'
sudo -u aribot mkdir -p /var/lib/aribot/.config/python_keyring /var/lib/aribot/.local/share/python_keyring
sudo -u aribot tee /var/lib/aribot/.config/python_keyring/keyringrc.cfg > /dev/null <<'EOF'
[backend]
default-keyring=keyrings.alt.file.PlaintextKeyring
EOF
```
Then ensure `/etc/aribot/aribot.env` contains:
```
XDG_CONFIG_HOME=/var/lib/aribot/.config
XDG_DATA_HOME=/var/lib/aribot/.local/share
```
The bot's X25519 secret lands at `/var/lib/aribot/.local/share/python_keyring/keyring_pass.cfg` (mode 600, aribot-owned). Backed up by `backup.sh`.

### iOS app can't connect after deploy
- Wrong base URL → must be `https://api.{YOUR_DOMAIN}` (no trailing slash, with HTTPS).
- JWT issuer mismatch → app must be signed in to the SAME Supabase project whose JWT secret you put in `/etc/aribot/aribot.env`. Dev project's JWT will fail validation against prod's secret.
- Cert pinning in the app → if the iOS app pins the dev self-signed cert, it will reject Caddy's Let's Encrypt cert. Ship a build that uses the system trust store for prod (or a separate prod build flavor).

---

## Out of scope (intentional follow-ups)

These do not block production launch:

- Multi-region failover
- CI/CD on push to main (manual `git pull && systemctl restart` is correct at this scale)
- Centralized log aggregation (Loki/Grafana)
- Prometheus metrics
- L7 DDoS protection beyond Cloudflare free tier
- Postgres migration (defer until SQLite hits limits — single tenant > 5 GB or visible write contention)
- TOTP MFA on `/credentials` (Aribot-internal feature; tracked separately)

---

## File reference

| File | Purpose |
|---|---|
| `deploy/install.sh` | Idempotent Ubuntu 24.04 bootstrap (sidecar) |
| `deploy/install-web.sh` | Node 22 + swap + npm ci + next build + systemd unit (web frontend) |
| `deploy/Caddyfile` | Reverse proxy: api.aribot.app + aribot.app + www redirect |
| `deploy/caddy-systemd-override.conf` | systemd drop-in that loads /etc/default/caddy (the apt unit doesn't by default) |
| `deploy/aribot-sidecar.service` | systemd unit for the multi-tenant sidecar (FastAPI on :8787) |
| `deploy/aribot-web.service` | systemd unit for the Next.js frontend (on :3000) |
| `deploy/aribot.service` | **Deprecated** — legacy single-tenant systemd unit (pre-migration) |
| `deploy/backup.sh` | Streamed encrypted backup → B2 |
| `deploy/.env.production.example` | Sidecar env template |
| `deploy/web.env.example` | Web env template (NEXT_PUBLIC_* baked at build time) |
| `deploy/register_telegram_commands.py` | Telegram bot setMyCommands utility (operational, not deploy-critical) |
