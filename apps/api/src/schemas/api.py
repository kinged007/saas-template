from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class RegisterRequest(BaseModel):
    email: EmailStr
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    password: str = Field(min_length=8)
    # Deprecated — kept for backward compat, ignored if first_name/last_name provided.
    display_name: str | None = Field(default=None, min_length=1, max_length=150, deprecated=True)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    slug: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=500)


class InvitationCreate(BaseModel):
    email: EmailStr
    role_id: str


class MemberRoleUpdate(BaseModel):
    role_id: str


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=300)
    permissions: list[str] = Field(default_factory=list)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    permissions: list[str] = Field(default_factory=list)


class NotificationAck(BaseModel):
    acknowledged: bool = True


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    participant_user_ids: list[str] = Field(min_length=1, max_length=19)
    initial_message: str = Field(min_length=1, max_length=5000)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)


class ConversationArchive(BaseModel):
    archived: bool


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ConversationRead(BaseModel):
    last_read_message_id: str | None = None


class WebhookSubscriptionCreate(BaseModel):
    url: str = Field(max_length=2000)
    events: list[str] = Field(min_length=1, max_length=50)

class WebhookSubscriptionUpdate(BaseModel):
    url: str | None = Field(default=None, max_length=2000)
    events: list[str] | None = Field(default=None, max_length=50)
    active: bool | None = None

class JobUpdate(BaseModel):
    """Editable job configuration. All fields optional (partial patch)."""

    cron_schedule: str | None = Field(default=None, max_length=100)
    params: dict[str, Any] | None = None
    enabled: bool | None = None
    missed_policy: Literal["single", "ignore"] | None = None


class GenericMessage(BaseModel):
    detail: str


class ProfileBase(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    bio: str | None = Field(default=None, max_length=1000)
    phone_number: str | None = Field(default=None, max_length=30)
    timezone: str | None = Field(default=None, max_length=50)
    locale: str | None = Field(default=None, max_length=10)
    date_of_birth: date | None = None
    website_url: AnyHttpUrl | None = None
    location: str | None = Field(default=None, max_length=200)


class ProfileRead(ProfileBase):
    id: str
    user_id: str
    custom_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProfileUpdate(ProfileBase):
    model_config = ConfigDict(extra="forbid")
    custom_data: dict[str, Any] | None = None
    avatar_url: str | None = Field(default=None, max_length=500)


class DeleteMeRequest(BaseModel):
    confirm: Literal["DELETE"]
    password: str | None = None


class ProfileExport(BaseModel):
    exported_at: datetime
    user: dict[str, Any]
    profile: dict[str, Any]
    workspaces: list[dict[str, Any]]
    counts: dict[str, Any]
