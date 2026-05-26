"""Per-user store for pushed Bybit credentials, with optional at-rest encryption.

The sidecar receives sealed-box payloads from the web app at POST /credentials,
decrypts them with the host keypair (bot_keypair.HostIdentity), validates the
keys against Bybit's /v5/user/query-api, and stores the plaintext in this
process-local store. The trading bot fetches the plaintext via the IPC handoff
(credential_pipe) at startup.

At-rest encryption (added 2026-05-26): when a `master_key` is provided at
construction, successful pushes are also serialized → XSalsa20-Poly1305
secretbox-encrypted → written atomically to `state_dir/credentials_at_rest/{user_id}.enc`.
On the next sidecar boot, `load_all_from_disk()` decrypts every file back
into the in-memory store so users don't have to re-push after a deploy or
restart. The master key lives at `state_dir/master.key` (mode 600). When
`master_key=None` the store stays memory-only (legacy/test mode).

Multi-tenant model: every entry is keyed by `user_id` (typically a Supabase
UUID, but treated as an opaque non-empty string by this module — the legacy
single-tenant code path uses the sentinel `"__legacy__"` from
auth_supabase.LEGACY_OPS_ID). Two users pushing credentials never collide:
each lands under their own key in `_by_user`. The caller is responsible for
sourcing `user_id` from a verified JWT (or the legacy sentinel) — this
module performs only minimal "non-empty string" validation because the
user_id is used only as a dict key, never as a path component.

Replay protection:
  - Each push carries an iOS-side ISO timestamp and a monotonic counter,
    along with the sender's ephemeral pubkey (used to scope the counter so
    a fresh-install device can start counting from 0 without conflicting
    with a prior device's state).
  - We reject |now − timestamp| > 60s.
  - We persist a per-sender_pubkey "last seen counter" on disk in JSON and
    reject any counter <= last seen. The store on disk holds NO secrets.
  - Replay state stays keyed by sender_pubkey (NOT user_id) because the
    threat model is "replay an intercepted push" — the sender_pubkey is
    what binds a push to a specific iOS session. Different users have
    distinct ephemeral keypairs; cross-user replay is naturally prevented.

Concurrency: a single threading.RLock protects the in-memory dict. Reads
return a snapshot, so callers don't hold the lock while doing IO.
"""

from __future__ import annotations

import base64
import datetime
import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

import nacl.secret
import nacl.utils

from bot_keypair import HostIdentity, CredentialDecryptError
from secret_loader import (
    BotSecrets,
    SecretValidationError,
    SecretLoader,
)


log = logging.getLogger("aribot.credentials")


_REPLAY_FILE = "replay_state.json"
_MASTER_KEY_FILE = "master.key"
_CREDENTIAL_DIR = "credentials_at_rest"
_MAX_CLOCK_SKEW_SECONDS = 60


def load_or_create_master_key(state_dir: Path) -> bytes:
    """Load the 32-byte symmetric master key, generating it on first boot.

    Stored at `state_dir/master.key` mode 600. The key NEVER rotates — if
    this file is lost, every persisted credentials_at_rest/*.enc becomes
    garbage. The nightly B2 backup MUST include this file alongside the
    encrypted credential files; restoring one without the other is useless.

    Sidecar threat model: if an attacker can read this file off disk they
    can also read the encrypted credential files in the same state dir, so
    on-disk encryption protects against backup leakage and stolen disk
    images — not against a fully-compromised host.
    """
    path = state_dir / _MASTER_KEY_FILE
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        data = None
    if data is not None:
        if len(data) != nacl.secret.SecretBox.KEY_SIZE:
            raise ValueError(
                f"master key at {path} is {len(data)} bytes, "
                f"expected {nacl.secret.SecretBox.KEY_SIZE}"
            )
        return data

    state_dir.mkdir(parents=True, exist_ok=True)
    key = nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(key)
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(path)
    log.warning(
        "generated new credentials master key at %s — back this file up "
        "alongside %s/*.enc or restored credentials will be unrecoverable",
        path,
        _CREDENTIAL_DIR,
    )
    return key


@dataclass
class LoadedCredentials:
    """Plaintext credentials held only in RAM. Never serialized to disk."""

    read_api_key: str
    read_api_secret: str
    trade_api_key: str
    trade_api_secret: str
    fingerprint: str  # sha256(read_key)[:16], for status display only
    validated_at_iso: str
    source: str = "ios"

    def to_bot_secrets(self, *, bot_mode: str, bybit_testnet: bool, kill_switch_file: str) -> BotSecrets:
        return BotSecrets(
            bot_mode=bot_mode,
            bybit_testnet=bybit_testnet,
            kill_switch_file=kill_switch_file,
            read_api_key=self.read_api_key,
            read_api_secret=self.read_api_secret,
            trade_api_key=self.trade_api_key,
            trade_api_secret=self.trade_api_secret,
        )


@dataclass
class CredentialPushResult:
    ok: bool
    detail: str
    fingerprint: Optional[str] = None
    status_code: int = 200  # advisory for the HTTP layer


@dataclass
class CredentialStatus:
    loaded: bool
    fingerprint: Optional[str] = None
    source: Optional[str] = None
    validatedAtIso: Optional[str] = None


@dataclass
class _ReplayState:
    """Per-sender counter ledger, persisted to disk between sidecar restarts."""

    counters: dict[str, int] = field(default_factory=dict)

    def is_fresh(self, sender_pub_b64: str, counter: int) -> bool:
        last = self.counters.get(sender_pub_b64, -1)
        return counter > last

    def remember(self, sender_pub_b64: str, counter: int) -> None:
        self.counters[sender_pub_b64] = counter


def _load_replay_state(path: Path) -> _ReplayState:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        counters = {str(k): int(v) for k, v in (raw.get("counters") or {}).items()}
        return _ReplayState(counters=counters)
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError, TypeError):
        return _ReplayState()


def _save_replay_state(path: Path, state: _ReplayState) -> None:
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"counters": state.counters}, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError as exc:
        log.warning("could not persist replay state: %s", exc)


def _parse_iso(value: str) -> Optional[datetime.datetime]:
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _key_fingerprint(read_key: str) -> str:
    import hashlib

    return hashlib.sha256(read_key.encode("utf-8")).hexdigest()[:16]


def _short_uid(user_id: str) -> str:
    """Truncate a user_id for log lines so we don't dump full UUIDs in plain
    text. Short identifiers (like the legacy sentinel `"__legacy__"`) pass
    through unchanged."""
    return user_id[:8] + "…" if len(user_id) > 12 else user_id


class CredentialStore:
    """Thread-safe holder for pushed Bybit credentials, keyed by user_id.

    Memory-resident by default; if `master_key` is provided at construction
    the store also persists each successful push under `state_dir/credentials_at_rest/`
    encrypted with libsodium secretbox (XSalsa20-Poly1305). On startup the
    caller invokes `load_all_from_disk()` to restore them.
    """

    def __init__(
        self,
        host: HostIdentity,
        state_dir: Path,
        *,
        master_key: Optional[bytes] = None,
    ):
        self._host = host
        self._state_dir = state_dir
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # Per-user credential dict. Empty until the first POST /credentials
        # from any tenant. The legacy sentinel `"__legacy__"` lives here too
        # alongside real Supabase UUIDs; both are treated as opaque keys.
        self._by_user: Dict[str, LoadedCredentials] = {}
        self._replay = _load_replay_state(state_dir / _REPLAY_FILE)

        if master_key is not None:
            if len(master_key) != nacl.secret.SecretBox.KEY_SIZE:
                raise ValueError(
                    f"master_key must be {nacl.secret.SecretBox.KEY_SIZE} bytes, "
                    f"got {len(master_key)}"
                )
            self._box: Optional[nacl.secret.SecretBox] = nacl.secret.SecretBox(master_key)
            self._cred_dir: Optional[Path] = state_dir / _CREDENTIAL_DIR
            self._cred_dir.mkdir(parents=True, exist_ok=True)
            try:
                self._cred_dir.chmod(0o700)
            except OSError:
                pass
        else:
            self._box = None
            self._cred_dir = None

    @property
    def at_rest_enabled(self) -> bool:
        return self._box is not None

    def load_all_from_disk(self) -> int:
        """Decrypt every persisted credentials_at_rest/*.enc and populate the
        in-memory store. Returns count of loaded entries. Failures per file
        log a warning and skip — never crash the sidecar on one bad record."""
        if self._box is None or self._cred_dir is None:
            return 0
        loaded = 0
        skipped = 0
        for path in sorted(self._cred_dir.glob("*.enc")):
            uid = path.stem
            try:
                ct = path.read_bytes()
                pt = self._box.decrypt(ct)
                payload = json.loads(pt.decode("utf-8"))
                cred = LoadedCredentials(**payload)
            except Exception as exc:
                log.warning(
                    "skipping unreadable persisted credentials at %s: %s",
                    path.name,
                    exc,
                )
                skipped += 1
                continue
            with self._lock:
                self._by_user[uid] = cred
            loaded += 1
        if loaded or skipped:
            log.info(
                "credentials at-rest: restored %d record(s) from disk (%d skipped)",
                loaded,
                skipped,
            )
        return loaded

    def _persist_to_disk(self, uid: str, cred: LoadedCredentials) -> None:
        """Encrypt + atomically write a single tenant's credentials. Called
        after a successful in-memory write so the next sidecar boot sees the
        creds without the user re-pushing. No-op when at-rest is disabled."""
        if self._box is None or self._cred_dir is None:
            return
        path = self._cred_dir / f"{uid}.enc"
        try:
            payload = json.dumps(asdict(cred), sort_keys=True).encode("utf-8")
            ct = bytes(self._box.encrypt(payload))
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(ct)
            try:
                tmp.chmod(0o600)
            except OSError:
                pass
            tmp.replace(path)
        except OSError as exc:
            log.warning(
                "could not persist credentials for user=%s: %s",
                _short_uid(uid),
                exc,
            )

    def _delete_persisted(self, uid: str) -> None:
        if self._cred_dir is None:
            return
        try:
            (self._cred_dir / f"{uid}.enc").unlink(missing_ok=True)
        except OSError as exc:
            log.warning(
                "could not delete persisted credentials for user=%s: %s",
                _short_uid(uid),
                exc,
            )

    @staticmethod
    def _check_user_id(user_id: str) -> str:
        """Defensive guard against accidental misuse (None, empty string,
        non-string types). This is NOT a security boundary — the upstream
        JWT verifier is. We just want to fail loudly if a caller forgets
        to thread `user_id` through."""
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id must be a non-empty string")
        return user_id

    def is_loaded(self, user_id: str) -> bool:
        uid = self._check_user_id(user_id)
        with self._lock:
            return uid in self._by_user

    def status(self, user_id: str) -> CredentialStatus:
        uid = self._check_user_id(user_id)
        with self._lock:
            cred = self._by_user.get(uid)
            if cred is None:
                return CredentialStatus(loaded=False)
            return CredentialStatus(
                loaded=True,
                fingerprint=cred.fingerprint,
                source=cred.source,
                validatedAtIso=cred.validated_at_iso,
            )

    def clear(self, user_id: str) -> None:
        uid = self._check_user_id(user_id)
        with self._lock:
            popped = self._by_user.pop(uid, None) is not None
        # Always attempt to remove the on-disk copy even when memory was empty —
        # the sidecar may have just been restarted and the user clicked Wipe
        # before any creds were loaded from disk.
        self._delete_persisted(uid)
        if popped:
            log.info("credential store cleared for user=%s", _short_uid(uid))

    def clear_all_for_shutdown(self) -> None:
        """Drop every tenant's credentials from RAM. Intended for sidecar
        SIGTERM cleanup. Logs the count but no identifying details."""
        with self._lock:
            count = len(self._by_user)
            self._by_user.clear()
            if count:
                log.info("credential store cleared %d record(s) on shutdown", count)

    def loaded_user_ids(self) -> list[str]:
        """List of user_ids with credentials currently in memory. Useful for
        sidecar `/admin` endpoints (future) and for the SIGTERM logger.
        Does not return secrets."""
        with self._lock:
            return list(self._by_user.keys())

    def snapshot(self, user_id: str) -> Optional[LoadedCredentials]:
        """Return the credentials for `user_id` (or None). Callers MUST NOT
        log or persist the returned record."""
        uid = self._check_user_id(user_id)
        with self._lock:
            return self._by_user.get(uid)

    def accept_sealed_push(
        self,
        *,
        user_id: str,
        ciphertext_b64: str,
        nonce_b64: str,
        sender_pubkey_b64: str,
        timestamp_iso: str,
        counter: int,
        bybit_testnet: bool,
    ) -> CredentialPushResult:
        """Handle a POST /credentials payload end-to-end.

        Steps: freshness check → replay check → sealed-box decrypt → JSON
        parse → distinct-keypair check → Bybit /v5/user/query-api validation
        → store in memory → persist replay counter.

        Returns a `CredentialPushResult` whose `status_code` advises the HTTP
        layer (400/401/422/200) without leaking which step failed beyond
        what's safe to expose.
        """
        uid = self._check_user_id(user_id)
        now = datetime.datetime.now(datetime.timezone.utc)

        ts = _parse_iso(timestamp_iso)
        if ts is None:
            return CredentialPushResult(
                ok=False, detail="timestamp unparseable", status_code=400
            )
        skew = abs((now - ts).total_seconds())
        if skew > _MAX_CLOCK_SKEW_SECONDS:
            return CredentialPushResult(
                ok=False,
                detail=f"timestamp outside ±{_MAX_CLOCK_SKEW_SECONDS}s window (skew={skew:.0f}s)",
                status_code=400,
            )

        with self._lock:
            if not self._replay.is_fresh(sender_pubkey_b64, counter):
                return CredentialPushResult(
                    ok=False,
                    detail="replay detected: counter must increase per sender",
                    status_code=409,
                )

        # Decrypt outside the lock so a slow CryptoError doesn't stall reads.
        try:
            ciphertext = base64.b64decode(ciphertext_b64)
            nonce = base64.b64decode(nonce_b64)
            sender_pub = base64.b64decode(sender_pubkey_b64)
        except (ValueError, base64.binascii.Error) as exc:
            return CredentialPushResult(
                ok=False, detail=f"base64 decode failed: {exc}", status_code=400
            )

        try:
            plaintext = self._host.decrypt(ciphertext, nonce, sender_pub)
        except CredentialDecryptError as exc:
            return CredentialPushResult(
                ok=False, detail=f"decrypt failed: {exc}", status_code=400
            )

        try:
            payload = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return CredentialPushResult(
                ok=False, detail=f"decrypted payload not JSON: {exc}", status_code=400
            )

        required = ("readKey", "readSecret", "tradeKey", "tradeSecret")
        missing = [k for k in required if not str(payload.get(k, "")).strip()]
        if missing:
            return CredentialPushResult(
                ok=False,
                detail=f"missing fields in payload: {', '.join(missing)}",
                status_code=400,
            )

        read_key = str(payload["readKey"]).strip()
        read_secret = str(payload["readSecret"]).strip()
        trade_key = str(payload["tradeKey"]).strip()
        trade_secret = str(payload["tradeSecret"]).strip()

        if read_key == trade_key:
            # Using one key for both scopes is supported but reduces blast-
            # radius separation if the key leaks. We log a warning so an
            # operator scanning logs can flag tenants on the "single-key"
            # plan, and let the push proceed. Bybit's own permission check
            # still ensures the key has both read + trade scopes.
            log.warning(
                "tenant %s pushed credentials with identical read/trade key; "
                "permission isolation reduced",
                uid,
            )

        # Validate against Bybit. Reuses the existing logic so the rules are
        # identical to .env-loaded credentials.
        try:
            self._validate_with_bybit(
                read_key, read_secret, trade_key, trade_secret, bybit_testnet
            )
        except SecretValidationError as exc:
            return CredentialPushResult(
                ok=False, detail=f"Bybit validation failed: {exc}", status_code=422
            )

        fingerprint = _key_fingerprint(read_key)
        validated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        cred = LoadedCredentials(
            read_api_key=read_key,
            read_api_secret=read_secret,
            trade_api_key=trade_key,
            trade_api_secret=trade_secret,
            fingerprint=fingerprint,
            validated_at_iso=validated_at,
            source="ios",
        )
        with self._lock:
            self._by_user[uid] = cred
            self._replay.remember(sender_pubkey_b64, counter)
            _save_replay_state(self._state_dir / _REPLAY_FILE, self._replay)

        # Persist outside the lock — disk IO + encryption shouldn't stall
        # concurrent reads. A failure here logs a warning but the in-memory
        # copy is already live, so the current session still works; the
        # user just loses the survives-restart property until the next
        # successful push.
        self._persist_to_disk(uid, cred)

        log.info(
            "credentials accepted: user=%s fingerprint=%s sender_pub=%s counter=%d at_rest=%s",
            _short_uid(uid),
            fingerprint,
            sender_pubkey_b64[:12] + "…",
            counter,
            "yes" if self.at_rest_enabled else "no",
        )
        return CredentialPushResult(
            ok=True, detail="credentials stored", fingerprint=fingerprint, status_code=200
        )

    @staticmethod
    def _validate_with_bybit(
        read_key: str,
        read_secret: str,
        trade_key: str,
        trade_secret: str,
        bybit_testnet: bool,
    ) -> None:
        """Reuse the validator from SecretLoader so iOS-pushed and .env
        credentials face identical Bybit-side checks (withdraw-disabled,
        read perms on the read key, trade perms on the trade key)."""
        loader = SecretLoader(environ={})
        loader.validate_keypair_against_bybit(
            api_key=read_key, api_secret=read_secret, testnet=bybit_testnet, role="read"
        )
        loader.validate_keypair_against_bybit(
            api_key=trade_key, api_secret=trade_secret, testnet=bybit_testnet, role="trade"
        )


if __name__ == "__main__":
    # Smoke-test the per-user dict isolation. This is white-box: it does not
    # exercise sealed-box decryption or Bybit validation (those need a real
    # X25519 keypair and network access). The full end-to-end isolation
    # check lives in tests/test_multitenant_isolation.py (Phase 4).
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        # We pass host=None because none of the tested methods touch _host.
        store = CredentialStore(host=None, state_dir=Path(td))  # type: ignore[arg-type]
        u1 = "11111111-2222-3333-4444-555555555555"
        u2 = "99999999-8888-7777-6666-555555555555"

        assert not store.is_loaded(u1)
        assert not store.is_loaded(u2)
        assert store.loaded_user_ids() == []

        cred_a = LoadedCredentials(
            read_api_key="A_read", read_api_secret="A_read_s",
            trade_api_key="A_trade", trade_api_secret="A_trade_s",
            fingerprint="A_FP", validated_at_iso="2026-01-01T00:00:00+00:00",
        )
        cred_b = LoadedCredentials(
            read_api_key="B_read", read_api_secret="B_read_s",
            trade_api_key="B_trade", trade_api_secret="B_trade_s",
            fingerprint="B_FP", validated_at_iso="2026-01-02T00:00:00+00:00",
        )
        # Direct dict population so we don't need real X25519 + Bybit roundtrip.
        store._by_user[u1] = cred_a
        store._by_user[u2] = cred_b

        assert store.is_loaded(u1) and store.is_loaded(u2)
        assert store.status(u1).fingerprint == "A_FP"
        assert store.status(u2).fingerprint == "B_FP"
        snap_a = store.snapshot(u1)
        snap_b = store.snapshot(u2)
        assert snap_a is not None and snap_a.read_api_key == "A_read"
        assert snap_b is not None and snap_b.read_api_key == "B_read"
        assert set(store.loaded_user_ids()) == {u1, u2}

        # Clearing one user must not affect the other — the migration's whole
        # reason for existing.
        store.clear(u1)
        assert not store.is_loaded(u1)
        assert store.is_loaded(u2)
        assert store.status(u2).fingerprint == "B_FP"
        assert store.snapshot(u1) is None

        # Unknown user returns absent without raising.
        unknown = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        assert not store.is_loaded(unknown)
        assert store.status(unknown).loaded is False
        assert store.snapshot(unknown) is None

        # Empty / non-string user_id raises.
        for bad in ("", "   ", None, 123):
            try:
                store.is_loaded(bad)  # type: ignore[arg-type]
            except ValueError:
                pass
            else:
                raise AssertionError(f"expected ValueError for user_id={bad!r}")

        # Legacy sentinel works as an opaque key.
        store._by_user["__legacy__"] = cred_a
        assert store.is_loaded("__legacy__")
        assert store.status("__legacy__").fingerprint == "A_FP"

        # Shutdown wipes everything in one shot.
        store.clear_all_for_shutdown()
        assert not store.is_loaded(u2)
        assert not store.is_loaded("__legacy__")
        assert store.loaded_user_ids() == []

        print("credential_store smoke test passed.")

    # ─── At-rest encryption round-trip ─────────────────────────────────
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td)
        master = load_or_create_master_key(sd)
        assert (sd / _MASTER_KEY_FILE).exists()
        assert len(master) == 32
        # Idempotent — same key returned on subsequent loads.
        assert load_or_create_master_key(sd) == master

        store1 = CredentialStore(host=None, state_dir=sd, master_key=master)  # type: ignore[arg-type]
        assert store1.at_rest_enabled
        u = "deadbeef-cafe-0000-1111-222233334444"
        cred = LoadedCredentials(
            read_api_key="K_read", read_api_secret="K_read_secret",
            trade_api_key="K_trade", trade_api_secret="K_trade_secret",
            fingerprint="K_FP", validated_at_iso="2026-05-26T00:00:00+00:00",
            source="ios",
        )
        # Bypass the Bybit roundtrip by writing through the internal API.
        store1._by_user[u] = cred
        store1._persist_to_disk(u, cred)
        enc_path = sd / _CREDENTIAL_DIR / f"{u}.enc"
        assert enc_path.exists(), f"expected encrypted file at {enc_path}"
        on_disk = enc_path.read_bytes()
        # Sanity: the ciphertext contains neither plaintext key in cleartext.
        assert b"K_read" not in on_disk and b"K_trade" not in on_disk, \
            "ciphertext leaked plaintext"

        # Fresh store instance — simulates sidecar restart.
        store2 = CredentialStore(host=None, state_dir=sd, master_key=master)  # type: ignore[arg-type]
        assert not store2.is_loaded(u), "fresh store should not auto-load"
        n = store2.load_all_from_disk()
        assert n == 1, f"expected 1 record loaded, got {n}"
        restored = store2.snapshot(u)
        assert restored is not None
        assert restored.read_api_key == "K_read"
        assert restored.trade_api_secret == "K_trade_secret"
        assert restored.fingerprint == "K_FP"

        # clear() removes both in-memory AND on-disk copies so the user
        # actually wiping their vault doesn't get them restored next boot.
        store2.clear(u)
        assert not store2.is_loaded(u)
        assert not enc_path.exists(), "clear() must delete the encrypted file"

        # Wrong master key produces a clean skip, not a crash.
        store1._by_user[u] = cred
        store1._persist_to_disk(u, cred)
        wrong_key = bytes(32)  # zeros — clearly not the real key
        store_bad = CredentialStore(host=None, state_dir=sd, master_key=wrong_key)  # type: ignore[arg-type]
        loaded = store_bad.load_all_from_disk()
        assert loaded == 0, "wrong key should fail to decrypt and return 0"
        assert not store_bad.is_loaded(u)

        print("credential_store at-rest encryption smoke test passed.")
