"""Background scheduler for due job definitions.

A single asyncio loop per process ticks every few seconds and asks the
JobService to claim due occurrences (atomically) and enqueue executions over
the event bus. Runs entirely in the background — HTTP requests never wait on
it. Housekeeping (history pruning, abandoned-run recovery) runs hourly.
"""

from __future__ import annotations

import asyncio
import logging

from src.db.session import SessionFactory
from src.events.bus import EventBus
from src.services.jobs import JobService
from src.settings import settings

logger = logging.getLogger(__name__)

HOUSEKEEPING_INTERVAL_SECONDS = 3600.0


class JobScheduler:
    def __init__(self, *, tick_seconds: float | None = None, bus: EventBus | None = None) -> None:
        self._tick_seconds = (
            tick_seconds
            if tick_seconds is not None
            else max(1.0, settings.jobs_scheduler_tick_seconds)
        )
        self._bus = bus
        self._task: asyncio.Task | None = None
        self._last_housekeeping = 0.0

    async def start(self) -> None:
        if self._task is not None:
            return
        if settings.environment == "test":
            # Tests drive `tick()` explicitly; the background loop would only
            # add sqlite write contention around fixture teardown.
            logger.info("job scheduler loop disabled in test environment")
            return
        self._task = asyncio.create_task(self._loop(), name="job-scheduler")
        logger.info("job scheduler started (tick=%.1fs)", self._tick_seconds)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("job scheduler stopped")

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._tick_seconds)
            try:
                await self.tick()
            except Exception:
                logger.exception("job scheduler tick failed")

    async def tick(self) -> int:
        """One scheduling pass. Returns the number of runs scheduled."""
        async with SessionFactory() as session:
            scheduled = await JobService(session, self._bus).schedule_due()
        await self._housekeeping_if_due()
        return scheduled

    async def _housekeeping_if_due(self) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        if now - self._last_housekeeping < HOUSEKEEPING_INTERVAL_SECONDS:
            return
        self._last_housekeeping = now
        async with SessionFactory() as session:
            service = JobService(session)
            await service.fail_stale_runs(
                older_than_seconds=max(
                    HOUSEKEEPING_INTERVAL_SECONDS, 2 * settings.jobs_default_timeout_seconds
                )
            )
            await service.prune_history(retention=settings.jobs_run_retention)
