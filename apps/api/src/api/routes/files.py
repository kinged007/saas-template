from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, parse_query
from src.api.deps import (
    get_container,
    get_current_user,
    get_current_workspace_id,
    require_permission,
)
from src.core.permissions import FILE_CREATE, FILE_READ
from src.db.session import get_db
from src.services.files import (
    FILE_CACHE_CONTROL,
    FileError,
    FileForbidden,
    FileNotFound,
    FileService,
    FileTooLarge,
    FileTypeRejected,
    file_etag,
)
from src.settings import settings

router = APIRouter(prefix="/files", tags=["files"])


def _service(db: AsyncSession, container) -> FileService:
    return FileService(db, container.storage, settings.storage_max_upload_bytes, container.bus)


@router.post("", status_code=201)
async def upload_file(
    file: UploadFile,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(FILE_CREATE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    limit = settings.storage_max_upload_bytes
    # Read in bounded chunks so an oversize body is rejected without ever
    # buffering all of it; the worst case is the cap plus one chunk.
    chunk_size = 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE, f"file exceeds {limit} bytes"
            ) from None
        chunks.append(chunk)
    content = b"".join(chunks)
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
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from None
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
    _perm: None = Depends(require_permission(FILE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        spec = parse_query(request)
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
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
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _perm: None = Depends(require_permission(FILE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        row, content = await _service(db, container).download(
            workspace_id=workspace_id,
            file_id=file_id,
            user_id=user.id,
            if_none_match=request.headers.get("if-none-match"),
            ip_address=request.client.host if request.client else None,
        )
    except FileForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except FileNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except FileError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    headers = {
        "ETag": file_etag(row),
        # Bytes are immutable once written and workspace-scoped, so they may sit
        # in the caller's cache and revalidate by ETag.
        "Cache-Control": FILE_CACHE_CONTROL,
        # Stored bytes come back under a declared type that upload verified
        # against the file's magic bytes, so forbid re-sniffing and sandbox the
        # response in case it is ever opened as a document instead of an image.
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        # Filenames are sanitized to [A-Za-z0-9._-] on upload, so this cannot
        # inject header parameters.
        "Content-Disposition": f'inline; filename="{row.filename}"',
    }
    if content is None:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=content, media_type=row.content_type, headers=headers)
