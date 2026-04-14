"""
Password hashing and verification utilities using bcrypt.

All passwords are hashed with bcrypt cost 12 for production-grade security.
"""

import bcrypt


def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plaintext.encode(), hashed.encode())
    except Exception:
        return False
        
