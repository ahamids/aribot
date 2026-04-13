#!/usr/bin/env bash
set -euo pipefail

: "${DASHBOARD_PORT:=8765}"

exec python -m uvicorn aribot_live.api:app --host 0.0.0.0 --port "${DASHBOARD_PORT}"
