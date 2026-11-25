"""Project-owned event subscriptions (demo: one `demo.ping` handler).

`register_workflows` receives the same `WorkflowRegistry`, `EventBus`,
connection manager and cipher the template `build_workflows` gets, right
after the template subscriptions are registered.
"""

from __future__ import annotations

import logging
from collections import deque

logger = logging.getLogger(__name__)

DEMO_PING = "demo.ping"

# Payloads observed by the demo handler, in arrival order. Tests publish a
# `demo.ping` event and assert it lands here; production code ignores it.
# Bounded so a long-running process cannot grow memory with event volume
# (`deque.append` is atomic, safe under concurrent handler invocations).
received: deque = deque(maxlen=100)


def register_workflows(registry, bus, connection_manager=None, cipher=None) -> None:
    async def on_demo_ping(payload: dict, metadata) -> None:
        received.append(payload)
        logger.info("demo.ping received (correlation_id=%s)", metadata.correlation_id)

    registry.register(DEMO_PING, on_demo_ping)
