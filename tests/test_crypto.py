import importlib

import pytest
from cryptography.exceptions import InvalidTag

import aribot_auth.crypto as crypto


def test_encrypt_decrypt_roundtrip() -> None:
    """Encrypt/decrypt returns original plaintext."""
    ciphertext, iv, tag = crypto.encrypt("hello")
    assert crypto.decrypt(ciphertext, iv, tag) == "hello"


def test_encrypt_produces_different_ciphertexts() -> None:
    """Encrypting the same plaintext twice produces different outputs."""
    a = crypto.encrypt("same")
    b = crypto.encrypt("same")
    assert a != b


def test_decrypt_invalid_tag_ciphertext_corrupted() -> None:
    """Decrypt raises InvalidTag when ciphertext is tampered."""
    ciphertext, iv, tag = crypto.encrypt("secret")
    tampered = bytearray(ciphertext)
    tampered[0] ^= 1
    with pytest.raises(InvalidTag):
        crypto.decrypt(bytes(tampered), iv, tag)


def test_decrypt_invalid_tag_tag_corrupted() -> None:
    """Decrypt raises InvalidTag when auth tag is tampered."""
    ciphertext, iv, tag = crypto.encrypt("secret")
    tampered = bytearray(tag)
    tampered[0] ^= 1
    with pytest.raises(InvalidTag):
        crypto.decrypt(ciphertext, iv, bytes(tampered))


def test_get_master_key_raises_if_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_master_key raises RuntimeError if ARIBOT_MEK is missing."""
    monkeypatch.delenv("ARIBOT_MEK", raising=False)
    module = importlib.reload(crypto)
    with pytest.raises(RuntimeError):
        module.get_master_key()


def test_get_master_key_raises_if_wrong_length(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_master_key raises RuntimeError if MEK has wrong length."""
    monkeypatch.setenv("ARIBOT_MEK", "ab")
    module = importlib.reload(crypto)
    with pytest.raises(RuntimeError):
        module.get_master_key()


def test_encrypt_mfa_secret_roundtrip() -> None:
    """encrypt_mfa_secret and decrypt_mfa_secret round-trip correctly."""
    packed = crypto.encrypt_mfa_secret("JBSWY3DPEHPK3PXP")
    assert crypto.decrypt_mfa_secret(packed) == "JBSWY3DPEHPK3PXP"
