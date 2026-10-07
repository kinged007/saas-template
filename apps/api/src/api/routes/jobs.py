"""Scheduled jobs API.

Permission model:
- Workspace-scoped jobs follow the workspace permission system
  (`jobs:read` to read history/config, `jobs:update` to modify or trigger).
- Global jobs are deployment-wide: every `/global*` route requires the
  superuser (SUPERADMIN_EMAIL bootstrap account). Superusers do NOT get an
  automatic bypass for workspace jobs — those stay governed by the
  workspace's roles.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, apply_query, parse_query
from src.api.deps import (
    AuthPrincipal,
    deployment_admin_denied,
    get_container,
    get_current_workspace_id,
    record_key_use,
    require_permission,
    require_superuser,
    resolve_auth_principal,
    resolve_or_deny,
)
from src.core.permissions import JOB_READ, JOB_UPDATE
from src.db.session import get_db
from src.events.publisher import publish_audit
from src.models.jobs import JobDefinition, JobRun, JobTrigger
from src.schemas.api import JobUpdate
from src.services.jobs import (
    JobError,
    JobService,
    ValidationError,
    job_log_to_dict,
    job_run_to_dict,
    job_to_dict,
)
from src.services.workspaces import WorkspaceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

_RUN_SORTABLE = {"scheduled_at", "started_at", "duration_ms", "status"}
_RUN_FILTERABLE = {"status", "trigger"}
# Newest occurrence first, id breaking scheduled_at ties. created_at is not in
# _RUN_SORTABLE, and scheduled_at is not null — see _MEMBER_DEFAULT_ORDER for
# why the tiebreak matters.
_RUN_DEFAULT_ORDER = (JobRun.scheduled_at.desc(), JobRun.id.desc())


async def _admin_definition_or_404(
    definition_id: str,
    db: AsyncSession,
) -> JobDefinition:
    """Fetch a definition by id, or the 404 on a miss.

    No workspace filter, and it applies none. All four callers are `/global*`
    routes behind `Depends(require_superuser)`. This helper authorizes nothing:
    a caller that is not superuser-gated has to authorize the definition it
    gets from here itself.
    """
    definition = await JobService(db).get_definition(definition_id)
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return definition


def _validate_patch(body: JobUpdate) -> None:
    if (
        body.cron_schedule is None
        and body.params is None
        and body.enabled is None
        and body.missed_policy is None
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "no editable fields supplied")


# --------------------------------------------------------------------- global


@router.get("/global")
async def list_global_jobs(
    _=Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
):
    return [job_to_dict(d) for d in await JobService(db).list_definitions(None)]


@router.get("/global/{definition_id}")
async def get_global_job(
    definition_id: str,
    _=Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
):
    return job_to_dict(await _admin_definition_or_404(definition_id, db))


@router.patch("/global/{definition_id}")
async def update_global_job(
    definition_id: str,
    body: JobUpdate,
    request: Request,
    user=Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    _validate_patch(body)
    definition = await _admin_definition_or_404(definition_id, db)
    try:
        updated = await JobService(db, container.bus, container.cipher).update_definition(
            definition,
            cron_schedule=body.cron_schedule,
            params=body.params,
            enabled=body.enabled,
            missed_policy=body.missed_policy,
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    except JobError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await publish_audit(
        container.bus,
        workspace_id=None,
        resource_type="job",
        resource_id=updated.id,
        action="job.updated",
        actor_user_id=user.id,
        details={
            "key": updated.key,
            "scope": "global",
            "enabled": updated.enabled,
            "cron_schedule": updated.cron_schedule,
        },
        ip_address=request.client.host if request.client else None,
    )
    return job_to_dict(updated)


@router.post("/global/{definition_id}/execute", status_code=201)
async def execute_global_job(
    definition_id: str,
    user=Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    """A `/global*` id may name a workspace-owned definition, by design: the
    route resolves with no workspace filter and the superuser gate is the
    authorization. Same as `GET`/`PATCH /jobs/global/{definition_id}`."""
    definition = await _admin_definition_or_404(definition_id, db)
    return await _execute_now(definition, user.id, db, container)


@router.get("/global/{definition_id}/runs")
async def list_global_job_runs(
    request: Request,
    response: Response,
    definition_id: str,
    _=Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
):
    definition = await _admin_definition_or_404(definition_id, db)
    return await _list_runs(request, response, definition, None, db)


# ------------------------------------------------------------------ run detail
# Declared BEFORE the dynamic /{definition_id} routes so "runs" is never
# captured as a definition id.


async def _get_run_or_deny(service: JobService, principal: AuthPrincipal, run_id: str) -> JobRun:
    """`resolve_or_deny` for a run; see there for why a key gets one answer."""
    return await resolve_or_deny(principal, service.get_run(run_id), "run not found")


@router.get("/runs/{run_id}")
async def get_job_run(
    response: Response,
    run_id: str,
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    db: AsyncSession = Depends(get_db),
):
    service = JobService(db)
    run = await _get_run_or_deny(service, principal, run_id)
    await _require_run_access(db, principal, run, response)
    schema = {}
    definition = await service.get_definition(run.definition_id)
    if definition is not None:
        schema = definition.params_schema or {}
    return job_run_to_dict(run, schema=schema)


@router.get("/runs/{run_id}/logs")
async def get_job_run_logs(
    response: Response,
    run_id: str,
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    db: AsyncSession = Depends(get_db),
):
    service = JobService(db)
    run = await _get_run_or_deny(service, principal, run_id)
    await _require_run_access(db, principal, run, response)
    return [job_log_to_dict(e) for e in await service.list_run_logs(run_id)]


async def _require_run_access(
    db: AsyncSession,
    principal: AuthPrincipal,
    run: JobRun,
    response: Response,
) -> None:
    """Global runs are superuser-only; workspace runs need jobs:read there.

    An API key is authorized by its own permission list and stays inside its
    own workspace — never by the creator's role, and never over a global run.
    A key outside the run's workspace gets the same deployment-admin refusal as
    a global run and as a lookup miss, so no pair of those states is readable
    from the answer it gets; a session user who is not a member gets 403. A key
    that passes spends one unit of its usage quota, the same charge
    require_permission makes, and `response` is what makes that charge
    observable (the quota headers) — so callers must thread their own
    Response through, never drop it.
    """
    if run.workspace_id is None:
        if not principal.is_deployment_admin:
            raise deployment_admin_denied(principal)
        return
    if principal.api_key is not None:
        api_key = principal.api_key
        if api_key.workspace_id != run.workspace_id:
            raise deployment_admin_denied(principal)
        if "*" in api_key.permissions or JOB_READ in api_key.permissions:
            await record_key_use(api_key, db, response)
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing permission: {JOB_READ}") from None
    membership = await WorkspaceService(db).get_membership(
        run.workspace_id, principal.user.id, active_only=True
    )
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "you are not a member of this workspace")
    _, role = membership
    if not ("*" in role.permissions or JOB_READ in role.permissions):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing permission: {JOB_READ}")


async def _require_job_access(
    db: AsyncSession,
    principal: AuthPrincipal,
    definition: JobDefinition,
    response: Response,
    *,
    need_edit: bool = False,
) -> None:
    """Unified check: global → superuser, workspace → jobs:read/update.

    A key outside the definition's workspace gets the deployment-admin
    refusal, the same one the global branch and a miss give it; a session user
    who is not a member gets 403. A key inside the workspace that lacks the
    permission is told which one it lacks, and that is deliberately a
    different answer from the deployment-admin refusal: it names the fix
    (mint the key with the permission), it is what `require_permission`
    returns on every other key route, and what it reveals is the existence of a
    definition id inside the key's own workspace — not its contents. A key
    that passes spends one unit of its usage quota through record_key_use, and
    `response` is what makes that charge observable (the quota headers) —
    callers must thread their own Response through, never drop it.
    """
    required = JOB_UPDATE if need_edit else JOB_READ
    if definition.workspace_id is None:
        if not principal.is_deployment_admin:
            raise deployment_admin_denied(principal)
        return
    # workspace-scoped job — check the workspace of the definition, not the header
    if principal.api_key is not None:
        api_key = principal.api_key
        if api_key.workspace_id != definition.workspace_id:
            raise deployment_admin_denied(principal)
        if "*" in api_key.permissions or required in api_key.permissions:
            await record_key_use(api_key, db, response)
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing permission: {required}") from None
    membership = await WorkspaceService(db).get_membership(
        definition.workspace_id, principal.user.id, active_only=True
    )
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "you are not a member of this workspace")
    _, role = membership
    if "*" in role.permissions or required in role.permissions:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing permission: {required}") from None


# ------------------------------------------------------------ workspace-scoped


@router.get("")
async def list_workspace_jobs(
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(JOB_READ)),
    db: AsyncSession = Depends(get_db),
):
    return [job_to_dict(d) for d in await JobService(db).list_definitions(workspace_id)]


@router.get("/{definition_id}")
async def get_job(
    response: Response,
    definition_id: str,
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    db: AsyncSession = Depends(get_db),
):
    definition = await resolve_or_deny(
        principal, JobService(db).get_definition(definition_id), "job not found"
    )
    await _require_job_access(db, principal, definition, response, need_edit=False)
    return job_to_dict(definition)


@router.patch("/{definition_id}")
async def update_job(
    response: Response,
    definition_id: str,
    body: JobUpdate,
    request: Request,
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    _validate_patch(body)
    definition = await resolve_or_deny(
        principal, JobService(db).get_definition(definition_id), "job not found"
    )
    await _require_job_access(db, principal, definition, response, need_edit=True)
    try:
        updated = await JobService(db, container.bus, container.cipher).update_definition(
            definition,
            cron_schedule=body.cron_schedule,
            params=body.params,
            enabled=body.enabled,
            missed_policy=body.missed_policy,
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    except JobError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await publish_audit(
        container.bus,
        workspace_id=updated.workspace_id,
        resource_type="job",
        resource_id=updated.id,
        action="job.updated",
        actor_user_id=principal.user.id,
        details={
            "key": updated.key,
            "enabled": updated.enabled,
            "cron_schedule": updated.cron_schedule,
        },
        ip_address=request.client.host if request.client else None,
    )
    return job_to_dict(updated)


@router.post("/{definition_id}/execute", status_code=201)
async def execute_job(
    response: Response,
    definition_id: str,
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    definition = await resolve_or_deny(
        principal, JobService(db).get_definition(definition_id), "job not found"
    )
    await _require_job_access(db, principal, definition, response, need_edit=True)
    return await _execute_now(definition, principal.user.id, db, container)


@router.get("/{definition_id}/runs")
async def list_job_runs(
    request: Request,
    response: Response,
    definition_id: str,
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    db: AsyncSession = Depends(get_db),
):
    definition = await resolve_or_deny(
        principal, JobService(db).get_definition(definition_id), "job not found"
    )
    await _require_job_access(db, principal, definition, response, need_edit=False)
    return await _list_runs(request, response, definition, definition.workspace_id, db)


# -------------------------------------------------------------------- internal


async def _execute_now(
    definition: JobDefinition,
    actor_user_id: str,
    db: AsyncSession,
    container,
) -> dict:
    try:
        run = await JobService(db, container.bus).create_run(
            definition,
            trigger=JobTrigger.MANUAL,
            actor_user_id=actor_user_id,
        )
    except JobError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    await publish_audit(
        container.bus,
        workspace_id=definition.workspace_id,
        resource_type="job",
        resource_id=definition.id,
        action="job.executed_manually",
        actor_user_id=actor_user_id,
        details={"run_id": run.id},
        ip_address=None,
    )
    logger.info("manual execution of job %s queued (run %s)", definition.key, run.id)
    return job_run_to_dict(run, schema=definition.params_schema or {})


async def _list_runs(
    request: Request,
    response: Response,
    definition: JobDefinition,
    run_workspace_id: str | None,
    db: AsyncSession,
) -> list[dict]:
    """List the runs of `definition`. `run_workspace_id` narrows the result
    to the runs of that workspace — it filters `JobRun` rows and authorizes
    nothing; the caller has already authorized — and resolved — the
    definition, whose params_schema serializes every row."""
    from sqlalchemy import func, select

    definition_id = definition.id
    stmt = select(JobRun).where(JobRun.definition_id == definition_id)
    if run_workspace_id is not None:
        stmt = stmt.where(JobRun.workspace_id == run_workspace_id)
    try:
        spec = parse_query(request)
        stmt = apply_query(stmt, JobRun, spec, sortable=_RUN_SORTABLE, filterable=_RUN_FILTERABLE)
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    if not spec.sort_by:
        stmt = stmt.order_by(*_RUN_DEFAULT_ORDER)
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return [job_run_to_dict(r, schema=definition.params_schema or {}) for r in rows.scalars().all()]
