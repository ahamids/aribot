#!/usr/bin/env bash
# =====================================================================
# Aribot web frontend bootstrap (Phase 6 of deploy/README.md).
#
# Prerequisites:
#   - Phase 1-4 of deploy/README.md complete (Hetzner CPX11 hardened,
#     sidecar running on 127.0.0.1:8787, Caddy serving api.aribot.app)
#   - /etc/aribot/web.env populated with NEXT_PUBLIC_SUPABASE_URL +
#     NEXT_PUBLIC_SUPABASE_ANON_KEY (see deploy/web.env.example)
#
# Idempotent. Safe to re-run for deploys.
# =====================================================================
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (use sudo)." >&2
    exit 1
fi

WEB_DIR=/opt/aribot/web
WEB_ENV=/etc/aribot/web.env
SWAP_FILE=/swapfile
SWAP_SIZE=1G

log()  { echo "[install-web.sh] $*"; }
warn() { echo "[install-web.sh] WARNING: $*" >&2; }

# ─── 1. Swap (CPX11 has 2GB RAM; next build peaks above 1.2GB) ──────
if ! swapon --show | grep -q "$SWAP_FILE"; then
    if [[ ! -f $SWAP_FILE ]]; then
        log "creating ${SWAP_SIZE} swap file at ${SWAP_FILE}"
        fallocate -l ${SWAP_SIZE} $SWAP_FILE
        chmod 600 $SWAP_FILE
        mkswap $SWAP_FILE
    fi
    swapon $SWAP_FILE
    if ! grep -q "^$SWAP_FILE" /etc/fstab; then
        echo "$SWAP_FILE none swap sw 0 0" >> /etc/fstab
        log "swap added to /etc/fstab"
    fi
else
    log "swap already active"
fi

# ─── 2. Node.js 22 LTS via NodeSource ───────────────────────────────
if ! command -v node >/dev/null || [[ "$(node --version | sed 's/v//;s/\..*//')" -lt 22 ]]; then
    log "installing Node.js 22"
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y -qq nodejs
fi
log "node:    $(node --version)"
log "npm:     $(npm --version)"

# ─── 3. Web env file must exist ─────────────────────────────────────
if [[ ! -f $WEB_ENV ]]; then
    log "ERROR: ${WEB_ENV} does not exist."
    log "Create it from /opt/aribot/deploy/web.env.example before re-running:"
    log "  sudo install -m 640 -o root -g aribot /opt/aribot/deploy/web.env.example ${WEB_ENV}"
    log "  sudo nano ${WEB_ENV}"
    exit 1
fi
log "web env file present: ${WEB_ENV}"

# ─── 4. Install deps + build (as the aribot user; same as the runtime) ─
if [[ ! -d $WEB_DIR ]]; then
    log "ERROR: ${WEB_DIR} not present. Re-run install.sh first."
    exit 1
fi

log "npm ci in ${WEB_DIR}"
sudo -u aribot bash -c "cd $WEB_DIR && npm ci --no-audit --no-fund"

# next build reads NEXT_PUBLIC_* from env. Source web.env so the build
# bakes the right Supabase URL/anon key into the browser bundle.
log "building Next.js for production"
sudo -u aribot bash -c "
    set -a
    source $WEB_ENV
    set +a
    cd $WEB_DIR
    NODE_OPTIONS='--max-old-space-size=1024' npm run build
"

# Standalone build needs static + public copied in for the server to find
# them. Next.js does NOT do this automatically.
log "copying static + public into .next/standalone"
sudo -u aribot bash -c "
    cd $WEB_DIR
    rm -rf .next/standalone/.next/static .next/standalone/public
    cp -r .next/static .next/standalone/.next/
    if [[ -d public ]]; then cp -r public .next/standalone/; fi
"

# Cache dir that the systemd unit will need to be writable.
sudo -u aribot mkdir -p $WEB_DIR/.next/cache

# ─── 5. systemd unit ────────────────────────────────────────────────
log "installing systemd unit for aribot-web"
install -m 0644 /opt/aribot/deploy/aribot-web.service /etc/systemd/system/aribot-web.service
systemctl daemon-reload
systemctl enable aribot-web.service

if systemctl is-active --quiet aribot-web.service; then
    log "restarting existing aribot-web service"
    systemctl restart aribot-web.service
else
    log "starting aribot-web service for the first time"
    systemctl start aribot-web.service
fi

sleep 2
if ! systemctl is-active --quiet aribot-web.service; then
    log "ERROR: aribot-web failed to start. Recent journal:"
    journalctl -u aribot-web -n 30 --no-pager
    exit 1
fi
log "aribot-web is active"

# ─── 6. Smoke test against loopback ─────────────────────────────────
log "smoke test: curl http://127.0.0.1:3000/"
if ! curl -fsS -o /dev/null -w "  HTTP %{http_code}\n" http://127.0.0.1:3000/; then
    log "ERROR: web app not responding on 127.0.0.1:3000"
    journalctl -u aribot-web -n 50 --no-pager
    exit 1
fi

cat <<EOF

╔═══════════════════════════════════════════════════════════════════════╗
║  install-web.sh finished. Phase 6 done.                               ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                       ║
║  NEXT STEPS:                                                          ║
║                                                                       ║
║  1. Add DNS records in Cloudflare:                                    ║
║       A     aribot.app       46.62.158.233   (proxied / orange)       ║
║       CNAME www.aribot.app   aribot.app      (proxied / orange)       ║
║                                                                       ║
║  2. Reload Caddy so it picks up the new aribot.app block:             ║
║       sudo systemctl reload caddy                                     ║
║                                                                       ║
║  3. Verify from outside (Let's Encrypt takes ~30s on first cert):     ║
║       curl -fsS https://aribot.app/                                   ║
║                                                                       ║
╚═══════════════════════════════════════════════════════════════════════╝

EOF
