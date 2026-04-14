from datetime import datetime, timedelta, timezone

import jwt
import pytest

from aribot_auth.jwt_handler import ACCESS_SECRET, issue_access_token, issue_refresh_token, verify_access_token


def test_issue_access_token_roundtrip() -> None:
    """Issued access tokens verify and preserve expected claims."""
    token = issue_access_token("u1", "u@example.com", "admin")
    payload = verify_access_token(token)
    assert payload["sub"] == "u1"
    assert payload["email"] == "u@example.com"
    assert payload["role"] == "admin"
    assert "jti" in payload


def test_expired_token_raises() -> None:
    """verify_access_token raises ExpiredSignatureError for expired tokens."""
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "u1",
            "email": "u@example.com",
            "role": "admin",
            "iat": int((now - timedelta(minutes=20)).timestamp()),
            "exp": int((now - timedelta(minutes=5)).timestamp()),
            "jti": "x",
        },
        ACCESS_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_access_token(token)


def test_wrong_secret_raises_invalid() -> None:
    """verify_access_token raises InvalidTokenError for wrong signing secret."""
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "u1",
            "email": "u@example.com",
            "role": "admin",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "jti": "x",
        },
        "a" * 64,
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidTokenError):
        verify_access_token(token)


def test_jti_is_unique() -> None:
    """Two issued tokens carry different jti values."""
    t1 = issue_access_token("u1", "u@example.com", "admin")
    t2 = issue_access_token("u1", "u@example.com", "admin")
    assert verify_access_token(t1)["jti"] != verify_access_token(t2)["jti"]


def test_refresh_token_is_uuid() -> None:
    """issue_refresh_token returns UUID text."""
    token = issue_refresh_token()
    assert len(token) == 36
    assert token[8] == "-"
