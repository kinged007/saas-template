"""Workspace cascade registry: every workspace-scoped table (coverage registry).

Template convention: each new table with a non-nullable `workspace_id`
column gets a WORKSPACE_CASCADE entry here; `test_cascade_registry_covers_all`
fails CI otherwise. `delete_workspace` loops this registry instead of
hand-written deletes; parent tables (Conversation, JobRun, JobDefinition)
are deleted last in `delete_workspace`, after their children.
AuditLogEntry is the only exempt workspace-scoped
table (append-only compliance trail — nothing ever deletes audit rows).
"""

from __future__ import annotations

from src.models.api_key import ApiKey
from src.models.audit import AuditLogEntry
from src.models.conversation import (
    Conversation,
    ConversationParticipant,
    Message,
)
from src.models.core import Invitation, Notification
from src.models.file_object import FileObject
from src.models.jobs import JobDefinition, JobLogEntry, JobRun
from src.models.secret import StoredSecret
from src.models.webhook import WebhookDelivery, WebhookSubscription
from src.models.workspace import Role, WorkspaceMember

WORKSPACE_CASCADE = (
    ApiKey,
    FileObject,
    Invitation,
    StoredSecret,
    Notification,
    WebhookDelivery,
    WebhookSubscription,
    WorkspaceMember,
    Role,
    Conversation,
    JobRun,
    JobDefinition,
)

CONVERSATION_CHILDREN = (Message, ConversationParticipant)

JOB_RUN_CHILDREN = (JobLogEntry,)

EXEMPT_WORKSPACE_MODELS = frozenset({AuditLogEntry})

__all__ = [
    "CONVERSATION_CHILDREN",
    "EXEMPT_WORKSPACE_MODELS",
    "JOB_RUN_CHILDREN",
    "WORKSPACE_CASCADE",
]
