from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, parse_query
from src.api.deps import (
    get_container,
    get_current_user,
    get_current_workspace_id,
    require_key_permission,
    resolve_auth_principal,
)
from src.core.permissions import MESSAGE_READ, MESSAGE_SEND
from src.db.session import get_db
from src.schemas.api import ConversationArchive, ConversationCreate, ConversationRead, ConversationUpdate, MessageCreate
from src.services.conversations import ConversationError, ConversationForbidden, ConversationNotFound, ConversationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])

_CONVERSATION_SORTABLE = {"last_message_at", "created_at", "title"}
_MESSAGE_SORTABLE = {"created_at"}


@router.get("/unread-count")
async def unread_count(
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(MESSAGE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    # principal check already done via require_key_permission for API keys; session users always pass
    service = ConversationService(db, container.bus)
    try:
        data = await service.get_unread_counts(workspace_id=workspace_id, user_id=user.id)
    except ConversationForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    return data


@router.get("")
async def list_conversations(
    request: Request,
    response: Response,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(MESSAGE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    # Parse pagination/sorting via generic parser
    try:
        spec = parse_query(request)
        # Validate sort fields
        for s in spec.sort_by:
            if s not in _CONVERSATION_SORTABLE and s != "":
                raise InvalidQuery(f"sort on unknown field: {s}")
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None

    # archived filter: support ?archived=true|false, default false; also support filter syntax archived=true
    q_params = request.query_params
    archived_raw = q_params.get("archived")
    # Also check spec.filters for archived (simple-rest style)
    for fname, op, value in spec.filters:
        if fname == "archived":
            archived_raw = value
    if archived_raw is None:
        archived = False
    else:
        lv = archived_raw.strip().lower()
        if lv in ("true", "1"):
            archived = True
        elif lv in ("false", "0"):
            archived = False
        elif lv in ("null", "none", ""):
            archived = None
        else:
            # parse_query already validated filter op eq, but treat as bool
            archived = lv == "true"

    q = q_params.get("q")
    if q is None:
        for fname, op, value in spec.filters:
            if fname == "q":
                q = value

    sort_by = spec.sort_by[0] if spec.sort_by else "last_message_at"
    sort_order = spec.sort_order[0] if spec.sort_order else "desc"

    service = ConversationService(db, container.bus)
    try:
        items, total = await service.list_conversations(
            workspace_id=workspace_id,
            user_id=user.id,
            archived=archived,
            q=q,
            offset=spec.offset,
            limit=spec.limit,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ConversationForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except ConversationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    response.headers["X-Total-Count"] = str(total)
    return items


@router.post("", status_code=201)
async def create_conversation(
    body: ConversationCreate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(MESSAGE_SEND)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = ConversationService(db, container.bus)
    try:
        conv, msg = await service.create_conversation(
            workspace_id=workspace_id,
            creator=user,
            title=body.title,
            participant_user_ids=body.participant_user_ids,
            participant_agent_ids=body.participant_agent_ids,
            entity_type=body.entity_type,
            initial_message=body.initial_message,
            ip_address=request.client.host if request.client else None,
        )
    except ConversationForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except ConversationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    # Return conversation with first_message embedded for client convenience; dataProvider will read top-level id.
    conv["first_message"] = msg
    return conv


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(MESSAGE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = ConversationService(db, container.bus)
    try:
        data = await service.get_conversation(
            workspace_id=workspace_id, conversation_id=conversation_id, user_id=user.id
        )
    except ConversationForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return data


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    body: ConversationUpdate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(MESSAGE_SEND)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    if body.title is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "title is required")
    service = ConversationService(db, container.bus)
    try:
        data = await service.rename(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            title=body.title,
            actor_user_id=user.id,
            actor_type="user",
            ip_address=request.client.host if request.client else None,
        )
    except ConversationForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except ConversationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return data


@router.patch("/{conversation_id}/read")
async def mark_read(
    conversation_id: str,
    body: ConversationRead,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(MESSAGE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = ConversationService(db, container.bus)
    try:
        data = await service.mark_read(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            user_id=user.id,
            last_read_message_id=body.last_read_message_id,
        )
    except ConversationForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except ConversationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return data


@router.patch("/{conversation_id}/unread")
async def mark_unread(
    conversation_id: str,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(MESSAGE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = ConversationService(db, container.bus)
    try:
        data = await service.mark_unread(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            user_id=user.id,
        )
    except ConversationForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except ConversationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return data


@router.patch("/{conversation_id}/archive")
async def archive_conversation(
    conversation_id: str,
    body: ConversationArchive,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(MESSAGE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = ConversationService(db, container.bus)
    try:
        data = await service.set_archived(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            user_id=user.id,
            archived=body.archived,
        )
    except ConversationForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except ConversationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return data


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    request: Request,
    response: Response,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(MESSAGE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        spec = parse_query(request)
        for s in spec.sort_by:
            if s not in _MESSAGE_SORTABLE:
                raise InvalidQuery(f"sort on unknown field: {s}")
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    sort_by = spec.sort_by[0] if spec.sort_by else "created_at"
    sort_order = spec.sort_order[0] if spec.sort_order else "asc"
    service = ConversationService(db, container.bus)
    try:
        items, total = await service.list_messages(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            user_id=user.id,
            offset=spec.offset,
            limit=spec.limit,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ConversationForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except ConversationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    response.headers["X-Total-Count"] = str(total)
    return items


@router.get("/{conversation_id}/session-history")
async def get_session_history(
    conversation_id: str,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(MESSAGE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    """Lazy enrichment: tool calls / thinking steps for agent messages, collapsed by default.

    Handler-routed — conversation.entity_type picks the handler (chat today).
    Verifies caller is conversation participant before revealing session artifacts.
    """
    from sqlalchemy import select as _select

    from src.agents.handlers.chat import ChatHandler
    from src.models.conversation import Conversation, ConversationParticipant

    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    # caller must be participant
    res = await db.execute(
        _select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.participant_type == "user",
            ConversationParticipant.participant_id == user.id,
        )
    )
    if res.scalar_one_or_none() is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "you are not a participant of this conversation")
    # find agent participants for history aggregation (return all per-agent steps)
    res2 = await db.execute(
        _select(ConversationParticipant.participant_id).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.participant_type == "agent",
        )
    )
    agent_ids = [r[0] for r in res2.all()]
    if not agent_ids:
        return []
    # aggregate across agents (chat: one per conversation but keep generic)
    handler = ChatHandler(bus=container.bus, secret_store=container.secret_store)
    all_steps: list[dict] = []
    for aid in agent_ids:
        from src.agents.handlers.base import AgentRequest as _Req

        req = _Req(
            entity_type=getattr(conv, "entity_type", "chat") or "chat",
            conversation_id=conversation_id,
            message_id="",
            agent_id=aid,
            workspace_id=workspace_id,
            triggering_user_id=user.id,
        )
        try:
            steps = await handler.retrieve_session_history(req)
            all_steps.extend(steps)
        except Exception:
            logger.warning("session history fetch failed for agent %s", aid, exc_info=True)
    return all_steps


@router.post("/{conversation_id}/messages", status_code=201)
async def send_message(
    conversation_id: str,
    body: MessageCreate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(MESSAGE_SEND)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = ConversationService(db, container.bus)
    try:
        msg = await service.send_message(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            sender=user,
            body=body.body,
            ip_address=request.client.host if request.client else None,
        )
    except ConversationForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except ConversationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return msg
