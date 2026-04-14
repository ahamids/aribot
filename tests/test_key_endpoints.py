import aiosqlite
import pyotp
import pytest


@pytest.mark.asyncio
async def test_create_and_list_keys(test_app, admin_user):
    """Creating a key returns metadata and listing includes it."""
    login = await test_app.post("/auth/login", json={"email": admin_user["email"], "password": admin_user["password"]})
    access = login.json()["access_token"]

    enable = await test_app.post("/auth/mfa/enable", headers={"Authorization": f"Bearer {access}"})
    code = pyotp.TOTP(enable.json()["secret"]).now()
    await test_app.post("/auth/mfa/confirm", headers={"Authorization": f"Bearer {access}"}, json={"totp_code": code})

    code = pyotp.TOTP(enable.json()["secret"]).now()
    body = {
        "exchange": "bybit",
        "label": "Main account",
        "environment": "testnet",
        "api_key": "KEY123",
        "api_secret": "SECRET123",
        "permissions": ["read", "trade"],
    }
    created = await test_app.post(
        "/api/keys",
        headers={"Authorization": f"Bearer {access}", "X-MFA-Token": code},
        json=body,
    )
    assert created.status_code == 200
    key_id = created.json()["id"]

    listed = await test_app.get("/api/keys", headers={"Authorization": f"Bearer {access}"})
    assert listed.status_code == 200
    assert any(k["id"] == key_id for k in listed.json())


@pytest.mark.asyncio
async def test_retrieve_key_returns_plaintext_and_logs_audit(test_app, test_env, admin_user):
    """Retrieving a key returns plaintext material and writes audit entry."""
    login = await test_app.post("/auth/login", json={"email": admin_user["email"], "password": admin_user["password"]})
    access = login.json()["access_token"]

    enable = await test_app.post("/auth/mfa/enable", headers={"Authorization": f"Bearer {access}"})
    secret = enable.json()["secret"]
    await test_app.post(
        "/auth/mfa/confirm",
        headers={"Authorization": f"Bearer {access}"},
        json={"totp_code": pyotp.TOTP(secret).now()},
    )

    created = await test_app.post(
        "/api/keys",
        headers={"Authorization": f"Bearer {access}", "X-MFA-Token": pyotp.TOTP(secret).now()},
        json={
            "exchange": "bybit",
            "label": "Main account",
            "environment": "testnet",
            "api_key": "KEY123",
            "api_secret": "SECRET123",
        },
    )
    key_id = created.json()["id"]

    retrieved = await test_app.get(
        f"/api/keys/{key_id}/retrieve",
        headers={"Authorization": f"Bearer {access}", "X-MFA-Token": pyotp.TOTP(secret).now()},
    )
    assert retrieved.status_code == 200
    assert retrieved.json()["api_key"] == "KEY123"

    async with aiosqlite.connect(test_env["ARIBOT_DB"]) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute("SELECT action FROM audit_log WHERE action = 'api_key.retrieved' ORDER BY timestamp DESC LIMIT 1")).fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_delete_key_soft_delete(test_app, admin_user):
    """Deleting a key removes it from active key listing."""
    login = await test_app.post("/auth/login", json={"email": admin_user["email"], "password": admin_user["password"]})
    access = login.json()["access_token"]

    enable = await test_app.post("/auth/mfa/enable", headers={"Authorization": f"Bearer {access}"})
    secret = enable.json()["secret"]
    await test_app.post(
        "/auth/mfa/confirm",
        headers={"Authorization": f"Bearer {access}"},
        json={"totp_code": pyotp.TOTP(secret).now()},
    )

    created = await test_app.post(
        "/api/keys",
        headers={"Authorization": f"Bearer {access}", "X-MFA-Token": pyotp.TOTP(secret).now()},
        json={
            "exchange": "bybit",
            "label": "Main account",
            "environment": "testnet",
            "api_key": "KEY123",
            "api_secret": "SECRET123",
        },
    )
    key_id = created.json()["id"]

    deleted = await test_app.delete(f"/api/keys/{key_id}", headers={"Authorization": f"Bearer {access}"})
    assert deleted.status_code == 200

    listed = await test_app.get("/api/keys", headers={"Authorization": f"Bearer {access}"})
    assert all(k["id"] != key_id for k in listed.json())
