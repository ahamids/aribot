import json
import os
import traceback
from datetime import datetime, timezone
from uuid import uuid4

import aiosqlite
from fastapi import Request


def _client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


async def log(
    db: aiosqlite.Connection,
    action: str,
    user_id: str | None,
    user_email: str | None,
    request: Request,
    resource: str | None = None,
    success: bool = True,
    detail: dict | None = None,
) -> None:
    try:
        await db.execute(
            """
            INSERT INTO audit_log (
              id, timestamp, user_id, user_email, app, action, resource,
              ip_address, user_agent, success, detail
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                datetime.now(timezone.utc).isoformat(),
                user_id,
                user_email,
                os.environ["ARIBOT_APP_NAME"],
                action,
                resource,
                _client_ip(request),
                request.headers.get("user-agent"),
                1 if success else 0,
                json.dumps(detail) if detail is not None else None,
            ),
        )
        await db.commit()
    except Exception:
        traceback.print_exc()
