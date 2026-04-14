import json
from datetime import datetime, timezone
from uuid import uuid4

import aiosqlite
from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, HTTPException, Request

from .audit import log
from .crypto import decrypt, encrypt
from .db import get_db
from .middleware import get_current_user, require_mfa_verified
from .models import KeyCreateRequest, KeyUpdateRequest
from .rate_limiter import key_retrieve_limit

router = APIRouter(prefix="/api/keys", tags=["keys"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("")
async def list_keys(current_user: dict = Depends(get_current_user), db: aiosqlite.Connection = Depends(get_db)) -> list[dict]:
    cursor = await db.execute(
        """
        SELECT id, exchange, label, environment, permissions, created_at, last_used, active
        FROM api_keys WHERE user_id = ? AND active = 1 ORDER BY created_at DESC
        """,
        (current_user["id"],),
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": row["id"],
            "exchange": row["exchange"],
            "label": row["label"],
            "environment": row["environment"],
            "permissions": json.loads(row["permissions"]) if row["permissions"] else None,
            "created_at": row["created_at"],
            "last_used": row["last_used"],
            "active": bool(row["active"]),
        }
        for row in rows
    ]


@router.post("")
async def create_key(
    request: Request,
    body: KeyCreateRequest,
    current_user: dict = Depends(require_mfa_verified),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    if not body.exchange.strip() or not body.label.strip() or not body.api_key.strip() or not body.api_secret.strip():
        raise HTTPException(status_code=400, detail="Required fields must be non-empty")

    enc_key, key_iv, key_tag = encrypt(body.api_key)
    enc_secret, secret_iv, secret_tag = encrypt(body.api_secret)
    key_id = str(uuid4())
    created_at = _now_iso()

    await db.execute(
        """
        INSERT INTO api_keys (
          id, user_id, exchange, label, environment, encrypted_key, encrypted_secret,
          key_iv, secret_iv, key_tag, secret_tag, permissions, created_at, active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            key_id,
            current_user["id"],
            body.exchange,
            body.label,
            body.environment,
            enc_key,
            enc_secret,
            key_iv,
            secret_iv,
            key_tag,
            secret_tag,
            json.dumps(body.permissions) if body.permissions is not None else None,
            created_at,
        ),
    )
    await db.commit()

    await log(
        db,
        "api_key.created",
        current_user["id"],
        current_user["email"],
        request,
        resource=key_id,
        detail={"exchange": body.exchange, "label": body.label, "environment": body.environment},
    )

    return {
        "id": key_id,
        "exchange": body.exchange,
        "label": body.label,
        "environment": body.environment,
        "permissions": body.permissions,
        "created_at": created_at,
    }


@router.get("/{key_id}/retrieve")
@key_retrieve_limit
async def retrieve_key(
    key_id: str,
    request: Request,
    current_user: dict = Depends(require_mfa_verified),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    cursor = await db.execute(
        "SELECT * FROM api_keys WHERE id = ? AND user_id = ? AND active = 1",
        (key_id, current_user["id"]),
    )
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Key not found")

    await log(
        db,
        "api_key.retrieved",
        current_user["id"],
        current_user["email"],
        request,
        resource=key_id,
        detail={"exchange": row["exchange"], "label": row["label"]},
    )

    try:
        api_key = decrypt(row["encrypted_key"], row["key_iv"], row["key_tag"])
        api_secret = decrypt(row["encrypted_secret"], row["secret_iv"], row["secret_tag"])
    except InvalidTag:
        await log(
            db,
            "api_key.retrieved",
            current_user["id"],
            current_user["email"],
            request,
            resource=key_id,
            success=False,
            detail={"error": "InvalidTag"},
        )
        raise HTTPException(status_code=500, detail="Key decryption failed — possible data corruption")

    await db.execute("UPDATE api_keys SET last_used = ? WHERE id = ?", (_now_iso(), key_id))
    await db.commit()

    return {
        "id": row["id"],
        "exchange": row["exchange"],
        "label": row["label"],
        "environment": row["environment"],
        "api_key": api_key,
        "api_secret": api_secret,
    }


@router.delete("/{key_id}")
async def delete_key(
    key_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    cursor = await db.execute(
        "UPDATE api_keys SET active = 0 WHERE id = ? AND user_id = ?",
        (key_id, current_user["id"]),
    )
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Key not found")

    await log(db, "api_key.deleted", current_user["id"], current_user["email"], request, resource=key_id)
    return {"ok": True}


@router.patch("/{key_id}")
async def patch_key(
    key_id: str,
    body: KeyUpdateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    fields: list[str] = []
    values: list[object] = []

    if body.label is not None:
        fields.append("label = ?")
        values.append(body.label)
    if body.permissions is not None:
        fields.append("permissions = ?")
        values.append(json.dumps(body.permissions))

    if not fields:
        raise HTTPException(status_code=400, detail="No changes requested")

    values.extend([key_id, current_user["id"]])
    cursor = await db.execute(
        f"UPDATE api_keys SET {', '.join(fields)} WHERE id = ? AND user_id = ? AND active = 1",
        tuple(values),
    )
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Key not found")

    await log(db, "api_key.updated", current_user["id"], current_user["email"], request, resource=key_id)

    cursor = await db.execute(
        """
        SELECT id, exchange, label, environment, permissions, created_at, last_used, active
        FROM api_keys WHERE id = ?
        """,
        (key_id,),
    )
    row = await cursor.fetchone()
    return {
        "id": row["id"],
        "exchange": row["exchange"],
        "label": row["label"],
        "environment": row["environment"],
        "permissions": json.loads(row["permissions"]) if row["permissions"] else None,
        "created_at": row["created_at"],
        "last_used": row["last_used"],
        "active": bool(row["active"]),
    }
