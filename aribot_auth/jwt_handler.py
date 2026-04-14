import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt

jwt_secret = os.environ.get("ARIBOT_JWT_SECRET")
if not jwt_secret:
    raise RuntimeError("Missing required environment variable: ARIBOT_JWT_SECRET")

try:
    secret_bytes = bytes.fromhex(jwt_secret)
except ValueError as exc:
    raise RuntimeError("ARIBOT_JWT_SECRET must be a valid hex string") from exc

if len(secret_bytes) != 64:
    raise RuntimeError("ARIBOT_JWT_SECRET must decode to exactly 64 bytes")

ACCESS_SECRET = secret_bytes
ACCESS_TOKEN_EXPIRY = timedelta(minutes=15)
REFRESH_TOKEN_EXPIRY = timedelta(days=7)


def issue_access_token(user_id: str, email: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + ACCESS_TOKEN_EXPIRY).timestamp()),
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, ACCESS_SECRET, algorithm="HS256")


def verify_access_token(token: str) -> dict:
    return jwt.decode(token, ACCESS_SECRET, algorithms=["HS256"])


def issue_refresh_token() -> str:
    return str(uuid4())
