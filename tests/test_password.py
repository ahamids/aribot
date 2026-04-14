from aribot_auth.password import hash_password, verify_password


def test_hash_password_produces_bcrypt_prefix() -> None:
    """hash_password uses bcrypt cost 12 prefix."""
    hashed = hash_password("Password123!")
    assert hashed.startswith("$2b$12$")


def test_verify_password_correct() -> None:
    """verify_password returns True for matching password."""
    hashed = hash_password("Password123!")
    assert verify_password("Password123!", hashed) is True


def test_verify_password_incorrect() -> None:
    """verify_password returns False for non-matching password."""
    hashed = hash_password("Password123!")
    assert verify_password("Wrong", hashed) is False


def test_verify_password_garbage() -> None:
    """verify_password returns False for invalid hash input."""
    assert verify_password("Password123!", "not-a-hash") is False
