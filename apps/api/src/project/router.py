"""Project-owned endpoints (demo: workspace-scoped widgets)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_workspace_id, get_db, require_permission
from src.project.models import DemoWidget
from src.project.permissions import DEMO_CREATE, DEMO_READ
from src.project.settings import project_settings

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoWidgetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


def _widget_dict(widget: DemoWidget) -> dict:
    return {"id": widget.id, "name": widget.name}


@router.get(
    "/widgets",
    dependencies=[Depends(require_permission(DEMO_READ))],
)
async def list_demo_widgets(
    db: AsyncSession = Depends(get_db),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict:
    rows = (
        (
            await db.execute(
                select(DemoWidget)
                .where(DemoWidget.workspace_id == workspace_id)
                .order_by(DemoWidget.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        "message": project_settings.demo_message,
        "widgets": [_widget_dict(w) for w in rows],
    }


@router.post(
    "/widgets",
    status_code=201,
    dependencies=[Depends(require_permission(DEMO_CREATE))],
)
async def create_demo_widget(
    body: DemoWidgetCreate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str = Depends(get_current_workspace_id),
) -> dict:
    widget = DemoWidget(workspace_id=workspace_id, name=body.name)
    db.add(widget)
    await db.commit()
    await db.refresh(widget)
    return _widget_dict(widget)
