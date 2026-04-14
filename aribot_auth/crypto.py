import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_master_key: bytes | None = None


def get_master_key() -> bytes:
    global _master_key
    if _master_key is not None:
        return _master_key

    mek_hex = os.environ.get("ARIBOT_MEK")
    if not mek_hex:
        raise RuntimeError("Missing required environment variable: ARIBOT_MEK")

    try:
        key = bytes.fromhex(mek_hex)
    except ValueError as exc:
        raise RuntimeError("ARIBOT_MEK must be a valid hex string") from exc

    if len(key) != 32:
        raise RuntimeError("ARIBOT_MEK must decode to exactly 32 bytes")

    _master_key = key
    return _master_key


def encrypt(plaintext: str) -> tuple[bytes, bytes, bytes]:
    iv = secrets.token_bytes(12)
    aesgcm = AESGCM(get_master_key())
    result = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    return result[:-16], iv, result[-16:]


def decrypt(ciphertext: bytes, iv: bytes, tag: bytes) -> str:
    aesgcm = AESGCM(get_master_key())
    return aesgcm.decrypt(iv, ciphertext + tag, None).decode("utf-8")


def encrypt_mfa_secret(secret: str) -> str:
    ciphertext, iv, tag = encrypt(secret)
    return f"{iv.hex()}.{tag.hex()}.{ciphertext.hex()}"


def decrypt_mfa_secret(packed: str) -> str:
    iv_hex, tag_hex, ciphertext_hex = packed.split(".")
    return decrypt(bytes.fromhex(ciphertext_hex), bytes.fromhex(iv_hex), bytes.fromhex(tag_hex))
