# aribot_auth: Authentication & Authorization Module

A production-grade, security-critical authentication module for **aribot_live** and **backtest_studio**.

## Overview

aribot_auth provides:

- **User Authentication**: Email/password login with optional MFA (TOTP-based)
- **Token Management**: JWT access tokens (15min) + refresh tokens (7 days) with rotation
- **API Key Management**: AES-256-GCM encrypted exchange API key/secret storage
- **Role-Based Access Control**: Admin, Operator, Observer roles with permission enforcement
- **Comprehensive Audit Logging**: Security-critical action logging with timestamps, IPs, and details
- **Rate Limiting**: Slowapi-based protection on sensitive endpoints
- **User Invitations**: 72-hour, one-time-use invite tokens for new account creation

## Architecture

### Database Schema (5 Tables)

| Table | Purpose | Key Fields |
|-------|---------|-----------|
| `users` | User accounts | id, email (unique), password_hash (bcrypt), role, mfa_enabled, active |
| `refresh_tokens` | Session management | id (UUID), user_id, expires_at, revoked, replaced_by (rotation chain) |
| `api_keys` | Encrypted exchange credentials | id, user_id, exchange, encrypted_key/secret (AES-256-GCM), iv, tag |
| `audit_log` | Security audit trail | timestamp (UTC), user, action, resource, success, detail (JSON) |
| `invites` | User invitations | token (hex), email, role, invited_by, expires_at, used_at |

### Cryptography

- **Master Encryption Key (MEK)**: 32-byte key (64 hex chars) from `ARIBOT_MEK` env var, cached at module load
- **AES-256-GCM**: 12-byte fresh IV per encrypt, 16-byte auth tag, no additional data
- **Bcrypt**: Cost factor 12 for password hashing
- **JWT (HS256)**: 64-byte HMAC key (`ARIBOT_JWT_SECRET`), 15-minute expiry per access token

### Token Rotation (Atomic)

Refresh token rotation uses **BEGIN IMMEDIATE transaction** to prevent race conditions:

```python
BEGIN IMMEDIATE  # Write lock
  INSERT new_refresh_token
  UPDATE old_token SET revoked=1, replaced_by=new_token WHERE revoked=0
  CHECK affected_rows > 0  # Detect race
COMMIT
```

## Environment Variables

Required at startup (missing vars raise `RuntimeError`):

| Variable | Format | Example |
|----------|--------|---------|
| `ARIBOT_MEK` | 64 hex chars (32 bytes) | Generated: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ARIBOT_JWT_SECRET` | 128 hex chars (64 bytes) | Generated: `python -c "import secrets; print(secrets.token_hex(64))"` |
| `ARIBOT_DB` | File path | `/path/to/shared.db` |
| `ARIBOT_APP_NAME` | "aribot_live" or "backtest_studio" | `aribot_live` |

## API Endpoints

### Authentication (`/auth`)

#### **POST /auth/login** (Rate: 10 req/min per IP)
Authenticate with email/password, optionally TOTP code.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "secure-password-12+",
  "totp_code": "123456"  // Optional if MFA enabled
}
```

**Response:** 201 Created
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "role": "operator",
    "mfa_enabled": false,
    "active": true,
    "created_at": "2026-04-13T10:30:00Z",
    "last_login": "2026-04-13T14:20:00Z"
  }
}
```

Sets `rt` (refresh token) cookie: `httpOnly, secure, samesite=strict, path=/auth/refresh, max_age=604800`

**Error Responses:**
- 401: "Invalid credentials" | "Account locked" | "MFA code required" | "Invalid MFA code"
- 400: Password validation errors

---

#### **POST /auth/refresh** (Rate: 30 req/min per IP)
Refresh access token using refresh token cookie.

**Request:** Body empty, reads `rt` cookie

**Response:** 200 OK
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "user": { ... }
}
```

Implements **token rotation**: old token revoked, new token issued and set in cookie.

**Error Responses:**
- 401: "Refresh token missing" | "Invalid refresh token" | "Token has been revoked" | "Token has expired" | "User is inactive"
- Special: `"token_already_rotated"` for race condition

---

#### **POST /auth/logout** (Auth Required)
Logout: revoke current refresh token and clear cookie.

**Response:** 200 OK
```json
{ "ok": true }
```

---

#### **POST /auth/logout-all** (Auth Required)
Logout everywhere: revoke all refresh tokens for user.

**Response:** 200 OK
```json
{
  "ok": true,
  "revoked_count": 3
}
```

---

#### **GET /auth/me** (Auth Required)
Get current user profile.

**Response:** 200 OK
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "role": "operator",
  "mfa_enabled": false,
  "active": true,
  "created_at": "2026-04-13T10:30:00Z",
  "last_login": "2026-04-13T14:20:00Z"
}
```

---

#### **POST /auth/change-password** (Auth Required)
Change password for current user. Revokes all existing refresh tokens.

**Request:**
```json
{
  "current_password": "old-password-12+",
  "new_password": "new-password-12+"
}
```

**Response:** 200 OK
```json
{ "ok": true }
```

Clears refresh token cookie.

**Error Responses:**
- 400: "New password must be at least 12 characters" | "Current password is incorrect"

---

#### **POST /auth/accept-invite** (No Auth Required)
Accept invite and create new user account.

**Request:**
```json
{
  "token": "64-character-hex-token",
  "password": "initial-password-12+"
}
```

**Response:** 201 Created
```json
{
  "ok": true,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "newuser@example.com",
    "role": "operator"
  }
}
```

**Error Responses:**
- 400: "Invalid invite" | "Invite already used" | "Invite expired" | "Password must be at least 12 characters"

---

#### **POST /auth/mfa/enable** (Auth Required)
Initialize MFA setup. Returns provisioning URI for QR code + plaintext secret (shown once).

**Response:** 200 OK
```json
{
  "provisioning_uri": "otpauth://totp/user%40example.com?secret=...",
  "secret": "JBSWY3DPEBLW64TMMQ======"
}
```

User must save secret to authenticator app, then call `/mfa/confirm` with TOTP code.

---

#### **POST /auth/mfa/confirm** (Auth Required)
Confirm MFA by verifying TOTP code. Enables MFA if valid.

**Request:**
```json
{
  "totp_code": "123456"
}
```

**Response:** 200 OK
```json
{ "ok": true }
```

**Error Responses:**
- 400: "MFA not initialized" | "Invalid code"

---

#### **POST /auth/mfa/disable** (Auth Required + MFA Verified)
Disable MFA for current user.

**Request:** Body empty, but `X-MFA-Token` header required if MFA enabled

**Response:** 200 OK
```json
{ "ok": true }
```

---

### API Keys (`/api/keys`)

#### **GET /api/keys** (Auth Required)
List all active API keys for current user.

**Response:** 200 OK
```json
[
  {
    "id": "key-uuid",
    "exchange": "bybit",
    "label": "Trading Bot - Testnet",
    "environment": "testnet",
    "permissions": null,
    "created_at": "2026-04-10T08:00:00Z",
    "last_used": "2026-04-13T14:15:00Z",
    "active": true
  }
]
```

---

#### **POST /api/keys** (Auth Required + MFA Verified)
Create new API key. Encrypts key/secret with AES-256-GCM.

**Request:**
```json
{
  "exchange": "bybit",
  "label": "Trading Bot - Testnet",
  "environment": "testnet",
  "api_key": "plaintext-exchange-key",
  "api_secret": "plaintext-exchange-secret",
  "permissions": "{\"read\": true, \"trade\": true}"
}
```

**Response:** 201 Created (metadata only, plaintext NOT returned)
```json
{
  "id": "key-uuid",
  "exchange": "bybit",
  "label": "Trading Bot - Testnet",
  "environment": "testnet",
  "permissions": "{\"read\": true, \"trade\": true}",
  "created_at": "2026-04-13T14:20:00Z",
  "last_used": null,
  "active": true
}
```

---

#### **GET /api/keys/{key_id}/retrieve** (Auth Required + MFA Verified, Rate: 10 req/hour per user)
Retrieve plaintext key/secret. **Audit logged BEFORE decryption.**

**Response:** 200 OK
```json
{
  "id": "key-uuid",
  "exchange": "bybit",
  "label": "Trading Bot - Testnet",
  "environment": "testnet",
  "api_key": "plaintext-exchange-key",
  "api_secret": "plaintext-exchange-secret"
}
```

**Error Responses:**
- 404: "Key not found"
- 500: "Key decryption failed — possible data corruption" (InvalidTag = tamper detected)

---

#### **DELETE /api/keys/{key_id}** (Auth Required)
Soft delete API key (sets `active=0`).

**Response:** 200 OK
```json
{ "ok": true }
```

**Error Responses:**
- 404: "Key not found"

---

#### **PATCH /api/keys/{key_id}** (Auth Required)
Update key metadata (label, permissions). Cannot update encrypted key/secret.

**Request:**
```json
{
  "label": "New Label",
  "permissions": "{\"read\": true}"
}
```

**Response:** 200 OK
```json
{
  "id": "key-uuid",
  "exchange": "bybit",
  "label": "New Label",
  "environment": "testnet",
  "permissions": "{\"read\": true}",
  "created_at": "2026-04-13T14:20:00Z",
  "last_used": "2026-04-13T14:15:00Z",
  "active": true
}
```

---

### Admin (`/admin`)

All endpoints require `require_role("admin")` dependency.

#### **GET /admin/users**
List all active users.

**Response:** 200 OK
```json
[
  {
    "id": "user-uuid",
    "email": "admin@example.com",
    "role": "admin",
    "mfa_enabled": true,
    "active": true,
    "created_at": "2026-01-01T00:00:00Z",
    "last_login": "2026-04-13T14:30:00Z"
  }
]
```

---

#### **POST /admin/users**
Create user directly (admin only).

**Request:**
```json
{
  "email": "newuser@example.com",
  "password": "strong-password-12+",
  "role": "operator"
}
```

**Response:** 201 Created
```json
{
  "id": "user-uuid",
  "email": "newuser@example.com",
  "role": "operator",
  "mfa_enabled": false,
  "active": true,
  "created_at": "2026-04-13T14:25:00Z",
  "last_login": null
}
```

**Error Responses:**
- 400: "Invalid role" | "Password must be at least 12 characters" | "User with this email already exists"

---

#### **PATCH /admin/users/{user_id}**
Update user role or active status. Cannot modify own account.

**Request:**
```json
{
  "role": "admin",
  "active": true
}
```

**Response:** 200 OK
```json
{
  "id": "user-uuid",
  "email": "user@example.com",
  "role": "admin",
  "mfa_enabled": false,
  "active": true,
  "created_at": "2026-04-13T14:25:00Z",
  "last_login": null
}
```

When deactivating, all refresh tokens are revoked automatically.

---

#### **DELETE /admin/users/{user_id}**
Delete user (cascade deletes refresh_tokens, api_keys). Cannot delete own account.

**Response:** 200 OK
```json
{ "ok": true }
```

---

#### **POST /admin/invite**
Create invite for new user (72-hour expiry).

**Request:**
```json
{
  "email": "newuser@example.com",
  "role": "operator"
}
```

**Response:** 201 Created
```json
{
  "token": "64-character-hex-token",
  "invite_url_fragment": "?invite=64-character-hex-token",
  "expires_at": "2026-04-16T14:30:00Z"
}
```

---

#### **GET /admin/invites**
List all invites (unexpired and used).

**Response:** 200 OK
```json
[
  {
    "token": "64-character-hex-token",
    "email": "newuser@example.com",
    "role": "operator",
    "invited_by": "admin-user-uuid",
    "created_at": "2026-04-13T14:30:00Z",
    "expires_at": "2026-04-16T14:30:00Z",
    "used_at": null
  }
]
```

---

#### **DELETE /admin/invites/{token}**
Hard delete invite.

**Response:** 200 OK
```json
{ "ok": true }
```

---

#### **GET /admin/audit-log**
Query audit log with optional filters.

**Query Parameters:**
- `user_id` (optional): Filter by user ID
- `action` (optional): Filter by action name
- `limit` (default 100, max 100)
- `offset` (default 0)

**Response:** 200 OK
```json
{
  "items": [
    {
      "id": "log-entry-uuid",
      "timestamp": "2026-04-13T14:30:00Z",
      "user_email": "user@example.com",
      "app": "aribot_live",
      "action": "auth.login.success",
      "resource": null,
      "success": true,
      "detail": null
    }
  ],
  "total": 150,
  "limit": 100,
  "offset": 0
}
```

---

## Authentication Headers

### Access Token
```
Authorization: Bearer <jwt_access_token>
```

### Refresh Token
Automatically managed via `rt` httpOnly cookie.

### MFA Token (when MFA is enabled)
```
X-MFA-Token: <6-digit-totp-code>
```

## Dependency Injection

FastAPI dependencies for auth middleware:

```python
from aribot_auth import get_current_user, require_role, require_mfa_verified

@app.get("/protected")
async def protected_endpoint(
    current_user: dict = Depends(get_current_user)
):
    return {"user": current_user}

@app.get("/admin-only")
async def admin_endpoint(
    admin_user: dict = Depends(require_role("admin", "operator"))
):
    return {"admin": admin_user}

@app.get("/mfa-protected")
async def mfa_endpoint(
    verified_user: dict = Depends(require_mfa_verified)
):
    return {"verified": verified_user}
```

## Audit Log Actions

Common audit actions logged:
- `auth.login.success`, `auth.login.failed`
- `auth.refresh.success`, `auth.refresh.failed`
- `auth.logout.success`, `auth.logout_all.success`
- `auth.password_change.success`, `auth.password_change.failed`
- `auth.mfa.enabled`, `auth.mfa.disabled`
- `auth.invite.created`, `auth.invite.accepted`, `auth.invite.failed`
- `api_key.created`, `api_key.retrieved`, `api_key.updated`, `api_key.deleted`
- `admin.user.created`, `admin.user.role_changed`, `admin.user.deactivated`, `admin.user.deleted`
- `admin.users.listed`, `admin.invites.listed`, `admin.audit_log.accessed`

## Deployment

1. **Generate Secrets:**
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"   # MEK
   python -c "import secrets; print(secrets.token_hex(64))"   # JWT_SECRET
   ```

2. **Set Environment Variables:**
   ```bash
   export ARIBOT_MEK=<64-hex-chars>
   export ARIBOT_JWT_SECRET=<128-hex-chars>
   export ARIBOT_DB=/path/to/shared.db
   export ARIBOT_APP_NAME=aribot_live
   ```

3. **Run Migrations:**
   ```bash
   python -c "import asyncio; from aribot_auth.db import run_migrations; asyncio.run(run_migrations())"
   ```

4. **Attach to FastAPI App:**
   ```python
   from fastapi import FastAPI
   from aribot_auth import create_auth_app
   
   app = FastAPI()
   app = create_auth_app(app)
   
   # Now /auth, /api/keys, /admin endpoints available
   ```

## Security Notes

- **Master Key**: Never commit `ARIBOT_MEK` to git. Use secure secrets management.
- **Password Requirements**: Minimum 12 characters enforced.
- **Bcrypt Cost**: 12 rounds (~1 second per hash on modern hardware).
- **Token Rotation**: Atomic with write lock to prevent race conditions.
- **Rate Limiting**: Applied to login, refresh, and sensitive key retrieval endpoints.
- **Audit Logging**: All security-critical actions logged with IP, timestamp, and details.
- **MFA**: TOTP with 30-second time window, ±1 window tolerance for clock skew.
- **Encryption**: AES-256-GCM with fresh IV per plaintext, 16-byte auth tag detects tampering.
- **httpOnly Cookies**: Refresh token cannot be accessed from JavaScript, preventing XSS theft.
- **Database**: Foreign keys enforced, WAL mode enabled for concurrent reads/writes.

## License

© Aribot 2026
