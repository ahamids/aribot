# Multi-Tenant Migration — Status & Resume Guide

> Resume document for the single-user → multi-tenant migration of Aribot.
> When opening this repo in a fresh session, read this file first.

**Last updated:** 2026-05-15 (end of Phase 2)
**Branch:** `feat/multi-tenant-migration`
**Commits on branch:** `0323bfa` (baseline) → `5a7d5de` (Phase 1) → `7e9f2ff` (resume doc) → `5da1963` (Phase 2)

---

## Quick state

| Phase | Status | Commit | Description |
| --- | --- | --- | --- |
| 0 — Baseline | ✅ | `0323bfa` (on `main`) | Pre-migration snapshot of single-user codebase |
| 1 — Foundation | ✅ | `5a7d5de` | `auth_supabase.py`, `meta_db.py`, `tenant_registry.py` additions, deps, env, docs |
| 2 — Per-user CredentialStore | ✅ | `5da1963` | `_current` → `_by_user` dict; loopback assertion; legacy sentinel threaded |
| 3 — Bot `--user-id` flag | ⬜ | — | Bot CLI accepts `--user-id`; all paths route through `TenantRegistry` |
| 4 — JWT-aware sidecar | ⬜ | — | Endpoints take JWT, scope per-tenant; isolation smoke test |
| 5 — Decommission legacy default | ⬜ | — | Make Supabase env mandatory unless `--legacy-single-user` |

**Behavior change to date:** zero. The sidecar, bot, and iOS app all run exactly as before Phase 1. The new modules are imported by nothing in the production path.

**User cadence preference:** pause-and-review after every phase. Do not chain.

---

## How to resume

```powershell
# 1. Confirm you're on the right branch
cd C:\git\aribot-og
git status
git log --oneline -5

# Expect: branch feat/multi-tenant-migration, last commit 5a7d5de

# 2. Re-verify Phase 1 modules still smoke-test
python tenant_registry.py
python meta_db.py
python auth_supabase.py
python -c "import status_server; print('legacy sidecar still imports')"

# 3. Read the plan for the next phase below, then ask the user for "go"
```

If `git status` shows uncommitted changes, stop and reconcile before
starting a new phase. Phase commits should be clean diffs.

---

## Architectural decisions (binding for all phases)

These were debated in the planning conversation and locked in:

1. **Pattern: per-tenant SQLite + one bot process per user (Silo).** Not shared DB with `tenant_id` columns. Layout already chosen by `tenant_registry.py`: `<artifact_dir>/tenants/<user_uuid>/usdt_bot_v2.{paper,shadow,live}.db`, `bot.log`, `bot.pid`, `status.json`, `kill_switch.flag`, `config.json`. Plus `<artifact_dir>/meta.db` at the root for cross-tenant operator queries.
2. **Auth: Supabase JWT validated server-side with `PyJWT[crypto]`.** Audience `authenticated`, issuer `f"{SUPABASE_URL}/auth/v1"`, HS256, 30s leeway. Validated `sub` claim becomes `user_id`. Legacy bearer token (`ARIBOT_API_TOKEN`) preserved as a secondary auth path returning a sentinel `AuthUser(id="__legacy__")` for ops/transition use.
3. **Path of authority for `user_id`:** enters the system **exactly once**, in the JWT verifier from the verified `sub` claim. Every downstream consumer takes it as an argument; nothing re-derives it from URL/body/header. This kills the entire IDOR risk class.
4. **API key encryption: in-RAM only, keyed by `user_id`.** Per-user master-key encryption at rest is **out of scope** for this migration (deferred to a follow-up). Phase 2 just makes the in-RAM dict per-user.
5. **One Python process per user**, supervised by sidecar. Per-launch credential pipe with unique handshake token in spawn env.
6. **Sidecar opens DBs read-only**; only the bot writes. Schema init is idempotent and runs per-tenant on first launch. **Zero new migration code.**
7. **`meta.db` is sidecar-only.** Bots never read or write it. Eliminates cross-tenant write contention; gives one stable file to back up regardless of tenant count.
8. **`--legacy-single-user` flag** keeps the single-tenant code path alive through Phases 1-4. Removed in Phase 5.

---

## Files in scope (status across phases)

| File | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 |
| --- | --- | --- | --- | --- | --- |
| `auth_supabase.py` (new) | ✅ created | LEGACY_OPS_ID exported | — | wired into endpoints | — |
| `meta_db.py` (new) | ✅ created | — | — | wired into start/stop | — |
| `tenant_registry.py` | ✅ helpers added | — | — | used in every endpoint | — |
| `credential_store.py` | — | ✅ per-user dict | — | — | — |
| `credential_pipe.py` | — | ✅ 127.0.0.1 assertion | — | — | — |
| `order_executor.py` | — | — | accept `idempotency_db_path` kwarg | — | — |
| `usdt_paper_bot_v2.py` | — | — | **`--user-id` + `TenantRegistry` path resolution** | — | — |
| `status_server.py` | — | ✅ threads `LEGACY_OPS_ID` at all 5 sites | — | **biggest refactor: per-user locks, JWT, per-tenant DB** | mandatory Supabase env |
| `tests/test_multitenant_isolation.py` (new) | — | — | — | created | — |
| `.env.example` | ✅ updated | — | — | — | — |
| `HOW_TO_RUN.md` | ✅ updated | — | — | — | flip default block |
| `requirements-status-server.txt` | ✅ +PyJWT | — | — | — | — |

---

## Phase 2 — Per-user CredentialStore + per-launch pipe wiring

**Goal:** convert `CredentialStore` from single-slot to per-user dict. Sidecar still threads `user_id="__legacy__"` everywhere it currently calls credential_store methods, so legacy mode keeps working while the multi-tenant API exists underneath.

**Files:**

### `credential_store.py` — substantial change
Current state: `self._current: Optional[LoadedCredentials]` at line ~149 — single slot. User B's push silently overwrites User A's keys. **The most dangerous bug in the multi-tenant migration.**

Changes:
- Replace `self._current` with `self._by_user: Dict[str, LoadedCredentials] = {}`
- All public methods take `user_id: str` as first arg: `is_loaded(user_id)`, `status(user_id)`, `clear(user_id)`, `snapshot(user_id)`, `accept_sealed_push(user_id, *, ciphertext_b64, …)`
- `accept_sealed_push` writes into `self._by_user[user_id]`
- Validate `user_id` via `tenant_registry._USER_ID_RE` (or import `_validate_user_id`)
- Replay state stays one shared dict keyed by `sender_pubkey_b64` — that scoping is already correct (each user's iOS session generates its own ephemeral pubkey per push)
- Add `clear_all_for_shutdown()` for sidecar SIGTERM cleanup

### `credential_pipe.py` — small clarification
Already designed as one-shot per `CredentialServer()` instance. No structural change needed. Add:
- Assertion in `start()` that `_bind_host == "127.0.0.1"` (defense against accidental `0.0.0.0`)
- Docstring note that the per-launch handshake token is single-use by design

### `status_server.py` — minimal update
Find every call site of `credential_store.{is_loaded,status,clear,snapshot,accept_sealed_push}` and pass `user_id="__legacy__"` everywhere. This keeps Phase 2 a no-op behavior change while the multi-tenant API exists underneath.

**Test plan:**
- Update or add `python -m credential_store` smoke test that pushes two distinct user IDs and verifies isolation
- Manually re-run the existing single-user workflow per `HOW_TO_RUN.md` — it must work identically
- `python status_server.py --host 0.0.0.0 --port 8787` boots and `/healthz` responds

**Risk:** Medium. Failure mode: a missed call site in `status_server.py` raises `AttributeError` because the old single-arg signature no longer exists. Mitigation: grep audit `grep -n "credential_store\." status_server.py` and confirm every match passes `user_id`.

**Commit message format:**
```
feat(multi-tenant): phase 2 — per-user CredentialStore

Converts CredentialStore from single-slot _current to per-user dict
keyed by user_id. Eliminates the User-B-overwrites-User-A's-keys bug.
Sidecar continues to authenticate with legacy bearer token and threads
user_id="__legacy__" everywhere; behavior unchanged from iOS perspective.
```

---

## Phase 3 — Bot accepts `--user-id`, paths via TenantRegistry

**Goal:** the bot subprocess can be launched with `--user-id <uuid>` and writes all per-tenant files under `<artifact_dir>/tenants/<uuid>/`. Without `--user-id`, behavior is exactly today's single-tenant.

**Files:**

### `order_executor.py` — one-line signature change
Line ~77: `self.idempotency_db_path = os.getenv('ORDER_EXECUTOR_DB', 'usdt_paper_bot_v2.db')`

Change to:
```python
def __init__(self, api_key: str, api_secret: str, *, idempotency_db_path: Optional[str] = None):
    ...
    self.idempotency_db_path = idempotency_db_path or os.getenv('ORDER_EXECUTOR_DB') or 'usdt_paper_bot_v2.db'
```

### `usdt_paper_bot_v2.py` — substantial, surgical
Key edits:

1. **CLI arg** (`parse_runtime_args`, ~line 101): add `parser.add_argument('--user-id', default=os.getenv('ARIBOT_USER_ID'))`
2. **`__main__` block** (~line 3123): if `--user-id` present, instantiate `TenantRegistry(Path(os.getenv('ARIBOT_ARTIFACT_DIR', '.aribot')).resolve())`, call `paths = registry.paths_for(user_id)`, pass into `Aribot` via new `tenant_paths` kwarg
3. **`Aribot.__init__`** (line 283): new optional `tenant_paths: Optional[TenantPaths] = None` kwarg
4. **Path replacements** when `tenant_paths` present:
   - Line ~325 `self.kill_switch_file` → `str(tenant_paths.kill_switch)`
   - Lines ~412-426 (mode-specific db) → `str(tenant_paths.db(mode_slug))`
   - Line ~434 `self.status_snapshot_file` → `str(tenant_paths.status)`
   - Line ~446 `StructuredEventLogger('observability.jsonl', …)` → `str(tenant_paths.root / 'observability.jsonl')`
5. **`setup_logging`** (~line 1057): add `log_file_path: Optional[Path] = None` param; use `tenant_paths.log` when provided
6. **`OrderExecutor` instantiation** (~line 314): pass `idempotency_db_path=self.db_file`
7. **PID write helper**: write `os.getpid()` to `tenant_paths.pid` after successful startup, before main loop
8. **Credential pipe**: env-based already (`ARIBOT_CRED_PIPE`/`ARIBOT_CRED_TOKEN`). No change. Sidecar will set per-launch in Phase 4.

**Test plan:**
- `python usdt_paper_bot_v2.py --symbols-file symbol_focus.example.json` (no `--user-id`) behaves identically to today
- `python usdt_paper_bot_v2.py --user-id 00000000-0000-0000-0000-000000000001 --symbols-file symbol_focus.example.json` writes files under `.aribot/tenants/00000000-0000-0000-0000-000000000001/`
- After grep audit: `Select-String -Pattern "kill_switch|status_snapshot|usdt_bot_v2|usdt_trading_log|observability" usdt_paper_bot_v2.py` — every match should be in branched code (`tenant_paths if … else legacy`)

**Risk:** Medium-High. Failure mode: forgetting one path → bot writes to wrong file. Grep audit is the safety net.

---

## Phase 4 — JWT-aware sidecar + isolation test (the keystone)

**Goal:** `status_server.py` becomes per-tenant. With Supabase env set: full multi-tenant. With only `ARIBOT_API_TOKEN` set: `--legacy-single-user` mode still works.

**Files:**

### `status_server.py` — heavy refactor
Add a `TenantContext` dataclass (or new `tenant_context.py`):
```python
@dataclass(frozen=True)
class TenantContext:
    user_id: str
    paths: TenantPaths
    mode: str          # from registry.read_config
    testnet: bool
```

Replace `_BotLock` (~line 412) with:
```python
class _PerUserBotLocks:
    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
    def get(self, user_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(user_id, threading.Lock())
```

Refactor `start_bot` to take `(cfg, registry, meta_db, credential_store, user_id)`:
- Lock from `_per_user_locks.get(user_id)`
- Paths from `registry.paths_for(user_id)`
- `bot_mode` from `registry.get_mode(user_id)`
- `cred_server = CredentialServer(); cred_handle = cred_server.start(credential_store.snapshot(user_id))`
- `spawn_env["ARIBOT_USER_ID"] = user_id`
- `spawn_env["ARIBOT_ARTIFACT_DIR"] = str(cfg.artifact_dir)`
- PID written to `paths.pid`
- After `Popen`: `meta_db.record_run_start(user_id, run_id)`, `registry.remember_running(BotProcessHandle(...))`

Same surgery for `stop_bot`, `kill_bot`, `clear_kill`.

Endpoint refactor pattern (worked example for `/positions`):
```python
@app.get("/positions", response_model=PositionsOut)
def get_positions(user: AuthUser = Depends(require_user)) -> PositionsOut:
    if user.is_legacy:
        positions = _fetch_open_positions_legacy(cfg)
    else:
        ctx = _resolve_tenant(registry, user.id)
        positions = _fetch_open_positions(ctx)
    return PositionsOut(positions=positions, asOfIso=_now_iso())
```

`/credentials` uses the strict `make_require_user_jwt_only(verifier)` dep — no legacy.

`build_app` signature additions:
```python
def build_app(
    cfg: Config,
    *,
    host_identity: HostIdentity,
    credential_store: CredentialStore,
    registry: TenantRegistry,
    meta_db: MetaDb,
    jwt_verifier: SupabaseJwtVerifier,
) -> FastAPI:
```

`main()`: instantiate `TenantRegistry`, `MetaDb(registry.meta_db_path)`, `SupabaseJwtVerifier(...)`. Crash loudly at startup if Supabase env unset and `--legacy-single-user` not passed.

**Sidecar startup reconciliation:**
```python
def _reconcile_running_bots_on_boot(registry, meta_db):
    for user_id, pid in registry.iter_tenants_with_pid():
        if pid and psutil.pid_exists(pid):
            registry.remember_running(BotProcessHandle(
                user_id=user_id, pid=pid, mode_at_start=registry.get_mode(user_id)))
            log.info("reconciled running bot user=%s pid=%d", user_id, pid)
        elif pid:
            registry.pid_path(user_id).unlink(missing_ok=True)
```

### `tests/test_multitenant_isolation.py` (new)

Coverage:
- Spin up `build_app` with temp `artifact_dir`, injected `SupabaseJwtVerifier` with known secret
- Mint two JWTs (`user_a`, `user_b` UUIDs) using `jwt.encode` with same secret
- POST `/credentials` for User A; assert `credential_store.is_loaded("user_a") is True`, `is_loaded("user_b") is False`
- POST `/credentials` for User B with different fingerprint; assert User A's stored creds unchanged
- Pre-seed two tenant SQLite DBs with different `positions` rows
- `GET /positions` with User A's token → only User A's positions; same for B
- Monkeypatch `subprocess.Popen`; `POST /start` with User A → assert spawn env has `ARIBOT_USER_ID=<user_a>`, credential pipe handle from User A's snapshot
- Concurrent `/start` for A and B in two threads → both succeed (no shared `_BotLock`)
- Two `/start` for User A back-to-back → second returns 409

**This is the acceptance test for the entire migration.** If it passes, the silo is real.

**Risk:** High — the central refactor. The isolation test is the safety net.

---

## Phase 5 — Decommission `--legacy-single-user` default

**Goal:** production is fully multi-tenant; legacy is opt-in for emergencies.

**Files:**

### `status_server.py` — small change
Make Supabase env mandatory unless `--legacy-single-user` explicitly passed:
```python
if not args.legacy_single_user:
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_JWT_SECRET"):
        log.error("Multi-tenant mode requires SUPABASE_URL and SUPABASE_JWT_SECRET. "
                  "Pass --legacy-single-user to opt out (deprecated).")
        sys.exit(2)
```
Print deprecation warning when `--legacy-single-user` is used.

### `HOW_TO_RUN.md`
Update the daily-operation block to use the JWT path. Move the legacy bearer-token instructions into a "Legacy single-tenant mode (deprecated)" section.

**Test plan:** boot with no Supabase env and no `--legacy-single-user` flag → exits with code 2. Boot with Supabase env → multi-tenant works. Boot with `--legacy-single-user` → legacy works + warning printed.

---

## Out of scope (follow-up backlog)

These are deferred until after the migration ships:

1. **Per-user master-key encryption of credentials at rest.** Master key in OS keyring (extend `bot_keypair.py` pattern), per-user wrapped AEAD keys via libsodium. Required to survive sidecar restart without forcing all users to re-push from iOS.
2. **TOTP MFA enforcement** on `POST /credentials` and LIVE-mode flips. Use Supabase Auth's built-in MFA, gate on `aal2`.
3. **`slowapi` rate limiting** keyed on `user_id` (not IP — shared NATs).
4. **Per-user Telegram bot isolation.** Either per-tenant Telegram tokens (each user creates their own) or a single bot that only sends notifications, never accepts commands, with strict `chat_id` scoping.
5. **Audit log GUI** in the iOS app (read from `meta.db.audit_log`).
6. **One-time data migration script** if the operator wants to lift existing `usdt_bot_v2.live.db` into a tenant directory. For now: assume fresh deployment per tenant.

---

## Decisions log (in case anything seems weird later)

- **Why PyJWT instead of python-jose:** smaller surface area, fewer historical CVEs. PyJWT 2.8+ is mature.
- **Why per-tenant SQLite instead of Postgres:** at ≤100 users, SQLite-per-tenant beats Postgres on isolation guarantees, backup simplicity, and operational complexity. Switch to Postgres when (a) cross-tenant analytical queries needed, (b) >200 tenants on one box, or (c) multi-region failover.
- **Why one process per user:** CCXT and Bybit websockets are per-API-key; you pay the connection cost regardless. Per-process gives OS-level fault isolation. RAM cost: ~80-150MB × 50 users = 5-7GB, fits CPX31 easily.
- **Why `id DESC` not `ts DESC` for audit_log ordering:** two events fired within the same millisecond would tie under timestamp ordering. AUTOINCREMENT id is monotonic within the single-writer sidecar, so it gives stable insertion order.
- **Why `--legacy-single-user` exists:** allows shipping each phase without a big-bang cutover. Removed in Phase 5.

---

## Resume checklist for the next session

- [ ] `git log --oneline -3` shows `5a7d5de feat(multi-tenant): phase 1 …`
- [ ] `git status` is clean
- [ ] Three smoke tests pass: `python tenant_registry.py`, `python meta_db.py`, `python auth_supabase.py`
- [ ] Read this file's "Phase 2" section
- [ ] Confirm with user before starting Phase 2 ("ready to start Phase 2?")
- [ ] Implement Phase 2 file-by-file
- [ ] Smoke test before commit
- [ ] Commit on `feat/multi-tenant-migration` with message format `feat(multi-tenant): phase 2 — …`
- [ ] Update this file's Quick state table with the Phase 2 commit hash
- [ ] Pause and present a "Phase 2 Complete" summary; wait for "go" on Phase 3
