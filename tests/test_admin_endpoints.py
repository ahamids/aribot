import pytest


@pytest.mark.asyncio
async def test_admin_can_list_users(test_app, admin_token):
    """Admin user can access /admin/users."""
    resp = await test_app.get("/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_observer_cannot_list_users(test_app, observer_token):
    """Observer user gets 403 from /admin/users."""
    resp = await test_app.get("/admin/users", headers={"Authorization": f"Bearer {observer_token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_create_user(test_app, admin_token):
    """Admin can create users through /admin/users."""
    resp = await test_app.post(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "new-admin@x.com", "password": "SuperStrongPass123!", "role": "observer"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "new-admin@x.com"


@pytest.mark.asyncio
async def test_admin_invite_and_list(test_app, admin_token):
    """Admin invite endpoint returns token and appears in invite list."""
    created = await test_app.post(
        "/admin/invite",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "invitee@x.com", "role": "observer"},
    )
    assert created.status_code == 200
    token = created.json()["token"]

    invites = await test_app.get("/admin/invites", headers={"Authorization": f"Bearer {admin_token}"})
    assert invites.status_code == 200
    assert any(i["token"] == token for i in invites.json())


@pytest.mark.asyncio
async def test_admin_cannot_delete_self(test_app, admin_token):
    """Admin cannot delete own account."""
    me = await test_app.get("/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    user_id = me.json()["id"]
    resp = await test_app.delete(f"/admin/users/{user_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_audit_log_endpoint(test_app, admin_token):
    """Admin can query paginated audit log."""
    resp = await test_app.get("/admin/audit-log", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data and "total" in data
