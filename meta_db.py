"""Operator-side metadata DB for the multi-tenant sidecar.

The per-tenant SQLite files (`<artifact_dir>/tenants/<uuid>/usdt_bot_v2.{mode}.db`)
hold the trade data and are owned exclusively by the bot. The sidecar
opens them read-only for the iOS app's status views.

This module owns a separate `<artifact_dir>/meta.db` that the **sidecar**
writes to record cross-tenant lifecycle events:

* `tenants` — one row per Supabase user we have ever seen
* `audit_log` — append-only record of consequential actions per tenant
  (`creds_pushed`, `start`, `stop`, `kill`, `mode_change`, …)
* `bot_runs` — one row per bot launch with start/stop timestamps and
  exit reason, useful for "why did User A's bot stop at 14:32?"

Bots never read or write meta.db. That separation eliminates the
cross-tenant write contention that would otherwise force a move to
Postgres at small scale, and gives operator queries one stable file to
back up regardless of how many tenants exist.

`MetaDb` is a thin wrapper around a single shared `sqlite3.Connection`
guarded by an `RLock`. WAL mode is enabled so the `/admin/*` endpoints
(future) can read while the sidecar writes. Every `record_*` call is one
short transaction; lock contention should be negligible at the ≤100-user
scale this design targets.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

log = logging.getLogger("aribot.meta_db")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    user_id    TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    plan       TEXT NOT NULL DEFAULT 'free',
    status     TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    action      TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_user_ts ON audit_log(user_id, ts DESC);

CREATE TABLE IF NOT EXISTS bot_runs (
    user_id     TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    stopped_at  TEXT,
    exit_reason TEXT,
    PRIMARY KEY (user_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_runs_user_started ON bot_runs(user_id, started_at DESC);
"""


def _now_iso() -> str:
    """ISO 8601 UTC timestamp with millisecond precision.

    Millisecond precision is enough for human-readable audit logs and
    avoids the same-second-tie problem when two events fire in rapid
    succession (e.g. `creds_pushed` immediately followed by `start`).
    For absolute insertion order, prefer the AUTOINCREMENT `id` column
    on `audit_log` — it is monotonic within the single-writer sidecar.
    """
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class MetaDb:
    """Thread-safe SQLite wrapper for the operator-side metadata store."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # `check_same_thread=False` is safe because every method holds
        # `self._lock` while touching the connection.
        self._conn = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; transactions are explicit
        )
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)

    # ───── tenant lifecycle ───────────────────────────────────────────

    def ensure_tenant(self, user_id: str, *, plan: str = "free") -> None:
        """Insert a tenant row if it doesn't exist. Idempotent."""
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO tenants(user_id, created_at, plan, status) "
                "VALUES (?, ?, ?, 'active')",
                (user_id, _now_iso(), plan),
            )

    def list_tenants(self) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT user_id, created_at, plan, status FROM tenants ORDER BY created_at"
            )
            return [dict(row) for row in cur.fetchall()]

    def set_status(self, user_id: str, status: str) -> None:
        if status not in {"active", "suspended"}:
            raise ValueError(f"invalid status {status!r}")
        with self._lock:
            self._conn.execute(
                "UPDATE tenants SET status=? WHERE user_id=?",
                (status, user_id),
            )

    # ───── audit log ──────────────────────────────────────────────────

    def record_audit(
        self,
        user_id: str,
        action: str,
        detail: Optional[dict[str, Any]] = None,
    ) -> None:
        """Append-only log of consequential actions. Never updated, never deleted."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_log(ts, user_id, action, detail_json) VALUES (?, ?, ?, ?)",
                (_now_iso(), user_id, action, json.dumps(detail or {}, sort_keys=True)),
            )

    def recent_audit(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            # Order by id DESC (not ts) so events written within the same
            # millisecond still come back in deterministic insertion order.
            cur = self._conn.execute(
                "SELECT ts, action, detail_json FROM audit_log "
                "WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, max(1, min(limit, 500))),
            )
            out = []
            for row in cur.fetchall():
                row_dict = dict(row)
                try:
                    row_dict["detail"] = json.loads(row_dict.pop("detail_json"))
                except (ValueError, TypeError):
                    row_dict["detail"] = {}
                out.append(row_dict)
            return out

    # ───── bot run history ────────────────────────────────────────────

    def record_run_start(self, user_id: str, run_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO bot_runs(user_id, run_id, started_at) "
                "VALUES (?, ?, ?)",
                (user_id, run_id, _now_iso()),
            )

    def record_run_stop(
        self,
        user_id: str,
        run_id: str,
        exit_reason: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE bot_runs SET stopped_at=?, exit_reason=? "
                "WHERE user_id=? AND run_id=?",
                (_now_iso(), exit_reason, user_id, run_id),
            )

    def recent_runs(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT run_id, started_at, stopped_at, exit_reason FROM bot_runs "
                "WHERE user_id=? ORDER BY started_at DESC LIMIT ?",
                (user_id, max(1, min(limit, 200))),
            )
            return [dict(row) for row in cur.fetchall()]

    # ───── housekeeping ───────────────────────────────────────────────

    def iter_tenants(self) -> Iterator[str]:
        with self._lock:
            for row in self._conn.execute("SELECT user_id FROM tenants"):
                yield row["user_id"]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


if __name__ == "__main__":
    # Smoke test the schema and basic CRUD.
    import tempfile
    import uuid

    with tempfile.TemporaryDirectory() as td:
        db = MetaDb(Path(td) / "meta.db")
        try:
            u1 = str(uuid.uuid4())
            u2 = str(uuid.uuid4())

            db.ensure_tenant(u1)
            db.ensure_tenant(u1)  # idempotent
            db.ensure_tenant(u2, plan="pro")
            tenants = db.list_tenants()
            assert {t["user_id"] for t in tenants} == {u1, u2}
            assert next(t for t in tenants if t["user_id"] == u2)["plan"] == "pro"

            db.record_audit(u1, "creds_pushed", {"fingerprint": "abc123"})
            db.record_audit(u1, "start", {"mode": "paper"})
            db.record_audit(u2, "start", {"mode": "live"})

            # u1 sees only u1 events. Insertion order via id DESC: most recent first.
            u1_audit = db.recent_audit(u1)
            assert len(u1_audit) == 2, u1_audit
            assert u1_audit[0]["action"] == "start", u1_audit
            assert u1_audit[1]["action"] == "creds_pushed", u1_audit
            assert u1_audit[1]["detail"]["fingerprint"] == "abc123"

            # Cross-tenant isolation: u2's audit must not include u1's rows.
            u2_audit = db.recent_audit(u2)
            assert len(u2_audit) == 1
            assert u2_audit[0]["action"] == "start"
            assert u2_audit[0]["detail"]["mode"] == "live"

            run_id = "run-" + uuid.uuid4().hex[:8]
            db.record_run_start(u1, run_id)
            time.sleep(0.01)
            db.record_run_stop(u1, run_id, exit_reason="kill_switch")
            runs = db.recent_runs(u1)
            assert runs[0]["run_id"] == run_id
            assert runs[0]["exit_reason"] == "kill_switch"
            assert runs[0]["stopped_at"] is not None

            db.set_status(u1, "suspended")
            assert next(t for t in db.list_tenants() if t["user_id"] == u1)["status"] == "suspended"

            print("meta_db smoke test passed.")
        finally:
            # Always release the SQLite handle so TemporaryDirectory cleanup
            # works on Windows (where -wal/-shm files keep the dir locked).
            db.close()
