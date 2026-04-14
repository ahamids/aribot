"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-13 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="observer"),
        sa.Column("mfa_secret", sa.Text(), nullable=True),
        sa.Column("mfa_enabled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("invited_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("last_login", sa.String(), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.String(), nullable=True),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issued_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("revoked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.String(), nullable=True),
        sa.Column("replaced_by", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exchange", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("encrypted_key", sa.LargeBinary(), nullable=False),
        sa.Column("encrypted_secret", sa.LargeBinary(), nullable=False),
        sa.Column("key_iv", sa.LargeBinary(), nullable=False),
        sa.Column("secret_iv", sa.LargeBinary(), nullable=False),
        sa.Column("key_tag", sa.LargeBinary(), nullable=False),
        sa.Column("secret_tag", sa.LargeBinary(), nullable=False),
        sa.Column("permissions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("last_used", sa.String(), nullable=True),
        sa.Column("active", sa.Integer(), nullable=False, server_default="1"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("timestamp", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_email", sa.String(), nullable=True),
        sa.Column("app", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("success", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("detail", sa.Text(), nullable=True),
    )

    op.create_table(
        "invites",
        sa.Column("token", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("invited_by", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("used_at", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("invites")
    op.drop_table("audit_log")
    op.drop_table("api_keys")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
