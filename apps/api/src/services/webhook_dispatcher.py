"""Background dispatcher for due webhook deliveries (jobs-tick pattern).

A single asyncio loop per process ticks and CAS-claims due deliveries so
exactly one replica attempts each delivery.
"""

from __future__ import annotations

import asyncio
import logging

from src.services.webhooks import dispatch_due
from src.settings import settings

logger = logging.getLogger(__name__)


class WebhookDispatcher:
    def __init__(self, *, tick_seconds: float | None = None, secret_store=None) -> None:
        self._tick_seconds = (
            tick_seconds
            if tick_seconds is not None
            else max(1.0, settings.jobs_scheduler_tick_seconds)
        )
        self._secrets = secret_store
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        if settings.environment == "test":
            logger.info("webhook dispatcher loop disabled in test environment")
            return
        self._task = asyncio.create_task(self._loop(), name="webhook-dispatcher")
        logger.info("webhook dispatcher started (tick=%.1fs)", self._tick_seconds)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("webhook dispatcher stopped")

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._tick_seconds)
            try:
                await self.tick()
            except Exception:
                logger.exception("webhook dispatcher tick failed")

    async def tick(self, **kwargs) -> int:
        return await dispatch_due(secret_store=self._secrets, **kwargs)
