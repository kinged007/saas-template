"""Console/log driver for dev: prints mail and keeps an in-memory outbox."""

from __future__ import annotations

import logging

from src.email.base import EmailMessage, EmailSender

logger = logging.getLogger(__name__)


class ConsoleEmailSender(EmailSender):
    """Dev driver: logs the message and records it in `outbox`.

    The outbox makes tests assert captures without any I/O.
    """

    name = "console"

    def __init__(self, from_addr: str = "") -> None:
        self.from_addr = from_addr
        self.outbox: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        message.validate()
        sender = message.from_addr or self.from_addr
        self.outbox.append(message)
        logger.info("email to=%s subject=%s from=%s", message.to, message.subject, sender)
