"""Loopback IPC for handing decrypted credentials from sidecar to bot.

Why not env vars: a Popen `env=` payload is visible in `/proc/<pid>/environ`
to any same-uid process and in Process Explorer on Windows. The security
review explicitly rejected that option.

Approach used here:
  - Sidecar binds a TCP server on 127.0.0.1 with a kernel-assigned ephemeral
    port. Cross-platform stdlib, no pywin32 required.
  - Sidecar generates a 32-byte random handshake token.
  - Sidecar exports `ARIBOT_CRED_PIPE=<host:port>` and
    `ARIBOT_CRED_TOKEN=<hex-token>` to the spawned bot process. Same-uid
    isolation is acceptable — anything that can read /proc/<pid>/environ
    can also read the in-memory plaintext directly.
  - Bot connects, sends `b"HELLO " + token + b"\\n"`, sidecar verifies via
    hmac.compare_digest, then sends a JSON document terminated by `\\n`.
  - One successful send per launch. The server stops accepting after that,
    so a second connector cannot exfiltrate.

Listener lifetime: started by status_server before Popen, stopped after the
bot reads (or after a 30s timeout, whichever comes first).
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import socket
import threading
from dataclasses import dataclass
from typing import Optional

from credential_store import LoadedCredentials


log = logging.getLogger("aribot.cred_pipe")


@dataclass(frozen=True)
class PipeHandle:
    host: str
    port: int
    token_hex: str

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"


class CredentialServer:
    """One-shot loopback server that hands credentials to a single client.

    Lifecycle: caller invokes `start(credentials)`, gets a PipeHandle to put
    in the bot's env, then `wait_for_handoff(timeout)` blocks until the bot
    connected and read OR the timeout expires. `close()` is idempotent.
    """

    def __init__(self, host: str = "127.0.0.1"):
        self._bind_host = host
        self._token_hex: Optional[str] = None
        self._socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._done = threading.Event()
        self._delivered = False
        self._error: Optional[str] = None
        self._payload_bytes: Optional[bytes] = None

    def start(self, credentials: LoadedCredentials) -> PipeHandle:
        if self._socket is not None:
            raise RuntimeError("CredentialServer already started")

        self._token_hex = secrets.token_hex(32)
        payload = json.dumps(
            {
                "readKey": credentials.read_api_key,
                "readSecret": credentials.read_api_secret,
                "tradeKey": credentials.trade_api_key,
                "tradeSecret": credentials.trade_api_secret,
                "fingerprint": credentials.fingerprint,
                "source": credentials.source,
                "validatedAtIso": credentials.validated_at_iso,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        self._payload_bytes = payload

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self._bind_host, 0))
        srv.listen(1)
        srv.settimeout(1.0)
        self._socket = srv

        port = srv.getsockname()[1]
        handle = PipeHandle(host=self._bind_host, port=int(port), token_hex=self._token_hex)

        self._thread = threading.Thread(
            target=self._serve_once,
            name="aribot-cred-pipe",
            daemon=True,
        )
        self._thread.start()
        log.info("credential pipe listening on %s", handle.address)
        return handle

    def _serve_once(self) -> None:
        assert self._socket is not None and self._token_hex is not None
        srv = self._socket
        # Try to accept one good handshake; rotate through any imposters.
        deadline_loops = 60  # ≈60s with 1s accept timeout
        while not self._done.is_set() and deadline_loops > 0:
            deadline_loops -= 1
            try:
                conn, peer = srv.accept()
            except socket.timeout:
                continue
            except OSError as exc:
                self._error = f"accept failed: {exc}"
                break
            with conn:
                conn.settimeout(5.0)
                try:
                    handled = self._handle_client(conn, peer)
                except OSError as exc:
                    self._error = f"client handler error: {exc}"
                    handled = False
                if handled:
                    self._delivered = True
                    break
        self._done.set()

    def _handle_client(self, conn: socket.socket, peer) -> bool:
        # Tight protocol: line 1 is `HELLO <token-hex>`, line 2 we send back
        # the JSON document. Anything else → drop.
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return False
            buf += chunk
            if len(buf) > 4096:
                return False
        line, _, _ = buf.partition(b"\n")
        try:
            text = line.decode("ascii").strip()
        except UnicodeDecodeError:
            return False
        if not text.startswith("HELLO "):
            return False
        provided = text[len("HELLO "):].strip()
        if not hmac.compare_digest(provided, self._token_hex or ""):
            log.warning("credential pipe: bad handshake token from %s", peer)
            return False
        assert self._payload_bytes is not None
        conn.sendall(self._payload_bytes + b"\n")
        return True

    def wait_for_handoff(self, timeout: float = 30.0) -> bool:
        """Block until the bot has read the credentials or the timeout
        expires. Returns True on a successful delivery."""
        self._done.wait(timeout=timeout)
        return self._delivered

    def close(self) -> None:
        self._done.set()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        # Zero our copy of the payload as best we can. Python strings are
        # immutable so we can only drop the reference; for bytes we overwrite.
        if self._payload_bytes is not None:
            try:
                ba = bytearray(self._payload_bytes)
                for i in range(len(ba)):
                    ba[i] = 0
            except Exception:
                pass
            self._payload_bytes = None

    @property
    def delivered(self) -> bool:
        return self._delivered

    @property
    def error(self) -> Optional[str]:
        return self._error


# ─────────────────────────────────────────────────────────────────────────────
# Client side (used by the bot at startup)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PipeCredentials:
    read_api_key: str
    read_api_secret: str
    trade_api_key: str
    trade_api_secret: str
    fingerprint: str
    source: str
    validated_at_iso: str


def read_from_pipe(address: str, token_hex: str, timeout: float = 5.0) -> PipeCredentials:
    """Connect to the sidecar's credential pipe and read one JSON document.

    `address` is `host:port` from the ARIBOT_CRED_PIPE env var. Raises
    RuntimeError on any protocol or transport failure.
    """
    host, _, port_str = address.partition(":")
    if not host or not port_str:
        raise RuntimeError(f"invalid pipe address '{address}'")
    try:
        port = int(port_str)
    except ValueError as exc:
        raise RuntimeError(f"invalid pipe port '{port_str}'") from exc

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.sendall(f"HELLO {token_hex}\n".encode("ascii"))
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
    except (OSError, socket.timeout) as exc:
        raise RuntimeError(f"credential pipe read failed: {exc}") from exc
    finally:
        try:
            sock.close()
        except OSError:
            pass

    blob = b"".join(chunks).split(b"\n", 1)[0]
    if not blob:
        raise RuntimeError("credential pipe returned no data; bad token?")
    try:
        payload = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"credential pipe payload not JSON: {exc}") from exc

    try:
        return PipeCredentials(
            read_api_key=str(payload["readKey"]),
            read_api_secret=str(payload["readSecret"]),
            trade_api_key=str(payload["tradeKey"]),
            trade_api_secret=str(payload["tradeSecret"]),
            fingerprint=str(payload.get("fingerprint", "")),
            source=str(payload.get("source", "ios")),
            validated_at_iso=str(payload.get("validatedAtIso", "")),
        )
    except KeyError as exc:
        raise RuntimeError(f"pipe payload missing field: {exc}") from exc


def read_from_env() -> Optional[PipeCredentials]:
    """Convenience for bot startup. Returns None if env vars are absent."""
    addr = os.environ.get("ARIBOT_CRED_PIPE", "").strip()
    token = os.environ.get("ARIBOT_CRED_TOKEN", "").strip()
    if not addr or not token:
        return None
    return read_from_pipe(addr, token)
