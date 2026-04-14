"""
Alembic migration: Initial schema for aribot_auth.

Creates 5 tables:
- users: User accounts with hashed passwords
- refresh_tokens: Refresh tokens with rotation chain
- api_keys: Encrypted API keys and secrets
- audit_log: Security audit trail
- invites: One-time user invites
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


def upgrade() -> None:
    """Create initial database schema."""
    
    # Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="observer"),
        sa.Column("mfa_enabled", sa.Integer, nullable=False, server_default="0"),
        sa.Column("mfa_secret", sa.Text, nullable=True),
        sa.Column("invited_by", sa.String(36), nullable=True),
        sa.Column("active", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(30), nullable=False),
        sa.Column("last_login", sa.String(30), nullable=True),
        sa.Column("failed_login_count", sa.Integer, server_default="0"),
        sa.Column("locked_until", sa.String(30), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_active", "users", ["active"])
    
    # Create refresh_tokens table
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.String(30), nullable=False),
        sa.Column("revoked", sa.Integer, nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.String(30), nullable=True),
        sa.Column("replaced_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.String(30), nullable=False, server_default="CURRENT_TIMESTAMP"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_revoked", "refresh_tokens", ["revoked"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])
    
    # Create api_keys table
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("exchange", sa.String(50), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("environment", sa.String(50), nullable=False),
        sa.Column("encrypted_key", sa.LargeBinary, nullable=False),
        sa.Column("key_iv", sa.LargeBinary(12), nullable=False),
        sa.Column("key_tag", sa.LargeBinary(16), nullable=False),
        sa.Column("encrypted_secret", sa.LargeBinary, nullable=False),
        sa.Column("secret_iv", sa.LargeBinary(12), nullable=False),
        sa.Column("secret_tag", sa.LargeBinary(16), nullable=False),
        sa.Column("permissions", sa.Text, nullable=True),
        sa.Column("active", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(30), nullable=False),
        sa.Column("last_used", sa.String(30), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_active", "api_keys", ["active"])
    op.create_index("ix_api_keys_exchange", "api_keys", ["exchange"])
    
    # Create audit_log table
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("timestamp", sa.String(30), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("app", sa.String(50), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource", sa.String(255), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("success", sa.Integer, nullable=False, server_default="1"),
        sa.Column("detail", sa.Text, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"])
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_resource", "audit_log", ["resource"])
    
    # Create invites table
    op.create_table(
        "invites",
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("invited_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(30), nullable=False),
        sa.Column("expires_at", sa.String(30), nullable=False),
        sa.Column("used_at", sa.String(30), nullable=True),
        sa.PrimaryKeyConstraint("token"),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_invites_email", "invites", ["email"])
    op.create_index("ix_invites_expires_at", "invites", ["expires_at"])
    op.create_index("ix_invites_used_at", "invites", ["used_at"])
    
    # Enable foreign keys
    op.execute("PRAGMA foreign_keys=ON;")


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""
    op.drop_table("invites")
    op.drop_table("audit_log")
    op.drop_table("api_keys")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
