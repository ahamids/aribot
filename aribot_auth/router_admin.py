import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .audit import log
from .db import get_db
from .middleware import require_role
from .models import AdminInviteRequest, AdminUserCreateRequest, AdminUserUpdateRequest
from .password import hash_password

router = APIRouter(prefix="/admin", tags=["admin"])

_ALLOWED_ROLES = {"admin", "operator", "observer"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/users")
async def list_users(
    current_user: dict = Depends(require_role("admin")),
    db: aiosqlite.Connection = Depends(get_db),
) -> list[dict]:
    cursor = await db.execute(
        """
        SELECT id, email, role, active, mfa_enabled, created_at, last_login,
               failed_login_count, locked_until
        FROM users ORDER BY created_at DESC
        """
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


@router.post("/users")
async def create_user(
    request: Request,
    body: AdminUserCreateRequest,
    current_user: dict = Depends(require_role("admin")),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    if body.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    if len(body.password) < 12:
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters")

    user_id = str(uuid4())
    try:
        await db.execute(
            """
            INSERT INTO users (
              id, email, password_hash, role, mfa_enabled, active, created_at,
              failed_login_count
            ) VALUES (?, ?, ?, ?, 0, 1, ?, 0)
            """,
            (user_id, body.email.lower(), hash_password(body.password), body.role, _now_iso()),
        )
        await db.commit()
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Email already registered") from exc

    await log(db, "admin.user.created", current_user["id"], current_user["email"], request, resource=user_id)

    cursor = await db.execute(
        """
        SELECT id, email, role, active, mfa_enabled, created_at, last_login,
               failed_login_count, locked_until
        FROM users WHERE id = ?
        """,
        (user_id,),
    )
    return dict(await cursor.fetchone())


@router.post("/invite")
async def create_invite(
    request: Request,
    body: AdminInviteRequest,
    current_user: dict = Depends(require_role("admin")),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    if body.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")

    cursor = await db.execute("SELECT id FROM users WHERE email = ?", (body.email.lower(),))
    if await cursor.fetchone() is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    token = secrets.token_hex(32)
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(hours=72)

    await db.execute(
        """
        INSERT INTO invites (token, email, role, invited_by, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            token,
            body.email.lower(),
            body.role,
            current_user["id"],
            created_at.isoformat(),
            expires_at.isoformat(),
        ),
    )
    await db.commit()

    await log(
        db,
        "auth.invite.created",
        current_user["id"],
        current_user["email"],
        request,
        detail={"email": body.email.lower(), "role": body.role},
    )

    return {
        "token": token,
        "invite_url_fragment": f"/accept-invite?token={token}",
        "expires_at": expires_at.isoformat(),
    }


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: AdminUserUpdateRequest,
    request: Request,
    current_user: dict = Depends(require_role("admin")),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    if user_id == current_user["id"]:
        if body.role is not None:
            raise HTTPException(status_code=400, detail="Cannot change own role")
        if body.active is not None and int(body.active) == 0:
            raise HTTPException(status_code=400, detail="Cannot deactivate own account")

    updates: list[str] = []
    params: list[object] = []
    action = None

    if body.role is not None:
        if body.role not in _ALLOWED_ROLES:
            raise HTTPException(status_code=400, detail="Invalid role")
        updates.append("role = ?")
        params.append(body.role)
        action = "admin.user.role_changed"

    if body.active is not None:
        updates.append("active = ?")
        params.append(int(body.active))
        if int(body.active) == 0:
            await db.execute(
                "UPDATE refresh_tokens SET revoked = 1, revoked_at = ? WHERE user_id = ? AND revoked = 0",
                (_now_iso(), user_id),
            )
            action = "admin.user.deactivated"

    if not updates:
        raise HTTPException(status_code=400, detail="No changes requested")

    params.append(user_id)
    cursor = await db.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", tuple(params))
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="User not found")

    if action:
        await log(db, action, current_user["id"], current_user["email"], request, resource=user_id)

    cursor = await db.execute(
        """
        SELECT id, email, role, active, mfa_enabled, created_at, last_login,
               failed_login_count, locked_until
        FROM users WHERE id = ?
        """,
        (user_id,),
    )
    return dict(await cursor.fetchone())


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    request: Request,
    current_user: dict = Depends(require_role("admin")),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete own account")

    cursor = await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="User not found")

    await log(db, "admin.user.deleted", current_user["id"], current_user["email"], request, resource=user_id)
    return {"ok": True}


@router.get("/audit-log")
async def audit_log(
    user_id: str | None = None,
    action: str | None = None,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(require_role("admin")),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    where = []
    params: list[object] = []
    if user_id:
        where.append("user_id = ?")
        params.append(user_id)
    if action:
        where.append("action = ?")
        params.append(action)

    where_clause = f"WHERE {' AND '.join(where)}" if where else ""

    cursor = await db.execute(f"SELECT COUNT(*) AS count FROM audit_log {where_clause}", tuple(params))
    total = int((await cursor.fetchone())["count"])

    cursor = await db.execute(
        f"SELECT * FROM audit_log {where_clause} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        tuple([*params, limit, offset]),
    )
    items = [dict(r) for r in await cursor.fetchall()]

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/invites")
async def list_invites(
    current_user: dict = Depends(require_role("admin")),
    db: aiosqlite.Connection = Depends(get_db),
) -> list[dict]:
    cursor = await db.execute("SELECT * FROM invites ORDER BY created_at DESC")
    return [dict(row) for row in await cursor.fetchall()]


@router.delete("/invites/{token}")
async def delete_invite(
    token: str,
    current_user: dict = Depends(require_role("admin")),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    cursor = await db.execute("DELETE FROM invites WHERE token = ?", (token,))
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"ok": True}
