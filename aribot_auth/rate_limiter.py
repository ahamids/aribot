from typing import Any

from slowapi import Limiter
from slowapi.util import get_remote_address


def _user_id_key(request: Any) -> str:
    user = getattr(request.state, "user", None)
    if isinstance(user, dict) and user.get("id"):
        return str(user["id"])
    return get_remote_address(request)


_ip_limiter = Limiter(key_func=get_remote_address)
_user_limiter = Limiter(key_func=_user_id_key)


def get_limiter() -> Limiter:
    return _ip_limiter


def login_limit(func):
    return _ip_limiter.limit("10/minute")(func)


def refresh_limit(func):
    return _ip_limiter.limit("30/minute")(func)


def key_retrieve_limit(func):
    return _user_limiter.limit("10/hour")(func)
