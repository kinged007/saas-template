"""Contract checks for the email abstraction: console capture + SMTP (mocked)."""

from __future__ import annotations


def _msg(**kwargs):
    from src.email.base import EmailMessage

    base = {
        "to": "invitee@example.com",
        "subject": "You're invited",
        "text_body": "join us",
        "html_body": "<p>join us</p>",
    }
    base.update(kwargs)
    return EmailMessage(**base)


async def test_console_driver_captures_message():
    from src.email.console import ConsoleEmailSender

    sender = ConsoleEmailSender(from_addr="noreply@example.com")
    await sender.send(_msg())
    assert len(sender.outbox) == 1
    captured = sender.outbox[0]
    assert captured.to == "invitee@example.com"
    assert captured.subject == "You're invited"
    assert captured.text_body == "join us"
    assert captured.html_body == "<p>join us</p>"


async def test_invalid_address_raises_send_error():
    import pytest

    from src.email.base import EmailSendError
    from src.email.console import ConsoleEmailSender

    sender = ConsoleEmailSender()
    with pytest.raises(EmailSendError):
        await sender.send(_msg(to="not-an-email"))


async def test_missing_subject_raises_send_error():
    import pytest

    from src.email.base import EmailSendError
    from src.email.console import ConsoleEmailSender

    sender = ConsoleEmailSender()
    with pytest.raises(EmailSendError):
        await sender.send(_msg(subject=""))


async def test_smtp_driver_sends_mime_with_tls_and_login(monkeypatch):
    from src.email.smtp import SmtpConfig, SmtpEmailSender

    calls: dict = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls["host"], calls["port"], calls["timeout"] = host, port, timeout
            calls["tls"] = calls["login"] = calls["sent"] = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            calls["tls"] = True

        def login(self, user, password):
            calls["login"] = (user, password)

        def sendmail(self, sender, recipients, raw):
            calls["sent"] = (sender, recipients, raw)

    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    sender = SmtpEmailSender(
        SmtpConfig(
            host="mail.example.com",
            port=587,
            username="user",
            password="pass",
            use_tls=True,
            from_addr="noreply@example.com",
        )
    )
    await sender.send(_msg())
    assert (calls["host"], calls["port"]) == ("mail.example.com", 587)
    assert calls["tls"] is True
    assert calls["login"] == ("user", "pass")
    from_addr, recipients, raw = calls["sent"]
    assert from_addr == "noreply@example.com"
    assert recipients == ["invitee@example.com"]
    assert "Subject: You're invited" in raw
    assert "join us" in raw
    assert "<p>join us</p>" in raw


async def test_missing_sender_raises_send_error():
    import pytest

    from src.email.base import EmailSendError
    from src.email.smtp import SmtpConfig, SmtpEmailSender

    with pytest.raises(EmailSendError, match="no sender address"):
        await SmtpEmailSender(SmtpConfig()).send(_msg())


def test_factory_smtp_without_from_raises(monkeypatch):
    import pytest

    from src.email.base import EmailDriver
    from src.email.factory import build_email_sender
    from src.settings import settings

    monkeypatch.setattr(settings, "email_driver", EmailDriver.SMTP)
    monkeypatch.setattr(settings, "email_from", "")
    with pytest.raises(ValueError, match="EMAIL_FROM is required"):
        build_email_sender()


async def test_smtp_driver_skips_tls_and_login_without_creds(monkeypatch):
    from src.email.smtp import SmtpConfig, SmtpEmailSender

    calls: dict = {}

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            calls["tls"] = calls["login"] = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            calls["tls"] = True

        def login(self, user, password):
            calls["login"] = True

        def sendmail(self, *args):
            calls["sent"] = True

    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    sender = SmtpEmailSender(SmtpConfig(use_tls=False, from_addr="noreply@example.com"))
    await sender.send(_msg(html_body=None))
    assert calls["tls"] is False
    assert calls["login"] is False
    assert calls["sent"] is True


async def test_smtp_failure_raises_send_error(monkeypatch):
    import smtplib

    import pytest

    from src.email.base import EmailSendError
    from src.email.smtp import SmtpConfig, SmtpEmailSender

    def boom(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    with pytest.raises(EmailSendError):
        await SmtpEmailSender(SmtpConfig(from_addr="noreply@example.com")).send(_msg())


async def test_factory_unknown_driver_raises(monkeypatch):
    import pytest

    from src.email.factory import build_email_sender
    from src.settings import settings

    monkeypatch.setattr(settings, "email_driver", "carrier-pigeon")
    with pytest.raises(ValueError, match="unsupported EMAIL_DRIVER"):
        build_email_sender()


async def test_factory_builds_each_driver(monkeypatch):
    from src.email.base import EmailDriver
    from src.email.console import ConsoleEmailSender
    from src.email.factory import build_email_sender
    from src.email.smtp import SmtpEmailSender
    from src.settings import settings

    monkeypatch.setattr(settings, "email_driver", EmailDriver.CONSOLE)
    assert isinstance(build_email_sender(), ConsoleEmailSender)
    monkeypatch.setattr(settings, "email_driver", EmailDriver.SMTP)
    monkeypatch.setattr(settings, "email_from", "noreply@example.com")
    assert isinstance(build_email_sender(), SmtpEmailSender)


def test_templates_build_valid_messages():
    from src.email import templates

    invite = templates.invitation(
        "invitee@example.com",
        workspace_name="Acme",
        invite_url="https://x/invite/abc",
        invited_by="Ada",
    )
    invite.validate()
    assert "Acme" in invite.subject
    for body in (invite.text_body, invite.html_body or ""):
        assert "Acme" in body and "Ada" in body and "https://x/invite/abc" in body
    reset = templates.password_reset("u@example.com", reset_url="https://x/reset/abc")
    reset.validate()
    assert "https://x/reset/abc" in reset.text_body
