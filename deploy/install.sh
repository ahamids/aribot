#!/usr/bin/env bash
# =====================================================================
# Aribot production bootstrap script
#
# Idempotent. Safe to re-run. Does NOT start any service or write any
# secret — those are explicit operator steps documented in deploy/README.md.
#
# Usage (run from anywhere on the server):
#   sudo bash /path/to/aribot-og/deploy/install.sh [--repo-url URL] [--ref REF]
#
# Defaults:
#   --repo-url   https://github.com/ahamids/aribot.git
#   --ref        chore/deploy-artifacts   (has both the multi-tenant
#                                          migration AND the deploy/
#                                          artifacts — install.sh, Caddyfile,
#                                          systemd unit, backup.sh, README.
#                                          Switch to `main` once both
#                                          branches are merged.)
#
# After this finishes, see the "next steps" block it prints.
# =====================================================================
set -euo pipefail

# ─── Args ────────────────────────────────────────────────────────────
REPO_URL="https://github.com/ahamids/aribot.git"
REPO_REF="chore/deploy-artifacts"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo-url) REPO_URL="$2"; shift 2 ;;
        --ref)      REPO_REF="$2"; shift 2 ;;
        *) echo "unknown arg: $1" >&2; exit 64 ;;
    esac
done

# ─── Preconditions ───────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (use sudo)." >&2
    exit 1
fi

# Detect Ubuntu version. We support 24.04 LTS only at this time. The
# install patterns (deadsnakes PPA, package names, Caddy repo) assume
# this exact target.
if [[ ! -r /etc/os-release ]]; then
    echo "Cannot read /etc/os-release; refusing to proceed on unknown OS." >&2
    exit 1
fi
. /etc/os-release
if [[ "${ID:-}" != "ubuntu" ]]; then
    echo "ERROR: this script supports Ubuntu only (saw ID=${ID:-?})." >&2
    exit 1
fi
if [[ "${VERSION_ID:-}" != "24.04" ]]; then
    echo "ERROR: this script targets Ubuntu 24.04 (saw VERSION_ID=${VERSION_ID:-?})." >&2
    exit 1
fi

log()  { echo "[install.sh] $*"; }
warn() { echo "[install.sh] WARNING: $*" >&2; }

# ─── Phase 1: base packages ──────────────────────────────────────────
log "apt-get update + install base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    git curl ca-certificates gnupg \
    ufw fail2ban unattended-upgrades \
    build-essential libssl-dev libffi-dev \
    sqlite3 \
    software-properties-common

# ─── Phase 2: Python 3.13 (deadsnakes) with 3.12 fallback ────────────
PY_BIN=""
log "attempting Python 3.13 install via deadsnakes PPA"
if add-apt-repository -y ppa:deadsnakes/ppa >/dev/null 2>&1 && apt-get update -qq; then
    if apt-get install -y -qq python3.13 python3.13-venv python3.13-dev 2>/dev/null; then
        PY_BIN="$(command -v python3.13 || true)"
    fi
fi

if [[ -z "${PY_BIN}" ]]; then
    warn "deadsnakes 3.13 unavailable; falling back to system Python 3.12"
    apt-get install -y -qq python3.12 python3.12-venv python3.12-dev
    PY_BIN="$(command -v python3.12 || true)"
fi

if [[ -z "${PY_BIN}" ]]; then
    echo "ERROR: could not install Python 3.13 OR 3.12. Check apt errors above." >&2
    exit 1
fi
log "using Python at: ${PY_BIN}"

# ─── Phase 3: aribot user + group ────────────────────────────────────
if ! getent group aribot >/dev/null; then
    log "creating system group: aribot"
    groupadd --system aribot
fi
if ! id -u aribot >/dev/null 2>&1; then
    log "creating system user: aribot"
    useradd --system --gid aribot --home-dir /opt/aribot \
            --shell /usr/sbin/nologin aribot
fi

# ─── Phase 4: clone or fetch the repo ────────────────────────────────
if [[ ! -d /opt/aribot/.git ]]; then
    log "cloning ${REPO_URL} (${REPO_REF}) to /opt/aribot"
    git clone --branch "${REPO_REF}" "${REPO_URL}" /opt/aribot
else
    log "/opt/aribot already cloned; fetching latest refs"
    git -C /opt/aribot fetch --all --prune
    log "  current HEAD: $(git -C /opt/aribot rev-parse --short HEAD)"
    log "  to update: cd /opt/aribot && sudo -u aribot git checkout <ref>"
fi
chown -R aribot:aribot /opt/aribot

# ─── Phase 5: venv + Python deps ─────────────────────────────────────
if [[ ! -d /opt/aribot/.venv ]]; then
    log "creating venv at /opt/aribot/.venv"
    sudo -u aribot "${PY_BIN}" -m venv /opt/aribot/.venv
fi
log "upgrading pip + installing requirements-status-server.txt"
sudo -u aribot /opt/aribot/.venv/bin/pip install --quiet --upgrade pip wheel
sudo -u aribot /opt/aribot/.venv/bin/pip install --quiet -r /opt/aribot/requirements-status-server.txt

# Bot-runtime deps. The bot runs as a subprocess of the sidecar; it shares
# the venv. requirements.txt is the canonical bot deps file (if absent,
# the bot installs lazily — but pre-install is safer for production).
if [[ -f /opt/aribot/requirements.txt ]]; then
    log "installing requirements.txt (bot runtime deps)"
    sudo -u aribot /opt/aribot/.venv/bin/pip install --quiet -r /opt/aribot/requirements.txt
else
    warn "requirements.txt not found; bot may need additional deps installed at first run"
fi

# ─── Phase 6: directories + perms ────────────────────────────────────
log "creating /var/lib/aribot/.aribot (artifact dir) and /var/log/aribot"
install -d -o aribot -g aribot -m 0750 /var/lib/aribot
install -d -o aribot -g aribot -m 0750 /var/lib/aribot/.aribot
install -d -o aribot -g aribot -m 0750 /var/log/aribot

# Caddy log dir is created in Phase 3 of the runbook (after caddy is
# installed) — it needs to be owned by caddy:caddy, not aribot:aribot.

# ─── Phase 6b: headless-Linux keyring backend ────────────────────────
# Python `keyring` has no usable backend on a headless Linux server
# (SecretService needs a desktop session that doesn't exist here).
# We point keyring at keyrings.alt's PlaintextKeyring, stored under the
# artifact dir's XDG_DATA_HOME (file mode 600, aribot-only). Backups
# pick this up automatically since it's inside /var/lib/aribot/.
# Threat model: equivalent to OS keyring on a server — neither protects
# against root or disk-image theft; both rely on file perms.
log "configuring file-backed Python keyring for the aribot service user"
install -d -o aribot -g aribot -m 0750 /var/lib/aribot/.config
install -d -o aribot -g aribot -m 0750 /var/lib/aribot/.config/python_keyring
install -d -o aribot -g aribot -m 0750 /var/lib/aribot/.local
install -d -o aribot -g aribot -m 0750 /var/lib/aribot/.local/share
install -d -o aribot -g aribot -m 0750 /var/lib/aribot/.local/share/python_keyring
if [[ ! -f /var/lib/aribot/.config/python_keyring/keyringrc.cfg ]]; then
    cat > /var/lib/aribot/.config/python_keyring/keyringrc.cfg <<'EOF'
[backend]
default-keyring=keyrings.alt.file.PlaintextKeyring
EOF
    chown aribot:aribot /var/lib/aribot/.config/python_keyring/keyringrc.cfg
    chmod 0640 /var/lib/aribot/.config/python_keyring/keyringrc.cfg
fi

# ─── Phase 7: /etc/aribot config dir ─────────────────────────────────
install -d -o root -g root -m 0755 /etc/aribot

# ─── Phase 8: logrotate ──────────────────────────────────────────────
log "installing logrotate config for /var/log/aribot"
cat > /etc/logrotate.d/aribot <<'EOF'
/var/log/aribot/*.log {
    weekly
    rotate 8
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    su aribot aribot
}
EOF

# ─── Done ────────────────────────────────────────────────────────────
cat <<EOF

╔═══════════════════════════════════════════════════════════════════════╗
║  install.sh finished. Phase 2 of deploy/README.md complete.           ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                       ║
║  NEXT STEPS (operator):                                               ║
║                                                                       ║
║  1. Copy the env template and fill in production secrets:             ║
║       sudo install -m 600 -o root -g root \\                          ║
║         /opt/aribot/deploy/.env.production.example \\                 ║
║         /etc/aribot/aribot.env                                        ║
║       sudo nano /etc/aribot/aribot.env                                ║
║                                                                       ║
║  2. Smoke-test the sidecar in the foreground (Ctrl+C to stop):        ║
║       sudo -u aribot bash -c '                                        ║
║         set -a; source /etc/aribot/aribot.env; set +a                 ║
║         cd /opt/aribot                                                ║
║         /opt/aribot/.venv/bin/python status_server.py \\              ║
║           --host 127.0.0.1 --port 8787 --no-tls'                      ║
║     In another shell: curl -fsS http://127.0.0.1:8787/healthz         ║
║                                                                       ║
║  3. Proceed to Phase 3 (Caddy + TLS) per deploy/README.md.            ║
║                                                                       ║
╚═══════════════════════════════════════════════════════════════════════╝

EOF
