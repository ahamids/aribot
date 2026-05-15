"""Host X25519 keypair management for the iOS-sourced credential vault.

The bot owns a long-lived X25519 keypair. iOS encrypts user Bybit credentials
TO the bot's public key (via tweetnacl's box construction) and POSTs the
ciphertext to /credentials. The sidecar uses the secret key here to decrypt
in memory.

Security model:
- Secret key lives in the OS keyring (Windows Credential Manager / macOS
  Keychain / Linux Secret Service) via the `keyring` library, NOT in a
  plaintext file. This matches the security-review locked-in choice.
- Public key + fingerprint mirror on disk (`.aribot/bot_pubkey.txt`) so the
  operator and iOS can read it without unlocking the keyring — pubkeys are
  public by definition.
- On first boot the fingerprint is printed to stdout so the operator can
  TOFU-pin from iOS by comparing.

This module has zero dependencies on FastAPI / the sidecar; it can also be
imported by unit tests or a future CLI for "show me the bot's identity".
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    from nacl.public import Box, PrivateKey, PublicKey
    from nacl.exceptions import CryptoError
except ImportError as exc:  # pragma: no cover - import failure is fatal
    raise SystemExit(
        "bot_keypair requires PyNaCl. Install with: pip install -r requirements-status-server.txt"
    ) from exc

try:
    import keyring
    import keyring.errors
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "bot_keypair requires the keyring library. Install with: pip install -r requirements-status-server.txt"
    ) from exc


_KEYRING_SERVICE = "aribot"
_KEYRING_USERNAME = "host_box_sk_v1"
_PUBKEY_FILENAME = "bot_pubkey.txt"


@dataclass(frozen=True)
class HostIdentity:
    """The bot's long-lived identity from the iOS app's point of view."""

    public_key: bytes
    public_key_b64: str
    fingerprint: str  # short hex (first 16 chars of sha256), for human display

    def decrypt(self, ciphertext: bytes, nonce: bytes, sender_pubkey: bytes) -> bytes:
        """Decrypt a sealed-box payload from iOS. The sender pubkey is the
        ephemeral X25519 key iOS generates per push, NOT the user's long-term
        Keychain key — see app/src/lib/crypto.ts sealForRecipient.
        """
        sk = _load_secret_key()
        box = Box(sk, PublicKey(sender_pubkey))
        try:
            return box.decrypt(ciphertext, nonce)
        except CryptoError as exc:
            raise CredentialDecryptError("sealed-box decrypt failed") from exc


class CredentialDecryptError(RuntimeError):
    """Raised when /credentials POST cannot be decrypted with the bot key."""


def _fingerprint(pub: bytes) -> str:
    return hashlib.sha256(pub).hexdigest()[:16]


def _load_secret_key() -> PrivateKey:
    """Read the bot's X25519 secret key from the OS keyring.

    Raises if the keyring lookup fails or the stored value is corrupt — the
    caller surfaces this to the operator as "bot identity missing; restart
    the sidecar to regenerate".
    """
    try:
        encoded = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except keyring.errors.KeyringError as exc:
        raise CredentialDecryptError(
            f"OS keyring lookup failed: {exc}. Is a keyring backend available?"
        ) from exc
    if not encoded:
        raise CredentialDecryptError(
            "Bot X25519 secret key not present in OS keyring. "
            "Restart the sidecar to regenerate."
        )
    try:
        raw = base64.b64decode(encoded)
        if len(raw) != 32:
            raise ValueError(f"unexpected secret-key length {len(raw)}")
    except (ValueError, base64.binascii.Error) as exc:
        raise CredentialDecryptError(
            f"Stored bot secret key is corrupt: {exc}"
        ) from exc
    return PrivateKey(raw)


def get_or_create_identity(
    pubkey_dir: Path,
    announce: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
) -> HostIdentity:
    """Return the host's X25519 identity, generating it on first use.

    Idempotent: subsequent calls return the existing keypair without rotating.
    Side effects on first run:
      - generates a fresh nacl keypair
      - stores the secret in the OS keyring
      - writes the public key + fingerprint to `<pubkey_dir>/bot_pubkey.txt`
      - announces the fingerprint via `announce` so the operator can pin it
    """
    try:
        existing = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except keyring.errors.KeyringError as exc:
        raise SystemExit(
            f"[bot_keypair] OS keyring is unreachable: {exc}\n"
            "On Linux, install the secretstorage/SecretService backend "
            "(e.g. gnome-keyring) or set up keyrings.alt with a passphrase store."
        ) from exc

    if existing:
        sk = PrivateKey(base64.b64decode(existing))
        pub_bytes = bytes(sk.public_key)
        return HostIdentity(
            public_key=pub_bytes,
            public_key_b64=base64.b64encode(pub_bytes).decode("ascii"),
            fingerprint=_fingerprint(pub_bytes),
        )

    # First boot: generate, store, announce.
    sk = PrivateKey.generate()
    pub_bytes = bytes(sk.public_key)
    secret_b64 = base64.b64encode(bytes(sk)).decode("ascii")

    try:
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, secret_b64)
    except keyring.errors.PasswordSetError as exc:
        raise SystemExit(
            f"[bot_keypair] Could not write secret to OS keyring: {exc}"
        ) from exc

    fingerprint = _fingerprint(pub_bytes)
    pubkey_dir.mkdir(parents=True, exist_ok=True)
    (pubkey_dir / _PUBKEY_FILENAME).write_text(
        # Two-line format: line 1 is the base64 pubkey (machine-parseable),
        # line 2 is the human fingerprint. Easy to `cat` and read aloud.
        f"{base64.b64encode(pub_bytes).decode('ascii')}\n{fingerprint}\n",
        encoding="ascii",
    )

    announce(
        f"[aribot] bot identity generated. pubkey fingerprint: {fingerprint}\n"
        f"[aribot] When iOS first connects it will TOFU-pin this fingerprint."
    )

    return HostIdentity(
        public_key=pub_bytes,
        public_key_b64=base64.b64encode(pub_bytes).decode("ascii"),
        fingerprint=fingerprint,
    )


def wipe_identity() -> bool:
    """Delete the bot's keypair from the OS keyring. Returns True if a key
    was removed, False if nothing was stored. Used by tests and the future
    'reset bot identity' admin tool.
    """
    try:
        existing = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        if not existing:
            return False
        keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        return True
    except keyring.errors.KeyringError:
        return False


def read_public_key_from_disk(pubkey_dir: Path) -> Optional[HostIdentity]:
    """Read pubkey + fingerprint from the on-disk mirror without touching the
    keyring. Useful for status/diagnostic endpoints that don't need to decrypt.
    Returns None if the file is absent or malformed.
    """
    path = pubkey_dir / _PUBKEY_FILENAME
    try:
        text = path.read_text(encoding="ascii").strip().splitlines()
    except (FileNotFoundError, OSError):
        return None
    if len(text) < 1:
        return None
    pubkey_b64 = text[0].strip()
    try:
        pub_bytes = base64.b64decode(pubkey_b64)
        if len(pub_bytes) != 32:
            return None
    except (ValueError, base64.binascii.Error):
        return None
    fp = text[1].strip() if len(text) > 1 else _fingerprint(pub_bytes)
    return HostIdentity(
        public_key=pub_bytes,
        public_key_b64=pubkey_b64,
        fingerprint=fp,
    )


if __name__ == "__main__":
    # Convenience CLI: `python bot_keypair.py` prints the current pubkey
    # fingerprint, generating one if needed. Useful for the operator to read
    # the fingerprint aloud during iOS pairing.
    target = Path(os.getenv("ARIBOT_PUBKEY_DIR", ".aribot")).resolve()
    identity = get_or_create_identity(target)
    print(f"public_key_b64: {identity.public_key_b64}")
    print(f"fingerprint:    {identity.fingerprint}")
