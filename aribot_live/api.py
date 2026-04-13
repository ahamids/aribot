from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import uvicorn
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

ARIBOT_DB = os.getenv("ARIBOT_DB", "usdt_bot_v2.db")
ARIBOT_JSONL = os.getenv("ARIBOT_JSONL", "observability.jsonl")
ARIBOT_ENV_FILE = os.getenv("ARIBOT_ENV_FILE", ".env")
ARIBOT_LEVERAGE_FILE = os.getenv("ARIBOT_LEVERAGE_FILE", "leverage_buckets.json")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8765"))
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")

LOGGER = logging.getLogger("aribot_live.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(ARIBOT_DB)
JSONL_PATH = Path(ARIBOT_JSONL)
ENV_PATH = Path(ARIBOT_ENV_FILE)
LEVERAGE_PATH = Path(ARIBOT_LEVERAGE_FILE)

ENV_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


class ControlBody(BaseModel):
    action: str
    symbol: str | None = None


class SettingsBody(BaseModel):
    env: dict[str, Any] = Field(default_factory=dict)
    leverage_buckets: dict[str, Any] = Field(default_factory=dict)
    restart: bool = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    v = str(value).strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    return default


def parse_env_file(path: Path) -> tuple[dict[str, str], list[str]]:
    if not path.exists():
        return {}, []

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    env: dict[str, str] = {}
    for line in lines:
        m = ENV_LINE_RE.match(line)
        if not m:
            continue
        key = m.group(1)
        raw_val = m.group(2).rstrip("\r\n")
        comment_idx = raw_val.find(" #")
        if comment_idx >= 0:
            raw_val = raw_val[:comment_idx]
        val = raw_val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in {'"', "'"}:
            val = val[1:-1]
        env[key] = val
    return env, lines


def render_env_value(value: str) -> str:
    if value == "" or any(ch.isspace() for ch in value) or "#" in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def write_env_file_preserve(path: Path, payload_env: dict[str, Any]) -> None:
    normalized: dict[str, str] = {str(k): "" if v is None else str(v) for k, v in payload_env.items()}
    existing_env, lines = parse_env_file(path)

    if not lines:
        content = "".join(f"{k}={render_env_value(v)}\n" for k, v in normalized.items())
        path.write_text(content, encoding="utf-8")
        return

    seen: set[str] = set()
    out_lines: list[str] = []
    for line in lines:
        m = ENV_LINE_RE.match(line)
        if not m:
            out_lines.append(line)
            continue
        key = m.group(1)
        if key in normalized:
            suffix = "\n" if line.endswith("\n") else ""
            out_lines.append(f"{key}={render_env_value(normalized[key])}{suffix}")
            seen.add(key)
        else:
            out_lines.append(line)

    for key, value in normalized.items():
        if key not in seen and key not in existing_env:
            out_lines.append(f"{key}={render_env_value(value)}\n")

    path.write_text("".join(out_lines), encoding="utf-8")


async def fetch_bot_state(db: aiosqlite.Connection) -> dict[str, str]:
    result: dict[str, str] = {}
    async with db.execute("SELECT key, value FROM bot_state") as cursor:
        rows = await cursor.fetchall()
        for row in rows:
            result[str(row["key"])] = "" if row["value"] is None else str(row["value"])
    return result


async def upsert_bot_state(db: aiosqlite.Connection, key: str, value: str) -> None:
    await db.execute(
        """
        INSERT INTO bot_state (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def tail_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or not path.exists():
        return []

    block_size = 8192
    data = bytearray()
    line_count = 0
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        while pos > 0 and line_count <= limit * 3:
            read_size = min(block_size, pos)
            pos -= read_size
            fh.seek(pos)
            chunk = fh.read(read_size)
            data[:0] = chunk
            line_count = data.count(b"\n")

    out: list[dict[str, Any]] = []
    for line in reversed(data.decode("utf-8", errors="replace").splitlines()):
        text = line.strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                out.append(obj)
                if len(out) >= limit:
                    break
        except json.JSONDecodeError:
            continue
    out.reverse()
    return out


def numeric_cast_row(row: dict[str, Any]) -> dict[str, Any]:
    casted: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, str):
            maybe = None
            try:
                maybe = float(value)
            except ValueError:
                maybe = None
            casted[key] = maybe if maybe is not None else value
        else:
            casted[key] = value
    return casted


app = FastAPI(title="ARIBOT LIVE API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_check() -> None:
    if not DB_PATH.exists():
        LOGGER.warning("ARIBOT_DB does not exist yet: %s", DB_PATH.resolve())


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(str(APP_DIR / "dashboard.html"))


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    if not DB_PATH.exists():
        state: dict[str, str] = {}
    else:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            state = await fetch_bot_state(db)

    current_balance = to_float(state.get("current_balance"), 0.0)
    session_start_balance = to_float(state.get("session_start_balance"), 0.0)
    session_pnl = current_balance - session_start_balance
    session_pnl_pct = (session_pnl / session_start_balance * 100.0) if session_start_balance else 0.0

    cooldown_raw = state.get("cooldown_until_utc", "").strip()
    cooldown_until_utc = cooldown_raw or None

    manual_entry_flag = state.get("manual_entry_paused", state.get("telegram_manual_pause_active", "0"))

    return {
        "bot_mode": state.get("bot_mode", state.get("BOT_MODE", "unknown")),
        "current_balance": current_balance,
        "session_start_balance": session_start_balance,
        "session_pnl": session_pnl,
        "session_pnl_pct": session_pnl_pct,
        "total_pnl": to_float(state.get("total_pnl"), 0.0),
        "winning_trades": to_int(state.get("winning_trades"), 0),
        "losing_trades": to_int(state.get("losing_trades"), 0),
        "loop_cycle_count": to_int(state.get("loop_cycle_count"), 0),
        "daily_drawdown_paused": to_bool(state.get("daily_drawdown_paused"), False),
        "manual_entry_paused": to_bool(manual_entry_flag, False),
        "cooldown_until_utc": cooldown_until_utc,
        "last_regime_signal": state.get("last_regime_signal", "UNKNOWN"),
        "telegram_pending_confirmations_json": state.get("telegram_pending_confirmations_json", ""),
        "db_path": str(DB_PATH.resolve()),
    }


@app.get("/api/positions")
async def api_positions() -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM positions ORDER BY timestamp DESC") as cursor:
            rows = await cursor.fetchall()
    return [numeric_cast_row(dict(row)) for row in rows]


@app.get("/api/trades")
async def api_trades(limit: int = Query(default=50, ge=1, le=1000), today_only: bool = False) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    sql = "SELECT * FROM closed_trades ORDER BY close_time DESC LIMIT ?"
    params: tuple[Any, ...] = (limit,)
    if today_only:
        sql = "SELECT * FROM closed_trades WHERE date(close_time) = date('now') ORDER BY close_time DESC LIMIT ?"
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
    return [numeric_cast_row(dict(row)) for row in rows]


@app.get("/api/equity")
async def api_equity() -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT value FROM bot_state WHERE key='initial_balance' LIMIT 1") as cursor:
            initial_row = await cursor.fetchone()
        initial_balance = to_float(initial_row["value"] if initial_row else 0.0, 0.0)

        async with db.execute("SELECT pnl, close_time FROM closed_trades ORDER BY close_time ASC") as cursor:
            rows = await cursor.fetchall()

    running = initial_balance
    series: list[dict[str, Any]] = []
    for row in rows:
        running += to_float(row["pnl"], 0.0)
        series.append({"timestamp": row["close_time"], "balance": running})
    return series


@app.get("/api/events")
async def api_events(limit: int = Query(default=100, ge=1, le=5000)) -> list[dict[str, Any]]:
    return tail_jsonl(JSONL_PATH, limit)


@app.get("/api/partials")
async def api_partials() -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM partial_realizations ORDER BY event_time DESC LIMIT 200") as cursor:
            rows = await cursor.fetchall()
    return [numeric_cast_row(dict(row)) for row in rows]


@app.post("/api/control")
async def api_control(body: ControlBody) -> JSONResponse:
    action = body.action.strip()
    if action not in {"pause", "resume", "close_symbol", "close_all", "kill"}:
        return JSONResponse(status_code=400, content={"ok": False, "message": f"Invalid action: {action}"})
    if action == "close_symbol" and not (body.symbol or "").strip():
        return JSONResponse(status_code=400, content={"ok": False, "message": "symbol is required for close_symbol"})

    if not DB_PATH.exists():
        return JSONResponse(status_code=400, content={"ok": False, "message": f"DB not found: {DB_PATH}"})

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row

        if action == "pause":
            await upsert_bot_state(db, "telegram_manual_pause_active", "1")
            await db.commit()
            return JSONResponse(content={"ok": True, "message": "Action queued"})

        if action == "resume":
            await upsert_bot_state(db, "telegram_manual_pause_active", "0")
            await db.commit()
            return JSONResponse(content={"ok": True, "message": "Action queued"})

        payload: dict[str, Any] = {
            "chat_id": "dashboard",
            "action": action,
            "created_at_utc": now_iso(),
            "expires_at_utc": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
            "nonce": str(uuid.uuid4()),
        }
        if action == "close_symbol":
            payload["args"] = {"symbol": body.symbol}

        await upsert_bot_state(db, "telegram_pending_confirmations_json", json.dumps(payload, separators=(",", ":")))
        await db.commit()

    return JSONResponse(content={"ok": True, "message": "Action queued"})


@app.get("/api/settings")
async def api_get_settings() -> dict[str, Any]:
    env_map, _lines = parse_env_file(ENV_PATH)

    leverage_buckets: dict[str, Any] = {}
    if LEVERAGE_PATH.exists():
        try:
            parsed = json.loads(LEVERAGE_PATH.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                leverage_buckets = parsed
        except json.JSONDecodeError:
            leverage_buckets = {}

    return {"env": env_map, "leverage_buckets": leverage_buckets}


@app.post("/api/settings")
async def api_post_settings(body: SettingsBody) -> dict[str, Any]:
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEVERAGE_PATH.parent.mkdir(parents=True, exist_ok=True)

    write_env_file_preserve(ENV_PATH, body.env)
    LEVERAGE_PATH.write_text(json.dumps(body.leverage_buckets, indent=2) + "\n", encoding="utf-8")

    restart_triggered = False
    if body.restart:
        env_map, _ = parse_env_file(ENV_PATH)
        restart_command = env_map.get("RESTART_COMMAND", "").strip()
        if restart_command:
            subprocess.Popen(restart_command, shell=True)
            restart_triggered = True

    return {"ok": True, "restart_triggered": restart_triggered}


@app.get("/api/health")
async def api_health() -> dict[str, Any]:
    return {"ok": True, "ts": now_iso()}


if __name__ == "__main__":
    uvicorn.run("aribot_live.api:app", host="0.0.0.0", port=DASHBOARD_PORT)
