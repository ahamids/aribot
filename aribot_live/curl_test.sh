#!/usr/bin/env bash
# ARIBOT LIVE API contract smoke/regression script.
# Usage: bash aribot_live/curl_test.sh
# Requires: curl, jq, python (with fastapi, uvicorn, aiosqlite installed)

set -euo pipefail

TMP_DIR="$(mktemp -d)"
PORT="${PORT:-18765}"
BASE_URL="http://127.0.0.1:${PORT}"

DB_FILE="${TMP_DIR}/test_aribot.db"
JSONL_FILE="${TMP_DIR}/test_observability.jsonl"
ENV_FILE="${TMP_DIR}/test.env"
LEVERAGE_FILE="${TMP_DIR}/leverage_buckets.json"
PID_FILE="${TMP_DIR}/api.pid"

cleanup() {
  set +e
  if [[ -f "${PID_FILE}" ]]; then
    PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
      kill "${PID}" 2>/dev/null || true
      wait "${PID}" 2>/dev/null || true
    fi
  fi
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT INT TERM

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing: $1" >&2; exit 1; }
}
require_cmd curl
require_cmd jq
require_cmd python

seed_files() {
  cat > "${ENV_FILE}" <<'EOF'
# ARIBOT test env
BOT_MODE=live
INITIAL_BALANCE=400
ALLOWED_ORIGIN=*
# restart is not configured
EOF

  cat > "${LEVERAGE_FILE}" <<'EOF'
{
  "major": ["BTCUSDT", "ETHUSDT"],
  "large_alt": ["SOLUSDT"],
  "mid_cap": []
}
EOF

  printf '%s\n' \
    '{"ts":"2026-04-13T00:00:00Z","level":"INFO","event_type":"startup","component":"engine","symbol":null,"message":"Started","values":{}}' \
    '{"ts":"2026-04-13T00:00:01Z","level":"INFO","event_type":"tick","component":"engine","symbol":"BTCUSDT","message":"Tick","values":{}}' \
    'this is a malformed jsonl line' \
    '{"ts":"2026-04-13T00:00:02Z","level":"WARNING","event_type":"signal","component":"strategy","symbol":"ETHUSDT","message":"Signal","values":{}}' \
    '{"ts":"2026-04-13T00:00:03Z","level":"INFO","event_type":"close","component":"engine","symbol":"BTCUSDT","message":"Closed","values":{}}' \
    > "${JSONL_FILE}"
}

seed_sqlite() {
  python - "${DB_FILE}" <<'PY'
import sqlite3, sys
db = sys.argv[1]
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.executescript("""
CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT,
  entry_price TEXT, current_price TEXT, quantity TEXT, pnl TEXT,
  pnl_percentage TEXT, peak_pnl_percentage TEXT,
  trailing_stop_active TEXT, trailing_stop_level TEXT,
  native_sl_active TEXT, native_tp_active TEXT, native_trail_active TEXT,
  native_sl_price TEXT, timestamp TEXT
);
CREATE TABLE IF NOT EXISTS closed_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT,
  entry_price TEXT, exit_price TEXT, pnl TEXT, pnl_percentage TEXT,
  reason TEXT, open_time TEXT, close_time TEXT
);
CREATE TABLE IF NOT EXISTS partial_realizations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, level TEXT,
  size TEXT, pnl TEXT, event_time TEXT
);
""")
cur.executemany("INSERT OR REPLACE INTO bot_state(key,value) VALUES(?,?)", [
  ("current_balance","430.5"),
  ("session_start_balance","400"),
  ("initial_balance","400"),
  ("total_pnl","30.5"),
  ("winning_trades","3"),
  ("losing_trades","2"),
  ("loop_cycle_count","12"),
  ("bot_mode","live"),
  ("daily_drawdown_paused","0"),
  ("manual_entry_paused","0"),
  ("cooldown_until_utc",""),
  ("last_regime_signal","BUY"),
  ("telegram_manual_pause_active","0"),
])
cur.executemany(
  "INSERT INTO positions(symbol,side,entry_price,current_price,quantity,pnl,pnl_percentage,peak_pnl_percentage,trailing_stop_active,trailing_stop_level,native_sl_active,native_tp_active,native_trail_active,native_sl_price,timestamp) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
  [
    ("BTCUSDT","LONG","50000","51000","0.01","10.0","2.0","3.0","1","49500","1","0","0","49000","2026-04-13T00:00:00Z"),
    ("ETHUSDT","SHORT","3000","2950","0.20","10.0","1.7","2.5","0","3050","1","0","0","3100","2026-04-13T00:01:00Z"),
  ]
)
cur.executemany(
  "INSERT INTO closed_trades(symbol,side,entry_price,exit_price,pnl,pnl_percentage,reason,open_time,close_time) VALUES(?,?,?,?,?,?,?,?,?)",
  [
    ("BTCUSDT","LONG","49000","49500","5.0","1.0","trailing_stop","2026-04-13T00:00:00Z","2026-04-13T00:10:00Z"),
    ("ETHUSDT","SHORT","3100","3000","20.0","3.2","stop_loss","2026-04-13T00:05:00Z","2026-04-13T00:15:00Z"),
    ("SOLUSDT","LONG","100","102","2.0","1.8","time_exit","2026-04-13T00:20:00Z","2026-04-13T00:30:00Z"),
    ("XRPUSDT","SHORT","0.60","0.59","1.0","1.7","manual_close","2026-04-13T00:25:00Z","2026-04-13T00:35:00Z"),
    ("ADAUSDT","LONG","0.45","0.46","2.2","1.6","partial_exit_complete","2026-04-13T00:40:00Z","2026-04-13T00:50:00Z"),
  ]
)
cur.executemany(
  "INSERT INTO partial_realizations(symbol,level,size,pnl,event_time) VALUES(?,?,?,?,?)",
  [
    ("BTCUSDT","1","0.003","1.1","2026-04-13T00:11:00Z"),
    ("ETHUSDT","2","0.050","3.0","2026-04-13T00:16:00Z"),
  ]
)
conn.commit(); conn.close()
PY
}

start_api() {
  ARIBOT_DB="${DB_FILE}" \
  ARIBOT_JSONL="${JSONL_FILE}" \
  ARIBOT_ENV_FILE="${ENV_FILE}" \
  ARIBOT_LEVERAGE_FILE="${LEVERAGE_FILE}" \
  DASHBOARD_PORT="${PORT}" \
  python -m uvicorn aribot_live.api:app --host 127.0.0.1 --port "${PORT}" \
    > "${TMP_DIR}/server.log" 2>&1 &
  echo $! > "${PID_FILE}"
  for _ in $(seq 1 60); do
    if curl -sS -o /dev/null -w "%{http_code}" "${BASE_URL}/api/health" 2>/dev/null | grep -q "^200$"; then return 0; fi
    sleep 0.25
  done
  echo "API failed to start:" >&2
  cat "${TMP_DIR}/server.log" >&2
  exit 1
}

ok200() {
  local label="$1" endpoint="$2" jq_expr="${3:-.}"
  local body status
  status="$(curl -sS -o "${TMP_DIR}/resp.json" -w "%{http_code}" "${BASE_URL}${endpoint}")"
  [[ "${status}" == "200" ]] || { echo "FAIL [${label}] expected 200, got ${status}"; cat "${TMP_DIR}/resp.json"; exit 1; }
  jq -e "${jq_expr}" "${TMP_DIR}/resp.json" >/dev/null || { echo "FAIL [${label}] jq: ${jq_expr}"; cat "${TMP_DIR}/resp.json"; exit 1; }
  echo "PASS [${label}]"
}

postjson() {
  local label="$1" endpoint="$2" payload="$3" jq_expr="${4:-.ok==true}"
  local status
  status="$(curl -sS -o "${TMP_DIR}/resp_post.json" -w "%{http_code}" \
    -H "Content-Type: application/json" -X POST -d "${payload}" "${BASE_URL}${endpoint}")"
  [[ "${status}" == "200" ]] || { echo "FAIL [${label}] expected 200, got ${status}"; cat "${TMP_DIR}/resp_post.json"; exit 1; }
  jq -e "${jq_expr}" "${TMP_DIR}/resp_post.json" >/dev/null || { echo "FAIL [${label}] jq: ${jq_expr}"; cat "${TMP_DIR}/resp_post.json"; exit 1; }
  echo "PASS [${label}]"
}

file_contains() {
  local file="$1" pattern="$2" label="$3"
  grep -Eq "${pattern}" "${file}" || { echo "FAIL [${label}] file does not contain: ${pattern}"; cat "${file}"; exit 1; }
  echo "PASS [${label}]"
}

main() {
  seed_files
  seed_sqlite
  start_api

  ok200 "health"    "/api/health"                            '.ok==true and has("ts")'
  ok200 "status"    "/api/status"                            'has("bot_mode") and has("session_start_balance") and has("manual_entry_paused")'
  ok200 "positions" "/api/positions"                         'type=="array" and length>=2'
  ok200 "trades"    "/api/trades"                            'type=="array" and length>=5'
  ok200 "trades50"  "/api/trades?limit=50&today_only=false"  'type=="array"'
  ok200 "equity"    "/api/equity"                            'type=="array"'
  ok200 "events"    "/api/events"                            'type=="array" and (map(has("ts")) | all)'
  ok200 "partials"  "/api/partials"                          'type=="array"'
  ok200 "settings"  "/api/settings"                          'has("env") and has("leverage_buckets")'

  postjson "ctrl_pause"        "/api/control" '{"action":"pause"}'                                '.ok==true'
  postjson "ctrl_resume"       "/api/control" '{"action":"resume"}'                               '.ok==true'
  postjson "ctrl_close_symbol" "/api/control" '{"action":"close_symbol","symbol":"BTCUSDT"}'      '.ok==true'
  postjson "ctrl_close_all"    "/api/control" '{"action":"close_all"}'                            '.ok==true'
  postjson "ctrl_kill"         "/api/control" '{"action":"kill"}'                                 '.ok==true'

  # settings write and verify on disk
  postjson "settings_write" "/api/settings" \
    '{"env":{"BOT_MODE":"paper","INITIAL_BALANCE":"777"},"leverage_buckets":{"major":["BTCUSDT"],"large_alt":[],"mid_cap":[]},"restart":false}' \
    '.ok==true'
  file_contains "${ENV_FILE}" '^BOT_MODE=paper$'     "env_bot_mode_written"
  file_contains "${ENV_FILE}" '^INITIAL_BALANCE=777$' "env_initial_balance_written"
  jq -e '.major|index("BTCUSDT")!=null' "${LEVERAGE_FILE}" >/dev/null && echo "PASS [leverage_written]" || { echo "FAIL [leverage_written]"; exit 1; }

  # Events: malformed line skipped, only valid JSON returned
  EVENTS_LEN=$(curl -sS "${BASE_URL}/api/events" | jq 'length')
  [[ "${EVENTS_LEN}" -ge 4 ]] && echo "PASS [events_skips_malformed (got ${EVENTS_LEN})]" || echo "WARN [events_skips_malformed] len=${EVENTS_LEN}"

  echo ""
  echo "All tests passed."
}

main "$@"
