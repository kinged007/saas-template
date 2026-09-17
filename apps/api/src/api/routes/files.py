from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import parse_query
from src.api.deps import (
    get_container,
    get_current_user,
    get_current_workspace_id,
    require_key_permission,
    require_permission,
    resolve_auth_principal,
)
from src.core.permissions import MESSAGE_READ, MESSAGE_SEND
from src.db.session import get_db
from src.services.files import (
    FileError,
    FileForbidden,
    FileNotFound,
    FileService,
    FileTooLarge,
    FileTypeRejected,
)
from src.settings import settings
from src.storage.factory import build_storage

router = APIRouter(prefix="/files", tags=["files"])


def _service(db: AsyncSession, container) -> FileService:
    storage = getattr(container, "storage", None) or build_storage()
    return FileService(db, storage, settings.storage_max_upload_bytes, container.bus)


@router.post("", status_code=201)
async def upload_file(
    file: UploadFile,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_permission(MESSAGE_SEND)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    content = await file.read()
    try:
        return await _service(db, container).upload(
            workspace_id=workspace_id,
            owner_user_id=user.id,
            filename=file.filename or "upload",
            content_type=file.content_type,
            content=content,
            ip_address=request.client.host if request.client else None,
        )
    except FileForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except FileTooLarge as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from None
    except FileTypeRejected as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from None
    except FileError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None


@router.get("")
async def list_files(
    request: Request,
    response: Response,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _key: None = Depends(require_key_permission(MESSAGE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    spec = parse_query(request)
    try:
        items, total = await _service(db, container).list_files(
            workspace_id=workspace_id, user_id=user.id, offset=spec.offset, limit=spec.limit
        )
    except FileForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    response.headers["X-Total-Count"] = str(total)
    return items


@router.get("/{file_id}")
async def download_file(
    file_id: str,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _key: None = Depends(require_key_permission(MESSAGE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        row, content = await _service(db, container).download(
            workspace_id=workspace_id, file_id=file_id, user_id=user.id
        )
    except FileForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except FileNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except FileError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return Response(content=content, media_type=row.content_type)
