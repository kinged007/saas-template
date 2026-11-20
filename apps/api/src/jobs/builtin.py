"""Built-in scheduled jobs shipped with the framework.

Register more jobs anywhere in service code:

    @job_registry.register(JobSpec(key="myapp.cleanup", ...))
    async def cleanup(ctx: JobContext) -> None:
        ...
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, select, update

from src.core.dates import now_utc
from src.jobs.registry import JobContext, JobSpec, job_registry
from src.models.api_key import ApiKey
from src.models.core import Invitation, Notification, NotificationPreference

logger = logging.getLogger(__name__)

# Invitations are kept as an "expired" status for this many days after their
# expiry before the expiry job purges them outright.
INVITATION_EXPIRED_RETENTION_DAYS = 30


@job_registry.register(
    JobSpec(
        key="system.heartbeat",
        name="System heartbeat",
        description=(
            "Writes a heartbeat log line on schedule. Useful as a smoke test "
            "for the scheduler and as a liveness trail in run history."
        ),
        scope="global",
        schedule="*/5 * * * *",
        params_schema={
            "message": {
                "type": "string",
                "default": "heartbeat",
                "max_length": 200,
                "label": "Message",
                "help": "Text written to the run log on every beat.",
            }
        },
        default_enabled=False,
        missed_policy="single",
        timeout_seconds=60,
    )
)
async def system_heartbeat(ctx: JobContext) -> None:
    logger.info("[%s] %s", ctx.run_id[:8], ctx.params.get("message", "heartbeat"))
    print(f"heartbeat: {ctx.params.get('message', 'heartbeat')}")


@job_registry.register(
    JobSpec(
        key="invitations.expire_stale",
        name="Expire Stale Invitations",
        description=(
            "Scans pending invitations across every workspace and marks the "
            "ones past their expiry as 'expired'. Accepting an expired "
            "invitation is rejected regardless, so this is housekeeping. "
            "Invitations that have been expired for more than "
            f"{INVITATION_EXPIRED_RETENTION_DAYS} days are then deleted."
        ),
        scope="global",
        schedule="0 3 * * *",
        params_schema={},
        default_enabled=True,
        missed_policy="single",
        timeout_seconds=300,
    )
)
async def expire_stale_invitations(ctx: JobContext) -> None:
    logger.info("Starting job '%s' (run %s)", ctx.job_key, ctx.run_id[:8])
    now = now_utc()
    async with ctx.session() as session:
        result = await session.execute(
            select(Invitation).where(Invitation.status == "pending", Invitation.expires_at < now)
        )
        stale = list(result.scalars().all())
        logger.info("Expiring %d stale invitation(s)", len(stale))
        for invitation in stale:
            logger.info(
                "Expiring invitation %s (%s) — expired at %s",
                invitation.id[:8],
                invitation.email,
                invitation.expires_at,
            )
            invitation.status = "expired"
        await session.commit()

        purge_cutoff = now - timedelta(days=INVITATION_EXPIRED_RETENTION_DAYS)
        # The window is measured from expires_at, not from the moment the row was
        # marked expired, so a first run after a long outage purges rows this job
        # never saw in the "expired" state.
        # synchronize_session=False: the rows above are already in this session's
        # identity map, and the default ORM evaluator re-checks the WHERE clause
        # in Python — where SQLite's naive timestamps cannot be compared against
        # the aware purge_cutoff. The delete is the last statement, so nothing
        # reads the stale objects afterwards.
        deleted = await session.execute(
            delete(Invitation).where(
                Invitation.status == "expired",
                Invitation.expires_at < purge_cutoff,
            ),
            execution_options={"synchronize_session": False},
        )
        purged = deleted.rowcount or 0
        await session.commit()
    logger.info("Completed — expired %d invitation(s), purged %d", len(stale), purged)
    print(f"expire stale invitations — expired {len(stale)}, purged {purged}")


@job_registry.register(
    JobSpec(
        key="demo.workspace_report",
        name="[Demo] Workspace Daily Report (Sample)",
        description=(
            "[Sample/Demo] Workspace demo job — one row per workspace, so it "
            "shows how scheduling, per-workspace configuration, execution "
            "history and log capture work. Emits sample log output only; it "
            "writes nothing. The global twin is '[Demo] Global Daily Report'."
        ),
        scope="workspace",
        schedule="0 5 * * *",
        params_schema={
            "message": {
                "type": "string",
                "default": "workspace demo report",
                "max_length": 200,
                "label": "Message",
                "help": "Sample text included in the demo log output.",
            }
        },
        default_enabled=True,
        missed_policy="single",
        timeout_seconds=120,
    )
)
async def demo_workspace_report(ctx: JobContext) -> None:
    logger.info(
        "[Demo] Starting workspace demo job '%s' (run %s, workspace %s)",
        ctx.job_key,
        ctx.run_id[:8],
        ctx.workspace_id,
    )
    msg = ctx.params.get("message", "workspace demo report")
    print(f"[Demo] Workspace demo job started — workspace={ctx.workspace_id} run={ctx.run_id[:8]}")
    print(f"[Demo] Step 1/3 — collecting sample metrics for workspace {ctx.workspace_id}...")
    logger.info("[Demo] Sample metrics collected for workspace %s", ctx.workspace_id)
    print("[Demo] Step 2/3 — generating demo report...")
    logger.warning("[Demo] Step 2/3 — this is a sample warning log line (demo)")
    print("[Demo]   → report message:", msg)
    print("[Demo] Step 3/3 — finalizing (no data written — demo only)")
    logger.info("[Demo] Workspace demo job completed successfully ✓")
    print("[Demo] Workspace demo completed ✓")


async def _digest_unsub_url(session, user_id: str) -> str:
    """Unsubscribe URL for the digest (token on the sentinel row)."""
    from src.services.notifications import DIGEST_TYPE, unsubscribe_url_for
    from src.settings import settings

    result = await session.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.type == DIGEST_TYPE,
        )
    )
    pref = result.scalar_one_or_none()
    if pref is None:
        pref = NotificationPreference(user_id=user_id, type=DIGEST_TYPE)
        session.add(pref)
    token = pref.ensure_token()
    await session.commit()
    return unsubscribe_url_for(token, "all", settings.frontend_url)


@job_registry.register(
    JobSpec(
        key="notifications.daily_digest",
        name="Daily notification digest",
        description=(
            "Emails one summary per user with digest enabled, listing their "
            "unread non-conversation notifications. Per-user opt-in gates "
            "sending; unconfigured email fails closed (skipped with a log)."
        ),
        scope="global",
        schedule="0 7 * * *",
        params_schema={},
        default_enabled=True,
        missed_policy="single",
        timeout_seconds=300,
    )
)
async def notifications_daily_digest(ctx: JobContext) -> None:
    from src.email.factory import send_email
    from src.email.templates import digest_email
    from src.models.workspace import User
    from src.services.notifications import DIGEST_EXCLUDED_TYPES, DIGEST_TYPE

    logger.info("digest starting (run %s)", ctx.run_id[:8])
    sent = 0
    async with ctx.session() as session:
        opted = (
            (
                await session.execute(
                    select(NotificationPreference.user_id).where(
                        NotificationPreference.type == DIGEST_TYPE,
                        NotificationPreference.digest_enabled.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        for user_id in opted:
            user = await session.get(User, user_id)
            if user is None or not user.is_active or not user.email:
                continue
            unread = (
                (
                    await session.execute(
                        select(Notification)
                        .where(
                            Notification.user_id == user_id,
                            Notification.acknowledged_at.is_(None),
                            Notification.type.not_in(DIGEST_EXCLUDED_TYPES),
                        )
                        .order_by(Notification.created_at.desc())
                        .limit(50)
                    )
                )
                .scalars()
                .all()
            )
            if not unread:
                continue
            items = [{"title": n.title, "body": n.body} for n in unread]
            unsub = await _digest_unsub_url(session, user_id)
            ok = await send_email(digest_email(user.email, items=items, unsubscribe_url=unsub))
            if ok:
                sent += 1
    logger.info("digest completed — %d email(s) sent", sent)
    print(f"digest completed — {sent} email(s) sent")


@job_registry.register(
    JobSpec(
        key="system.retention_cleanup",
        name="Retention cleanup",
        description=(
            "Deletes aged operational rows: job runs+logs past the log cutoff, "
            "acknowledged notifications past the notification cutoff, and audit "
            "entries past the audit cutoff (audit is kept forever by default)."
        ),
        scope="global",
        schedule="0 4 * * *",
        params_schema={},
        default_enabled=True,
        missed_policy="single",
        timeout_seconds=600,
    )
)
async def retention_cleanup(ctx: JobContext) -> None:
    from datetime import timedelta

    from src.models.audit import AuditLogEntry
    from src.models.core import Notification
    from src.models.jobs import JobLogEntry, JobRun
    from src.settings import settings

    now = now_utc()
    async with ctx.session() as session:
        runs_removed = 0
        run_cutoff = now - timedelta(days=settings.jobs_log_retention_days)
        if settings.jobs_log_retention_days > 0:
            stale = (
                (await session.execute(select(JobRun.id).where(JobRun.created_at < run_cutoff)))
                .scalars()
                .all()
            )
            if stale:
                await session.execute(delete(JobLogEntry).where(JobLogEntry.run_id.in_(stale)))
                await session.execute(delete(JobRun).where(JobRun.id.in_(stale)))
                runs_removed = len(stale)
        notifs_removed = 0
        if settings.notifications_retention_days > 0:
            notif_cutoff = now - timedelta(days=settings.notifications_retention_days)
            result = await session.execute(
                delete(Notification).where(
                    Notification.acknowledged_at.is_not(None),
                    Notification.created_at < notif_cutoff,
                )
            )
            notifs_removed = result.rowcount or 0
        audit_removed = 0
        if settings.audit_log_retention_days > 0:
            audit_cutoff = now - timedelta(days=settings.audit_log_retention_days)
            result = await session.execute(
                delete(AuditLogEntry).where(AuditLogEntry.created_at < audit_cutoff)
            )
            audit_removed = result.rowcount or 0
        await session.commit()
    logger.info(
        "retention cleanup — %d run(s), %d notification(s), %d audit entr(ies) removed",
        runs_removed,
        notifs_removed,
        audit_removed,
    )
    print(
        f"retention cleanup — {runs_removed} run(s), "
        f"{notifs_removed} notification(s), {audit_removed} audit entr(ies) removed"
    )


@job_registry.register(
    JobSpec(
        key="apikeys.cleanup",
        name="API key expiry cleanup",
        description=(
            "Revokes API keys whose expires_at has passed and hard-deletes keys "
            "revoked more than the retention window ago. Expired keys already "
            "fail authentication immediately, so revoking them here keeps the "
            "stored state honest rather than gating access."
        ),
        scope="global",
        schedule="0 5 * * *",
        params_schema={},
        default_enabled=True,
        missed_policy="single",
        timeout_seconds=300,
    )
)
async def api_key_cleanup(ctx: JobContext) -> None:
    from datetime import timedelta

    from src.events.publisher import publish_audit, publish_event
    from src.events.subjects import Subjects
    from src.settings import settings

    now = now_utc()
    async with ctx.session() as session:
        # Only the keys that actually expired are read — the id and label
        # columns the audit trail needs — so a large table is never
        # materialized. The mutation itself is a set-based UPDATE.
        expired = (
            (
                await session.execute(
                    select(ApiKey.id, ApiKey.workspace_id, ApiKey.name, ApiKey.key_prefix).where(
                        ApiKey.revoked_at.is_(None),
                        ApiKey.expires_at.is_not(None),
                        ApiKey.expires_at <= now,
                    )
                )
            )
            .tuples()
            .all()
        )
        revoked = 0
        revoked_ids: set[str] = set()
        if expired:
            # `revoked_at IS NULL` is re-asserted: a key the user revoked between the
            # SELECT and this UPDATE keeps its own revoked_at, so its retention clock is
            # not restarted. The returned ids are exactly the rows the audit trail below
            # describes — `rowcount` is -1 on aiosqlite once RETURNING is used, so the
            # count comes from the returned ids.
            result = await session.execute(
                update(ApiKey)
                .where(
                    ApiKey.id.in_([e[0] for e in expired]),
                    ApiKey.revoked_at.is_(None),
                )
                .values(revoked_at=now)
                .execution_options(synchronize_session=False)
                .returning(ApiKey.id)
            )
            revoked_ids = {row[0] for row in result.all()}
            revoked = len(revoked_ids)

        removed = 0
        if settings.api_key_retention_days > 0:
            cutoff = now - timedelta(days=settings.api_key_retention_days)
            # Keys the UPDATE above just revoked carry revoked_at == now, so
            # they never match this cutoff: expiry starts the retention clock,
            # it does not end the key.
            result = await session.execute(delete(ApiKey).where(ApiKey.revoked_at <= cutoff))
            removed = result.rowcount or 0
        await session.commit()

    unpublished: list[str] = []
    for key_id, workspace_id, name, key_prefix in expired:
        if key_id not in revoked_ids:
            continue
        try:
            await publish_event(
                ctx.bus,
                Subjects.APIKEY_REVOKED,
                {
                    "apikey_id": key_id,
                    "workspace_id": workspace_id,
                    "name": name,
                    "key_prefix": key_prefix,
                    "revoked_by_user_id": None,
                },
            )
            await publish_audit(
                ctx.bus,
                workspace_id=workspace_id,
                resource_type="apikey",
                resource_id=key_id,
                action="apikey.revoked",
                actor_user_id=None,
                details={"name": name, "key_prefix": key_prefix, "reason": "expired"},
            )
        except Exception:
            # The commit is not transactional with the bus, so a failed publish leaves a
            # revoked key with no event and no audit entry. Record it and keep going; the
            # run fails below with the count of what was lost.
            # ponytail: the gap is permanent — nothing retries a FAILED run and the key
            # now carries revoked_at, so the next run's SELECT will never select it again.
            # Repair is manual. Upgrade path: a backfill job re-publishing audit entries
            # for keys revoked with reason "expired" that have no audit row.
            log = logger.exception if len(unpublished) == 0 else logger.warning
            log("api key cleanup — audit publish failed for key %s", key_id)
            unpublished.append(key_id)

    logger.info(
        "api key cleanup — %d key(s) revoked as expired, %d key(s) deleted",
        revoked,
        removed,
    )
    print(f"api key cleanup — {revoked} key(s) revoked as expired, {removed} key(s) deleted")
    if unpublished:
        # Cap the id list: job_runs.error is unbounded Text and a bus outage during a
        # large cleanup would otherwise write one id per revoked key into the row.
        listed = unpublished[:10]
        more = len(unpublished) - len(listed)
        raise RuntimeError(
            f"api key cleanup — {revoked} key(s) revoked as expired, but the event or audit "
            f"entry was not published for {len(unpublished)} of them: {', '.join(listed)}"
            f"{f' (+{more} more)' if more else ''}"
        )


@job_registry.register(
    JobSpec(
        key="demo.global_daily_report",
        name="[Demo] Global Daily Report (Sample)",
        description=(
            "[Sample/Demo] Global demo job — visible only to superadmins. "
            "Runs daily (02:00 UTC) and emits sample log output to demonstrate "
            "scheduling, execution history and log capture. Does not modify any "
            "real data."
        ),
        scope="global",
        schedule="0 2 * * *",
        params_schema={
            "message": {
                "type": "string",
                "default": "global demo report",
                "max_length": 200,
                "label": "Message",
                "help": "Sample text included in the demo log output.",
            }
        },
        default_enabled=True,
        missed_policy="single",
        timeout_seconds=120,
    )
)
async def demo_global_daily_report(ctx: JobContext) -> None:
    logger.info(
        "[Demo] Starting global demo job '%s' (run %s)",
        ctx.job_key,
        ctx.run_id[:8],
    )
    msg = ctx.params.get("message", "global demo report")
    print(f"[Demo] Global demo job started — run={ctx.run_id[:8]} message={msg!r}")
    print("[Demo] Step 1/3 — collecting sample metrics...")
    logger.info("[Demo] Step 1/3 — collecting sample metrics")
    print("[Demo]   • workspaces: (demo) 2 sample workspaces")
    print("[Demo]   • users: (demo) 5 sample users")
    logger.info("[Demo] Sample metrics collected — workspaces=2 users=5")
    print("[Demo] Step 2/3 — generating demo report...")
    logger.warning("[Demo] Step 2/3 — this is a sample warning log line (demo)")
    print("[Demo]   → report message:", ctx.params.get("message", "global demo report"))
    print("[Demo] Step 3/3 — finalizing (no data written — demo only)")
    logger.info("[Demo] Global demo job completed successfully ✓")
    print("[Demo] Global demo completed ✓")
