import os
from typing import Iterable

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi import _rate_limit_exceeded_handler

from .db import get_db, run_migrations
from .middleware import get_current_user, require_mfa_verified, require_role
from .rate_limiter import get_limiter
from .router_admin import router as router_admin
from .router_auth import router as router_auth
from .router_keys import router as router_keys

__version__ = "0.1.0"


def _required_env_vars() -> Iterable[str]:
    return ("ARIBOT_MEK", "ARIBOT_JWT_SECRET", "ARIBOT_DB", "ARIBOT_APP_NAME")


def validate_required_env() -> None:
    missing = [name for name in _required_env_vars() if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")

    app_name = os.environ["ARIBOT_APP_NAME"]
    if app_name not in {"aribot_live", "backtest_studio", "test"}:
        raise RuntimeError("ARIBOT_APP_NAME must be 'aribot_live' or 'backtest_studio'")


def create_auth_app(app: FastAPI) -> FastAPI:
    validate_required_env()

    limiter = get_limiter()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    app.include_router(router_auth)
    app.include_router(router_keys)
    app.include_router(router_admin)

    @app.on_event("startup")
    async def _startup_migrations() -> None:
        await run_migrations(os.environ["ARIBOT_DB"])

    return app


__all__ = [
    "__version__",
    "create_auth_app",
    "get_db",
    "get_current_user",
    "require_role",
    "require_mfa_verified",
]
