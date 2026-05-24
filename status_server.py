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
from typing import Callable, Dict, Iterable, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status as http_status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

try:
    import psutil
except ImportError as exc:
    raise SystemExit(
        "status_server requires psutil. Install with: pip install -r requirements-status-server.txt"
    ) from exc

from auth_supabase import (
    AuthUser,
    LEGACY_OPS_ID,
    SupabaseJwtVerifier,
    make_require_user,
    make_require_user_jwt_only,
    make_require_user_legacy_only,
)
from bot_keypair import HostIdentity, get_or_create_identity
from credential_pipe import CredentialServer
from credential_store import CredentialStore
from meta_db import MetaDb
from tenant_registry import (
    BotProcessHandle,
    InvalidTenantId,
    TenantPaths,
    TenantRegistry,
)
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


def _read_snapshot_at(snapshot_path: Path) -> Optional[dict]:
    """Read the bot's status snapshot JSON at `snapshot_path`. Returns None
    on missing file, OS error, or invalid JSON. Used by both legacy
    (cfg.snapshot_path) and tenant (ctx.paths.status) code paths."""
    try:
        raw = snapshot_path.read_text(encoding="utf-8-sig")
    except (FileNotFoundError, OSError):
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _read_snapshot(cfg: Config) -> Optional[dict]:
    """Legacy single-tenant snapshot reader. Callers in tenant mode use
    `_read_snapshot_at(ctx.paths.status)` directly."""
    return _read_snapshot_at(cfg.snapshot_path)


def _resolve_legacy_db_path(cfg: Config) -> Path:
    """Pick the right sqlite file in legacy single-tenant mode. The bot
    writes the resolved path to its snapshot (`db_file` field). Prefer that
    — it's the source of truth for "the file the bot currently has open."
    Fall back to cfg.db_path for backward compat (e.g. fresh install with
    no snapshot yet).

    Multi-tenant callers do NOT use this helper — they call
    `ctx.db_path()` directly, which is unambiguous from the user_id +
    BOT_MODE.
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


def _open_db_at(db_path: Path) -> sqlite3.Connection:
    """Read-only sqlite3 connection at the given path. Used by both legacy
    and tenant code paths — the only difference is who computed the path."""
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
# Tenant context + per-user resources
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TenantContext:
    """Resolved per-request tenant view: the user_id, their TenantPaths,
    their BOT_MODE (from the per-tenant config.json), and BYBIT_TESTNET.

    Built once per HTTP request via `_resolve_tenant` from the verified JWT
    `sub`. Endpoints pass this around instead of re-reading registry state.
    """

    user_id: str
    paths: TenantPaths
    mode: str          # 'paper' | 'shadow' | 'live'
    testnet: bool

    def db_path(self) -> Path:
        return self.paths.db(self.mode)


def _resolve_tenant(registry: TenantRegistry, user_id: str) -> TenantContext:
    """Build a TenantContext for `user_id`. Validates the user_id shape via
    `paths_for` (raises InvalidTenantId on a bad UUID) and reads per-tenant
    BOT_MODE / BYBIT_TESTNET from `config.json`."""
    paths = registry.paths_for(user_id)
    return TenantContext(
        user_id=user_id,
        paths=paths,
        mode=registry.get_mode(user_id),
        testnet=registry.get_testnet(user_id),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Process control — start/stop bot (per-tenant locking)
# ─────────────────────────────────────────────────────────────────────────────


class _PerUserBotLocks:
    """One single-flight lock per user_id. The legacy sentinel
    `LEGACY_OPS_ID` gets its own lock so the legacy code path retains the
    "one bot at a time" guarantee. Two distinct tenants get distinct locks
    and can /start in parallel."""

    def __init__(self) -> None:
        self._locks: Dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, user_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(user_id, threading.Lock())


_per_user_locks = _PerUserBotLocks()


def _read_pid_file(path: Path) -> Optional[int]:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _running_bot_pid_legacy(cfg: Config) -> Optional[int]:
    """Returns the PID of the running legacy single-tenant bot, or None.

    Trusts the snapshot file first (the bot itself wrote its own PID there),
    falls back to the sidecar's pid file. Either way, psutil confirms
    liveness so a stale PID isn't reported as alive.
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


def _running_bot_pid_tenant(ctx: TenantContext) -> Optional[int]:
    """Returns the PID of the tenant's running bot, or None. Same logic as
    legacy but reads from per-tenant snapshot + pid paths."""
    snap = _read_snapshot_at(ctx.paths.status)
    if snap:
        pid = int(snap.get("pid", 0))
        if pid and _pid_alive(pid):
            return pid
    file_pid = _read_pid_file(ctx.paths.pid)
    if file_pid and _pid_alive(file_pid):
        return file_pid
    return None


def _read_bot_mode(cfg: Config) -> str:
    """Reads BOT_MODE from .env (legacy single-tenant only). Returns
    lower-case 'paper' on any read failure — the bot itself would do the
    same, and PAPER is the safe default for credential-gating decisions.

    Multi-tenant callers use `registry.get_mode(user_id)` instead, which
    reads from the per-tenant config.json.
    """
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


def start_bot(
    cfg: Config,
    credential_store: CredentialStore,
    user: AuthUser,
    *,
    registry: Optional[TenantRegistry] = None,
    meta_db: Optional[MetaDb] = None,
) -> tuple[bool, str, Optional[int]]:
    """Launch the bot for the given user.

    Legacy mode (`user.is_legacy`): writes to cfg.bot_pid_path and
    cfg.bot_log_path, reads BOT_MODE from .env, uses LEGACY_OPS_ID for
    credential lookup. Behaviour identical to pre-Phase-4.

    Tenant mode: writes to ctx.paths.pid and ctx.paths.root/bot.launcher.log,
    reads mode from registry.get_mode(user.id), uses user.id for credentials,
    sets ARIBOT_USER_ID + ARIBOT_ARTIFACT_DIR in spawn env so the bot routes
    every per-tenant artifact through TenantRegistry (Phase 3).
    """
    is_legacy = user.is_legacy
    if not is_legacy and (registry is None or meta_db is None):
        return False, "tenant start_bot requires registry and meta_db", None

    user_id = user.id
    ctx: Optional[TenantContext] = None
    if not is_legacy:
        try:
            ctx = _resolve_tenant(registry, user_id)  # type: ignore[arg-type]
        except InvalidTenantId as exc:
            return False, f"invalid user_id: {exc}", None

    lock = _per_user_locks.get(user_id)
    if not lock.acquire(timeout=1.0):
        return False, "another start request is in flight", None
    try:
        if is_legacy:
            existing = _running_bot_pid_legacy(cfg)
            kill_path = cfg.kill_switch_path
            bot_mode = _read_bot_mode(cfg)
            pid_path = cfg.bot_pid_path
            log_path = cfg.bot_log_path
        else:
            assert ctx is not None
            existing = _running_bot_pid_tenant(ctx)
            kill_path = ctx.paths.kill_switch
            bot_mode = ctx.mode
            pid_path = ctx.paths.pid
            log_path = ctx.paths.root / "bot.launcher.log"

        if existing is not None:
            return False, f"bot already running (pid {existing})", existing

        # If a kill switch is still on disk, refuse to start — the operator
        # set it intentionally, the bot would just exit again immediately.
        if kill_path.exists():
            return (
                False,
                f"kill switch present at {kill_path} — remove before starting",
                None,
            )

        # LIVE-mode credential guard. LIVE refuses to start without iOS-pushed
        # credentials FOR THIS user. PAPER/SHADOW stay permissive.
        cred_handle = None
        cred_server: Optional[CredentialServer] = None
        if credential_store.is_loaded(user_id):
            cred_server = CredentialServer()
            cred_handle = cred_server.start(credential_store.snapshot(user_id))
        elif bot_mode == "live":
            return (
                False,
                "LIVE mode refuses to start without iOS-pushed credentials. "
                "Open the iOS app and submit Bybit keys, then retry.",
                None,
            )

        # Open the log file in append mode so we don't clobber prior launch logs.
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_fh = log_path.open("ab", buffering=0)
        except OSError as exc:
            if cred_server is not None:
                cred_server.close()
            return False, f"could not open log file {log_path}: {exc}", None

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
        # Tenant routing: tell the spawned bot who it's running for. The
        # bot's __main__ resolves all per-tenant paths from these env vars
        # (Phase 3). In legacy mode we explicitly clear them so a stale
        # env doesn't accidentally place files under tenants/.
        if is_legacy:
            spawn_env.pop("ARIBOT_USER_ID", None)
        else:
            spawn_env["ARIBOT_USER_ID"] = user_id
            spawn_env["ARIBOT_ARTIFACT_DIR"] = str(cfg.artifact_dir)

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
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(proc.pid), encoding="utf-8")
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

        # Tenant-mode bookkeeping: meta.db audit trail + in-memory registry.
        if not is_legacy and meta_db is not None and registry is not None:
            try:
                meta_db.ensure_tenant(user_id)
                run_id = (
                    f"sidecar-{proc.pid}-"
                    f"{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}"
                )
                meta_db.record_run_start(user_id, run_id)
                meta_db.record_audit(user_id, "start", {"mode": bot_mode, "pid": proc.pid})
            except Exception as exc:  # never fail a start because of audit
                run_id = ""
                print(f"[status_server] meta_db record_run_start failed: {exc}", file=sys.stderr)
            registry.remember_running(
                BotProcessHandle(
                    user_id=user_id,
                    pid=proc.pid,
                    mode_at_start=bot_mode,
                    run_id=run_id,
                )
            )

        return True, f"bot launched (pid {proc.pid})", proc.pid
    finally:
        try:
            lock.release()
        except RuntimeError:
            pass


def _write_kill_switch_at(kill_path: Path, intent: Literal["stop", "kill"]) -> Optional[str]:
    """Atomically write a kill switch file. Returns None on success or an
    error string on failure. The bot's kill detector only checks file
    presence, but the intent string is captured for forensic clarity so
    operators can tell after the fact whether the flag came from a graceful
    /stop or an emergency /kill.
    """
    try:
        kill_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = kill_path.with_suffix(kill_path.suffix + ".tmp")
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        tmp.write_text(
            f"intent: {intent}\ncreated_by: status_server\ncreated_at: {now_iso}\n",
            encoding="utf-8",
        )
        os.replace(tmp, kill_path)
        return None
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"


def stop_bot(
    cfg: Config,
    user: AuthUser,
    *,
    registry: Optional[TenantRegistry] = None,
    meta_db: Optional[MetaDb] = None,
) -> tuple[bool, str, Optional[int]]:
    if user.is_legacy:
        kill_path = cfg.kill_switch_path
        pid = _running_bot_pid_legacy(cfg)
    else:
        if registry is None:
            return False, "tenant stop_bot requires registry", None
        try:
            ctx = _resolve_tenant(registry, user.id)
        except InvalidTenantId as exc:
            return False, f"invalid user_id: {exc}", None
        kill_path = ctx.paths.kill_switch
        pid = _running_bot_pid_tenant(ctx)

    err = _write_kill_switch_at(kill_path, "stop")
    if err is not None:
        return False, f"could not write kill switch: {err}", pid

    if not user.is_legacy and meta_db is not None:
        try:
            meta_db.record_audit(user.id, "stop", {"pid": pid})
        except Exception as exc:
            print(f"[status_server] meta_db record_audit(stop) failed: {exc}", file=sys.stderr)

    if pid is None:
        return True, "kill switch written; no running bot detected", None
    return True, f"kill switch written; bot pid {pid} will exit at next cycle", pid


def kill_bot(
    cfg: Config,
    user: AuthUser,
    *,
    registry: Optional[TenantRegistry] = None,
    meta_db: Optional[MetaDb] = None,
) -> tuple[bool, str, Optional[int]]:
    """Trip the kill switch. Same file as stop_bot, different intent line.
    The bot's kill detector treats both the same way — it exits at the next
    cycle. The intent line lets operators distinguish in post-mortem logs.
    """
    if user.is_legacy:
        kill_path = cfg.kill_switch_path
        pid = _running_bot_pid_legacy(cfg)
    else:
        if registry is None:
            return False, "tenant kill_bot requires registry", None
        try:
            ctx = _resolve_tenant(registry, user.id)
        except InvalidTenantId as exc:
            return False, f"invalid user_id: {exc}", None
        kill_path = ctx.paths.kill_switch
        pid = _running_bot_pid_tenant(ctx)

    err = _write_kill_switch_at(kill_path, "kill")
    if err is not None:
        return False, f"could not write kill switch: {err}", pid

    if not user.is_legacy and meta_db is not None:
        try:
            meta_db.record_audit(user.id, "kill", {"pid": pid})
        except Exception as exc:
            print(f"[status_server] meta_db record_audit(kill) failed: {exc}", file=sys.stderr)

    if pid is None:
        return True, "kill switch tripped; no running bot detected", None
    return True, f"kill switch tripped; bot pid {pid} will exit at next cycle", pid


def clear_kill(
    cfg: Config,
    user: AuthUser,
    *,
    registry: Optional[TenantRegistry] = None,
    meta_db: Optional[MetaDb] = None,
) -> tuple[bool, str]:
    """Remove the kill switch flag. Returns ok=True even if the flag didn't
    exist (idempotent) — the goal is a clear state, not a removal action.
    """
    if user.is_legacy:
        kill_path = cfg.kill_switch_path
    else:
        if registry is None:
            return False, "tenant clear_kill requires registry"
        try:
            ctx = _resolve_tenant(registry, user.id)
        except InvalidTenantId as exc:
            return False, f"invalid user_id: {exc}"
        kill_path = ctx.paths.kill_switch

    try:
        kill_path.unlink(missing_ok=True)
    except OSError as exc:
        return False, f"could not clear kill switch: {type(exc).__name__}: {exc}"

    if not user.is_legacy and meta_db is not None:
        try:
            meta_db.record_audit(user.id, "clear_kill", {})
        except Exception as exc:
            print(f"[status_server] meta_db record_audit(clear_kill) failed: {exc}", file=sys.stderr)

    return True, "kill switch cleared"


# ─────────────────────────────────────────────────────────────────────────────
# Mode persistence — atomic update to .env preserving comments + other keys.
# ─────────────────────────────────────────────────────────────────────────────

_VALID_MODES = ("paper", "shadow", "live")


def set_bot_mode(
    cfg: Config,
    user: AuthUser,
    requested_mode: str,
    *,
    registry: Optional[TenantRegistry] = None,
    meta_db: Optional[MetaDb] = None,
) -> tuple[bool, str, Optional[int], Optional[str]]:
    """Update BOT_MODE for the given user.

    Returns (ok, detail, running_pid, effective_mode).

    Legacy mode (`user.is_legacy`): rewrites BOT_MODE in cfg.env_file_path
    atomically, preserving comments + other keys. Refuses if the legacy
    bot is currently running.

    Tenant mode: writes the new mode to the tenant's config.json via
    registry.set_mode(user.id, mode). Refuses if THAT user's bot is
    currently running. Other tenants are unaffected.

    Mode change while running would be a silent no-op until restart, hence
    the running-bot refusal in both code paths.
    """
    norm = (requested_mode or "").strip().lower()
    if norm not in _VALID_MODES:
        return False, f"invalid mode '{requested_mode}'; must be one of {_VALID_MODES}", None, None

    if user.is_legacy:
        running = _running_bot_pid_legacy(cfg)
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

    # Tenant mode.
    if registry is None:
        return False, "tenant set_bot_mode requires registry", None, None
    try:
        ctx = _resolve_tenant(registry, user.id)
    except InvalidTenantId as exc:
        return False, f"invalid user_id: {exc}", None, None

    running = _running_bot_pid_tenant(ctx)
    if running is not None:
        return (
            False,
            f"bot is currently running (pid {running}); stop it first via POST /stop",
            running,
            None,
        )

    try:
        registry.set_mode(user.id, norm)
    except ValueError as exc:
        return False, f"could not set mode: {exc}", None, None

    if meta_db is not None:
        try:
            meta_db.record_audit(user.id, "mode_change", {"mode": norm})
        except Exception as exc:
            print(f"[status_server] meta_db record_audit(mode_change) failed: {exc}", file=sys.stderr)

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

def _leverage_lookup(repo_root: Path) -> dict[str, float]:
    """Read leverage_buckets.json to derive per-symbol leverage.

    Currently a global config (every tenant shares the same buckets). Per-
    user leverage overrides are a follow-up — the registry's per-tenant
    config.json is the place they'd land. For now: same lookup table for
    every endpoint, regardless of legacy or tenant mode.
    """
    path = repo_root / "leverage_buckets.json"
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


def _fetch_open_positions(db_path: Path, lev_lookup: dict[str, float]) -> list[PositionOut]:
    if not db_path.exists():
        return []
    out: list[PositionOut] = []

    with _open_db_at(db_path) as db:
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


def _compute_todays_pnl(db_path: Path, lev_lookup: dict[str, float]) -> float:
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
    for row in _fetch_closed_trades_since(db_path, midnight, limit=1000):
        ts = _parse_iso(str(row["close_time"] or ""))
        if ts is None or ts < midnight:
            continue
        realized += float(row["pnl"] or 0.0)

    unrealized = 0.0
    for p in _fetch_open_positions(db_path, lev_lookup):
        unrealized += float(p.pnl or 0.0)

    return realized + unrealized


def _fetch_closed_trades_since(db_path: Path, since: datetime.datetime, limit: int = 500) -> list[sqlite3.Row]:
    """Returns closed_trades rows from `since` -> now, newest first.

    Used by both /trades and /equity. Empty list on schema mismatch or missing
    db — never raises, so callers can render an empty UI state.
    """
    if not db_path.exists():
        return []
    with _open_db_at(db_path) as db:
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


def _fetch_closed_trades(db_path: Path, since: datetime.datetime, limit: int = 500) -> list[TradeOut]:
    out: list[TradeOut] = []
    rows = _fetch_closed_trades_since(db_path, since, limit=limit)
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


def _equity_window(db_path: Path, current_balance: float, hours: int) -> tuple[list[EquityPoint], EquityStats]:
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

    rows = _fetch_closed_trades_since(db_path, cutoff, limit=1000)
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
    registry: Optional[TenantRegistry] = None,
    meta_db: Optional[MetaDb] = None,
    jwt_verifier: Optional[SupabaseJwtVerifier] = None,
) -> FastAPI:
    """Build the FastAPI app.

    Multi-tenant mode: pass `registry`, `meta_db`, and `jwt_verifier`. Every
    endpoint authenticates via Supabase JWT and scopes per-tenant. Legacy
    bearer-token requests are also accepted via `cfg.expected_token` and
    routed through the legacy single-tenant code paths (paths in `cfg`).

    Legacy-only mode: pass `jwt_verifier=None`. Only the legacy bearer
    token works. Endpoints behave exactly as pre-Phase-4. Useful for
    `--legacy-single-user` ops fallback.
    """
    app = FastAPI(title="Aribot status", version=VERSION, docs_url=None, redoc_url=None)

    multi_tenant = jwt_verifier is not None
    if multi_tenant and (registry is None or meta_db is None):
        raise RuntimeError(
            "build_app: jwt_verifier requires registry and meta_db (multi-tenant mode)"
        )

    if cfg.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cfg.cors_origins),
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Accept", "Content-Type"],
            allow_credentials=False,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Auth dependencies. Two flavors:
    #
    #   require_user        — accepts JWT (returns AuthUser with real id)
    #                         OR legacy bearer (returns sentinel AuthUser
    #                         with id=LEGACY_OPS_ID). Used by every
    #                         endpoint that is meaningful in both modes.
    #
    #   require_user_jwt    — accepts ONLY JWT. Used by /credentials* in
    #                         multi-tenant mode so a leaked legacy bearer
    #                         token cannot push or wipe a tenant's keys.
    #                         In legacy-only mode this falls back to the
    #                         vault token (which is the legacy bearer or
    #                         a separate ARIBOT_API_TOKEN_VAULT).
    # ──────────────────────────────────────────────────────────────────────
    if multi_tenant:
        require_user = make_require_user(
            jwt_verifier, allow_legacy_token=cfg.expected_token  # type: ignore[arg-type]
        )
        require_user_jwt = make_require_user_jwt_only(jwt_verifier)  # type: ignore[arg-type]
    else:
        require_user = make_require_user_legacy_only(cfg.expected_token)
        # In legacy-only mode, /credentials* uses the vault token (which
        # falls back to expected_token when no separate vault token is set).
        require_user_jwt = make_require_user_legacy_only(cfg.expected_vault_token)

    @app.get("/healthz")
    def healthz() -> dict:
        # Liveness for the sidecar; unauthenticated by design.
        return {"ok": True, "version": VERSION, "multiTenant": multi_tenant}

    # ──────────────────────────────────────────────────────────────────────
    # Tenant resolution helpers (closures so they can read registry).
    # ──────────────────────────────────────────────────────────────────────

    def _tenant_db_path(user: AuthUser) -> Path:
        if user.is_legacy:
            return _resolve_legacy_db_path(cfg)
        ctx = _resolve_tenant(registry, user.id)  # type: ignore[arg-type]
        return ctx.paths.db(ctx.mode)

    def _tenant_snapshot(user: AuthUser) -> Optional[dict]:
        if user.is_legacy:
            return _read_snapshot(cfg)
        ctx = _resolve_tenant(registry, user.id)  # type: ignore[arg-type]
        return _read_snapshot_at(ctx.paths.status)

    def _tenant_kill_path(user: AuthUser) -> Path:
        if user.is_legacy:
            return cfg.kill_switch_path
        ctx = _resolve_tenant(registry, user.id)  # type: ignore[arg-type]
        return ctx.paths.kill_switch

    def _derive_status_for(user: AuthUser, snap: Optional[dict], now_utc: datetime.datetime) -> tuple[Status, Optional[str]]:
        kill_path = _tenant_kill_path(user)
        if kill_path.exists():
            return "killed", f"kill_switch_present:{kill_path.name}"
        if snap is None:
            return "stopped", "snapshot_missing"
        pid = int(snap.get("pid", 0))
        if pid and not _pid_alive(pid):
            return "error", f"pid_dead:{pid}"
        wrote_at = _parse_iso(str(snap.get("wrote_at", "")))
        if wrote_at is None:
            return "error", "snapshot_wrote_at_unparseable"
        interval = float(snap.get("loop_interval_seconds", 60))
        age_s = (now_utc - wrote_at).total_seconds()
        if age_s > interval * cfg.stale_multiplier:
            return "error", f"snapshot_stale:{age_s:.0f}s>{interval * cfg.stale_multiplier:.0f}s"
        return "running", None

    @app.get("/status", response_model=StatusOut)
    def get_status(user: AuthUser = Depends(require_user)) -> StatusOut:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            snap = _tenant_snapshot(user)
            st, reason = _derive_status_for(user, snap, now_utc)
            db_path = _tenant_db_path(user)
            lev = _leverage_lookup(cfg.bot_cwd)
        except InvalidTenantId as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # The bot's runtime status snapshot is the authoritative source of
        # truth for `mode` ONLY while a bot is running. For a tenant with
        # no snapshot (never started, or bot stopped before writing one),
        # fall back to the persisted preference in the tenant's
        # config.json. Otherwise a user who clicks "Shadow" in the UI
        # before they've ever started a bot keeps seeing "Paper" — which
        # was the actual reported bug.
        if not user.is_legacy and registry is not None:
            try:
                persisted_mode: Mode = registry.get_mode(user.id).upper()  # type: ignore[assignment]
                if persisted_mode not in ("PAPER", "SHADOW", "LIVE"):
                    persisted_mode = "PAPER"
            except Exception:
                persisted_mode = "PAPER"
        else:
            persisted_mode = "PAPER"

        if snap is None:
            return StatusOut(
                version=VERSION,
                mode=persisted_mode,
                status=st,
                lastCycleIso=now_utc.isoformat(),
                reason=reason,
            )

        started = _parse_iso(str(snap.get("started_at", "")))
        uptime = int((now_utc - started).total_seconds()) if started else 0
        mode_raw = str(snap.get("mode", persisted_mode)).upper()
        mode: Mode = mode_raw if mode_raw in ("PAPER", "SHADOW", "LIVE") else persisted_mode

        return StatusOut(
            version=VERSION,
            mode=mode,
            status=st,
            uptimeSeconds=max(0, uptime),
            lastCycleIso=str(snap.get("last_cycle_iso") or snap.get("wrote_at") or now_utc.isoformat()),
            openPositions=int(snap.get("open_positions", 0)),
            currentBalance=float(snap.get("current_balance", 0.0)),
            todaysPnl=_compute_todays_pnl(db_path, lev),
            testnet=bool(snap.get("testnet", False)),
            cycleCount=int(snap.get("cycle_count", 0)),
            runId=str(snap.get("run_id", "")),
            reason=reason,
        )

    @app.get("/positions", response_model=PositionsOut)
    def get_positions(user: AuthUser = Depends(require_user)) -> PositionsOut:
        try:
            db_path = _tenant_db_path(user)
        except InvalidTenantId as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        lev = _leverage_lookup(cfg.bot_cwd)
        positions = _fetch_open_positions(db_path, lev)
        return PositionsOut(
            positions=positions,
            asOfIso=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

    @app.get("/equity", response_model=EquityOut)
    def get_equity(days: int = 1, user: AuthUser = Depends(require_user)) -> EquityOut:
        # Clamp to a sensible range so a runaway client can't ask for 10 years.
        clamped_days = max(1, min(int(days), 30))
        hours = clamped_days * 24
        try:
            snap = _tenant_snapshot(user)
            db_path = _tenant_db_path(user)
        except InvalidTenantId as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        bal = float(snap.get("current_balance", 0.0)) if snap else 0.0
        lev = _leverage_lookup(cfg.bot_cwd)
        pnl_today = _compute_todays_pnl(db_path, lev)
        points, stats = _equity_window(db_path, bal, hours)
        return EquityOut(
            points=points,
            todaysPnl=pnl_today,
            rangeHours=hours,
            stats=stats,
        )

    @app.get("/trades", response_model=TradesOut)
    def get_trades(days: int = 7, user: AuthUser = Depends(require_user)) -> TradesOut:
        clamped_days = max(1, min(int(days), 30))
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=clamped_days)
        try:
            db_path = _tenant_db_path(user)
        except InvalidTenantId as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        trades = _fetch_closed_trades(db_path, since, limit=500)
        return TradesOut(
            trades=trades,
            asOfIso=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

    @app.post("/start", response_model=ControlOut)
    def post_start(user: AuthUser = Depends(require_user)) -> JSONResponse:
        ok, detail, pid = start_bot(
            cfg, credential_store, user, registry=registry, meta_db=meta_db
        )
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
    def post_stop(user: AuthUser = Depends(require_user)) -> JSONResponse:
        ok, detail, pid = stop_bot(cfg, user, registry=registry, meta_db=meta_db)
        body = ControlOut(ok=ok, action="stop", pid=pid, detail=detail).model_dump()
        if not ok:
            return JSONResponse(body, status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
        return JSONResponse(body, status_code=http_status.HTTP_202_ACCEPTED)

    @app.post("/kill", response_model=ControlOut)
    def post_kill(user: AuthUser = Depends(require_user)) -> JSONResponse:
        # Semantically: emergency kill switch. Same kill_switch.flag file as
        # /stop (per locked-in scope decision), different intent line so the
        # operator can tell the two apart in post-mortem.
        ok, detail, pid = kill_bot(cfg, user, registry=registry, meta_db=meta_db)
        body = ControlOut(ok=ok, action="kill", pid=pid, detail=detail).model_dump()
        if not ok:
            return JSONResponse(body, status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
        return JSONResponse(body, status_code=http_status.HTTP_202_ACCEPTED)

    @app.delete("/kill", response_model=ControlOut)
    def delete_kill(user: AuthUser = Depends(require_user)) -> JSONResponse:
        # Idempotent — succeeds even if the flag wasn't present.
        ok, detail = clear_kill(cfg, user, registry=registry, meta_db=meta_db)
        body = ControlOut(ok=ok, action="clear_kill", pid=None, detail=detail).model_dump()
        if not ok:
            return JSONResponse(body, status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
        return JSONResponse(body, status_code=http_status.HTTP_200_OK)

    @app.post("/mode", response_model=ModeOut)
    def post_mode(
        body: ModeBody,
        user: AuthUser = Depends(require_user),
    ) -> JSONResponse:
        ok, detail, running_pid, effective = set_bot_mode(
            cfg, user, body.mode, registry=registry, meta_db=meta_db
        )
        out = ModeOut(ok=ok, mode=effective, detail=detail, runningPid=running_pid).model_dump()
        if not ok and running_pid is not None:
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
        # anything to us. TLS pinning + TOFU fingerprint match (operator reads
        # it off the sidecar's stdout) is the authentication path here.
        return PubkeyOut(
            publicKey=host_identity.public_key_b64,
            fingerprint=host_identity.fingerprint,
        )

    @app.post("/credentials", response_model=CredentialsAckOut)
    def post_credentials(
        body: CredentialsBody,
        user: AuthUser = Depends(require_user_jwt),
    ) -> JSONResponse:
        # Resolve current testnet flag from per-tenant config (or legacy .env).
        if user.is_legacy:
            bybit_testnet = _read_bybit_testnet(cfg)
        else:
            try:
                bybit_testnet = registry.get_testnet(user.id)  # type: ignore[union-attr]
            except InvalidTenantId as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        result = credential_store.accept_sealed_push(
            user_id=user.id,
            ciphertext_b64=body.ciphertext,
            nonce_b64=body.nonce,
            sender_pubkey_b64=body.senderPublicKey,
            timestamp_iso=body.timestampIso,
            counter=body.counter,
            bybit_testnet=bybit_testnet,
        )
        if result.ok and not user.is_legacy and meta_db is not None:
            try:
                meta_db.ensure_tenant(user.id)
                meta_db.record_audit(
                    user.id, "creds_pushed", {"fingerprint": result.fingerprint}
                )
            except Exception as exc:
                print(
                    f"[status_server] meta_db record_audit(creds_pushed) failed: {exc}",
                    file=sys.stderr,
                )
        ack = CredentialsAckOut(
            ok=result.ok, detail=result.detail, fingerprint=result.fingerprint
        ).model_dump()
        return JSONResponse(ack, status_code=result.status_code)

    @app.get("/credentials/status", response_model=CredentialsStatusOut)
    def get_credentials_status(
        user: AuthUser = Depends(require_user_jwt),
    ) -> CredentialsStatusOut:
        st = credential_store.status(user.id)
        return CredentialsStatusOut(
            loaded=st.loaded,
            fingerprint=st.fingerprint,
            source=st.source,
            validatedAtIso=st.validatedAtIso,
        )

    @app.delete("/credentials", response_model=CredentialsAckOut)
    def delete_credentials(
        user: AuthUser = Depends(require_user_jwt),
    ) -> CredentialsAckOut:
        credential_store.clear(user.id)
        if not user.is_legacy and meta_db is not None:
            try:
                meta_db.record_audit(user.id, "creds_wiped", {})
            except Exception as exc:
                print(
                    f"[status_server] meta_db record_audit(creds_wiped) failed: {exc}",
                    file=sys.stderr,
                )
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
# Sidecar startup reconciliation
# ─────────────────────────────────────────────────────────────────────────────


def _reconcile_running_bots_on_boot(
    registry: TenantRegistry,
    *,
    out: Optional[Iterable[str]] = None,
) -> int:
    """Walk every tenant directory on disk, check for a live bot PID, and
    rebuild the in-memory `BotProcessHandle` registry accordingly. Stale
    pid files (PID gone) are unlinked so subsequent /status reports
    "stopped" instead of "error pid_dead".

    Called once at sidecar startup before uvicorn binds. Returns the count
    of tenants found running (for the operator-facing log line).
    """
    found = 0
    for user_id, pid in registry.iter_tenants_with_pid():
        paths = registry.paths_for(user_id)
        if pid is None:
            continue
        if _pid_alive(pid):
            registry.remember_running(
                BotProcessHandle(
                    user_id=user_id,
                    pid=pid,
                    mode_at_start=registry.get_mode(user_id),
                    run_id="",  # we didn't witness the launch
                )
            )
            found += 1
            print(
                f"[status_server] reconciled running bot user={user_id[:8]}… pid={pid}",
                file=sys.stderr,
            )
        else:
            try:
                paths.pid.unlink(missing_ok=True)
            except OSError:
                pass
    return found


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
    parser.add_argument(
        "--legacy-single-user",
        action="store_true",
        default=os.getenv("ARIBOT_LEGACY_SINGLE_USER", "").lower() in {"1", "true", "yes", "on"},
        help=(
            "Disable multi-tenant routing. Endpoints accept ONLY the legacy "
            "ARIBOT_API_TOKEN bearer and operate on the single-tenant paths "
            "in cfg. Useful as an ops fallback during the multi-tenant "
            "migration. Will be removed in Phase 5+."
        ),
    )
    args = parser.parse_args()

    cfg = load_config(args)
    auth_mode = "token (mandatory)" if cfg.expected_token else "OPEN (no token set)"
    if not cfg.expected_token:
        print(
            "[status_server] WARNING: ARIBOT_API_TOKEN is not set. "
            "Endpoints reachable WITHOUT authentication. "
            "Set ARIBOT_API_TOKEN in the environment to lock them down.",
            file=sys.stderr,
        )

    # ──────────────────────────────────────────────────────────────────
    # Multi-tenant wiring. When --legacy-single-user is NOT set, require
    # SUPABASE_URL + SUPABASE_JWT_SECRET and instantiate the multi-tenant
    # stack (TenantRegistry + MetaDb + JWT verifier). With the flag, the
    # sidecar runs in legacy mode (current single-tenant behavior).
    # ──────────────────────────────────────────────────────────────────
    registry: Optional[TenantRegistry] = None
    meta_db: Optional[MetaDb] = None
    jwt_verifier: Optional[SupabaseJwtVerifier] = None
    if args.legacy_single_user:
        print(
            "[status_server] DEPRECATED: --legacy-single-user (or "
            "ARIBOT_LEGACY_SINGLE_USER=1) is for ops emergencies only. "
            "Multi-tenant mode is the supported configuration; the legacy "
            "flag will be removed in a future release. To switch to "
            "multi-tenant: set SUPABASE_URL and SUPABASE_JWT_SECRET in the "
            "environment and remove the flag.",
            file=sys.stderr,
        )
    if not args.legacy_single_user:
        supabase_url = os.getenv("SUPABASE_URL", "").strip()
        supabase_jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()
        if not supabase_url or not supabase_jwt_secret:
            print(
                "[status_server] ERROR: multi-tenant mode requires "
                "SUPABASE_URL and SUPABASE_JWT_SECRET to be set. Either set "
                "them in the environment, or pass --legacy-single-user (or "
                "ARIBOT_LEGACY_SINGLE_USER=1) to opt out.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        registry = TenantRegistry(cfg.artifact_dir)
        meta_db = MetaDb(registry.meta_db_path)
        jwt_verifier = SupabaseJwtVerifier(
            jwt_secret=supabase_jwt_secret, supabase_url=supabase_url
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

    if registry is not None:
        running_count = _reconcile_running_bots_on_boot(registry)
        print(
            f"[status_server] reconciled {running_count} running bot(s) "
            f"across {len(registry.all_known_tenants())} known tenant(s)",
            file=sys.stderr,
        )

    scheme = "https" if tls_artifacts is not None else "http"
    tenancy = "multi-tenant" if registry is not None else "legacy single-user"
    print(
        f"[status_server] version={VERSION} bind={scheme}://{args.host}:{args.port} "
        f"snapshot={cfg.snapshot_path} kill_switch={cfg.kill_switch_path} "
        f"db={cfg.db_path} auth={auth_mode} mode={tenancy} "
        f"host_pubkey_fp={host_identity.fingerprint}"
    )

    import uvicorn

    app = build_app(
        cfg,
        host_identity=host_identity,
        credential_store=credential_store,
        registry=registry,
        meta_db=meta_db,
        jwt_verifier=jwt_verifier,
    )
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
