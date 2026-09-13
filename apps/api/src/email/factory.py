"""Email sender factory: selects the backend from `EMAIL_DRIVER`.

Console (dev default) logs and captures; SMTP delivers for real. Unknown
drivers raise `ValueError`, same shape as the secret-store factory.
"""

from __future__ import annotations

from src.email.base import EmailDriver, EmailSender
from src.email.console import ConsoleEmailSender
from src.email.smtp import SmtpConfig, SmtpEmailSender

_EMAIL_DRIVERS: dict[str, str] = {
    EmailDriver.CONSOLE.value: "console",
    EmailDriver.SMTP.value: "smtp",
}


def build_email_sender() -> EmailSender:
    from src.settings import settings

    driver = str(settings.email_driver)
    if driver == EmailDriver.SMTP.value:
        return SmtpEmailSender(
            SmtpConfig(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                password=settings.smtp_password,
                use_tls=settings.smtp_use_tls,
                timeout_s=settings.smtp_timeout_s,
                from_addr=settings.email_from,
            )
        )
    if driver == EmailDriver.CONSOLE.value:
        return ConsoleEmailSender(from_addr=settings.email_from)
    raise ValueError(f"unsupported EMAIL_DRIVER: {driver!r} (available: {sorted(_EMAIL_DRIVERS)})")
