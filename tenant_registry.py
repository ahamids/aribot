"""Per-user resource layout + bot-process registry for multi-tenant deploys.

The single-tenant project assumes one of everything: one sqlite file, one
status snapshot, one kill switch, one bot process. Multi-tenant needs all
of these scoped by Supabase `user_id` (a UUID).

This module is the source of truth for that scoping. Callers ask it:

    registry.db_path(user_id, mode='live')      -> Path
    registry.snapshot_path(user_id)             -> Path
    registry.kill_switch_path(user_id)          -> Path
    registry.pid_path(user_id)                  -> Path
    registry.config_path(user_id)               -> Path
    registry.ensure_tenant_dir(user_id)         -> Path

…and the registry returns paths under `<artifact_dir>/tenants/<user_id>/…`.

It also tracks running bot processes per user, so the sidecar can answer
"is User A's bot running?" without poll-scanning `/proc`.

This is intentionally a thin module — no FastAPI imports, no I/O at import
time. The sidecar instantiates one `TenantRegistry` at startup and passes
it through to handlers via the dependency-injection layer.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, Optional

log = logging.getLogger("aribot.tenants")


# Supabase user IDs are UUID v4 with hyphens — strict regex prevents any
# attempt to abuse path traversal via the user_id segment.
_USER_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

_VALID_MODES = frozenset({"paper", "shadow", "live"})


class InvalidTenantId(ValueError):
    """Raised when a caller passes a string that doesn't look like a Supabase UUID."""


def _validate_user_id(user_id: str) -> str:
    """Defensive check — never trust `user_id` until it matches the UUID shape.
    Callers should ideally get this from a verified JWT `sub`, but a typo or
    a bad client could still send something weird here."""
    if not isinstance(user_id, str) or not _USER_ID_RE.match(user_id.lower()):
        raise InvalidTenantId(f"not a Supabase UUID: {user_id!r}")
    return user_id.lower()


@dataclass
class BotProcessHandle:
    """Lightweight record of a tenant's currently-running bot process.

    We deliberately don't store the Popen object here — the sidecar's
    start/stop helpers already handle that via `.pid_path()` + psutil.
    This dataclass is just for in-memory bookkeeping so a `/status` for
    User B can return immediately without re-reading their pid file.
    """

    user_id: str
    pid: int
    started_at_ts: float = field(default_factory=time.time)
    mode_at_start: str = "paper"


@dataclass(frozen=True)
class TenantPaths:
    """All paths that belong to one tenant. Returned by `paths_for()` so
    callers can pass one bundle instead of five separate strings."""

    root: Path
    pid: Path
    status: Path
    kill_switch: Path
    config: Path
    log: Path

    def db(self, mode: str) -> Path:
        if mode not in _VALID_MODES:
            raise ValueError(f"unknown mode {mode!r}; expected one of {sorted(_VALID_MODES)}")
        return self.root / f"usdt_bot_v2.{mode}.db"


class TenantRegistry:
    """Single source of truth for per-tenant paths + running-bot bookkeeping."""

    def __init__(self, artifact_dir: Path):
        self.artifact_dir = artifact_dir.resolve()
        self.tenants_root = self.artifact_dir / "tenants"
        self.tenants_root.mkdir(parents=True, exist_ok=True)
        self._handles: Dict[str, BotProcessHandle] = {}
        self._lock = threading.RLock()

    # ───── path resolution ────────────────────────────────────────────

    def ensure_tenant_dir(self, user_id: str) -> Path:
        uid = _validate_user_id(user_id)
        target = self.tenants_root / uid
        target.mkdir(parents=True, exist_ok=True)
        return target

    def paths_for(self, user_id: str) -> TenantPaths:
        root = self.ensure_tenant_dir(user_id)
        return TenantPaths(
            root=root,
            pid=root / "bot.pid",
            status=root / "status.json",
            kill_switch=root / "kill_switch.flag",
            config=root / "config.json",
            log=root / "bot.log",
        )

    def db_path(self, user_id: str, mode: str) -> Path:
        return self.paths_for(user_id).db(mode)

    def snapshot_path(self, user_id: str) -> Path:
        return self.paths_for(user_id).status

    def kill_switch_path(self, user_id: str) -> Path:
        return self.paths_for(user_id).kill_switch

    def pid_path(self, user_id: str) -> Path:
        return self.paths_for(user_id).pid

    def config_path(self, user_id: str) -> Path:
        return self.paths_for(user_id).config

    def log_path(self, user_id: str) -> Path:
        return self.paths_for(user_id).log

    # ───── per-tenant config (replaces .env BOT_MODE for multi-tenant) ─

    def read_config(self, user_id: str) -> dict:
        """Tenant-scoped config (BOT_MODE, BYBIT_TESTNET, leverage overrides).

        Returns an empty dict if the file is absent — the sidecar treats
        that as "PAPER + testnet defaults", which is the safe initial
        state for a freshly-signed-up user.
        """
        path = self.config_path(user_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}

    def write_config(self, user_id: str, cfg: dict) -> None:
        """Atomic write of tenant config. Caller is responsible for any
        running-bot check before mutating (mode changes while running
        produce confusing behavior — the bot reads config once at boot)."""
        path = self.config_path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(cfg, sort_keys=True, indent=2), encoding="utf-8")
        tmp.replace(path)

    def get_mode(self, user_id: str) -> str:
        return str(self.read_config(user_id).get("BOT_MODE", "paper")).lower()

    def set_mode(self, user_id: str, mode: str) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(f"invalid mode {mode!r}")
        cfg = self.read_config(user_id)
        cfg["BOT_MODE"] = mode
        self.write_config(user_id, cfg)

    def get_testnet(self, user_id: str) -> bool:
        return bool(self.read_config(user_id).get("BYBIT_TESTNET", True))

    def set_testnet(self, user_id: str, testnet: bool) -> None:
        cfg = self.read_config(user_id)
        cfg["BYBIT_TESTNET"] = bool(testnet)
        self.write_config(user_id, cfg)

    # ───── running-bot registry ───────────────────────────────────────

    def remember_running(self, handle: BotProcessHandle) -> None:
        with self._lock:
            self._handles[handle.user_id] = handle

    def forget_running(self, user_id: str) -> None:
        uid = _validate_user_id(user_id)
        with self._lock:
            self._handles.pop(uid, None)

    def get_running(self, user_id: str) -> Optional[BotProcessHandle]:
        uid = _validate_user_id(user_id)
        with self._lock:
            return self._handles.get(uid)

    def iter_running(self) -> Iterator[BotProcessHandle]:
        with self._lock:
            yield from list(self._handles.values())

    def count_running(self) -> int:
        with self._lock:
            return len(self._handles)

    # ───── discovery for resync at sidecar startup ────────────────────

    def all_known_tenants(self) -> list[str]:
        """Lists every tenant directory currently on disk. Used by the
        sidecar at startup to rebuild the in-memory running-bot dict by
        scanning each tenant's pid file."""
        if not self.tenants_root.exists():
            return []
        out: list[str] = []
        for child in self.tenants_root.iterdir():
            if child.is_dir() and _USER_ID_RE.match(child.name):
                out.append(child.name)
        return sorted(out)


if __name__ == "__main__":
    # Smoke test the path layout. Doesn't touch real tenants.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        registry = TenantRegistry(Path(td))
        sample = "11111111-2222-3333-4444-555555555555"
        registry.set_mode(sample, "shadow")
        registry.set_testnet(sample, False)
        paths = registry.paths_for(sample)
        print(f"root:        {paths.root}")
        print(f"db(live):    {paths.db('live')}")
        print(f"snapshot:    {paths.status}")
        print(f"kill switch: {paths.kill_switch}")
        print(f"mode:        {registry.get_mode(sample)}")
        print(f"testnet:     {registry.get_testnet(sample)}")
        print(f"tenants:     {registry.all_known_tenants()}")
        try:
            registry.paths_for("../etc/passwd")
        except InvalidTenantId as exc:
            print(f"rejected bad id: {exc}")
