"""End-to-end isolation tests for the multi-tenant sidecar.

This is the acceptance test for the entire migration. If these pass, the
silo is real: User A's data, credentials, locks, and bot launches do not
commingle with User B's.

Tests are pytest-style but also runnable as `python tests/test_multitenant_isolation.py`
for ad-hoc smoke runs without installing pytest.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Optional
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import jwt as pyjwt  # PyJWT
from fastapi.testclient import TestClient

import status_server as ss
from auth_supabase import LEGACY_OPS_ID, SupabaseJwtVerifier
from credential_store import CredentialStore, LoadedCredentials
from meta_db import MetaDb
from tenant_registry import TenantRegistry


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

JWT_SECRET = "isolation-test-secret-padding-padding-padding-padding"  # ≥32 bytes
SUPABASE_URL = "https://isolation-test.supabase.co"
USER_A = "11111111-2222-3333-4444-555555555555"
USER_B = "99999999-8888-7777-6666-555555555555"


def _mint_jwt(user_id: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {
            "sub": user_id,
            "email": f"{user_id}@example.test",
            "role": "authenticated",
            "aud": "authenticated",
            "iss": f"{SUPABASE_URL}/auth/v1",
            "iat": now,
            "exp": now + 3600,
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def _seed_tenant_db(db_path: Path, fixtures: list[dict]) -> None:
    """Create a per-tenant sqlite with the bot's `positions` schema and
    insert a few rows. Mirrors what `Aribot.setup_database` would create."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                side TEXT,
                entry_price REAL,
                quantity REAL,
                timestamp TEXT,
                current_price REAL,
                pnl REAL,
                pnl_percentage REAL
            )
        """)
        for row in fixtures:
            conn.execute(
                "INSERT INTO positions(symbol, side, entry_price, quantity, "
                "timestamp, current_price, pnl, pnl_percentage) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["symbol"], row["side"], row["entry_price"], row["quantity"],
                    row.get("timestamp", "2026-01-01T00:00:00+00:00"),
                    row.get("current_price", 0), row.get("pnl", 0),
                    row.get("pnl_percentage", 0),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _fake_loaded_credentials(fingerprint: str) -> LoadedCredentials:
    return LoadedCredentials(
        read_api_key=f"{fingerprint}_read",
        read_api_secret=f"{fingerprint}_read_s",
        trade_api_key=f"{fingerprint}_trade",
        trade_api_secret=f"{fingerprint}_trade_s",
        fingerprint=fingerprint,
        validated_at_iso="2026-01-01T00:00:00+00:00",
    )


def _make_app(tmpdir: Path):
    """Spin up a fully wired multi-tenant build_app against tmpdir.
    Returns (app, registry, meta_db, credential_store, host_identity)."""
    from bot_keypair import get_or_create_identity

    artifact_dir = tmpdir / ".aribot"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    cfg = ss.Config(
        snapshot_path=tmpdir / "aribot_status.json",
        kill_switch_path=tmpdir / "kill_switch.flag",
        db_path=tmpdir / "usdt_bot_v2.db",
        bot_pid_path=tmpdir / ".aribot.pid",
        bot_log_path=tmpdir / ".aribot.launched.log",
        bot_command=("python", "-c", "import time; time.sleep(0.1)"),
        bot_cwd=tmpdir,
        env_file_path=tmpdir / ".env",
        expected_token="legacy-token-not-used-in-this-test",
        expected_vault_token="legacy-vault-token",
        stale_multiplier=5.0,
        cors_origins=(),
        artifact_dir=artifact_dir,
    )

    host_identity = get_or_create_identity(artifact_dir)
    credential_store = CredentialStore(host=host_identity, state_dir=artifact_dir)
    registry = TenantRegistry(artifact_dir)
    meta_db = MetaDb(registry.meta_db_path)
    verifier = SupabaseJwtVerifier(jwt_secret=JWT_SECRET, supabase_url=SUPABASE_URL)

    app = ss.build_app(
        cfg,
        host_identity=host_identity,
        credential_store=credential_store,
        registry=registry,
        meta_db=meta_db,
        jwt_verifier=verifier,
    )
    return app, registry, meta_db, credential_store, host_identity, cfg


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_credential_isolation():
    """User A pushing credentials must not affect User B's stored credentials."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        app, registry, meta_db, credential_store, _, _ = _make_app(Path(td))

        # Direct dict population (white-box) — sealed-box decrypt is not the
        # subject of this test; per-user keying is.
        credential_store._by_user[USER_A] = _fake_loaded_credentials("FP_A")
        credential_store._by_user[USER_B] = _fake_loaded_credentials("FP_B")

        client = TestClient(app)

        # User A sees A's fingerprint.
        r_a = client.get(
            "/credentials/status",
            headers={"Authorization": f"Bearer {_mint_jwt(USER_A)}"},
        )
        assert r_a.status_code == 200, r_a.text
        body_a = r_a.json()
        assert body_a["loaded"] is True
        assert body_a["fingerprint"] == "FP_A"

        # User B sees B's fingerprint.
        r_b = client.get(
            "/credentials/status",
            headers={"Authorization": f"Bearer {_mint_jwt(USER_B)}"},
        )
        assert r_b.json()["fingerprint"] == "FP_B"

        # User A wipes; User B's keys are unaffected.
        r_del = client.delete(
            "/credentials",
            headers={"Authorization": f"Bearer {_mint_jwt(USER_A)}"},
        )
        assert r_del.status_code == 200, r_del.text
        assert credential_store.is_loaded(USER_A) is False
        assert credential_store.is_loaded(USER_B) is True
        assert credential_store.snapshot(USER_B).fingerprint == "FP_B"

        meta_db.close()


def test_data_isolation_positions():
    """User A's GET /positions must NEVER return rows from User B's DB."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        app, registry, meta_db, _, _, _ = _make_app(Path(td))

        # Pre-seed two distinct per-tenant DBs.
        paths_a = registry.paths_for(USER_A)
        paths_b = registry.paths_for(USER_B)
        registry.set_mode(USER_A, "paper")
        registry.set_mode(USER_B, "paper")
        _seed_tenant_db(
            paths_a.db("paper"),
            [{"symbol": "BTC/USDT:USDT", "side": "long", "entry_price": 100.0, "quantity": 1.0}],
        )
        _seed_tenant_db(
            paths_b.db("paper"),
            [
                {"symbol": "ETH/USDT:USDT", "side": "long", "entry_price": 200.0, "quantity": 2.0},
                {"symbol": "SOL/USDT:USDT", "side": "short", "entry_price": 50.0, "quantity": 5.0},
            ],
        )

        client = TestClient(app)

        r_a = client.get("/positions", headers={"Authorization": f"Bearer {_mint_jwt(USER_A)}"})
        assert r_a.status_code == 200, r_a.text
        symbols_a = {p["symbol"] for p in r_a.json()["positions"]}
        assert symbols_a == {"BTC/USDT:USDT"}, symbols_a

        r_b = client.get("/positions", headers={"Authorization": f"Bearer {_mint_jwt(USER_B)}"})
        symbols_b = {p["symbol"] for p in r_b.json()["positions"]}
        assert symbols_b == {"ETH/USDT:USDT", "SOL/USDT:USDT"}, symbols_b

        # Critical: A and B saw disjoint sets.
        assert symbols_a.isdisjoint(symbols_b)

        meta_db.close()


def test_start_bot_routes_per_user_env():
    """POST /start for User A must spawn with ARIBOT_USER_ID=A in spawn env
    and use User A's credential snapshot — not User B's."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        app, registry, meta_db, credential_store, _, cfg = _make_app(Path(td))

        credential_store._by_user[USER_A] = _fake_loaded_credentials("FP_A")
        credential_store._by_user[USER_B] = _fake_loaded_credentials("FP_B")

        captured_calls = []

        class _FakeProc:
            pid = 12345

        def _fake_popen(cmd, **kwargs):
            captured_calls.append({"cmd": cmd, "env": kwargs.get("env", {}).copy()})
            # Real Popen takes ownership of stdout/stderr file handles; our
            # fake doesn't fork a subprocess, so close them here so the temp
            # dir cleanup isn't blocked by an open log file on Windows.
            for key in ("stdout", "stderr"):
                fh = kwargs.get(key)
                if fh is not None and hasattr(fh, "close"):
                    try:
                        fh.close()
                    except OSError:
                        pass
            return _FakeProc()

        client = TestClient(app)
        with patch.object(ss.subprocess, "Popen", side_effect=_fake_popen):
            r_a = client.post("/start", headers={"Authorization": f"Bearer {_mint_jwt(USER_A)}"})
            assert r_a.status_code == 202, r_a.text

        assert len(captured_calls) == 1
        env_a = captured_calls[0]["env"]
        assert env_a.get("ARIBOT_USER_ID") == USER_A
        assert env_a.get("ARIBOT_ARTIFACT_DIR") == str(cfg.artifact_dir)
        # The credential pipe handle must be present (we have creds for A).
        assert "ARIBOT_CRED_PIPE" in env_a
        assert "ARIBOT_CRED_TOKEN" in env_a

        # Audit row landed in meta.db for A specifically.
        audit_a = meta_db.recent_audit(USER_A)
        assert any(row["action"] == "start" for row in audit_a), audit_a
        # B has no start row.
        assert meta_db.recent_audit(USER_B) == []

        meta_db.close()


def test_concurrent_start_two_users_no_shared_lock():
    """User A and User B starting bots concurrently must both succeed
    (no shared _BotLock blocking)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        app, registry, meta_db, credential_store, _, _ = _make_app(Path(td))
        credential_store._by_user[USER_A] = _fake_loaded_credentials("FP_A")
        credential_store._by_user[USER_B] = _fake_loaded_credentials("FP_B")

        # Make Popen "slow" so the two requests overlap. If a shared lock
        # were holding, the second start would either time out (1s lock
        # timeout) or be sequenced.
        barrier = threading.Barrier(2)

        class _FakeProc:
            def __init__(self, pid):
                self.pid = pid

        proc_counter = [10000]

        def _slow_popen(cmd, **kwargs):
            barrier.wait(timeout=2.0)  # both threads must arrive
            for key in ("stdout", "stderr"):
                fh = kwargs.get(key)
                if fh is not None and hasattr(fh, "close"):
                    try:
                        fh.close()
                    except OSError:
                        pass
            proc_counter[0] += 1
            return _FakeProc(proc_counter[0])

        client = TestClient(app)
        results: dict[str, int] = {}

        def _kick(user_id: str) -> None:
            with patch.object(ss.subprocess, "Popen", side_effect=_slow_popen):
                r = client.post(
                    "/start",
                    headers={"Authorization": f"Bearer {_mint_jwt(user_id)}"},
                )
                results[user_id] = r.status_code

        t_a = threading.Thread(target=_kick, args=(USER_A,))
        t_b = threading.Thread(target=_kick, args=(USER_B,))
        t_a.start(); t_b.start()
        t_a.join(timeout=5.0); t_b.join(timeout=5.0)

        assert results[USER_A] == 202, results
        assert results[USER_B] == 202, results

        meta_db.close()


def test_repeated_start_same_user_returns_409():
    """Two /start for User A back-to-back: second returns 409 (still
    enforces one bot per user)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        app, registry, meta_db, credential_store, _, _ = _make_app(Path(td))
        credential_store._by_user[USER_A] = _fake_loaded_credentials("FP_A")

        # Patch _running_bot_pid_tenant so the SECOND call sees a "live" PID.
        # We use a sentinel: first call returns None (no bot), second returns
        # a PID we mark as alive via _pid_alive patch.
        pid_call_count = [0]

        def _patched_running_pid(ctx):
            pid_call_count[0] += 1
            if pid_call_count[0] == 1:
                return None
            return 99999

        class _FakeProc:
            pid = 99999

        client = TestClient(app)
        with patch.object(ss, "_running_bot_pid_tenant", side_effect=_patched_running_pid), \
             patch.object(ss.subprocess, "Popen", return_value=_FakeProc()), \
             patch.object(ss, "_pid_alive", return_value=True):
            r1 = client.post("/start", headers={"Authorization": f"Bearer {_mint_jwt(USER_A)}"})
            assert r1.status_code == 202, r1.text
            r2 = client.post("/start", headers={"Authorization": f"Bearer {_mint_jwt(USER_A)}"})
            assert r2.status_code == 409, r2.text

        meta_db.close()


def test_jwt_required_for_credentials_endpoint():
    """POST /credentials must reject the legacy bearer token (uses
    require_user_jwt_only). Only a real JWT works."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        app, registry, meta_db, credential_store, _, cfg = _make_app(Path(td))
        client = TestClient(app)

        # Legacy bearer rejected on /credentials/status (jwt-only endpoint).
        r_legacy = client.get(
            "/credentials/status",
            headers={"Authorization": f"Bearer {cfg.expected_token}"},
        )
        assert r_legacy.status_code == 401, r_legacy.text

        # Real JWT works.
        r_jwt = client.get(
            "/credentials/status",
            headers={"Authorization": f"Bearer {_mint_jwt(USER_A)}"},
        )
        assert r_jwt.status_code == 200

        meta_db.close()


def test_invalid_user_id_returns_400():
    """A JWT with a sub that's not a Supabase UUID must be rejected by
    the verifier (401), not 500."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        app, registry, meta_db, _, _, _ = _make_app(Path(td))
        client = TestClient(app)

        bad_token = pyjwt.encode(
            {
                "sub": "not-a-uuid",
                "aud": "authenticated",
                "iss": f"{SUPABASE_URL}/auth/v1",
                "iat": int(time.time()),
                "exp": int(time.time()) + 60,
            },
            JWT_SECRET,
            algorithm="HS256",
        )
        r = client.get("/positions", headers={"Authorization": f"Bearer {bad_token}"})
        assert r.status_code == 401, r.text

        meta_db.close()


def test_legacy_bearer_routes_to_legacy_paths():
    """The legacy bearer token path uses cfg paths (not tenant paths) and
    returns AuthUser(id=LEGACY_OPS_ID). Verifies the dual-mode coexistence."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        app, registry, meta_db, credential_store, _, cfg = _make_app(Path(td))

        # Seed the LEGACY DB at cfg.db_path with a unique row.
        _seed_tenant_db(
            cfg.db_path,
            [{"symbol": "LEGACY/USDT:USDT", "side": "long", "entry_price": 1.0, "quantity": 1.0}],
        )

        client = TestClient(app)
        r = client.get(
            "/positions",
            headers={"Authorization": f"Bearer {cfg.expected_token}"},
        )
        assert r.status_code == 200, r.text
        symbols = {p["symbol"] for p in r.json()["positions"]}
        assert symbols == {"LEGACY/USDT:USDT"}, symbols

        meta_db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Ad-hoc runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_credential_isolation,
        test_data_isolation_positions,
        test_start_bot_routes_per_user_env,
        test_concurrent_start_two_users_no_shared_lock,
        test_repeated_start_same_user_returns_409,
        test_jwt_required_for_credentials_endpoint,
        test_invalid_user_id_returns_400,
        test_legacy_bearer_routes_to_legacy_paths,
    ]
    failed = []
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as exc:
            failed.append((t.__name__, exc))
            print(f"FAIL  {t.__name__}: {type(exc).__name__}: {exc}")
    if failed:
        print(f"\n{len(failed)}/{len(tests)} tests failed")
        sys.exit(1)
    print(f"\n{len(tests)} tests passed")
