"""Project-owned background jobs (demo: one heartbeat).

Specs register on the shared `job_registry` (imported here, owned by the
template) so the scheduler provisions and runs them like template jobs.
Disabled by default so the demo never fires uninvited.
"""

from __future__ import annotations

import logging

from src.jobs.registry import JobContext, JobSpec, job_registry

logger = logging.getLogger(__name__)


@job_registry.register(
    JobSpec(
        key="demo.heartbeat",
        name="Demo heartbeat",
        description="Extension-seam demo: proves project jobs register and provision.",
        scope="global",
        schedule="*/5 * * * *",
        params_schema={
            "message": {
                "type": "string",
                "default": "demo-heartbeat",
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
async def demo_heartbeat(ctx: JobContext) -> None:
    logger.info("[%s] %s", ctx.run_id[:8], ctx.params.get("message", "demo-heartbeat"))
    print(f"demo heartbeat: {ctx.params.get('message', 'demo-heartbeat')}")
