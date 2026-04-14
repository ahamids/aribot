from collections.abc import Callable

import aiosqlite
import pyotp
from fastapi import Depends, HTTPException, Request
from jwt import ExpiredSignatureError, InvalidTokenError

from .crypto import decrypt_mfa_secret
from .db import get_db
from .jwt_handler import verify_access_token


async def get_current_user(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")

    token = auth_header.split(" ", 1)[1]
    try:
        payload = verify_access_token(token)
    except (ExpiredSignatureError, InvalidTokenError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    cursor = await db.execute(
        """
        SELECT id, email, role, mfa_enabled, active, mfa_secret
        FROM users WHERE id = ?
        """,
        (payload["sub"],),
    )
    row = await cursor.fetchone()
    if row is None or int(row["active"]) != 1:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    user = {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "mfa_enabled": bool(row["mfa_enabled"]),
        "active": bool(row["active"]),
        "mfa_secret": row["mfa_secret"],
    }
    request.state.user = user
    return user


def require_role(*roles: str) -> Callable:
    async def dependency(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return current_user

    return dependency


async def require_mfa_verified(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> dict:
    if not current_user["mfa_enabled"]:
        return current_user

    mfa_token = request.headers.get("x-mfa-token")
    if not mfa_token:
        raise HTTPException(status_code=403, detail="MFA verification required")

    encrypted_secret = current_user.get("mfa_secret")
    if not encrypted_secret:
        raise HTTPException(status_code=403, detail="MFA verification required")

    secret = decrypt_mfa_secret(encrypted_secret)
    if not pyotp.TOTP(secret).verify(mfa_token, valid_window=1):
        raise HTTPException(status_code=403, detail="MFA verification required")

    return current_user
