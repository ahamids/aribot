"""In-memory store for iOS-pushed Bybit credentials.

The sidecar receives sealed-box payloads from the iOS app at POST /credentials,
decrypts them with the host keypair (bot_keypair.HostIdentity), validates the
keys against Bybit's /v5/user/query-api, and stores the plaintext in this
process-local store. The trading bot fetches the plaintext via the IPC handoff
(credential_pipe) at startup; the keys never touch disk.

Replay protection:
  - Each push carries an iOS-side ISO timestamp and a monotonic counter,
    along with the sender's ephemeral pubkey (used to scope the counter so
    a fresh-install device can start counting from 0 without conflicting
    with a prior device's state).
  - We reject |now − timestamp| > 60s.
  - We persist a per-sender_pubkey "last seen counter" on disk in JSON and
    reject any counter <= last seen. The store on disk holds NO secrets.

Concurrency: a single threading.RLock protects the in-memory record. Reads
return a snapshot tuple, so callers don't hold the lock while doing IO.
"""

from __future__ import annotations

import base64
import datetime
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from bot_keypair import HostIdentity, CredentialDecryptError
from secret_loader import (
    BotSecrets,
    SecretValidationError,
    SecretLoader,
)


log = logging.getLogger("aribot.credentials")


_REPLAY_FILE = "replay_state.json"
_MAX_CLOCK_SKEW_SECONDS = 60


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


class CredentialStore:
    """Thread-safe in-memory holder for iOS-supplied credentials."""

    def __init__(self, host: HostIdentity, state_dir: Path):
        self._host = host
        self._state_dir = state_dir
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._current: Optional[LoadedCredentials] = None
        self._replay = _load_replay_state(state_dir / _REPLAY_FILE)

    def is_loaded(self) -> bool:
        with self._lock:
            return self._current is not None

    def status(self) -> CredentialStatus:
        with self._lock:
            if self._current is None:
                return CredentialStatus(loaded=False)
            return CredentialStatus(
                loaded=True,
                fingerprint=self._current.fingerprint,
                source=self._current.source,
                validatedAtIso=self._current.validated_at_iso,
            )

    def clear(self) -> None:
        with self._lock:
            self._current = None
            log.info("credential store cleared")

    def snapshot(self) -> Optional[LoadedCredentials]:
        """Return the current credentials (or None). Callers should NOT log
        or persist the returned record."""
        with self._lock:
            return self._current

    def accept_sealed_push(
        self,
        *,
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
            return CredentialPushResult(
                ok=False,
                detail="read and trade API keys must be different keypairs",
                status_code=422,
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

        with self._lock:
            self._current = LoadedCredentials(
                read_api_key=read_key,
                read_api_secret=read_secret,
                trade_api_key=trade_key,
                trade_api_secret=trade_secret,
                fingerprint=fingerprint,
                validated_at_iso=validated_at,
                source="ios",
            )
            self._replay.remember(sender_pubkey_b64, counter)
            _save_replay_state(self._state_dir / _REPLAY_FILE, self._replay)

        log.info(
            "credentials accepted: fingerprint=%s sender_pub=%s counter=%d",
            fingerprint,
            sender_pubkey_b64[:12] + "…",
            counter,
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
