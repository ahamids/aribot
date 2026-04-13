# ARIBOT LIVE Dashboard

ARIBOT LIVE provides a FastAPI backend and a single-file React operator dashboard.

## Files

- `aribot_live/api.py` - FastAPI backend
- `aribot_live/dashboard.html` - single-file React SPA (no build)
- `aribot_live/run.sh` - startup launcher

## Requirements

- Python 3.10+
- Dependencies installed from project `requirements.txt` (`fastapi`, `uvicorn`, `aiosqlite`)

## Environment

The API reads these variables (with defaults):

- `ARIBOT_DB` (default `usdt_bot_v2.db`)
- `ARIBOT_JSONL` (default `observability.jsonl`)
- `ARIBOT_ENV_FILE` (default `.env`)
- `ARIBOT_LEVERAGE_FILE` (default `leverage_buckets.json`)
- `DASHBOARD_PORT` (default `8765`)
- `ALLOWED_ORIGIN` (default `*`)

## Run

From repo root:

```bash
bash aribot_live/run.sh
```

Or directly:

```bash
python -m uvicorn aribot_live.api:app --host 0.0.0.0 --port 8765
```

Open:

- `http://localhost:8765/`

## API Endpoints

- `GET /api/health`
- `GET /api/status`
- `GET /api/positions`
- `GET /api/trades?limit=50&today_only=false`
- `GET /api/equity`
- `GET /api/events?limit=100`
- `GET /api/partials`
- `GET /api/settings`
- `POST /api/control`
- `POST /api/settings`

## Quick Verification

```bash
curl -s http://localhost:8765/api/health | jq
curl -s http://localhost:8765/api/status | jq
curl -s http://localhost:8765/api/positions | jq 'length'
curl -s 'http://localhost:8765/api/trades?limit=50&today_only=false' | jq 'length'
curl -s http://localhost:8765/api/equity | jq 'length'
curl -s 'http://localhost:8765/api/events?limit=50' | jq 'length'
curl -s http://localhost:8765/api/partials | jq 'length'
```

Control actions:

```bash
curl -s -X POST http://localhost:8765/api/control \
  -H 'Content-Type: application/json' \
  -d '{"action":"pause"}' | jq

curl -s -X POST http://localhost:8765/api/control \
  -H 'Content-Type: application/json' \
  -d '{"action":"resume"}' | jq

curl -s -X POST http://localhost:8765/api/control \
  -H 'Content-Type: application/json' \
  -d '{"action":"close_symbol","symbol":"BTCUSDT"}' | jq

curl -s -X POST http://localhost:8765/api/control \
  -H 'Content-Type: application/json' \
  -d '{"action":"close_all"}' | jq

curl -s -X POST http://localhost:8765/api/control \
  -H 'Content-Type: application/json' \
  -d '{"action":"kill"}' | jq
```

Settings read/write:

```bash
curl -s http://localhost:8765/api/settings | jq

curl -s -X POST http://localhost:8765/api/settings \
  -H 'Content-Type: application/json' \
  -d '{
    "env": {"BOT_MODE":"paper"},
    "leverage_buckets": {"major": ["BTCUSDT"], "large_alt": ["ETHUSDT"], "mid_cap": []},
    "restart": false
  }' | jq
```

## Notes

- `POST /api/control` writes pending actions into `bot_state.telegram_pending_confirmations_json`.
- Missing database file at startup logs a warning and does not crash API boot.
- `GET /api/events` skips malformed JSONL lines and returns valid parsed events only.
- v1 ignores `reconciliation_reports` and `order_idempotency` tables for dashboard output.
