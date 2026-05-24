"""Supabase JWT verification + FastAPI auth dependency.

The sidecar accepts two auth modes on the same endpoints:

1. **Supabase JWT (the multi-tenant path).** Clients sign in to Supabase
   and forward `session.access_token` as `Authorization: Bearer <jwt>`.
   The verifier supports BOTH signing schemes Supabase has shipped:

     * **HS256** — legacy symmetric signing with the project's JWT
       secret. Used by projects created before Supabase's mid-2025
       switch to asymmetric keys.
     * **ES256 / RS256 / EdDSA** — current default. Supabase signs with
       its private key; clients verify against the public key served at
       `<supabase_url>/auth/v1/.well-known/jwks.json`. PyJWT's built-in
       JWKS client caches the key set in-process.

   The algorithm is detected from the unverified JWT header on every
   request and routed to the matching key source. Asymmetric mode does
   NOT require `SUPABASE_JWT_SECRET` to be set; if both are configured,
   each token is verified with the key matching its declared alg.

2. **Legacy shared bearer token (`ARIBOT_API_TOKEN`).** Preserved so
   single-tenant ops workflows keep working through the migration. A
   request authenticated this way receives a sentinel `AuthUser` with
   `id="__legacy__"`; endpoints that require a real tenant must reject
   the sentinel.

`SupabaseJwtVerifier.verify` raises `HTTPException(401, …)` on any
failure (signature, expiry, bad audience/issuer, malformed `sub`).
The intent is to let FastAPI surface 401s without bespoke handling at
every endpoint.
"""

from __future__ import annotations

import hmac
import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional

try:
    import jwt as pyjwt  # PyJWT
except ImportError as _exc:  # pragma: no cover - import-time hint
    raise ImportError(
        "auth_supabase requires PyJWT. Install with `pip install -r "
        "requirements-status-server.txt` (or `pip install 'PyJWT[crypto]>=2.8'`)."
    ) from _exc

from fastapi import Header, HTTPException

log = logging.getLogger("aribot.auth")


# Supabase user IDs are UUID v4 with hyphens. We re-declare the regex here
# instead of importing from tenant_registry to keep auth_supabase free of
# any registry dependency (the registry imports it indirectly via the
# sidecar wiring, not the other way around).
_USER_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

# Sentinel returned for legacy bearer-token authentication. Endpoints
# that require a tenant must check `user.id == LEGACY_OPS_ID` and reject.
LEGACY_OPS_ID = "__legacy__"


@dataclass(frozen=True)
class AuthUser:
    """Identity attached to every authenticated request."""

    id: str           # Supabase UUID (lowercased) or `LEGACY_OPS_ID`
    email: str
    role: str         # `authenticated` for Supabase users, `ops` for legacy

    @property
    def is_legacy(self) -> bool:
        return self.id == LEGACY_OPS_ID


class SupabaseJwtVerifier:
    """Verifies a Supabase JWT and returns an `AuthUser`.

    Supports HS256 (legacy shared secret) and ES256/RS256/EdDSA
    (asymmetric, via the project's JWKS endpoint). The algorithm is
    selected per-token from the unverified header; the verifier never
    accepts a key intended for one alg when verifying a token with a
    different alg (defense against alg-confusion attacks).

    Construction is cheap: no network, no file I/O. The JWKS client is
    lazy-initialized on the first asymmetric token; PyJWT caches keys
    in-process for `JWKS_CACHE_LIFESPAN_SECONDS`. `verify` is the only
    hot path and is thread-safe.
    """

    # Whitelisted algorithms. Anything outside these is rejected before
    # we touch the key material.
    _ASYMMETRIC_ALGS = ("ES256", "RS256", "EdDSA")
    _SYMMETRIC_ALGS = ("HS256",)

    # PyJWT's JWKS client refreshes the keyset on cache miss, but we
    # also have a TTL so a key rotation propagates within this window
    # without a sidecar restart.
    JWKS_CACHE_LIFESPAN_SECONDS = 300

    def __init__(
        self,
        *,
        supabase_url: str,
        jwt_secret: str = "",
        audience: str = "authenticated",
        leeway_seconds: int = 30,
    ) -> None:
        if not supabase_url:
            raise ValueError("supabase_url is required")
        # Empty secret is allowed: asymmetric-only projects don't have
        # one. We only enforce non-empty when an HS256 token actually
        # arrives.
        self._secret = jwt_secret or ""
        self._supabase_url = supabase_url.rstrip("/")
        self._issuer = f"{self._supabase_url}/auth/v1"
        self._audience = audience
        self._leeway = leeway_seconds
        self._jwks_client: Optional[pyjwt.PyJWKClient] = None

    def _jwks(self) -> pyjwt.PyJWKClient:
        if self._jwks_client is None:
            self._jwks_client = pyjwt.PyJWKClient(
                f"{self._supabase_url}/auth/v1/.well-known/jwks.json",
                cache_keys=True,
                lifespan=self.JWKS_CACHE_LIFESPAN_SECONDS,
            )
        return self._jwks_client

    def verify(self, token: str) -> AuthUser:
        # Step 1: peek at the alg before signature verification so we
        # know which key source to consult.
        try:
            header = pyjwt.get_unverified_header(token)
        except pyjwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail=f"jwt malformed header: {exc}")

        alg = header.get("alg", "")
        if alg in self._ASYMMETRIC_ALGS:
            try:
                signing_key = self._jwks().get_signing_key_from_jwt(token)
            except pyjwt.PyJWKClientError as exc:
                raise HTTPException(
                    status_code=401, detail=f"jwks fetch failed: {exc}"
                )
            key: object = signing_key.key
            allowed_algs = list(self._ASYMMETRIC_ALGS)
        elif alg in self._SYMMETRIC_ALGS:
            if not self._secret:
                raise HTTPException(
                    status_code=401,
                    detail="HS256 token but SUPABASE_JWT_SECRET not configured",
                )
            key = self._secret
            allowed_algs = list(self._SYMMETRIC_ALGS)
        else:
            raise HTTPException(
                status_code=401, detail=f"jwt alg not allowed: {alg or '(none)'}"
            )

        # Step 2: full verification against the chosen key + alg.
        try:
            claims = pyjwt.decode(
                token,
                key,
                algorithms=allowed_algs,
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except pyjwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="jwt expired")
        except pyjwt.InvalidIssuerError:
            raise HTTPException(status_code=401, detail="jwt issuer mismatch")
        except pyjwt.InvalidAudienceError:
            raise HTTPException(status_code=401, detail="jwt audience mismatch")
        except pyjwt.InvalidSignatureError:
            raise HTTPException(status_code=401, detail="jwt signature invalid")
        except pyjwt.MissingRequiredClaimError as exc:
            raise HTTPException(status_code=401, detail=f"jwt missing claim: {exc}")
        except pyjwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail=f"jwt invalid: {exc}")

        sub_raw = claims.get("sub")
        if not isinstance(sub_raw, str):
            raise HTTPException(status_code=401, detail="jwt sub missing or not a string")
        sub = sub_raw.lower()
        if not _USER_ID_RE.match(sub):
            raise HTTPException(status_code=401, detail="jwt sub is not a Supabase UUID")

        return AuthUser(
            id=sub,
            email=str(claims.get("email", "")),
            role=str(claims.get("role", "authenticated")),
        )


def _looks_like_jwt(token: str) -> bool:
    """Cheap heuristic: a JWT has exactly two `.` separators and no spaces."""
    return token.count(".") == 2 and " " not in token


def make_require_user(
    verifier: SupabaseJwtVerifier,
    *,
    allow_legacy_token: Optional[str] = None,
) -> Callable[..., AuthUser]:
    """FastAPI dependency factory.

    Returns a function suitable for `Depends(...)`. The returned function
    inspects the `Authorization: Bearer <token>` header and:

    1. If the token shape looks like a JWT, validates it via `verifier`
       and returns the resulting `AuthUser`.
    2. Else, if `allow_legacy_token` is provided and the token matches it
       (constant-time), returns the legacy ops sentinel.
    3. Otherwise raises 401.

    Endpoints that must NOT accept the legacy sentinel should use
    `make_require_user_jwt_only` instead.
    """

    def _require_user(
        authorization: Optional[str] = Header(default=None),
    ) -> AuthUser:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization[len("Bearer ") :].strip()
        if not token:
            raise HTTPException(status_code=401, detail="empty bearer token")

        if _looks_like_jwt(token):
            return verifier.verify(token)

        if allow_legacy_token and hmac.compare_digest(token, allow_legacy_token):
            return AuthUser(id=LEGACY_OPS_ID, email="", role="ops")

        raise HTTPException(status_code=401, detail="invalid token")

    return _require_user


def make_require_user_jwt_only(
    verifier: SupabaseJwtVerifier,
) -> Callable[..., AuthUser]:
    """Stricter variant: rejects the legacy bearer token entirely.

    Use for endpoints that operate on a tenant's secrets or state and
    must never be reachable from the ops bearer token (e.g. `POST
    /credentials`, mode flips to LIVE).
    """

    def _require_user_jwt(
        authorization: Optional[str] = Header(default=None),
    ) -> AuthUser:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization[len("Bearer ") :].strip()
        if not _looks_like_jwt(token):
            raise HTTPException(status_code=401, detail="jwt required for this endpoint")
        return verifier.verify(token)

    return _require_user_jwt


def make_require_user_legacy_only(
    legacy_token: Optional[str],
) -> Callable[..., AuthUser]:
    """Single-tenant fallback dependency. Used when the sidecar runs with
    `--legacy-single-user` and no Supabase verifier is configured.

    Returns the legacy sentinel `AuthUser(id=LEGACY_OPS_ID, role='ops')` when
    the bearer token matches `legacy_token` (constant-time compare). Raises
    503 if `legacy_token` is None (refuse to authenticate without a configured
    secret), 401 otherwise.

    Endpoint bodies that branch on `user.is_legacy` continue to work
    uniformly because this dependency returns the same `AuthUser` shape as
    `make_require_user`.
    """

    def _require_user_legacy(
        authorization: Optional[str] = Header(default=None),
    ) -> AuthUser:
        if not legacy_token:
            raise HTTPException(
                status_code=503,
                detail="ARIBOT_API_TOKEN not configured; cannot authenticate in legacy mode",
            )
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization[len("Bearer ") :].strip()
        if not hmac.compare_digest(token, legacy_token):
            raise HTTPException(status_code=401, detail="invalid bearer token")
        return AuthUser(id=LEGACY_OPS_ID, email="", role="ops")

    return _require_user_legacy


if __name__ == "__main__":
    # Smoke test: round-trip JWTs through the verifier in both HS256
    # (legacy shared secret) and ES256 (asymmetric, JWKS) modes.
    import time
    import uuid

    secret = "test-secret-do-not-use-in-prod-padding-padding-pad"
    supabase_url = "https://example.supabase.co"
    verifier = SupabaseJwtVerifier(jwt_secret=secret, supabase_url=supabase_url)

    user_id = str(uuid.uuid4())
    now = int(time.time())
    token = pyjwt.encode(
        {
            "sub": user_id,
            "email": "test@example.com",
            "role": "authenticated",
            "aud": "authenticated",
            "iss": f"{supabase_url}/auth/v1",
            "iat": now,
            "exp": now + 3600,
        },
        secret,
        algorithm="HS256",
    )

    user = verifier.verify(token)
    assert user.id == user_id, (user.id, user_id)
    assert user.email == "test@example.com"
    assert user.role == "authenticated"
    assert not user.is_legacy
    print(f"hs256 verify ok: {user}")

    # ES256 path: generate a keypair, mint a token, monkeypatch the
    # verifier's JWKS client to return the matching public key.
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    ec_priv = ec.generate_private_key(ec.SECP256R1())
    ec_pub_pem = ec_priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    ec_priv_pem = ec_priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    es_token = pyjwt.encode(
        {
            "sub": user_id,
            "email": "test@example.com",
            "role": "authenticated",
            "aud": "authenticated",
            "iss": f"{supabase_url}/auth/v1",
            "iat": now,
            "exp": now + 3600,
        },
        ec_priv_pem,
        algorithm="ES256",
        headers={"kid": "test-key"},
    )

    class _StubSigningKey:
        def __init__(self, key: object) -> None:
            self.key = key

    class _StubJwksClient:
        def __init__(self, key: object) -> None:
            self._key = key

        def get_signing_key_from_jwt(self, _token: str) -> _StubSigningKey:
            return _StubSigningKey(self._key)

    verifier._jwks_client = _StubJwksClient(  # type: ignore[assignment]
        serialization.load_pem_public_key(ec_pub_pem)
    )
    es_user = verifier.verify(es_token)
    assert es_user.id == user_id
    print(f"es256 verify ok: {es_user}")

    # Expired token should raise.
    expired = pyjwt.encode(
        {
            "sub": user_id,
            "aud": "authenticated",
            "iss": f"{supabase_url}/auth/v1",
            "iat": now - 7200,
            "exp": now - 3600,
        },
        secret,
        algorithm="HS256",
    )
    try:
        verifier.verify(expired)
    except HTTPException as exc:
        assert exc.status_code == 401 and "expired" in exc.detail.lower()
        print(f"expired rejected: {exc.detail}")

    # Unknown algorithm rejected.
    try:
        verifier.verify(pyjwt.encode({"sub": user_id}, "x", algorithm="none"))
    except HTTPException as exc:
        # PyJWT refuses to encode with algorithm="none" by default, so
        # we expect either the encode to throw OR the verifier to
        # reject. If we got here, the verifier did its job.
        assert exc.status_code == 401
        print(f"unknown alg rejected: {exc.detail}")
    except (TypeError, ValueError, pyjwt.PyJWTError):
        print("unknown alg rejected at encode (pyjwt refuses 'none')")

    # Asymmetric-only project: no secret configured, HS256 token should
    # be rejected with a clear message.
    asym_only = SupabaseJwtVerifier(supabase_url=supabase_url)
    try:
        asym_only.verify(token)  # token is HS256
    except HTTPException as exc:
        assert exc.status_code == 401 and "SUPABASE_JWT_SECRET" in exc.detail
        print(f"asym-only rejects HS256: {exc.detail}")

    # Legacy token path.
    require = make_require_user(verifier, allow_legacy_token="legacy-token-123")
    legacy = require(authorization="Bearer legacy-token-123")
    assert legacy.is_legacy, legacy
    print(f"legacy ok: {legacy}")

    # Legacy token rejected by jwt-only dependency.
    require_strict = make_require_user_jwt_only(verifier)
    try:
        require_strict(authorization="Bearer legacy-token-123")
    except HTTPException as exc:
        assert exc.status_code == 401
        print(f"strict rejects legacy: {exc.detail}")

    print("auth_supabase smoke test passed.")
