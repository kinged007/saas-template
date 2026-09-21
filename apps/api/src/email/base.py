"""Outbound email contract: message value + sender interface.

The backend (console for dev, SMTP for real delivery) is chosen via
`EMAIL_DRIVER`; callers only depend on `EmailSender` (see `factory`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from enum import StrEnum

from email_validator import EmailNotValidError, validate_email


class EmailDriver(StrEnum):
    CONSOLE = "console"
    SMTP = "smtp"


class EmailSendError(RuntimeError):
    """Raised when a driver cannot deliver a message.

    Callers (workflows) decide retry vs. log; drivers never swallow failures.
    """


@dataclass
class EmailMessage:
    to: str
    subject: str
    text_body: str
    html_body: str | None = None
    from_addr: str = ""

    def validate(self) -> None:
        if not self.to or not self.subject or not self.text_body:
            raise EmailSendError("email needs a recipient, subject, and text body")
        for label, value in (("to", self.to), ("subject", self.subject)):
            if "\n" in value or "\r" in value:
                raise EmailSendError(f"{label} must not contain newlines")
        for label, addr in (("to", self.to), ("from", self.from_addr)):
            if label == "from" and not addr:
                continue
            try:
                validate_email(addr, check_deliverability=False)
            except EmailNotValidError as exc:
                raise EmailSendError(f"invalid {label} address {addr!r}: {exc}") from exc

    def as_mime(self, sender: str) -> MimeMessage:
        mime = MimeMessage()
        mime["From"] = sender
        mime["To"] = self.to
        mime["Subject"] = self.subject
        mime.set_content(self.text_body)
        if self.html_body:
            mime.add_alternative(self.html_body, subtype="html")
        return mime


class EmailSender(ABC):
    """Interface for sending transactional email."""

    name = "base"

    @abstractmethod
    async def send(self, message: EmailMessage) -> None:
        """Deliver one message, raising `EmailSendError` on any failure."""
