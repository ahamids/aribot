import pyotp
import pytest


@pytest.mark.asyncio
async def test_require_role_admin_passes(test_app, admin_token):
    """Admin bearer token can access admin-only endpoint."""
    resp = await test_app.get("/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_require_role_admin_denies_observer(test_app, observer_token):
    """Observer bearer token cannot access admin-only endpoint."""
    resp = await test_app.get("/admin/users", headers={"Authorization": f"Bearer {observer_token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_require_mfa_verified_missing_header_blocks_create_key(test_app, admin_token):
    """MFA-enabled key creation rejects missing X-MFA-Token header."""
    await test_app.post("/auth/mfa/enable", headers={"Authorization": f"Bearer {admin_token}"})
    body = {
        "exchange": "bybit",
        "label": "main",
        "environment": "testnet",
        "api_key": "abc",
        "api_secret": "xyz",
    }
    resp = await test_app.post("/api/keys", headers={"Authorization": f"Bearer {admin_token}"}, json=body)
    assert resp.status_code == 403
