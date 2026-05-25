#!/usr/bin/env bash
# =====================================================================
# Aribot nightly backup
#
# Streams: tar(artifact_dir) | gzip | gpg(symmetric AES-256) | b2 upload
# Never writes a plaintext temp file. Cleans up gpg-encrypted staging
# file after upload.
#
# Usage (typically from cron, run as root):
#   /usr/local/sbin/aribot-backup
#
# Reads:
#   /etc/aribot/b2.env                  B2_APPLICATION_KEY_ID,
#                                       B2_APPLICATION_KEY, B2_BUCKET
#   /etc/aribot/backup-passphrase       single-line GPG passphrase, mode 600
#
# Writes:
#   /var/log/aribot/backup.log          one-line success entry per run
#   B2 bucket                           aribot-backup-<UTC-timestamp>.tar.gz.gpg
#
# Retention: keep newest 14 backups in B2; prune older.
#
# Cron entry (mailto root for failure alerts):
#   /etc/cron.d/aribot-backup:
#     MAILTO=root
#     17 3 * * * root /usr/local/sbin/aribot-backup
# =====================================================================
set -euo pipefail

ARTIFACT_DIR="/var/lib/aribot/.aribot"
LOG_FILE="/var/log/aribot/backup.log"
B2_ENV="/etc/aribot/b2.env"
PASSPHRASE_FILE="/etc/aribot/backup-passphrase"
RETAIN=14
STAGING_DIR="/var/lib/aribot/.aribot-backup-stage"  # ReadWritePath in case sidecar unit grants access; root-only here

log() {
    local msg="$1"
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$msg" | tee -a "$LOG_FILE" >&2
}
fail() {
    log "ERROR: $1"
    exit 1
}

# ─── Preconditions ───────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || fail "must run as root"
[[ -d "$ARTIFACT_DIR" ]] || fail "artifact dir missing: $ARTIFACT_DIR"
[[ -r "$B2_ENV" ]]       || fail "B2 env file missing or unreadable: $B2_ENV"
[[ -r "$PASSPHRASE_FILE" ]] || fail "passphrase file missing or unreadable: $PASSPHRASE_FILE"
command -v b2  >/dev/null || fail "b2 CLI not on PATH"
command -v gpg >/dev/null || fail "gpg not on PATH"
command -v tar >/dev/null || fail "tar not on PATH"

# Tighten passphrase file mode if loose.
chmod 600 "$PASSPHRASE_FILE"

# Source B2 creds. Don't export to subshells we don't control.
# shellcheck disable=SC1090
. "$B2_ENV"
: "${B2_APPLICATION_KEY_ID:?B2_APPLICATION_KEY_ID missing in $B2_ENV}"
: "${B2_APPLICATION_KEY:?B2_APPLICATION_KEY missing in $B2_ENV}"
: "${B2_BUCKET:?B2_BUCKET missing in $B2_ENV}"

mkdir -p "$STAGING_DIR"
chmod 700 "$STAGING_DIR"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="aribot-backup-${STAMP}.tar.gz.gpg"
STAGED="${STAGING_DIR}/${NAME}"

# ─── B2 authorize (idempotent; cached in /root/.b2_account_info) ─────
log "authorizing B2 account"
b2 account authorize "$B2_APPLICATION_KEY_ID" "$B2_APPLICATION_KEY" >/dev/null \
    || fail "b2 authorize failed"

# ─── Stream tar | gzip | gpg → encrypted staging file ────────────────
# Excludes:
#   *-wal, *-shm   transient SQLite WAL files (re-derived on next open)
#   *.tmp          partial atomic writes
log "creating ${NAME} from ${ARTIFACT_DIR}"
if ! tar --create --gzip \
        --exclude='*-wal' \
        --exclude='*-shm' \
        --exclude='*.tmp' \
        --directory="$(dirname "$ARTIFACT_DIR")" \
        "$(basename "$ARTIFACT_DIR")" \
    | gpg --batch --yes --quiet \
          --symmetric --cipher-algo AES256 \
          --passphrase-file "$PASSPHRASE_FILE" \
          --output "$STAGED"; then
    rm -f "$STAGED"
    fail "tar | gpg pipeline failed"
fi

SIZE_BYTES=$(stat -c '%s' "$STAGED")
log "staged ${NAME} (${SIZE_BYTES} bytes)"

# ─── Upload ──────────────────────────────────────────────────────────
log "uploading ${NAME} to b2://${B2_BUCKET}/"
if ! b2 file upload "$B2_BUCKET" "$STAGED" "$NAME" >/dev/null; then
    rm -f "$STAGED"
    fail "b2 upload failed"
fi

rm -f "$STAGED"
log "uploaded ${NAME}"

# ─── Prune old backups (keep newest $RETAIN) ─────────────────────────
# Note on b2 CLI versioning: v4+ requires bucket arguments as b2:// URIs.
# Passing a bare bucket name silently returns 0 results (the CLI errors
# to stderr but the awk/grep pipeline still exits 0), so old backups
# would never be pruned. Always use the b2:// form.
log "pruning old backups (retain=${RETAIN})"
mapfile -t ALL < <(b2 ls --recursive "b2://${B2_BUCKET}" | awk '{print $NF}' | grep -E '^aribot-backup-.*\.tar\.gz\.gpg$' | sort)
TOTAL=${#ALL[@]}
if (( TOTAL > RETAIN )); then
    PRUNE_COUNT=$(( TOTAL - RETAIN ))
    for victim in "${ALL[@]:0:PRUNE_COUNT}"; do
        log "  deleting ${victim}"
        b2 file delete "b2://${B2_BUCKET}/${victim}" >/dev/null \
            || log "  WARN: delete failed for ${victim}"
    done
fi

REMAIN=$(( TOTAL > RETAIN ? RETAIN : TOTAL ))
log "SUCCESS file=${NAME} size=${SIZE_BYTES}B remaining=${REMAIN}"
