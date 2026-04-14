import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import aiosqlite
import pyotp
import pytest


@pytest.mark.asyncio
async def test_login_success_returns_access_and_cookie(test_app, admin_user):
    """Successful login returns bearer token and sets rt cookie."""
    resp = await test_app.post("/auth/login", json={"email": admin_user["email"], "password": admin_user["password"]})
    assert resp.status_code == 200
    assert "access_token" in resp.json()
    assert "rt" in resp.cookies


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(test_app, admin_user):
    """Invalid password login returns 401."""
    resp = await test_app.post("/auth/login", json={"email": admin_user["email"], "password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_lockout_after_five_failures(test_app, test_env, admin_user):
    """Five failed logins trigger account lock behavior."""
    for _ in range(5):
        await test_app.post("/auth/login", json={"email": admin_user["email"], "password": "wrong"})
    async with aiosqlite.connect(test_env["ARIBOT_DB"]) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute("SELECT locked_until FROM users WHERE id = ?", (admin_user["id"],))).fetchone()
    assert row["locked_until"] is not None


@pytest.mark.asyncio
async def test_refresh_success_rotates_token(test_app, admin_user):
    """Refresh endpoint rotates refresh token and returns a new access token."""
    login = await test_app.post("/auth/login", json={"email": admin_user["email"], "password": admin_user["password"]})
    rt = login.cookies.get("rt")
    refresh = await test_app.post("/auth/refresh", cookies={"rt": rt})
    assert refresh.status_code == 200
    assert refresh.cookies.get("rt") != rt


@pytest.mark.asyncio
async def test_refresh_race_only_one_wins(test_app, admin_user):
    """Concurrent refresh requests for same token produce exactly one success."""
    login = await test_app.post("/auth/login", json={"email": admin_user["email"], "password": admin_user["password"]})
    rt = login.cookies.get("rt")

    async def do_refresh():
        return await test_app.post("/auth/refresh", cookies={"rt": rt})

    r1, r2 = await asyncio.gather(do_refresh(), do_refresh())
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [401, 200]


@pytest.mark.asyncio
async def test_logout_revokes_current_refresh(test_app, admin_user):
    """Logout revokes current refresh token and future refresh fails."""
    login = await test_app.post("/auth/login", json={"email": admin_user["email"], "password": admin_user["password"]})
    access = login.json()["access_token"]
    rt = login.cookies.get("rt")
    out = await test_app.post("/auth/logout", headers={"Authorization": f"Bearer {access}"}, cookies={"rt": rt})
    assert out.status_code == 200
    fail = await test_app.post("/auth/refresh", cookies={"rt": rt})
    assert fail.status_code == 401


@pytest.mark.asyncio
async def test_get_me_requires_auth(test_app):
    """GET /auth/me returns 401 for missing bearer token."""
    resp = await test_app.get("/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_change_password_revokes_sessions(test_app, admin_user):
    """Changing password revokes refresh tokens and requires fresh login."""
    login = await test_app.post("/auth/login", json={"email": admin_user["email"], "password": admin_user["password"]})
    access = login.json()["access_token"]
    rt = login.cookies.get("rt")
    resp = await test_app.post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {access}"},
        cookies={"rt": rt},
        json={"current_password": admin_user["password"], "new_password": "BrandNewPassword123!"},
    )
    assert resp.status_code == 200
    assert (await test_app.post("/auth/refresh", cookies={"rt": rt})).status_code == 401


@pytest.mark.asyncio
async def test_accept_invite_success(test_app, test_env, admin_user):
    """Accept invite creates a user account with invite role."""
    token = "a" * 64
    now = datetime.now(timezone.utc)
    async with aiosqlite.connect(test_env["ARIBOT_DB"]) as db:
        await db.execute(
            "INSERT INTO invites (token, email, role, invited_by, created_at, expires_at, used_at) VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (token, "new@x.com", "observer", admin_user["id"], now.isoformat(), (now + timedelta(hours=72)).isoformat()),
        )
        await db.commit()

    resp = await test_app.post("/auth/accept-invite", json={"token": token, "password": "InvitePassword123!"})
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "new@x.com"


@pytest.mark.asyncio
async def test_mfa_enable_confirm_flow(test_app, admin_user):
    """MFA enable and confirm activates mfa_enabled for user."""
    login = await test_app.post("/auth/login", json={"email": admin_user["email"], "password": admin_user["password"]})
    access = login.json()["access_token"]

    enabled = await test_app.post("/auth/mfa/enable", headers={"Authorization": f"Bearer {access}"})
    assert enabled.status_code == 200
    secret = enabled.json()["secret"]
    code = pyotp.TOTP(secret).now()

    confirmed = await test_app.post(
        "/auth/mfa/confirm",
        headers={"Authorization": f"Bearer {access}"},
        json={"totp_code": code},
    )
    assert confirmed.status_code == 200
