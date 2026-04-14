# aribot_auth

Shared authentication and API key module for:
- aribot_live
- backtest_studio

## Required Environment Variables

```bash
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
ARIBOT_MEK=your_64_char_hex_here

# Generate with: python -c "import secrets; print(secrets.token_hex(64))"
ARIBOT_JWT_SECRET=your_128_char_hex_here

ARIBOT_DB=/opt/aribot/shared.db
ARIBOT_APP_NAME=aribot_live
```

## Integration

```python
from fastapi import FastAPI
from aribot_auth import create_auth_app

app = FastAPI()
create_auth_app(app)
```

## Routers

- `/auth`: login, refresh, logout, logout-all, me, change-password, invite claim, MFA setup
- `/api/keys`: encrypted key storage and retrieval
- `/admin`: user/invite/audit administration

## Security Controls

- Password hashing: bcrypt cost factor 12
- Access token: JWT HS256, 15 minutes
- Refresh token: opaque UUID, 7 days, rotation with revoke chain
- API key encryption: AES-256-GCM with per-secret random IV
- MFA secret encryption with ARIBOT_MEK
- Audit trail for auth, admin, and key actions
- Rate limits on login, refresh, and key retrieval
