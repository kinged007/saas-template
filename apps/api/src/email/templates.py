"""Minimal transactional templates: plain f-strings, no Jinja.

ponytail: ceiling is ~2 simple templates; adopt Jinja when templates need
loops/conditionals or shared layouts.
"""

from __future__ import annotations

from html import escape

from src.email.base import EmailMessage


def _brand(inner_html: str) -> str:
    """Branded mail layout: logo header plus a sent-by footer.

    The logo resolves against FRONTEND_URL (where /logo.svg is served), so
    self-hosted deployments brand mail automatically. Read at call time so
    tests can monkeypatch settings without reimporting this module.
    """
    from src.settings import settings

    base = (settings.frontend_url or "").rstrip("/")
    # Scheme-check the admin-controlled base: escape() stops attribute
    # breakout but a javascript: base would survive into the src. Fall back
    # to the relative logo path for anything that is not http(s).
    logo = f"{base}/logo.svg" if base.startswith(("http://", "https://")) else "/logo.svg"
    name = settings.app_name or "SaaS Template"
    return (
        '<div style="font-family:sans-serif;max-width:560px;margin:0 auto;">'
        f'<p><img src="{escape(logo, quote=True)}" alt="{escape(name)}" '
        'width="120" style="max-width:120px;"></p>'
        f"{inner_html}"
        f'<p style="color:#888888;font-size:12px;">Sent by {escape(name)}.</p>'
        "</div>"
    )


def invitation(
    to: str,
    *,
    workspace_name: str,
    invite_url: str,
    invited_by: str = "",
) -> EmailMessage:
    inviter = invited_by.strip()
    lead = (
        f"{inviter} has invited you" if inviter else "You've been invited"
    ) + f" to join the {workspace_name} workspace."
    text = (
        f"Hi there,\n\n{lead}\n\nAccept your invitation:\n{invite_url}\n\n"
        "If you weren't expecting this email, you can safely ignore it.\n"
    )
    if inviter:
        lead_html = (
            f"<strong>{escape(inviter)}</strong> has invited you to join "
            f"the <strong>{escape(workspace_name)}</strong> workspace."
        )
    else:
        lead_html = (
            f"You've been invited to join the <strong>{escape(workspace_name)}</strong> workspace."
        )
    html = (
        f"<p>Hi there,</p><p>{lead_html}</p>"
        f'<p><a href="{escape(invite_url, quote=True)}">Accept your invitation</a></p>'
        "<p>If you weren't expecting this email, you can safely ignore it.</p>"
    )
    return EmailMessage(
        to=to,
        subject=f"You're invited to {workspace_name}",
        text_body=text,
        html_body=_brand(html),
    )


def notification_email(
    to: str,
    *,
    title: str,
    body: str | None = None,
    workspace_name: str = "",
    unsubscribe_url: str = "",
) -> EmailMessage:
    lead = f"New notification from {workspace_name}:" if workspace_name else "New notification:"
    text = f"Hi there,\n\n{lead}\n{title}\n"
    if body:
        text += f"\n{body}\n"
    if unsubscribe_url:
        text += f"\nUnsubscribe:\n{unsubscribe_url}\n"
    head_html = (
        escape(lead)
        if not workspace_name
        else (f"New notification from <strong>{escape(workspace_name)}</strong>:")
    )
    html = f"<p>Hi there,</p><p>{head_html}<br><strong>{escape(title)}</strong></p>"
    if body:
        html += f"<p>{escape(body)}</p>"
    if unsubscribe_url:
        html += (
            f'<p><a href="{escape(unsubscribe_url, quote=True)}">Unsubscribe</a> '
            "from these emails.</p>"
        )
    return EmailMessage(
        to=to,
        subject=title[:200],
        text_body=text,
        html_body=_brand(html),
    )


def digest_email(
    to: str,
    *,
    items: list[dict],
    unsubscribe_url: str = "",
) -> EmailMessage:
    lines = [f"{i.get('title', 'Notification')}" for i in items]
    detail = [
        f"- {t}" + (f" — {i.get('body')}" if i.get("body") else "")
        for t, i in zip(lines, items, strict=True)
    ]
    text = (
        f"Hi there,\n\nYou have {len(items)} unread notification(s):\n\n" + "\n".join(detail) + "\n"
    )
    if unsubscribe_url:
        text += f"\nUnsubscribe:\n{unsubscribe_url}\n"
    html_items = "".join(
        f"<li><strong>{escape(str(i.get('title', 'Notification')))}</strong>"
        + (f" — {escape(str(i.get('body')))}" if i.get("body") else "")
        + "</li>"
        for i in items
    )
    html = (
        f"<p>Hi there,</p><p>You have {len(items)} unread notification(s):</p><ul>{html_items}</ul>"
    )
    if unsubscribe_url:
        html += (
            f'<p><a href="{escape(unsubscribe_url, quote=True)}">Unsubscribe</a> '
            "from digest emails.</p>"
        )
    return EmailMessage(
        to=to,
        subject=f"Your daily digest: {len(items)} unread notification(s)",
        text_body=text,
        html_body=_brand(html),
    )


def email_verification(to: str, *, verify_url: str) -> EmailMessage:
    return EmailMessage(
        to=to,
        subject="Verify your email",
        text_body=(
            "Hi there,\n\nThanks for registering — please confirm this email address.\n\n"
            f"Verify your email:\n{verify_url}\n\n"
            "If you didn't create this account, you can safely ignore this email.\n"
        ),
        html_body=_brand(
            "<p>Hi there,</p>"
            "<p>Thanks for registering — please confirm this email address.</p>"
            f'<p><a href="{escape(verify_url, quote=True)}">Verify your email</a></p>'
            "<p>If you didn't create this account, you can safely ignore this email.</p>"
        ),
    )


def password_reset(to: str, *, reset_url: str) -> EmailMessage:
    return EmailMessage(
        to=to,
        subject="Reset your password",
        text_body=(
            "Hi there,\n\nWe received a request to reset your password.\n\n"
            f"Choose a new password:\n{reset_url}\n\n"
            "If you didn't request this, you can safely ignore this email; "
            "your password won't change.\n"
        ),
        html_body=_brand(
            "<p>Hi there,</p>"
            "<p>We received a request to reset your password.</p>"
            f'<p><a href="{escape(reset_url, quote=True)}">Choose a new password</a></p>'
            "<p>If you didn't request this, you can safely ignore this email; "
            "your password won't change.</p>"
        ),
    )
