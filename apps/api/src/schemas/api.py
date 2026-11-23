from __future__ import annotations

import math
from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StrictBool,
    StringConstraints,
    field_serializer,
    field_validator,
)
from pydantic_core import PydanticCustomError

from src.core.dates import iso_or_none
from src.models.api_key import MAX_QUOTA, QUOTA_MAX_MESSAGE, QUOTA_MIN_MESSAGE

# strip_whitespace runs before the length check, so padding is normalized on
# write (names are compared exactly on read, e.g. the auto-join lookup) and a
# name that is blank after stripping fails min_length. Only what every name
# field shares lives here; the bound is per-field in Field(max_length=...).
StrippedName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _quota_in_range(value: Any) -> Any:
    """Refuse a quota outside 1..MAX_QUOTA ahead of the bounds, in the service's words.

    A BeforeValidator sees the raw value, before pydantic coerces it to int, so
    int, float and str all have to be read here: a client that sends "0" from a
    form or a YAML config must get the same refusal as one that sends 0.

    ApiKeyService raises the same messages for callers that never reach this
    schema (seed data, direct service calls). PydanticCustomError keeps the 422
    free of the "Value error," prefix pydantic adds to a plain ValueError, and
    reusing the ge=1 / le=MAX_QUOTA codes keeps the rest of the body identical
    to main, so only the wording changes for a client.
    """
    if not isinstance(value, (int, float, str)):
        return value  # null, a datetime, ...: leave the type to pydantic
    try:
        number = float(value)
    except (ValueError, OverflowError):
        # Not a number, or a JSON integer wider than a float64: the int() call
        # below still reads it exactly, so an enormous integer is refused at
        # the upper bound rather than overflowing into a silently unlimited key.
        try:
            number = int(value)
        except (ValueError, OverflowError):
            return value  # leave it to pydantic rather than raise a non-422
        if number > MAX_QUOTA:
            raise PydanticCustomError("less_than_equal", QUOTA_MAX_MESSAGE) from None
        return value
    if not math.isfinite(number) or not number.is_integer():
        return value  # inf/nan is not a quota; 0.5 wants an int, not a bound
    if number < 1:
        raise PydanticCustomError("greater_than_equal", QUOTA_MIN_MESSAGE)
    if number > MAX_QUOTA:
        raise PydanticCustomError("less_than_equal", QUOTA_MAX_MESSAGE)
    return value


# BeforeValidator runs before the bounds on the fields below, so the 422
# carries the service's words. ge/le stay on the fields so OpenAPI states the bounds.
#
# Rows stored with usage_quota = 0 before this guard are dead, not broken:
# record_use's conditional UPDATE refuses every use (0 < 0), so the key
# cannot authenticate, while the listing still reports it with
# X-API-Key-Remaining: 0. Do not migrate them: NULL is the unlimited
# sentinel, so 0 -> NULL would turn every dead credential into an unlimited
# one, and any positive replacement is arbitrary. The repair is a PATCH to a
# positive quota (or null for a deliberately unlimited key); revoking
# (revoked_at) is how to disable a key. No CHECK constraint while a 0 row
# can exist — both backends reject it when violating rows are present, so it
# belongs in the same migration as whatever decision the row count motivates.
QuotaAtLeastOne = Annotated[int | None, BeforeValidator(_quota_in_range)]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    # Browser opt-in: set the HttpOnly refresh cookie and omit the refresh
    # token from the JSON body (in-memory access token only).
    use_cookies: bool = False


class RegisterRequest(BaseModel):
    email: EmailStr
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    # 72 is bcrypt's limit; longer input must be a 422, never a 500.
    password: str = Field(min_length=8, max_length=72)
    # Deprecated — kept for backward compat, ignored if first_name/last_name provided.
    display_name: str | None = Field(default=None, min_length=1, max_length=150, deprecated=True)
    # Browser opt-in: set the HttpOnly refresh cookie and omit the refresh
    # token from the JSON body (in-memory access token only).
    use_cookies: bool = False


class TokenResponse(BaseModel):
    access_token: str
    # Absent for the browser cookie flow (refresh lives in the HttpOnly
    # cookie); present for non-browser JSON clients.
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    # Optional: cookie-authenticated callers send none (refresh comes from
    # the HttpOnly cookie). 401 when neither is present.
    refresh_token: str | None = None
    # Browser opt-in: re-set the HttpOnly refresh cookie on rotation.
    use_cookies: bool = False


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    # 72 is bcrypt's limit; longer input must be a 422, never a 500.
    new_password: str = Field(min_length=8, max_length=72)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1)


class TwoFactorChallenge(BaseModel):
    challenge_token: str


class TwoFactorSetupConfirm(BaseModel):
    setup_token: str
    code: str = Field(min_length=6, max_length=8)


class TwoFactorLogin(BaseModel):
    challenge_token: str
    code: str = Field(min_length=6, max_length=10)
    # Browser opt-in: set the HttpOnly refresh cookie and omit the refresh
    # token from the JSON body (in-memory access token only).
    use_cookies: bool = False


class TwoFactorDisable(BaseModel):
    password: str = Field(min_length=8)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8)
    # 72 is bcrypt's limit; longer input must be a 422, never a 500.
    new_password: str = Field(min_length=8, max_length=72)
    code: str | None = Field(default=None, min_length=6, max_length=10)


class MemberPasswordUpdate(BaseModel):
    """Admin-set password: no current_password. The caller already holds
    `profile:update` on the target's workspace."""

    new_password: str = Field(min_length=8, max_length=72)


# Pydantic serializes a naive datetime with no offset, so the three instants go
# through the shared helper instead of Pydantic's own dialect.
class SessionRead(BaseModel):
    id: str
    created_at: datetime | None = None
    expires_at: datetime | None = None
    # Always None here: `list_sessions` filters revoked rows out.
    revoked_at: datetime | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    current: bool = False

    @field_serializer("created_at", "expires_at", "revoked_at")
    def _utc_iso(self, value: datetime | None) -> str | None:
        return iso_or_none(value)


class WorkspaceCreate(BaseModel):
    name: StrippedName = Field(max_length=150)
    slug: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class WorkspaceUpdate(BaseModel):
    name: StrippedName | None = Field(default=None, max_length=150)
    description: str | None = Field(default=None, max_length=500)
    # StrictBool so a string/int is rejected with 422 rather than coerced.
    # None = leave the flag alone; the flag itself is default-on.
    onboarding_enabled: StrictBool | None = None


class InvitationCreate(BaseModel):
    email: EmailStr
    # UUID, not str: a malformed role_id is a request error (422), and the 400
    # "unknown role for this workspace" stays reserved for a role that does not
    # exist. One status per field, so the response reveals nothing about which.
    role_id: UUID


class MemberRoleUpdate(BaseModel):
    role_id: UUID


class OwnershipTransfer(BaseModel):
    new_owner_membership_id: str


class RoleCreate(BaseModel):
    name: StrippedName = Field(max_length=50)
    description: str | None = Field(default=None, max_length=300)
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: StrippedName | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=300)
    permissions: list[str] | None = None


class ApiKeyCreate(BaseModel):
    name: StrippedName = Field(max_length=150)
    permissions: list[str] = Field(default_factory=list)
    usage_quota: QuotaAtLeastOne = Field(default=None, ge=1, le=MAX_QUOTA)
    # Optional hard expiry. Naive input is rejected: without an offset the
    # instant is ambiguous, and the service compares against UTC.
    expires_at: datetime | None = Field(default=None, examples=["2027-01-01T00:00:00Z"])

    @field_validator("expires_at")
    @classmethod
    def _expires_at_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("expires_at must include a timezone offset (e.g. 2027-01-01T00:00Z)")
        return value


class ApiKeyQuotaUpdate(BaseModel):
    usage_quota: QuotaAtLeastOne = Field(default=None, ge=1, le=MAX_QUOTA)


class NotificationAck(BaseModel):
    acknowledged: bool = True


class NotificationPreferencesUpdate(BaseModel):
    channels: dict[str, str] = Field(default_factory=dict, max_length=50)
    digest_enabled: bool | None = None


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    participant_user_ids: list[str] = Field(min_length=1, max_length=19)
    initial_message: str = Field(min_length=1, max_length=5000)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)


class ConversationParticipantsUpdate(BaseModel):
    # The caller must keep their own id in the list; the service rejects removal.
    participant_user_ids: list[str] = Field(min_length=1, max_length=19)


class ConversationArchive(BaseModel):
    archived: bool


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    # Mentioned users are added to the conversation so they receive the message.
    mentioned_user_ids: list[str] = Field(default_factory=list, max_length=19)


class ConversationRead(BaseModel):
    last_read_message_id: str | None = None


class WebhookSubscriptionCreate(BaseModel):
    url: AnyHttpUrl = Field(max_length=2000)
    events: list[str] = Field(default_factory=list, max_length=50)
    active: bool = True


class WebhookSubscriptionUpdate(BaseModel):
    url: AnyHttpUrl | None = None
    events: list[str] | None = Field(default=None, max_length=50)
    active: bool | None = None


class AdminUserUpdate(BaseModel):
    is_active: StrictBool


class AdminWorkspaceFlags(BaseModel):
    flags: dict[str, StrictBool]


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
