# aribot_auth Threat Model Test Plan

| Threat | Attack vector | Expected response | Mitigation implemented |
|---|---|---|---|
| Database file exfiltration | Attacker reads `shared.db` only | Cannot recover plaintext API keys or MFA secret | API keys and MFA secrets stored as AES-256-GCM ciphertext with IV and tag; no plaintext material stored |
| Database + env exfiltration | Attacker reads `shared.db` and `.env` | Full compromise possible | Operational control: secrets kept outside repo, rotate MEK/JWT immediately, audit anomalies |
| Stolen access token after expiry | Replay expired JWT | `401 Unauthorized` | JWT `exp` enforced by verifier, 15-minute lifetime |
| Stolen refresh token replay after rotation | Old token used after one successful refresh | `401 Unauthorized` | Atomic refresh rotation with `revoked=0` guard and `replaced_by` chain |
| Brute-force login | High-volume wrong passwords | Lock account after 5 failures, then `401` with lock message | Failed login counter + 15-minute lockout + per-IP rate limit |
| TOTP replay | Reuse same TOTP in valid window | Request accepted if still valid; monitor via audit | MFA checked per request; sensitive actions audited for replay detection |
| Horizontal escalation | User A requests user B key ID | `404 Not Found` | Key queries scoped to `user_id = current_user.id` |
| Vertical escalation | Observer calls `/admin/*` | `403 Forbidden` | `require_role("admin")` dependency on all admin routes |
| MEK tamper/ciphertext tamper | Modify encrypted blob or tag in DB | `500` on decrypt failure + audit failure event | AES-GCM authenticity check triggers `InvalidTag`; retrieval logs failure |
| Concurrent refresh race | Two parallel refresh calls with one cookie | Exactly one succeeds, one fails `401` | `BEGIN IMMEDIATE` + atomic guarded `UPDATE` and rowcount check |
