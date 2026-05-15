"""Aribot status + control HTTP sidecar.

A FastAPI service that wraps the trading bot for the iOS app. Endpoints:

  GET  /healthz   sidecar liveness, independent of the bot
  GET  /status    snapshot of bot state (status/mode/PnL/balance/positions count)
  GET  /positions current open positions (joined from positions table)
  GET  /equity    24h equity curve, reconstructed from closed_trades + current state
  POST /start     launch the bot via subprocess.Popen
  POST /stop      gracefully stop the bot by writing kill_switch.flag

Bearer auth: ARIBOT_API_TOKEN must be set in the sidecar's environment. Every
endpoint requires `Authorization: Bearer <token>`, validated with hmac.compare_digest.
The /healthz path is the one exception — it never reveals anything sensitive
and is useful for unauthenticated readiness probes.

Run:

    python status_server.py --host 0.0.0.0 --port 8787

The sidecar reads aribot_status.json (the bot writes it every cycle) for status
fields and queries usdt_bot_v2.db directly (read-only) for positions and trade
history.
"""

from __future__ import annotations

import argparse
import datetime
import hmac
import json
import os
import sqlite3
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status as http_status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

try:
    import psutil
except ImportError as exc:
    raise SystemExit(
        "status_server requires psutil. Install with: pip install -r requirements-status-server.txt"
    ) from exc

from bot_keypair import HostIdentity, get_or_create_identity
from credential_pipe import CredentialServer
from credential_store import CredentialStore
from tls_cert import TlsArtifacts, ensure_tls


Status = Literal["running", "stopped", "error", "killed"]
Mode = Literal["PAPER", "SHADOW", "LIVE"]


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

_DEV_CORS_DEFAULT = (
    "http://localhost:8081",
    "http://127.0.0.1:8081",
    "http://localhost:19006",
    "http://127.0.0.1:19006",
    "http://localhost:19000",
    "http://127.0.0.1:19000",
)


@dataclass(frozen=True)
class Config:
    snapshot_path: Path
    kill_switch_path: Path
    db_path: Path
    bot_pid_path: Path
    bot_log_path: Path
    bot_command: tuple[str, ...]
    bot_cwd: Path
    env_file_path: Path
    expected_token: Optional[str]
    # Optional vault-scoped token. When set, /credentials* endpoints require
    # this token instead of the general control token, so a leaked control
    # token cannot push or wipe Bybit creds. Falls back to expected_token if
    # unset, for single-token deployments.
    expected_vault_token: Optional[str]
    stale_multiplier: float
    cors_origins: tuple[str, ...]
    # Directory the host keypair and TLS cert live in.
    artifact_dir: Path


def _resolve_version() -> str:
    here = Path(__file__).resolve().parent
    try:
        out = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        sha = out.stdout.strip()
        if sha:
            return sha
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "dev"


VERSION = _resolve_version()


def load_config(args: argparse.Namespace) -> Config:
    here = Path(__file__).resolve().parent

    # Anchor relative defaults to the sidecar's script directory, NOT the
    # process CWD. The bot writes the flag/snapshot from its own CWD too,
    # so if both are launched from different directories, they'd disagree
    # about which file is "the" kill switch. Anchoring at `here` (which is
    # the repo root, since status_server.py lives at the root) gives both
    # processes a stable absolute path as long as they're started from the
    # repo root — which is what HOW_TO_RUN.md instructs.
    def _anchor(value: Optional[str], env_key: str, default_name: str) -> Path:
        raw = value or os.getenv(env_key, default_name)
        p = Path(raw)
        if not p.is_absolute():
            p = here / p
        return p.resolve()

    snapshot = _anchor(args.snapshot, "STATUS_SNAPSHOT_FILE", "aribot_status.json")
    kill = _anchor(args.kill_switch, "KILL_SWITCH_FILE", "kill_switch.flag")
    env_file = _anchor(None, "ARIBOT_ENV_FILE", ".env")
    db = Path(os.getenv("ARIBOT_DB_FILE", str(here / "usdt_bot_v2.db"))).resolve()
    pid_file = Path(os.getenv("ARIBOT_PID_FILE", str(here / ".aribot.pid"))).resolve()
    log_file = Path(os.getenv("ARIBOT_LOG_FILE", str(here / ".aribot.launched.log"))).resolve()

    # Command the sidecar runs to start the bot. Defaults to the exact line
    # from HOW_TO_RUN.md so behaviour matches the user's manual workflow.
    default_cmd = (
        sys.executable,
        str(here / "usdt_paper_bot_v2.py"),
        "--symbols-file",
        "symbol_focus.example.json",
        "--emojis",
    )
    cmd_env = os.getenv("ARIBOT_START_COMMAND")
    if cmd_env:
        # Whitespace-split is fine for our use case; users with spaces in paths
        # should set the env var to a single quoted python path and pass args.
        bot_command = tuple(cmd_env.split())
    else:
        bot_command = default_cmd

    token = os.getenv("ARIBOT_API_TOKEN")
    vault_token = os.getenv("ARIBOT_API_TOKEN_VAULT") or token
    stale_mult = float(os.getenv("STATUS_STALE_MULTIPLIER", "5"))
    cors_raw = os.getenv("STATUS_CORS_ORIGINS", "").strip()
    if cors_raw:
        cors = tuple(p.strip() for p in cors_raw.split(",") if p.strip())
    else:
        cors = _DEV_CORS_DEFAULT
    artifact_dir = Path(os.getenv("ARIBOT_ARTIFACT_DIR", str(here / ".aribot"))).resolve()
    return Config(
        snapshot_path=snapshot,
        kill_switch_path=kill,
        db_path=db,
        bot_pid_path=pid_file,
        bot_log_path=log_file,
        bot_command=bot_command,
        bot_cwd=here,
        env_file_path=env_file,
        expected_token=token,
        expected_vault_token=vault_token,
        stale_multiplier=stale_mult,
        cors_origins=cors,
        artifact_dir=artifact_dir,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_iso(s: str) -> Optional[datetime.datetime]:
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    # Normalize: assume any naive timestamp is UTC. The bot's sqlite writes
    # close_time without a tz suffix; we'd rather treat it as UTC than crash
    # on comparison with the tz-aware cutoff.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def derive_status(snapshot: Optional[dict], cfg: Config, now_utc: datetime.datetime) -> tuple[Status, Optional[str]]:
    if cfg.kill_switch_path.exists():
        return "killed", f"kill_switch_present:{cfg.kill_switch_path.name}"
    if snapshot is None:
        return "stopped", "snapshot_missing"
    pid = int(snapshot.get("pid", 0))
    if pid and not _pid_alive(pid):
        return "error", f"pid_dead:{pid}"
    wrote_at = _parse_iso(str(snapshot.get("wrote_at", "")))
    if wrote_at is None:
        return "error", "snapshot_wrote_at_unparseable"
    interval = float(snapshot.get("loop_interval_seconds", 60))
    age_s = (now_utc - wrote_at).total_seconds()
    if age_s > interval * cfg.stale_multiplier:
        return "error", f"snapshot_stale:{age_s:.0f}s>{interval * cfg.stale_multiplier:.0f}s"
    return "running", None


def _read_snapshot(cfg: Config) -> Optional[dict]:
    try:
        raw = cfg.snapshot_path.read_text(encoding="utf-8-sig")
    except (FileNotFoundError, OSError):
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _resolve_db_path(cfg: Config) -> Path:
    """Pick the right sqlite file. The bot now uses mode-specific db files
    (usdt_bot_v2.{paper,shadow,live}.db) and writes the resolved path to its
    snapshot. Prefer that — it's the source of truth for "the file the bot
    currently has open." Fall back to cfg.db_path for backward compat (e.g.
    when the snapshot file doesn't exist yet on a fresh install).
    """
    snap = _read_snapshot(cfg)
    if snap:
        snap_db = snap.get("db_file")
        if isinstance(snap_db, str) and snap_db:
            p = Path(snap_db)
            if not p.is_absolute():
                p = cfg.bot_cwd / p
            if p.exists():
                return p
    return cfg.db_path


def _open_db(cfg: Config) -> sqlite3.Connection:
    # Read-only mode so the sidecar can never corrupt the bot's state.
    db_path = _resolve_db_path(cfg)
    uri = f"file:{db_path.as_posix()}?mode=ro"
    db = sqlite3.connect(uri, uri=True, detect_types=sqlite3.PARSE_DECLTYPES)
    db.row_factory = sqlite3.Row
    return db


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic response models — keeps the iOS contract documented and validated.
# ─────────────────────────────────────────────────────────────────────────────

class StatusOut(BaseModel):
    version: str
    mode: Mode = "PAPER"
    status: Status
    uptimeSeconds: int = 0
    lastCycleIso: str
    openPositions: int = 0
    currentBalance: float = 0.0
    todaysPnl: float = 0.0
    testnet: bool = False
    cycleCount: int = 0
    runId: str = ""
    reason: Optional[str] = None


class PositionOut(BaseModel):
    symbol: str
    side: Literal["LONG", "SHORT"]
    size: float
    entry: float
    mark: Optional[float] = None
    pnl: float = 0.0
    pnlPercent: Optional[float] = None
    leverage: Optional[float] = None
    liquidationPrice: Optional[float] = None
    openedAtIso: Optional[str] = None


class PositionsOut(BaseModel):
    positions: list[PositionOut]
    asOfIso: str


class TradeOut(BaseModel):
    symbol: str
    side: Literal["LONG", "SHORT"]
    pnl: float
    pnlPercent: Optional[float] = None
    entryPrice: Optional[float] = None
    exitPrice: Optional[float] = None
    quantity: Optional[float] = None
    reason: Optional[str] = None
    openedAtIso: Optional[str] = None
    closedAtIso: str


class TradesOut(BaseModel):
    trades: list[TradeOut]
    asOfIso: str
    note: str = Field(
        default="Sorted newest first. Client groups by day in its own timezone.",
    )


class EquityStats(BaseModel):
    winRate: Optional[float] = None  # fraction 0..1, not percent
    tradeCount: int = 0
    avgWin: Optional[float] = None
    avgLoss: Optional[float] = None  # negative number
    bestWin: Optional[float] = None
    worstLoss: Optional[float] = None
    pnlAbs: float = 0.0
    pnlPercent: Optional[float] = None


class EquityPoint(BaseModel):
    t: str  # ISO timestamp
    equity: float


class EquityOut(BaseModel):
    points: list[EquityPoint]
    todaysPnl: float
    rangeHours: int
    stats: EquityStats
    note: str = Field(
        default="Reconstructed from closed_trades + current balance. "
        "Per-cycle equity history is not yet persisted.",
    )


class ControlOut(BaseModel):
    ok: bool
    action: Literal["start", "stop", "kill", "clear_kill"]
    pid: Optional[int] = None
    detail: str


class ModeOut(BaseModel):
    ok: bool
    mode: Optional[Mode] = None
    detail: str
    # When ok=False and a running bot is the reason, this is its pid so the
    # iOS app can offer a "stop & retry" affordance.
    runningPid: Optional[int] = None


class ModeBody(BaseModel):
    mode: Mode


# ─────────────────────────────────────────────────────────────────────────────
# Credential vault wire models (paired with app/src/lib/botApi.ts)
# ─────────────────────────────────────────────────────────────────────────────

class PubkeyOut(BaseModel):
    publicKey: str  # base64 (32 bytes X25519)
    fingerprint: str
    algo: Literal["x25519-nacl-box"] = "x25519-nacl-box"


class CredentialsBody(BaseModel):
    ciphertext: str
    nonce: str
    senderPublicKey: str
    timestampIso: str
    counter: int


class CredentialsAckOut(BaseModel):
    ok: bool
    detail: str
    fingerprint: Optional[str] = None


class CredentialsStatusOut(BaseModel):
    loaded: bool
    fingerprint: Optional[str] = None
    source: Optional[str] = None
    validatedAtIso: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Process control — start/stop bot
# ─────────────────────────────────────────────────────────────────────────────

class _BotLock:
    """Single-flight lock so two concurrent /start calls don't fork two bots."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 1.0) -> bool:
        return self._lock.acquire(timeout=timeout)

    def release(self) -> None:
        try:
            self._lock.release()
        except RuntimeError:
            pass


_bot_lock = _BotLock()


def _read_pid_file(path: Path) -> Optional[int]:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _running_bot_pid(cfg: Config) -> Optional[int]:
    """Returns the PID of a running bot, or None.

    Trusts the snapshot file first (the bot itself wrote its own PID there),
    falls back to the sidecar's pid file. Either way, we require psutil to
    confirm liveness so a stale PID isn't reported as alive.
    """
    snap = _read_snapshot(cfg)
    if snap:
        pid = int(snap.get("pid", 0))
        if pid and _pid_alive(pid):
            return pid
    file_pid = _read_pid_file(cfg.bot_pid_path)
    if file_pid and _pid_alive(file_pid):
        return file_pid
    return None


def _read_bot_mode(cfg: Config) -> str:
    """Reads BOT_MODE from .env. Returns lower-case 'paper' on any read
    failure — the bot itself would do the same, and PAPER is the safe
    default for credential-gating decisions."""
    try:
        text = cfg.env_file_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return "paper"
    for raw_line in text.splitlines():
        stripped = raw_line.lstrip()
        if stripped.startswith("BOT_MODE=") or stripped.startswith("export BOT_MODE="):
            value = stripped.split("=", 1)[1].strip()
            # Strip optional surrounding quotes.
            if (value.startswith("'") and value.endswith("'")) or (
                value.startswith('"') and value.endswith('"')
            ):
                value = value[1:-1]
            return value.strip().lower() or "paper"
    return "paper"


def start_bot(cfg: Config, credential_store: CredentialStore) -> tuple[bool, str, Optional[int]]:
    if not _bot_lock.acquire(timeout=1.0):
        return False, "another start request is in flight", None
    try:
        existing = _running_bot_pid(cfg)
        if existing is not None:
            return False, f"bot already running (pid {existing})", existing

        # If a kill switch is still on disk, refuse to start — the operator
        # set it intentionally, the bot would just exit again immediately.
        if cfg.kill_switch_path.exists():
            return (
                False,
                f"kill switch present at {cfg.kill_switch_path} — remove before starting",
                None,
            )

        # LIVE-mode credential guard. The locked-in policy is "refuse always":
        # LIVE will not start unless iOS-pushed keys are present in the
        # CredentialStore. PAPER/SHADOW stay permissive (current behaviour).
        bot_mode = _read_bot_mode(cfg)
        cred_handle = None
        cred_server: Optional[CredentialServer] = None
        if credential_store.is_loaded():
            cred_server = CredentialServer()
            cred_handle = cred_server.start(credential_store.snapshot())
        elif bot_mode == "live":
            return (
                False,
                "LIVE mode refuses to start without iOS-pushed credentials. "
                "Open the iOS app and submit Bybit keys, then retry.",
                None,
            )

        # Open the log file in append mode so we don't clobber prior launch logs.
        try:
            log_fh = cfg.bot_log_path.open("ab", buffering=0)
        except OSError as exc:
            if cred_server is not None:
                cred_server.close()
            return False, f"could not open log file {cfg.bot_log_path}: {exc}", None

        creationflags = 0
        if sys.platform == "win32":
            # CREATE_NEW_PROCESS_GROUP so the child doesn't die when the sidecar
            # gets Ctrl+C. DETACHED_PROCESS would orphan it entirely; we want it
            # tracked but independent.
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        spawn_env = os.environ.copy()
        if cred_handle is not None:
            spawn_env["ARIBOT_CRED_PIPE"] = cred_handle.address
            spawn_env["ARIBOT_CRED_TOKEN"] = cred_handle.token_hex

        try:
            proc = subprocess.Popen(
                cfg.bot_command,
                cwd=str(cfg.bot_cwd),
                stdout=log_fh,
                stderr=log_fh,
                stdin=subprocess.DEVNULL,
                env=spawn_env,
                creationflags=creationflags,
                start_new_session=(sys.platform != "win32"),
            )
        except (OSError, FileNotFoundError) as exc:
            log_fh.close()
            if cred_server is not None:
                cred_server.close()
            return False, f"subprocess.Popen failed: {exc}", None

        try:
            cfg.bot_pid_path.write_text(str(proc.pid), encoding="utf-8")
        except OSError:
            # Failing to write the pid file is not fatal — the snapshot the bot
            # writes will carry its own pid soon enough.
            pass

        if cred_server is not None:
            # Wait briefly for the bot to read the pipe, then tear it down.
            # We don't block the HTTP response on this; spawn a thread.
            def _close_after_handoff() -> None:
                try:
                    cred_server.wait_for_handoff(timeout=30.0)
                finally:
                    cred_server.close()

            threading.Thread(target=_close_after_handoff, daemon=True).start()

        return True, f"bot launched (pid {proc.pid})", proc.pid
    finally:
        _bot_lock.release()


def _write_kill_switch(cfg: Config, intent: Literal["stop", "kill"]) -> Optional[str]:
    """Atomically write the kill switch file. Returns None on success or an
    error string on failure. The bot's kill detector only checks file
    presence, but the intent string is captured for forensic clarity so
    operators can tell after the fact whether the flag came from a graceful
    /stop or an emergency /kill.
    """
    try:
        tmp = cfg.kill_switch_path.with_suffix(cfg.kill_switch_path.suffix + ".tmp")
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        tmp.write_text(
            f"intent: {intent}\ncreated_by: status_server\ncreated_at: {now_iso}\n",
            encoding="utf-8",
        )
        os.replace(tmp, cfg.kill_switch_path)
        return None
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"


def stop_bot(cfg: Config) -> tuple[bool, str, Optional[int]]:
    pid = _running_bot_pid(cfg)
    err = _write_kill_switch(cfg, "stop")
    if err is not None:
        return False, f"could not write kill switch: {err}", pid
    if pid is None:
        return True, "kill switch written; no running bot detected", None
    return True, f"kill switch written; bot pid {pid} will exit at next cycle", pid


def kill_bot(cfg: Config) -> tuple[bool, str, Optional[int]]:
    """Trip the kill switch. Same file as stop_bot, different intent line.
    The bot's kill detector treats both the same way — it exits at the next
    cycle. The intent line lets operators distinguish in post-mortem logs.
    """
    pid = _running_bot_pid(cfg)
    err = _write_kill_switch(cfg, "kill")
    if err is not None:
        return False, f"could not write kill switch: {err}", pid
    if pid is None:
        return True, "kill switch tripped; no running bot detected", None
    return True, f"kill switch tripped; bot pid {pid} will exit at next cycle", pid


def clear_kill(cfg: Config) -> tuple[bool, str]:
    """Remove the kill switch flag. Returns ok=True even if the flag didn't
    exist (idempotent) — the goal is a clear state, not a removal action.
    """
    try:
        cfg.kill_switch_path.unlink(missing_ok=True)
        return True, "kill switch cleared"
    except OSError as exc:
        return False, f"could not clear kill switch: {type(exc).__name__}: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# Mode persistence — atomic update to .env preserving comments + other keys.
# ─────────────────────────────────────────────────────────────────────────────

_VALID_MODES = ("paper", "shadow", "live")


def set_bot_mode(cfg: Config, requested_mode: str) -> tuple[bool, str, Optional[int], Optional[str]]:
    """Update BOT_MODE in the .env file.

    Returns (ok, detail, running_pid, effective_mode).

    Refuses if the bot is currently running (the bot reads BOT_MODE once at
    startup, so a live change while it's running would be a silent no-op until
    restart — confusing UX). The caller should /stop first.

    The write is atomic (tmp + os.replace) and preserves every other line in
    .env — comments, blank lines, unrelated keys, and the quoting style of
    other values. Only the BOT_MODE line is rewritten; if BOT_MODE wasn't
    present, a new line is appended.
    """
    norm = (requested_mode or "").strip().lower()
    if norm not in _VALID_MODES:
        return False, f"invalid mode '{requested_mode}'; must be one of {_VALID_MODES}", None, None

    running = _running_bot_pid(cfg)
    if running is not None:
        return (
            False,
            f"bot is currently running (pid {running}); stop it first via POST /stop",
            running,
            None,
        )

    env_path = cfg.env_file_path
    try:
        existing_text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    except OSError as exc:
        return False, f"could not read {env_path}: {exc}", None, None

    new_text = _rewrite_env_key(existing_text, "BOT_MODE", norm)

    try:
        tmp = env_path.with_suffix(env_path.suffix + ".tmp")
        tmp.write_text(new_text, encoding="utf-8")
        os.replace(tmp, env_path)
    except OSError as exc:
        return False, f"could not write {env_path}: {exc}", None, None

    # Response uses upper-case to match the iOS Mode contract; the value
    # we wrote to .env is lower-case (the bot reads it that way).
    return True, f"BOT_MODE set to {norm}; bot will use it on next start", None, norm.upper()


def _rewrite_env_key(text: str, key: str, value: str) -> str:
    """Replace `KEY=...` line in dotenv text (preserving everything else), or
    append a new line if the key wasn't present. Quoting strategy: if the new
    value has no whitespace or special chars, write it bare; else single-quote.

    This is intentionally simpler than python-dotenv's set_key — we don't need
    full RFC compliance, just preservation of comments and other keys. The
    keys we touch (BOT_MODE: 'paper'/'shadow'/'live') are always bare-safe.
    """
    # Bare-safe heuristic: ASCII letters/digits/underscore/dot/hyphen only.
    safe = bool(value) and all(c.isalnum() or c in "_-." for c in value)
    encoded = value if safe else "'" + value.replace("'", "'\\''") + "'"
    replacement = f"{key}={encoded}"

    if not text:
        return replacement + "\n"

    out_lines: list[str] = []
    replaced = False
    for line in text.splitlines():
        stripped = line.lstrip()
        # Match `KEY=` ignoring leading whitespace; preserve nothing past the
        # `=` since we're replacing it. Lines that start with `#` or are
        # blank are passed through unchanged.
        if stripped.startswith(f"{key}=") or stripped.startswith(f"export {key}="):
            out_lines.append(replacement)
            replaced = True
        else:
            out_lines.append(line)

    if not replaced:
        # Preserve trailing newline if the file had one.
        if out_lines and out_lines[-1] != "":
            out_lines.append("")
        out_lines.append(replacement)

    # Preserve trailing newline.
    result = "\n".join(out_lines)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Data queries — read-only against usdt_bot_v2.db
# ─────────────────────────────────────────────────────────────────────────────

def _leverage_lookup(cfg: Config) -> dict[str, float]:
    """Read leverage_buckets.json to derive per-symbol leverage.

    The bot stores leverage per-bucket (major / large_alt / mid_cap) in a JSON
    file, not per-position in sqlite. We mirror its lookup so the iOS app can
    show realistic leverage chips on each position card.
    """
    path = cfg.bot_cwd / "leverage_buckets.json"
    if not path.exists():
        return {}
    try:
        cfg_obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    mapping: dict[str, float] = {}
    for bucket in ("major", "large_alt", "mid_cap"):
        spec = cfg_obj.get(bucket) or {}
        lev = float(spec.get("leverage", 0.0))
        for coin in spec.get("coins", []):
            mapping[str(coin).upper()] = lev
    return mapping


def _fetch_open_positions(cfg: Config) -> list[PositionOut]:
    if not _resolve_db_path(cfg).exists():
        return []
    out: list[PositionOut] = []
    lev_lookup = _leverage_lookup(cfg)

    with _open_db(cfg) as db:
        rows = db.execute(
            """
            SELECT symbol, side, entry_price, quantity, timestamp,
                   COALESCE(current_price, 0)  AS current_price,
                   COALESCE(pnl, 0)            AS pnl,
                   COALESCE(pnl_percentage, 0) AS pnl_percentage
            FROM positions
            """
        ).fetchall()
        for r in rows:
            side_raw = (r["side"] or "").upper()
            side: Literal["LONG", "SHORT"] = "SHORT" if side_raw.startswith("S") else "LONG"
            entry = float(r["entry_price"] or 0.0)
            mark = float(r["current_price"] or 0.0) or None
            qty = float(r["quantity"] or 0.0)
            pnl = float(r["pnl"] or 0.0)
            # Fallback PnL calc if the bot hasn't updated pnl yet.
            if pnl == 0.0 and mark is not None and entry > 0:
                if side == "LONG":
                    pnl = (mark - entry) * qty
                else:
                    pnl = (entry - mark) * qty
            pnl_pct = float(r["pnl_percentage"] or 0.0) or None

            # Symbol arrives like "BTC/USDT:USDT" — extract the base for the
            # leverage lookup. Falls back to None for symbols not in any bucket.
            base = str(r["symbol"]).split("/", 1)[0].upper()
            lev = lev_lookup.get(base)

            out.append(
                PositionOut(
                    symbol=str(r["symbol"]),
                    side=side,
                    size=qty,
                    entry=entry,
                    mark=mark,
                    pnl=pnl,
                    pnlPercent=pnl_pct,
                    leverage=lev,
                    liquidationPrice=None,  # bot does not store this
                    openedAtIso=str(r["timestamp"]) if r["timestamp"] else None,
                )
            )
    return out


def _compute_todays_pnl(cfg: Config) -> float:
    """Accurate today's PnL = closed-trade PnL since UTC midnight + open-position unrealized PnL.

    Replaces the bot's snapshot.session_pnl, which is broken across restarts
    because session_start_balance is set BEFORE load_state() reads the
    persisted balance from sqlite. After a restart it equals
    `current_balance - hardcoded $400 initial_balance`, which on a profitable
    account inflates into "lifetime PnL" rather than "today's".

    This function recomputes from durable sqlite state, so it survives any
    number of restarts and resets cleanly at UTC midnight.
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    midnight = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    realized = 0.0
    for row in _fetch_closed_trades_since(cfg, midnight, limit=1000):
        ts = _parse_iso(str(row["close_time"] or ""))
        if ts is None or ts < midnight:
            continue
        realized += float(row["pnl"] or 0.0)

    unrealized = 0.0
    for p in _fetch_open_positions(cfg):
        unrealized += float(p.pnl or 0.0)

    return realized + unrealized


def _fetch_closed_trades_since(cfg: Config, since: datetime.datetime, limit: int = 500) -> list[sqlite3.Row]:
    """Returns closed_trades rows from `since` -> now, newest first.

    Used by both /trades and /equity. Empty list on schema mismatch or missing
    db — never raises, so callers can render an empty UI state.
    """
    if not _resolve_db_path(cfg).exists():
        return []
    with _open_db(cfg) as db:
        try:
            return db.execute(
                """
                SELECT symbol, side, entry_price, exit_price, quantity, pnl,
                       pnl_percentage, reason, open_time, close_time
                FROM closed_trades
                WHERE close_time IS NOT NULL
                ORDER BY close_time DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        except sqlite3.OperationalError:
            return []


def _fetch_closed_trades(cfg: Config, since: datetime.datetime, limit: int = 500) -> list[TradeOut]:
    out: list[TradeOut] = []
    rows = _fetch_closed_trades_since(cfg, since, limit=limit)
    for r in rows:
        ts = _parse_iso(str(r["close_time"] or ""))
        if ts is None or ts < since:
            continue
        side_raw = (r["side"] or "").upper()
        side: Literal["LONG", "SHORT"] = "SHORT" if side_raw.startswith("S") else "LONG"
        out.append(
            TradeOut(
                symbol=str(r["symbol"]),
                side=side,
                pnl=float(r["pnl"] or 0.0),
                pnlPercent=float(r["pnl_percentage"] or 0.0) or None,
                entryPrice=float(r["entry_price"] or 0.0) or None,
                exitPrice=float(r["exit_price"] or 0.0) or None,
                quantity=float(r["quantity"] or 0.0) or None,
                reason=str(r["reason"]) if r["reason"] else None,
                openedAtIso=str(r["open_time"]) if r["open_time"] else None,
                closedAtIso=ts.isoformat(),
            )
        )
    return out


def _equity_window(cfg: Config, current_balance: float, hours: int) -> tuple[list[EquityPoint], EquityStats]:
    """Reconstructs equity samples + summary stats over the last `hours`.

    Strategy: anchor end of curve at current_balance (now), then walk backwards
    subtracting each closed trade's PnL whose close timestamp falls in window.
    This is a stepped function with one point per trade plus a single anchor at
    now — honest about what the bot persists today.
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now_utc - datetime.timedelta(hours=hours)
    points: list[EquityPoint] = [EquityPoint(t=now_utc.isoformat(), equity=float(current_balance))]
    stats = EquityStats()

    rows = _fetch_closed_trades_since(cfg, cutoff, limit=1000)
    if not rows:
        return points, stats

    running = float(current_balance)
    wins: list[float] = []
    losses: list[float] = []
    for r in rows:
        ts = _parse_iso(str(r["close_time"] or ""))
        if ts is None or ts < cutoff:
            continue
        pnl = float(r["pnl"] or 0.0)
        running = running - pnl  # equity BEFORE this trade
        points.append(EquityPoint(t=ts.isoformat(), equity=running))
        if pnl > 0:
            wins.append(pnl)
        elif pnl < 0:
            losses.append(pnl)

    total_trades = len(wins) + len(losses)
    pnl_abs = float(current_balance) - running  # equity_now - equity_at_window_start
    pnl_pct = (pnl_abs / running * 100.0) if running > 0 else None

    stats = EquityStats(
        winRate=(len(wins) / total_trades) if total_trades > 0 else None,
        tradeCount=total_trades,
        avgWin=(sum(wins) / len(wins)) if wins else None,
        avgLoss=(sum(losses) / len(losses)) if losses else None,
        bestWin=max(wins) if wins else None,
        worstLoss=min(losses) if losses else None,
        pnlAbs=pnl_abs,
        pnlPercent=pnl_pct,
    )

    points.reverse()  # oldest -> newest for the chart
    return points, stats


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────

def build_app(
    cfg: Config,
    *,
    host_identity: HostIdentity,
    credential_store: CredentialStore,
) -> FastAPI:
    app = FastAPI(title="Aribot status", version=VERSION, docs_url=None, redoc_url=None)

    if cfg.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cfg.cors_origins),
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Accept", "Content-Type"],
            allow_credentials=False,
        )

    def _check_token(authorization: Optional[str], expected: Optional[str]) -> None:
        if not expected:
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="ARIBOT_API_TOKEN not configured on the sidecar",
            )
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
        provided = authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")

    def require_token(authorization: Optional[str] = Header(default=None)) -> None:
        _check_token(authorization, cfg.expected_token)

    def require_vault_token(authorization: Optional[str] = Header(default=None)) -> None:
        # If ARIBOT_API_TOKEN_VAULT is unset we fall back to expected_token
        # during load_config, so this just adds a separate verification path
        # callers can split later by setting the env var.
        _check_token(authorization, cfg.expected_vault_token)

    @app.get("/healthz")
    def healthz() -> dict:
        # Liveness for the sidecar; unauthenticated by design.
        return {"ok": True, "version": VERSION}

    @app.get("/status", response_model=StatusOut)
    def get_status(_: None = Depends(require_token)) -> StatusOut:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        snap = _read_snapshot(cfg)
        st, reason = derive_status(snap, cfg, now_utc)

        if snap is None:
            return StatusOut(
                version=VERSION,
                status=st,
                lastCycleIso=now_utc.isoformat(),
                reason=reason,
            )

        started = _parse_iso(str(snap.get("started_at", "")))
        uptime = int((now_utc - started).total_seconds()) if started else 0
        mode_raw = str(snap.get("mode", "PAPER")).upper()
        mode: Mode = mode_raw if mode_raw in ("PAPER", "SHADOW", "LIVE") else "PAPER"

        return StatusOut(
            version=VERSION,
            mode=mode,
            status=st,
            uptimeSeconds=max(0, uptime),
            lastCycleIso=str(snap.get("last_cycle_iso") or snap.get("wrote_at") or now_utc.isoformat()),
            openPositions=int(snap.get("open_positions", 0)),
            currentBalance=float(snap.get("current_balance", 0.0)),
            # Computed sidecar-side, NOT from snapshot.session_pnl — see
            # _compute_todays_pnl for the why. The snapshot field is left in
            # place for other consumers (telegram), but the iOS app gets the
            # accurate computation.
            todaysPnl=_compute_todays_pnl(cfg),
            testnet=bool(snap.get("testnet", False)),
            cycleCount=int(snap.get("cycle_count", 0)),
            runId=str(snap.get("run_id", "")),
            reason=reason,
        )

    @app.get("/positions", response_model=PositionsOut)
    def get_positions(_: None = Depends(require_token)) -> PositionsOut:
        positions = _fetch_open_positions(cfg)
        return PositionsOut(
            positions=positions,
            asOfIso=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

    @app.get("/equity", response_model=EquityOut)
    def get_equity(days: int = 1, _: None = Depends(require_token)) -> EquityOut:
        # Clamp to a sensible range so a runaway client can't ask for 10 years.
        clamped_days = max(1, min(int(days), 30))
        hours = clamped_days * 24
        snap = _read_snapshot(cfg)
        bal = float(snap.get("current_balance", 0.0)) if snap else 0.0
        # Same accurate-todays-pnl logic as /status.
        pnl_today = _compute_todays_pnl(cfg)
        points, stats = _equity_window(cfg, bal, hours)
        return EquityOut(
            points=points,
            todaysPnl=pnl_today,
            rangeHours=hours,
            stats=stats,
        )

    @app.get("/trades", response_model=TradesOut)
    def get_trades(days: int = 7, _: None = Depends(require_token)) -> TradesOut:
        clamped_days = max(1, min(int(days), 30))
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=clamped_days)
        trades = _fetch_closed_trades(cfg, since, limit=500)
        return TradesOut(
            trades=trades,
            asOfIso=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

    @app.post("/start", response_model=ControlOut)
    def post_start(_: None = Depends(require_token)) -> JSONResponse:
        ok, detail, pid = start_bot(cfg, credential_store)
        body = ControlOut(ok=ok, action="start", pid=pid, detail=detail).model_dump()
        # Use a clear HTTP code so the iOS app can distinguish "already running"
        # (409 Conflict) from "credentials missing for LIVE" (412 Precondition
        # Failed) from other failures (500). Successful launch is 202.
        if not ok and pid is not None:
            return JSONResponse(body, status_code=http_status.HTTP_409_CONFLICT)
        if not ok and "iOS-pushed credentials" in detail:
            return JSONResponse(body, status_code=http_status.HTTP_412_PRECONDITION_FAILED)
        if not ok:
            return JSONResponse(body, status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
        return JSONResponse(body, status_code=http_status.HTTP_202_ACCEPTED)

    @app.post("/stop", response_model=ControlOut)
    def post_stop(_: None = Depends(require_token)) -> JSONResponse:
        ok, detail, pid = stop_bot(cfg)
        body = ControlOut(ok=ok, action="stop", pid=pid, detail=detail).model_dump()
        if not ok:
            return JSONResponse(body, status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
        return JSONResponse(body, status_code=http_status.HTTP_202_ACCEPTED)

    @app.post("/kill", response_model=ControlOut)
    def post_kill(_: None = Depends(require_token)) -> JSONResponse:
        # Semantically: emergency kill switch. Same kill_switch.flag file as
        # /stop (per locked-in scope decision), different intent line so the
        # operator can tell the two apart in post-mortem.
        ok, detail, pid = kill_bot(cfg)
        body = ControlOut(ok=ok, action="kill", pid=pid, detail=detail).model_dump()
        if not ok:
            return JSONResponse(body, status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
        return JSONResponse(body, status_code=http_status.HTTP_202_ACCEPTED)

    @app.delete("/kill", response_model=ControlOut)
    def delete_kill(_: None = Depends(require_token)) -> JSONResponse:
        # Idempotent — succeeds even if the flag wasn't present. Operators
        # can call this without first checking; the bot will start cleanly
        # once the flag is gone.
        ok, detail = clear_kill(cfg)
        body = ControlOut(ok=ok, action="clear_kill", pid=None, detail=detail).model_dump()
        if not ok:
            return JSONResponse(body, status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
        return JSONResponse(body, status_code=http_status.HTTP_200_OK)

    @app.post("/mode", response_model=ModeOut)
    def post_mode(body: ModeBody, _: None = Depends(require_token)) -> JSONResponse:
        ok, detail, running_pid, effective = set_bot_mode(cfg, body.mode)
        out = ModeOut(ok=ok, mode=effective, detail=detail, runningPid=running_pid).model_dump()
        if not ok and running_pid is not None:
            # Bot is running → 409 Conflict. iOS surfaces "stop bot first".
            return JSONResponse(out, status_code=http_status.HTTP_409_CONFLICT)
        if not ok:
            return JSONResponse(out, status_code=http_status.HTTP_400_BAD_REQUEST)
        return JSONResponse(out, status_code=http_status.HTTP_200_OK)

    # ──────────────────────────────────────────────────────────────────────
    # Credential vault — iOS-sourced Bybit API keys
    # ──────────────────────────────────────────────────────────────────────

    @app.get("/pubkey", response_model=PubkeyOut)
    def get_pubkey() -> PubkeyOut:
        # Unauthenticated by design: iOS needs the pubkey BEFORE it can prove
        # anything to us. The TLS pinning + TOFU fingerprint match (operator
        # reads it off the sidecar's stdout) is the authentication path here.
        return PubkeyOut(
            publicKey=host_identity.public_key_b64,
            fingerprint=host_identity.fingerprint,
        )

    @app.post("/credentials", response_model=CredentialsAckOut)
    def post_credentials(
        body: CredentialsBody,
        _: None = Depends(require_vault_token),
    ) -> JSONResponse:
        # Resolve current testnet flag from .env so iOS-supplied keys validate
        # against the same Bybit environment the bot will use.
        bybit_testnet = _read_bybit_testnet(cfg)
        result = credential_store.accept_sealed_push(
            ciphertext_b64=body.ciphertext,
            nonce_b64=body.nonce,
            sender_pubkey_b64=body.senderPublicKey,
            timestamp_iso=body.timestampIso,
            counter=body.counter,
            bybit_testnet=bybit_testnet,
        )
        ack = CredentialsAckOut(
            ok=result.ok, detail=result.detail, fingerprint=result.fingerprint
        ).model_dump()
        return JSONResponse(ack, status_code=result.status_code)

    @app.get("/credentials/status", response_model=CredentialsStatusOut)
    def get_credentials_status(_: None = Depends(require_vault_token)) -> CredentialsStatusOut:
        st = credential_store.status()
        return CredentialsStatusOut(
            loaded=st.loaded,
            fingerprint=st.fingerprint,
            source=st.source,
            validatedAtIso=st.validatedAtIso,
        )

    @app.delete("/credentials", response_model=CredentialsAckOut)
    def delete_credentials(_: None = Depends(require_vault_token)) -> CredentialsAckOut:
        credential_store.clear()
        return CredentialsAckOut(ok=True, detail="credentials wiped")

    return app


def _read_bybit_testnet(cfg: Config) -> bool:
    """Mirror SecretLoader's BYBIT_TESTNET parsing without instantiating it.
    Defaults to True (testnet) on any read failure — safer fallback for a
    credential-validation roundtrip.
    """
    try:
        text = cfg.env_file_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return True
    for raw_line in text.splitlines():
        stripped = raw_line.lstrip()
        if stripped.startswith("BYBIT_TESTNET=") or stripped.startswith("export BYBIT_TESTNET="):
            value = stripped.split("=", 1)[1].strip().strip("'\"").lower()
            return value in {"1", "true", "yes", "on"}
    return True


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Aribot status + control HTTP sidecar")
    parser.add_argument("--host", default=os.getenv("STATUS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("STATUS_PORT", "8787")))
    parser.add_argument("--snapshot", default=None)
    parser.add_argument("--kill-switch", default=None)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument(
        "--no-tls",
        action="store_true",
        help="Disable TLS. NOT RECOMMENDED. Only for local-only test rigs.",
    )
    args = parser.parse_args()

    cfg = load_config(args)
    auth_mode = "token (mandatory)" if cfg.expected_token else "OPEN (no token set)"
    if not cfg.expected_token:
        print(
            "[status_server] WARNING: ARIBOT_API_TOKEN is not set. "
            "POST /start and POST /stop are reachable WITHOUT authentication. "
            "Set ARIBOT_API_TOKEN in the environment to lock them down.",
            file=sys.stderr,
        )

    # Generate / load the host's X25519 identity and TLS cert before the
    # sidecar starts. Both surface their fingerprint on stdout so the
    # operator can pin them in the iOS app on first connect.
    cfg.artifact_dir.mkdir(parents=True, exist_ok=True)
    host_identity = get_or_create_identity(cfg.artifact_dir)
    credential_store = CredentialStore(host=host_identity, state_dir=cfg.artifact_dir)

    tls_artifacts: Optional[TlsArtifacts] = None
    if not args.no_tls:
        tls_artifacts = ensure_tls(cfg.artifact_dir)
        print(
            f"[status_server] TLS cert SHA-256: {tls_artifacts.fingerprint_sha256_hex}",
            file=sys.stderr,
        )
    else:
        print(
            "[status_server] WARNING: --no-tls set. Bearer token and credential "
            "ciphertext will travel cleartext. iOS will reject the connection "
            "unless cert pinning is disabled on that side too.",
            file=sys.stderr,
        )

    scheme = "https" if tls_artifacts is not None else "http"
    print(
        f"[status_server] version={VERSION} bind={scheme}://{args.host}:{args.port} "
        f"snapshot={cfg.snapshot_path} kill_switch={cfg.kill_switch_path} "
        f"db={cfg.db_path} auth={auth_mode} "
        f"host_pubkey_fp={host_identity.fingerprint}"
    )

    import uvicorn

    app = build_app(cfg, host_identity=host_identity, credential_store=credential_store)
    uvicorn_kwargs: dict[str, object] = dict(
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    if tls_artifacts is not None:
        uvicorn_kwargs["ssl_keyfile"] = str(tls_artifacts.key_path)
        uvicorn_kwargs["ssl_certfile"] = str(tls_artifacts.cert_path)
    uvicorn.run(app, **uvicorn_kwargs)


if __name__ == "__main__":
    main()
