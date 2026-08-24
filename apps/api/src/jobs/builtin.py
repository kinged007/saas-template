"""Built-in scheduled jobs shipped with the framework.

Register more jobs anywhere in service code:

    @job_registry.register(JobSpec(key="myapp.cleanup", ...))
    async def cleanup(ctx: JobContext) -> None:
        ...
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from src.core.dates import ensure_utc, now_utc
from src.jobs.registry import JobContext, JobSpec, job_registry
from src.models.core import Invitation

logger = logging.getLogger(__name__)


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
        name="[Demo] Expire Stale Invitations (Sample)",
        description=(
            "[Sample/Demo] Workspace demo job — scans for pending invitations "
            "past their expiry and marks them 'expired'. Note: invitations are "
            "already rejected on accept when expired, so this is purely a "
            "housekeeping/demo job to showcase scheduling, per-workspace config, "
            "execution history and log capture."
        ),
        scope="workspace",
        schedule="0 3 * * *",
        params_schema={},
        default_enabled=True,
        missed_policy="single",
        timeout_seconds=300,
    )
)
async def expire_stale_invitations(ctx: JobContext) -> None:
    logger.info(
        "[Demo] Starting workspace demo job '%s' (run %s, workspace %s)",
        ctx.job_key,
        ctx.run_id[:8],
        ctx.workspace_id,
    )
    print(f"[Demo] Workspace demo job started — workspace={ctx.workspace_id} run={ctx.run_id[:8]}")
    print("[Demo] Step 1/4 — loading pending invitations...")
    logger.info("[Demo] Step 1/4 — querying pending invitations")
    now = now_utc()
    async with ctx.session() as session:
        result = await session.execute(select(Invitation).where(Invitation.status == "pending"))
        pending = list(result.scalars().all())
        stale = [i for i in pending if ensure_utc(i.expires_at) < now]
        print(f"[Demo] Step 2/4 — found {len(pending)} pending, {len(stale)} stale/expired")
        logger.info("[Demo] Found %d pending invitations, %d stale", len(pending), len(stale))
        if stale:
            print(f"[Demo] Step 3/4 — expiring {len(stale)} stale invitation(s)...")
            logger.info("[Demo] Step 3/4 — expiring %d stale invitation(s)", len(stale))
            for invitation in stale:
                logger.info(
                    "[Demo] Expiring invitation %s (%s) — expired at %s",
                    invitation.id[:8],
                    invitation.email,
                    invitation.expires_at,
                )
                print(f"[Demo]   → expiring {invitation.email} ({invitation.id[:8]}...)")
                invitation.status = "expired"
            await session.commit()
            print(f"[Demo] Step 4/4 — committed {len(stale)} expired invitation(s)")
        else:
            print("[Demo] Step 3/4 — nothing to expire, skipping updates")
            logger.info("[Demo] Nothing to expire — all pending invitations are still valid")
            print("[Demo] Step 4/4 — no changes to commit")
    logger.info("[Demo] Workspace demo job completed — expired %d invitation(s)", len(stale))
    print(f"[Demo] Workspace demo completed — expired {len(stale)} stale invitation(s) ✓")


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
