from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AuthUserModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="User ID")
    email: str = Field(description="Email address")
    role: Literal["admin", "operator", "observer"] = Field(description="Role")
    mfa_enabled: bool = Field(description="MFA enabled status")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(description="Email address")
    password: str = Field(description="Account password")
    totp_code: str | None = Field(default=None, description="Optional TOTP code")


class LoginResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(description="JWT access token")
    token_type: str = Field(description="Token type")
    user: AuthUserModel = Field(description="Authenticated user")


class RefreshResponse(LoginResponse):
    pass


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="User ID")
    email: str = Field(description="Email")
    role: Literal["admin", "operator", "observer"] = Field(description="Role")
    mfa_enabled: bool = Field(description="MFA enabled")
    active: bool = Field(description="Active status")
    created_at: str = Field(description="Creation timestamp")
    last_login: str | None = Field(default=None, description="Last login timestamp")


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(description="Current password")
    new_password: str = Field(description="New password")


class AcceptInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(description="Invite token")
    password: str = Field(description="Initial password")


class MFAEnableResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provisioning_uri: str = Field(description="Provisioning URI")
    secret: str = Field(description="Raw base32 secret")


class MFAConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    totp_code: str = Field(description="TOTP code")


class KeyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exchange: str = Field(description="Exchange")
    label: str = Field(description="Label", max_length=100)
    environment: Literal["live", "testnet"] = Field(description="Environment")
    api_key: str = Field(description="API key")
    api_secret: str = Field(description="API secret")
    permissions: list[str] | None = Field(default=None, description="Permissions")


class KeyMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Key ID")
    exchange: str = Field(description="Exchange")
    label: str = Field(description="Label")
    environment: str = Field(description="Environment")
    permissions: list[str] | None = Field(default=None, description="Permissions")
    created_at: str = Field(description="Created timestamp")
    last_used: str | None = Field(default=None, description="Last used timestamp")
    active: bool = Field(description="Active state")


class KeyRetrieveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Key ID")
    exchange: str = Field(description="Exchange")
    label: str = Field(description="Label")
    environment: str = Field(description="Environment")
    api_key: str = Field(description="Plaintext api_key")
    api_secret: str = Field(description="Plaintext api_secret")


class KeyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, description="Updated label")
    permissions: list[str] | None = Field(default=None, description="Updated permissions")


class AdminUserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(description="User email")
    password: str = Field(description="Password")
    role: Literal["admin", "operator", "observer"] = Field(description="Role")


class AdminInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(description="Invite email")
    role: Literal["admin", "operator", "observer"] = Field(description="Role")


class AdminInviteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(description="Invite token")
    invite_url_fragment: str = Field(description="Invite URL fragment")
    expires_at: str = Field(description="Expiry timestamp")


class AdminUserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["admin", "operator", "observer"] | None = Field(default=None, description="Optional role")
    active: int | None = Field(default=None, description="Optional active flag")


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="User ID")
    email: str = Field(description="Email")
    role: Literal["admin", "operator", "observer"] = Field(description="Role")
    active: bool = Field(description="Active")
    mfa_enabled: bool = Field(description="MFA enabled")
    created_at: str = Field(description="Creation time")
    last_login: str | None = Field(default=None, description="Last login")
    failed_login_count: int = Field(description="Failed login count")
    locked_until: str | None = Field(default=None, description="Lockout timestamp")


class AdminAuditItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Audit id")
    timestamp: str = Field(description="Timestamp")
    user_id: str | None = Field(default=None, description="User id")
    user_email: str | None = Field(default=None, description="User email")
    app: str = Field(description="Application name")
    action: str = Field(description="Action")
    resource: str | None = Field(default=None, description="Resource")
    ip_address: str | None = Field(default=None, description="IP")
    user_agent: str | None = Field(default=None, description="User agent")
    success: bool = Field(description="Success")
    detail: str | None = Field(default=None, description="JSON detail")


class AdminAuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminAuditItem] = Field(description="Audit items")
    total: int = Field(description="Total count")
    limit: int = Field(description="Applied limit")
    offset: int = Field(description="Applied offset")
