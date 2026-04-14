from sqlalchemy import (
    BOOLEAN,
    BLOB,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", String, primary_key=True),
    Column("email", String, nullable=False, unique=True),
    Column("password_hash", String, nullable=False),
    Column("role", String, nullable=False, server_default="observer"),
    Column("mfa_secret", Text, nullable=True),
    Column("mfa_enabled", Integer, nullable=False, server_default="0"),
    Column("active", Integer, nullable=False, server_default="1"),
    Column("invited_by", String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("created_at", String, nullable=False),
    Column("last_login", String, nullable=True),
    Column("failed_login_count", Integer, nullable=False, server_default="0"),
    Column("locked_until", String, nullable=True),
)

refresh_tokens = Table(
    "refresh_tokens",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("issued_at", String, nullable=False),
    Column("expires_at", String, nullable=False),
    Column("revoked", Integer, nullable=False, server_default="0"),
    Column("revoked_at", String, nullable=True),
    Column("replaced_by", String, nullable=True),
    Column("ip_address", String, nullable=True),
    Column("user_agent", Text, nullable=True),
)

api_keys = Table(
    "api_keys",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("exchange", String, nullable=False),
    Column("label", String, nullable=False),
    Column("environment", String, nullable=False),
    Column("encrypted_key", BLOB, nullable=False),
    Column("encrypted_secret", BLOB, nullable=False),
    Column("key_iv", BLOB, nullable=False),
    Column("secret_iv", BLOB, nullable=False),
    Column("key_tag", BLOB, nullable=False),
    Column("secret_tag", BLOB, nullable=False),
    Column("permissions", Text, nullable=True),
    Column("created_at", String, nullable=False),
    Column("last_used", String, nullable=True),
    Column("active", Integer, nullable=False, server_default="1"),
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", String, primary_key=True),
    Column("timestamp", String, nullable=False),
    Column("user_id", String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("user_email", String, nullable=True),
    Column("app", String, nullable=False),
    Column("action", String, nullable=False),
    Column("resource", String, nullable=True),
    Column("ip_address", String, nullable=True),
    Column("user_agent", Text, nullable=True),
    Column("success", Integer, nullable=False, server_default="1"),
    Column("detail", Text, nullable=True),
)

invites = Table(
    "invites",
    metadata,
    Column("token", String, primary_key=True),
    Column("email", String, nullable=False),
    Column("role", String, nullable=False),
    Column("invited_by", String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", String, nullable=False),
    Column("expires_at", String, nullable=False),
    Column("used_at", String, nullable=True),
)
