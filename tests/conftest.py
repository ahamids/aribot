import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import aiosqlite
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# Ensure import-time env checks pass during test collection.
os.environ.setdefault("ARIBOT_MEK", secrets.token_hex(32))
os.environ.setdefault("ARIBOT_JWT_SECRET", secrets.token_hex(64))
os.environ.setdefault("ARIBOT_DB", str(Path.cwd() / "_bootstrap_test.db"))
os.environ.setdefault("ARIBOT_APP_NAME", "test")

from aribot_auth import create_auth_app
from aribot_auth.db import run_migrations
from aribot_auth.password import hash_password


@pytest_asyncio.fixture(scope="function")
async def tmp_db(tmp_path: Path) -> str:
    """Create a fresh SQLite database and run schema migrations."""
    db_path = tmp_path / "shared.db"
    os.environ["ARIBOT_DB"] = str(db_path)
    await run_migrations(str(db_path))
    return str(db_path)


@pytest.fixture(scope="function")
def test_env(monkeypatch: pytest.MonkeyPatch, tmp_db: str) -> dict:
    """Set required aribot_auth environment variables for each test."""
    env = {
        "ARIBOT_MEK": secrets.token_hex(32),
        "ARIBOT_JWT_SECRET": secrets.token_hex(64),
        "ARIBOT_DB": tmp_db,
        "ARIBOT_APP_NAME": "test",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return env


@pytest_asyncio.fixture(scope="function")
async def test_app(test_env: dict) -> AsyncClient:
    """Create a FastAPI app with mounted auth routers and an async HTTP client."""
    app = FastAPI()
    create_auth_app(app)

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def _insert_user(db_path: str, email: str, password: str, role: str, mfa_enabled: int = 0, mfa_secret: str | None = None) -> dict:
    user_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO users (
                id, email, password_hash, role, mfa_secret, mfa_enabled, active,
                invited_by, created_at, last_login, failed_login_count, locked_until
            ) VALUES (?, ?, ?, ?, ?, ?, 1, NULL, ?, NULL, 0, NULL)
            """,
            (user_id, email, hash_password(password), role, mfa_secret, mfa_enabled, created_at),
        )
        await db.commit()
    return {"id": user_id, "email": email, "password": password, "role": role}


@pytest_asyncio.fixture(scope="function")
async def admin_user(test_env: dict) -> dict:
    """Create an admin user in the test database."""
    return await _insert_user(test_env["ARIBOT_DB"], "admin@x.com", "AdminPassword123!", "admin")


@pytest_asyncio.fixture(scope="function")
async def observer_user(test_env: dict) -> dict:
    """Create an observer user in the test database."""
    return await _insert_user(test_env["ARIBOT_DB"], "observer@x.com", "ObserverPassword123!", "observer")


@pytest_asyncio.fixture(scope="function")
async def operator_user(test_env: dict) -> dict:
    """Create an operator user in the test database."""
    return await _insert_user(test_env["ARIBOT_DB"], "operator@x.com", "OperatorPassword123!", "operator")


@pytest_asyncio.fixture(scope="function")
async def admin_token(test_app: AsyncClient, admin_user: dict) -> str:
    """Issue an admin bearer token via /auth/login."""
    resp = await test_app.post("/auth/login", json={"email": admin_user["email"], "password": admin_user["password"]})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest_asyncio.fixture(scope="function")
async def observer_token(test_app: AsyncClient, observer_user: dict) -> str:
    """Issue an observer bearer token via /auth/login."""
    resp = await test_app.post("/auth/login", json={"email": observer_user["email"], "password": observer_user["password"]})
    assert resp.status_code == 200
    return resp.json()["access_token"]
