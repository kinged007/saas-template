"""SMTP driver: stdlib `smtplib`, blocking socket off the event loop."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from dataclasses import dataclass

from src.email.base import EmailMessage, EmailSender, EmailSendError

logger = logging.getLogger(__name__)


@dataclass
class SmtpConfig:
    host: str = "localhost"
    port: int = 1025
    username: str = ""
    password: str = ""
    use_tls: bool = True
    timeout_s: float = 10.0
    from_addr: str = ""


class SmtpEmailSender(EmailSender):
    """Real delivery over SMTP. Unit-testable by patching `smtplib.SMTP`."""

    name = "smtp"

    def __init__(self, config: SmtpConfig) -> None:
        self.config = config

    async def send(self, message: EmailMessage) -> None:
        message.validate()
        sender = message.from_addr or self.config.from_addr
        if not sender:
            raise EmailSendError("no sender address: set EMAIL_FROM or from_addr")
        try:
            mime = message.as_mime(sender)
            await asyncio.to_thread(self._deliver, sender, message.to, mime.as_string())
        except EmailSendError:
            raise
        except Exception as exc:
            raise EmailSendError(f"smtp send failed: {exc}") from exc

    def _deliver(self, sender: str, recipient: str, raw: str) -> None:
        cfg = self.config
        try:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout_s) as smtp:
                smtp.ehlo()
                if cfg.use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                if cfg.username and cfg.password:
                    smtp.login(cfg.username, cfg.password)
                elif cfg.username or cfg.password:
                    logger.warning("SMTP credentials incomplete; sending unauthenticated")
                smtp.sendmail(sender, [recipient], raw)
        except Exception as exc:
            raise EmailSendError(f"smtp send failed: {exc}") from exc
