from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=8)


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


class GenericMessage(BaseModel):
    detail: str
