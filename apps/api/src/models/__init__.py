from src.models.api_key import ApiKey
from src.models.audit import AuditLogEntry
from src.models.conversation import (
    Conversation,
    ConversationParticipant,
    Message,
)
from src.models.core import (
    Invitation,
    Notification,
    NotificationPreference,
)
from src.models.jobs import (
    JobDefinition,
    JobLogEntry,
    JobRun,
)
from src.models.oauth import OAuthAccount
from src.models.secret import StoredSecret
from src.models.two_factor import UserTotpCredential
from src.models.user_profile import UserProfile
from src.models.webhook import WebhookDelivery, WebhookSubscription
from src.models.workspace import (
    AuthToken,
    RefreshToken,
    Role,
    User,
    Workspace,
    WorkspaceMember,
)

__all__ = [
    "ApiKey",
    "AuditLogEntry",
    "Conversation",
    "ConversationParticipant",
    "AuthToken",
    "Invitation",
    "JobDefinition",
    "JobLogEntry",
    "JobRun",
    "Message",
    "Notification",
    "NotificationPreference",
    "OAuthAccount",
    "RefreshToken",
    "Role",
    "StoredSecret",
    "User",
    "UserTotpCredential",
    "UserProfile",
    "WebhookDelivery",
    "WebhookSubscription",
    "Workspace",
    "WorkspaceMember",
]

# Project extension models (update-path seam, see src/extensions.py): importing
# `{module}.models` for each configured extension registers its tables on
# Base.metadata, so Alembic autogenerate and create_all see them with zero
# per-feature edits here.
from src.extensions import load_extension_models as _load_extension_models  # noqa: E402

_load_extension_models()
