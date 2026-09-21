"""Webhook dispatch loop: retries due deliveries with backoff.

Same shape as the job scheduler (`src.jobs.scheduler`): a per-process
asyncio loop ticks every few seconds and asks `dispatch_due` to CAS-claim
due deliveries (exactly one replica attempts each delivery) and POST them.
"""

from __future__ import annotations

import asyncio
import logging

from src.db.session import SessionFactory
from src.services.webhooks import dispatch_due
from src.settings import settings

logger = logging.getLogger(__name__)


class WebhookDispatcher:
    def __init__(self, *, tick_seconds: float = 15.0, secret_store=None) -> None:
        self._tick_seconds = max(1.0, tick_seconds)
        self._secret_store = secret_store
        self._task: asyncio.Task | None = None

    def _store(self):
        if self._secret_store is not None:
            return self._secret_store
        from src.container import Container  # deferred: avoids import cycle at module load

        try:
            import src.main as main_module

            return main_module.app.state.container.secret_store
        except Exception:
            return Container().secret_store

    async def start(self) -> None:
        if self._task is not None:
            return
        if settings.environment == "test":
            # Tests drive `dispatch_due()` explicitly; the background loop
            # would only add sqlite write contention around fixture teardown.
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
        # Resolve the secret store lazily: at lifespan time the app container
        # exists, so deliveries sign with the same store the API writes to.
        store = self._store()
        while True:
            await asyncio.sleep(self._tick_seconds)
            try:
                async with SessionFactory() as session:
                    await dispatch_due(session, store)
            except Exception:
                logger.exception("webhook dispatcher tick failed")

    async def tick(self, limit: int = 50) -> int:
        """One dispatch pass (used by tests and the background loop)."""
        async with SessionFactory() as session:
            return await dispatch_due(session, self._store(), limit=limit)
