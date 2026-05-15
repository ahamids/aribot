"""Self-signed TLS certificate management for the sidecar.

Per the locked-in security plan, the sidecar runs uvicorn with TLS. iOS pins
the SHA-256 of the cert on first connect (TOFU). For a self-hosted bot this
is the right tradeoff: no public-DNS / Let's Encrypt requirement, and the
pinning gives us channel integrity even with a self-signed cert.

Layout:
  .aribot/tls.crt          <- self-signed cert, PEM (public, on disk is fine)
  .aribot/tls_key.b64       (NOT used) — we store the PRIVATE key in the OS
                            keyring under (aribot, tls_key_v1), same backend
                            as bot_keypair.py.

Why keyring for the TLS private key too? Same reason as the X25519 secret:
a disk-read attacker who finds tls.key plaintext can MITM the sidecar
indefinitely. The cert public material is on disk by design.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import ipaddress
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "tls_cert requires the cryptography library. Install with: "
        "pip install -r requirements-status-server.txt"
    ) from exc

try:
    import keyring
    import keyring.errors
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "tls_cert requires the keyring library."
    ) from exc


_KEYRING_SERVICE = "aribot"
_KEYRING_USERNAME = "tls_key_v1"
_CERT_FILENAME = "tls.crt"
_KEY_FILENAME = "tls.key"  # written briefly during uvicorn startup, see ensure_tls()


@dataclass(frozen=True)
class TlsArtifacts:
    cert_path: Path
    key_path: Path  # path to a freshly-written key file uvicorn can read
    fingerprint_sha256_hex: str  # uppercase colon-separated, iOS UI format


def _cert_fingerprint(cert_der: bytes) -> str:
    digest = hashlib.sha256(cert_der).digest()
    return ":".join(f"{b:02X}" for b in digest)


def _build_self_signed(
    common_name: str = "aribot.local",
    san_dns: tuple[str, ...] = ("localhost", "aribot.local"),
    san_ip: tuple[str, ...] = ("127.0.0.1", "::1"),
    days_valid: int = 825,  # Apple's iOS cert lifetime cap; staying under it
) -> tuple[bytes, bytes]:
    """Generate a P-256 self-signed cert.  Returns (cert_pem, key_pem)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.timezone.utc)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Aribot self-host"),
    ])

    san_entries: list[x509.GeneralName] = [x509.DNSName(d) for d in san_dns]
    for ip in san_ip:
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            continue

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=days_valid))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def ensure_tls(
    artifact_dir: Path,
    announce: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
) -> TlsArtifacts:
    """Make sure tls.crt + a usable tls.key exist on disk for uvicorn.

    On first call:
      - generates a new cert+key
      - writes cert to disk
      - stashes the private key in the OS keyring (encrypted at rest by the OS)
      - rehydrates the keyring copy to a tls.key file for uvicorn to read

    On subsequent calls:
      - reads cert from disk, rehydrates key from keyring

    The on-disk tls.key has 0600 perms where supported. The file is recreated
    on every sidecar boot so a leaked stale copy doesn't outlive a key rotation.
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)
    cert_path = artifact_dir / _CERT_FILENAME
    key_path = artifact_dir / _KEY_FILENAME

    try:
        stored_key_b64 = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except keyring.errors.KeyringError as exc:
        raise SystemExit(
            f"[tls_cert] OS keyring unreachable: {exc}"
        ) from exc

    cert_pem: Optional[bytes] = None
    key_pem: Optional[bytes] = None

    if stored_key_b64 and cert_path.exists():
        try:
            key_pem = base64.b64decode(stored_key_b64)
            cert_pem = cert_path.read_bytes()
        except (ValueError, OSError, base64.binascii.Error):
            cert_pem = None
            key_pem = None

    if cert_pem is None or key_pem is None:
        cert_pem, key_pem = _build_self_signed()
        try:
            keyring.set_password(
                _KEYRING_SERVICE,
                _KEYRING_USERNAME,
                base64.b64encode(key_pem).decode("ascii"),
            )
        except keyring.errors.PasswordSetError as exc:
            raise SystemExit(
                f"[tls_cert] could not stash TLS key in OS keyring: {exc}"
            ) from exc
        cert_path.write_bytes(cert_pem)
        announce("[aribot] generated new self-signed TLS cert")

    # Write the live key file uvicorn will read. Re-created every boot.
    key_path.write_bytes(key_pem)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        # Windows ignores chmod for unix-style bits; rely on inherited NTFS ACLs.
        pass

    # Pin the full-cert DER fingerprint — what iOS URLSession's serverTrust
    # path computes, so the two sides agree byte-for-byte.
    cert_obj = x509.load_pem_x509_certificate(cert_pem)
    der_bytes = cert_obj.public_bytes(serialization.Encoding.DER)
    fp = _cert_fingerprint(der_bytes)

    return TlsArtifacts(
        cert_path=cert_path,
        key_path=key_path,
        fingerprint_sha256_hex=fp,
    )


def wipe_tls() -> bool:
    """Remove TLS key from OS keyring. Cert file on disk is left to the
    operator. Used by the reset/regenerate flow."""
    try:
        if keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME):
            keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
            return True
        return False
    except keyring.errors.KeyringError:
        return False


if __name__ == "__main__":
    target = Path(os.getenv("ARIBOT_TLS_DIR", ".aribot")).resolve()
    artifacts = ensure_tls(target)
    print(f"cert: {artifacts.cert_path}")
    print(f"key:  {artifacts.key_path}")
    print(f"cert SHA-256: {artifacts.fingerprint_sha256_hex}")
