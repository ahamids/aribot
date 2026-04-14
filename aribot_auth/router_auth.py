import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import aiosqlite
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .audit import log
from .crypto import decrypt_mfa_secret, encrypt_mfa_secret
from .db import get_db
from .jwt_handler import REFRESH_TOKEN_EXPIRY, issue_access_token, issue_refresh_token
from .middleware import get_current_user, require_mfa_verified
from .models import (
    AcceptInviteRequest,
    ChangePasswordRequest,
    LoginRequest,
    MFAConfirmRequest,
    MFAEnableResponse,
)
from .password import hash_password, verify_password
from .rate_limiter import login_limit, refresh_limit

router = APIRouter(prefix="/auth", tags=["auth"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_rt_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="rt",
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=7 * 24 * 3600,
        path="/auth/refresh",
    )


def _clear_rt_cookie(response: Response) -> None:
    response.set_cookie(
        key="rt",
        value="",
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=0,
        path="/auth/refresh",
    )


@router.post("/login")
@login_limit
async def login(request: Request, body: LoginRequest, response: Response, db: aiosqlite.Connection = Depends(get_db)) -> dict:
    cursor = await db.execute("SELECT * FROM users WHERE email = ?", (body.email.lower(),))
    user = await cursor.fetchone()

    if user is None:
        await log(db, "auth.login.failure", None, body.email.lower(), request, success=False)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    now = datetime.now(timezone.utc)
    locked_until_raw = user["locked_until"]
    if locked_until_raw:
        locked_until = datetime.fromisoformat(locked_until_raw)
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if now < locked_until:
            await log(db, "auth.login.locked", user["id"], user["email"], request, success=False)
            raise HTTPException(status_code=401, detail="Account temporarily locked. Try again later.")

    if not verify_password(body.password, user["password_hash"]):
        failed = int(user["failed_login_count"]) + 1
        if failed >= 5:
            lock_until = (now + timedelta(minutes=15)).isoformat()
            await db.execute(
                "UPDATE users SET failed_login_count = 0, locked_until = ? WHERE id = ?",
                (lock_until, user["id"]),
            )
        else:
            await db.execute("UPDATE users SET failed_login_count = ? WHERE id = ?", (failed, user["id"]))
        await db.commit()
        await log(db, "auth.login.failure", user["id"], user["email"], request, success=False)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if int(user["mfa_enabled"]) == 1:
        if not body.totp_code:
            await log(
                db,
                "auth.login.failure",
                user["id"],
                user["email"],
                request,
                success=False,
                detail={"reason": "mfa_failed"},
            )
            raise HTTPException(status_code=401, detail="Invalid credentials")
        secret = decrypt_mfa_secret(user["mfa_secret"])
        if not pyotp.TOTP(secret).verify(body.totp_code, valid_window=1):
            await log(
                db,
                "auth.login.failure",
                user["id"],
                user["email"],
                request,
                success=False,
                detail={"reason": "mfa_failed"},
            )
            raise HTTPException(status_code=401, detail="Invalid credentials")

    await db.execute(
        "UPDATE users SET failed_login_count = 0, locked_until = NULL, last_login = ? WHERE id = ?",
        (_now_iso(), user["id"]),
    )

    access_token = issue_access_token(user["id"], user["email"], user["role"])
    refresh_token = issue_refresh_token()
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + REFRESH_TOKEN_EXPIRY

    await db.execute(
        """
        INSERT INTO refresh_tokens (id, user_id, issued_at, expires_at, revoked, ip_address, user_agent)
        VALUES (?, ?, ?, ?, 0, ?, ?)
        """,
        (
            refresh_token,
            user["id"],
            issued_at.isoformat(),
            expires_at.isoformat(),
            request.client.host if request.client else None,
            request.headers.get("user-agent"),
        ),
    )
    await db.commit()

    await log(db, "auth.login.success", user["id"], user["email"], request)
    _set_rt_cookie(response, refresh_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"],
            "mfa_enabled": bool(user["mfa_enabled"]),
        },
    }


@router.post("/refresh")
@refresh_limit
async def refresh(request: Request, response: Response, db: aiosqlite.Connection = Depends(get_db)) -> dict:
    rt = request.cookies.get("rt")
    if not rt:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    new_token = issue_refresh_token()
    now = datetime.now(timezone.utc)

    await db.execute("BEGIN IMMEDIATE")
    cursor = await db.execute("SELECT * FROM refresh_tokens WHERE id = ?", (rt,))
    old = await cursor.fetchone()
    if old is None or int(old["revoked"]) == 1:
        await db.execute("ROLLBACK")
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if datetime.fromisoformat(old["expires_at"]) <= now:
        await db.execute("ROLLBACK")
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    await db.execute(
        """
        INSERT INTO refresh_tokens (id, user_id, issued_at, expires_at, revoked, ip_address, user_agent)
        VALUES (?, ?, ?, ?, 0, ?, ?)
        """,
        (
            new_token,
            old["user_id"],
            now.isoformat(),
            (now + REFRESH_TOKEN_EXPIRY).isoformat(),
            request.client.host if request.client else None,
            request.headers.get("user-agent"),
        ),
    )

    updated = await db.execute(
        """
        UPDATE refresh_tokens
        SET revoked = 1, revoked_at = ?, replaced_by = ?
        WHERE id = ? AND revoked = 0 AND expires_at > ?
        """,
        (now.isoformat(), new_token, rt, now.isoformat()),
    )

    if updated.rowcount != 1:
        await db.execute("ROLLBACK")
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    cursor = await db.execute("SELECT id, email, role, mfa_enabled, active FROM users WHERE id = ?", (old["user_id"],))
    user = await cursor.fetchone()
    if user is None or int(user["active"]) != 1:
        await db.execute("UPDATE refresh_tokens SET revoked = 1, revoked_at = ? WHERE id = ?", (now.isoformat(), new_token))
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    await db.commit()

    access_token = issue_access_token(user["id"], user["email"], user["role"])
    _set_rt_cookie(response, new_token)
    await log(
        db,
        "auth.refresh",
        user["id"],
        user["email"],
        request,
        detail={"old_token": rt, "new_token": new_token},
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"],
            "mfa_enabled": bool(user["mfa_enabled"]),
        },
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    rt = request.cookies.get("rt")
    if rt:
        await db.execute("UPDATE refresh_tokens SET revoked = 1, revoked_at = ? WHERE id = ?", (_now_iso(), rt))
        await db.commit()
    _clear_rt_cookie(response)
    await log(db, "auth.logout", current_user["id"], current_user["email"], request)
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    now = _now_iso()
    cursor = await db.execute(
        "UPDATE refresh_tokens SET revoked = 1, revoked_at = ? WHERE user_id = ? AND revoked = 0",
        (now, current_user["id"]),
    )
    await db.commit()
    _clear_rt_cookie(response)
    await log(db, "auth.logout_all", current_user["id"], current_user["email"], request)
    return {"ok": True, "revoked_count": cursor.rowcount}


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user), db: aiosqlite.Connection = Depends(get_db)) -> dict:
    cursor = await db.execute("SELECT created_at, last_login FROM users WHERE id = ?", (current_user["id"],))
    row = await cursor.fetchone()
    return {
        "id": current_user["id"],
        "email": current_user["email"],
        "role": current_user["role"],
        "mfa_enabled": current_user["mfa_enabled"],
        "active": current_user["active"],
        "created_at": row["created_at"],
        "last_login": row["last_login"],
    }


@router.post("/change-password")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    response: Response,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    if len(body.new_password) < 12:
        raise HTTPException(status_code=400, detail="New password must be at least 12 characters")

    cursor = await db.execute("SELECT password_hash FROM users WHERE id = ?", (current_user["id"],))
    row = await cursor.fetchone()
    if row is None or not verify_password(body.current_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password incorrect")

    await db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(body.new_password), current_user["id"]))
    await db.execute(
        "UPDATE refresh_tokens SET revoked = 1, revoked_at = ? WHERE user_id = ? AND revoked = 0",
        (_now_iso(), current_user["id"]),
    )
    await db.commit()
    _clear_rt_cookie(response)
    await log(db, "auth.password_change", current_user["id"], current_user["email"], request)
    return {"ok": True}


@router.post("/accept-invite")
async def accept_invite(request: Request, body: AcceptInviteRequest, db: aiosqlite.Connection = Depends(get_db)) -> dict:
    cursor = await db.execute("SELECT * FROM invites WHERE token = ?", (body.token,))
    invite = await cursor.fetchone()
    if invite is None:
        raise HTTPException(status_code=400, detail="Invalid invite")
    if invite["used_at"] is not None:
        raise HTTPException(status_code=400, detail="Invite already used")
    if datetime.fromisoformat(invite["expires_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invite has expired")
    if len(body.password) < 12:
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters")

    user_id = str(uuid4())
    await db.execute(
        """
        INSERT INTO users (
          id, email, password_hash, role, mfa_secret, mfa_enabled, active,
          invited_by, created_at, failed_login_count
        ) VALUES (?, ?, ?, ?, NULL, 0, 1, ?, ?, 0)
        """,
        (
            user_id,
            invite["email"],
            hash_password(body.password),
            invite["role"],
            invite["invited_by"],
            _now_iso(),
        ),
    )
    await db.execute("UPDATE invites SET used_at = ? WHERE token = ?", (_now_iso(), body.token))
    await db.commit()
    await log(db, "auth.invite.accepted", user_id, invite["email"], request)

    return {"ok": True, "user": {"id": user_id, "email": invite["email"], "role": invite["role"]}}


@router.post("/mfa/enable", response_model=MFAEnableResponse)
async def mfa_enable(
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
) -> MFAEnableResponse:
    if current_user["mfa_enabled"]:
        raise HTTPException(status_code=400, detail="MFA already enabled")

    secret = pyotp.random_base32()
    encrypted_secret = encrypt_mfa_secret(secret)
    await db.execute("UPDATE users SET mfa_secret = ? WHERE id = ?", (encrypted_secret, current_user["id"]))
    await db.commit()

    provisioning_uri = pyotp.TOTP(secret).provisioning_uri(
        current_user["email"],
        issuer_name="Aribot Suite",
    )
    return MFAEnableResponse(provisioning_uri=provisioning_uri, secret=secret)


@router.post("/mfa/confirm")
async def mfa_confirm(
    request: Request,
    body: MFAConfirmRequest,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    cursor = await db.execute("SELECT mfa_secret FROM users WHERE id = ?", (current_user["id"],))
    row = await cursor.fetchone()
    if row is None or row["mfa_secret"] is None:
        raise HTTPException(status_code=400, detail="MFA not initialized. Call /auth/mfa/enable first")

    secret = decrypt_mfa_secret(row["mfa_secret"])
    if not pyotp.TOTP(secret).verify(body.totp_code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid code")

    await db.execute("UPDATE users SET mfa_enabled = 1 WHERE id = ?", (current_user["id"],))
    await db.commit()
    await log(db, "auth.mfa.enabled", current_user["id"], current_user["email"], request)
    return {"ok": True}


@router.post("/mfa/disable")
async def mfa_disable(
    request: Request,
    current_user: dict = Depends(require_mfa_verified),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    await db.execute("UPDATE users SET mfa_enabled = 0, mfa_secret = NULL WHERE id = ?", (current_user["id"],))
    await db.commit()
    await log(db, "auth.mfa.disabled", current_user["id"], current_user["email"], request)
    return {"ok": True}
