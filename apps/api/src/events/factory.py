from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from src.events.bus import EventBus, EventMetadata
from src.events.inprocess import InProcessEventBus
from src.events.nats import NatsEventBus
from src.settings import settings

logger = logging.getLogger(__name__)

WorkflowHandler = Callable[[dict, EventMetadata], Awaitable[None]]


def build_event_bus() -> EventBus:
    if settings.event_bus_driver.value == "nats":
        return NatsEventBus(settings.nats_url)
    return InProcessEventBus()


class WorkflowRegistry:
    """Registers event subjects → workflow handlers and wires them to a bus.

    Workflows are plain callables receiving (payload, metadata); the registry
    owns the lifecycle so subscribers are always registered before the bus
    starts (important for the in-process bus, which buffers nothing lost).
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._entries: dict[str, tuple[WorkflowHandler, bool]] = {}

    def register(self, subject: str, handler: WorkflowHandler, *, fanout: bool = False) -> None:
        if subject in self._entries:
            raise ValueError(f"duplicate workflow for subject {subject}")
        self._entries[subject] = (handler, fanout)

    @property
    def subjects(self) -> list[str]:
        return list(self._entries)

    async def wire(self) -> None:
        for subject, (handler, fanout) in self._entries.items():
            await self._bus.subscribe(subject, handler, fanout=fanout)
            logger.info("wired workflow for %s (fanout=%s)", subject, fanout)

    async def start(self) -> None:
        await self._bus.start()

    async def stop(self) -> None:
        await self._bus.stop()
