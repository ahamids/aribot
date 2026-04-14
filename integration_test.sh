#!/usr/bin/env bash
set -euo pipefail

TMP_DIR="$(mktemp -d)"
cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

MEK="$(python -c 'import secrets; print(secrets.token_hex(32))')"
JWT_SECRET="$(python -c 'import secrets; print(secrets.token_hex(64))')"
DB_PATH="$TMP_DIR/shared.db"

cat > "$TMP_DIR/.env" <<EOF
ARIBOT_MEK=$MEK
ARIBOT_JWT_SECRET=$JWT_SECRET
ARIBOT_DB=$DB_PATH
ARIBOT_APP_NAME=test
EOF

set -a
source "$TMP_DIR/.env"
set +a

pip install -e . >/dev/null

cat > "$TMP_DIR/app.py" <<'PY'
from fastapi import FastAPI
from aribot_auth import create_auth_app

app = FastAPI()

@app.get('/health')
async def health():
    return {'ok': True}

create_auth_app(app)
PY

python -m uvicorn app:app --app-dir "$TMP_DIR" --host 127.0.0.1 --port 9999 >/dev/null 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 40); do
  if curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9999/health | grep -q '^200$'; then
    break
  fi
  sleep 0.25
done

assert_code() {
  local expected="$1"
  local actual="$2"
  if [[ "$actual" != "$expected" ]]; then
    echo "Assertion failed: expected $expected got $actual"
    exit 1
  fi
}

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:9999/auth/login -H 'content-type: application/json' -d '{"email":"x@x.com","password":"bad"}')
assert_code 401 "$code"

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:9999/admin/users -H 'content-type: application/json' -d '{"email":"x@x.com","password":"Password123!","role":"observer"}')
assert_code 401 "$code"

python - <<'PY'
import sqlite3, uuid, os
from datetime import datetime, timezone
from aribot_auth.password import hash_password

db = sqlite3.connect(os.environ['ARIBOT_DB'])
uid = str(uuid.uuid4())
now = datetime.now(timezone.utc).isoformat()
db.execute("INSERT INTO users (id,email,password_hash,role,mfa_enabled,active,created_at,failed_login_count) VALUES (?,?,?,?,1,1,?,0)", (uid, 'admin@test.local', hash_password('AdminPassword123!'), 'admin', now))
db.commit()
PY

LOGIN_JSON=$(curl -s -X POST http://127.0.0.1:9999/auth/login -H 'content-type: application/json' -d '{"email":"admin@test.local","password":"AdminPassword123!"}')
ACCESS_TOKEN=$(echo "$LOGIN_JSON" | jq -r '.access_token')
[[ "$ACCESS_TOKEN" != "null" ]]

ME_JSON=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" http://127.0.0.1:9999/auth/me)
[[ "$(echo "$ME_JSON" | jq -r '.email')" == "admin@test.local" ]]

echo "ALL ASSERTIONS PASSED"
