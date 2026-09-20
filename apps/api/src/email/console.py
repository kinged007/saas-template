"""Console/log driver for dev/test only: prints mail and keeps a bounded in-memory outbox."""

from __future__ import annotations

import logging
from collections import deque

from src.email.base import EmailMessage, EmailSender

logger = logging.getLogger(__name__)


class ConsoleEmailSender(EmailSender):
    """Dev driver: logs the message and records it in `outbox`.

    The outbox makes tests assert captures without any I/O.
    Dev/test only: never use in a long-lived production process.
    """

    name = "console"

    def __init__(self, from_addr: str = "") -> None:
        self.from_addr = from_addr
        self.outbox: deque[EmailMessage] = deque(maxlen=100)

    async def send(self, message: EmailMessage) -> None:
        message.validate()
        sender = message.from_addr or self.from_addr
        self.outbox.append(message)
        logger.info("email to=%s subject=%s from=%s", message.to, message.subject, sender)
